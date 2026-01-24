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
            
            least(1.0, 4.0 / (ifNull(z_depth, 100.0) + 0.1)) AS w_shade,
            
            toUInt64(
                (ifNull(tex_u, 0) + 
                bitAnd(
                    toUInt32((y - draw_start) * (512 / (abs(draw_end - draw_start) + 0.01))), 
                    511
                ) * 512) + 1
            ) AS w_tex_idx,

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
                    -- !!! FIX HERE: arrayJoin requires Integer arguments !!!
                    arrayJoin(range(screen_x_start, screen_x_end)) AS x,
                    
                    id,
                    
                    -- Use the FLOATING POINT 'raw' coordinates for math
                    (x - raw_x1) / (raw_x2 - raw_x1 + 0.0001) AS t_global,
                    
                    (iz_start + (iz_end - iz_start) * t_global) AS iz_curr,
                    (uiz_start + (uiz_end - uiz_start) * t_global) AS uiz_curr,
                    
                    1.0 / iz_curr AS z_depth_val,
                    toUInt32(uiz_curr / iz_curr) AS tex_u,

                    toInt32(240 - (480 * (ceil_h - 0.5) / z_depth_val)) AS draw_start,
                    toInt32(240 + (480 * (0.5 - floor_h) / z_depth_val)) AS draw_end
                    
                FROM (
                    SELECT
                        *,
                        -- Keep precision for interpolation math
                        least(proj_x1, proj_x2) AS raw_x1,
                        greatest(proj_x1, proj_x2) AS raw_x2,
                        
                        -- !!! FIX HERE: Cast to Int32 for the 'range' function !!!
                        toInt32(greatest(0, least(640, raw_x1))) AS screen_x_start,
                        toInt32(least(640, greatest(0, raw_x2))) AS screen_x_end,
                        
                        if(proj_x1 < proj_x2, rz1, rz2) AS z_start,
                        if(proj_x1 < proj_x2, rz2, rz1) AS z_end,
                        
                        if(proj_x1 < proj_x2, 0.0, wall_len * 512.0) AS u_start,
                        if(proj_x1 < proj_x2, wall_len * 512.0, 0.0) AS u_end,

                        1.0 / z_start AS iz_start,
                        1.0 / z_end AS iz_end,
                        u_start / z_start AS uiz_start,
                        u_end / z_end AS uiz_end
                    FROM (
                        SELECT
                            id,
                            dictGet('doomhouse.dict_bsp_segs', 'ceil', id) AS ceil_h,
                            dictGet('doomhouse.dict_bsp_segs', 'floor', id) AS floor_h,
                            
                            (dictGet('doomhouse.dict_bsp_segs', 'x1', id) - valid_x) AS dx1,
                            (dictGet('doomhouse.dict_bsp_segs', 'y1', id) - valid_y) AS dy1,
                            (dictGet('doomhouse.dict_bsp_segs', 'x2', id) - valid_x) AS dx2,
                            (dictGet('doomhouse.dict_bsp_segs', 'y2', id) - valid_y) AS dy2,
                            
                            (dx1 * dir_x + dy1 * dir_y) AS rz1,
                            (dx2 * dir_x + dy2 * dir_y) AS rz2,
                            (dx1 * plane_x + dy1 * plane_y) AS rx1,
                            (dx2 * plane_x + dy2 * plane_y) AS rx2,
                            
                            -- Keep as Float
                            (320.0 + (rx1 / rz1) * 320.0) AS proj_x1,
                            (320.0 + (rx2 / rz2) * 320.0) AS proj_x2,
                            
                            sqrt(pow(dx2-dx1, 2) + pow(dy2-dy1, 2)) AS wall_len
                        FROM doomhouse.player_state
                        CROSS JOIN (SELECT id FROM doomhouse.dict_bsp_segs) AS ids
                    )
                    WHERE rz1 > 0.1 AND rz2 > 0.1
                )
                WHERE screen_x_end > screen_x_start
            ) AS walls ON all_x.x = walls.x
            GROUP BY all_x.x
        )
    )
)