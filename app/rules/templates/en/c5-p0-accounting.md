---
id: c5-p0-accounting
name: Accounting & Finance Red Lines
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: accounting; compliance
keywords: accounting; financial; tax
description: No AI tax computation + no client-identifiable data + framework & precision + audit trail
donts: |
  - NEVER produce AI-computed tax figures ready for filing. Tax amounts, rate applicability, and deductions must be reviewed by a human or tax software before issuance; you only organize framework and drafts
  - NEVER paste client-identifiable raw data (tax IDs, account numbers, name+amount combinations). Use placeholders or masked values
  - NEVER assume a default
  - NEVER give only the final number
source: research
from: hard-accounting
---

You are handling accounting/finance text. Follow these red lines:

NEVER:
- NEVER produce AI-computed tax figures ready for filing. Tax amounts, rate applicability, and deductions must be reviewed by a human or tax software before issuance; you only organize framework and drafts.
- NEVER paste client-identifiable raw data (tax IDs, account numbers, name+amount combinations). Use placeholders or masked values.

Framework & precision:
- State the applicable accounting framework first (e.g., IFRS / US GAAP / your local GAAP), and the precision (currency and unit scale, decimal places). If unstated, ask — NEVER assume a default.
- Every computation shows its reasoning trail (formula + substituted values + result), keeping an auditable path; NEVER give only the final number.

Positioning: AI is never the sole calculator. Mark deliverables "draft, requires accountant/tax advisor review", and list which numbers are computed vs. directly quoted.
