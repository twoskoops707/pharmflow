# FamFlow sequence logic (high-school level)

One **sequence** = one full run on one phone. The farm schedules ~**15 sequences per hour per phone**, spread through the hour (not all at once).

```mermaid
flowchart TB
  subgraph FARM["Farm schedule (each phone)"]
    H["Hour starts → build ~15 time slots<br/>(each phone has different spacing)"]
    W["Wait until that phone's next slot"]
    D{"Is it time for the<br/>1 ad this hour?"}
    P["Pick a sequence JSON<br/>Prefer unused ad slot + unused<br/>material / concentrate / heater combo"]
    RUN["Run the sequence"]
    MEM["Remember what we used<br/>(ad_key + combo) so next pick differs"]
    H --> W --> D
    D -->|yes → Path 3 pool| P
    D -->|no → Path 1 or 2| P
    P --> RUN --> MEM --> W
  end

  subgraph SEQ["Inside every sequence"]
    I["1. rotate_identity<br/>Scramble browser (new UA / model)<br/>Same idea as the EXE scramble mode"]
    F["2. ensure_fingerprint<br/>Check browser headers look right"]
    C["3. clear_cookies<br/>Wipe Chromium site data"]
    L["4. Open Chromium<br/>Dismiss FRE Skip only if splash is up"]
    O["5. open_url getdabflow.app<br/>~1.5s later: tap Age Yes<br/>(no FRE dump loop)"]
    A["6. Safety retap Age Yes"]
    S["7. Select material → concentrate → heater<br/>(real different screen coordinates)"]
    T["8. Scroll to reveal Start Perfect Dab<br/>Tap it and confirm the timer is running"]
    I --> F --> C --> L --> O --> A --> S --> T
  end

  RUN -.-> I

  T --> PATH{"Which path?"}

  PATH -->|Path 2 halfway| P2["Wait ~45–60s<br/>Close app<br/>(no session notes, no ad)"]
  PATH -->|Path 1 complete| P1["Timer wait ~78–84s<br/>Session notes → Skip quickly<br/>Open 1–3 tabs (stats / glass / settings)<br/>Scroll each tab toward the bottom<br/>Close app"]
  PATH -->|Path 3 ad| P3["Timer wait ~78–84s<br/>Session notes → Skip quickly<br/>Do exactly ONE ad click<br/>Close app"]

  P3 --> A3A["3A Home ads<br/>Scroll depth by ordinal:<br/>2 / 4 / 6 / 8 flicks<br/>then tap sponsored area"]
  P3 --> A3T["3B / 3C / 3D Tab ads<br/>Open tab → scroll depth 2 or 5<br/>Do NOT slam to absolute bottom first"]
  A3A --> AD["Short fill wait 0.6–1.2s<br/>Tap ad → view ~8–14s<br/>BACK → Age Yes if needed"]
  A3T --> AD
```

## Why ads used to look the same
We used to scroll **all the way to the bottom every time**, then tap near the same Y. That hits the same Sponsored unit. Now each ad ordinal uses a **different scroll depth**, and the farm **refuses recently used ad keys** (`home:0`, `stats:1`, etc.).

## Your notes

### What looks wrong?


### What should change?


### Ideas

