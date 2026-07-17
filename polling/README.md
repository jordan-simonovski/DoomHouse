# Polling engine (concurrent render, request/response delivery)

This is the **fair like-for-like** control for the streaming version. It runs the
*exact same* concurrent render engine as [`../src`](../src) — the four per-quarter
render+blur query templates in [`SQL/frame_render.sql`](SQL/frame_render.sql),
dispatched four at a time — but delivers frames with plain request/response
`SELECT`s instead of `SELECT ... STREAM`. It runs on its own `doomhouse_poll`
database, so it can run alongside the other two.

## The point: isolate what streaming actually buys

There are three engines in this repo, differing along two independent axes —
*how rendering is triggered* and *how frames are delivered*:

| Engine | Render | Delivery | fps\* |
|---|---|---|---|
| [`non-streaming/`](../non-streaming) (original fork) | sequential materialized views (~100ms) | polled `SELECT` | ~8 |
| `polling/` (this dir) | **concurrent** query templates (~31ms) | polled `SELECT` | ~16 |
| [`src/`](../src) (streaming) | **concurrent** query templates (~20ms) | `SELECT ... STREAM` | ~31 |

\* Read off the on-screen counter in the recordings in
[`../screen_recording/`](../screen_recording/); your hardware will differ.

Each step roughly doubles the frame rate, for a *different* reason:

- **non-streaming → polling** changes only the *render*. The original runs the
  four quarter materialized views sequentially on a single thread (~100ms/frame);
  dispatching four independent render queries concurrently uses the idle cores and
  drops that to ~31ms. ~8 → ~16 fps.
- **polling → src** changes only the *delivery*. This variant deserializes each
  frame's four pixel arrays (~78k `UInt32` each) synchronously on the UI thread
  and blocks it; streaming pushes frames that are parsed off-thread (via
  `raw_stream` + numpy) and painted async, so the UI thread never stalls on
  deserialization. ~16 → ~31 fps.

So both concurrency *and* streaming are real throughput wins here — streaming
isn't just cosmetic smoothing; moving delivery off the UI thread roughly doubles
fps again. The full write-up is in [../docs/streaming.md](../docs/streaming.md).

## Running

```bash
make db-up          # from repo root — same ClickHouse for all three
make polling
```

Run all three at once to compare on your hardware:

```bash
make non-streaming   # original
make polling         # concurrent render, polled
make streaming       # concurrent render, streamed
```

Launch from the repo root (textures/images are read via relative paths). Controls
are the same as the main README.
