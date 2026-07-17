# DOOMHouse — Streaming Edition

<p align="center">
  <img src="images/splash.png" width="400" alt="Splash">
</p>

A Doom-style 3D engine whose entire renderer runs **inside ClickHouse** — and, in
this fork, streams finished frames to the client with ClickHouse's new continuous
queries (`SELECT ... STREAM`). The Python client only sends input and blits
pixels; raycasting, texturing, shading, and the post-process blur are all SQL.

> Forked from [arniwesth/DoomHouse](https://github.com/arniwesth/DoomHouse), which
> established the pure-SQL raycasting engine. This fork rebuilds the render loop
> around **ClickHouse streaming queries** and concurrent rendering. What that took
> — and the surprises along the way — is written up in
> [docs/streaming.md](docs/streaming.md).

## Why streaming?

The original engine used a request/response loop: insert an input, then block on
`SELECT`s to pull the frame back. This fork instead treats each rendered frame as
an event on a live stream:

- **Concurrent rendering.** The screen is split into four quarters, each rendered
  by its own query dispatched in parallel, so rendering uses many cores instead of
  the single thread ClickHouse gives a sequential materialized-view chain. This is
  where most of the speed-up comes from.
- **`SELECT ... STREAM` continuous queries** (ClickHouse 26.6+) tail the frame
  tables and *push* each new frame to the client the moment it lands — no polling,
  no per-frame query setup, and the pixel parsing happens off the UI thread.
- **A `frame_id` barrier** keeps the four independently-streamed quarters coherent,
  so frames never tear across the seam.

Frame rate is very machine- and display-dependent, so rather than quote numbers
here: the [three engines](#side-by-side-three-engines-two-variables) below each
show a live fps counter — run them on your hardware and compare. The
[full engineering log](docs/streaming.md) covers what the migration took,
including every silent failure mode of a two-week-old ClickHouse feature.

## Demo

Same ClickHouse, same hardware — only the render loop differs. (fps read off the
on-screen counter in each clip.)

**Original — sequential materialized-view render (~8fps):**

https://github.com/user-attachments/assets/472ed0dc-9c29-452c-ad20-441c8d4708d4

**Concurrent render, polled delivery (~16fps):**

https://github.com/user-attachments/assets/1b4dc733-1c1d-4006-bdb6-5d6f789dea75

**This fork — concurrent render + streaming delivery (~31fps):**

https://github.com/user-attachments/assets/689fba6e-d25c-4782-907c-8107ed144657

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** for Python (`curl -LsSf https://astral.sh/uv/install.sh | sh`, or `brew install uv`)
- **Docker** (for the bundled ClickHouse), or **ClickHouse Server 26.6+** reachable some other way

Streaming queries (`SELECT ... STREAM` + `enable_streaming_queries`) require
**ClickHouse 26.6 or later**.

## Quickstart

```bash
make db-up        # start ClickHouse 26.6+ (localhost only)
make streaming    # run this fork (uv installs deps on first run)
```

`make db-down` stops ClickHouse. The compose file runs the server with a
passwordless `default` user bound to `127.0.0.1` — deliberate, because the game's
texture/map dictionaries self-connect as `default` (see
[docs/streaming.md](docs/streaming.md) for the why). Don't expose that port to an
untrusted network.

### Configuration

Connection settings live in `.env` (defaults target the bundled ClickHouse):

```env
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASS=
```

### Dependencies

Managed by uv via `pyproject.toml` / `uv.lock` — the `make` run targets handle the
virtualenv, so there's no separate install step (use `make sync` to pre-install).
The project uses:

- `clickhouse-connect` — ClickHouse client (streaming via `raw_stream`)
- `Pillow` — texture loading and image blitting
- `numpy` — fast parsing of streamed pixel rows
- `python-dotenv` — `.env` configuration

## Controls

| Key | Action |
|-----|--------|
| ↑ / W | Move Forward |
| ↓ / S | Move Backward |
| ← / A | Rotate Left |
| → / D | Rotate Right |
| T     | Switch theme |
| Esc | Exit |

## Side-by-side: three engines, two variables

The repo ships three engines so you can separate *what actually made it faster*
from *what streaming adds*. They differ along two independent axes — how rendering
is triggered, and how frames are delivered — each on its own ClickHouse database
so all three run at once:

| Engine | Render | Delivery | fps\* |
|---|---|---|---|
| [`non-streaming/`](non-streaming/) (original fork) | sequential materialized views (~100ms, one thread) | polled `SELECT` | ~8 |
| [`polling/`](polling/) | **concurrent** query templates (~31ms) | polled `SELECT` (UI thread deserializes) | ~16 |
| `src/` (this fork) | **concurrent** query templates (~20ms) | `SELECT ... STREAM` (parsed off-thread) | ~31 |

\* Read off the on-screen counter in the [demo clips](#demo) above; your hardware
will differ, so run them and read your own counter.

Each change roughly **doubles** the frame rate, for a different reason:

- **non-streaming → polling** (rendering only): the original runs the four
  quarter materialized views sequentially on one thread (~100ms/frame);
  dispatching four independent render queries concurrently uses the idle cores
  and cuts that to ~31ms.
- **polling → streaming** (delivery only): request/response deserializes each
  frame's pixel arrays synchronously on the UI thread and stalls it; streaming
  pushes frames that are parsed off-thread and painted async, so the UI thread
  keeps moving.

See [`polling/README.md`](polling/README.md) and
[docs/streaming.md](docs/streaming.md) for the full breakdown.

```bash
make non-streaming   # original: sequential MVs, polled
make polling         # concurrent render, polled
make streaming       # concurrent render, streamed (this fork)
```

## End-to-end test (headless)

Exercises the full streaming pipeline without opening a window:

```bash
make db-up
make test
```

## Screen recording

[![DoomHouse](images/yt_thumbnail.jpeg)](https://youtu.be/us5Vp_spnP8)

## Themes

| Theme 1 | Theme 2 |
|---------|---------|
| <img src="images/theme1.png" width="400" alt="Theme 1"> | <img src="images/theme2.png" width="400" alt="Theme 2"> |

## Acknowledgments

- **[arniwesth/DoomHouse](https://github.com/arniwesth/DoomHouse)** — the original
  pure-SQL DoomHouse engine this fork is built on.

Also inspired by:
- [DoomQL: Rendering Doom in a Database](https://cedardb.com/blog/doomql/)
- [DuckDB-Doom: Rendering Doom in DuckDB](https://www.hey.earth/posts/duckdb-doom)
- [Interactive Visualization and Analytics on ADS-B Flight Data with ClickHouse](https://clickhouse.com/blog/interactive-visualization-analytics-adsb-flight-data-with-clickhouse)
- [Writing a retro 3D FPS engine from scratch](https://medium.com/@btco_code/writing-a-retro-3d-fps-engine-from-scratch-b2a9723e6b06)
