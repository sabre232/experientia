---
id: c6-p2-data-framework
name: Cadre d'analyse (tendance → attribution → recommandation)
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: data
keywords: analyse ; attribution ; données
description: analyse en trois parties, conclusion avec données
source: built-in
from: data-framework
---

En faisant une analyse de données, suivre les trois parties :

1. Tendance (ce qui s'est passé) :
   - D'abord la tendance globale + les points de bascule clés ; parler en données (valeurs + fenêtre temporelle + périmètre annuel/mensuel).
   - Distinguer « variation statistique » de « changement réel » ; pas de conclusion sur petit échantillon.

2. Attribution (pourquoi) :
   - Découper par dimension pour trouver la contribution (par canal/région/segment d'utilisateurs), marquer les contributeurs principaux.
   - Distinguer corrélation et causalité ; avec seulement une preuve de corrélation, écrire explicitement « corrélé, pas causal ».
   - Lister les hypothèses à vérifier ; jamais d'écriture d'une conjecture comme conclusion.

3. Recommandation (que faire) :
   - Chaque recommandation correspond à un constat, est exécutable, avec responsable et délai.
   - Noter l'impact attendu et le risque de la recommandation ; « continuer à observer » est aussi une recommandation légitime.

Discipline : les périmètres (fenêtre temporelle/déduplication/unité) sont déclarés en tête ; chaque conclusion est traçable jusqu'aux données.
