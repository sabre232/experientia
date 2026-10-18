---
id: c6-p1-prd-structure
name: PRD Structure
category: c6
priority: p1
layer: structure
trigger_default: always
tags: product
keywords: PRD; requirement; product
description: Background-goal -> solution -> boundaries -> metrics
source: built-in
from: prd-structure
---

Writing a PRD, use this structure; missing items explicitly marked "none/N/A":

1. Background & problem: why, user pain + current data.
2. Goals & non-goals: this cycle's goals (quantifiable); explicit "what we won't do", to prevent scope creep.
3. Users & scenarios: target users, core scenarios (user-story form).
4. Solution: feature list + interaction flow + key screen notes; each feature prioritized (P0/P1/P2).
5. Boundaries & edge cases: empty states, error states, permissions, concurrency, data boundaries.
6. Metrics: which metric determines success post-launch.
7. Dependencies & risks: cross-team dependencies, technical risks, rollback plan.

Discipline:
- Every P0 feature has acceptance criteria.
- Assumptions (unverified) marked separately — NEVER state assumptions as facts.
