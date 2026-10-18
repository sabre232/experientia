---
id: c3-p2-eng-baseline
name: Baseline de build y tests
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: build; tests; baseline
description: lanzar la baseline antes de cambiar, relanzar los tests afectados después antes de commitear
source: built-in
from: eng-general
---

Build y tests (confirmar primero, lanzar después):
- Antes de empezar a modificar, lanzar una vez los tests existentes y anotar la baseline; tras cada modificación, relanzar los tests del módulo afectado antes de commitear.
- Las órdenes de build/tests se basan en el README, el Makefile, la configuración CI del repo; NUNCA adivinar las órdenes de memoria.
