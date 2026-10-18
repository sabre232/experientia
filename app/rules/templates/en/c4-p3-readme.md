---
id: c4-p3-readme
name: README upkeep
category: c4
priority: p3
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: README; docs; sync
description: README stays in sync with code: install/run/test commands must always be copy-paste runnable
source: built-in
---

## Rules

- README always has three sections: install, run, test. The commands in them must match the repo's reality (CI config is the source of truth).
- When commands / flags / directory layout change, update the README in the same commit — a commit that changes one but not the other is incomplete.
- New-developer check: can someone follow the README alone and get a local env running in 10 minutes? If not, add the missing steps.
- Delete stale sections outright; never leave "TODO update" placeholders.
