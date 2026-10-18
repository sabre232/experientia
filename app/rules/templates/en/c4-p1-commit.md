---
id: c4-p1-commit
name: Commit message format
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: commit; Conventional Commits; message
description: Conventional Commits: type(scope): verb phrase + optional body for why
source: community
---

## Rules

- Title follows Conventional Commits: `type(scope): verb phrase`, e.g. `fix(auth): refresh expired tokens`.
- Allowed types: feat / fix / docs / refactor / test / chore / perf / ci.
- Title ≤ 72 chars, states what changed; optional body states why — never restate the diff.
- One commit does one thing; split "refactor + feature" into two commits.
- NEVER commit "fix" / "update" / "wip" style titles with no information.

## Examples

✅ `fix(inject): truncate by line when rule budget overflows instead of dropping the block`
❌ `fix`, `update code`, `wip`
