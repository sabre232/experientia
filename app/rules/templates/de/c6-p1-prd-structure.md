---
id: c6-p1-prd-structure
name: PRD-Struktur
category: c6
priority: p1
layer: structure
trigger_default: always
tags: product
keywords: PRD; Anforderung; Produkt
description: Kontext-Ziel → Option → Grenzen → Messung
source: built-in
from: prd-structure
---

Bei der Erstellung einer PRD dieser Struktur folgen; ein Fehlender wird explizit „keiner / nicht anwendbar“ geschrieben:

1. Kontext und Problem: warum, Nutzer-Pain-Points + Ist-Daten.
2. Ziele und Nicht-Ziele: Ziel dieses Sprints (quantifizierbar); „was nicht gemacht wird“ klarstellen, Scope-Creeppen vermeiden.
3. Nutzer und Szenarien: Zielgruppe, zentrale Szenarien (als User Story).
4. Option: Funktionsliste + Interaktionsfluss + Beschreibung der zentralen Screens; jede Funktion mit Priorität (P0/P1/P2).
5. Grenzen und Ausnahmen: Leerzustand, Fehlerzustand, Rechte, Concurrent-Handling, Daten-Grenzen.
6. Messung: welche Kennzahlen nach dem Live-Gang den Erfolg zeigen.
7. Abhängigkeiten und Risiken: teamübergreifende Abhängigkeiten, technische Risiken, Rollback-Plan.

Disziplin:
- Jede P0-Funktion hat Akzeptanzkriterien.
- Annahmen (unüberprüft) werden isoliert; NIEMALS eine Annahme wie eine Tatsache schreiben.
