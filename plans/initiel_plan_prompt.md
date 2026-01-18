
Act as an expert in ClickHouse SQL and Computer Graphics. I need a comprehensive technical plan and proof-of-concept code for implementing a **Wolfenstein 3D-style raycasting engine entirely within a single ClickHouse SQL query**.

The goal is to generate a static frame that replicates the visual style of the attached image (gray textured walls, brown tiled floor, blue ceiling/void).

Please structure the plan as follows:

1.  **The Map Data Structure:** How to represent a 2D grid map (walls vs. empty space) using ClickHouse arrays or temporary tables.
2.  **The Screen Buffer:** Use the approach described in the 'ADSB Flight Data' blog post (using `groupBitmap`, `arrayJoin`, or coordinate grids) to generate a set of X, Y pixel coordinates representing a 320x240 (or similar) resolution.
3.  **The Raycasting Logic (DDA):** Explain how to implement the Digital Differential Analyzer (DDA) algorithm using ClickHouse mathematical functions (`tan`, `cos`, `floor`) to cast rays from a fixed camera position for every horizontal pixel column.
4.  **Procedural Texturing:** Since we cannot load external assets, detail how to generate pseudo-random noise or checkerboard patterns using `cityHash`, modulo arithmetic, or coordinate hashing to mimic the gray stone and floor tiles seen in the image.
5.  **Output Formatting:** Provide the SQL logic to combine these calculations into a renderable format (e.g., constructing a valid PPM binary string or a hex dump that can be interpreted as an image).

**Constraints:**
*   No external UDFs; use native ClickHouse functions only.
*   The output must be a query that, when run, produces the visual data.