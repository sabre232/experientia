---
id: c4-p4-inline-comment
name: Inline comments
category: c4
priority: p4
layer: structure
trigger_default: manual
tags: engineering; comments
keywords: comment; inline; why
description: Comment only constraints and trade-offs code cannot express, never what the code does
source: built-in
---

## Rules

- Inline comments answer "why": constraints, trade-offs, non-obvious edge conditions.
- "What" is the code's job — `i += 1  # increment i` is noise; delete it.
- Workarounds must state the reason: `# remove once upstream fixes XYZ`, with issue/link.
- Comments change with the code: when behavior changes, update or delete stale comments in the same commit.
