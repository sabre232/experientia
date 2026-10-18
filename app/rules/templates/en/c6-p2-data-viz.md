---
id: c6-p2-data-viz
name: Visualization Standards
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: data
keywords: chart; visualization
description: Chart type fit + honest axes + less is more
source: built-in
from: data-viz
---

Making data visualizations, follow:

Chart type fits content:
- Trend -> line; comparison -> bar; composition -> stacked/pie (<=5 categories); distribution -> histogram/box; relation -> scatter.
- Ask first "what should the reader see"; NEVER force 3D/pie for looks.

Axes & honesty:
- Bar charts start Y-axis at 0 (truncation exaggerates differences); truncated line charts must be labeled.
- Dual-axis charts used sparingly; when required, state both axes' units and zero alignment.
- NEVER mislead with charts (truncation, non-linear axes, misleading color).

Less is more:
- One chart, one message; drop gridlines, borders, legends that carry no information.
- Color has meaning (distinguish/emphasize) — NEVER rainbow with no logic; color-blind friendly.

Annotation:
- Title states the conclusion; key points labeled on the chart (arrow/text) — NEVER dump coordinates for the reader to decode.
- Unit, time range, data source — the three-piece set, always.
