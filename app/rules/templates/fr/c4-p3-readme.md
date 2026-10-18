---
id: c4-p3-readme
name: Maintenance du README
category: c4
priority: p3
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: README ; documentation ; synchronisation
description: README synchronisé avec le code : les trois commandes installer/lancer/tester restent toujours copiables et exécutables
source: built-in
---

## Règles

- Le README doit contenir trois blocs : installation, exécution, tests ; les commandes de ces trois blocs doivent correspondre à la réalité du repo (la config CI est la source de vérité).
- Quand on change commande/paramètre/structure de dossiers, mettre à jour le README dans le même commit — commander et documentation dans des commits séparés est considéré comme incomplet.
- Vérifier du point de vue d'un nouveau venu : avec seulement le README, peut-on faire tourner l'environnement local en 10 minutes ; sinon, compléter les étapes manquantes.
- Supprimer directement les sections obsolètes, ne pas laisser de placeholder « à mettre à jour ».
