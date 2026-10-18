---
id: c3-p2-deploy
name: Déploiement / exploitation
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: déploiement ; mise en ligne ; exploitation
description: points de confirmation avant déploiement + plan de rollback + traçabilité des changements
source: built-in
from: eng-deploy
---

Déploiement/exploitation — règles :

Avant le déploiement, émettre les points de confirmation et attendre validation (contrainte dure) :
- Lister : périmètre d'impact (quels services/environnements), migrations de données (les étapes s'il y en a), durée d'indisponibilité estimée, plan de rollback.
- En cas de production/opération irréversible, s'arrêter et attendre une confirmation explicite ; NEVER exécuter automatiquement.

Plan de rollback :
- À chaque changement, d'abord se demander « comment on rollback » ; sans chemin de rollback sûr, faire d'abord une sauvegarde/snapshot.
- Les migrations de données en scripts ré-exécutable (une re-exécution n'applique pas deux fois).

Traçabilité des changements :
- Noter le contenu du changement, l'exécutant, l'horodatage ; NEVER modifier une config de production sans trace.
- Les secrets/certificats n'entrent jamais dans le repo, ils passent par la gestion de secrets ; NEVER les exposer dans les logs/captures d'écran.

NEVER : NEVER exécuter du SQL non éprouvé directement sur la base de production ; NEVER modifier en parallèle plusieurs services qui se dépendent.
