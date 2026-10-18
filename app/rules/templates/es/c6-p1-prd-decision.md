---
id: c6-p1-prd-decision
name: Matriz de decisión
category: c6
priority: p1
layer: structure
trigger_default: always
tags: product
keywords: decisión; elección; ponderación
description: opciones × dimensiones puntuadas ponderadas + hipótesis explícitas
source: built-in
from: prd-decision
---

Al comparar/arbitrar opciones, respetar:

Estructura:
- Listar 2-4 opciones candidatas (incluida « no hacer nada » como baseline).
- 3-6 dimensiones de evaluación (p. ej. coste, riesgo, velocidad, mantenibilidad), cada dimensión con un peso (suma = 100).
- Puntuación en la matriz (1-5), suma ponderada, la opción recomendada está marcada.

Disciplina:
- Cada puntuación tiene una frase de justificación; las dimensiones « a feeling » se marcan explícitamente subjetivas.
- Los pesos se justifican (por qué esta dimensión pesa más); NUNCA partir de una distribución igual por defecto.
- Listar las hipótesis clave (qué puntuaciones dependen de una premisa no verificada); si una hipótesis cambia, la conclusión se recalcula.

Salida:
- Opción recomendada + razón en una frase + riesgo principal + condición de disparo « cuándo se cambia de opción ».
- NUNCA dar solo puntuaciones sin razonamiento.
