# CWB — Code Workbench

Barrierefreie Desktop-Oberfläche (PySide6) für Claude Code, für einen blinden
Nutzer per Spracheingabe/-ausgabe bedienbar. Jede Funktion ist über F-Taste
und Schaltfläche erreichbar; gesprochen wird nur, was der Nutzer wissen muss.

## Dateien in core/

- **fenster.py** — Hauptfenster (`Werkbank`), Aktivitätsbalken und `main()`.
  Gestaltung ausschließlich in `stil.qss`.
- **grundlagen.py** — Pfade, Log-Einrichtung, `einstellungen.json`, Skalierung des
  Stilblatts, Liste der offenen Fenster, `slot_geschuetzt`. Liegt getrennt, weil
  fenster.py beim Start als Hauptmodul läuft und nicht zurückimportiert werden darf.
- **faden.py** — `SitzungsFaden`, hält die `Sitzung` in einem eigenen Thread und
  meldet sich nur über Qt-Signale zurück.
- **projektwahl.py** — `ProjektListe` und die Startansicht `Start`. Welche Klasse
  geöffnet wird, reicht der Aufrufer als `werkbank_klasse` herein.
- **einstellungen.py** — `EinstellungenFenster`, die Seite hinter F12 und der
  Kachel „Einstellungen“: Sprache (Ausgabeweg, Stimme, Tempo, Probehören), Töne
  (Hauptschalter und drei Gruppen), Verhalten und die Anzeige der geladenen Skills.
  Änderungen wirken sofort und landen in `einstellungen.json`.
- **kopfzeile.py** — `Ausgabekopf`: Tätigkeitsplakette, Dateianzeige,
  Statusmeldung, Tokenzähler, Modellwahl (Auswahlfeld) und Kopieren-Schaltfläche.
- **modelle.py** — wählbare Modelle: deutsche Kurzhinweise, Rückfallliste und
  die Merkfunktionen für `einstellungen.json` (Schlüssel `modell`). Welche
  Modelle das Abo hergibt, liest `sitzung.py` bei jeder Verbindung frisch über
  `get_server_info()["models"]` — dieselbe Liste, aus der `claude --model` wählt.
- **sitzung.py** — Anbindung ans Claude Agent SDK. `Sitzung` führt Aufträge aus,
  meldet Ereignisse/Zustände (Balkenfarbe, Ton), prüft Berechtigungen über
  `sicherheit.Wache`, stellt Rückfragen bei kritischen Aktionen, zählt Tokenverbrauch.
- **sicherheit.py** — reines Python, keine Oberfläche. `Ordnergrenze` hält Zugriffe
  im Projektordner und sperrt Geheimnisdateien (.env, Keys, …). `GitNetz` legt vor
  jedem Auftrag einen Git-Sicherungspunkt an und kann zurückrollen. Klassifiziert
  Shell-Befehle in frei / rückfragepflichtig / verboten. `Wache` bündelt beides.
- **sprache.py** — Sprachausgabe und Signaltöne. Wege: Edge-TTS (Standard, braucht
  Internet), SAPI (Windows-Bordstimme, Rückfall), NVDA (spricht durch Screenreader),
  stumm. Erzeugte Sätze werden in `.stimmen/` zwischengespeichert.
- **wissen.py** — Projektgedächtnis: `CLAUDE.md` im Projekt (Grundlagen),
  `wissen/tagebuch.md` (Verlauf), `wissen/offen.md` (offene Punkte), Archiv nach
  Alter. Liest zusätzlich einträge aus dem projektübergreifenden Memory Hub
  (`memory_hub/memory.db`), aber nur die des aktuellen Projekts bzw. `global`.

## Dateien in index/

Code-Index: lokale semantische Codesuche über alle Projekte, die Robert je
in CWB öffnet — kein API-Schlüssel, rechnet mit `all-MiniLM-L6-v2`. Keine
feste Projektliste: jeder Ordner, den CWB öffnet, wird zu einem Eintrag.

- **indexer.py** — Chunking, Einbettung, ChromaDB-Anbindung (`chroma_db/`,
  eine Sammlung pro Projekt-Pfad-Hash), Datei-Stat-Manifest (`manifeste/`)
  für die Änderungserkennung, Schreibsperre (`.sperre`) gegen gleichzeitige
  Läufe. `index_aktualisieren()` ist der einzige Indizier-Weg, für den
  ersten Lauf genauso wie für spätere.
- **cli.py** — Kommandozeile, ein Projektordner pro Aufruf; `sitzung.py`
  ruft das bei jedem Projektwechsel auf.
- **code_index_mcp.py** — MCP-Server (stdio), Werkzeug `code_suchen`.
  Läuft als eigener, in `~/.claude.json` registrierter Prozess; das
  Projekt erkennt er über sein eigenes Arbeitsverzeichnis, das CWB beim
  Verbindungsaufbau setzt (`core/sitzung.py`, `ClaudeAgentOptions.cwd`).
  Die Registrierung selbst ist Rechner-Sache, nicht Teil von CWB.

Einstiegspunkt ist `fenster.main()`.

## Konventionen

- Strikte Trennung: keine Inline-Scripts, keine Inline-Styles, keine
  Inline-Event-Handler. Scripts in .js, Styles in .css, Handler nur über
  `addEventListener`.
- Barrierefreiheit hat Vorrang, die Oberfläche muss für sehende Nutzer trotzdem
  gut aussehen.
- Flexible, responsive Raster. Keine festen Pixelgrößen.
- Jede neue Werkzeugdatei bekommt Fehler-Logging über das Modul `logging`
  (siehe Muster in core/*.py: eigener Logger je Modul, Datei `cwb_fehler.log`).
- Deutsche Bezeichner im gesamten Code (Klassen, Funktionen, Variablen).
- Lies eine Datei, bevor du sie änderst.
- Antworte kurz: ein bis drei Sätze zum Ergebnis, keine langen Erklärungen.
- Ist etwas unklar, unmöglich oder unlogisch: sag es in einem Satz statt zu raten.
- Alte Memory-Hub-Einträge zu Deploy und FILE/END-Markern gelten für CWB
  nicht: CWB schreibt Dateien direkt auf die Platte, ohne Deploy-System.

## Sparsam arbeiten

- Weißt du schon, wonach du suchst: Datei gezielt mit Zeilenbereich lesen,
  nicht komplett.
- Erst mit Grep die Stelle finden, dann erst lesen — nicht die ganze Datei
  durchsuchen, indem du sie einliest.
- Nie lesen: `.stimmen/`, `.ablage/`, `.cwb/`, `__pycache__/`, `.git/`.
- Jede Datei nur einmal pro Sitzung lesen.
