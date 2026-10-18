---
id: c1-p1-backend
name: Backend-API-Engineering
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: API; Backend; Schnittstelle
description: Vertrag zuerst + Fehlersemantik + Idempotenz und Grenzen
source: built-in
from: eng-backend
---

Backend/API-Entwicklung — Regeln:

Vertrag:
- Den Eingabe/Ausgabe-Schema der API festlegen, bevor die Implementierung geschrieben wird; einen Vertrag zu ändern heißt zuerst Doc/Tests ändern, dann den Code.
- Die Benennung der öffentlichen Felder bleibt mit der bestehenden API konsistent; NIEMALS mehrere Schreibweisen für dieselbe Bedeutung.

Fehler und Status:
- Die richtigen HTTP-Statuscodes verwenden (4xx Client-Fehler, 5xx Server-Fehler); der Fehlerkörper trägt eine maschinenlesbare code + eine menschenlesbare message.
- NIEMALS eine Exception schlucken und einen leeren 200 zurückgeben; entweder behandeln oder weiterreichen.

Idempotenz und Grenzen:
- Schreiboperationen (vor allem mit Geld) brauchen einen Idempotenz-Schlüssel; NIEMALS annehmen, dass eine Anfrage nur einmal kommt.
- Eingabeparameter immer validieren (Typ/Bereich/Länge); NIEMALS dem Aufrufer vertrauen.

Logging:
- „Was passiert ist + wichtiger Kontext“ protokollieren; NIEMALS Secrets, Tokens, sensible Felder im Request-Körper loggen.
