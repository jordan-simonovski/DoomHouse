# DOOMHouse Post-Processing Architecture

This diagram illustrates the "Fast Gaussian Blur" pipeline implemented in `post_process_view.sql`. The rendering engine splits the workload into 4 parallel Materialized Views. This diagram shows the logic for **one single view** (e.g., Quarter 1).

```mermaid
flowchart TD
    %% Styling
    classDef storage fill:#e1f5fe,stroke:#01579b,stroke-width:2px;
    classDef process fill:#f3e5f5,stroke:#4a148c,stroke-width:2px;
    classDef logic fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    classDef output fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px;

    subgraph InputStage ["1. Input"]
        RF[("rendered_frame_N")]:::storage --> AS["Array Setup<br/>(Source Image)"]:::process
    end

    subgraph NeighborGen ["2. Neighbor Generation (Array Shifting)"]
        AS --> L["Left Array<br/>(Shift Right 1)"]:::logic
        AS --> R["Right Array<br/>(Shift Left 1)"]:::logic
        AS --> U["Up Array<br/>(Shift Right W)"]:::logic
        AS --> D["Down Array<br/>(Shift Left W)"]:::logic
        AS --> C["Center Array<br/>(Source)"]:::logic
    end

    subgraph SWAR ["3. SWAR Blur Kernel"]
        direction TB
        note[("Formula: (Center*4 + Left + Right + Up + Down) / 8")]
        
        L & R & U & D & C --> CS["Channel Split"]:::process
        
        CS --> RB["Red/Blue Path<br/>(Mask: 0x00FF00FF)"]:::logic
        CS --> G["Green Path<br/>(Mask: 0x0000FF00)"]:::logic
        
        RB --> RBS["Weighted Sum<br/>(C*4 + Neighbors)"]:::process
        G --> GS["Weighted Sum<br/>(C*4 + Neighbors)"]:::process
        
        RBS --> RBD["Divide by 8<br/>(BitShift Right 3)"]:::process
        GS --> GD["Divide by 8<br/>(BitShift Right 3)"]:::process
        
        RBD & GD --> REC["Recombine Channels<br/>(BitOr)"]:::output
    end

    subgraph OutputStage ["4. Output"]
        REC --> RFP[("rendered_frame_post_processed_N")]:::storage
    end

    %% Flow
    InputStage --> NeighborGen
    NeighborGen --> SWAR
    SWAR --> OutputStage
```
