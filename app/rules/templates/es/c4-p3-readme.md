---
id: c4-p3-readme
name: Mantenimiento del README
category: c4
priority: p3
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: README; documentación; sincronización
description: README sincronizado con el código: los tres comandos instalar/ejecutar/testear siguen siempre copiables y ejecutables
source: built-in
---

## Reglas

- El README debe contener tres bloques: instalación, ejecución, tests; los comandos de estos tres bloques deben coincidir con la realidad del repo (la configuración CI es la fuente de verdad).
- Al cambiar comando/parametro/estructura de directorios, actualizar el README en el mismo commit — comandos y documentación en commits separados se considera incompleto.
- Comprobar desde la perspectiva de un novato: solo con el README, ¿se puede arrancar el entorno local en 10 minutos; si no, completar los pasos que faltan.
- Borrar directamente las secciones obsoletas, no dejar placeholder « por actualizar ».
