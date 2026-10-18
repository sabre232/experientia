---
id: c5-p0-eng-safety
name: Limites de sécurité d'ingénierie
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: engineering; security
keywords: secrets ; CI ; suppression ; sécurité
description: pas de secrets dans le repo, ne pas toucher CI/verrouillage de dépendances à la légère, s'arrêter et demander pour les opérations irréversibles
donts: |
  - NEVER commiter des secrets, des tokens, des adresses d'intranet dans le code ou la config
  - NEVER modifier la config CI, le verrouillage de versions de dépendances, sauf si la tâche l'exige explicitement
  - Avant de supprimer des données/fichiers, confirmer le périmètre d'impact ; pour une opération irréversible, s'arrêter et demander
source: research
from: eng-general
---

Limites de sécurité NEVER :
- NEVER commiter des secrets, des tokens, des adresses d'intranet dans le code ou la config.
- NEVER modifier la config CI, le verrouillage de versions de dépendances, sauf si la tâche l'exige explicitement.
- Avant de supprimer des données/fichiers, confirmer le périmètre d'impact ; pour une opération irréversible, s'arrêter et demander.
