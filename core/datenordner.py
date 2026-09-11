"""
CWB - Code Workbench
Datenordner: wo die Laufzeitdaten liegen, die einen Programmwechsel
ueberleben muessen.

Reines Python ohne Oberflaeche und ohne Log-Einrichtung beim Laden. Das
Modul wird nicht nur von core/pfade.py gebraucht, sondern auch von den
beiden MCP-Servern (memory_hub/memory_db.py, index/indexer.py), die als
eigene Prozesse aus jeder Claude-Code-Sitzung heraus starten - auch ohne
CWB. Deshalb darf hier nichts von core/ abhaengen.

Die Daten liegen nicht mehr im Programmordner, sondern unter
%LOCALAPPDATA%\\CWB (also C:\\Users\\Name\\AppData\\Local\\CWB):

    CWB/
      memory_hub/memory.db      Gedaechtnis ueber alle Projekte
      index/chroma_db/          Vektordatenbank des Code-Index
      index/manifeste/          Datei-Stat-Manifeste des Code-Index
      index/.sperre             Schreibsperre des Code-Index

So bleibt alles erhalten, wenn CWB neu ausgepackt, aus einem anderen
Ordner gestartet oder eine aeltere Fassung durch eine neue ersetzt wird.

`daten_umziehen()` holt Bestaende aus dem alten Ablageort (Programmordner)
einmalig herueber. Jeder Aufrufer ruft es beim Laden auf; ist nichts zu
tun, kostet der Aufruf nur ein paar Dateiabfragen.

`erstuebernahme()` ist der zweite, davon getrennte Fall: eine frisch
installierte Fassung startet mit leerem Datenordner, weil Gedaechtnis und
Index beim Packen bewusst draussen bleiben. Liegt auf demselben Rechner eine
aeltere Datenhaltung - der Projektordner, aus dem heraus entwickelt wird,
oder ein frueherer Ablageort - wird sie beim allerersten Start kopiert, nie
verschoben. Ein Marker sorgt dafuer, dass das genau einmal passiert.
"""

import json
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger("cwb.datenordner")

CWB_WURZEL = Path(__file__).resolve().parent.parent
PROGRAMM_NAME = "CWB"

# Der alte Ablageort: die Werkzeug-Unterordner im Programmordner selbst.
ALT_HUB_DATENBANK = CWB_WURZEL / "memory_hub" / "memory.db"
ALT_INDEX_ORDNER = CWB_WURZEL / "index"
INDEX_UNTERORDNER = ("chroma_db", "manifeste")

# Endung, die eine erfolgreich umgezogene Datei am alten Ort bekommt. Sie
# wird nicht geloescht: wer nachsehen will, findet sie noch.
UMGEZOGEN_ENDUNG = ".umgezogen"


def datenordner() -> Path:
    """%LOCALAPPDATA%\\CWB. Fehlt die Umgebungsvariable (fremde Shell,
    Dienstkonto), wird der uebliche Ort im Benutzerordner genommen."""
    basis = os.environ.get("LOCALAPPDATA", "").strip()
    if basis:
        return Path(basis) / PROGRAMM_NAME
    return Path.home() / "AppData" / "Local" / PROGRAMM_NAME


def hub_datenbank() -> Path:
    return datenordner() / "memory_hub" / "memory.db"


def index_datenordner() -> Path:
    return datenordner() / "index"


# ---------------------------------------------------------------------------
# Einmaliger Umzug alter Bestaende
# ---------------------------------------------------------------------------

def _lese_uri(datenbank: Path) -> str:
    """Nur-Lese-Zugriff, der die Quelle wirklich unangetastet laesst. Ohne
    Write-Ahead-Log daneben darf SQLite die Datei als unveraenderlich
    behandeln und legt dann keine -wal/-shm-Begleitdateien an. Liegt ein
    WAL daneben, muss es mitgelesen werden - dort koennen die juengsten
    Eintraege stehen -, und dafuer braucht SQLite die Begleitdateien."""
    if datenbank.with_name(datenbank.name + "-wal").exists():
        return f"file:{datenbank}?mode=ro"
    return f"file:{datenbank}?mode=ro&immutable=1"


def _zeilen_zaehlen(datenbank: Path) -> int | None:
    """Anzahl der Eintraege in `memories`, `None` wenn nicht lesbar."""
    # `with` auf einer Verbindung schliesst sie nicht, es beendet nur die
    # Transaktion - offen gebliebene Verbindungen wuerden das Umbenennen der
    # alten Datei unter Windows verhindern. Deshalb ausdruecklich schliessen.
    verbindung = None
    try:
        verbindung = sqlite3.connect(_lese_uri(datenbank), uri=True)
        return verbindung.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    except sqlite3.Error as fehler:
        log.warning("Eintraege in %s nicht zaehlbar: %s", datenbank, fehler)
        return None
    finally:
        if verbindung is not None:
            verbindung.close()


def _datenbank_umziehen(alt: Path, neu: Path) -> None:
    """Kopiert die SQLite-Datei ueber die Backup-Schnittstelle: die nimmt
    auch mit, was noch im Write-Ahead-Log steht, und stoert sich nicht an
    einem Prozess, der die alte Datei gerade offen hat. Erst wenn beide
    gleich viele Eintraege haben, wird die alte Datei umbenannt."""
    if not alt.is_file():
        return
    if neu.exists():
        if _tabelle_vorhanden(alt):
            _nachtraege_uebernehmen(alt, neu)
        else:
            # Ein alter Prozess hat nach dem Umzug nur noch eine leere Huelle
            # angelegt (PRAGMA journal_mode ohne Tabellen) - nichts drin.
            log.info("Leere alte Datenbank ohne Eintraege beiseitegelegt: %s", alt)
            _alte_datenbank_markieren(alt)
        return
    neu.parent.mkdir(parents=True, exist_ok=True)
    quelle = sqlite3.connect(str(alt))
    ziel = sqlite3.connect(str(neu))
    try:
        quelle.backup(ziel)
    finally:
        ziel.close()
        quelle.close()
    vorher, nachher = _zeilen_zaehlen(alt), _zeilen_zaehlen(neu)
    if vorher != nachher:
        neu.unlink(missing_ok=True)
        raise RuntimeError(
            f"Memory Hub nach dem Kopieren unvollstaendig: alt {vorher}, neu {nachher} Eintraege"
        )
    log.info("Memory Hub umgezogen: %s -> %s (%s Eintraege)", alt, neu, nachher)
    _alte_datenbank_markieren(alt)


def _tabelle_vorhanden(datenbank: Path) -> bool:
    """Wahr, wenn die Datei eine Tabelle `memories` enthaelt."""
    verbindung = None
    try:
        verbindung = sqlite3.connect(_lese_uri(datenbank), uri=True)
        treffer = verbindung.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memories'"
        ).fetchone()
        return treffer is not None
    except sqlite3.Error:
        return False
    finally:
        if verbindung is not None:
            verbindung.close()


def _alte_datenbank_markieren(alt: Path) -> None:
    """Benennt die alte Datenbank samt ihren WAL-Begleitdateien um."""
    _als_umgezogen_markieren(alt)
    for anhang in ("-wal", "-shm"):
        _als_umgezogen_markieren(alt.with_name(alt.name + anhang))


def _nachtraege_uebernehmen(alt: Path, neu: Path) -> None:
    """Beide Datenbanken sind da: die neue ist massgeblich, aber ein noch
    laufender alter Prozess (MCP-Server einer offenen Sitzung) kann nach dem
    Umzug weiter in die alte geschrieben haben. Was dort fehlt, wird
    nachgetragen - erkannt an Projekt, Text und Anlagedatum, nicht an der
    Nummer, weil beide Dateien unabhaengig weiterzaehlen."""
    verbindung = sqlite3.connect(str(neu))
    try:
        verbindung.execute("ATTACH DATABASE ? AS alt", (str(alt),))
        zeiger = verbindung.execute(
            "INSERT INTO main.memories "
            "(project, category, content, source, pinned, created, updated) "
            "SELECT a.project, a.category, a.content, a.source, a.pinned, a.created, a.updated "
            "FROM alt.memories AS a WHERE NOT EXISTS ("
            "  SELECT 1 FROM main.memories AS m"
            "  WHERE m.project = a.project AND m.content = a.content AND m.created = a.created)"
        )
        verbindung.commit()
        nachgetragen = zeiger.rowcount
    except sqlite3.Error as fehler:
        log.warning(
            "Memory Hub liegt an beiden Orten, Abgleich nicht moeglich, beide bleiben: "
            "alt %s (%s Eintraege), neu %s (%s Eintraege): %s",
            alt, _zeilen_zaehlen(alt), neu, _zeilen_zaehlen(neu), fehler,
        )
        return
    finally:
        verbindung.close()
    if nachgetragen:
        log.info("Memory Hub: %s Eintraege aus %s nachgetragen", nachgetragen, alt)
    _alte_datenbank_markieren(alt)


def _ordner_umziehen(alt: Path, neu: Path) -> None:
    """Verschiebt einen Ordner. Auf demselben Laufwerk ist das ein Umbenennen
    und dauert keine Sekunde. Geht das nicht - anderes Laufwerk oder ein
    Prozess haelt noch eine Datei offen - wird kopiert und der alte Ordner
    bleibt liegen."""
    if not alt.is_dir():
        return
    if neu.exists():
        log.warning("Liegt schon am neuen Ort, alter Ordner bleibt: %s", alt)
        return
    neu.parent.mkdir(parents=True, exist_ok=True)
    try:
        alt.rename(neu)
        log.info("Verschoben: %s -> %s", alt, neu)
        return
    except OSError as fehler:
        log.info("Umbenennen nicht moeglich (%s), kopiere stattdessen: %s", fehler, alt)
    zwischen = neu.with_name(neu.name + ".teil")
    if zwischen.exists():
        shutil.rmtree(zwischen)
    shutil.copytree(alt, zwischen)
    zwischen.rename(neu)
    log.info("Kopiert: %s -> %s (alter Ordner bleibt liegen)", alt, neu)


def _als_umgezogen_markieren(datei: Path) -> None:
    if not datei.exists():
        return
    try:
        # replace statt rename: ein Rest vom vorigen Umzug darf ueberschrieben
        # werden, sein Inhalt ist laengst uebernommen.
        datei.replace(datei.with_name(datei.name + UMGEZOGEN_ENDUNG))
    except OSError as fehler:
        # Passiert, wenn ein alter Prozess die Datei noch offen hat. Beim
        # naechsten Start meldet _datenbank_umziehen dann beide Bestaende.
        log.warning("Alte Datei konnte nicht umbenannt werden: %s (%s)", datei, fehler)


def daten_umziehen() -> None:
    """Holt alte Bestaende aus dem Programmordner nach %LOCALAPPDATA%\\CWB.
    Mehrfacher Aufruf ist harmlos. Ein Fehler wird gemeldet, bricht aber
    den Aufrufer nicht ab - lieber laeuft CWB mit leerem Gedaechtnis, als
    gar nicht."""
    try:
        datenordner().mkdir(parents=True, exist_ok=True)
        _datenbank_umziehen(ALT_HUB_DATENBANK, hub_datenbank())
        for name in INDEX_UNTERORDNER:
            _ordner_umziehen(ALT_INDEX_ORDNER / name, index_datenordner() / name)
    except Exception as fehler:  # noqa: BLE001
        log.error("Datenumzug nach %s fehlgeschlagen: %s", datenordner(), fehler, exc_info=True)


# ---------------------------------------------------------------------------
# Einmalige Uebernahme beim ersten Start einer installierten Fassung
# ---------------------------------------------------------------------------

# Der Marker liegt im Datenordner: einmal geschrieben, wird nie wieder
# gesucht - auch dann nicht, wenn nichts gefunden wurde (fremder Empfaenger).
UEBERNAHME_MARKER_NAME = "uebernahme.json"
CLAUDE_KONFIG = Path.home() / ".claude.json"
MCP_SKRIPTE = ("memory_mcp.py", "mcp_server.py")


@dataclass
class Uebernahme:
    """Was beim ersten Start uebernommen wurde. `eintraege` ist `None`, wenn
    kein Gedaechtnis gefunden wurde."""
    quelle: str = ""
    eintraege: int | None = None
    index: bool = False
    einstellungen: bool = False
    fehler: list[str] = field(default_factory=list)

    def gefunden(self) -> bool:
        return self.eintraege is not None or self.index or self.einstellungen

    def ansage(self) -> str:
        """Ein Satz fuer die Sprachausgabe. Leer, wenn nichts uebernommen wurde."""
        teile = []
        if self.eintraege is not None:
            teile.append(f"{self.eintraege} Gedächtniseinträge")
        if self.index:
            teile.append("den Code-Index")
        if self.einstellungen:
            teile.append("die Einstellungen")
        if not teile:
            return ""
        if len(teile) == 1:
            aufzaehlung = teile[0]
        else:
            aufzaehlung = ", ".join(teile[:-1]) + " und " + teile[-1]
        return f"Vorhandene Daten übernommen: {aufzaehlung}."


def _kandidaten_aus_claude_konfig() -> list[Path]:
    """CWB-Ordner, deren MCP-Server in ~/.claude.json eingetragen sind -
    der einzige verlaessliche Hinweis darauf, wo auf diesem Rechner die
    Entwicklungsfassung liegt. Fehlt die Datei: keine Kandidaten."""
    try:
        werte = json.loads(CLAUDE_KONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    server = werte.get("mcpServers") if isinstance(werte, dict) else None
    if not isinstance(server, dict):
        return []
    ordner: list[Path] = []
    for eintrag in server.values():
        args = eintrag.get("args", []) if isinstance(eintrag, dict) else []
        for arg in args:
            if not isinstance(arg, str) or not arg.endswith(MCP_SKRIPTE):
                continue
            wurzel = Path(arg).resolve().parent.parent
            if wurzel not in ordner:
                ordner.append(wurzel)
    return ordner


def _uebernahme_kandidaten() -> list[Path]:
    """Ordner, die nach der bekannten CWB-Aufteilung durchsucht werden
    (memory_hub/, index/, einstellungen.json). Bewusst kurz: die Suche darf
    den Start nicht spuerbar verzoegern."""
    kandidaten = _kandidaten_aus_claude_konfig()
    roaming = os.environ.get("APPDATA", "").strip()
    if roaming:
        kandidaten.append(Path(roaming) / PROGRAMM_NAME)
    eigener = CWB_WURZEL.resolve()
    return [k for k in kandidaten if k.resolve() != eigener and k.is_dir()]


def _gedaechtnis_quellen(kandidat: Path) -> list[Path]:
    """Moegliche memory.db in einem Kandidaten: die Datei selbst, der Rest
    eines frueheren Umzugs und der frueher eigenstaendige Memory Hub neben
    dem CWB-Ordner."""
    hub = kandidat / "memory_hub"
    return [
        hub / "memory.db",
        hub / ("memory.db" + UMGEZOGEN_ENDUNG),
        kandidat.parent / "memory_hub" / "memory.db",
    ]


def _beste_gedaechtnis_quelle(kandidaten: list[Path]) -> tuple[Path | None, int]:
    """Die memory.db mit den meisten Eintraegen ueber alle Kandidaten."""
    beste, meiste = None, 0
    for kandidat in kandidaten:
        for datei in _gedaechtnis_quellen(kandidat):
            if not datei.is_file() or not _tabelle_vorhanden(datei):
                continue
            anzahl = _zeilen_zaehlen(datei) or 0
            if anzahl > meiste:
                beste, meiste = datei, anzahl
    return beste, meiste


def _gedaechtnis_kopieren(quelle: Path, ziel: Path) -> int:
    """Kopiert ueber die Backup-Schnittstelle (nimmt das Write-Ahead-Log
    mit, laesst die Quelle unveraendert) und prueft die Anzahl."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    von = sqlite3.connect(_lese_uri(quelle), uri=True)
    nach = sqlite3.connect(str(ziel))
    try:
        von.backup(nach)
    finally:
        nach.close()
        von.close()
    vorher, nachher = _zeilen_zaehlen(quelle), _zeilen_zaehlen(ziel)
    if vorher != nachher:
        ziel.unlink(missing_ok=True)
        raise RuntimeError(f"unvollstaendig kopiert: Quelle {vorher}, Ziel {nachher} Eintraege")
    return nachher or 0


def _index_kopieren(quelle_index: Path, ziel_index: Path) -> None:
    """chroma_db und manifeste gehoeren zusammen: ohne Manifest wuerde der
    naechste Lauf den Index fuer veraltet halten und neu bauen."""
    for name in INDEX_UNTERORDNER:
        von, nach = quelle_index / name, ziel_index / name
        if von.is_dir() and not nach.exists():
            shutil.copytree(von, nach)


def _marker_schreiben(marker: Path, ergebnis: Uebernahme) -> None:
    inhalt = {
        "zeitpunkt": datetime.now().isoformat(timespec="seconds"),
        "quelle": ergebnis.quelle,
        "eintraege": ergebnis.eintraege,
        "index": ergebnis.index,
        "einstellungen": ergebnis.einstellungen,
        "fehler": ergebnis.fehler,
    }
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(inhalt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def erstuebernahme(einstellungen_datei: Path) -> Uebernahme | None:
    """Beim allerersten Start mit leerem Datenordner: sucht an den
    naheliegenden Orten nach einer aelteren Datenhaltung und kopiert sie.

    Gibt zurueck, was uebernommen wurde - fuer die Ansage. `None` heisst:
    nicht der erste Start, Datenordner schon gefuellt, oder nichts gefunden.
    Alles davon ist kein Fehler; ein fremder Empfaenger landet immer hier.
    Ein Fehler beim Kopieren wird geloggt und bricht den Start nicht ab."""
    marker = datenordner() / UEBERNAHME_MARKER_NAME
    if marker.exists():
        return None
    ergebnis = Uebernahme()
    try:
        if hub_datenbank().is_file() or (index_datenordner() / "chroma_db").is_dir():
            # Kein leerer Erststart - z.B. laeuft auf diesem Rechner schon
            # die Entwicklungsfassung mit demselben Datenordner.
            ergebnis.quelle = "(Datenordner war schon gefuellt)"
            _marker_schreiben(marker, ergebnis)
            log.info("Erstuebernahme nicht noetig, Datenordner schon gefuellt")
            return None
        kandidaten = _uebernahme_kandidaten()
        log.info("Erstuebernahme: %s Kandidaten geprueft", len(kandidaten))

        quelle, anzahl = _beste_gedaechtnis_quelle(kandidaten)
        if quelle is not None:
            try:
                ergebnis.eintraege = _gedaechtnis_kopieren(quelle, hub_datenbank())
                ergebnis.quelle = str(quelle.parent.parent)
                log.info("Gedaechtnis uebernommen: %s (%s Eintraege)", quelle, ergebnis.eintraege)
            except (sqlite3.Error, OSError, RuntimeError) as fehler:
                ergebnis.fehler.append(f"Gedaechtnis {quelle}: {fehler}")
                log.error("Gedaechtnis nicht uebernommen aus %s: %s", quelle, fehler)

        for kandidat in kandidaten:
            if (kandidat / "index" / "chroma_db").is_dir():
                try:
                    _index_kopieren(kandidat / "index", index_datenordner())
                    ergebnis.index = True
                    ergebnis.quelle = ergebnis.quelle or str(kandidat)
                    log.info("Code-Index uebernommen aus %s", kandidat / "index")
                except OSError as fehler:
                    ergebnis.fehler.append(f"Index {kandidat}: {fehler}")
                    log.error("Code-Index nicht uebernommen aus %s: %s", kandidat, fehler)
                break

        if not einstellungen_datei.exists():
            for kandidat in kandidaten:
                datei = kandidat / einstellungen_datei.name
                if datei.is_file():
                    try:
                        shutil.copy2(datei, einstellungen_datei)
                        ergebnis.einstellungen = True
                        ergebnis.quelle = ergebnis.quelle or str(kandidat)
                        log.info("Einstellungen uebernommen aus %s", datei)
                    except OSError as fehler:
                        ergebnis.fehler.append(f"Einstellungen {datei}: {fehler}")
                        log.error("Einstellungen nicht uebernommen aus %s: %s", datei, fehler)
                    break

        _marker_schreiben(marker, ergebnis)
    except Exception as fehler:  # noqa: BLE001
        log.error("Erstuebernahme fehlgeschlagen: %s", fehler, exc_info=True)
        return None
    return ergebnis if ergebnis.gefunden() else None


if __name__ == "__main__":
    print("Datenordner  :", datenordner())
    print("Memory Hub   :", hub_datenbank(), "(vorhanden)" if hub_datenbank().is_file() else "(fehlt)")
    print("Code-Index   :", index_datenordner(), "(vorhanden)" if index_datenordner().is_dir() else "(fehlt)")
