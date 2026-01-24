# Technical Implementation Plan: Integrating Doom WAD Data Structures

This plan outlines the refactoring of the SQL rendering engine to natively store and process Doom WAD data structures. Instead of resolving map geometry in Python, we will load raw WAD tables into ClickHouse and perform the geometry resolution (Segs → Linedefs → Sectors) using SQL views.

## 1. Schema Analysis

We will introduce a set of normalized tables to store the raw WAD lumps. This moves the "source of truth" for the level geometry into the database.

### New Raw Tables (`src/SQL/create_source_tables.sql`)

| Table Name | Columns | Description |
|------------|---------|-------------|
| `wad_vertexes` | `id UInt32`, `x Int16`, `y Int16` | Raw vertex coordinates |
| `wad_sectors` | `id UInt32`, `floor_h Int16`, `ceil_h Int16`, `floor_tex String`, `ceil_tex String`, `light UInt8`, `special UInt16`, `tag UInt16` | Sector properties |
| `wad_sidedefs` | `id UInt32`, `x_off Int16`, `y_off Int16`, `upper String`, `lower String`, `middle String`, `sector_id UInt16` | Wall texture & sector links |
| `wad_linedefs` | `id UInt32`, `v1 UInt16`, `v2 UInt16`, `flags Int16`, `special Int16`, `tag Int16`, `front_side Int16`, `back_side Int16` | Line definitions |
| `wad_segs` | `id UInt32`, `v1 UInt16`, `v2 UInt16`, `angle Int16`, `linedef_id UInt16`, `side Int16`, `offset Int16` | BSP Segments (Draw order) |
| `wad_things` | `id UInt32`, `x Int16`, `y Int16`, `angle Int16`, `type Int16`, `options Int16` | Player starts, enemies, items |

### Expanded Resolved Table (`bsp_resolved`)

We will replace or upgrade the existing `bsp_source` table with `bsp_resolved` to include texture and lighting data derived from the raw tables.

| Column | Type | Source |
|--------|------|--------|
| `id` | `UInt32` | `wad_segs.id` |
| `x1`, `y1` | `Float64` | `wad_vertexes` (via `wad_segs.v1`) |
| `x2`, `y2` | `Float64` | `wad_vertexes` (via `wad_segs.v2`) |
| `ceil` | `Float32` | `wad_sectors.ceil_h` |
| `floor` | `Float32` | `wad_sectors.floor_h` |
| `wall_tex` | `String` | `wad_sidedefs.middle` |
| `ceil_tex` | `String` | `wad_sectors.ceil_tex` |
| `floor_tex` | `String` | `wad_sectors.floor_tex` |
| `light` | `UInt8` | `wad_sectors.light` |
| `sector_id` | `UInt16` | `wad_sidedefs.sector_id` |

## 2. View Logic Updates

### Geometry Resolution View (`src/SQL/resolve_geometry.sql`)

We will create a view (or use an `INSERT INTO ... SELECT` statement) to resolve the relationships. This replaces the Python logic in `DOOMHouse.py`.

```sql
SELECT
    s.id,
    v1.x * 0.01 AS x1, v1.y * 0.01 AS y1,
    v2.x * 0.01 AS x2, v2.y * 0.01 AS y2,
    
    -- Resolve Sector Heights
    sec.ceil_h * 0.01 AS ceil,
    sec.floor_h * 0.01 AS floor,
    
    -- Resolve Textures
    sd.middle AS wall_tex,
    sec.ceil_tex AS ceil_tex,
    sec.floor_tex AS floor_tex,
    
    sec.light AS light,
    sec.id AS sector_id

FROM doomhouse.wad_segs AS s
LEFT JOIN doomhouse.wad_vertexes AS v1 ON s.v1 = v1.id
LEFT JOIN doomhouse.wad_vertexes AS v2 ON s.v2 = v2.id
LEFT JOIN doomhouse.wad_linedefs AS l ON s.linedef_id = l.id
-- Determine correct sidedef (front=0, back=1)
LEFT JOIN doomhouse.wad_sidedefs AS sd ON sd.id = if(s.side = 0, l.front_side, l.back_side)
LEFT JOIN doomhouse.wad_sectors AS sec ON sd.sector_id = sec.id
WHERE sd.id != -1 -- Skip invalid sides (though SEGS should always have valid sides)
```

### Render View Updates (`src/SQL/render_view.sql`)

The `render_view.sql` must be updated to:
1.  Use the new `dict_bsp_resolved` (pointing to `bsp_resolved`).
2.  Utilize the new texture and light columns for rendering.

```sql
-- Example snippet update
dictGet('doomhouse.dict_bsp_resolved', 'wall_tex', id) AS w_tex_name,
dictGet('doomhouse.dict_bsp_resolved', 'light', id) AS light_level,
...
-- Use light_level in shading calculation
least(1.0, (light_level / 255.0) * (4.0 / (z_depth + 0.1))) AS w_shade
```

## 3. Data Mapping Strategy

We will modify `src/DOOMHouse.py` to map WAD lumps directly to the new tables.

| Python Object (Lump) | Target Table | Mapping Logic |
|----------------------|--------------|---------------|
| `vertices` (List of tuples) | `wad_vertexes` | `enumerate` -> `id`, `x`, `y` |
| `sectors` (List of dicts) | `wad_sectors` | `enumerate` -> `id`, fields map 1:1 |
| `sidedefs` (List of dicts) | `wad_sidedefs` | `enumerate` -> `id`, fields map 1:1 |
| `linedefs` (List of dicts) | `wad_linedefs` | `enumerate` -> `id`, fields map 1:1 |
| `seg_data` (Raw bytes) | `wad_segs` | Parse struct -> `id`, fields map 1:1 |
| `thing_data` (Raw bytes) | `wad_things` | Parse struct -> `id`, fields map 1:1 |

**Note:** Python will no longer perform the "Resolve SEGS" step (joining vertices/sectors). It will just parse the binary data and insert it.

## 4. Migration Steps

1.  **Backup**: Ensure `Doom1.WAD` is safe.
2.  **Schema Creation**:
    - Execute updated `create_source_tables.sql` to create `wad_*` tables and `bsp_resolved`.
    - Execute updated `create_dictionaries.sql` to create `dict_bsp_resolved`.
3.  **Python Update**:
    - Modify `DOOMHouse.py`:
        - Remove `_initialize_fallback_data` (or update it to populate raw tables).
        - Rewrite `initialize_game_data` to insert into `wad_*` tables.
        - Add a SQL execution step: `INSERT INTO doomhouse.bsp_resolved SELECT ... FROM ...` (The resolution query).
        - Trigger `SYSTEM RELOAD DICTIONARY`.
4.  **Render Engine Update**:
    - Update `render_view.sql` to reference `dict_bsp_resolved`.
    - Update `player_state.sql` to reference `dict_bsp_resolved`.
5.  **Cleanup**: Drop old `bsp_source` and `dict_bsp_segs`.

## 5. Verification

### Test Queries

**1. Verify Sector Resolution**
Check if segments have correct heights (compare with known E1M1 values).
```sql
SELECT id, ceil, floor, wall_tex FROM doomhouse.bsp_resolved LIMIT 5
```

**2. Verify Geometry Integrity**
Ensure coordinates are scaled correctly (should be small floats, e.g., 10.5, not 1050).
```sql
SELECT min(x1), max(x1), min(y1), max(y1) FROM doomhouse.bsp_resolved
```

**3. Visual Verification**
- Run the game.
- Check if walls appear at correct positions.
- Check if "light levels" (if implemented) affect shading.
