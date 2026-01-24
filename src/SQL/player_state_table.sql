CREATE TABLE doomhouse.player_state
(
    valid_x Float64,
    valid_y Float64,
    dir_x Float64,
    dir_y Float64,
    plane_x Float64,
    plane_y Float64
)
ENGINE = Memory 
SETTINGS min_rows_to_keep = 1, max_rows_to_keep = 1;
