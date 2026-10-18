---
id: c5-p0-edu-pii
name: Schülerschutz (PII nicht antasten)
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: education; privacy
keywords: Schüler; Datenschutz; Bildung
description: PII-Anonymisierung + Minimierung + Compliance
donts: |
  - NIEMALS Name, Schülernummer, Familienangaben, Adresse, Kontaktdaten und andere identifizierende Daten in Ausgabe/Zwischenprodukten aufbewahren
  - NIEMALS nebenbei die gesamte Schülerakte exportieren
  - NIEMALS Schüldaten an einen externen Online-Dienst senden
source: built-in
from: edu-pii
---

Bei der Arbeit mit Bildungs-/Schülerdaten einhalten:

PII-Disziplin (personenbezogene Daten):
- NIEMALS Name, Schülernummer, Familienangaben, Adresse, Kontaktdaten und andere identifizierende Daten in Ausgabe/Zwischenprodukten aufbewahren.
- Vor der Verarbeitung anonymisieren: Identitätsfelder durch Code/Platzhalter ersetzen; die Analyse behält nur die nötigen Felder.

Minimierungsprinzip:
- Nur die für die Aufgabe nötigen Felder nehmen; NIEMALS nebenbei die gesamte Schülerakte exportieren.
- Noten/Verhalten „aggregiert“ (Klassenverteilung) bevorzugen, um individuelle Identifizierung zu vermeiden.

Compliance:
- DSGVO und das jeweilige Landes-Schulrecht sowie die Vorgaben des Datenschutzbeauftragten einhalten; ein unsicheres Feld wird standardmäßig nicht verarbeitet.
- Die Daten bleiben auf dem Rechner; NIEMALS Schüldaten an einen externen Online-Dienst senden.

Disziplin:
- Wenn sich PII in den Daten einschleicht, anhalten, anonymisieren, dann weiter.
- Diese Vorlage ist keine Rechtsberatung; für Compliance die Schulrechtsabteilung/den Datenschutzbeauftragten konsultieren.
