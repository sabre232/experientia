---
id: c6-p2-data-eng
name: Data Engineering
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: data; engineering
keywords: data; pipeline; batch
description: Idempotent pipelines + data-quality assertions + documented conventions
source: built-in
from: eng-data
---

Data pipelines/batch jobs, follow:

Idempotent & re-entrant:
- Re-running a job gives the same result; process incrementally by partition/date — NEVER blind full-table overwrite.
- Failures resume from the checkpoint; NEVER assume a job runs only once.

Data quality:
- Add assertions on key tables (not-null, uniqueness, row-count drift thresholds); alert on anomalies then continue or halt — NEVER silently swallow dirty data.
- Document conventions (dedup rule, time window, currency/timezone) — NEVER leave them implicit in one SQL.

Security:
- Minimize sensitive fields (PII) in the pipeline; intermediate artifacts de-identified too.
- Check data volume and indexes before big queries; NEVER full-table-scan the production DB.
