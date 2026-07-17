# Non-streaming engine (for comparison)

This is the **original** DoomHouse render loop — request/response, driven by
materialized views — kept here so you can run it side-by-side with the streaming
fork and compare frame rates on your own hardware.

## How it differs from the streaming version

| | non-streaming (this dir) | streaming (`src/`) |
|---|---|---|
| Frame delivery | client fires 4 blocking `SELECT`s per frame | 4 long-lived `SELECT ... STREAM` tails push frames |
| Rendering | materialized views fire **sequentially** on one INSERT | 4 quarter renders dispatched **concurrently** |
| Frame table engine | `Memory` | `MergeTree` (required by `STREAM`) |
| Typical frame rate | ~6-8 fps | ~30 fps |

The renderer SQL (raycasting + blur) is identical; only *how work is triggered and
frames are delivered* changes. The full story is in
[../docs/streaming.md](../docs/streaming.md).

## Running

It uses a **separate ClickHouse database (`doomhouse_ns`)**, so it can run at the
same time as the streaming version against the same server without clashing:

```bash
docker compose up -d          # from the repo root — same ClickHouse for both
uv run non-streaming/DOOMHouse.py
```

Run both at once to compare:

```bash
uv run non-streaming/DOOMHouse.py   # window titled "... (NON-STREAMING) ..."
uv run src/DOOMHouse.py             # the streaming fork
```

Both read textures/images from the repo root, so launch from the repo root (not
from inside this directory). Controls are the same as the main README.
