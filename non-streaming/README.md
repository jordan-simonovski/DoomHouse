# Non-streaming engine (for comparison)

This is the **original** DoomHouse render loop — request/response, driven by
materialized views — kept here so you can run it side-by-side with the streaming
fork and compare frame rates on your own hardware.

## How it differs from the streaming version

| | non-streaming (this dir) | streaming (`src/`) |
|---|---|---|
| Rendering | materialized views fire **sequentially** on one INSERT (~100ms) | 4 quarter renders dispatched **concurrently** (~20ms) |
| Frame delivery | client fires 4 blocking `SELECT`s per frame | 4 long-lived `SELECT ... STREAM` tails push frames |
| Frame table engine | `Memory` | `MergeTree` (required by `STREAM`) |
| fps\* | ~8 | ~31 |

\* From the demo clips in the [main README](../README.md#demo); read the
on-screen counter, and expect different numbers on your hardware.

The renderer SQL (raycasting + blur) is identical; only *how work is triggered and
frames are delivered* changes. For the middle step that isolates each variable —
concurrent render with plain polling (~16fps) — see [`../polling`](../polling).
The full story is in [../docs/streaming.md](../docs/streaming.md).

## Running

It uses a **separate ClickHouse database (`doomhouse_ns`)**, so it can run at the
same time as the streaming version against the same server without clashing:

```bash
make db-up            # from the repo root — same ClickHouse for all engines
make non-streaming
```

Run them side by side to compare:

```bash
make non-streaming   # window titled "... (NON-STREAMING) ..."
make polling         # concurrent render, polled
make streaming       # the streaming fork
```

Both read textures/images from the repo root, so launch from the repo root (not
from inside this directory). Controls are the same as the main README.
