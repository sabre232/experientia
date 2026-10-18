---
id: c6-p2-prd-stories
name: User Stories (with acceptance criteria)
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: product
keywords: user story; acceptance criteria
description: Standard form + Given-When-Then acceptance
source: built-in
from: prd-stories
---

Writing user stories, follow:

Standard form:
As a [role], I want [capability], so that [value/benefit].
- Role specific (not "user" but "free user registered <3 days ago").
- Value real — NEVER empty "improve experience".

Acceptance criteria (required for every story):
Given-When-Then:
- Given [precondition], When [action], Then [observable result].
- Cover happy path + at least one edge (empty, failure, no permission).

Splitting discipline:
- One story = one independently deliverable capability; split if too big, merge if too small.
- Mark dependencies between stories (A depends on B first).

NEVER: NEVER put implementation into the story (stories say "what", not "how").
