INSERT INTO doomhouse.bsp_resolved
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
