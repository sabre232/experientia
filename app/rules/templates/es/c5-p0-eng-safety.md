---
id: c5-p0-eng-safety
name: Límites de seguridad de ingeniería
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: engineering; security
keywords: secrets; CI; borrado; seguridad
description: no secrets en el repo, no tocar CI/bloqueo de dependencias a la ligera, parar y preguntar en una operación irreversible
donts: |
  - NUNCA commitear secrets, tokens, direcciones de intranet en el código o la configuración
  - NUNCA modificar la configuración CI, el bloqueo de versiones de dependencias, salvo que la tarea lo exija explícitamente
  - Antes de borrar datos/archivos, confirmar el alcance de impacto; en una operación irreversible, parar y preguntar
source: research
from: eng-general
---

Límites de seguridad NUNCA:
- NUNCA commitear secrets, tokens, direcciones de intranet en el código o la configuración.
- NUNCA modificar la configuración CI, el bloqueo de versiones de dependencias, salvo que la tarea lo exija explícitamente.
- Antes de borrar datos/archivos, confirmar el alcance de impacto; en una operación irreversible, parar y preguntar.
