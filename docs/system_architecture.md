# DOOMHouse Architecture

## Render Engine Pipeline

The following diagram illustrates the pipeline architecture of the DOOMHouse Render Engine. Note that the rendering process is parallelized across four "quarters" of the screen (x4), but for simplicity, only one pipeline is shown below.

```mermaid
graph TD
    %% Styles
    classDef client fill:#f9f,stroke:#333,stroke-width:2px;
    classDef table fill:#e1f5fe,stroke:#0277bd,stroke-width:2px;
    classDef view fill:#fff9c4,stroke:#fbc02d,stroke-width:2px,stroke-dasharray: 5 5;
    classDef dict fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef source fill:#f3e5f5,stroke:#7b1fa2,stroke-width:1px;

    %% Client
    Client[Python Client<br/>DOOMHouse.py]:::client

    %% Input Table
    InputTable[doomhouse.player_input]:::table
    Client -->|INSERT| InputTable

    %% Dictionaries & Sources
    subgraph DataSources [Data Sources]
        direction TB
        MapSource[map_source]:::source --> MapDict[dict_map_data]:::dict
        FloorSource[floor_dist_source]:::source --> FloorDict[dict_floor_dist]:::dict
        
        subgraph TextureDictionaries [Texture Dictionaries]
            TexWSource[tex_wall_source]:::source --> TexWDict[dict_tex_wall_data]:::dict            
            TexFSource[tex_floor_source]:::source --> TexFDict[dict_tex_floor_data]:::dict
            TexCSource[tex_ceiling_source]:::source --> TexCDict[dict_tex_ceiling_data]:::dict
        end
    end

    %% Rendering Pipeline (Single Logical Flow)
    subgraph RenderPipeline ["Render Pipeline (x4 Parallel)"]
        direction TB
        
        RV["render_materialized_N<br/>(Raycasting, Texture Mapping,<br/>Shading, Pixel Packing)"]:::view
        RF["rendered_frame_N<br/>(Raw Frame Buffer)"]:::table
        PPV["post_process_materialized_N<br/>(SWAR Smoothing/Blur)"]:::view
        RPP["rendered_frame_post_processed_N<br/>(Final Frame Buffer)"]:::table
        
        InputTable -.->|Trigger| RV
        RV -->|Populate| RF
        RF -.->|Trigger| PPV
        PPV -->|Populate| RPP
    end

    %% Dictionary Dependencies
    MapDict -.-> RV
    FloorDict -.-> RV
    TexWDict -.-> RV    
    TexFDict -.-> RV
    TexCDict -.-> RV

    %% Output
    RPP -->|SELECT| Client
```
