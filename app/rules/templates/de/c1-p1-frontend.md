---
id: c1-p1-frontend
name: Frontend-Engineering
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: Frontend; Komponente
description: Komponenten-Grenzen + State-Management + Barrierefreiheit
source: built-in
from: eng-frontend
---

Frontend-Entwicklung — Regeln:

Komponenten:
- Eine Komponente = eine Verantwortung; über eine Bildschirmtaille oder bei gemischten Zuständigkeiten aufteilen.
- Kontrollierte und unkontrollierte Komponenten nicht mischen; die Prop-Benennung folgt der bestehenden Bibliothek.

State:
- Lieber lokalisieren als globalisieren; zuerst fragen „diesen State muss durch wie viele Komponenten“, wenn die Antwort ≤ 2, props/lokaler State.
- Abgeleitete Daten über useMemo/Berechnung; NIEMALS zwei States mit gleicher Quelle speichern und manuell synchronisieren.

Barrierefreiheit und Qualität:
- Interaktive Elemente müssen per Tastatur erreichbar sein (keine Schein-Button aus div); Formular-Steuerungen haben ein Label.
- Nach einer UI-Änderung prüfen, dass die Konsole keine neuen Fehler/Warnungen hat, bevor geliefert wird.

NIEMALS: NIEMALS eine umgebungsabhängige URL hart in einer Komponente schreiben; NIEMALS den globalen CSS verschmutzen, um eine Zeile zu sparen.
