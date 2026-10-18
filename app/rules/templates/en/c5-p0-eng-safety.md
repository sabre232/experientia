---
id: c5-p0-eng-safety
name: Engineering safety boundaries
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: engineering; security
keywords: secrets; CI; deletion; safety
description: No secrets in code, don't touch CI/lockfiles, stop before irreversible ops
donts: |
  - NEVER commit secrets, tokens, or internal network addresses to code or config
  - NEVER modify CI config or dependency lock files unless the task explicitly requires it
  - Confirm blast radius before deleting data/files; stop and ask for irreversible operations
source: research
from: eng-general
---

NEVER safety boundaries:
- NEVER commit secrets, tokens, or internal network addresses to code or config.
- NEVER modify CI config or dependency lock files unless the task explicitly requires it.
- Confirm blast radius before deleting data/files; stop and ask for irreversible operations.
