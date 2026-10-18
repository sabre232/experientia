---
id: c4-p1-pr-description
name: PR description standard
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: PR; pull request; description
description: Summary + motivation + test plan + impact scope, four sections, none optional
source: community
---

## Rules

- Every PR description has four sections: summary (1-3 sentences), motivation (what problem / which issue), test plan (how it was verified), impact scope (which modules/users are affected).
- Summary states conclusions, not process; include key diff snippets or screenshots, never the whole diff.
- When impact touches config / data migration / API changes, state the rollback path.
- Link issues with `Fixes #123` for auto-close.
- NEVER open a PR with an empty description ("see diff" is not a description).

## Example

✅
Summary: inject block now truncates by line when over budget.
Motivation: dropping the whole block disabled low-priority rules (#42).
Tests: 2 new budget-truncation unit tests; manual check of 3 rule combinations.
Impact: proxy/inject.py only; no data migration.
