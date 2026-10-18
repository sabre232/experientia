---
id: c6-p1-prd-structure
name: Structure de PRD
category: c6
priority: p1
layer: structure
trigger_default: always
tags: product
keywords: PRD ; besoin ; produit
description: contexte-objectif → option → limites → mesure
source: built-in
from: prd-structure
---

En écrivant une PRD, suivre cette structure ; un manquant est écrit explicitement « aucun / non applicable » :

1. Contexte et problème : pourquoi on le fait, points de douleur utilisateur + données de l'état actuel.
2. Objectifs et non-objectifs : objectif de cette itération (quantifiable) ; préciser « ce qu'on ne fait pas », pour éviter le glissement de périmètre.
3. Utilisateurs et scénarios : cible, scénarios clés (au format user story).
4. Option : liste de fonctionnalités + flux d'interaction + description des écrans clés ; chaque fonctionnalité avec une priorité (P0/P1/P2).
5. Limites et cas limites : état vide, état d'erreur, droits, concurrence, limites de données.
6. Mesure : quels indicateurs post-mise en ligne pour juger du succès.
7. Dépendances et risques : dépendances inter-équipes, risques techniques, plan de rollback.

Discipline :
- Chaque fonctionnalité P0 a des critères d'acceptation.
- Les hypothèses (non vérifiées) sont isolées ; NEVER écrire une hypothèse comme un fait.
