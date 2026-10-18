---
id: c6-p2-prd-stories
name: User stories (con criterios de aceptación)
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: product
keywords: user story; criterios de aceptación
description: formulación estándar + aceptación Given-When-Then
source: built-in
from: prd-stories
---

Al escribir user stories, respetar:

Formulación estándar:
Como [rol], quiero [capacidad] para [valor/beneficio].
- El rol es preciso (no « un usuario » sino « un usuario gratuito inscrito hace menos de 3 días »).
- El valor es real; NUNCA escribir fórmulas vacías como « mejorar la experiencia ».

Criterios de aceptación (obligatorios para cada story):
En formato Given-When-Then:
- Dado [estado previo], Cuando [acción], Entonces [resultado observable].
- Cubrir el camino normal + al menos un caso límite/excepción (vacío, fallo, sin permiso).

Disciplina de partición:
- Una story = una capacidad entregable independientemente; demasiado grande se parte, demasiado pequeña se fusiona.
- Marcar las dependencias entre stories (A depende de B a hacer primero).

NUNCA: NUNCA escribir la opción técnica en la story (la story dice « qué », no « cómo »).
