CREATE MATERIALIZED VIEW doomhouse.render_materialized
TO doomhouse.rendered_frame
AS
SELECT
    any(valid_x) as pos_x,
    any(valid_y) as pos_y,
    arrayMap(x -> x.2, arraySort(k -> k.1, groupArray((y * 640 + x, final_color)))) AS image_data
FROM
(
    SELECT
        x, y,
        valid_x, valid_y,
        
        -- =========================================================
        -- FRAGMENT SHADER
        -- =========================================================
        multiIf(
            -- CASE 1: WALL
            is_wall,
            if(wall_tex_id > 0,
                -- Texture Lookup
                CAST(
                    bitOr(
                        bitOr(
                            bitShiftLeft(toUInt32(
                                bitAnd(dictGet('doomhouse.dict_wad_texture_pixels', 'color', tuple(toUInt32(wall_tex_id), toUInt16(bitAnd(toInt32(wall_u), 63)), toUInt16(bitAnd(toInt32(wall_v), 63)))), 255) * w_shade
                            ), 0),
                            bitShiftLeft(toUInt32(
                                bitAnd(bitShiftRight(dictGet('doomhouse.dict_wad_texture_pixels', 'color', tuple(toUInt32(wall_tex_id), toUInt16(bitAnd(toInt32(wall_u), 63)), toUInt16(bitAnd(toInt32(wall_v), 63)))), 8), 255) * w_shade
                            ), 8)
                        ),
                        bitShiftLeft(toUInt32(
                            bitAnd(bitShiftRight(dictGet('doomhouse.dict_wad_texture_pixels', 'color', tuple(toUInt32(wall_tex_id), toUInt16(bitAnd(toInt32(wall_u), 63)), toUInt16(bitAnd(toInt32(wall_v), 63)))), 16), 255) * w_shade
                        ), 16)
                    )
                , 'UInt32'),
                -- Fallback Solid Color
                CAST(
                    bitOr(
                        bitOr(
                            bitShiftLeft(toUInt32(180 * w_shade), 0),
                            bitShiftLeft(toUInt32(100 * w_shade), 8)
                        ),
                        bitShiftLeft(toUInt32(50 * w_shade), 16)
                    )
                , 'UInt32')
            ),

            -- CASE 2: CEILING
            y < draw_start OR isNull(draw_start),
            CAST(
                bitOr(
                    bitOr(
                        bitShiftLeft(toUInt32(
                            bitAnd(dictGet('doomhouse.dict_wad_texture_pixels', 'color', tuple(toUInt32(ceil_tex_id), toUInt16(bitAnd(toInt32(map_x * 64), 63)), toUInt16(bitAnd(toInt32(map_y * 64), 63)))), 255) * f_shade
                        ), 0),
                        bitShiftLeft(toUInt32(
                            bitAnd(bitShiftRight(dictGet('doomhouse.dict_wad_texture_pixels', 'color', tuple(toUInt32(ceil_tex_id), toUInt16(bitAnd(toInt32(map_x * 64), 63)), toUInt16(bitAnd(toInt32(map_y * 64), 63)))), 8), 255) * f_shade
                        ), 8)
                    ),
                    bitShiftLeft(toUInt32(
                        bitAnd(bitShiftRight(dictGet('doomhouse.dict_wad_texture_pixels', 'color', tuple(toUInt32(ceil_tex_id), toUInt16(bitAnd(toInt32(map_x * 64), 63)), toUInt16(bitAnd(toInt32(map_y * 64), 63)))), 16), 255) * f_shade
                    ), 16)
                )
            , 'UInt32'),

            -- CASE 3: FLOOR
            CAST(
                bitOr(
                    bitOr(
                        bitShiftLeft(toUInt32(
                            bitAnd(dictGet('doomhouse.dict_wad_texture_pixels', 'color', tuple(toUInt32(floor_tex_id), toUInt16(bitAnd(toInt32(map_x * 64), 63)), toUInt16(bitAnd(toInt32(map_y * 64), 63)))), 255) * f_shade
                        ), 0),
                        bitShiftLeft(toUInt32(
                            bitAnd(bitShiftRight(dictGet('doomhouse.dict_wad_texture_pixels', 'color', tuple(toUInt32(floor_tex_id), toUInt16(bitAnd(toInt32(map_x * 64), 63)), toUInt16(bitAnd(toInt32(map_y * 64), 63)))), 8), 255) * f_shade
                        ), 8)
                    ),
                    bitShiftLeft(toUInt32(
                        bitAnd(bitShiftRight(dictGet('doomhouse.dict_wad_texture_pixels', 'color', tuple(toUInt32(floor_tex_id), toUInt16(bitAnd(toInt32(map_x * 64), 63)), toUInt16(bitAnd(toInt32(map_y * 64), 63)))), 16), 255) * f_shade
                    ), 16)
                )
            , 'UInt32')
        ) AS final_color
        
    FROM
    (
        SELECT
            x,
            arrayJoin(range(0, 480)) AS y,
            
            valid_x, valid_y,
            
            -- Wall Geometry Flags
            (not isNull(draw_start) AND y >= draw_start AND y <= draw_end) AS is_wall,
            ifNull(draw_start, 240) AS draw_start, 
            ifNull(draw_end, 240) AS draw_end,
            
            -- Texture IDs
            ifNull(ceil_tex_id, 1) AS ceil_tex_id,
            ifNull(floor_tex_id, 1) AS floor_tex_id,
            ifNull(wall_tex_id, 1) AS wall_tex_id,
            
            -- Wall Texture Coords
            -- u = offset + t_global * length
            -- v = tex_y_off + (y - draw_start) / height * wall_height_units
            (seg_offset + tex_x_off + t_global * length) AS wall_u,
            (tex_y_off + (y - draw_start) / (draw_end - draw_start + 0.001) * (ceil_h - floor_h) * 100.0) AS wall_v,
            
            -- Shading Math
            least(1.0, (ifNull(light_level, 255) / 255.0) * (4.0 / (ifNull(z_depth, 100.0) + 0.1))) AS w_shade,
            (1.0 - least((240 / (abs(y - 240) + 0.01)) * 0.125, 1.0)) AS f_shade,
            
            -- Floor/Ceiling Coords
            240 / (abs(y - 240) + 0.01) AS row_dist,
            (valid_x + row_dist * (p_dir_x + p_plane_x * (2.0 * x * (1.0/640.0) - 1.0))) AS map_x,
            (valid_y + row_dist * (p_dir_y + p_plane_y * (2.0 * x * (1.0/640.0) - 1.0))) AS map_y

        FROM
        (
            SELECT
                all_x.x AS x,
                -- Aggregate Camera Pos
                any(valid_x) AS valid_x, 
                any(valid_y) AS valid_y,
                any(dir_x) AS p_dir_x,
                any(dir_y) AS p_dir_y,
                any(plane_x) AS p_plane_x,
                any(plane_y) AS p_plane_y,
                
                -- Z-Buffer Logic
                argMin(draw_start, z_depth_val) AS draw_start,
                argMin(draw_end, z_depth_val) AS draw_end,
                min(z_depth_val) AS z_depth,
                argMin(light_level, z_depth_val) AS light_level,
                argMin(ceil_tex_id, z_depth_val) AS ceil_tex_id,
                argMin(floor_tex_id, z_depth_val) AS floor_tex_id,
                argMin(wall_tex_id, z_depth_val) AS wall_tex_id,
                
                -- Wall Texture Params
                argMin(seg_offset, z_depth_val) AS seg_offset,
                argMin(tex_x_off, z_depth_val) AS tex_x_off,
                argMin(tex_y_off, z_depth_val) AS tex_y_off,
                argMin(length, z_depth_val) AS length,
                argMin(t_global, z_depth_val) AS t_global,
                argMin(ceil_h, z_depth_val) AS ceil_h,
                argMin(floor_h, z_depth_val) AS floor_h
                
            FROM doomhouse.player_state AS camera
            CROSS JOIN (SELECT arrayJoin(range(0, 640)) AS x) AS all_x
            LEFT JOIN (
                SELECT
                    -- RASTERIZER
                    arrayJoin(range(screen_x_start, screen_x_end)) AS x,
                    
                    -- PERSPECTIVE INTERPOLATION
                    (x - raw_x1) / (raw_x2 - raw_x1 + 0.00001) AS t_global,
                    (iz_start + (iz_end - iz_start) * t_global) AS iz_curr,
                    1.0 / iz_curr AS z_depth_val,

                    -- PERSPECTIVE PROJECTION OF HEIGHT
                    toInt32(240 - (480 * (ceil_h - 0.5) / z_depth_val)) AS draw_start,
                    toInt32(240 + (480 * (0.5 - floor_h) / z_depth_val)) AS draw_end,
                    
                    light_level,
                    ceil_tex_id,
                    floor_tex_id,
                    wall_tex_id,
                    seg_offset,
                    tex_x_off,
                    tex_y_off,
                    length,
                    ceil_h,
                    floor_h
                    
                FROM (
                    SELECT
                        *,
                        -- MATH HELPERS
                        least(proj_x1, proj_x2) AS raw_x1,
                        greatest(proj_x1, proj_x2) AS raw_x2,
                        
                        -- CLAMPING
                        toInt32(greatest(0, least(640, raw_x1))) AS screen_x_start,
                        toInt32(least(640, greatest(0, raw_x2))) AS screen_x_end,
                        
                        -- DEPTH SETUP
                        if(proj_x1 < proj_x2, rz1_c, rz2_c) AS z_start,
                        if(proj_x1 < proj_x2, rz2_c, rz1_c) AS z_end,
                        1.0 / z_start AS iz_start,
                        1.0 / z_end AS iz_end
                    FROM (
                        -- PROJECTION STAGE
                        SELECT 
                            ceil_h, floor_h, light_level,
                            ceil_tex_id, floor_tex_id, wall_tex_id,
                            seg_offset, tex_x_off, tex_y_off, length,
                            rz1_c, rz2_c,
                            320.0 + (rx1_c / rz1_c) * 320.0 AS proj_x1,
                            320.0 + (rx2_c / rz2_c) * 320.0 AS proj_x2
                        FROM (
                            -- CLIPPING STAGE
                            SELECT
                                ceil_h, floor_h, light_level,
                                ceil_tex_id, floor_tex_id, wall_tex_id,
                                seg_offset, tex_x_off, tex_y_off, length,
                                rx1, rz1, rx2, rz2,
                                0.1 AS near,
                                (near - rz1) / (rz2 - rz1 + 0.00001) AS clip_t,
                                
                                if(rz1 < near, rx1 + clip_t * (rx2 - rx1), rx1) AS rx1_c,
                                if(rz1 < near, near, rz1)                       AS rz1_c,
                                if(rz2 < near, rx1 + clip_t * (rx2 - rx1), rx2) AS rx2_c,
                                if(rz2 < near, near, rz2)                       AS rz2_c
                            FROM (
                                -- CAMERA TRANSFORM
                                SELECT
                                    dictGet('doomhouse.dict_bsp_resolved', 'ceil', id) AS ceil_h,
                                    dictGet('doomhouse.dict_bsp_resolved', 'floor', id) AS floor_h,
                                    dictGet('doomhouse.dict_bsp_resolved', 'light', id) AS light_level,
                                    dictGet('doomhouse.dict_bsp_resolved', 'ceil_tex_id', id) AS ceil_tex_id,
                                    dictGet('doomhouse.dict_bsp_resolved', 'floor_tex_id', id) AS floor_tex_id,
                                    dictGet('doomhouse.dict_bsp_resolved', 'wall_tex_id', id) AS wall_tex_id,
                                    dictGet('doomhouse.dict_bsp_resolved', 'seg_offset', id) AS seg_offset,
                                    dictGet('doomhouse.dict_bsp_resolved', 'tex_x_off', id) AS tex_x_off,
                                    dictGet('doomhouse.dict_bsp_resolved', 'tex_y_off', id) AS tex_y_off,
                                    dictGet('doomhouse.dict_bsp_resolved', 'length', id) AS length,
                                    
                                    (dictGet('doomhouse.dict_bsp_resolved', 'x1', id) - valid_x) AS dx1,
                                    (dictGet('doomhouse.dict_bsp_resolved', 'y1', id) - valid_y) AS dy1,
                                    (dictGet('doomhouse.dict_bsp_resolved', 'x2', id) - valid_x) AS dx2,
                                    (dictGet('doomhouse.dict_bsp_resolved', 'y2', id) - valid_y) AS dy2,
                                    (dx1 * dir_x + dy1 * dir_y) AS rz1,
                                    (dx2 * dir_x + dy2 * dir_y) AS rz2,
                                    (dx1 * plane_x + dy1 * plane_y) AS rx1,
                                    (dx2 * plane_x + dy2 * plane_y) AS rx2
                                FROM doomhouse.player_state
                                CROSS JOIN (SELECT id FROM doomhouse.dict_bsp_resolved) AS ids
                            )
                            WHERE rz1 >= near OR rz2 >= near
                        )
                    )
                    WHERE screen_x_end > screen_x_start
                )
            ) AS walls ON all_x.x = walls.x
            GROUP BY all_x.x
        )
    )
)
