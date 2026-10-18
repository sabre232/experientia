---
id: c1-p1-frontend
name: Ingeniería frontend
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: frontend; componente
description: límites de componente + gestión de estado + accesibilidad
source: built-in
from: eng-frontend
---

Desarrollo frontend — reglas:

Componentes:
- Un componente = una responsabilidad; si supera una pantalla de alto o hay responsabilidades mezcladas, partir.
- No mezclar componentes controlados y no controlados; la nomenclatura de los props sigue a la biblioteca existente.

Estado:
- Preferir localizar a globalizar; primero preguntar « este estado debe atravesar cuántos componentes », si la respuesta es ≤ 2, props/estado local.
- Los datos derivados vía useMemo/cálculo; NUNCA guardar dos estados de la misma fuente y sincronizarlos a mano.

Accesibilidad y calidad:
- Los elementos interactivos deben ser alcanzables por teclado (no botones falsos con div); los controles de formulario tienen un label.
- Tras un cambio de UI, comprobar que la consola no tiene nuevos errores/avisos antes de entregar.

NUNCA: NUNCA escribir una URL dependiente del entorno en duro en un componente; NUNCA ensuciar el CSS global para ahorrar una línea.
