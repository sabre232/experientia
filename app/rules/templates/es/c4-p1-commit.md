---
id: c4-p1-commit
name: Formato del mensaje de commit
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: commit; Conventional Commits
description: Conventional Commits: type(scope): título verbo+objeto + cuerpo opcional con motivación
source: community
---

## Reglas

- Título en Conventional Commits: `type(scope): frase verbo+objeto`, p. ej. `fix(auth): corregir el refresh de token expirado`.
- type limitado a: feat / fix / docs / refactor / test / chore / perf / ci.
- Título ≤ 72 caracteres, dice « qué se hizo »; el cuerpo (opcional) dice « por qué », sin repetir el contenido del diff.
- Un commit = una sola cosa; mezclar « refactor + nueva función » se parte en dos commits.
- NUNCA commitear un título sin información como « fix » / « update » / « wip ».

## Ejemplos

✅ `fix(inject): truncar línea por línea cuando se supera el presupuesto, en vez de descartar todo el bloque`
❌ `fix`, `actualización de código`, `wip`
