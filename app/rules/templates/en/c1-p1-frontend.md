---
id: c1-p1-frontend
name: Frontend Engineering
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: frontend; component
description: Component boundaries + state management + accessibility
source: built-in
from: eng-frontend
---

Frontend development, follow:

Components:
- Single responsibility; split when a component exceeds a screen height or mixes concerns.
- Don't mix controlled and uncontrolled components; prop names match the existing component library.

State:
- Keep state local when possible; first ask "how many components does this state need to cross" — answer <=2 means props/local state.
- Derive data with useMemo/computation; NEVER store two copies of the same source and sync manually.

Accessibility & quality:
- Interactive elements must be keyboard-reachable (real button, not a fake div); form controls have labels.
- After UI changes, check the console for no new errors/warnings before delivery.

NEVER: NEVER hard-code environment-specific URLs in components; NEVER introduce global CSS pollution to save a line.
