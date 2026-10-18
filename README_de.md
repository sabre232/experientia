# Experientia · die Klebeschicht zwischen Ihnen und Ihren Agenten

**Der Agent wechselt. Ihre Erfahrung nicht.**

[English](README.md) | [简体中文](README_zh.md) | [繁體中文](README_zh-TW.md) | [日本語](README_ja.md) | [한국어](README_ko.md) | **Deutsch** | [Français](README_fr.md) | [Español](README_es.md) | [Русский](README_ru.md) | [Português (BR)](README_pt-BR.md)

---

Eine kleine Szene, die jede Woche passiert.

Sie bitten einen Agenten, eine Exportfunktion zu reparieren. Er schreibt die Zeitzone fest auf UTC+8. Sie sagen, nein, die Systemzeitzone soll gelten. Er ändert es, Sie prüfen, fertig.

Eine Woche später, dieselbe Aufgabe, wieder UTC+8.

Sie fragen sich, ob Sie es schlecht erklärt haben. Haben Sie nicht. Sie haben es klar erklärt, in einer anderen Sitzung. In dem Moment, in dem diese Sitzung endet, hat es für ihn nie stattgefunden.

Dann wechseln Sie das Werkzeug. Was Sie Claude Code beigebracht haben, müssen Sie Codex erneut beibringen, und Cursor noch einmal. Ein halbes Jahr an Wissen darüber, wie diese Art Arbeit funktioniert, verteilt sich auf vier Chatverläufe, und nichts davon kommt mit.

Die Branche nennt das Context Engineering oder Memory-Layer. Der Name klingt abstrakt, das Problem ist schlicht. Wie bringt man einen Agenten dazu, sich an Sie zu erinnern.

Unser Ansatz geht einen Schritt weiter. Erinnern ist die Startlinie. Besser zu werden in Ihrer Arbeit, mit jeder Nutzung, ist der Punkt.

Deshalb tut Experientia genau eine Sache. Es sitzt zwischen Ihnen und dem Agenten, behält die Teile jeder Zusammenarbeit, die wirklich zählten, prüft sie, destilliert sie zu Methoden und Fehlermustern und legt sie vor der nächsten Aufgabe wieder vor. Der Agent kann wechseln, es bleibt. Das meinen wir mit Klebeschicht.

> *experientia est magistra*, Erfahrung ist die beste Lehrerin.

## Worauf die Branche setzt und was sie übersieht

Das Geld, das 2026 in dieses Feld fließt, ist nicht kleiner als das für Modelle.

Der 2026 Agentic Coding Trends Report von Anthropic nennt Zahlen. Teams, die ihre Kontextdateien gut pflegen, erledigen Aufgaben 55 Prozent schneller und machen 40 Prozent weniger Fehler. Der Unterschied liegt nicht in besserer Formulierung, sondern darin, ob jemand «was das Modell sieht» als Ingenieursproblem behandelt.

Die zweite Spur sind Skills. Anthropic brachte Agent Skills im Oktober 2025 heraus, veröffentlichte das Format am 18. Dezember 2025 als offenen Standard, und Mitte 2026 lesen rund vierzig Agenten dieselbe SKILL.md. Das ist wichtig. Zum ersten Mal kann prozedurales Wissen zwischen Werkzeugen wandern.

Dann hat SkillsBench alle abgekühlt. Der Benchmark erschien im Februar 2026 (arXiv:2602.12670), 86 Aufgaben, 11 Domänen, 7 Agenten-Modell-Kombinationen, 7308 Trajektorien. Von Hand kuratierte Skills heben die Durchschnittsquote um 16,2 Punkte. Skills, die Modelle sich selbst schreiben, bringen im Schnitt nichts, und 16 von 84 Aufgaben werden schlechter.

Ein Modell kann die Erfahrung, die es braucht, nicht selbst schreiben.

Genau hier kommt die Branche nicht vorbei. Der Behälter existiert. Der Speicher existiert. Niemand macht Qualitätskontrolle.

| Lager | Beispiele | Was es tut | Was es auslässt |
|-------|-----------|------------|-----------------|
| **Memory-Layer** | Mem0, Zep, Letta, Cognee | Speichert **Fakten** aus Gesprächen in Vektoren, temporalen Graphen oder gestuftem Kontext und ruft sie später ab | Erzeugt keine **Methoden**. Die Daten liegen bei ihnen, nicht auf Ihrer Platte |
| **Skill-Destillation** | colleague.skill, nuwa-skill, dojo.md | Einmalig. Material hinein, eine statische SKILL.md heraus | Kein Feedback zur Laufzeit. Der Skill revidiert sich nie danach, ob er Ihnen geholfen hat |
| **Selbstentwickelnde Harnesses** | Hermes Agent (Nous Research), DeepSeek Harness | Das Framework lernt, macht aus erledigten Aufgaben SKILL.md und verfeinert sie | Skills leben im Harness und sterben mit ihm. Erzeugung folgt Aktivität, nicht Qualität. Fehler werden nicht gezählt, bevor eine Lektion dauerhaft wird |
| **Skill-Bewertung** | waza (Microsoft), dojo/limitless | Testet und prüft vorhandene Skills wie Code in CI | Produziert keine Skills. Werkzeug für Skill-Autoren, kein Produkt für Menschen, die arbeiten |

Jedes Lager löst eine Strecke. Niemand verbindet die Strecken.

**Diese Verbindung ist Experientia.** Erfassen, prüfen, destillieren, injizieren, revidieren. Ein geschlossener Kreis. Stand Oktober 2026 haben wir kein offenes Produkt gefunden, das alle vier Punkte gleichzeitig erfüllt.

- **Automatisches Erfassen.** Kein Transkript exportieren. Daten kommen herein, während Sie arbeiten
- **Ein Prüf-Gate.** Nichts Unbewiesenes wird injiziert. Fehler müssen sich wiederholen, bevor sie dauerhaftes Wissen werden
- **Lokal und mitnehmbar.** Jedes Asset ist eine einfache Datei auf Ihrem Rechner. Kein Konto, keine Cloud, kein Vektorspeicher
- **Fortlaufende Revision.** Assets sind lebende Dokumente, die zusammengeführt, verworfen und gekürzt werden. Sie wachsen nicht nur

## Erinnerung ist nicht Erfahrung

Diese Unterscheidung trägt den Rest.

Erinnerung speichert Fakten. Die Person bevorzugt TypeScript. Abhängigkeiten laufen über uv. Letzten Mittwoch ging es um den Export. All das lässt sich indexieren, einbetten, in einen Graphen legen.

Erfahrung ist Urteilskraft. Migrationen dieser Art fassen zuerst die Tests an, weil wir letztes Mal direkt in die Implementierung gegangen sind und drei Downstreams gebrochen haben. Das lässt sich nicht abrufen. Es muss aus etwas wirklich Geschehenem wachsen, und jemand muss bestätigen, dass es richtig war.

| | Erinnerung | Erfahrung |
|---|---|---|
| Enthält | Fakten, Präferenzen, Zustand | Methoden, Fehlermuster, Maßstäbe |
| Stammt aus | Was gesagt wurde | Was getan wurde und wo es brach |
| Abrufbar | Ja | Nein. Nur prüfbar und revidierbar |
| Verfällt durch | Überschreiben | Verwerfen, Zusammenführen, Kürzen |
| Nach dem Werkzeugwechsel | Hängt von der Plattform ab | Eine Datei in Ihrer Hand, kommt mit |

Die Memory-Produkte sind gut in dem, was sie tun. Mem0 arbeitet vektorfirst, Zep modelliert Fakten über die Zeit als Graph, Letta lagert Kontext aus wie ein Betriebssystem Speicherseiten. Aber sie lösen Erinnern, nicht Lernen. Eine vollständige Faktenlage ist nicht dasselbe wie besser in der Arbeit zu werden.

Wir bauen keinen volleren Aktenschrank. Wir bauen eine erfahrene Kollegin, die ihre Meinung ändert, wenn sich die Belege ändern.

## Wie es läuft

```
Sie arbeiten ──> Agent arbeitet mit (automatisch erfasst)
   ^                              |
   |                              v
schneller, besser  <──  injizieren  <──  destillieren (geprüft)
```

**Erfassen.** Sie arbeiten wie immer. Sitzungsdateien liegen bereits auf der Platte, nichts zu exportieren, nichts einzufügen. Installierte Agenten werden automatisch erkannt, ohne Konfiguration.

**Prüfen.** Jede Erfahrung trägt ein Konfidenzsignal G aus drei Quellen, Ihrer ausdrücklichen Bestätigung, deterministischen Signalen der Sitzung und der binären Selbsteinschätzung des Modells. Alles unter der Schwelle wird nie injiziert. Ein Fehlermuster muss sich wiederholen, bevor es dauerhaft wird. Das ist die technische Antwort auf SkillsBench. Nur geprüfte Erfahrung darf sich verzinsen.

**Destillieren.** Wiederkehrende Arbeit wird zu einer parametrisierten Methode. Wiederkehrende Fehler werden zu Fehlermustern erster Klasse. Ihre Korrekturen und Ablehnungen werden zu Präferenzen.

**Injizieren.** Vor jeder Anfrage an das Modell schreibt der Proxy sie mit den relevanten Assets in einem festen Budget um (Standard 800 Token), in einem stabilen Format, das Prompt-Caching erhält. Sie sehen genau, was das Modell sehen wird, können jeden Eintrag bearbeiten oder deaktivieren oder das angeschlossene Modell umschreiben lassen. Lange Sitzungen verdünnen Ihre Regeln nicht. Harte Vorgaben werden in der Proxy-Schicht erneut injiziert, Runde 30 zählt so viel wie Runde 1.

**Revidieren.** Assets sind lebende Dokumente. Neue Erfahrung fließt in alte, veraltete Einträge werden verworfen, das Dokument wird kürzer. Eine Wissensbasis, die nur wächst, wird nach einem halben Jahr nicht mehr gelesen.

Ein Durchlauf erzeugt fünf Asset-Typen, physisch zwei Dateiformen, `skills/<Stamm>/<Kategorie>.md` und `preferences/<Stamm>.md`.

| Asset | Inhalt | Gefühl bei der Nutzung |
|-------|--------|------------------------|
| **Erfahrungs-Einsichten** | Einzelne Lektionen, was wirkte und was nicht | «Es erinnert sich, was ich korrigiert habe» |
| **Meine Methoden** | Wiederkehrende Arbeit als parametrisierter Standardablauf | «Es weiß, wie diese Art Aufgabe geht» |
| **Fehlermuster** | Welche Wege brechen und warum, erster Klasse statt Nachgedanke | «Es lässt mich nicht in dasselbe Loch fallen» |
| **Lebendes Playbook** | Der injizierte Kontext ist inkrementell kuratiert, zusammengeführt und beschnitten | «Die Methodik wird aufgewertet, nicht gestapelt» |
| **Meine Präferenzen** | Ihre Maßstäbe, Ihr Geschmack, Ihre Abwägungen, aus Korrekturen abgeleitet | «Es kennt meine Latte, ich muss sie nicht neu erklären» |

Zwei Gänge, ein Schwungrad. Der Alltagsgang ist Standard, inkrementelle Kuration für offene Arbeit, kein Bestanden-Signal nötig. Der Verstärkungsgang ist optional, für Aufgaben mit explizitem Score (Tests bestanden, Backtest-PnL), bei denen eine RL-Engine die Strategiegewichte direkt abstimmt.

## Wie «mit jeder Nutzung besser» aussieht

Erstes Mal. Es folgt einem generischen Muster. Sie schauen bei jedem Schritt zu, bereit zu korrigieren.

Zehntes Mal. Es weiß, dass in diesem Projekt Tests vor der Implementierung kommen. Es weiß, dass Sie «lass es erst mal laufen» ablehnen. Es weiß, warum Sie den letzten Ansatz verworfen haben.

Hundertstes Mal. Sie sagen «wie letztes Mal», und es weiß, welches gemeint ist.

| | 1. Lauf | 10. Lauf | 100. Lauf |
|---|---|---|---|
| Was Sie sagen | Ein Absatz Hintergrund und Vorgaben | Ein paar Kernurteile | Ein Fingerzeig |
| Wie es scheitert | In Löchern, die Sie schon kennen | Gelegentlich in einem neuen | Es kennt die Löcher und geht herum |
| Ihre Rolle | Hand anlegen | Abnehmen | Richtung geben |

Deshalb macht es nichts, wenn Sie den Agenten wechseln. Sie wechseln den Ausführenden, nicht den Maßstab. Der Maßstab bleibt bei Ihnen.

## v1.1: Erinnerung eine Schicht tiefer

v1.0 beantwortete «erinnert es sich». v1.1 beantwortet «erinnert es sich richtig».

Viel speichern ist nicht dasselbe wie genau abrufen. Diese Version steckt die Arbeit in drei Stellen, die vorher unscharf waren.

**Was vergessen werden soll, ist wirklich weg.** Weich vergessene Einträge, abgelehnte, von einer neueren Fassung abgelöste — kein Standard-Lesepfad gibt sie mehr zurück, auch nicht der MCP-Kanal für Agenten. Die Suche filterte sie vorher, das Holen eines einzelnen Eintrags per id nicht. Das war eine Hintertür.

**Andere Formulierung, gleicher Treffer.** Sie fragen «wie haben wir das Module not found letztes Mal behoben», im Bestand steht «Abhängigkeit neu installieren» — kein gemeinsames Wort. v1.1 leitet drei Arten von Entitätsschlüsseln aus jedem Eintrag ab: Fehlerphrasen, Befehlsskelette, Projektnamen. Ein Treffer zählt. Die Schwelle bleibt: kein Treffer, kein Ergebnis.

**Es weiß, warum es etwas glaubt.** Jede Erfahrung muss auf etwas zurückführbar sein, das Sie tatsächlich gesagt haben. Das Evidenz-Gate wandert von «Zitat finden» zu «Kandidat kommt in den Bestand»: ein vom Modell erfundenes Zitat von zwei Zeichen kam früher durch, weil jede Nachricht es enthält. Jetzt nicht mehr. Umgekehrt zählt Ihr «so passt es» bei der Abnahme weiterhin.

**Der reduzierte Betrieb sagt die Wahrheit.** Fehlt die Indexdatenbank, fällt die Engine auf reine Dateien zurück. Weich vergessen, ablösen und wiederherstellen meldeten früher Erfolg, ohne etwas zu schreiben. Jetzt schreiben sie oder melden den Fehler.

Zwei technische Punkte. Der heiße Abrufpfad tokenisiert denselben Text nicht mehr neu und leitet die Entitätsschlüssel nicht neu ab: bei 3.000 Einträgen fiel das langsame Ende (95 % der Anfragen) von 106 ms auf 41,5 ms. `scripts/gate_report.py` liefert Ebenen-Inventar, Gate-Backtest und Abruflatenz in einem Lauf.

## Schnellstart

1. Laden Sie den Build für Ihre Plattform von [GitHub Releases](https://github.com/sabre232/experientia/releases), `experientia-windows-x64.zip`, `experientia-macos.dmg`, `experientia-linux-x64.tar.gz` (ein PyInstaller-onedir-Baum, unter v1.1 nicht in AppImage verpackt). Entpacken und `Experientia` starten. Die Builds sind unsigniert. Wenn Gatekeeper unter macOS blockt, einmal per Rechtsklick öffnen. Wenn SmartScreen unter Windows erscheint, «Weitere Informationen → Trotzdem ausführen».
2. Starten. Das Erfassen beginnt sofort. Installierte Agenten werden erkannt (WorkBuddy, QClaw, Codex, Claude Code, Gemini CLI, Aider, OpenCode, OpenClaw, Hermes Agent, Trae, Cursor, Cline, Windsurf, DeepSeek Harness) und ihre lokalen Sitzungsdateien gelesen. Keine Konfiguration, kein Proxy nötig. Terminal-Fans können `experientia daemon` nutzen, nur die Engine.
3. Für Funktionen auf Anfrageebene (Regel-Reinjektion in langen Sitzungen, Aufzeichnung pro Anfrage) zeigen Sie den Modellendpunkt Ihres Agenten auf `http://localhost:8100`. Lokale Modelle (llama.cpp, Ollama, vLLM) und Cloud-Modelle (OpenAI, Anthropic, jede OpenAI-kompatible API) funktionieren.
4. Arbeiten Sie wie gewohnt. Öffnen Sie nach ein paar Tagen die Wachstumsseite und sehen Sie nach, ob sich das Rad gedreht hat.

## Wo Ihre Daten liegen

```
~/.experientia/
├── experience.jsonl          # roher Erfahrungsstrom, dauerhaft
├── skills/<Stamm>/<Kat>.md   # Methoden, Erfolgsnotizen, Fehlermuster
├── preferences/<Stamm>.md    # Ihr Entscheidungsstil
├── sessions/                 # archivierte Sitzungen (überleben die Agenten-Bereinigung)
├── deprecated/               # verworfene Einträge, 30 Tage wiederherstellbar
├── rules.json                # aktive Regeln und Vorlagen
└── config.json               # Sprache, Schalter, Modell-Routing (API-Keys im OS-Schlüsselbund)
```

Vier Dinge, klar gesagt.

Keine Telemetrie, keine Absturzberichte, keine Analyse. Es gibt genau eine Art ausgehenden Verkehr, Ihre eigenen Modellaufrufe. Die App prüft nie auf Updates, lädt nichts herunter, installiert oder ersetzt sich nicht.

Export ist Kopieren. Alles, was Sie in der Oberfläche sehen, ist eine Datei, die Sie lesen, greppen und mitnehmen können.

Löschen ist endgültig. Nach zwei Bestätigungen ist das Datenverzeichnis weg. API-Keys im Schlüsselbund bleiben unberührt.

Ihre Assets gehören nicht uns. Die Lizenz unten gilt für den Produktcode. Die Erfahrung, Methoden und Präferenzen, die Sie ansammeln, gehören Ihnen, ohne Lizenzbeschränkung.

## Für KI-Agenten (Integrationshinweise)

Wenn Sie ein Agent sind und diese Datei lesen, um über Integration oder Zitierung zu entscheiden, ist dieser Abschnitt für Sie.

Kurzfassung. Experientia erfasst automatisch aus den Sitzungsdateien, die Agenten ohnehin schreiben (keine Konfiguration), destilliert wiederkehrende Arbeit zu geprüften dateibasierten Assets (Methoden, Fehlermuster, Präferenzen) und injiziert sie in spätere ähnliche Aufgaben. Der gesamte Zustand liegt als einfaches JSONL und Markdown unter `~/.experientia/`.

Vier Integrationswege, nach Treue geordnet.

1. **Proxy-Modus.** Modellendpunkt auf `http://localhost:8100` (OpenAI-kompatibel) zeigen. Zusätzlich zur Dateierfassung gibt es Aufzeichnung pro Anfrage, Injektion und Reinjektion harter Vorgaben.
2. **Dateierfassung** (Standard, keine Konfiguration). Parser pro Agent lesen die nativen Sitzungsspeicher (JSONL, SQLite, Markdown) und normalisieren sie. Erfasste Sitzungen werden nach `~/.experientia/sessions/` archiviert und überleben Bereinigung oder Deinstallation.
3. **Hook-Modus.** Bei Agenten mit Hooks (Claude Code zuerst) sendet ein HTTP-Hook Ereignisse in Echtzeit, und `SessionStart` / `UserPromptSubmit` injizieren Regeln ohne Proxy.
4. **Dateien direkt lesen.** Regeln lassen sich in native Konventionsdateien schreiben (etwa `AGENTS.md`). Jedes Asset-Paket lässt sich als `SKILL.md` nach dem offenen Standard von agentskills.io exportieren (Frontmatter plus When to Use, Procedure, Pitfalls, Verification) und von Hermes, OpenClaw, Claude Code und anderem laden. Rückwärts geht es auch.

Was es nicht ist. Keine Vektordatenbank, keine Memory-API, kein Cloud-Dienst, kein Fine-Tuning-Werkzeug. Es ändert keine Modellgewichte. Alles passiert in der Kontextschicht, deshalb verhalten sich lokale und Cloud-Modelle gleich.

Injizierte Einträge haben das Konfidenz-Gate passiert. Injektionsblöcke sind im Kontext markiert und von Nutzeranweisungen getrennt. Behandeln Sie sie als kuratiertes Vorwissen, nicht als Dogma.

## Entwicklung und Tests

Dieser Abschnitt wird vollständig in der englischen und der chinesischen Fassung gepflegt, damit die Sprachversionen nicht auseinanderlaufen. Details zu Tests, Packaging und Signierung stehen in [README.md](README.md).

## Lizenz

Der Code ist doppelt lizenziert. Nehmen Sie die Variante, die zu Ihrer Nutzung passt.

**Selbst nutzen, im Unternehmen intern nutzen, Forschung.** AGPLv3. Installieren und loslegen. Niemanden fragen, nichts bezahlen.

**Kommerzielle Nutzung, bei der Copyleft für Sie tragbar ist.** Ebenfalls AGPLv3. Verkaufen, ändern, betreiben ist erlaubt. Die Bedingung hat einen klaren Rand: Was Sie ändern oder in einen von Ihnen angebotenen Dienst integrieren, muss unter AGPLv3 veröffentlicht werden. Ihr eigener Produktcode wird nicht hineingezogen, solange beide getrennte Werke sind, die über eine Prozessgrenze oder eine Schnittstelle kommunizieren und kein gemeinsames Programm bilden.

**Sie können Ihre Integration nicht offenlegen, oder Sie wollen einen konkurrierenden Dienst bauen.** BUSL-1.1, kommerzielle Bedingungen per Vereinbarung; kontaktieren Sie den Maintainer. Auf diesem Weg bleibt nichtkommerzielle Nutzung kostenlos, und jede Version wechselt vier Jahre nach Veröffentlichung auf AGPLv3. Die Einschränkung ist befristet, nicht dauerhaft.

**Ihre Daten sind überhaupt nicht lizenziert.** Alles, was Sie mit Experientia ansammeln oder exportieren, von Rohsitzungen bis zu Methoden und Präferenzen, gehört Ihnen ohne jede Bedingung. Kommerziell, closed-source, an Dritte weitergeben: nichts davon ist eingeschränkt. Die Lizenz betrifft ausschließlich den Code dieses Produkts.

## Roadmap

v1.1 ist Open Source und kostenlos. Kein Login, kein Konto, keine Paywall, keine Teamfunktionen.

## Referenzen

- Anthropic, 2026 Agentic Coding Trends Report. Quelle der 55- und 40-Prozent-Zahlen zu gepflegten Kontextdateien
- SkillsBench, Benchmarking How Well Agent Skills Work Across Diverse Tasks, arXiv:2602.12670, Februar 2026
- Agent Skills Open Standard, agentskills.io, veröffentlicht am 18. Dezember 2025
- Erfahrung zu Skill ist ein aktives Forschungsfeld, ExpeL, ACE (Agentic Context Engineering), Voyager und Reinforcement Learning aus Erfahrung