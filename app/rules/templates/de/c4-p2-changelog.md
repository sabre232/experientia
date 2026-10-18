---
id: c4-p2-changelog
name: Changelog-Regeln
category: c4
priority: p2
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: Changelog; Änderungsprotokoll; Version
description: nach Added/Changed/Fixed/Removed geordnet, für den Endnutzer, ohne internen Jargon
source: community
---

## Regeln

- Das Changelog ist nach Version unterteilt, und innerhalb eines Abschnitts nach Added / Changed / Fixed / Removed sortiert.
- Jeder Eintrag ist für den Endnutzer verfasst: „Änderungsprotokoll wird jetzt wöchentlich archiviert“, nicht „Refactor archive job“.
- Breaking Changes werden oben isoliert und mit `BREAKING` markiert, mit Migrationsschritten.
- Interne Refactorings und Abhängigkeits-Updates (ohne sichtbare Änderung) kommen nicht ins Changelog.
- Beim Release aus dem Commit-Verlauf einen Entwurf erzeugen, vor der Veröffentlichung manuell überarbeiten — NIEMALS die maschinell erzeugte Version unverändert veröffentlichen.
