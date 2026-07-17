# Streaming DOOMHouse: rendering frames with ClickHouse continuous queries

This fork replaces DOOMHouse's request/response render loop with **continuous
queries** — ClickHouse's `SELECT ... STREAM` feature (26.6+) — so rendered frames
are *pushed* to the client as soon as they exist, and reworks the render pipeline
so the four screen quarters render **concurrently**. Net result on an 18-core
box: **~8fps → ~31fps**, with no frame tearing.

This document is the engineering log: the architecture, what's stored in the
database, what gets streamed, and every hiccup worth knowing. It doubles as
blog-post source material.

## Background: how DOOMHouse rendered before

DOOMHouse renders a Doom-style 3D view entirely in SQL; the Python client only
captures input and blits pixels. The original loop was pure request/response:

1. On a keypress, the client `INSERT`s one row into `player_input`.
2. That insert fires a chain of materialized views (raycasting → texturing →
   shading → a Gaussian-blur post-process) that write the finished frame into
   four `rendered_frame_post_processed_{1..4}` tables. The frame is split into
   four horizontal quarters so rendering can parallelise.
3. The client fires **four parallel blocking `SELECT`s**, one per quarter, each
   returning the whole quarter as a single `Array(UInt32)` row, then stitches
   them into a 640×480 image and paints.

Every displayed frame cost a full round-trip. Worse, as the performance section
shows, the render itself ran single-threaded at ~125ms/frame.

## The final architecture

```
                per frame, 4 concurrent threads (one per quarter)
   input ──► [ INSERT INTO bus_N SELECT <render+blur, input inlined> ] ──► bus_N (MergeTree)
                                                                              │
                                                          one long-lived STREAM per quarter
                                                                              ▼
   paint loop ◄── frame barrier (composite only when all 4 quarters share frame_id) ◄── 4 STREAM tails
```

- **No materialized views, no `player_input` table.** The raycaster + blur for
  each quarter live in a **query template** (`src/SQL/frame_render.sql`) with
  `@@placeholders@@` for the current player input. Each frame, the client fills
  the placeholders and dispatches four `INSERT INTO bus_N SELECT ...` **concurrently**
  (one client/thread per quarter). ClickHouse runs the four renders in parallel
  across cores.
- **Four MergeTree "bus" tables** (`rendered_frame_post_processed_{1..4}`) hold
  the rendered quarters. These are the only persistent objects.
- **Four long-lived `STREAM` queries** (one per quarter) tail the bus tables. The
  moment a render insert lands, ClickHouse pushes the row to the client.
- **A paint loop** on the Tk main thread composites the four latest quarters and
  draws — but only when all four agree on `frame_id` (the tearing barrier).

## What's stored in a DB row, and what gets streamed

**Bus table schema** (`src/SQL/rendered_frame_post_processed_table.sql`), one per quarter:

```sql
CREATE TABLE doomhouse.rendered_frame_post_processed_N (
    frame_id  UInt64,          -- which frame this quarter belongs to
    pos_x     Float32,         -- player position after collision (fed back to client)
    pos_y     Float32,
    image_data Array(UInt32),  -- the quarter's pixels, one UInt32 per pixel
    ts        DateTime DEFAULT now()   -- for the TTL that bounds table size
)
ENGINE = MergeTree ORDER BY tuple()
TTL ts + INTERVAL 10 SECOND
SETTINGS ttl_only_drop_parts = 1, merge_with_ttl_timeout = 1;
```

So **one row = one quarter of one frame**. A full 640×480 frame is four rows
(one per bus table), written by four concurrent inserts.

The heavy column is `image_data`: an `Array(UInt32)` of the quarter's pixels in
row-major order. A quarter is 640 wide and ~121 rows tall (120 visible + 1
overlap row the blur needs for a seamless seam), so ~77–78k entries per row.
Each `UInt32` packs one pixel as `0x00BBGGRR` — in little-endian memory that's
the byte sequence `R, G, B, 0`, i.e. exactly PIL's `RGBX` raw layout, so the
client can hand the raw bytes straight to `Image.frombytes(...,"raw","RGBX")`
with no per-pixel work.

**What the render insert writes.** Each frame the client runs, per quarter:

```sql
INSERT INTO doomhouse.rendered_frame_post_processed_N (frame_id, pos_x, pos_y, image_data)
SELECT @@frame_id@@ AS frame_id, pos_x, pos_y, image_data
FROM ( <blur> FROM ( <raycaster with input inlined as literals> ) )
```

`frame_id` is inlined as a literal (the client's frame counter). `pos_x/pos_y`
come out of the raycaster's collision step (the *validated* position, which the
client reads back so walls actually stop you). `image_data` is the blurred
quarter.

**What gets streamed back.** Each quarter's worker holds one query open:

```sql
SELECT frame_id, pos_x, pos_y, arrayStringConcat(image_data, ',')
FROM doomhouse.rendered_frame_post_processed_N STREAM
SETTINGS enable_streaming_queries = 1, stream_flush_interval_ms = 16
```

That yields, per new frame, a single tab-separated text row:

```
<frame_id>\t<pos_x>\t<pos_y>\t<c0,c1,c2,...,cN>
```

where the last field is the pixel array joined with commas (see the format
hiccup below for why it's text and not binary). The client parses `frame_id`,
`pos_x`, `pos_y`, and turns the comma list into a `numpy.uint32` array. It buffers
the latest quarter per stream keyed by `frame_id`; when all four quarters share a
`frame_id`, it slices off the overlap rows, concatenates the four arrays, and
blits the 640×480 image.

## Performance: how ~8fps became ~31fps

Measured on an 18-core machine, fps read off the on-screen counter in the
recordings in [`../screen_recording/`](../screen_recording/). The three engines
isolate the two variables:

| Engine | Render | Delivery | fps |
|---|---|---|---|
| non-streaming (original) | sequential MVs, ~100ms, 1 thread | polled `SELECT` | ~8 |
| polling | concurrent render, ~31ms | polled `SELECT` (UI-thread deserialize) | ~16 |
| streaming | concurrent render, ~20ms | `STREAM`, parsed off-thread | ~31 |

Each change roughly doubles the frame rate — **concurrent rendering** takes
~8 → ~16 (it uses the idle cores), and **streaming delivery** takes ~16 → ~31
(polling stalls the UI thread deserializing each frame's pixel arrays; streaming
parses off-thread and paints async). So streaming is a genuine throughput win
here, not just smoothing — a surprise, since streaming changes *delivery*, not
*compute*. Where the render time itself went:

| Stage | Cost | Note |
|---|---|---|
| Original full render (INSERT firing all MVs) | ~100–125 ms | single-threaded! ~0.6 of 18 cores |
| One quarter's raycast (standalone `SELECT`) | ~15 ms | |
| 4 quarter renders, **serial** | ~64 ms | |
| 4 quarter renders, **concurrent** | **~20 ms** | ~3–4 cores — the unlock |
| Text parse of a full frame's ints (`array`+`map`) | ~31 ms | GIL-bound |
| Text parse with numpy | ~7 ms | |

The key discovery: **the render parallelises beautifully, but ClickHouse runs the
materialized views attached to one INSERT sequentially on a single thread.** So
the original pipeline left 17 of 18 cores idle. `parallel_view_processing=1` did
not help (the real, CPU-bound MV chain stayed at ~113ms).

Getting to concurrent rendering took three architecture changes, each forced by a
measurement:

1. **Collapse the two-hop MV chain into one query.** The chain was
   `player_input → render MV → rendered_frame_N (Memory) → blur MV → bus`. Even
   dispatched as four concurrent inserts it ran at ~225ms on ~1 core — the Memory
   intermediate serialised everything. Folding render+blur into a single
   `INSERT ... SELECT` (no intermediate) dropped four concurrent renders to
   **~20ms**.

2. **Drop the `player_input` table; inline the input as literals.** With the MV
   chain gone, the next bottleneck was, bizarrely, the per-frame input insert:
   four concurrent one-row Memory inserts measured ~100–160ms. Inlining the input
   values directly into each render query removed the insert (and the table)
   entirely.

3. **Parse with numpy.** With rendering at ~20ms, the client became the limit:
   four threads parsing ~78k integers each via `int()` saturated the GIL.
   `numpy.fromstring(sep=',')` is ~4× faster and holds the GIL for less wall-time,
   which unblocks the other stream threads sooner.

Movement is applied per frame, so ~2.4×-ing the frame rate made the player move
~2.4× faster — the movement constants were scaled down to compensate.

## Controlling frame tearing

The four quarters stream independently, so a naive "composite the latest of each"
can stitch quarter 1 of frame N+1 onto quarter 4 of frame N during motion. Two
mechanisms prevent it:

- **`render_busy` gate:** the client never dispatches frame N+1 until all four of
  frame N's inserts have completed, so only one frame is ever in flight.
- **Frame barrier:** every streamed quarter carries its `frame_id`, and the paint
  loop composites only when all four buffered quarters share the same `frame_id`.
  A mismatched quarter is held back rather than drawn. `frame_id` is attached
  cheaply — it's just the inlined literal the render already selects — so it costs
  nothing to carry through.

## The hiccups (the interesting part)

Every one of these was a **silent** failure — the stream connected and simply
delivered nothing — found by testing each layer against a live server, because
the feature is new enough that the Python client docs don't mention `STREAM` yet.

1. **`Memory` tables can't be streamed.** `SELECT ... STREAM` on a `Memory` table
   fails with `Storage Memory doesn't support STREAM (ILLEGAL_STREAM)`. Continuous
   queries need a MergeTree-family engine, so the streamed bus tables are MergeTree.

2. **The 7.5-second flush window.** `stream_flush_interval_ms` defaults to
   **7500ms** — the server batches streamed output on that timer. One frame per
   flush never hits the row-count threshold, so you wait the full 7.5s. We run the
   streams with `stream_flush_interval_ms = 16`.

3. **clickhouse-connect's block reader can't consume a live stream.** The
   `query_row_block_stream` / `query_rows_stream` helpers wrap a native block
   reader that waits for a *complete* block, which a continuous query never
   signals — they yield zero rows even for realistic frames. The low-level
   `raw_stream()` (raw response bytes, like `curl --no-buffer`) works; the client
   parses rows itself.

4. **Binary formats buffer; text formats stream.** `RowBinary`, `Native`,
   `ArrowStream`, `Values`, `Protobuf` all buffer the row payload server-side — a
   single big row never fills the output buffer, so nothing streams (their headers
   flush, the data doesn't). Only row-based text formats (`TSV`, `CSV`,
   `JSONCompactEachRow`) flush a big row as it's written. Hence the pixel array is
   streamed as a comma-joined string via `arrayStringConcat(image_data, ',')`.

5. **Disable compression.** clickhouse-connect compresses responses by default,
   and the compressor buffers until it has enough data — reintroducing the latency
   we're removing. The streaming clients use `compress=False`.

6. **A password breaks the dictionaries.** Unrelated to streaming but painful: the
   latest ClickHouse image disables network access for `default` unless you set a
   password, but the game's texture/map dictionaries use `SOURCE(CLICKHOUSE(...))`,
   which self-connects as `default` with *no* password. Setting a password fails
   dictionary loading with a confusing `AUTHENTICATION_FAILED` that only surfaces
   when the `dictGet`-using views are created. The compose file uses
   `CLICKHOUSE_SKIP_USER_SETUP=1` (passwordless `default`, network enabled) — fine
   for a local dev box, don't expose the port.

7. **`STREAM` replays history before tailing.** With no time filter, a `STREAM`
   query returns all existing rows first, then tails new ones (verified directly).
   DOOMHouse recreates the bus tables at startup so the streams subscribe to empty
   tables; if you point one at a populated table you'll get a history burst first
   (bounded here by the 10s TTL). Add `WHERE ts >= now()` for new-only, like the
   canonical `system.text_log` example.

8. **`parallel_view_processing` didn't help.** The setting that *should* run an
   insert's materialized views concurrently made no difference to the real
   CPU-bound render chain (~113ms either way). Concurrency had to be driven from
   the client instead.

## Bounding table growth

MergeTree is append-only and every frame row is ~300KB, so a play session would
grow the bus tables without bound. Each insert lands as its own part (one row),
so a `TTL ts + INTERVAL 10 SECOND` with `ttl_only_drop_parts = 1` and
`merge_with_ttl_timeout = 1` drops whole parts within a second of expiring while
the live streams keep tailing new inserts. Verified: part count rises then falls
back as old frames age out, and the stream never skips.

## Was it easy?

The *concept* is beautifully simple: change an engine, open a `STREAM`, read the
bytes. The friction was entirely in the plumbing around a two-week-old feature the
client library and docs haven't caught up to, and in discovering that the payoff
of streaming (push delivery) is orthogonal to the thing that actually gated frame
rate (a single-threaded render). Once measured, the fix — render the four quarters
concurrently and get out of the pipeline's way — was straightforward. Every
number in this doc came from a live server, not a guess; with a feature this
fresh, "it connected and returned no error and no data" was most of the debugging.
