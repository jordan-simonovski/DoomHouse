CREATE MATERIALIZED VIEW doomhouse.render_materialized
TO doomhouse.rendered_frame
AS
WITH 
    -- =========================================================
    -- RESOLUTION & CONSTANTS
    -- =========================================================
    640 AS W,
    480 AS H,
    240 AS H_HALF,
    
    -- Field of View calculations (90 degrees)
    -- Focal length calculation for projection
    CAST(0.5 * W / 0.99, 'Float32') AS FOCAL_LEN, 
    512 AS TEX_SIZE,

    -- =========================================================
    -- PLAYER STATE (The "Camera")
    -- =========================================================
    -- We grab the latest input state once
    (SELECT valid_x FROM doomhouse.player_input) AS p_x,
    (SELECT valid_y FROM doomhouse.player_input) AS p_y,
    (SELECT dir_x FROM doomhouse.player_input) AS p_dir_x, -- cos(angle)
    (SELECT dir_y FROM doomhouse.player_input) AS p_dir_y, -- sin(angle)
    -- Pre-calculate perpendicular vector for rotation matrix
    (SELECT -dir_y FROM doomhouse.player_input) AS p_plane_x,
    (SELECT dir_x FROM doomhouse.player_input) AS p_plane_y

SELECT
    -- =========================================================
    -- STEP 5: FINAL FRAME BUFFER AGGREGATION
    -- =========================================================
    -- Unlike Raycasting (which is naturally sorted 0..W), projection
    -- produces unordered fragments. We must group by Screen X.
    x AS pos_x,
    0 AS pos_y, -- Placeholder, logic handles full column
    
    -- We render vertical strips. 
    -- For every X, we have a column of pixels.
    groupArray((y_pixel, color)) AS column_data

FROM
(
    SELECT
        screen_x AS x,
        y_coord AS y_pixel,
        
        -- =========================================================
        -- STEP 4: PIXEL SHADING (WALLS, FLOORS, CEILINGS)
        -- =========================================================
        multiIf(
            -- DRAW WALL
            y_coord >= draw_start AND y_coord <= draw_end,
            CAST(
                -- Calculate Texture U (horizontal) based on hit percentage along wall
                -- Calculate Texture V (vertical) based on height
                bitOr(
                    bitShiftLeft(toUInt32(dictGet('doomhouse.dict_textures', 'r', tex_idx) * shade), 0),
                    bitShiftLeft(toUInt32(dictGet('doomhouse.dict_textures', 'g', tex_idx) * shade), 8),
                    bitShiftLeft(toUInt32(dictGet('doomhouse.dict_textures', 'b', tex_idx) * shade), 16)
                )
            , 'UInt32'),
            
            -- DRAW VISIBLE FLOOR (DOOM has variable height floors)
            y_coord > draw_end,
            0x333333, -- Simple floor color (or perform floor projection math here)
            
            -- DRAW VISIBLE CEILING
            0x111111  -- Simple ceiling color
        ) AS color
        
    FROM
    (
        SELECT
            screen_x,
            -- Generate vertical pixels for this column
            arrayJoin(range(0, H)) AS y_coord,
            
            draw_start, draw_end,
            tex_u, 
            -- Interpolate texture V coordinate
            toUInt64((y_coord - draw_start) / (draw_end - draw_start + 0.01) * TEX_SIZE) * TEX_SIZE + tex_u + 1 AS tex_idx,
            
            -- Lighting based on depth
            1.0 / (depth + 0.1) * 5.0 AS shade
        FROM
        (
            SELECT
                screen_x,
                depth,
                
                -- Project Wall Heights to Screen
                -- DOOM Feature: Variable sector heights (top/bottom)
                toInt32(H_HALF - (H * (sect_ceil - 0.0) / depth)) AS draw_start,
                toInt32(H_HALF + (H * (0.0 - sect_floor) / depth)) AS draw_end,
                
                -- Texture Mapping (U coordinate)
                -- We know where we are on the screen relative to the projected wall edges
                toUInt64((screen_x - proj_x1) / (proj_x2 - proj_x1 + 0.01) * wall_length * TEX_SIZE) AS tex_u,
                
                sect_ceil, sect_floor
            FROM
            (
                -- =========================================================
                -- STEP 3: OCCLUSION & Z-BUFFERING
                -- =========================================================
                -- In Raycasting, we stop at the first wall.
                -- In Projection, we project ALL walls. 
                -- We use 'argMin' to pick the closest wall for every screen column.
                SELECT
                    screen_x,
                    argMin(trans_z, trans_z) AS depth, -- The "Z-Buffer"
                    argMin(proj_x1, trans_z) AS proj_x1,
                    argMin(proj_x2, trans_z) AS proj_x2,
                    argMin(len, trans_z) AS wall_length,
                    argMin(h_ceil, trans_z) AS sect_ceil,
                    argMin(h_floor, trans_z) AS sect_floor
                FROM
                (
                    SELECT 
                        -- =========================================================
                        -- STEP 2: RASTERIZATION (Line -> Columns)
                        -- =========================================================
                        -- "Explode" the wall segment into individual vertical strips (columns)
                        arrayJoin(range(MAX(0, toInt32(proj_x1)), MIN(W, toInt32(proj_x2)))) AS screen_x,
                        
                        -- Interpolate Z (Depth) for this specific X column for accurate Z-buffering
                        -- (Perspective correct interpolation)
                        tz1 + (tz2 - tz1) * ((screen_x - proj_x1) / (proj_x2 - proj_x1)) AS trans_z,
                        
                        proj_x1, proj_x2, 
                        dist AS len,
                        ceil_h AS h_ceil, 
                        floor_h AS h_floor,
                        tz1, tz2
                    FROM 
                    (
                        -- =========================================================
                        -- STEP 1: GEOMETRY TRANSFORMATION & CLIPPING
                        -- =========================================================
                        SELECT 
                            *,
                            -- Perspective Projection: World Space -> Screen X coordinates
                            (W/2) + (tx1 / tz1) * FOCAL_LEN AS proj_x1,
                            (W/2) + (tx2 / tz2) * FOCAL_LEN AS proj_x2
                        FROM 
                        (
                            SELECT 
                                -- 1. Translate Wall to be relative to Player
                                (x1 - p_x) AS dx1, (y1 - p_y) AS dy1,
                                (x2 - p_x) AS dx2, (y2 - p_y) AS dy2,
                                
                                -- 2. Rotate Wall around Player (World -> Camera Space)
                                (dx1 * p_dir_x + dy1 * p_dir_y) AS tz1, -- Depth Z1
                                (dx1 * p_plane_x + dy1 * p_plane_y) AS tx1, -- Lateral X1
                                
                                (dx2 * p_dir_x + dy2 * p_dir_y) AS tz2, -- Depth Z2
                                (dx2 * p_plane_x + dy2 * p_plane_y) AS tx2, -- Lateral X2
                                
                                -- Pass through properties
                                sqrt(pow(x2-x1,2) + pow(y2-y1,2)) AS dist,
                                sector_floor AS floor_h,
                                sector_ceil AS ceil_h
                                
                            FROM doomhouse.geometry_segs 
                            -- 3. Frustum Culling (Simple)
                            -- Ensure at least one point is in front of player (Z > 0)
                            WHERE ( (x1 - p_x) * p_dir_x + (y1 - p_y) * p_dir_y > 0.1 )
                               OR ( (x2 - p_x) * p_dir_x + (y2 - p_y) * p_dir_y > 0.1 )
                        )
                        -- 4. Clipping Loop (Simplified)
                        -- If a wall crosses the near plane (z=0), we must clip it mathematically
                        -- to avoid "division by zero" or "wrapping around" artifacts.
                        WHERE tz1 > 0.1 AND tz2 > 0.1 -- (Simplification: Cull walls crossing plane for this snippet)
                    )
                )
                GROUP BY screen_x
            )
        )
    )
)
ORDER BY pos_x ASC