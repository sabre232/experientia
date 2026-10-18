---
id: c4-p1-commit
name: Commit-Nachricht-Format
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: Commit; Conventional Commits
description: Conventional Commits: type(scope): Verb+Objekt-Überschrift + optionaler Body mit Motivation
source: community
---

## Regeln

- Überschrift in Conventional Commits: `type(scope): Verb+Objekt-Phrase`, z. B. `fix(auth): abgelaufenes Token-Refresh korrigieren`.
- type beschränkt auf: feat / fix / docs / refactor / test / chore / perf / ci.
- Überschrift ≤ 72 Zeichen, sie sagt „was gemacht wurde“; der Body (optional) sagt „warum“, ohne den Diff-Inhalt zu wiederholen.
- Ein Commit = eine Sache; „Refactor + neue Funktion“ mischen in zwei Commits aufteilen.
- NIEMALS inhaltslose Überschriften wie „fix“ / „update“ / „wip“ committen.

## Beispiele

✅ `fix(inject): bei Budgetüberschreitung zeilenweise kappen statt den ganzen Block zu verwerfen`
❌ `fix`, `Code aktualisiert`, `wip`
