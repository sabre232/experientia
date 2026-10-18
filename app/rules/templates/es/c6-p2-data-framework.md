---
id: c6-p2-data-framework
name: Marco de análisis (tendencia → atribución → recomendación)
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: data
keywords: análisis; atribución; datos
description: análisis en tres partes, conclusión con datos
source: built-in
from: data-framework
---

Al hacer un análisis de datos, seguir las tres partes:

1. Tendencia (qué pasó):
   - Primero la tendencia global + los puntos de inflexión clave; hablar en datos (valores + ventana temporal + alcance anual/mensual).
   - Distinguir « variación estadística » de « cambio real »; no conclusiones con muestra pequeña.

2. Atribución (por qué):
   - Partir por dimensión para encontrar la contribución (por canal/región/segmento de usuarios), marcar los principales contribuyentes.
   - Distinguir correlación y causalidad; con solo prueba de correlación, escribir explícitamente « correlacionado, no causal ».
   - Listar las hipótesis por verificar; nunca escribir una conjetura como conclusión.

3. Recomendación (qué hacer):
   - Cada recomendación corresponde a un hallazgo, es ejecutable, con responsable y plazo.
   - Notar el impacto esperado y el riesgo de la recomendación; « seguir observando » es también una recomendación legítima.

Disciplina: los alcances (ventana temporal/deduplicación/unidad) se declaran al principio; cada conclusión es rastreable hasta los datos.
