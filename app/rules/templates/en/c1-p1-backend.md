---
id: c1-p1-backend
name: Backend API Engineering
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: API; backend; endpoint
description: Contract first + error semantics + idempotency & boundaries
source: built-in
from: eng-backend
---

Backend/API development, follow:

Contract:
- Define input/output schema before implementation; when the contract changes, change docs/tests first, then code.
- Outward field naming consistent with existing APIs; NEVER multiple spellings for the same meaning.

Errors & status:
- Correct HTTP status codes (4xx client, 5xx server); error bodies carry a machine-readable code + human-readable message.
- NEVER swallow exceptions and return 200 with an empty body; handle or throw.

Idempotency & boundaries:
- Write operations (especially money-related) consider an idempotency key; NEVER assume a request arrives only once.
- Validate all inputs (type/range/length); NEVER trust the caller.

Logging:
- Log "what happened + key context"; NEVER log secrets, tokens, or sensitive fields from full request bodies.
