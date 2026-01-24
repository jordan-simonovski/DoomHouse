CREATE DATABASE IF NOT EXISTS doomhouse;

-- 1. Map Data Source
CREATE TABLE doomhouse.map_source (
    id UInt32, 
    val UInt8
) ENGINE = MergeTree ORDER BY id;

INSERT INTO doomhouse.map_source
WITH [
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,0,0,0,0,0,0,1,0,0,0,0,0,0,1,
    1,0,0,1,0,0,2,1,0,0,1,0,0,2,1,
    1,0,0,0,0,0,0,1,0,0,0,0,0,0,1,
    1,0,2,0,0,0,0,0,0,2,0,0,0,0,1,
    1,0,0,1,0,0,0,1,0,0,1,0,0,0,1,
    1,0,0,0,0,0,0,1,0,0,0,0,0,0,1,
    1,1,1,0,1,1,1,1,1,1,0,1,1,1,1,
    1,0,0,0,0,0,0,1,0,0,0,0,0,0,1,
    1,0,0,1,0,0,2,1,0,0,1,0,0,2,1,
    1,0,0,0,0,0,0,1,0,0,0,0,0,0,1,
    1,0,2,0,0,0,0,0,0,2,0,0,0,0,1,
    1,0,0,1,0,0,0,1,0,0,1,0,0,0,1,
    1,0,0,0,0,0,0,1,0,0,0,0,0,0,1,
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1
] AS map_data
SELECT 
    idx AS id, 
    map_data[idx] AS val 
FROM (SELECT arrayJoin(arrayEnumerate(map_data)) AS idx);

-- 2. Floor Distance Source
CREATE TABLE doomhouse.floor_dist_source (
    id UInt32, 
    dist Float32
) ENGINE = MergeTree ORDER BY id;

INSERT INTO doomhouse.floor_dist_source
SELECT 
    number + 1 as id, 
    if(number <= 240, 0.0, 480.0 / (2.0 * number - 480.0)) as dist
FROM numbers(480);

-- 3. Texture Data Sources (Placeholder tables, populated by Python client)
CREATE TABLE IF NOT EXISTS doomhouse.tex_wall1_source (id UInt32, r UInt8, g UInt8, b UInt8) ENGINE = MergeTree ORDER BY id;
CREATE TABLE IF NOT EXISTS doomhouse.tex_wall2_source (id UInt32, r UInt8, g UInt8, b UInt8) ENGINE = MergeTree ORDER BY id;
CREATE TABLE IF NOT EXISTS doomhouse.tex_floor_source (id UInt32, r UInt8, g UInt8, b UInt8) ENGINE = MergeTree ORDER BY id;
CREATE TABLE IF NOT EXISTS doomhouse.tex_ceiling_source (id UInt32, r UInt8, g UInt8, b UInt8) ENGINE = MergeTree ORDER BY id;

-- 4. BSP Segment Source (Fallback)
CREATE TABLE IF NOT EXISTS doomhouse.bsp_source (
    id UInt32,
    x1 Float64,
    y1 Float64,
    x2 Float64,
    y2 Float64,
    ceil Float32,
    floor Float32
) ENGINE = MergeTree ORDER BY id;

-- 5. Raw WAD Tables
CREATE TABLE IF NOT EXISTS doomhouse.wad_vertexes (
    id UInt32,
    x Int16,
    y Int16
) ENGINE = MergeTree ORDER BY id;

CREATE TABLE IF NOT EXISTS doomhouse.wad_sectors (
    id UInt32,
    floor_h Int16,
    ceil_h Int16,
    floor_tex String,
    ceil_tex String,
    light UInt8,
    special UInt16,
    tag UInt16
) ENGINE = MergeTree ORDER BY id;

CREATE TABLE IF NOT EXISTS doomhouse.wad_sidedefs (
    id UInt32,
    x_off Int16,
    y_off Int16,
    upper String,
    lower String,
    middle String,
    sector_id UInt16
) ENGINE = MergeTree ORDER BY id;

CREATE TABLE IF NOT EXISTS doomhouse.wad_linedefs (
    id UInt32,
    v1 UInt16,
    v2 UInt16,
    flags Int16,
    special Int16,
    tag Int16,
    front_side Int16,
    back_side Int16
) ENGINE = MergeTree ORDER BY id;

CREATE TABLE IF NOT EXISTS doomhouse.wad_segs (
    id UInt32,
    v1 UInt16,
    v2 UInt16,
    angle Int16,
    linedef_id UInt16,
    side Int16,
    offset Int16
) ENGINE = MergeTree ORDER BY id;

CREATE TABLE IF NOT EXISTS doomhouse.wad_things (
    id UInt32,
    x Int16,
    y Int16,
    angle Int16,
    type Int16,
    options Int16
) ENGINE = MergeTree ORDER BY id;

-- 6. Resolved BSP Table
CREATE TABLE IF NOT EXISTS doomhouse.bsp_resolved (
    id UInt32,
    x1 Float64,
    y1 Float64,
    x2 Float64,
    y2 Float64,
    ceil Float32,
    floor Float32,
    wall_tex String,
    ceil_tex String,
    floor_tex String,
    wall_tex_id UInt32,
    ceil_tex_id UInt32,
    floor_tex_id UInt32,
    light UInt8,
    sector_id UInt16,
    seg_offset Float32,
    tex_x_off Float32,
    tex_y_off Float32,
    length Float32
) ENGINE = MergeTree ORDER BY id;
