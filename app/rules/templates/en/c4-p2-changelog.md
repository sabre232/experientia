---
id: c4-p2-changelog
name: Changelog rules
category: c4
priority: p2
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: changelog; release notes; version
description: Group by Added/Changed/Fixed/Removed, write for users, no internal jargon
source: community
---

## Rules

- Changelog is sectioned by version; within a section, entries are grouped as Added / Changed / Fixed / Removed.
- Write each entry for the end user: "release notes are now archived weekly", not "refactor archive job".
- Breaking changes go to the top, marked `BREAKING`, with migration steps.
- Internal refactors and dependency bumps with no user-visible change do not belong in the changelog.
- At release time, generate a draft from commits and revise by hand — NEVER publish the machine-generated version as-is.
