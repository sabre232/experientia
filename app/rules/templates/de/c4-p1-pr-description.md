---
id: c4-p1-pr-description
name: PR-Beschreibungs-Norm
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: PR; Merge Request; Beschreibung
description: Änderungszusammenfassung + Motivation + Testplan + Wirkungsbereich, alle vier Teile Pflicht
source: community
---

## Regeln

- PR-Beschreibung in vier festen Teilen: Änderungszusammenfassung (1-3 Sätze), Motivation (welches Problem / welches Issue), Testplan (wie verifiziert), Wirkungsbereich (welche Module/Nutzer betroffen).
- Die Zusammenfassung gibt die Schlussfolgerung, nicht den Verlauf; ein zentrales Diff-Fragment oder einen Screenshot einfügen, nicht den ganzen Diff.
- Wenn der Wirkungsbereich Konfiguration/Datenmigration/API-Änderung betrifft, die Rollback-Methode obligatorisch angeben.
- Das Issue mit `Fixes #123` verlinken, um es automatisch zu schließen.
- NIEMALS eine PR ohne Beschreibung öffnen („Diff ansehen“ zählt nicht als Beschreibung).

## Beispiel

✅
Zusammenfassung: Bei Injektionsblock-Budgetüberschreitung auf zeilenweises Kappen umgestellt.
Motivation: Das Verwerfen des ganzen Blocks deaktiviert alle Regeln niedriger Priorität (#42).
Tests: 2 Unit-Tests für Budget-Kappung hinzugefügt; manuelle Prüfung von 3 Regel-Kombinationen.
Auswirkung: nur proxy/inject.py; keine Datenmigration.
