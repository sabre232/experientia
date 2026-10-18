---
id: c4-p3-readme
name: README-Pflege
category: c4
priority: p3
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: README; Dokumentation; Synchronisation
description: README mit dem Code synchron: die drei Befehle installieren/ausführen/testen bleiben immer kopierbar und ausführbar
source: built-in
---

## Regeln

- Das README muss drei Blöcke enthalten: Installation, Ausführung, Tests; die Befehle dieser drei Blöcke müssen mit der Realität des Repos übereinstimmen (die CI-Konfiguration ist die Wahrheit).
- Wenn Befehl/Parameter/Verzeichnisstruktur geändert wird, das README im selben Commit aktualisieren — Befehl und Dokumentation in getrennten Commits gilt als unvollständig.
- Aus der Sicht eines Neulings prüfen: Nur mit dem README, kann die lokale Umgebung in 10 Minuten zum Laufen gebracht werden; wenn nein, die fehlenden Schritte ergänzen.
- Veraltete Abschnitte direkt löschen, keinen „zu aktualisieren“-Platzhalter lassen.
