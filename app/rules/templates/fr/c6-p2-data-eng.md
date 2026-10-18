---
id: c6-p2-data-eng
name: Génie des données
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: data; engineering
keywords: données ; pipeline ; batch
description: pipeline idempotent + assertions de qualité + doc des périmètres
source: built-in
from: eng-data
---

Pipelines de données / traitement par lot — règles :

Idempotence et ré-exécutabilité :
- Une re-exécution donne le même résultat ; traitement incrémental par partition/date, jamais d'écrasement bête de toute la table.
- L'échec est récupérable depuis un point de contrôle ; jamais de supposition que la tâche ne tourne qu'une fois.

Qualité des données :
- Assertions sur les tables critiques (non nul, unique, seuil de variation des lignes) ; en cas d'anomalie, alerter d'abord puis continuer ou arrêter, jamais avaler silencieusement les données sales.
- Les périmètres (règle de déduplication, fenêtre temporelle, devise/fuseau horaire) sont documentés ; jamais qu'un périmètre existe seulement dans un bout de SQL.

Sécurité :
- Les champs sensibles (PII) sont minimisés dans le pipeline ; les produits intermédiaires sont aussi anonymisés.
- Avant une grosse requête, vérifier le volume et les index ; jamais de scan de table complète sur la base de production.
