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
            
            -- Shading
            least(1.0, 4.0 / (ifNull(z_depth, 100.0) + 0.1)) AS w_shade,
            
            -- Texture Mapping (Perspective Correct)
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
                    -- RASTERIZER LOOP
                    arrayJoin(range(screen_x_start, screen_x_end)) AS x,
                    id,
                    
                    -- PERSPECTIVE INTERPOLATION
                    -- 1. Calculate T relative to the clipped, projected wall
                    (x - raw_x1) / (raw_x2 - raw_x1 + 0.00001) AS t_global,
                    
                    -- 2. Interpolate 1/Z and U/Z
                    (iz_start + (iz_end - iz_start) * t_global) AS iz_curr,
                    (uiz_start + (uiz_end - uiz_start) * t_global) AS uiz_curr,
                    
                    -- 3. Recover Z and U
                    1.0 / iz_curr AS z_depth_val,
                    toUInt32(uiz_curr / iz_curr) AS tex_u,

                    -- 4. Calculate Vertical Extents
                    toInt32(240 - (480 * (ceil_h - 0.5) / z_depth_val)) AS draw_start,
                    toInt32(240 + (480 * (0.5 - floor_h) / z_depth_val)) AS draw_end
                    
                FROM (
                    SELECT
                        *,
                        -- SORT LEFT-TO-RIGHT FOR INTERPOLATION
                        least(proj_x1, proj_x2) AS raw_x1,
                        greatest(proj_x1, proj_x2) AS raw_x2,
                        
                        -- CLAMP TO SCREEN (for the loop)
                        toInt32(greatest(0, least(640, raw_x1))) AS screen_x_start,
                        toInt32(least(640, greatest(0, raw_x2))) AS screen_x_end,
                        
                        -- ASSIGN ATTRIBUTES TO LEFT/RIGHT EDGES
                        if(proj_x1 < proj_x2, rz1_c, rz2_c) AS z_start,
                        if(proj_x1 < proj_x2, rz2_c, rz1_c) AS z_end,
                        
                        if(proj_x1 < proj_x2, u1_c, u2_c) AS u_start,
                        if(proj_x1 < proj_x2, u2_c, u1_c) AS u_end,

                        -- PRECOMPUTE RECIPROCALS
                        1.0 / z_start AS iz_start,
                        1.0 / z_end AS iz_end,
                        u_start / z_start AS uiz_start,
                        u_end / z_end AS uiz_end
                    FROM (
                        -- PROJECTION STAGE (Operating on Clipped Coords)
                        SELECT 
                            id, ceil_h, floor_h,
                            rz1_c, rz2_c, u1_c, u2_c,
                            
                            -- Project X (Standard Doom Projection)
                            320.0 + (rx1_c / rz1_c) * 320.0 AS proj_x1,
                            320.0 + (rx2_c / rz2_c) * 320.0 AS proj_x2
                        FROM (
                            -- CLIPPING STAGE (Clip against Z=0.1)
                            SELECT
                                id, ceil_h, floor_h, wall_len,
                                rx1, rz1, rx2, rz2,
                                
                                0.1 AS near,
                                -- Calculate intersection t
                                (near - rz1) / (rz2 - rz1 + 0.00001) AS clip_t,
                                
                                -- Clip Point 1
                                if(rz1 < near, rx1 + clip_t * (rx2 - rx1), rx1) AS rx1_c,
                                if(rz1 < near, near, rz1)                       AS rz1_c,
                                if(rz1 < near, clip_t * wall_len * 512.0, 0.0)  AS u1_c,
                                
                                -- Clip Point 2
                                if(rz2 < near, rx1 + clip_t * (rx2 - rx1), rx2) AS rx2_c,
                                if(rz2 < near, near, rz2)                       AS rz2_c,
                                if(rz2 < near, clip_t * wall_len * 512.0, wall_len * 512.0) AS u2_c
                                
                            FROM (
                                -- CAMERA TRANSFORM
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
                                    
                                    sqrt(pow(dx2-dx1, 2) + pow(dy2-dy1, 2)) AS wall_len
                                FROM doomhouse.player_state
                                CROSS JOIN (SELECT id FROM doomhouse.dict_bsp_segs) AS ids
                            )
                            -- Only discard if ENTIRE wall is behind
                            WHERE rz1 >= near OR rz2 >= near
                        )
                    )
                    -- Discard walls that are completely off-screen horizontally
                    WHERE screen_x_end > screen_x_start
                )
            ) AS walls ON all_x.x = walls.x
            GROUP BY all_x.x
        )
    )
)