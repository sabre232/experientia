---
id: c3-p2-eng-baseline
name: Baseline de build et de tests
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: build ; tests ; baseline
description: lancer la baseline avant de changer, relancer les tests impactés après avant de commiter
source: built-in
from: eng-general
---

Build et tests (confirmer d'abord, lancer ensuite) :
- Avant de commencer à modifier, lancer une fois les tests existants et noter la baseline ; après chaque modification, relancer les tests du module impacté avant de commiter.
- Les commandes de build/tests se basent sur le README, le Makefile, la config CI du repo ; NEVER deviner les commandes de mémoire.
