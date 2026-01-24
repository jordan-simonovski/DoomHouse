# DOOMHouse Current Context

## Current State
**Status**: Working Prototype  
**Last Updated**: 2026-01-12

The DOOMHouse project is functional with a complete raycasting engine implemented in ClickHouse SQL. The Python client successfully renders frames and handles user input.

## Recent Changes
- **WAD Data Integration**: Refactored the engine to load raw Doom WAD data into ClickHouse tables (`wad_vertexes`, `wad_sectors`, etc.) and resolve geometry using SQL (`bsp_resolved`).
- **Level Listing**: Added logic to `src/DOOMHouse.py` to automatically find and print all levels (e.g., E1M1-E1M9) found in the WAD file during initialization.
- **Fixed Render Pipeline**: Resolved an issue where `rendered_frame` was empty due to Materialized View chaining and inference problems.
- **Optimized `render_view.sql`**: 
    - Moved `player_state` to the top-level `FROM` clause to ensure MV triggers correctly.
    - Removed erroneous `GROUP BY x` at the end of the MV.
    - Implemented a `LEFT JOIN` with a full range of 640 columns to ensure consistent frame size (640x480).
- **Fixed `create_dictionaries.sql`**: Removed syntax errors caused by trailing semicolons/comments.
- **Debugged Pipeline**: Created `debug_pipeline.py` to trace data flow from `player_input_raw` to `rendered_frame_post_processed`.

Based on Notes.md, the project evolved through several iterations:
1. **Plans**: Initial planning (Gemini 3.0)
2. **clickhouse v1**: First implementation (Gemini 3.0 Flash)
3. **clickhouse v2**: Refinement (Opus 4.5)
4. **clickhouse v3**: Current version (Gemini 3.0 Pro)
5. **Materialized View Migration**: Moved rendering logic to a ClickHouse Materialized View for better performance and cleaner client code.
6. **Tkinter Migration**: Refactored the GUI from OpenCV to Tkinter to support real-time, non-queued keyboard input with proper key-up/down tracking.
7. **Packed Binary Framebuffer**: Replaced PPM string output with `Array(UInt32)` for faster data transfer.
8. **Post-Processing Pipeline**: Added a second Materialized View for SWAR-based smoothing/blurring.
9. **Dictionary Optimization**: Moved map and textures to ClickHouse Dictionaries with split R/G/B channels.
10. **Theme Support**: Added interactive theme switching (Classic/Dungeon) and high-res texture support (512x512).
11. **WAD Data Structures**: Moved "source of truth" for level geometry to ClickHouse tables, enabling SQL-side geometry resolution.


Latest implementation includes:
- **Table-based Input/Output**: Client inserts to `player_input` and selects from `rendered_frame_post_processed`.
- **SQL-side Rendering**: All raycasting and pixel generation happens in the `render_materialized` view.
- **SWAR Post-Processing**: SIMD-style blur implemented in SQL.
- **Slide-and-Collide**: Improved collision detection in SQL.
- **Distance Lookups**: Pre-computed floor/ceiling distances for performance.
- **WAD-based Geometry**: Raw WAD lumps stored in DB and resolved to BSP segments via SQL.

## Current Work Focus
Maintaining documentation and exploring further SQL-side optimizations.

## Known Issues to Address
1. **Texture Size Limits**: 1024x1024 textures cause memory/dictionary issues.

## Potential Next Steps
- [x] Make texture path relative to project root
- [ ] Add textures to version control or document how to obtain them
- [x] Create requirements.txt for Python dependencies
- [x] Add README.md with setup instructions
- [x] Expand README.md with Architecture and Optimizations details
- [x] Implement WAD data loading and SQL-side geometry resolution
- [ ] Consider continuous render loop option for smoother movement
- [ ] Explore ClickHouseDB optimizations for better frame rates
- [ ] Add more wall texture types for visual variety

## Environment Notes
- Project developed on macOS
- ClickHouse server expected on localhost:8123
- Python 3 with tkinter required
- Original SQL ported from CedarDB implementation
