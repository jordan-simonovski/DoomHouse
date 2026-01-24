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
        -- SIMPLE SHADER (Solid Colors + Lighting)
        -- =========================================================
        multiIf(
            -- CASE 1: WALL (Orange/Brown)
            is_wall,
            CAST(
                bitOr(
                    bitOr(
                        bitShiftLeft(toUInt32(180 * w_shade), 0),
                        bitShiftLeft(toUInt32(100 * w_shade), 8)
                    ),
                    bitShiftLeft(toUInt32(50 * w_shade), 16)
                )
            , 'UInt32'),

            -- CASE 2: CEILING (Dark Grey)
            y < draw_start OR isNull(draw_start),
            CAST(
                bitOr(
                    bitOr(
                        bitShiftLeft(toUInt32(80 * f_shade), 0),
                        bitShiftLeft(toUInt32(80 * f_shade), 8)
                    ),
                    bitShiftLeft(toUInt32(80 * f_shade), 16)
                )
            , 'UInt32'),

            -- CASE 3: FLOOR (Dark Blue/Grey)
            CAST(
                bitOr(
                    bitOr(
                        bitShiftLeft(toUInt32(50 * f_shade), 0),
                        bitShiftLeft(toUInt32(50 * f_shade), 8)
                    ),
                    bitShiftLeft(toUInt32(60 * f_shade), 16)
                )
            , 'UInt32')
        ) AS final_color
        
    FROM
    (
        SELECT
            x,
            arrayJoin(range(0, 480)) AS y,
            
            -- !!! CRITICAL FIX: Explicitly select these so the outer query can find them !!!
            valid_x, 
            valid_y,
            
            -- Wall Geometry Flags
            (not isNull(draw_start) AND y >= draw_start AND y <= draw_end) AS is_wall,
            ifNull(draw_start, 240) AS draw_start, 
            ifNull(draw_end, 240) AS draw_end,
            
            -- Shading Math
            -- Use light_level from WAD (0-255) combined with distance shading
            least(1.0, (ifNull(light_level, 255) / 255.0) * (4.0 / (ifNull(z_depth, 100.0) + 0.1))) AS w_shade,
            (1.0 - least((240 / (abs(y - 240) + 0.01)) * 0.125, 1.0)) AS f_shade

        FROM
        (
            SELECT
                all_x.x AS x,
                -- Aggregate Camera Pos (should be constant, but required for Group By)
                any(valid_x) AS valid_x, 
                any(valid_y) AS valid_y,
                
                -- Z-Buffer Logic: Find the closest wall for this X column
                argMin(draw_start, z_depth_val) AS draw_start,
                argMin(draw_end, z_depth_val) AS draw_end,
                min(z_depth_val) AS z_depth,
                argMin(light_level, z_depth_val) AS light_level
                
            FROM doomhouse.player_state AS camera
            CROSS JOIN (SELECT arrayJoin(range(0, 640)) AS x) AS all_x
            LEFT JOIN (
                SELECT
                    -- RASTERIZER: Expand horizontal range
                    arrayJoin(range(screen_x_start, screen_x_end)) AS x,
                    
                    -- PERSPECTIVE INTERPOLATION
                    (x - raw_x1) / (raw_x2 - raw_x1 + 0.00001) AS t_global,
                    (iz_start + (iz_end - iz_start) * t_global) AS iz_curr,
                    1.0 / iz_curr AS z_depth_val,

                    -- PERSPECTIVE PROJECTION OF HEIGHT
                    toInt32(240 - (480 * (ceil_h - 0.5) / z_depth_val)) AS draw_start,
                    toInt32(240 + (480 * (0.5 - floor_h) / z_depth_val)) AS draw_end,
                    
                    light_level
                    
                FROM (
                    SELECT
                        *,
                        -- MATH HELPERS
                        least(proj_x1, proj_x2) AS raw_x1,
                        greatest(proj_x1, proj_x2) AS raw_x2,
                        
                        -- CLAMPING (Cast to Int32 for range function)
                        toInt32(greatest(0, least(640, raw_x1))) AS screen_x_start,
                        toInt32(least(640, greatest(0, raw_x2))) AS screen_x_end,
                        
                        -- DEPTH SETUP (Sort by screen X to ensure linear interpolation works)
                        if(proj_x1 < proj_x2, rz1_c, rz2_c) AS z_start,
                        if(proj_x1 < proj_x2, rz2_c, rz1_c) AS z_end,
                        1.0 / z_start AS iz_start,
                        1.0 / z_end AS iz_end
                    FROM (
                        -- PROJECTION STAGE
                        SELECT 
                            ceil_h, floor_h, light_level,
                            rz1_c, rz2_c,
                            320.0 + (rx1_c / rz1_c) * 320.0 AS proj_x1,
                            320.0 + (rx2_c / rz2_c) * 320.0 AS proj_x2
                        FROM (
                            -- CLIPPING STAGE (Homogeneous Clip against Z=0.1)
                            SELECT
                                ceil_h, floor_h, light_level,
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
                                    dictGet('doomhouse.dict_bsp_resolved', 'wall_tex', id) AS wall_tex,
                                    dictGet('doomhouse.dict_bsp_resolved', 'ceil_tex', id) AS ceil_tex,
                                    dictGet('doomhouse.dict_bsp_resolved', 'floor_tex', id) AS floor_tex,
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