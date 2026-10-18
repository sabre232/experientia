---
id: c3-p2-deploy
name: Deployment & Ops
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: deploy; release; ops
description: Pre-deploy checkpoints + rollback plan + change trail
source: built-in
from: eng-deploy
---

Deployment/ops, follow:

Pre-deploy checkpoints (hard constraint) — output and wait for confirmation:
- List: blast radius (which services/environments), data migration (steps if any), expected downtime, rollback plan.
- For production/irreversible operations, stop and wait for explicit confirmation — NEVER auto-execute.

Rollback plan:
- For every change, first think "how do we roll back"; if no safe rollback path, take a backup/snapshot first.
- Data migrations written as re-entrant scripts (re-running does not double-apply).

Change trail:
- Record change content, executor, timestamp; NEVER modify production config without a trace.
- Secrets/certificates stay in secret management, never in the repo; NEVER expose them in logs/screenshots.

NEVER: NEVER run untested SQL directly on the production DB; NEVER change multiple interdependent services at once.
