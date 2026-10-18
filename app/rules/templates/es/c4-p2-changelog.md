---
id: c4-p2-changelog
name: Reglas de changelog
category: c4
priority: p2
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: changelog; registro de versiones
description: clasificado por Added/Changed/Fixed/Removed, escrito para el usuario final, sin jerga interna
source: community
---

## Reglas

- El changelog se secciona por versión, y dentro de una sección se clasifica en Added / Changed / Fixed / Removed.
- Cada entrada se escribe para el usuario final: « el registro de versiones ahora se archiva por semana », no « refactor archive job ».
- Los cambios rompedores se aíslan arriba y se marcan `BREAKING`, con los pasos de migración.
- Los refactorings internos y las actualizaciones de dependencias (sin cambio visible) no entran en el changelog.
- En el release, generar un borrador desde el historial de commits, revisarlo a mano antes de publicar — NUNCA publicar la versión generada por máquina tal cual.
