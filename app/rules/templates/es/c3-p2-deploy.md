---
id: c3-p2-deploy
name: Despliegue / explotación
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: despliegue; puesta en producción; explotación
description: puntos de confirmación antes del despliegue + plan de rollback + trazabilidad de cambios
source: built-in
from: eng-deploy
---

Despliegue/explotación — reglas:

Antes del despliegue, emitir los puntos de confirmación y esperar validación (restricción dura):
- Listar: alcance de impacto (qué servicios/entornos), migración de datos (pasos si los hay), tiempo de indisponibilidad estimado, plan de rollback.
- En producción/operación irreversible, parar y esperar una confirmación explícita; NUNCA ejecutar automáticamente.

Plan de rollback:
- En cada cambio, primero preguntarse « cómo se hace rollback »; sin una ruta de rollback segura, hacer primero backup/snapshot.
- Las migraciones de datos como scripts reejecutables (una reejecución no aplica dos veces).

Trazabilidad de cambios:
- Anotar el contenido del cambio, el ejecutante, la marca de tiempo; NUNCA modificar una configuración de producción sin rastro.
- Los secrets/certificados nunca entran en el repo, pasan por gestión de secrets; NUNCA exponerlos en logs/capturas de pantalla.

NUNCA: NUNCA ejecutar SQL no probado directamente en la base de producción; NUNCA modificar en paralelo varios servicios que se dependen.
