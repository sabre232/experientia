---
id: c5-p0-edu-pii
name: Confidencialidad de alumnos (no tocar PII)
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: education; privacy
keywords: alumnos; privacidad; educación
description: anonimización PII + minimización + cumplimiento
donts: |
  - NUNCA conservar en la salida/los productos intermedios el nombre, el número de alumno, los datos familiares, la dirección, los contactos y otros datos identificables
  - NUNCA exportar de paso el expediente completo de un alumno
  - NUNCA enviar datos de alumnos a un servicio en línea externo
source: built-in
from: edu-pii
---

Al trabajar con datos de educación/alumnos, respetar:

Disciplina PII (datos personales):
- NUNCA conservar en la salida/los productos intermedios el nombre, el número de alumno, los datos familiares, la dirección, los contactos y otros datos identificables.
- Anonimizar antes del tratamiento: sustituir los campos de identidad por un código/un marcador; el análisis solo conserva los campos necesarios.

Principio de minimización:
- Tomar solo los campos indispensables para la tarea; NUNCA exportar de paso el expediente completo de un alumno.
- Las notas/comportamiento se presentan « en agregado » (distribución de la clase) por preferencia, para evitar la identificación individual.

Cumplimiento:
- Seguir el RGPD y la normativa educativa local (expediente académico), así como las recomendaciones de la agencia de protección de datos; un campo incierto no se trata por defecto.
- Los datos se quedan en la máquina; NUNCA enviar datos de alumnos a un servicio en línea externo.

Disciplina:
- Si se infiltra PII en los datos, parar, anonimizar, y luego continuar.
- Este modelo no constituye asesoramiento jurídico; para el cumplimiento, consultar a la jurídica/al delegado de protección de datos del centro.
