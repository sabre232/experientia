---
id: c6-p1-prd-structure
name: Estructura de PRD
category: c6
priority: p1
layer: structure
trigger_default: always
tags: product
keywords: PRD; requisito; producto
description: contexto-objetivo → opción → límites → medición
source: built-in
from: prd-structure
---

Al escribir una PRD, seguir esta estructura; un faltante se escribe explícitamente « ninguno / no aplicable »:

1. Contexto y problema: por qué se hace, puntos de dolor del usuario + datos del estado actual.
2. Objetivos y no-objetivos: objetivo de esta iteración (cuantificable); precisar « qué no se hace », para evitar el desborde de alcance.
3. Usuarios y escenarios: audiencia, escenarios clave (en formato user story).
4. Opción: lista de funcionalidades + flujo de interacción + descripción de las pantallas clave; cada funcionalidad con una prioridad (P0/P1/P2).
5. Límites y casos límite: estado vacío, estado de error, permisos, concurrencia, límites de datos.
6. Medición: qué indicadores post-misión en línea para juzgar el éxito.
7. Dependencias y riesgos: dependencias interequipos, riesgos técnicos, plan de rollback.

Disciplina:
- Cada funcionalidad P0 tiene criterios de aceptación.
- Las hipótesis (no verificadas) se aíslan; NUNCA escribir una hipótesis como un hecho.
