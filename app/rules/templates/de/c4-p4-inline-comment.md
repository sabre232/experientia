---
id: c4-p4-inline-comment
name: Inline-Kommentar
category: c4
priority: p4
layer: structure
trigger_default: manual
tags: engineering; comments
keywords: Kommentar; inline
description: nur Beschränkungen und Abwägungen nennen, die der Code nicht ausdrücken kann, nicht „was diese Zeile tut“
source: built-in
---

## Regeln

- Der Inline-Kommentar beantwortet nur „warum“: Beschränkung, Abwägung, nicht offensichtliche Grenzbedingung.
- Das „was“ sagt der Code selbst — `i += 1  # i erhöhen` ist Lärm, löschen.
- Jede Umgehung muss mit dem Grund kommentiert sein: `# entfernen, wenn upstream XYZ fixt`, mit Issue/Link.
- Kommentar und Code ändern sich zusammen: wenn sich das Verhalten ändert, den veralteten Kommentar im selben Commit aktualisieren oder löschen.
