---
id: c6-p2-data-viz
name: Normes de visualisation
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: data
keywords: graphique ; visualisation
description: type de graphique adapté + axes honnêtes + moins c'est mieux
source: built-in
from: data-viz
---

En faisant de la visualisation de données, respecter :

Type de graphique adapté au contenu :
- Tendance → courbe ; comparaison → barres ; composition → empilé/camembert (≤ 5 catégories) ; distribution → histogramme/boîte à moustaches ; relation → nuage de points.
- Avant de choisir le type, se demander « que doit voir le lecteur » ; jamais de 3D/camembert forcé pour l'esthétique.

Axes et honnêteté :
- Le graphique en barres part de 0 sur l'axe Y (tronquer exagère les différences) ; une courbe tronquée doit être annotée.
- Usage prudent du double axe ; quand c'est indispensable, expliquer clairement l'alignement des unités et des zéros.
- Jamais de graphiques trompeurs (troncature, axe non linéaire, palette trompeuse).

Moins c'est mieux :
- Un graphique = une information ; supprimer les lignes de grille, cadres, légendes qui ne portent pas d'information.
- La couleur a un sens (distinction/emphase) ; jamais de couleur arc-en-ciel indifférenciée ; penser à la lisibilité daltonienne.

Annotation :
- Le titre dit la conclusion ; les points clés sont annotés directement sur le graphique (flèches/texte) ; jamais de laisser le lecteur lire des axes nus.
- Le trio unité / période / source de données est complet.
