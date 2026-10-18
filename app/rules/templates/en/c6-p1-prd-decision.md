---
id: c6-p1-prd-decision
name: Decision Matrix
category: c6
priority: p1
layer: structure
trigger_default: always
tags: product
keywords: decision; trade-off; selection
description: Options x weighted dimensions + explicit assumptions
source: built-in
from: prd-decision
---

Doing option trade-offs/selection, follow:

Structure:
- List 2-4 candidate options (including "do nothing" as baseline).
- 3-6 evaluation dimensions (cost, risk, speed, maintainability...), each weighted (sum=100).
- Score the matrix (1-5), weighted sum, mark the recommended option.

Discipline:
- Each score gets a one-line reason; "gut feel" dimensions marked subjective.
- Weights themselves justified (why this dimension weighs more) — NEVER default to equal weight.
- List key assumptions (which scores rest on unverified premises); if an assumption changes, recompute.

Output:
- Recommended option + one-line reason + main risk + the trigger condition that would switch the choice.
- NEVER give scores without reasoning.
