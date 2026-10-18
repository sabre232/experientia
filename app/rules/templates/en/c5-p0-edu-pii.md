---
id: c5-p0-edu-pii
name: Student Privacy (no PII)
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: education; privacy
keywords: student; privacy; education
description: PII de-identification + minimization + compliance
donts: |
  - NEVER keep student names, IDs, family info, addresses, contact info — any identifiable info — in outputs/intermediate artifacts
  - NEVER casually export full student records
  - NEVER send student data to external online services
source: built-in
from: edu-pii
---

Handling education/student data, follow:

PII discipline:
- NEVER keep student names, IDs, family info, addresses, contact info — any identifiable info — in outputs/intermediate artifacts.
- De-identify before processing: replace identity fields with codes/placeholders; analysis keeps only necessary fields.

Minimization:
- Take only the fields the task needs — NEVER casually export full student records.
- Grades/behavior data prefer "aggregated presentation" (class distribution) over individually identifiable.

Compliance:
- Follow applicable law (FERPA / local student-privacy law); when unsure, don't process the field by default.
- Data never leaves the local machine — NEVER send student data to external online services.

Discipline:
- PII found mixed in the data? Stop, de-identify, then continue.
- This template is not legal advice; consult the school's legal/privacy officer on compliance.
