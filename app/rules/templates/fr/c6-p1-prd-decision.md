---
id: c6-p1-prd-decision
name: Matrice de décision
category: c6
priority: p1
layer: structure
trigger_default: always
tags: product
keywords: décision ; choix ; arbitrage
description: options × dimensions notées pondérées + hypothèses explicites
source: built-in
from: prd-decision
---

En comparant/arbitrant des options, respecter :

Structure :
- Lister 2-4 options candidates (dont « ne rien faire » comme baseline).
- 3-6 dimensions d'évaluation (ex. coût, risque, vitesse, maintenabilité), chaque dimension avec un poids (somme = 100).
- Notation dans la matrice (1-5), somme pondérée, l'option recommandée est marquée.

Discipline :
- Chaque note a une phrase de justification ; les dimensions « au feeling » sont explicitement marquées subjectives.
- Les poids sont justifiés (pourquoi cette dimension pèse plus) ; NEVER partir d'une répartition égale par défaut.
- Lister les hypothèses clés (quelles notes reposent sur une prémisse non vérifiée) ; si une hypothèse change, la conclusion est recalculée.

Sortie :
- Option recommandée + raison en une phrase + risque principal + condition de déclenchement « quand est-ce qu'on change d'option ».
- NEVER donner que des scores sans raisonnement.
