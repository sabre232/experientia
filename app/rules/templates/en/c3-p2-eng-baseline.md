---
id: c3-p2-eng-baseline
name: Build & test baseline
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: build; test; baseline
description: Run the existing tests before changing; re-run affected tests before committing
source: built-in
from: eng-general
---

Build & test (confirm before running):
- Before starting changes, run the existing tests once and record the baseline; after each change, re-run the affected modules' tests before committing.
- Build/test commands come from the repo's README, Makefile, and CI config — NEVER guess from memory.
