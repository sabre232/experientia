---
id: c6-p2-prd-stories
name: User stories (avec critères d'acceptation)
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: product
keywords: user story ; critères d'acceptation
description: formulation standard + acceptance Given-When-Then
source: built-in
from: prd-stories
---

En écrivant des user stories, respecter :

Formulation standard :
En tant que [rôle], je veux [capacité] afin de [valeur/bénéfice].
- Le rôle est précis (pas « un utilisateur » mais « un utilisateur gratuit inscrit depuis moins de 3 jours »).
- La valeur est réelle ; NEVER écrire des formules vides comme « améliorer l'expérience ».

Critères d'acceptation (obligatoires pour chaque story) :
Au format Given-When-Then :
- Étant donné [état préalable], Quand [action], Alors [résultat observable].
- Couvrir le chemin normal + au moins un cas limite/exception (vide, échec, sans droit).

Discipline de découpage :
- Une story = une capacité livrable indépendamment ; trop grosse on découpe, trop petite on fusionne.
- Marquer les dépendances entre stories (A dépend de B à faire d'abord).

NEVER : NEVER écrire l'option technique dans la story (la story dit « quoi », pas « comment »).
