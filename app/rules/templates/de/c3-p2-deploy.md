---
id: c3-p2-deploy
name: Deployment / Betrieb
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: Deployment; Release; Betrieb
description: Bestätiguns-Punkte vor dem Deploy + Rollback-Plan + Änderungsprotokoll
source: built-in
from: eng-deploy
---

Deployment/Betrieb — Regeln:

Vor dem Deployment die Bestätigungs-Punkte ausgeben und auf Bestätigung warten (harte Vorgabe):
- Auflisten: Wirkungsbereich (welche Dienste/Umgebungen), Datenmigration (Schritte, falls vorhanden), geschätzte Downtime, Rollback-Plan.
- Bei Produktion/irreversibler Operation: anhalten und auf eine explizite Bestätigung warten; NIEMALS automatisch ausführen.

Rollback-Plan:
- Bei jeder Änderung zuerst denken „wie rollt man zurück“; ohne sicheren Rollback-Pfad zuerst Backup/Snapshot.
- Datenmigrationen als wiederlauffähige Skripte (ein erneuter Lauf wendet nicht doppelt an).

Änderungsprotokoll:
- Inhalt der Änderung, Ausführender, Zeitstempel dokumentieren; NIEMALS eine Produktions-Konfiguration ohne Spur ändern.
- Secrets/Zertifikate gehören nie ins Repo, sie laufen über Secret-Management; NIEMALS in Logs/Screenshots preisgeben.

NIEMALS: NIEMALS ungetestetes SQL direkt auf der Produktions-DB ausführen; NIEMALS gleichzeitig mehrere voneinander abhängige Dienste ändern.
