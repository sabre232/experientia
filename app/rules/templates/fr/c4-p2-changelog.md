---
id: c4-p2-changelog
name: Règles de changelog
category: c4
priority: p2
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: changelog ; journal des versions
description: classé par Added/Changed/Fixed/Removed, écrit pour l'utilisateur final, sans jargon interne
source: community
---

## Règles

- Le changelog est sectionné par version, et au sein d'une section classé en Added / Changed / Fixed / Removed.
- Chaque entrée est écrite pour l'utilisateur final : « le journal des versions est maintenant archivé par semaine », pas « refactor archive job ».
- Les changements cassants sont isolés en tête et marqués `BREAKING`, avec les étapes de migration.
- Les refactorings internes et les mises à jour de dépendances (sans changement visible) n'entrent pas dans le changelog.
- À la release, générer un brouillon depuis l'historique des commits, le réviser à la main avant publication — NEVER publier la version générée par machine telle quelle.
