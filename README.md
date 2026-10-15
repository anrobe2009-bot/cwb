# CWB — Code Workbench

Eine barrierefreie Desktop-Oberfläche für Claude Code, gebaut für die Bedienung
per Tastatur und Sprache. Jede Funktion ist über eine F-Taste **und** über eine
Schaltfläche erreichbar. CWB spricht selbst, auch ohne laufenden Screenreader,
und sagt nur, was man wissen muss: was gerade passiert, was fertig ist, was
schiefging.

Dazu kommt ein Sicherheitsnetz: vor jedem Auftrag legt CWB einen
Git-Sicherungspunkt an, alle Zugriffe bleiben im Projektordner, Geheimnisdateien
(`.env`, Schlüssel, Zugangsdaten) sind gesperrt, und kritische Befehle werden
vorher vorgelesen und abgefragt.

## Was CWB ist

CWB ist eine eigenständige Oberfläche für Claude Code. Claude Code selbst läuft
im Terminal — und ein Terminal ist für jemanden, der mit einem Screenreader
arbeitet, mühsam: Ausgaben scrollen weg, Fortschrittsanzeigen rattern
endlos, und man erfährt nicht verlässlich, ob gerade etwas passiert oder
nichts mehr kommt. CWB legt ein ruhiges Fenster darüber.

Es geht dabei nicht um Vorlesen von allem, sondern um Auswahl. CWB sagt
knapp an, was gerade läuft, was fertig ist und was schiefging — den Rest
holt man sich mit einer Taste, wenn man ihn braucht. Jede Funktion ist
doppelt erreichbar: über eine F-Taste und über eine sichtbare Kachel.
Das Fenster ist also mit einer Hand am Tastenbrett genauso bedienbar wie
mit der Maus.

Dazu ein Sicherheitsnetz, weil man nicht überblicken kann, was ein Modell
im Hintergrund anstellt: Vor jedem Auftrag entsteht ein Git-Sicherungspunkt,
der sich mit **Strg + Z** zurückrollen lässt. Alle Zugriffe bleiben im
Projektordner. Geheimnisdateien sind gesperrt. Kritische Befehle werden
vorgelesen und einzeln abgefragt. Mit **F10** lässt sich ein Nur-Lesen-Modus
einschalten, in dem gar nichts geschrieben wird.

## Für wen

- **Blinde und sehbehinderte Entwicklerinnen und Entwickler**, die mit
  Claude Code arbeiten wollen, ohne sich durch Terminalausgaben zu kämpfen.
  Das ist der Anlass für CWB und der Maßstab für jede Entscheidung darin.
- **Wer per Sprache arbeitet** — diktieren, abschicken, zuhören, ohne
  zwischendurch auf den Bildschirm zu schauen.
- **Wer schlicht ein ruhiges Fenster bevorzugt** und den Wert eines
  Sicherungspunkts vor jedem Auftrag kennt. Barrierefreiheit hat Vorrang,
  aber die Oberfläche ist auch für sehende Nutzer gebaut.

Vorausgesetzt wird eine eigene, angemeldete Claude-Code-Installation —
CWB bringt keinen Zugang mit und speichert keine Zugangsdaten.

## Voraussetzungen

- **Windows 10 oder 11.** Töne laufen über `winsound`, die Bordstimme über SAPI.
  Auf anderen Systemen startet CWB, bleibt aber ohne Töne und ohne SAPI-Stimme.
- **Python 3.10 oder neuer** (getestet mit 3.12/3.13).
- **Claude Code**, angemeldet und lauffähig — CWB spricht über das
  Claude Agent SDK mit derselben Installation.
- **Git**, damit die Sicherungspunkte angelegt werden können. Ohne Git läuft
  CWB weiter, dann aber ohne Sicherungsnetz.
- **Internet** für die natürliche Edge-Stimme. Ohne Internet fällt die
  Sprachausgabe auf die Windows-Bordstimme zurück.

## Installation

```
git clone <adresse> CWB
cd CWB
pip install -r requirements.txt
```

Gestartet wird mit einem Doppelklick auf **`CWB starten.vbs`** — das sucht sich
`pythonw` selbst und startet ohne störendes Konsolenfenster. Alternativ:

```
python core/fenster.py
```

### Beim ersten Start

CWB fragt einmalig nach drei Pfaden und merkt sie in `einstellungen.json`:

| Angabe | Bedeutung | Vorschlag |
| --- | --- | --- |
| **Projektordner** | Der Ordner, in dem die Projekte nebeneinander liegen. Jeder Unterordner wird ein Eintrag in der Projektwahl. | der Ordner **über** dem CWB-Ordner |
| **Skill-Ordner** | Enthält je Skill einen Unterordner mit `SKILL.md`. Nur zur Anzeige. | `.claude/skills` im Benutzerordner |
| **Memory Hub** | Datei `memory.db` des projektübergreifenden Gedächtnisses. | leer — der Hub darf ganz fehlen |

Stimmt der Vorschlag, genügt die Eingabetaste. Nur der Projektordner muss
stimmen; die beiden anderen dürfen leer bleiben, ohne dass etwas bricht.
Später ändern lässt sich alles unter **F12 → Reiter „Pfade"**.

## Tastenkürzel

Alles ist auch über die Kachelreihe unter dem Aktivitätsbalken erreichbar.
**F1** liest die ganze Liste im laufenden Fenster vor.

| Taste | Wirkung |
| --- | --- |
| **Strg + Eingabe** | Auftrag abschicken |
| **F7** | Text aus der Zwischenablage holen und abschicken |
| **F8** | Not-Aus: laufenden Auftrag abbrechen |
| **Escape** | laufende Ansage abbrechen |
| **F1** | Hilfe vorlesen |
| **F2** | Wo stehen wir — Zustand, Projekt, Verbrauch |
| **F3** | letzte Antwort vorlesen |
| **Strg + L** | markierten Text vorlesen |
| **Strg + K** | Ausgabe in die Zwischenablage kopieren |
| **Strg + Z** | letzten Auftrag zurücknehmen (Git-Sicherungspunkt) |
| **Strg + B** | Bild anhängen |
| **Strg + 0** | Schriftgröße zurücksetzen |
| **F5** | zum Eingabefeld springen |
| **F6** | zum Verlauf springen |
| **F9** | Projekt wechseln |
| **F10** | Nur-Lesen-Modus ein- und ausschalten |
| **F4** | kompletter Neustart |
| **F12** | Einstellungen |

In den Einstellungen (F12) wechselt **Strg + Tabulator** den Reiter,
**Tabulator** das Element, **Leertaste** schaltet um, **Escape** schließt.

### Markierung im Eingabefeld

Steht in der ersten Zeile allein `#CODE#`, gilt alles darunter als Auftrag und
die Markierungszeile selbst wird nicht mitgeschickt.

## Aufbau

Alle Bausteine liegen in `core/`, Einstiegspunkt ist `fenster.main()`. Das
Aussehen steht vollständig in `stil.qss` und `verlauf.css`, im Python steht
keine Gestaltung.

| Datei | Aufgabe |
| --- | --- |
| `fenster.py` | Hauptfenster, Aktivitätsbalken, Programmstart |
| `pfade.py` | die einstellbaren Pfade und `einstellungen.json` |
| `grundlagen.py` | Log, Stilblatt-Skalierung, Fensterliste, Tageszähler |
| `ersteinrichtung.py` | die Pfadfrage beim ersten Start |
| `projektwahl.py` | Projektliste und Startansicht |
| `einstellungen.py` | die Seite hinter F12 |
| `kopfzeile.py` | Tätigkeit, Datei, Status, Zähler, Modellwahl |
| `modelle.py` | wählbare Modelle und ihre Kurzhinweise |
| `faden.py` | hält die Sitzung in einem eigenen Thread |
| `sitzung.py` | Anbindung ans Claude Agent SDK |
| `sicherheit.py` | Ordnergrenze, Git-Sicherungspunkte, Befehlsprüfung |
| `sprache.py` | Sprachausgabe (Edge, SAPI, NVDA, stumm) und Töne |
| `wissen.py` | Projektgedächtnis und Memory Hub |
| `tastenleiste.py` | die Kachelreihe |
| `ablagewaechter.py` | beobachtet die Zwischenablage |

Erzeugte Daten liegen in `.stimmen/` (gesprochene Sätze), `.toene/`, `.cwb/`
und `cwb_fehler.log`. Nichts davon muss gesichert werden.

## Wenn etwas nicht läuft

Jeder Fehler landet mit vollem Verlauf in **`cwb_fehler.log`** im CWB-Ordner —
auch Abstürze, die sonst spurlos wären, weil CWB ohne Konsole läuft. Die letzten
Zeilen dieser Datei sind bei jedem Problem die erste Anlaufstelle.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
