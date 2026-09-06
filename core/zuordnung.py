"""
CWB - Code Workbench
Projektzuordnung: erkennt Auftraege, die zu einem anderen Projekt gehoeren.

Nennt ein Auftrag Dateinamen oder Pfade, die es im geoeffneten Projekt nicht
gibt, wohl aber in einem anderen, dann gehoert er vermutlich dorthin. Er wird
dann nicht ausgefuehrt, sondern vorgemerkt: wird spaeter genau dieses Projekt
geoeffnet, laeuft er dort von allein los. Wird ein anderes Projekt geoeffnet
oder ein neuer Auftrag abgeschickt, ist die Vormerkung hinfaellig.

Reines Python, keine Oberflaeche. Die Werkbank ruft nur
`fremdes_projekt_erkennen`, `auftrag_vormerken`, `vormerkung_abholen` und
`vormerkung_verwerfen`.
"""

import logging
import os
import re
import time
from pathlib import Path

try:
    from .sicherheit import Projekt, projekte_finden
except ImportError:
    from sicherheit import Projekt, projekte_finden

log = logging.getLogger("cwb.zuordnung")

# Ordner, die nie zum Dateibestand eines Projekts zaehlen.
ORDNER_UEBERGEHEN = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".stimmen", ".toene", ".ablage", ".cwb", ".idea", ".vscode",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages",
    "dist", "build", ".next", ".cache", "graphify-out",
}

# Ein Dateiname oder Pfad im Auftragstext: Namensteile mit Trennern,
# abgeschlossen von einer Endung. "core/fenster.py" ebenso wie "main.py".
MUSTER_DATEI = re.compile(r"[A-Za-z0-9_.\-]+(?:[/\\][A-Za-z0-9_.\-]+)*\.[A-Za-z0-9]{1,6}")

# Grenzen, damit das Durchsehen grosser Projekte kurz bleibt.
MAX_TIEFE = 6
MAX_DATEIEN = 30000
CACHE_ALTER = 60.0  # Sekunden, die ein gelesener Dateibestand gilt

# Dateibestand je Projektpfad: (Zeitpunkt, volle Pfade, Basisnamen)
_bestand_cache: dict[str, tuple[float, set[str], set[str]]] = {}

# Der eine vorgemerkte Auftrag: (Projektname, Rohtext) oder None.
_vorgemerkt: tuple[str, str] | None = None


# ---------------------------------------------------------------------------
# Dateibestand eines Projekts
# ---------------------------------------------------------------------------

def _bestand(pfad: Path) -> tuple[set[str], set[str]]:
    """Alle Dateien eines Projekts, einmal als Pfad ab Projektwurzel und
    einmal als blosser Dateiname, beides klein geschrieben."""
    schluessel = str(pfad)
    jetzt = time.monotonic()
    gemerkt = _bestand_cache.get(schluessel)
    if gemerkt is not None and jetzt - gemerkt[0] < CACHE_ALTER:
        return gemerkt[1], gemerkt[2]

    pfade: set[str] = set()
    namen: set[str] = set()
    try:
        wurzel = str(pfad)
        for ordner, unterordner, dateien in os.walk(wurzel):
            unterordner[:] = [
                u for u in unterordner
                if u not in ORDNER_UEBERGEHEN and not u.startswith(".")
            ]
            rest = ordner[len(wurzel):].strip("\\/")
            if rest.count(os.sep) + 1 > MAX_TIEFE:
                unterordner[:] = []
                continue
            for datei in dateien:
                namen.add(datei.lower())
                teil = f"{rest}/{datei}" if rest else datei
                pfade.add(teil.replace("\\", "/").lower())
            if len(pfade) > MAX_DATEIEN:
                log.info("Dateibestand von %s gekuerzt bei %d Eintraegen",
                         pfad, len(pfade))
                break
    except OSError as fehler:
        log.error("Dateibestand von %s nicht lesbar: %s", pfad, fehler)

    _bestand_cache[schluessel] = (jetzt, pfade, namen)
    return pfade, namen


def _kommt_vor(kandidat: str, pfade: set[str], namen: set[str]) -> bool:
    """Wahr, wenn der genannte Dateiname oder Pfad zum Bestand passt."""
    kandidat = kandidat.replace("\\", "/").lower().strip("/")
    if not kandidat:
        return False
    if kandidat in pfade or kandidat in namen:
        return True
    # Genannt wird oft nur ein Stueck des Pfades, etwa "core/fenster.py"
    # oder ein vollstaendiger Windows-Pfad. Beides zaehlt als Treffer.
    return any(voll.endswith("/" + kandidat) for voll in pfade)


def _kandidaten(text: str) -> list[str]:
    """Alle Dateinamen und Pfade, die im Auftragstext stehen."""
    gefunden: list[str] = []
    for treffer in MUSTER_DATEI.findall(text):
        eintrag = treffer.strip(".,;:!?()[]{}\"'")
        if not eintrag or eintrag.endswith("."):
            continue
        if eintrag.lower() not in [g.lower() for g in gefunden]:
            gefunden.append(eintrag)
    return gefunden


# ---------------------------------------------------------------------------
# Erkennung
# ---------------------------------------------------------------------------

def fremdes_projekt_erkennen(text: str, aktuelles: Projekt) -> str | None:
    """Name des Projekts, zu dem der Auftrag vermutlich gehoert, oder None.

    Gemeldet wird nur, wenn im Text Dateien genannt sind, die es im
    geoeffneten Projekt nicht gibt, dafuer aber in genau einem anderen."""
    try:
        kandidaten = _kandidaten(text)
        if not kandidaten:
            return None

        hier_pfade, hier_namen = _bestand(Path(aktuelles.pfad))
        offen = [k for k in kandidaten if not _kommt_vor(k, hier_pfade, hier_namen)]
        if not offen:
            return None

        treffer: dict[str, int] = {}
        for projekt in projekte_finden():
            if projekt.name == aktuelles.name:
                continue
            pfade, namen = _bestand(Path(projekt.pfad))
            anzahl = sum(1 for k in offen if _kommt_vor(k, pfade, namen))
            if anzahl:
                treffer[projekt.name] = anzahl

        if not treffer:
            return None
        beste = max(treffer.values())
        vorn = [name for name, wert in treffer.items() if wert == beste]
        if len(vorn) != 1:
            # Mehrere Projekte passen gleich gut: raten waere schlechter als
            # den Auftrag hier laufen zu lassen.
            log.info("Zuordnung uneindeutig: %s", ", ".join(sorted(vorn)))
            return None
        log.info("Auftrag gehoert vermutlich zu %s (genannt: %s)",
                 vorn[0], ", ".join(offen))
        return vorn[0]
    except Exception as fehler:  # noqa: BLE001
        log.exception("Projektzuordnung fehlgeschlagen: %s", fehler)
        return None


# ---------------------------------------------------------------------------
# Vormerkung
# ---------------------------------------------------------------------------

def auftrag_vormerken(projektname: str, roh: str) -> None:
    """Merkt den Auftrag im Wortlaut fuer das genannte Projekt. Eine aeltere
    Vormerkung wird dabei ersetzt."""
    global _vorgemerkt
    _vorgemerkt = (projektname, roh)
    log.info("Auftrag fuer %s vorgemerkt: %s", projektname, roh[:120])


def vormerkung_verwerfen() -> None:
    global _vorgemerkt
    if _vorgemerkt is not None:
        log.info("Vormerkung fuer %s verworfen", _vorgemerkt[0])
    _vorgemerkt = None


def vormerkung_offen() -> str | None:
    """Projektname der offenen Vormerkung, sonst None."""
    return _vorgemerkt[0] if _vorgemerkt else None


def vormerkung_abholen(projektname: str) -> str | None:
    """Beim Oeffnen eines Projekts aufzurufen. Passt die Vormerkung, wird der
    Auftrag zurueckgegeben; in jedem Fall ist sie danach verbraucht."""
    global _vorgemerkt
    if _vorgemerkt is None:
        return None
    ziel, roh = _vorgemerkt
    _vorgemerkt = None
    if ziel != projektname:
        log.info("Vormerkung fuer %s verfaellt, geoeffnet wurde %s",
                 ziel, projektname)
        return None
    return roh
