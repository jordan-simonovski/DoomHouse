-- WAD Texture Tables

-- 1. Texture Metadata
CREATE TABLE IF NOT EXISTS doomhouse.wad_texture_info (
    id UInt32,
    name String,
    width UInt16,
    height UInt16,
    type String -- 'flat' or 'wall'
) ENGINE = MergeTree ORDER BY id;

-- 2. Texture Data (Pixels)
-- Storing as packed UInt32 (0x00RRGGBB) for efficiency
CREATE TABLE IF NOT EXISTS doomhouse.wad_texture_data (
    tex_id UInt32,
    u UInt16,
    v UInt16,
    color UInt32
) ENGINE = MergeTree ORDER BY (tex_id, u, v);

-- 3. Dictionaries

-- Map Name -> ID
CREATE DICTIONARY IF NOT EXISTS doomhouse.dict_wad_texture_name_to_id (
    name String,
    id UInt32
)
PRIMARY KEY name
SOURCE(CLICKHOUSE(TABLE 'wad_texture_info' DB 'doomhouse'))
LIFETIME(MIN 3600 MAX 3600)
LAYOUT(HASHED());

-- Map (ID, U, V) -> Color
CREATE DICTIONARY IF NOT EXISTS doomhouse.dict_wad_texture_pixels (
    tex_id UInt32,
    u UInt16,
    v UInt16,
    color UInt32
)
PRIMARY KEY tex_id, u, v
SOURCE(CLICKHOUSE(TABLE 'wad_texture_data' DB 'doomhouse'))
LIFETIME(MIN 3600 MAX 3600)
LAYOUT(COMPLEX_KEY_HASHED());
