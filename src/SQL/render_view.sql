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
        -- FRAGMENT SHADER (Unchanged)
        -- =========================================================
        multiIf(
            is_wall,
            CAST(bitOr(bitOr(bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_wall', 'r', w_tex_idx) * w_shade), 0), bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_wall', 'g', w_tex_idx) * w_shade), 8)), bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_wall', 'b', w_tex_idx) * w_shade), 16)), 'UInt32'),
            y < draw_start OR isNull(draw_start),
            CAST(bitOr(bitOr(bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_ceiling_data', 'r', f_tex_idx) * f_shade), 0), bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_ceiling_data', 'g', f_tex_idx) * f_shade), 8)), bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_ceiling_data', 'b', f_tex_idx) * f_shade), 16)), 'UInt32'),
            CAST(bitOr(bitOr(bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_floor_data', 'r', f_tex_idx) * f_shade), 0), bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_floor_data', 'g', f_tex_idx) * f_shade), 8)), bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_floor_data', 'b', f_tex_idx) * f_shade), 16)), 'UInt32')
        ) AS final_color
        
    FROM
    (
        SELECT
            x,
            arrayJoin(range(0, 480)) AS y,
            valid_x, valid_y,
            p_dir_x, p_dir_y, p_plane_x, p_plane_y,
            
            (not isNull(draw_start) AND y >= draw_start AND y <= draw_end) AS is_wall,
            ifNull(draw_start, 240) AS draw_start, 
            ifNull(draw_end, 240) AS draw_end,
            
            -- Wall Shading
            least(1.0, 4.0 / (ifNull(z_depth, 100.0) + 0.1)) AS w_shade,
            
            -- Wall Texture Index (Perspective Corrected)
            toUInt64(
                (ifNull(tex_u, 0) + 
                bitAnd(
                    toUInt32((y - draw_start) * (512 / (abs(draw_end - draw_start) + 0.01))), 
                    511
                ) * 512) + 1
            ) AS w_tex_idx,

            -- Floor/Ceiling
            240 / (abs(y - 240) + 0.01) AS row_dist,
            (p_dir_x + p_plane_x * (2.0 * x * (1.0/640.0) - 1.0)) AS r_dir_x,
            (p_dir_y + p_plane_y * (2.0 * x * (1.0/640.0) - 1.0)) AS r_dir_y,
            (valid_x + row_dist * r_dir_x) AS map_x,
            (valid_y + row_dist * r_dir_y) AS map_y,
            toUInt64(bitAnd(toInt32(map_y * 512), 511) * 512 + bitAnd(toInt32(map_x * 512), 511) + 1) AS f_tex_idx,
            (1.0 - least(row_dist * 0.125, 1.0)) AS f_shade

        FROM
        (
            SELECT
                all_x.x AS x,
                any(valid_x) AS valid_x, any(valid_y) AS valid_y,
                any(dir_x) AS p_dir_x, any(dir_y) AS p_dir_y,
                any(plane_x) AS p_plane_x, any(plane_y) AS p_plane_y,
                
                argMin(draw_start, z_depth_val) AS draw_start,
                argMin(draw_end, z_depth_val) AS draw_end,
                min(z_depth_val) AS z_depth,
                argMin(tex_u, z_depth_val) AS tex_u
                
            FROM doomhouse.player_state AS camera
            CROSS JOIN (SELECT arrayJoin(range(0, 640)) AS x) AS all_x
            LEFT JOIN (
                SELECT
                    arrayJoin(range(screen_x_start, screen_x_end)) AS x,
                    id,

                    -- =========================================================
                    -- CORRECTED PERSPECTIVE INTERPOLATION
                    -- =========================================================
                    -- We calculate 't' based on the RELATIVE position from the start
                    -- of the RAW projection, not the clamped screen edge.
                    
                    (x - raw_x1) / (raw_x2 - raw_x1 + 0.0001) AS t_global,
                    
                    -- Interpolate Reciprocals (1/Z) and (U/Z)
                    (iz_start + (iz_end - iz_start) * t_global) AS iz_curr,
                    (uiz_start + (uiz_end - uiz_start) * t_global) AS uiz_curr,
                    
                    -- Recover real values
                    1.0 / iz_curr AS z_depth_val,
                    toUInt32(uiz_curr / iz_curr) AS tex_u,

                    -- Calculate Wall Height
                    toInt32(240 - (480 * (ceil_h - 0.5) / z_depth_val)) AS draw_start,
                    toInt32(240 + (480 * (0.5 - floor_h) / z_depth_val)) AS draw_end
                    
                FROM (
                    SELECT
                        *,
                        -- 1. Determine "Left" and "Right" in Screen Space
                        -- Even if the wall is flipped (x2 < x1), we order strictly by screen X
                        -- to make interpolation linear from left to right.
                        least(proj_x1, proj_x2) AS raw_x1,
                        greatest(proj_x1, proj_x2) AS raw_x2,
                        
                        -- 2. Determine Depth and U at those Left/Right edges
                        if(proj_x1 < proj_x2, rz1, rz2) AS z_start,
                        if(proj_x1 < proj_x2, rz2, rz1) AS z_end,
                        
                        if(proj_x1 < proj_x2, 0.0, wall_len * 512.0) AS u_start,
                        if(proj_x1 < proj_x2, wall_len * 512.0, 0.0) AS u_end,

                        -- 3. Pre-calculate Reciprocals
                        1.0 / z_start AS iz_start,
                        1.0 / z_end AS iz_end,
                        u_start / z_start AS uiz_start,
                        u_end / z_end AS uiz_end,

                        -- 4. Determine Clipping Bounds (Actual pixels to draw)
                        greatest(0, least(640, raw_x1)) AS screen_x_start,
                        least(640, greatest(0, raw_x2)) AS screen_x_end
                        
                    FROM (
                        SELECT
                            id,
                            dictGet('doomhouse.dict_bsp_segs', 'ceil', id) AS ceil_h,
                            dictGet('doomhouse.dict_bsp_segs', 'floor', id) AS floor_h,
                            
                            -- Projection Math
                            (dictGet('doomhouse.dict_bsp_segs', 'x1', id) - valid_x) AS dx1,
                            (dictGet('doomhouse.dict_bsp_segs', 'y1', id) - valid_y) AS dy1,
                            (dictGet('doomhouse.dict_bsp_segs', 'x2', id) - valid_x) AS dx2,
                            (dictGet('doomhouse.dict_bsp_segs', 'y2', id) - valid_y) AS dy2,
                            
                            (dx1 * dir_x + dy1 * dir_y) AS rz1,
                            (dx2 * dir_x + dy2 * dir_y) AS rz2,
                            (dx1 * plane_x + dy1 * plane_y) AS rx1,
                            (dx2 * plane_x + dy2 * plane_y) AS rx2,
                            
                            -- Keep Projection as Float for precision
                            (320.0 + (rx1 / rz1) * 320.0) AS proj_x1,
                            (320.0 + (rx2 / rz2) * 320.0) AS proj_x2,
                            
                            sqrt(pow(dx2-dx1, 2) + pow(dy2-dy1, 2)) AS wall_len
                        FROM doomhouse.player_state
                        CROSS JOIN (SELECT id FROM doomhouse.dict_bsp_segs) AS ids
                    )
                    WHERE rz1 > 0.1 AND rz2 > 0.1 -- Simple Near Clip
                )
                WHERE screen_x_end > screen_x_start -- Discard invisible walls
            ) AS walls ON all_x.x = walls.x
            GROUP BY all_x.x
        )
    )
)