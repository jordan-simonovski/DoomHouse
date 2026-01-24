CREATE MATERIALIZED VIEW doomhouse.player_state_mv
TO doomhouse.player_state
AS
SELECT
    final_x AS valid_x,
    final_y AS valid_y,
    input.dir_x AS dir_x,
    input.dir_y AS dir_y,
    input.plane_x AS plane_x,
    input.plane_y AS plane_y
FROM doomhouse.player_input_raw AS input
CROSS JOIN
(
    -- =========================================================
    -- PASS 2: RESOLVE Y MOVEMENT
    -- =========================================================
    -- We take the safe X from Pass 1 and try to move Y.
    -- If Y hits a wall, we keep the old Y (Sliding effect).
    SELECT
        safe_x AS final_x,
        if(min(dist_y) < 0.3, old_y_val, try_y_val) AS final_y
    FROM
    (
        SELECT
            safe_x,
            old_y_val, try_y_val,
            -- Vector Math: Distance from Point (safe_x, try_y) to Line Segment (x1,y1->x2,y2)
            sqrt(pow(safe_x - closest_x, 2) + pow(try_y_val - closest_y, 2)) AS dist_y
        FROM
        (
            SELECT
                -- Geometry from Pass 1
                r1.safe_x,
                input.try_y AS try_y_val,
                input.old_y AS old_y_val,
                
                -- Wall Segment Vectors
                seg.x1, seg.y1, seg.x2, seg.y2,
                (seg.x2 - seg.x1) as wall_dx,
                (seg.y2 - seg.y1) as wall_dy,
                
                -- Projection Factor 't'
                ((r1.safe_x - seg.x1) * wall_dx + (input.try_y - seg.y1) * wall_dy) / (pow(wall_dx, 2) + pow(wall_dy, 2) + 0.0001) as t_raw,
                greatest(0.0, least(1.0, t_raw)) as t,
                
                -- Closest Point on Wall
                seg.x1 + t * wall_dx as closest_x,
                seg.y1 + t * wall_dy as closest_y
                
            FROM doomhouse.player_input_raw AS input
            CROSS JOIN (SELECT arrayJoin(range(1, 9)) AS id) AS wall_iter -- Reduced range
            CROSS JOIN
            (
                -- =========================================================
                -- PASS 1: RESOLVE X MOVEMENT
                -- =========================================================
                SELECT 
                    if(min(dist_x) < 0.3, old_x_val, try_x_val) AS safe_x
                FROM 
                (
                    SELECT 
                        old_x_val, try_x_val,
                        -- Distance from Point (try_x, old_y) to Line
                        sqrt(pow(try_x_val - closest_x, 2) + pow(old_y_val - closest_y, 2)) AS dist_x
                    FROM
                    (
                        SELECT
                            input.try_x AS try_x_val,
                            input.old_y AS old_y_val,
                            input.old_x AS old_x_val,
                            
                            dictGet('doomhouse.dict_bsp_segs', 'x1', id) as x1,
                            dictGet('doomhouse.dict_bsp_segs', 'y1', id) as y1,
                            dictGet('doomhouse.dict_bsp_segs', 'x2', id) as x2,
                            dictGet('doomhouse.dict_bsp_segs', 'y2', id) as y2,
                            
                            (x2 - x1) as w_dx, (y2 - y1) as w_dy,
                            
                            -- Projection 't'
                            ((try_x_val - x1) * w_dx + (old_y_val - y1) * w_dy) / (pow(w_dx, 2) + pow(w_dy, 2) + 0.0001) as t,
                            
                            x1 + greatest(0.0, least(1.0, t)) * w_dx as closest_x,
                            y1 + greatest(0.0, least(1.0, t)) * w_dy as closest_y
                        FROM doomhouse.player_input_raw AS input
                        CROSS JOIN (SELECT arrayJoin(range(1, 9)) AS id) AS ids -- Reduced range
                    )
                )
                GROUP BY old_x_val, try_x_val
            ) AS r1
            LEFT JOIN doomhouse.dict_bsp_segs AS seg ON wall_iter.id = seg.id
        )
    )
    GROUP BY safe_x, old_y_val, try_y_val
) AS r2
