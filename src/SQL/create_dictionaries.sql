CREATE DICTIONARY doomhouse.dict_map_data (id UInt32, val UInt8)
PRIMARY KEY id
SOURCE(CLICKHOUSE(TABLE 'map_source' DB 'doomhouse'))
LIFETIME(MIN 3600 MAX 3600)
LAYOUT(FLAT());

CREATE DICTIONARY doomhouse.dict_floor_dist (id UInt32, dist Float32)
PRIMARY KEY id
SOURCE(CLICKHOUSE(TABLE 'floor_dist_source' DB 'doomhouse'))
LIFETIME(MIN 3600 MAX 3600)
LAYOUT(FLAT());

CREATE DICTIONARY doomhouse.dict_bsp_segs (
    id UInt32,
    x1 Float64,
    y1 Float64,
    x2 Float64,
    y2 Float64,
    ceil Float32,
    floor Float32
)
PRIMARY KEY id
SOURCE(CLICKHOUSE(TABLE 'bsp_source' DB 'doomhouse'))
LIFETIME(MIN 3600 MAX 3600)
LAYOUT(FLAT())
