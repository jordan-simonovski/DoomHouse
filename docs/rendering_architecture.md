# DOOMHouse Rendering Architecture

This diagram illustrates the data flow and processing steps within the `render_view_org.sql` Materialized View. It details how player input is transformed into a rendered frame entirely within ClickHouse SQL.

```mermaid
flowchart TD
    %% Styling
    classDef storage fill:#e1f5fe,stroke:#01579b,stroke-width:2px;
    classDef process fill:#f3e5f5,stroke:#4a148c,stroke-width:2px;
    classDef logic fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    classDef output fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px;

    subgraph InputStage ["1. Input & Collision Detection"]
        direction TB
        PI[("doomhouse.player_input")]:::storage
        PI --> |"try_x, try_y, old_x, old_y"| CX["Collision Check X"]:::logic
        
        MD1[("dict_map_data")]:::storage -.-> CX
        
        CX --> |"valid_x_inter"| CY["Collision Check Y"]:::logic
        MD1 -.-> CY
        
        CY --> |"valid_x, valid_y"| VP["Validated Player Position"]:::process
    end

    subgraph RayGen ["2. Ray Generation"]
        direction TB
        VP --> |"pos, dir, plane"| RC["Calculate Ray Direction"]:::logic
        SC["numbers(W)<br/>(Screen Columns)"]:::storage --> RC
        
        RC --> |"r_dir_x, r_dir_y"| SA["Generate Step Arrays<br/>range(1, RAY_STEPS)"]:::process
    end

    subgraph Raycasting ["3. Vectorized Raycasting"]
        direction TB
        SA --> |"arrayMap"| XI["Calc X-Grid Intersections"]:::logic
        SA --> |"arrayMap"| YI["Calc Y-Grid Intersections"]:::logic
        
        XI --> |"arrayMap + dictGet"| WCX["Check Walls X"]:::logic
        YI --> |"arrayMap + dictGet"| WCY["Check Walls Y"]:::logic
        
        MD2[("dict_map_data")]:::storage -.-> WCX
        MD2 -.-> WCY
        
        WCX --> |"arrayMin"| MDX["Min Dist X"]:::process
        WCY --> |"arrayMin"| MDY["Min Dist Y"]:::process
    end

    subgraph HitProc ["4. Hit Processing"]
        direction TB
        MDX & MDY --> |"least()"| RHD["Raw Hit Dist & Side"]:::logic
        
        RHD --> |"Dot Product"| PWD["Perp Wall Dist<br/>(Fish-eye Correction)"]:::process
        
        PWD --> WH["Calc Wall Height<br/>(draw_start, draw_end)"]:::process
        RHD --> TC["Calc Texture Coords<br/>(hit_x_wall, hit_y_wall)"]:::process
        RHD --> BS["Calc Base Shade<br/>(Fog + Contrast)"]:::process
    end

    subgraph PixelShader ["5. Pixel Shader Pipeline"]
        direction TB
        WH & TC & BS --> PJ["Pixel Row Expansion"]:::logic
        SR["numbers(H)<br/>(Screen Rows)"]:::storage --> PJ
        
        PJ --> |"Lookup Y"| FD["Get Floor Dist"]:::logic
        FDD[("dict_floor_dist")]:::storage -.-> FD
        
        FD --> TIC["Calc Texture Indices<br/>(w_tex_idx, f_tex_idx)"]:::process
        
        TIC --> |"w_tex_idx"| WCL["Wall Color Lookup"]:::logic
        TIC --> |"f_tex_idx"| FCL["Floor/Ceil Color Lookup"]:::logic
        
        TDW[("dict_tex_wall")]:::storage -.-> WCL
        TDFC[("dict_tex_floor/ceil")]:::storage -.-> FCL
        
        WCL & FCL --> BP["Bit Packing<br/>(R,G,B -> UInt32)"]:::process
    end

    subgraph OutputStage ["6. Output Aggregation"]
        direction TB
        BP --> |"groupArray + arraySort"| FF["Final Frame Buffer<br/>Array(UInt32)"]:::output
        VP --> |"any()"| FVP["Final Player Pos"]:::output
        
        FF & FVP --> MV[("doomhouse.rendered_frame")]:::storage
    end

    %% Flow Connections
    InputStage --> RayGen
    RayGen --> Raycasting
    Raycasting --> HitProc
    HitProc --> PixelShader
    PixelShader --> OutputStage
```
