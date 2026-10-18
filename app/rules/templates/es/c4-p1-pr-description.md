---
id: c4-p1-pr-description
name: Norma de descripción de PR
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: PR; merge request; descripción
description: resumen del cambio + motivación + plan de test + alcance de impacto, las cuatro partes son obligatorias
source: community
---

## Reglas

- Descripción de PR en cuatro partes fijas: resumen del cambio (1-3 frases), motivación (qué problema resuelve / qué issue), plan de test (cómo se verifica), alcance de impacto (qué módulos/usuarios afectados).
- El resumen da la conclusión, no el desarrollo; pegar un fragmento de diff clave o una captura, no todo el diff.
- Si el alcance de impacto toca configuración/migración de datos/cambio de API, indicar obligatoriamente el método de rollback.
- Vincular el issue con `Fixes #123` para cerrarlo automáticamente.
- NUNCA abrir una PR sin descripción (« ver el diff » no cuenta como descripción).

## Ejemplo

✅
Resumen: cuando el bloque de inyección supera el presupuesto, se pasa a truncado línea por línea.
Motivación: descartar todo el bloque desactivaba todas las reglas de baja prioridad (#42).
Tests: 2 tests unitarios añadidos para el truncado de presupuesto; verificación manual de 3 combinaciones de reglas.
Impacto: solo proxy/inject.py; sin migración de datos.
