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

- **`SELECT ... STREAM` continuous queries** (ClickHouse 26.6+) tail the frame
  tables and *push* each new frame to the client the moment it lands — no polling,
  no per-frame query setup.
- **Concurrent rendering.** The screen is split into four quarters, each rendered
  by its own query dispatched in parallel, so rendering uses many cores instead of
  one. This is the bulk of the speed-up.
- **A `frame_id` barrier** keeps the four independently-streamed quarters coherent,
  so frames never tear across the seam.

On an 18-core machine this took the engine from **~8fps to ~30fps**. See the
[side-by-side comparison](#side-by-side-non-streaming-vs-streaming) to feel the
difference, and [docs/streaming.md](docs/streaming.md) for the full engineering log
(including every silent failure mode of a two-week-old ClickHouse feature).

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** for Python (`curl -LsSf https://astral.sh/uv/install.sh | sh`, or `brew install uv`)
- **Docker** (for the bundled ClickHouse), or **ClickHouse Server 26.6+** reachable some other way

Streaming queries (`SELECT ... STREAM` + `enable_streaming_queries`) require
**ClickHouse 26.6 or later**.

## Quickstart

```bash
docker compose up -d          # start ClickHouse 26.6+ (localhost only)
uv run src/DOOMHouse.py        # uv installs deps on first run
```

`docker compose down` stops ClickHouse. The compose file runs the server with a
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

Managed by uv via `pyproject.toml` / `uv.lock` — `uv run` handles the virtualenv,
so there's no separate install step (use `uv sync` to pre-install). The project
uses:

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

## Side-by-side: non-streaming vs streaming

`non-streaming/` contains the original request/response engine, wired to the *same*
ClickHouse (a separate `doomhouse_ns` database, so both can run at once). Run them
together to compare frame rates on your hardware:

```bash
docker compose up -d
uv run non-streaming/DOOMHouse.py   # original polling + materialized-view engine
uv run src/DOOMHouse.py             # this fork: streaming + concurrent render
```

See [non-streaming/README.md](non-streaming/README.md) for details.

## End-to-end test (headless)

Exercises the full streaming pipeline without opening a window:

```bash
docker compose up -d
uv run test_e2e.py
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
