# Plan: Use WAD Textures in Render Pipeline

## Objective
Replace the current placeholder textures and simple shading with actual textures extracted from the Doom WAD file. This involves extracting texture data (Flats and Wall Textures) in Python, storing them in ClickHouse, and updating the SQL rendering pipeline to perform texture lookups.

## 1. Data Extraction (Python)
Extend `src/DOOMHouse.py` (or create a new module `src/wad_loader.py`) to handle texture extraction.

### 1.1. Palette Extraction
- Read the `PLAYPAL` lump.
- Extract the first palette (256 RGB tuples).
- This is required to convert raw Doom graphics (indexes) to RGB colors.

### 1.2. Flats (Floors/Ceilings) Extraction
- Iterate through lumps between `F_START` and `F_END`.
- Each lump is a raw 64x64 byte array (4096 bytes).
- Convert each byte to an RGB tuple using the palette.
- Store as `(name, data)` where data is a list of pixels.

### 1.3. Wall Texture Extraction (Phase 2)
- **Patches**: Read `PNAMES` and all patch lumps.
- **Texture Definitions**: Read `TEXTURE1` and `TEXTURE2`.
- **Composition**: For each texture definition:
    - Create a canvas of `width x height`.
    - Draw each patch at its specified offset (handling transparency if needed, though Doom walls are mostly opaque).
    - Convert to RGB.
- *Note*: For the first iteration, we might focus on Flats or simple single-patch textures.

## 2. Data Storage (ClickHouse)

### 2.1. Texture Metadata Table
Store information about available textures.
```sql
CREATE TABLE doomhouse.wad_texture_info (
    id UInt32,          -- Unique Texture ID
    name String,        -- Texture Name (e.g., 'FLOOR4_8', 'STARTAN3')
    width UInt16,
    height UInt16,
    type String         -- 'flat' or 'wall'
) ENGINE = MergeTree ORDER BY id;
```

### 2.2. Texture Data Table
Store the actual pixel data. To optimize for SQL lookup, we can use a flat structure or a packed array.
Given the volume, a flat table with a composite primary key is best for Dictionary lookup.

```sql
CREATE TABLE doomhouse.wad_texture_data (
    tex_id UInt32,
    u UInt16,
    v UInt16,
    color UInt32  -- Packed RGB (0x00RRGGBB)
) ENGINE = MergeTree ORDER BY (tex_id, u, v);
```

### 2.3. Dictionaries
Create dictionaries for fast O(1) lookup during rendering.

```sql
-- Map Name -> ID (for resolving in bsp_resolved)
CREATE DICTIONARY doomhouse.dict_wad_texture_name_to_id
(name String, id UInt32)
PRIMARY KEY name
SOURCE(CLICKHOUSE(TABLE 'wad_texture_info')) ...

-- Map (ID, U, V) -> Color (for rendering)
CREATE DICTIONARY doomhouse.dict_wad_texture_pixels
(tex_id UInt32, u UInt16, v UInt16, color UInt32)
PRIMARY KEY tex_id, u, v
SOURCE(CLICKHOUSE(TABLE 'wad_texture_data')) ...
```

## 3. Render Pipeline Updates (SQL)

### 3.1. Update Geometry Resolution (`resolve_geometry.sql`)
- Join `wad_texture_info` (via dictionary or table) to resolve string texture names (`floor_tex`, `ceil_tex`, `wall_tex`) to integer IDs (`floor_tex_id`, `ceil_tex_id`, `wall_tex_id`).
- Store these IDs in `bsp_resolved`.

### 3.2. Update Render View (`render_view.sql`)
- **Texture Coordinates**:
    - **Walls**: Calculate `u` based on wall length/offset. Calculate `v` based on world Z.
    - **Floors/Ceilings**: Use world `x, y` as `u, v`.
- **Pixel Lookup**:
    - Replace the "Simple Shader" logic.
    - Use `dictGet('doomhouse.dict_wad_texture_pixels', 'color', tex_id, u, v)` to fetch the pixel color.
    - Apply lighting (`w_shade` / `f_shade`) to the retrieved color.

## 4. Implementation Steps

1.  **Python**: Implement `load_playpal` and `load_flats`.
2.  **Python**: Populate `wad_texture_info` and `wad_texture_data` with Flats.
3.  **SQL**: Create the new tables and dictionaries.
4.  **SQL**: Update `resolve_geometry.sql` to map Flat names to IDs.
5.  **SQL**: Update `render_view.sql` to render floors/ceilings using the new texture dictionary.
6.  **Python**: Implement `load_textures` (Walls).
7.  **SQL**: Update `resolve_geometry.sql` to map Wall names to IDs.
8.  **SQL**: Update `render_view.sql` to render walls using the new texture dictionary.
