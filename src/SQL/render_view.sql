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
        -- FRAGMENT SHADER (Pixel Coloring)
        -- =========================================================
        multiIf(
            -- CASE 1: DRAW WALL
            is_wall,
            CAST(
                bitOr(
                    bitOr(
                        bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_wall', 'r', w_tex_idx) * w_shade), 0),
                        bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_wall', 'g', w_tex_idx) * w_shade), 8)
                    ),
                    bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_wall', 'b', w_tex_idx) * w_shade), 16)
                )
            , 'UInt32'),

            -- CASE 2: DRAW CEILING (Textured)
            y < draw_start OR isNull(draw_start),
            CAST(
                bitOr(
                    bitOr(
                        bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_ceiling_data', 'r', f_tex_idx) * f_shade), 0),
                        bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_ceiling_data', 'g', f_tex_idx) * f_shade), 8)
                    ),
                    bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_ceiling_data', 'b', f_tex_idx) * f_shade), 16)
                )
            , 'UInt32'),

            -- CASE 3: DRAW FLOOR (Textured)
            CAST(
                bitOr(
                    bitOr(
                        bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_floor_data', 'r', f_tex_idx) * f_shade), 0),
                        bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_floor_data', 'g', f_tex_idx) * f_shade), 8)
                    ),
                    bitShiftLeft(toUInt32(dictGet('doomhouse.dict_tex_floor_data', 'b', f_tex_idx) * f_shade), 16)
                )
            , 'UInt32')
        ) AS final_color
        
    FROM
    (
        SELECT
            x,
            arrayJoin(range(0, 480)) AS y, -- Vertical Rasterization
            
            valid_x, valid_y,
            
            -- Pass through Camera Vectors for Floor Calculation
            p_dir_x, p_dir_y, p_plane_x, p_plane_y,
            
            -- Geometry Checks
            (not isNull(draw_start) AND y >= draw_start AND y <= draw_end) AS is_wall,
            ifNull(draw_start, 240) AS draw_start, 
            ifNull(draw_end, 240) AS draw_end,
            
            -- =========================================================
            -- WALL SHADING & TEXTURING
            -- =========================================================
            least(1.0, 4.0 / (ifNull(z_depth, 100.0) + 0.1)) AS w_shade,
            
            -- Wall Texture Index
            toUInt64(
                (ifNull(tex_u, 0) + 
                bitAnd(
                    toUInt32((y - draw_start) * (512 / (abs(draw_end - draw_start) + 0.01))), 
                    511
                ) * 512) + 1
            ) AS w_tex_idx,

            -- =========================================================
            -- FLOOR/CEILING CALCULATION
            -- =========================================================
            -- 1. Calculate floor distance for this row (y)
            -- Distance = H / (2 * y - H)
            240 / (abs(y - 240) + 0.01) AS row_dist,
            
            -- 2. Calculate Ray Direction for this column (x)
            -- We reconstruct the ray vector here to project the floor pixel
            (p_dir_x + p_plane_x * (2.0 * x * (1.0/640.0) - 1.0)) AS r_dir_x,
            (p_dir_y + p_plane_y * (2.0 * x * (1.0/640.0) - 1.0)) AS r_dir_y,
            
            -- 3. Project to World Coordinates
            (valid_x + row_dist * r_dir_x) AS map_x,
            (valid_y + row_dist * r_dir_y) AS map_y,
            
            -- 4. Calculate Texture Index
            toUInt64(
                bitAnd(toInt32(map_y * 512), 511) * 512 + 
                bitAnd(toInt32(map_x * 512), 511) + 
                1
            ) AS f_tex_idx,
            
            -- 5. Floor Shading (Distance Fog)
            (1.0 - least(row_dist * 0.125, 1.0)) AS f_shade

        FROM
        (
            -- =========================================================
            -- Z-BUFFER / OCCLUSION (BSP Simulation)
            -- =========================================================
            SELECT
                all_x.x AS x,
                any(valid_x) AS valid_x, any(valid_y) AS valid_y,
                any(dir_x) AS p_dir_x, any(dir_y) AS p_dir_y,
                any(plane_x) AS p_plane_x, any(plane_y) AS p_plane_y,
                
                -- Select the CLOSEST wall for this column
                argMin(draw_start, z_depth_val) AS draw_start,
                argMin(draw_end, z_depth_val) AS draw_end,
                min(z_depth_val) AS z_depth,
                argMin(tex_u, z_depth_val) AS tex_u,
                any(id) AS id
                
            FROM doomhouse.player_state AS camera
            CROSS JOIN (SELECT arrayJoin(range(0, 640)) AS x) AS all_x
            LEFT JOIN (
                SELECT
                    arrayJoin(range(screen_x_start, screen_x_end)) AS x,
                    id,
                    rz1 + ((rz2 - rz1) * ((x - screen_x_start) / (screen_x_end - screen_x_start + 0.01))) AS z_depth_val,
                    toInt32(240 - (480 * (ceil_h - 0.5) / z_depth_val)) AS draw_start,
                    toInt32(240 + (480 * (0.5 - floor_h) / z_depth_val)) AS draw_end,
                    toUInt32((x - screen_x_start) / (screen_x_end - screen_x_start + 0.01) * wall_len * 512) AS tex_u
                FROM (
                    SELECT
                        *,
                        greatest(0, least(640, if(proj_x1 < proj_x2, proj_x1, proj_x2))) AS screen_x_start,
                        least(640, greatest(0, if(proj_x1 < proj_x2, proj_x2, proj_x1))) AS screen_x_end,
                        if(proj_x1 < proj_x2, rz1, rz2) AS rz1,
                        if(proj_x1 < proj_x2, rz2, rz1) AS rz2,
                        dictGet('doomhouse.dict_bsp_segs', 'ceil', id) AS ceil_h,
                        dictGet('doomhouse.dict_bsp_segs', 'floor', id) AS floor_h,
                        sqrt(pow(dx2-dx1, 2) + pow(dy2-dy1, 2)) AS wall_len
                    FROM (
                        SELECT
                            id, dx1, dy1, dx2, dy2, rz1, rz2, rx1, rx2,
                            toInt32((640 / 2) + (rx1 / rz1) * 320.0) AS proj_x1,
                            toInt32((640 / 2) + (rx2 / rz2) * 320.0) AS proj_x2
                        FROM (
                            SELECT
                                id,
                                (dictGet('doomhouse.dict_bsp_segs', 'x1', id) - valid_x) AS dx1,
                                (dictGet('doomhouse.dict_bsp_segs', 'y1', id) - valid_y) AS dy1,
                                (dictGet('doomhouse.dict_bsp_segs', 'x2', id) - valid_x) AS dx2,
                                (dictGet('doomhouse.dict_bsp_segs', 'y2', id) - valid_y) AS dy2,
                                (dx1 * dir_x + dy1 * dir_y) AS rz1,
                                (dx2 * dir_x + dy2 * dir_y) AS rz2,
                                (dx1 * plane_x + dy1 * plane_y) AS rx1,
                                (dx2 * plane_x + dy2 * plane_y) AS rx2,
                                valid_x, valid_y, dir_x, dir_y, plane_x, plane_y
                            FROM doomhouse.player_state
                            CROSS JOIN (SELECT id FROM doomhouse.dict_bsp_segs) AS ids
                        )
                        WHERE rz1 > 0.1 AND rz2 > 0.1
                    )
                )
                WHERE screen_x_end > screen_x_start
            ) AS walls ON all_x.x = walls.x
            GROUP BY all_x.x
        )
    )
)
