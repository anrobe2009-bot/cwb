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
"""

import logging
import os
import shutil
import sqlite3
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

def _zeilen_zaehlen(datenbank: Path) -> int | None:
    """Anzahl der Eintraege in `memories`, `None` wenn nicht lesbar."""
    # `with` auf einer Verbindung schliesst sie nicht, es beendet nur die
    # Transaktion - offen gebliebene Verbindungen wuerden das Umbenennen der
    # alten Datei unter Windows verhindern. Deshalb ausdruecklich schliessen.
    verbindung = None
    try:
        verbindung = sqlite3.connect(f"file:{datenbank}?mode=ro", uri=True)
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
        verbindung = sqlite3.connect(f"file:{datenbank}?mode=ro", uri=True)
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


if __name__ == "__main__":
    print("Datenordner  :", datenordner())
    print("Memory Hub   :", hub_datenbank(), "(vorhanden)" if hub_datenbank().is_file() else "(fehlt)")
    print("Code-Index   :", index_datenordner(), "(vorhanden)" if index_datenordner().is_dir() else "(fehlt)")
