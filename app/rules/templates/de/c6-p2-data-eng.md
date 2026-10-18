---
id: c6-p2-data-eng
name: Data Engineering
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: data; engineering
keywords: Daten; Pipeline; Batch
description: idempotente Pipeline + Datenqualitäts-Assertions + Umfangs-Doku
source: built-in
from: eng-data
---

Daten-Pipeline / Batch-Verarbeitung — Regeln:

Idempotenz und Wiederlaufbarkeit:
- Ein erneuter Lauf gibt dasselbe Ergebnis; inkrementelle Verarbeitung nach Partition/Datum, nie blödes Überschreiben der ganzen Tabelle.
- Ein Fehlschlag ist von einem Checkpoint wiederholbar; nie annehmen, dass die Aufgabe nur einmal läuft.

Datenqualität:
- Assertions auf zentralen Tabellen (nicht null, eindeutig, Zeilen-Schwankungsschwelle); bei Anomalie zuerst alarmieren, dann weiter oder stoppen, nie schmutzige Daten still schlucken.
- Die Umsätze (Deduplizierungsregel, Zeitfenster, Währung/Zeitzone) werden dokumentiert; nie dass ein Umsatz nur in einem SQL-Ausschnitt existiert.

Sicherheit:
- Sensible Felder (PII) werden in der Pipeline minimiert; Zwischenprodukte werden ebenfalls anonymisiert.
- Vor einer großen Abfrage Datenmenge und Indizes prüfen; nie ein Full-Table-Scan auf der Produktions-DB.
