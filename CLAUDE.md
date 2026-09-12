# CWB — Code Workbench

Barrierefreie Desktop-Oberfläche (PySide6) für Claude Code, für einen blinden
Nutzer per Spracheingabe/-ausgabe bedienbar. Jede Funktion ist über F-Taste
und Schaltfläche erreichbar; gesprochen wird nur, was der Nutzer wissen muss.

## Dateien in core/

- **fenster.py** — Hauptfenster (`Werkbank`), Aktivitätsbalken und `main()`.
  Gestaltung ausschließlich in `stil.qss`.
- **datenordner.py** — reines Python ohne Qt und ohne Log-Einrichtung beim
  Laden: kennt `%LOCALAPPDATA%\CWB`, wo Gedächtnis (`memory_hub/memory.db`)
  und Code-Index (`index/chroma_db`, `index/manifeste`, `index/.sperre`)
  liegen, damit sie jeden Programmwechsel überleben. `daten_umziehen()` holt
  alte Bestände aus dem Programmordner einmalig herüber (SQLite-Backup-API,
  Nachtrag fehlender Einträge, Ordner per Umbenennen) und wird von
  `pfade.py`, `memory_hub/memory_db.py` und `index/indexer.py` beim Laden
  aufgerufen — die beiden MCP-Server laufen auch ohne CWB. `erstuebernahme()`
  (aus `fenster.main()`) ist der Gegenfall: startet eine installierte Fassung
  mit leerem Datenordner, kopiert sie einmalig Gedächtnis, Index und
  `einstellungen.json` aus einer älteren Datenhaltung auf demselben Rechner
  (CWB-Ordner aus `~/.claude.json`, `%APPDATA%\CWB`); nie verschieben,
  Marker `uebernahme.json` im Datenordner, bei Fremden passiert still nichts.
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
  Alter. Liest zusätzlich Einträge aus dem projektübergreifenden Memory Hub
  (`memory_hub/memory.db`, `pfade.HUB_DATENBANK`), aber nur die des aktuellen
  Projekts bzw. `global` — direkt per SQLite, ohne Umweg über den MCP-Server.

## Dateien in index/

Code-Index: lokale semantische Codesuche über alle Projekte, die Robert je
in CWB öffnet — kein API-Schlüssel, rechnet mit `all-MiniLM-L6-v2`. Keine
feste Projektliste: jeder Ordner, den CWB öffnet, wird zu einem Eintrag.

- **indexer.py** — Chunking, Einbettung, ChromaDB-Anbindung (`chroma_db/`,
  eine Sammlung pro Projekt-Pfad-Hash), Datei-Stat-Manifest (`manifeste/`)
  für die Änderungserkennung, Schreibsperre (`.sperre`) gegen gleichzeitige
  Läufe. Alle drei liegen unter `%LOCALAPPDATA%\CWB\index\`
  (`core/datenordner.py`), nicht im Programmordner. `index_aktualisieren()` ist der einzige Indizier-Weg, für den
  ersten Lauf genauso wie für spätere.
- **cli.py** — Kommandozeile, ein Projektordner pro Aufruf; `sitzung.py`
  ruft das bei jedem Projektwechsel auf.
- **mcp_server.py** — MCP-Server (stdio), Werkzeug `code_suchen`.
  Läuft als eigener, in `~/.claude.json` registrierter Prozess; das
  Projekt erkennt er über sein eigenes Arbeitsverzeichnis, das CWB beim
  Verbindungsaufbau setzt (`core/sitzung.py`, `ClaudeAgentOptions.cwd`).
  Die Registrierung selbst ist Rechner-Sache, nicht Teil von CWB.

## Dateien in memory_hub/

Projektübergreifendes Gedächtnis, MCP-Server `memory-hub`. Der Code liegt
hier, die Datenbank unter `%LOCALAPPDATA%\CWB\memory_hub\memory.db`
(`pfade.HUB_DATENBANK`, `core/datenordner.py`) — anders als beim
Code-Index braucht `core/wissen.py` (`HubLeser`) hier keinen eigenen
MCP-Aufruf, sondern liest `memory.db` direkt per SQLite mit.

- **memory_db.py** — Schema (`CREATE TABLE IF NOT EXISTS`, legt die
  Datenbank beim ersten Aufruf selbst an), Lesen/Schreiben/Suche/FTS5,
  Projektverwaltung. `DB_PATH` kommt aus `core/datenordner.py`; neben der
  Datei liegt nur noch das Log.
- **memory_mcp.py** — MCP-Server (stdio), Werkzeuge `memory_search`,
  `memory_add`, `memory_list`, `memory_forget`, `memory_projects`,
  `memory_aufraeumen`.
- **aufraeumen.py** — Aufräummodus fürs Tagesende, pro Projekt: findet
  inhaltsleere Einträge (Meldungen übers Schreiben), Doppelungen (der
  ausführlichere bleibt), erledigte `[OFFEN]`-Vermerke (werden zu
  `[ERLEDIGT datum]`) und überholte Einträge (nur Hinweis). `analysieren()`
  ändert nichts und liefert einen Bericht zum Vorlesen; `ausfuehren()` setzt
  nur ausdrücklich genannte Nummern um und legt Gelöschtes vorher in
  `aufraeum_papierkorb.jsonl` neben der Datenbank ab (`wiederherstellen()`).
  Angeheftete Einträge werden nie angefasst. Auch als Kommandozeile nutzbar.

Nur diese Dateien plus `memory.db` sind Teil von CWB; die frühere
eigenständige GUI, das Audit-Werkzeug und die Dokumentation des Memory Hub
blieben bewusst im alten, eigenständigen Projektordner zurück.

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
