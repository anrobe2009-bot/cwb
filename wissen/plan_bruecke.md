# Vorhaben "Brücke"

Die KI im Chat (claude.ai im Browser) soll Aufträge selbst an CWB schicken
und Berichte selbst abholen können, ohne dass Robert Blöcke von Hand
kopiert. Anlass: Robert hat mehrfach Blöcke übersehen; die Zwischenablage
hat außerdem nachts in gesperrter Sitzung versagt (Zeitschaltung 01:15 Uhr
endete mit Fehler 1, CWB erhielt nichts). Robert nutzt Claude im Browser,
daher kommen keine lokalen MCP-Server infrage - der Weg führt über einen
Remote-MCP-Connector auf Roberts eigenem Server.

## Grundsätze

- Der Server führt nie etwas aus, er speichert nur Aufträge und Berichte.
- Der PC öffnet keinen Port nach außen; CWB fragt ausgehend per HTTPS ab.
- Erlaubt über die Brücke: #CODE#, #RUN#, #BILD#. #ADMIN# ist über die
  Brücke immer gesperrt.
- Sperrliste, Nur-Lesen, verbotene Befehle und F8 Not-Aus gelten
  unverändert. Neuer Schalter "Brücke an/aus" (F12 und Sprachbefehl),
  Vorgabe aus, bis Robert ihn einschaltet.
- Jeder Brücken-Auftrag wird angesagt: "Block N von Claude erhalten."
  Blocknummern-Prüfung aus Block 56 (core/bloecke.py) gilt auch hier.
- Alles wird auf Server und PC protokolliert.

## Stufen

- **B1** Eingangsordner in CWB. *(umgesetzt, siehe unten)*
- **B2** Server-Dienst: kleiner MCP-Server (Python, streamable HTTP) mit den
  Werkzeugen `auftrag_senden(projekt, art, text)`, `bericht_holen(id oder
  neuester)`, `status()`. Warteschlange in SQLite. Absicherung zunächst über
  einen geheimen Pfad in der Connector-Adresse plus ein eigenes PC-Token für
  den Abruf durch CWB; HTTPS über den vorhandenen nginx; Ratenbegrenzung.
  Wo und wie Roberts Server betrieben wird (eigener Rechner, Docker, VPS),
  ermittelt Claude Code zuerst im Projekt max-friends.
- **B3** CWB-Abruf: CWB fragt alle 5 Sekunden ausgehend ab, legt neue
  Aufträge in den Eingangsordner, lädt nach Abschluss den Bericht-Text
  hoch. Abbruch bei Netzfehlern still, Ansage nur bei dauerhaftem Ausfall.
- **B4** Robert bindet die Adresse in claude.ai als eigenen Connector ein;
  Test mit einem harmlosen #RUN#.
- **B5** später: OAuth statt geheimem Pfad.

## Stand B1 (umgesetzt)

Eingangsordner `%LOCALAPPDATA%\CWB\eingang\` (core/pfade.py,
`EINGANG_ORDNER`). CWB überwacht ihn pro offenem Fenster
(core/eingangsordner.py, `Eingangswaechter`): Dateisystem-Ereignis sofort,
zusätzlich ein Blick alle zwei Sekunden als Rückfall.

Jede Datei `*.json` trägt die Felder `quelle` (z. B. `"zeitschaltung"`,
`"bruecke"`, `"lokal"`), `projekt` (optional) und `text` (der vollständige
Block samt Markierung). Verarbeitet wird sie genau wie ein Block aus der
Zwischenablage: gleiche Markierungserkennung (`fenster.markierung_erkennen`),
gleiche Blocknummern-Prüfung, gleiche Dublettensperre
(`_dublette_abgewiesen`). Danach wandert die Datei nach `eingang\erledigt\`
bzw. `eingang\abgelehnt\` (mit Grund in einer gleichnamigen `.txt`-Datei).

`#ADMIN#` wird abgelehnt, außer `quelle` ist `"lokal"` - das prüft
`core.eingangsordner.admin_gesperrt()`, bevor der Auftrag überhaupt an das
Fenster weitergereicht wird.

Ein Auftrag mit gesetztem Feld `projekt` wird nur von dem Fenster
beansprucht, dessen offenes Projekt dazu passt (`passend_fuer_projekt()`);
ohne dieses Feld darf ihn jedes offene Fenster holen - wie bei der
Zwischenablage gibt es keine Weiterleitung zwischen Fenstern verschiedener
Projekte, nur die Zuordnung zum richtigen bereits offenen Fenster.

Funktioniert auch bei gesperrter Sitzung, weil keine Zwischenablage
beteiligt ist. Das Hilfsskript `werkzeuge\in_eingang.ps1` legt für
Zeitschaltungen den Inhalt einer Textdatei als Auftrag ab.

Bewusst noch nicht Teil von B1: der Schalter "Brücke an/aus" (gehört zu
B2/B3, weil erst dort eine echte Brücke zu claude.ai existiert) und die
Ansage "Block N von Claude erhalten" (nennt die Quelle "Claude" - das stimmt
erst, sobald `quelle == "bruecke"` tatsächlich vorkommt).
