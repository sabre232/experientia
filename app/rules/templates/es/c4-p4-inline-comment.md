---
id: c4-p4-inline-comment
name: Comentario en línea
category: c4
priority: p4
layer: structure
trigger_default: manual
tags: engineering; comments
keywords: comentario; inline
description: solo notan las restricciones y arbitrajes que el código no puede expresar, no « qué hace esta línea »
source: built-in
---

## Reglas

- El comentario en línea solo responde a « por qué »: restricción, arbitraje, condición límite no evidente.
- El « qué » lo dice el código mismo — `i += 1  # incrementa i` es ruido, borrar.
- Toda escritura de rodeo debe estar comentada con la razón: `# retirar cuando upstream corrija XYZ`, con el issue/el enlace.
- Comentario y código cambian juntos: si cambia el comportamiento, actualizar o borrar el comentario obsoleto en el mismo commit.
