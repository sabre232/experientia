---
id: c3-p2-eng-baseline
name: Build- und Test-Baseline
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: Build; Tests; Baseline
description: vor der Änderung die Baseline laufen lassen, danach die betroffenen Tests vor dem Commit
source: built-in
from: eng-general
---

Build und Tests (zuerst bestätigen, dann ausführen):
- Vor dem Anfang der Änderung die bestehenden Tests einmal laufen lassen und die Baseline notieren; nach jeder Änderung die Tests des betroffenen Moduls vor dem Commit neu laufen lassen.
- Build/Test-Befehle orientieren sich am README, Makefile, der CI-Konfiguration des Repos; NIEMALS Befehle aus dem Gedächtnis raten.
