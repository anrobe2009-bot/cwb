# CWB – Anweisung für die KI im Chat

Stand: 13.09.2026. Abgelesen aus dem Code im Ordner `C:\Users\Entwickler\Desktop\start\CWB`
(core/*.py, index/*.py, memory_hub/*.py, CLAUDE.md, stil.qss, verlauf.css, Startskripte,
einstellungen.json). Nichts in dieser Datei ist geraten; wo der Code eine Frage offen lässt,
steht ausdrücklich **ungeklärt**. Diese Datei ersetzt `ctb_anweisung_fuer_ki.txt` und
`deploy_system_anleitung_claude.md`.

---

## 1. Was CWB ist

- **Name:** CWB – Code Workbench. Deutsche Bezeichner im gesamten Code.
- **Zweck:** Eine barrierefreie Desktop-Oberfläche (PySide6/Qt) für Claude Code. Sie hält
  eine durchgehende Claude-Code-Sitzung je Projekt, nimmt Aufträge an, spricht Ergebnisse
  aus und legt vor jedem Auftrag einen Git-Sicherungspunkt an. Claude Code läuft dabei
  als Unterprozess über das Claude Agent SDK (`core/sitzung.py`, `ClaudeSDKClient`).
- **Ordner:** Programm: `C:\Users\Entwickler\Desktop\start\CWB`. Einstellungen und Log
  liegen im Programmordner (`einstellungen.json`, `cwb_fehler.log`, rotierend 500 KB × 3).
  Laufzeitdaten, die einen Programmwechsel überleben müssen, liegen unter
  `%LOCALAPPDATA%\CWB` (`core/datenordner.py`): `memory_hub\memory.db`, `index\chroma_db`,
  `index\manifeste`, `index\.sperre`. Je Projekt entsteht ein Ordner `.cwb\` mit
  `protokoll\`, `bericht\`, `bilder\` sowie ein Ordner `wissen\` und – falls fehlend –
  eine `CLAUDE.md`.
- **Kein Terminalfenster:** CWB startet über `CWB starten.vbs` mit `pythonw.exe`
  (Fenster ausgeblendet, `shell.Run befehl, 0`). Die Claude-Code-CLI wird mit
  `CREATE_NO_WINDOW` gestartet (`sitzung.py`, `_unterdruecke_konsolenfenster`), PowerShell-
  Befehle ebenfalls ohne sichtbares Fenster. Weil es keine Konsole gibt, landet jeder Fehler
  ausschließlich in `cwb_fehler.log` (`sys.excepthook`, `slot_geschuetzt`).
- **Modell:** Voreinstellung `default` – CWB gibt dann **kein** Modell an und lässt Claude
  Code entscheiden (`sitzung.py`, `self.modell = None`). Die Rückfallliste in
  `core/modelle.py` (Stand 05.09.2026) löst `default` als `claude-opus-5[1m]` auf. Die
  tatsächlich angebotenen Modelle liest CWB bei jeder Verbindung über
  `get_server_info()["models"]`; wählbar unter F12. In `einstellungen.json` steht derzeit kein
  Schlüssel `modell`, also gilt `default`. Der wirklich aufgelöste Modellname steht nach dem
  Verbinden im Log („Sitzung verbunden … Modell …“). Eine Haiku-Funktion zum „Schärfen“
  eines Auftrags existiert im Code (`Sitzung.schaerfen`), wird aber von der Oberfläche
  nicht aufgerufen (nur im Selbsttest).
- **System-Prompt:** Preset `claude_code` plus ein fester Zusatz (`SYSTEM_ZUSATZ` in
  `sitzung.py`: blinder Nutzer, kurz antworten, strikte Trennung von Script/Style/Handler,
  keine festen Pixelgrößen, Logging, Datei vor Änderung lesen, Unklares in einem Satz
  benennen). `setting_sources=["user","project"]`: die globale `~/.claude/CLAUDE.md` und die
  `CLAUDE.md` des offenen Projekts werden von Claude Code selbst geladen.
  `permission_mode="default"`, jede Werkzeugfreigabe geht durch `Sitzung._darf_werkzeug`.
- **Start:** Doppelklick `CWB starten.vbs` (sucht pythonw in Registry/PATH, startet
  `core\fenster.py`), alternativ `python core/fenster.py`. `CWB neu starten.bat` beendet
  laufende `pythonw … fenster.py`-Prozesse und startet neu. Im Fenster: **Strg+F4** =
  kompletter Neustart (neuer Prozess), **F9** = Projekt wechseln. Beim Start öffnet CWB
  ohne Nachfrage das zuletzt geöffnete Projekt (`einstellungen.json` → `letztes_projekt`,
  aktuell „CWB“). Es gibt außerdem eine gepackte Installation unter
  `AppData\Local\Programs\CWB` mit `starter.py` (`sys.frozen`); welche Fassung gerade
  läuft, ist aus dem Code nicht ablesbar – **ungeklärt** (steht im Log als „Werkbank startet
  aus …“).

---

## 2. Für wen

Robert ist blind, arbeitet per Spracheingabe und lässt sich Ausgaben vorlesen. Er nutzt
**keinen Screenreader**; CWB spricht selbst (`core/sprache.py`): Wege `edge` (Edge-TTS,
Internet, Standard), `sapi` (Windows-Bordstimme, Rückfall), `nvda`, `stumm`. Erzeugte
Sätze werden unter `.stimmen\` zwischengespeichert. Zusätzlich gibt es zwölf Signaltöne je
Zustand (`.toene\`), in drei Gruppen abschaltbar.

### Was CWB von sich aus spricht

Es gilt eine harte Sperre (`sprache.py`, `ERLAUBTE_ARTEN = {"immer","auftrag","fertig",
"fehler","frage"}`). Nur Sätze dieser Arten werden überhaupt gesprochen:

| Anlass | Gesprochener Satz |
| --- | --- |
| Auftrag angenommen (jeder Weg) | „Auftrag erhalten.“ |
| Auftrag angenommen, aber einer läuft schon | „Auftrag erhalten, er wartet noch.“ |
| Claude-Code-Auftrag fertig | „Fertig.“ + ggf. „Bericht-Datei liegt in der Zwischenablage.“ / „Bericht-Text liegt in der Zwischenablage.“ |
| Fehler | „Fehler. …“ (auf zwei Sätze gekürzt, Pfade durch „Datei“ ersetzt) |
| Not-Aus verarbeitet | „Abgebrochen.“ |
| Rückfrage (Bash-Befehl, Internet, Admin, Dublette) | kurzer Anlass + „Fortfahren?“ bzw. „Auftrag wiederholen?“ – **Eingabe = ja, Escape = nein** |
| Abgelehnte Aktion (Sperrliste, Nur-Lesen, verbotener Befehl) | kurzer Grund ohne Pfad |
| Auftrag gehört zu anderem Projekt | „Auftrag gehört vermutlich zu Projekt X, hier nicht ausgeführt.“ |
| #RUN#/#ADMIN# fertig | „Terminalbefehl fertig. Ergebnis eingefügt.“ oder „… Ergebnis liegt in der Zwischenablage.“ / „Terminalbefehl fehlgeschlagen.“ |
| #BILD# fertig | „Screenshot bereit.“ |
| Ausnahme in einem Qt-Slot | „Fehler in der Oberfläche, steht im Log“ |

**Auf Tastendruck (Art „immer“, spricht in jeder Stufe):** F1 Hilfe (liest alle Kürzel),
F2 „Wo stehen wir“ (Schritt, Dauer, letzter Schritt bzw. Tokenstand), F3 letzte Antwort,
Strg+L markierter Text, Probehören in den Einstellungen, Ersteinrichtung.

**Im Code vorhanden, aber durch `ERLAUBTE_ARTEN` stumm** (Art „meldung“ oder ohne Art):
„Bereit.“ nach dem Verbinden (nur Ton), „Nur lesen.“/„Lesen und Schreiben erlaubt.“ (F10),
„Not-Aus.“, „Warteschlange geleert …“, „Ausgabe kopiert.“, „Bild angehängt“, „Projekt
wechseln.“, „Öffne X.“, „Ja.“/„Nein.“ nach einer Rückfrage, „Terminalbefehl läuft…“,
„Screenshot wird geholt…“, „Bericht-Text liegt jetzt in der Zwischenablage.“ (F6),
„Bitte Rechteanforderung von Windows bestätigen.“ (vor dem UAC-Dialog – nur der Ton
„wartet“ kommt durch), sämtliche Bestätigungen in den Einstellungen, die Ansage bei
Mauszeiger. Ob das so gewollt ist, ist aus dem Code nicht ablesbar – **ungeklärt**
(Kommentar: „seit der Reduzierung der Sprachausgabe“).

### Tastenkürzel (aus `fenster.py`, `_tasten`)

Strg+Eingabe abschicken · F7 Zwischenablage abschicken (Notweg, der Wächter tut das sonst
selbst) · F8 Not-Aus · Escape Ansage abbrechen bzw. Rückfrage mit Nein · Eingabe Rückfrage
mit Ja · F1 Hilfe · F2 Wo stehen wir · F3 letzte Antwort · Strg+L Markiertes · Strg+K Ausgabe
kopieren · Strg+0 Schrift zurück · F10 Nur lesen an/aus · Strg+Z letzten Auftrag zurücknehmen
(Git) · Strg+B Bild anhängen · F5 Eingabefeld / nach Projektwarnung „trotzdem hier“ · F6
Bericht-Text kopieren · Strg+F6 Berichtordner öffnen · Strg+F7 Bericht-Datei kopieren · F11
zum Verlauf · F9 Projekt wechseln · F4 Warteschlange leeren · Strg+F4 Neustart · F12
Einstellungen. Strg+V mit einem Bild in der Zwischenablage hängt es an. Die README im
Ordner ist an mehreren Stellen älter als der Code (F4/F6-Belegung, Memory-Hub-Frage bei
der Ersteinrichtung) – maßgeblich ist der Code.

---

## 3. Die Trigger

Auswertende Stelle: `fenster.py`, `markierung_erkennen()` mit `_MARKIERUNGEN`. Der Code
kennt **genau vier** Markierungen: `#CODE#`, `#RUN#`, `#ADMIN#`, `#BILD#`. Weitere gibt es
nicht.

### Gemeinsame Regeln der Erkennung

- Die Markierung muss **allein in der ersten nicht-leeren Zeile** stehen. Erkannt wird
  `kopf.strip(RANDZEICHEN).upper()` – also Groß-/Kleinschreibung egal (`#code#`, `#Run#`),
  Leerzeichen, Tabs, Leerzeilen, geschütztes Leerzeichen, Nullbreite-Zeichen und
  BOM davor werden übergangen. Steht in der ersten Zeile noch etwas anderes
  (`#CODE# bitte …`), wird **keine** Markierung erkannt.
- Alles unter der Markierungszeile ist der Inhalt; die Markierungszeile selbst wird nie
  mitgeschickt.
- **Fallstrick Code-Zaun:** Wird ein Block samt Markdown-Zaun (```` ``` ````) kopiert, ist
  die erste Zeile der Zaun und nicht die Markierung → keine Erkennung. Wie Robert kopiert
  (mit oder ohne Zaun), ist aus dem Code nicht ablesbar – **ungeklärt**. Sicher ist nur:
  die Markierung muss die erste Zeile des kopierten Textes sein.
- **Drei Wege ins System:** (a) Zwischenablage-Wächter (`core/ablagewaechter.py`): prüft
  alle 2 s, ob Text mit Markierung in der Zwischenablage liegt; ohne Markierung passiert
  nichts; ohne Inhalt (außer #BILD#) passiert nichts; bei Treffer wird die
  **Zwischenablage sofort geleert** und der Auftrag ausgeführt – derselbe Text kann so nie
  zweimal auslösen. Schaltbar über F12 → Verhalten → „Zwischenablage überwachen“
  (`ablage_waechter`, derzeit an). (b) F7: liest die Zwischenablage von Hand; ohne
  Markierung wird der ganze Text als gewöhnlicher Auftrag geschickt; nur Markierung ohne
  Inhalt → ganzer Text als Auftrag. (c) Eingabefeld + Strg+Eingabe: dieselbe Erkennung.
- Aufträge **ohne** Markierung gehen (über F7 oder Eingabefeld) als gewöhnlicher
  Claude-Code-Auftrag durch; der Wächter ignoriert sie.

### `#CODE#` – Auftrag an Claude Code

- **Wofür:** Alles, was Claude Code im Projekt tun soll (lesen, ändern, suchen, Bash,
  MCP-Werkzeuge `memory_search`, `memory_add`, `code_suchen` usw.).
- **Kopfzeile:** genau `#CODE#` allein in Zeile 1. Darunter der Auftragstext.
- **Was passiert:** Text landet im Eingabefeld und geht über `_absenden` → Arbeitsfaden →
  `Sitzung.auftrag()`. Ausgabefeld wird geleert, Aktivitätsbalken läuft, Sekundenzähler
  startet. Nach Abschluss: Bericht wird gebaut und in die Zwischenablage gelegt (siehe 4).
- **Kosten:** Token beim gewählten Modell. Zusätzlich stellt CWB **nach jedem Auftrag eine
  zweite Anfrage** an dieselbe Sitzung (`NACHTRAG_ANWEISUNG`: Zusammenfassung fürs
  Tagebuch) – das kostet erneut Token, wird nicht gesprochen und nicht im Ausgabefeld
  gezeigt. Beim **ersten Auftrag einer Sitzung** wird der Kontextblock aus dem
  Projektgedächtnis vorangestellt (bis 12.000 Zeichen, siehe 7).
- **Fallstricke aus dem Code:**
  - *Dublette:* Nur wenn F12 → „Doppelte Aufträge nachfragen“ an ist (Schalter
    `dubletten_pruefung`, derzeit **aus**) – dann löst praktisch gleicher Text (Leerraum
    geglättet) innerhalb von 10 Minuten die Rückfrage „Auftrag wiederholen?“ aus statt der
    Ausführung; Eingabe = ja. Steht der Schalter aus, läuft jede Wiederholung ohne
    Rückfrage durch.
  - *Projektzuordnung* (`core/zuordnung.py`): Nennt der Text Dateien, die es im offenen
    Projekt nicht gibt, wohl aber in genau einem anderen Projekt der Projektliste – oder
    nennt er den Namen eines anderen Projekts (≥ 3 Zeichen, als eigenes Wort) und nicht den
    des offenen –, wird der Auftrag **nicht ausgeführt**, sondern vorgemerkt: „Auftrag gehört
    vermutlich zu Projekt X …“. F9 wechselt dorthin (Auftrag läuft dann dort von allein), F5
    führt ihn trotzdem hier aus. Wer das offene Projekt im Text nennt (z. B. erste
    Inhaltszeile `Projekt: CWB`), schaltet die Namensregel ab. Die Projektliste besteht
    derzeit nur aus den Zusatzprojekten CWB, hausgemacht, assistenz.
  - *Warteschlange:* Läuft schon ein Auftrag, reiht sich der neue ein und startet danach
    von allein; F4 leert die Schlange, F8 bricht den laufenden ab und verwirft die Schlange.
  - *Git-Commit mit Auftragstext:* Vor jedem Auftrag `git add -A` + Commit mit den ersten
    120 Zeichen des Auftrags als Nachricht („CWB Sicherungspunkt: …“), und – wenn ein Remote
    eingetragen ist – **`git push` ohne Rückfrage** (`sicherheit.py`, `_push_versuchen`).
    Der Auftragsanfang wird also ggf. öffentlich. Nichts Vertrauliches in die ersten Zeilen.
  - *Nur-Lesen-Modus (F10):* Write/Edit/MultiEdit/NotebookEdit und schreibende
    Bash-Befehle werden hart abgelehnt; der Auftrag bekommt einen Hinweis vorangestellt.
  - *Kein Ergebnis:* Bleibt die `ResultMessage` aus, meldet CWB Fehler, verbindet neu und
    bittet um Wiederholung des Auftrags.
  - *Bilder:* Per Strg+B oder Strg+V angehängte Bilder gehen nur mit dem **nächsten**
    Auftrag mit (auch aus der Zwischenablage), danach ist die Liste leer.

### `#RUN#` – PowerShell-Befehl ohne Claude Code

- **Wofür:** Einen Befehl direkt ausführen (Tests, git, Skripte, `python …`), ohne Modell.
- **Kopfzeile:** `#RUN#` allein in Zeile 1. Darunter der Befehl, auch mehrzeilig (wird in
  eine temporäre `.ps1` geschrieben, UTF-8 ohne BOM, LF, und mit `powershell.exe -NoLogo
  -NoProfile -NonInteractive -ExecutionPolicy Bypass -File` gestartet). Vorangestellt wird
  `[Console]::OutputEncoding = UTF8; $OutputEncoding = UTF8;`.
- **Was passiert:** Arbeitsverzeichnis = Projektordner. Ausgabefeld wird geleert, Zeilen
  erscheinen live, stdout und stderr gemeinsam. Zeitlimit **120 s**, dann Abbruch. Danach
  legt CWB die Ausgabe als Text in die Zwischenablage, holt das **zuletzt aktive fremde
  Fenster** nach vorn und sendet **Strg+V** (`core/zielfenster.py`) – das Ergebnis erscheint
  also von selbst im Chat-Eingabefeld, aus dem der Befehl kam. Kennt CWB noch kein
  Zielfenster, bleibt die Ausgabe nur in der Zwischenablage. Ausnahme: Befehle, die
  `android_screenshot.py` enthalten – dort bleibt das Bild in der Zwischenablage.
- **Kosten:** keine Token.
- **Fallstricke:** Verbotene Befehle (`BEFEHL_VERBOTEN`: format, diskpart, mkfs, shutdown,
  Löschen einer Laufwerkswurzel, `rm -rf /`, `reg delete`, `cipher /w`) werden immer
  abgelehnt. Rückfragepflichtige Befehle (Löschen, Verschieben, git push, git reset
  --hard, pip/npm/winget, curl/wget, Start-Process, schtasks, netsh …) fragen **nur**, wenn
  F12 → „Sicherheitsrückfrage bei Befehlen“ an ist – derzeit **aus**, also läuft alles außer
  Verbotenem ohne Rückfrage. Im Nur-Lesen-Modus werden schreibende Befehle abgelehnt.
  Die Ordnergrenze (Pfadprüfung) wird bei #RUN# **nicht** angewandt – nur die Befehlsprüfung.
  Es läuft immer nur ein Terminalbefehl zugleich („Es läuft schon ein Terminalbefehl.“).
  Nach der Markierung muss ein Befehl stehen, sonst „Nach der Markierung steht kein
  Befehl.“ Keine Dublettenprüfung, wenn der Befehl über Wächter oder F7 kommt.
  Ein gleichzeitig laufender Claude-Auftrag schreibt währenddessen nicht ins Ausgabefeld;
  sein Text wird nachgetragen.

### `#ADMIN#` – PowerShell mit erhöhten Rechten

- **Wofür:** Befehle, die Administratorrechte brauchen.
- **Kopfzeile:** `#ADMIN#` allein in Zeile 1, darunter der Befehl.
- **Was passiert:** Beim ersten Admin-Befehl je CWB-Prozess startet CWB sich selbst als
  erhöhten Worker (`ShellExecuteEx runas`) → Windows zeigt den **UAC-Dialog**, den Robert
  bestätigen muss (Ton „wartet“; die Ansage dazu ist stumm, siehe 2). Aufträge gehen als
  HMAC-signierte JSON-Dateien über `%TEMP%\cwb_admin_cmd.json` / `cwb_admin_res.json`; der
  Schlüssel entsteht je Programmstart im Speicher. Zeitlimit im Worker **300 s**, CWB wartet
  bis **420 s**. Keine Live-Ausgabe, nur das Endergebnis; Rückspielung ins Zielfenster wie
  bei #RUN#.
- **Kosten:** keine Token.
- **Fallstricke:** Wird der UAC-Dialog abgelehnt, gibt es in diesem Prozess **keinen
  zweiten Versuch** – jeder weitere #ADMIN# läuft bis zum Zeitlimit ins Leere; Abhilfe ist
  ein Neustart (Strg+F4). Der Worker beendet sich, wenn `%TEMP%\cwb_admin_lock` länger als
  5 s fehlt (CWB geschlossen). Die feste Admin-Rückfrage gilt ebenfalls nur bei
  eingeschalteter „Sicherheitsrückfrage bei Befehlen“ – derzeit fragt #ADMIN# **nicht**
  zurück. Verbotene Befehle und Nur-Lesen gelten wie bei #RUN#.

### `#BILD#` – Android-Screenshot

- **Wofür:** Screenshot des per USB/adb verbundenen Android-Geräts in die Zwischenablage
  legen (als Dateiverweis, wie „Datei kopieren“ im Explorer), damit er per Strg+V als
  Anhang in den Chat kann.
- **Kopfzeile:** `#BILD#` allein – **kein Inhalt nötig**, Text darunter wird ignoriert.
- **Was passiert:** `adb exec-out screencap -p` (Zeitlimit 20 s), Datei
  `%USERPROFILE%\Downloads\android_screenshot.png` (wird jedes Mal überschrieben),
  Dateiverweis (CF_HDROP) in die Zwischenablage, Ansage „Screenshot bereit.“ Kein
  Eingabefeld, kein Ausgabefeld, keine Rückspielung in ein Fenster. Läuft im eigenen Thread.
- **Kosten:** keine Token.
- **Fallstricke:** Braucht `adb` im PATH und ein verbundenes, freigegebenes Gerät, sonst
  Fehleransage. Nur ein Screenshot-Auftrag zugleich. Für Aufrufe aus anderen Projekten
  gibt es zusätzlich den alten Weg `#run# python C:\Users\Entwickler\.cwb-werkzeuge\
  android_screenshot.py` (optional `--zwischenablage`); ob die Datei dort liegt, ist aus dem
  CWB-Code nicht prüfbar – **ungeklärt**.
- **Vierter Weg ohne Chat:** die Pause-Taste (core/pausetaste.py), systemweiter
  Win32-Hotkey ohne Zusatztaste, unabhängig davon, welches Fenster gerade vorn ist. Löst
  denselben Ablauf aus wie ein #BILD#-Auftrag (`fenster.py`, `_bild_markierung`), keine
  eigene Logik. Schaltbar über F12 → Verhalten → „Pause-Taste holt Screenshot“
  (`pause_screenshot`, Standard an) – die Einstellung wird bei jedem Tastendruck neu
  gelesen, ein Umschalten wirkt sofort. Ist die Taste von einem anderen Programm belegt,
  bleibt CWB bedienbar; Fehler stehen im Log und werden beim Start einmal angesagt.

---

## 4. Was CWB von sich aus tut

### Git-Sicherungsnetz (`core/sicherheit.py`, `GitNetz`)
- Hat das Projekt kein eigenes Repository (Wurzel = Projektordner), legt CWB eines an:
  `git init`, `user.name CWB`, `user.email cwb@lokal`, ergänzt `.gitignore`
  (`__pycache__/`, `.env`, `*.key`, `*.log` …), Commit „CWB: Ausgangsstand“.
- Vor jedem Claude-Code-Auftrag: gibt es Änderungen, `git add -A` + Commit „CWB
  Sicherungspunkt: <erste 120 Zeichen des Auftrags>“ + stiller `git push`, falls ein Remote
  existiert. HEAD wird als Sicherungspunkt gemerkt.
- Nach dem Auftrag: geänderte Dateien = `git diff --name-only <punkt>` + neue, nicht
  ignorierte Dateien, ohne `.stimmen`, `.toene`, `.ablage`, `.cwb`, `__pycache__`.
- **Strg+Z** = `git reset --hard <punkt>` + `git clean -fd` → stellt den Stand vor dem
  letzten Auftrag her; **neue, nicht versionierte Dateien werden dabei gelöscht**.
- Ohne installiertes Git läuft CWB weiter, ohne Sicherungsnetz (Projektansage „ohne
  Sicherungsnetz“). Für #RUN#/#ADMIN#/#BILD# gibt es keinen Sicherungspunkt.

### Ordnergrenze und Sperrliste (`Ordnergrenze`, `Wache`)
- **Sperrliste (immer hart):** `.env*`, `secrets.*`, `credentials.*`, `.netrc`, `.npmrc`,
  `.pypirc`, `id_rsa`/`id_ed25519`, `.ssh/`, `.aws/`, `*token*.json|txt|ini|cfg`,
  `*passwort*`-Dateien, `*.pem|key|pfx|p12|keystore|jks` – weder lesen noch schreiben, in
  jedem Ordner.
- **Freigaben:** Liste in `einstellungen.json` → `freigaben` (F12 → Freigaben); aktuell:
  Skill-Ordner, Claude-Temp-Ordner, `.cwb-werkzeuge`, `code_index`, `packer`, `C:\Projekte`,
  `CWB`, `claude_agent_sdk`. Sie werden beim Verbinden als `add_dirs` an Claude Code
  gegeben.
- **Pfad außerhalb von Projekt und Freigaben:** wird **nicht abgelehnt**, sondern der
  Ordner automatisch als neue Freigabe eingetragen und der Zugriff erlaubt
  (`Ordnergrenze.pruefe`, „automatisch als Freigabe eingetragen“). Die Grenze hält also nur
  Geheimnisdateien fern. Ob die Claude-Code-CLI selbst Zugriffe außerhalb von `cwd` +
  `add_dirs` zusätzlich sperrt, ist aus dem CWB-Code nicht ablesbar – **ungeklärt**;
  sicher ist: neue `add_dirs` wirken erst bei der nächsten Verbindung.

### Rückfragen (`Sitzung._darf_werkzeug`, `Wache.darf_befehl`)
- Bash-Befehle: verboten → Ablehnung; rückfragepflichtig → gesprochene Rückfrage, **nur
  wenn** `rueckfrage_bei_befehl` an ist (derzeit aus → alles Nichtverbotene läuft durch).
  Bei eingeschalteter Rückfrage gelten drei Ausnahmen: `internet_ohne_rueckfrage`,
  `loeschen_ohne_rueckfrage` (nur Ziele im Projektordner, keine Platzhalter),
  `installieren_ohne_rueckfrage` – alle drei derzeit an.
- WebFetch/WebSearch: Rückfrage „Zugriff auf das Internet“, außer
  `internet_ohne_rueckfrage` ist an (ist an).
- Rückfrage beantworten: **Eingabetaste = ja, Escape = nein**; Escape bricht zuerst eine
  laufende Ansage ab und lehnt erst beim zweiten Druck ab.
- Nur-Lesen (F10): schreibende Werkzeuge und Befehle abgelehnt.

### Auftragsprotokoll (`sitzung.py`, `_protokoll_schreiben`)
- Je Claude-Code-Auftrag eine Markdown-Datei
  `<Projekt>\.cwb\protokoll\JJJJ-MM-TT_HH-MM-SS.md` mit Auftrag, allen Werkzeugaufrufen
  (Name, Ziel, Ergebnis bis 300 Zeichen), Ablehnungen, Rückfragen samt Antwort, geänderten
  Dateien, Tokenverbrauch. Nicht für #RUN#/#ADMIN#/#BILD#.

### Bericht in der Zwischenablage (`fenster.py`, `_fertig`, `_bericht_*`)
- Nach jedem Claude-Code-Auftrag baut CWB einen Textbericht: Projekt, Zeit, Auftrag,
  Antwort (nur der Antworttext, keine Werkzeugausgaben), Fehler/Abbruch, geänderte
  Dateien, Tokenverbrauch. Er wird unter `<Projekt>\.cwb\bericht\` gespeichert –
  als **ZIP mit einer .txt darin** (`bericht_als_zip`, Standard an) oder als .txt; die
  jüngsten 30 bleiben.
- Ist das CWB-Fenster im Vordergrund, legt CWB die **Berichtdatei als Dateiverweis**
  (CF_HDROP) in die Zwischenablage, sonst den Text; ist es nicht im Vordergrund, wird das
  beim nächsten Aktivieren nachgeholt und angesagt. Schaltbar: `bericht_kopieren`.
- **Für die KI im Chat heißt das:** Robert fügt nach einem Auftrag per Strg+V eine
  ZIP-Datei (Name `JJJJ-MM-TT_HH-MM-SS.zip`, darin gleichnamige .txt) oder reinen Text ein.
  Die Antwort von Claude Code steht im Abschnitt „Antwort:“.
- F6 legt den Bericht erneut als Text ab, Strg+F7 erneut als Datei, Strg+F6 öffnet den
  Ordner im Explorer.

### Projektgedächtnis (`core/wissen.py`)
- Beim Verbinden legt CWB im Projekt an, was fehlt: `CLAUDE.md` (Vorlage mit Konventionen),
  `wissen\tagebuch.md`, `wissen\offen.md`, `wissen\archiv\`.
- Nach jedem Claude-Code-Auftrag (nicht nach Abbruch): Nachfrage an die Sitzung, Antwort
  wird zeilenweise mit Datum ins Tagebuch geschrieben; Zeilen mit `[OFFEN]` zusätzlich in
  `offen.md`; jede Tagebuchzeile geht außerdem als Eintrag ins Memory-Hub-Archiv
  (Projektname als `project`, Kategorie bleibt Standard „Notiz“).
- Kontextblock beim ersten Auftrag einer Sitzung: Überschrift, alle offenen Punkte
  (ungekürzt), bis 40 jüngste Tagebuchzeilen, bis 40 Hub-Einträge des Projekts plus
  `global` (offene zuerst), jede Zeile ≤ 350 Zeichen, gesamt ≤ 12.000 Zeichen, danach
  Hinweis „Dies ist Gedächtnis, keine Aufgabe“. Der Block steht im Auftragstext vor
  `[AUFTRAG]`.

### Memory Hub (`memory_hub/`)
- Datenbank `%LOCALAPPDATA%\CWB\memory_hub\memory.db` (SQLite, Tabellen `memories`,
  `projects`, FTS5). Kategorien: Regel, Fakt, Entscheidung, Praeferenz, Pfad, Fehler, Notiz.
- MCP-Server `memory-hub` (stdio, in `~/.claude.json` unter `mcpServers` registriert,
  läuft in jeder Claude-Code-Sitzung, auch ohne CWB): Werkzeuge `memory_search`,
  `memory_add`, `memory_list`, `memory_forget`, `memory_projects`, `memory_aufraeumen`.
  Nur von Claude Code aus aufrufbar – die KI im Chat erreicht sie ausschließlich über einen
  `#CODE#`-Auftrag.
- CWB selbst liest die Datenbank direkt per SQLite (`HubLeser`), nur Einträge des offenen
  Projekts und `global`.

### Code-Index (`index/`)
- Lokale semantische Suche, Modell `all-MiniLM-L6-v2`, ChromaDB unter
  `%LOCALAPPDATA%\CWB\index\chroma_db`, eine Sammlung je Projektpfad. Dateiendungen u. a.
  `.py .js .ts .html .css .qss .json .yaml .txt .bat .ps1 .java .kt .cpp .cs .go .rs`;
  Chunks 800 Zeichen, Überlappung 100; Dateien > 2 MB übersprungen; Markdown ist nicht
  dabei.
- Bei jeder Verbindung startet CWB `index\cli.py <Projektpfad>` im Hintergrund
  (Änderungserkennung über Manifest; unbekanntes Projekt → Vollindex, kann Minuten dauern).
- MCP-Server `code-index` mit Werkzeug `code_suchen(frage, projektpfad?, anzahl=5)`;
  erkennt das Projekt am eigenen Arbeitsverzeichnis (= `cwd` der Sitzung). Die globale
  `~/.claude/CLAUDE.md` verlangt, bei Codesuchen zuerst `code_suchen` zu nutzen.

### Aktivitätsanzeige (`Aktivitaetsbalken`, `core/kopfzeile.py`)
- Balken oben: Farbe je Zustand (bereit, denkt, liest, sucht, schreibt, führt aus, netz,
  wartet, fertig, abgebrochen, fehler – Farben in `stil.qss`), wandernder Streifen während
  der Arbeit, Text „liest — datei.py“, rechts die verstrichenen Sekunden. Jeder
  Zustandswechsel gibt einen Ton (Gruppen Arbeit/Warnung/Abschluss). Werkzeugaufrufe
  erscheinen als Zeilen im Ausgabefeld („liest fenster.py“), werden nicht gesprochen.
- Kopfzeile: Statusmeldung, Warteschlangenzahl, Sicherheitshinweis („⚠ Internet · Löschen
  · Installieren“, solange Ausnahmen an sind), Zahl der Freigaben, Tokenzähler,
  Kopieren-Knopf. Die Kachelreihe unter dem Balken trägt die häufigsten Befehle; die
  Zugriffskachel zeigt „Lesen und Schreiben“ oder „Nur lesen“.

### Tokenzähler (`Sitzung._verbrauch_erfassen`, `grundlagen.py`)
- Aus der `ResultMessage`: Eingabe, Cache gelesen, Cache erstellt, Ausgabe. Angezeigt
  wird „Auftrag“ (Eingabe + Ausgabe **ohne** Cache), „Sitzung“ (Summe seit Verbindung) und
  „Heute“ (Kalendertag, über alle Projekte und Neustarts, in `einstellungen.json` →
  `tokenverbrauch`, 30 Tage aufbewahrt). Nur angezeigt, nicht gesprochen; F2 nennt den
  Sitzungsstand. Der Bericht listet alle Werte einschließlich Cache.

### Bildanhänge
- Strg+B: Dateidialog (png, jpg, jpeg, webp, gif, bmp). Strg+V im Fenster mit Bild in der
  Zwischenablage: Bild wird unter `<CWB-Ordner>\.ablage\ablage_N.png` gespeichert und
  angehängt. Beim Abschicken werden angehängte Bilder nach `<Projekt>\.cwb\bilder\` kopiert
  (Zeitstempel im Namen) und als Base64-Bildblock vor dem Text an Claude Code gesendet.
  Die SDK-Puffergröße ist dafür auf 32 MB angehoben.

### Zwischenablage-Wächter und Zielfenster
- Wächter siehe 3. Zielfenster (`core/zielfenster.py`): ein Hintergrundthread merkt sich
  alle 0,5 s das zuletzt aktive fremde Fenster (nicht CWB, nicht Desktop/Taskleiste/UAC).
  Bei #RUN#/#ADMIN# wird das Ergebnis dort per Strg+V eingefügt (mit Fokusfreigabe,
  mehreren Versuchen und Rücklese-Prüfung der Zwischenablage). Eingefügt wird nur, wenn
  das Ziel im Moment des Strg+V wirklich vorn ist.

### Sonstiges
- Einstellungen (F12): Sprache (Weg, Stimme, Tempo, Stufe), Töne, Verhalten (siehe
  Schalter oben, außerdem `mauszeiger_ansage`), Kacheln, Pfade, Projekte
  (Zusatzprojekte), Freigaben, Skills (nur Anzeige aus Skill-Ordner und
  `<Projekt>\.claude\skills`), Modellwahl. Änderungen wirken sofort und landen in
  `einstellungen.json`.
- Zusatzprojekte: Sind welche eingetragen, zeigt die Projektwahl **nur** diese, der
  Projektordner wird nicht durchsucht (`projekte_finden`). Derzeit: CWB, hausgemacht,
  assistenz.
- Fenstergeometrie wird gemerkt (`fenster`), Stilblatt skaliert mit der Fenstergröße.

---

## 5. Was es nicht (mehr) gibt

Damit eine KI nicht in alte Muster zurückfällt – nichts davon existiert im CWB-Code:

- **Kein Deploy-System.** Es gibt keinen Deploy-Ordner, keinen Deploy-Befehl, keine
  Deploy-Anleitung. Claude Code schreibt Dateien direkt auf die Platte im Projektordner.
- **Kein CTB, kein ATB.** Diese Vorgänger-Werkzeuge kommen im Code nur noch in zwei
  Kommentaren als Vergleich vor (`grundlagen.py`, `kopfzeile.py`). Ihre Befehlsformate
  gelten nicht.
- **Keine FILE/END-Marker.** CWB wertet keine `FILE:`- oder `END`-Zeilen aus; Dateiinhalte
  werden nicht über den Chat transportiert. Die Zeilen `' FILE: CWB starten.vbs` und
  `/* FILE: CWB/stil.qss */` sind reine Kommentare ohne Funktion.
- **Keine Dateidownloads / kein Datei-Upload-Format.** Die KI im Chat liefert keine
  Dateien, die CWB einspielt. Einzige Richtung vom Chat zu CWB: ein Textblock mit
  Markierung über die Zwischenablage. Einzige Richtungen von CWB zum Chat: der Bericht
  (ZIP/Text in der Zwischenablage, von Robert eingefügt), die #RUN#/#ADMIN#-Ausgabe
  (automatisch per Strg+V) und der Screenshot (#BILD#, Dateiverweis).
- **Keine Kachel „Aus Zwischenablage“** mehr; der Wächter holt markierte Aufträge selbst,
  F7 bleibt als Notweg.
- **Keine Auftrags-Schärfung** in der Oberfläche (Funktion vorhanden, nicht angebunden).

---

## 6. Regeln für die KI im Chat

Diese Regeln folgen aus dem Ablauf: Robert kopiert einen Block, der Wächter greift ihn
alle 2 s ab und leert die Zwischenablage; der Block wird **ohne jede Nachbearbeitung**
als Auftrag (#CODE#) an Claude Code geschickt oder als PowerShell-Skript (#RUN#/#ADMIN#)
ausgeführt.

1. **Ein Befehl pro Block.** Jeder Block beginnt in seiner ersten Zeile allein mit der
   Markierung (`#CODE#`, `#RUN#`, `#ADMIN#` oder `#BILD#`), darunter der Inhalt. Zwei
   Markierungen in einem Block sind nicht vorgesehen; die zweite würde als Text
   mitgeschickt bzw. als PowerShell-Zeile ausgeführt.
2. **Nur der letzte Block einer Antwort wird ausgeführt.** Das ist Roberts Arbeitsweise
   (er kopiert einen Block); CWB kennt keine Blockreihenfolge. Also: pro Antwort genau
   ein ausführbarer Block, und zwar am Ende.
3. **Jede Korrektur ist ein vollständiger neuer Block**, nie ein Nachtrag („ergänze
   noch …“) – der vorige Block ist längst ausgeführt, die Zwischenablage geleert; ein
   Nachtrag ohne Kontext ergibt für Claude Code keinen Sinn.
4. **Keine Erklärungen innerhalb eines Blocks.** Bei #CODE# würden sie als Teil des
   Auftrags gelesen, bei #RUN#/#ADMIN# als PowerShell ausgeführt und scheitern.
   Erklärungen stehen vor dem Block, kurz, weil sie vorgelesen werden.
5. **Markierung exakt:** allein in Zeile 1, nichts dahinter, kein Zaun als erste Zeile
   (siehe 3, „Fallstrick Code-Zaun“ – ungeklärt, wie Robert kopiert; sicherste Form ist
   ein Block, dessen erste Zeile die Markierung ist).
6. **Bei #CODE# das Projekt nennen** (erste Inhaltszeile z. B. `Projekt: CWB`). Das
   schaltet die Namensregel der Projektzuordnung ab und sagt Claude Code, worum es geht.
   Namen anderer Projekte (CWB, hausgemacht, assistenz) und Dateinamen aus anderen
   Projekten im Auftragstext vermeiden, sonst wird der Auftrag vorgemerkt statt ausgeführt.
7. **Keine Wiederholung** desselben Auftragstexts innerhalb von 10 Minuten ohne Änderung
   (Dublettenrückfrage) – nur wenn F12 → „Doppelte Aufträge nachfragen“ an ist, derzeit
   **aus**. Ist der Schalter an und muss derselbe Auftrag noch einmal laufen, den Text
   leicht ändern oder Robert bitten, die Rückfrage mit Eingabe zu bestätigen.
8. **Nichts Vertrauliches in die ersten 120 Zeichen** eines #CODE#-Auftrags – sie werden
   Commit-Nachricht und ggf. gepusht.
9. **#RUN# ist PowerShell**, Arbeitsverzeichnis Projektordner, 120 s Limit, keine
   Interaktion möglich (`-NonInteractive`). Relative Pfade beziehen sich auf das offene
   Projekt. Lange Läufe (Installationen, Indexläufe) eher als #CODE# oder mit eigenem
   Zeitverhalten planen.
10. **Ergebnisse abwarten:** Nach #CODE# kommt der Bericht als eingefügte ZIP/Text-Anlage;
    nach #RUN#/#ADMIN# erscheint die Ausgabe automatisch als Text im Chat-Eingabefeld
    (Robert schickt sie ab). Erst dann den nächsten Block liefern.
11. **Antworten kurz halten** – Robert hört alles. Der Block selbst darf lang sein, der Text
    davor nicht.

Beispielform (ohne Zaunzeilen als Teil des kopierten Textes):

```
#CODE#
Projekt: CWB
Lies core/fenster.py und …
```

```
#RUN#
python -m pytest tests -q
```

---

## 7. Sitzungsbeginn

Was der Code beim Start einer Sitzung **von selbst** tut – dafür braucht die KI im Chat
keinen Befehl:

- Claude Code lädt die globale `~/.claude/CLAUDE.md` und die `CLAUDE.md` des Projekts
  (`setting_sources=["user","project"]`). Die globale Datei verlangt von Claude Code, vor
  der ersten inhaltlichen Antwort `memory_search` mit Stichworten aus der Aufgabe
  aufzurufen, Codestellen zuerst mit `code_suchen` zu suchen und Erkenntnisse sofort per
  `memory_add` zu sichern.
- CWB stellt dem **ersten** Auftrag der Sitzung den Kontextblock voran (offene Punkte,
  Tagebuch, Hub-Einträge des Projekts + global, ≤ 12.000 Zeichen). Bei jedem weiteren
  Auftrag derselben Sitzung nicht mehr; eine neue Sitzung entsteht bei Projektwechsel,
  Modellwechsel, Neustart oder nach einem Verbindungsabbruch.
- Der Code-Index des Projekts wird beim Verbinden im Hintergrund aktualisiert.

Was die KI im Chat **selbst** tun kann, wenn sie mehr Kontext will (Empfehlung, keine
Vorgabe des Codes):

```
#CODE#
Projekt: <Name>
Rufe memory_search zum Projekt <Name> mit den Stichworten <…> auf und memory_list für
das Projekt. Fasse in höchstens fünf Sätzen zusammen, was für den heutigen Auftrag
<Kurzbeschreibung> zu beachten ist. Ändere keine Datei.
```

Die Antwort kommt als Bericht (ZIP/Text) zurück. Welche Befehle Robert bisher am
Chatanfang absetzt, ist aus dem Code nicht ablesbar – **ungeklärt**; der Code verlangt
keinen bestimmten Startbefehl.
