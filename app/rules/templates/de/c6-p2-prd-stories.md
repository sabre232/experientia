---
id: c6-p2-prd-stories
name: User Stories (mit Akzeptanzkriterien)
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: product
keywords: User Story; Akzeptanzkriterien
description: Standardformulierung + Given-When-Then-Akzeptanz
source: built-in
from: prd-stories
---

Bei der Erstellung von User Stories einhalten:

Standardformulierung:
Als [Rolle] möchte ich [Fähigkeit] damit [Wert/Nutzen].
- Die Rolle ist konkret (nicht „ein Nutzer“, sondern „ein Free-Nutzer, der sich vor weniger als 3 Tagen registriert hat“).
- Der Wert ist real; NIEMALS leere Floskeln wie „das Erlebnis verbessern“.

Akzeptanzkriterien (Pflicht für jede Story):
Als Given-When-Then:
- Given [Ausgangszustand], When [Aktion], Then [beobachtbares Ergebnis].
- Den normalen Pfad + mindestens einen Grenz-/Ausnahmefall (leer, Fehlschlag, kein Recht) abdecken.

Aufteilungs-Disziplin:
- Eine Story = eine unabhängig lieferbare Fähigkeit; zu groß aufteilen, zu klein zusammenführen.
- Abhängigkeiten zwischen Stories markieren (A hängt an B zuerst).

NIEMALS: NIEMALS die technische Option in die Story schreiben (die Story sagt „was“, nicht „wie“).
