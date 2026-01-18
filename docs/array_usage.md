I have analyzed [`src/SQL/render_view_org.sql`](src/SQL/render_view_org.sql) and can explain how these three array functions work together to implement the raycasting engine without traditional loops.

### 1. `arrayMap`: The "Loop" Replacement
In a standard programming language, raycasting uses a `while` loop to step a ray forward until it hits a wall. Since SQL is declarative and lacks imperative loops, `arrayMap` is used to process all potential steps *simultaneously* (vectorization).

**Usage 1: Calculating Distances (Lines 246 & 250)**
The engine first generates a list of steps `[1, 2, ... 25]` using `range(1, RAY_STEPS)`. `arrayMap` then transforms these step indices into actual world distances for every potential grid intersection.

```sql
-- Calculate distance to every vertical grid line (X-axis)
arrayMap(i -> (i - valid_x) / r_dir_x, steps) as d_x
```

**Usage 2: Checking for Walls (Lines 248 & 252)**
It is used again to check *every* calculated distance to see if a wall exists at that location.

```sql
-- (Simplified): Check if a wall exists at distance 'd'
arrayMap((d, i) -> 
    if(
        dictGet('doomhouse.dict_map_data', ..., coordinates) > 0, -- Is there a wall?
        d,      -- Yes: Return the distance
        999.0   -- No: Return a huge number (infinity)
    ), 
    d_x, steps
)
```

### 2. `arrayMin`: Finding the First Hit
After `arrayMap` has checked all 25 potential steps, we have an array that looks something like this: `[999.0, 999.0, 4.5, 999.0, 8.2, ...]`.
- `999.0` represents empty space.
- `4.5` is the first wall hit.
- `8.2` is a wall behind the first one.

`arrayMin` simply grabs the smallest number from this array, which corresponds to the **closest wall** the ray hit.

```sql
-- Find the nearest wall distance
arrayMin(...) as dist_x
```
This effectively simulates the "break" in a `while` loop—we only care about the first intersection.

### 3. `arraySort`: Assembling the Framebuffer
ClickHouse processes data in parallel, so the pixels for the screen (640x480) are generated in a completely random order. To display the image correctly, the pixels must be reassembled into a linear sequence (Row 0, Row 1, etc.).

**Usage (Line 103)**
```sql
arrayMap(x -> x.2, 
    arraySort(k -> k.1, 
        groupArray((y * W + x, final_color))
    )
)
```

1.  **`groupArray`**: Collects all `(position_index, color)` tuples into one giant array.
2.  **`arraySort(k -> k.1, ...)`**: Sorts this array based on the first element of the tuple (`y * W + x`), which is the pixel's linear position (0 to 307,199).
3.  **`arrayMap(x -> x.2, ...)`**: Strips away the position index, leaving just the sorted color values ready to be sent to the Python client.