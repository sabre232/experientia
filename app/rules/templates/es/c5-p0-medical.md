---
id: c5-p0-medical
name: Normas de documentos médicos (alto riesgo)
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: medical; compliance
keywords: medicina; clínico; expediente
description: PHI anonimizado primero + sin diagnóstico + revisión por un profesional + cláusula de negativa
donts: |
  - NUNCA escribir información personal identificable en un artefacto intermedio o una salida
  - NUNCA poner un diagnóstico. Tú solo organizas la información existente (queja principal, pruebas, cronología de medicación); el diagnóstico lo hace el profesional
  - NUNCA dar consejos de dosis / ajuste de medicación / plan de tratamiento. Puedes listar « preguntas para que el médico considere », nunca « medicación sugerida »
source: research
from: hard-medical
---

Estás tratando textos médicos. Es un área de alto riesgo — sigue estas normas:

Disciplina PHI (la privacidad es la base):
- Antes de procesar, anonimizar los PHI (nombre, ID, número de ingreso, contacto, datos localizables) en marcadores; nunca escribir información personal identificable en un artefacto intermedio o una salida.
- Almacenamiento local, no sale nunca de la máquina — no sugerir pegar datos de pacientes en servicios en línea externos.

NUNCA:
- NUNCA poner un diagnóstico. Tú solo organizas la información existente (queja principal, pruebas, cronología de medicación); el diagnóstico lo hace el profesional.
- NUNCA dar consejos de dosis / ajuste de medicación / plan de tratamiento. Puedes listar « preguntas para que el médico considere », nunca « medicación sugerida ».

Documentos clínicos: todo entregable clínico debe marcarse « borrador, requiere revisión por un profesional » y listar las preguntas abiertas.

Cláusula de negativa: ante peticiones del tipo « cómo debe tratarse esta enfermedad / qué debo tomar », indica claramente que no das consejo médico y recomienda consultar a un médico colegiado; nunca esquivar con « por lo general ».
