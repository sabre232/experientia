---
id: c4-p4-inline-comment
name: Commentaire en ligne
category: c4
priority: p4
layer: structure
trigger_default: manual
tags: engineering; comments
keywords: commentaire ; inline
description: ne noter que les contraintes et arbitrages que le code ne peut pas exprimer, pas « ce que fait cette ligne »
source: built-in
---

## Règles

- Le commentaire en ligne ne répond qu'à « pourquoi » : contrainte, arbitrage, condition limite non évidente.
- Le « quoi » est dit par le code lui-même — `i += 1  # incrémente i` est du bruit, à supprimer.
- Toute écriture de contournement doit être commentée avec la raison : `# à retirer quand upstream corrige XYZ`, avec l'issue/le lien.
- Commentaire et code changent ensemble : si le comportement change, mettre à jour ou supprimer le commentaire obsolète dans le même commit.
