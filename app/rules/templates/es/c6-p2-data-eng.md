---
id: c6-p2-data-eng
name: Ingeniería de datos
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: data; engineering
keywords: datos; pipeline; batch
description: pipeline idempotente + assertions de calidad + doc de los alcances
source: built-in
from: eng-data
---

Pipeline de datos / procesamiento por lotes — reglas:

Idempotencia y reejecutabilidad:
- Una reejecución da el mismo resultado; procesamiento incremental por partición/fecha, nunca borrón y cuenta nueva de toda la tabla.
- El fallo es recuperable desde un punto de control; nunca suponer que la tarea corre solo una vez.

Calidad de datos:
- Assertions en las tablas críticas (no nulo, único, umbral de variación de filas); ante una anomalía, alertar primero y luego continuar o parar, nunca tragar silenciosamente datos sucios.
- Los alcances (regla de deduplicación, ventana temporal, divisa/hora) se documentan; nunca que un alcance exista solo en un trozo de SQL.

Seguridad:
- Los campos sensibles (PII) se minimizan en el pipeline; los productos intermedios también se anonimizan.
- Antes de una consulta grande, verificar el volumen y los índices; nunca un escaneo de tabla completa en la base de producción.
