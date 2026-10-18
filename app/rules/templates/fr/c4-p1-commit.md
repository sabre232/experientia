---
id: c4-p1-commit
name: Format du message de commit
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: commit ; Conventional Commits
description: Conventional Commits : type(scope): titre verbe+objet + corps optionnel expliquant la motivation
source: community
---

## Règles

- Titre en Conventional Commits : `type(scope): phrase verbe+objet`, ex. `fix(auth): corriger le refresh de token expiré`.
- type limité à : feat / fix / docs / refactor / test / chore / perf / ci.
- Titre ≤ 72 caractères, il dit « ce qui a été fait » ; le corps (optionnel) dit « pourquoi », sans répéter le contenu du diff.
- Un commit = une seule chose ; mélanger « refactor + nouvelle fonction » se découpe en deux commits.
- NEVER commiter un titre sans information comme « fix » / « update » / « wip ».

## Exemples

✅ `fix(inject): tronquer ligne par ligne quand le budget est dépassé, au lieu de jeter tout le bloc`
❌ `fix`, `mise à jour du code`, `wip`
