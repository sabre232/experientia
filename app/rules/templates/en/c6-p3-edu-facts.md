---
id: c6-p3-edu-facts
name: Fact-Verification Marking
category: c6
priority: p3
layer: structure
trigger_default: smart
tags: education
keywords: fact; verify; teaching
description: Fact grading + to-verify marking + sources
source: built-in
from: edu-facts
---

Writing teaching/science content, grade facts:

Fact grading:
- Confident (authoritative source, verifiable): write it, cite the source.
- To-verify (in memory but unsure / source doubtful): mark "[to verify]" — NEVER present as established.
- Disputed (scholarly disagreement): state "views differ", list the main positions.

Discipline:
- Verify numbers, dates, names, citations one by one; unverifiable items marked "[to verify]" and listed at the end.
- Textbook/exam content follows the specified version's convention; version mismatches flagged.
- Never treat "generally" / "reportedly" as a source.

Output:
- Body (with inline [to verify] marks) + end-of-doc "to-verify list" (each: content + why doubtful + suggested verification source).
- Remind the user: [to verify] items must be human-verified before formal use.

NEVER: NEVER fabricate plausible-looking authoritative sources/page numbers to fill gaps.
