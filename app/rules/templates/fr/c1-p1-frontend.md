---
id: c1-p1-frontend
name: Ingénierie frontend
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: frontend ; composant
description: limites de composant + gestion d'état + accessibilité
source: built-in
from: eng-frontend
---

Développement frontend — règles :

Composants :
- Un composant = une responsabilité unique ; au-delà d'un écran de haut ou si les responsabilités se mélangent, découper.
- Ne pas mélanger composants contrôlés et non contrôlés ; la nomenclature des props suit la bibliothèque existante.

État :
- Localiser plutôt que globaliser ; d'abord se demander « cet état doit-il traverser combien de composants », si la réponse est ≤ 2, props/état local.
- Les données dérivées via useMemo/calcul ; NEVER stocker deux états de même source puis les synchroniser à la main.

Accessibilité et qualité :
- Les éléments interactifs doivent rester atteignables au clavier (pas de faux bouton en div) ; les contrôles de formulaire ont un label.
- Après une modif UI, vérifier que la console n'a pas de nouvelle erreur/avertissement avant de livrer.

NEVER : NEVER écrire en dur une URL dépendante de l'environnement dans un composant ; NEVER polluer le CSS global pour économiser une ligne.
