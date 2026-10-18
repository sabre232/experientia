---
id: c5-p0-eng-safety
name: Engineering-Sicherheitsgrenzen
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: engineering; security
keywords: Secrets; CI; Löschung; Sicherheit
description: keine Secrets im Repo, CI/Dependency-Lock nicht leichtfertig ändern, bei irreversibler Operation anhalten und fragen
donts: |
  - NIEMALS Secrets, Tokens, Intranet-Adressen in Code oder Konfiguration committen
  - NIEMALS die CI-Konfiguration, das Dependency-Versions-Lock ändern, es sei denn, die Aufgabe verlangt es explizit
  - Vor dem Löschen von Daten/Dateien den Wirkungsbereich bestätigen; bei irreversibler Operation anhalten und fragen
source: research
from: eng-general
---

Sicherheitsgrenzen NIEMALS:
- NIEMALS Secrets, Tokens, Intranet-Adressen in Code oder Konfiguration committen.
- NIEMALS die CI-Konfiguration, das Dependency-Versions-Lock ändern, es sei denn, die Aufgabe verlangt es explizit.
- Vor dem Löschen von Daten/Dateien den Wirkungsbereich bestätigen; bei irreversibler Operation anhalten und fragen.
