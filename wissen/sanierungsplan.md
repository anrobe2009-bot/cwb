# Sanierungsplan CWB

Neu aufgestellt am 06.09.2026 aus `wissen/tagebuch.md`, `wissen/offen.md` und
dem tatsächlichen Code. Die Gruppen sind neu nummeriert und entsprechen **nicht**
der früheren, verlorengegangenen Einteilung.

Jeder Punkt trägt seinen Stand, die betroffenen Stellen und einen Prüfschritt.

---

## Gruppe 1 — Log und Diagnose

1. **[erledigt] Log rotiert statt unbegrenzt zu wachsen.**
   `log_einrichten()` in `core/pfade.py` (RotatingFileHandler, 500 KB,
   3 Sicherungen); aufgerufen von `pfade`, `grundlagen`, `sicherheit`,
   `zeigeransage`, `tastenleiste`, `einstellungen`, `ablagewaechter`.
   *Test:* `python -c "import pfade; import logging; print(logging.getLogger().handlers)"`
   nennt genau einen `RotatingFileHandler`; nach Überschreiten der 500 KB
   existiert `cwb_fehler.log.1`.

2. **[erledigt] Wächter schreibt keine Zeile je Prüflauf mehr.**
   `Zwischenablagewaechter._nachsehen` in `core/ablagewaechter.py`, Merkfeld
   `_letzte_entscheidung`.
   *Test:* CWB mit markiertem Text in der Ablage zwei Minuten laufen lassen —
   im Log steht genau eine Prüflauf-Zeile, nicht sechzig.

3. **[offen] Rotation im laufenden Betrieb nicht beobachtet.**
   Bisher nur Handler-Kurztest; `cwb_fehler.log` liegt bei rund 460 KB und hat
   die Grenze noch nicht erreicht.
   *Test:* Nach dem nächsten längeren Lauf prüfen, ob `cwb_fehler.log.1`
   entsteht und die Hauptdatei wieder klein anfängt.

---

## Gruppe 2 — Kopfzeile und Platzbedarf

1. **[erledigt] Wort „Ausgabe" entfernt.**
   `Ausgabekopf.__init__` und `masse_festlegen` in `core/kopfzeile.py`,
   Regel `#ausgabetitel` in `stil.qss` gelöscht.
   *Test:* Fenster öffnen — die Zeile beginnt links mit der Tätigkeitsplakette.

2. **[erledigt/gegenstandslos] Umbenennung `#dateianzeige` → `#taetigkeitsanzeige`.**
   Entfällt: Tätigkeit und Datei sind heute zwei getrennte Felder
   (`taetigkeitsplakette`, `dateianzeige` in `core/kopfzeile.py`), die alte
   gemeinsame Anzeige existiert nicht mehr.
   *Test:* `grep taetigkeitsanzeige` liefert nichts, `#dateianzeige` bleibt gültig.

3. **[offen] Kopfzeile kürzt schon bei 1200 Pixel.**
   `Schrumpffeld` / `Schrumpfwahl` und `masse_festlegen` in `core/kopfzeile.py`.
   Ob die Zeile inhaltlich schlanker werden soll (weniger Felder statt Kürzung),
   ist nicht entschieden.
   *Test:* Fenster auf 1200 Pixel ziehen und ablesen, welche Felder Punkte zeigen.

4. **[offen] Breite der Zugriffsplakette nur offscreen gemessen.**
   `zugriffsplakette` in `core/kopfzeile.py`, Farben in `stil.qss`.
   *Test:* Im laufenden Fenster F10 umschalten und die Zeile ansehen.

---

## Gruppe 3 — Nur-Lesen-Modus

1. **[erledigt] Inkonsistenz nach den abgelehnten Änderungen behoben.**
   `_absenden` in `core/fenster.py` setzt `_taetigkeit_zeigen("beginnt")`;
   `_datei_zeigen` existiert nicht mehr, der Absturz beim Absenden ist weg.
   *Test:* Auftrag abschicken — die Plakette zeigt „beginnt", keine Ausnahme im Log.

2. **[offen] `test.txt` mit Inhalt „Hallo" anlegen.**
   Alter Prüfauftrag aus der Zeit des aktiven Nur-Lesen-Modus; die Datei fehlt
   weiterhin im Projektordner.
   *Test:* Bei ausgeschaltetem Nur-Lesen-Modus anlegen lassen und `Test-Path test.txt`.

---

## Gruppe 4 — Zwischenablage-Wächter

1. **[erledigt] Sperrzeit ersatzlos entfernt.**
   `core/ablagewaechter.py`: `_zuletzt`, `_letzter_inhalt`, `auftrag_dazwischen()`.
   Derselbe Text läuft nur erneut, wenn die Ablage zwischendurch anderes enthielt.
   *Test:* Markierten Text liegen lassen — er startet nicht von allein erneut.

2. **[erledigt/gegenstandslos] Zeitstempel für den gemerkten Prüfwert.**
   Ohne Sperrzeit gibt es nichts mehr ablaufen zu lassen; gespeichert wird nur
   `ablage_zuletzt` in `einstellungen.json`
   (`ablage_pruefwert_lesen`/`_merken` in `core/grundlagen.py`).
   *Test:* Neustart mit unveränderter Ablage — der Auftrag läuft nicht erneut.

3. **[offen] Kein Lauf mit echter Zwischenablage.**
   Bisher nur `py_compile`.
   *Test:* Text mit `#code#` in der ersten Zeile kopieren und beobachten, ob der
   Auftrag genau einmal startet.

---

## Gruppe 5 — Sprachausgabe und Töne

1. **[erledigt] Drei Sprachstufen.**
   `core/sprache.py` (`STUFEN`, Art je Sprechstelle), Auswahl im Reiter Sprache
   in `core/einstellungen.py`, gespeichert unter `sprache.stufe`.
   *Test:* Stufe 1 wählen — Berührtes schweigt, Meldungen kommen.

2. **[erledigt] Arbeitstöne nur beim Zustandswechsel.**
   `Sprecher.ton` mit `_letzter_arbeitston` in `core/sprache.py`;
   alle drei Tongruppen stehen ab Werk auf an.
   *Test:* Langen Auftrag laufen lassen — je Zustand ein Ton, keine Wiederholung.

3. **[offen] Vorlesetasten in Stufe 1.**
   F1, F2, F3, F5, Probehören und Ersteinrichtung sprechen derzeit in jeder
   Stufe; ob sie in Stufe 1 schweigen sollen, ist nicht entschieden.
   *Test:* Stufe 1 wählen und F1 drücken — Erwartung festlegen.

4. **[offen] Stufen nur offscreen geprüft.**
   *Test:* Im laufenden Fenster alle drei Stufen durchschalten und je einen
   Auftrag hören.

---

## Gruppe 6 — Projektzuordnung

1. **[erledigt] Fremdes Projekt wird erkannt.**
   `core/zuordnung.py`; `_absenden` bricht mit Ansage ab,
   `_vorgemerkten_holen` startet den Auftrag im richtigen Projekt
   (beide `core/fenster.py`).
   *Test:* Auftrag „In core/fenster.py …" aus einem fremden Projekt absetzen.

2. **[offen] Kein Test mit echtem Projektwechsel.**
   Bisher `py_compile` und ein Kurztest der Erkennung.
   *Test:* Vormerkung auslösen, mit F9 das genannte Projekt öffnen und prüfen,
   ob der Auftrag von allein anläuft.

---

## Gruppe 7 — Sicherheit und Ordnergrenze

1. **[erledigt] Meldungen nennen Pfad und Befehl.**
   `Urteil.ansage()` und `Ordnergrenze.pruefe` in `core/sicherheit.py`,
   `_ablehnen` und `_frage` in `core/sitzung.py`.
   *Test:* Zugriff außerhalb des Projekts anfordern — die Ansage nennt das Ziel.

2. **[erledigt] Freigegebene Sonderpfade.**
   `ARBEITSORDNER_CLAUDE` mit `_ist_arbeitsordner` und `SKILL_ORDNER` mit
   `_ist_skillordner` in `core/sicherheit.py`; Geheimnisprüfung greift dort weiter.
   *Test:* Schreiben in `~/.claude/skills` gelingt, in `~/.claude` nicht.

3. **[offen] Nur Kurztests der Pfadprüfung.**
   Kein Lauf mit echter Sitzung.
   *Test:* Im laufenden Fenster je einen erlaubten und einen gesperrten Zugriff
   auslösen.

---

## Gruppe 8 — Git und Veröffentlichung

1. **[erledigt] Frisches Repository, saubere Ignorierliste.**
   `einstellungen.json`, `wissen/`, `*.log`, `.stimmen/`, `.toene/`, `.cwb/`
   und `.git_alt/` stehen in `.gitignore` und sind nicht mehr versioniert;
   `core/zuordnung.py` ist inzwischen eingetragen.
   *Test:* `git ls-files` enthält keine dieser Dateien, `git status` ist sauber.

2. **[offen] 12 Sicherungspunkte liegen unveröffentlicht.**
   Lokaler Branch `main` ist `origin/main`
   (https://github.com/anrobe2009-bot/cwb) um 12 Commits voraus.
   *Test:* `git rev-list --count origin/main..main` ergibt 0 nach dem Hochladen.

3. **[offen] Commit-Autor.**
   Alle Commits laufen auf `anrobe2009-bot`; ob dort „Robert" stehen soll,
   ist nicht entschieden.
   *Test:* `git log -1 --format='%an'` gegen die gewünschte Angabe halten.

4. **[offen] `.git_alt` liegt weiter auf der Platte.**
   Die alte Historie samt Sprachaufnahmen und Auftragsprotokollen ist nur dort
   noch erreichbar.
   *Test:* Entscheiden, ob sie gebraucht wird; sonst löschen.

---

## Gruppe 9 — Nachweis im laufenden Fenster

Sammelpunkt für alles, was bisher nur offscreen, per `py_compile` oder per
Kurztest belegt ist. Betroffen sind Modellwechsel (`core/modelle.py`,
`Sitzung.modell_wechseln`), Tokenzähler (`core/grundlagen.py`,
`core/kopfzeile.py`), Ersteinrichtung (`core/ersteinrichtung.py`),
Mauszeiger-Ansage (`core/zeigeransage.py`) und die Kachelreihe
(`core/tastenleiste.py`).

1. **[erledigt] Kachel „Aus Zwischenablage" entfernt, F7 bleibt.**
   `_kachel_eintraege` und `_kuerzel_merken` in `core/fenster.py`.
   *Test:* F1 liest F7 vor, die Reihe zeigt die Kachel nicht mehr.

2. **[offen] Ein durchgehender Probelauf fehlt.**
   *Test:* CWB mit F4 starten, einen echten Auftrag geben und dabei prüfen:
   Modellwechsel, die drei Zähler, Mauszeiger-Ansage, Kachelreihe bei halber
   Bildschirmbreite, keine Fehlerzeile in `cwb_fehler.log`.

3. **[offen] Ablage des Skills `oberflaeche`.**
   Liegt unter `.claude/skills/oberflaeche/SKILL.md` im Projekt und ist damit
   veröffentlicht; ob das so bleiben soll oder er in den Benutzerordner gehört,
   ist nicht entschieden.
   *Test:* Zielort festlegen und die Datei dort führen.
