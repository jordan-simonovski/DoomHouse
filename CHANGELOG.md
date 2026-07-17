# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-17
### Added
- Streaming render loop using ClickHouse continuous queries (`SELECT ... STREAM`, requires ClickHouse 26.6+).
- Concurrent per-quarter rendering (combined render+blur query templates dispatched from the client) — ~8fps to ~30fps.
- `frame_id` barrier so independently-streamed quarters never tear.
- `docker-compose.yml` for a local ClickHouse; migrated dependency management to uv (`pyproject.toml`/`uv.lock`).
- `non-streaming/` copy of the original engine (on a separate `doomhouse_ns` database) for side-by-side comparison.
- `docs/streaming.md` engineering writeup and `test_e2e.py` headless pipeline test.

### Changed
- Frame tables moved from `Memory` to `MergeTree` with a TTL (required by `STREAM`).
- Streamed pixel rows parsed with numpy.

### Removed
- Materialized-view render/post-process pipeline and the `player_input` table (superseded by client-dispatched render templates).

## [0.1.2] - 2026-01-17
### Added
 - Rendering process has been split into 4 parallel queries for improved performance.
 - ClickHouse Version Check.

## [0.1.1] - 2026-01-11
### Added
- Materialized View rendering pipeline.
- SWAR post-processing.
- Tkinter-based client.

## [0.1.0] - 2025-12-20
### Added
- Basic raycasting in SQL.
- Project initialization and planning.
- Prototype implementations.
