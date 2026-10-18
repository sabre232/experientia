---
id: c4-p1-pr-description
name: Norme de description de PR
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: PR ; merge request ; description
description: résumé du changement + motivation + plan de test + périmètre d'impact, les quatre parties sont obligatoires
source: community
---

## Règles

- Description de PR en quatre parties fixes : résumé du changement (1-3 phrases), motivation (quel problème résolu / quel issue), plan de test (comment c'est vérifié), périmètre d'impact (quels modules/utilisateurs touchés).
- Le résumé donne la conclusion, pas le déroulé ; coller un extrait de diff clé ou une capture, pas tout le diff.
- Si le périmètre d'impact touche config/migration de données/changement d'API, indiquer obligatoirement la méthode de rollback.
- Lier l'issue avec `Fixes #123` pour la fermer automatiquement.
- NEVER ouvrir une PR sans description (« voir le diff » ne compte pas comme description).

## Exemple

✅
Résumé : quand le bloc d'injection dépasse le budget, on passe au troncature ligne par ligne.
Motivation : jeter tout le bloc désactivait toutes les règles de basse priorité (#42).
Tests : 2 tests unitaires ajoutés pour le troncature budget ; vérification manuelle de 3 combinaisons de règles.
Impact : seulement proxy/inject.py ; pas de migration de données.
