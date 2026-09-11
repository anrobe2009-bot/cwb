"""
CWB - Code Workbench
Pfade: wo die Projekte liegen, wo die Skills liegen, wo der Memory Hub liegt.

Reines Python ohne Oberflaeche. Dadurch koennen sicherheit.py und wissen.py
hier lesen, ohne Qt zu laden, und grundlagen.py holt sich von hier die
Einstellungsdatei.

Nichts ist fest auf einen Rechner eingetragen. Gefragt wird beim ersten
Start (core/ersteinrichtung.py), gemerkt wird in einstellungen.json unter
dem Schluessel "pfade":

    "pfade": {
      "projektwurzel": "D:/Arbeit",
      "skills":        "C:/Users/Name/.claude/skills",
      "memory_hub":    ""
    }

Ein leerer Eintrag heisst "gibt es hier nicht" - beim Memory Hub ist das der
Normalfall und bricht nichts. Fehlt ein Schluessel ganz, gilt der Vorschlag.
"""

import json
import logging
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

CWB_WURZEL = Path(__file__).resolve().parent.parent
EINSTELLUNGEN_DATEI = CWB_WURZEL / "einstellungen.json"
LOG_DATEI = CWB_WURZEL / "cwb_fehler.log"

# Das Log waechst sonst unbegrenzt. Ist die Datei voll, wandert sie nach
# cwb_fehler.log.1, die aelteren rutschen nach; alles jenseits der dritten
# Sicherung faellt weg.
LOG_GROESSE = 500 * 1024
LOG_SICHERUNGEN = 3
LOG_FORM = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def log_einrichten() -> None:
    """Haengt den rotierenden Schreiber einmalig an den Wurzel-Logger.

    Jedes Modul ruft das beim Laden auf; der zweite und jeder weitere Aufruf
    tut nichts. Nur so bekommen alle Module dieselbe Rotation - `basicConfig`
    wirkte immer nur beim zuerst geladenen Modul."""
    wurzel = logging.getLogger()
    for vorhanden in wurzel.handlers:
        if getattr(vorhanden, "_cwb_log", False):
            return
    schreiber = RotatingFileHandler(
        str(LOG_DATEI),
        maxBytes=LOG_GROESSE,
        backupCount=LOG_SICHERUNGEN,
        encoding="utf-8",
    )
    schreiber.setFormatter(logging.Formatter(LOG_FORM))
    schreiber._cwb_log = True
    wurzel.addHandler(schreiber)
    wurzel.setLevel(logging.INFO)


log_einrichten()
log = logging.getLogger("cwb.pfade")

PFADE_SCHLUESSEL = "pfade"
PROJEKTWURZEL = "projektwurzel"
SKILLS = "skills"
MEMORY_HUB = "memory_hub"
CODE_INDEX = "code_index"
ZUSATZPROJEKTE_SCHLUESSEL = "zusatzprojekte"
FREIGABEN_SCHLUESSEL = "freigaben"


# ---------------------------------------------------------------------------
# Einstellungsdatei. Sie liegt hier und nicht in grundlagen.py, damit auch
# Module ohne Oberflaeche sie lesen koennen.
# ---------------------------------------------------------------------------

def einstellungen_lesen() -> dict:
    """Liest einstellungen.json. Fehlt sie oder ist sie kaputt: leer."""
    try:
        werte = json.loads(EINSTELLUNGEN_DATEI.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fehler:
        log.info("einstellungen.json nicht lesbar: %s", fehler)
        return {}
    return werte if isinstance(werte, dict) else {}


def einstellungen_schreiben(werte: dict) -> None:
    """Schreibt einstellungen.json. Scheitert das, läuft CWB trotzdem weiter."""
    try:
        EINSTELLUNGEN_DATEI.write_text(
            json.dumps(werte, ensure_ascii=False, indent=2) + chr(10),
            encoding="utf-8",
        )
    except OSError as fehler:
        log.error("einstellungen.json nicht schreibbar: %s", fehler)


# ---------------------------------------------------------------------------
# Lesen und Merken einzelner Pfade
# ---------------------------------------------------------------------------

def pfade_lesen() -> dict:
    """Der Abschnitt "pfade" aus den Einstellungen, immer als Wörterbuch."""
    werte = einstellungen_lesen().get(PFADE_SCHLUESSEL)
    return werte if isinstance(werte, dict) else {}


def _pfad_gemerkt(schluessel: str) -> str | None:
    """Der gemerkte Text zu einem Schlüssel. `None`, wenn nie etwas gesetzt
    wurde; ein leerer Text heisst ausdrücklich "gibt es hier nicht"."""
    wert = pfade_lesen().get(schluessel)
    return wert.strip() if isinstance(wert, str) else None


def pfad_merken(schluessel: str, pfad: Path | str | None) -> None:
    """Schreibt einen Pfad in einstellungen.json. `None` merkt sich als
    leerer Text, also als bewusstes "nicht vorhanden"."""
    werte = einstellungen_lesen()
    abschnitt = werte.get(PFADE_SCHLUESSEL)
    if not isinstance(abschnitt, dict):
        abschnitt = {}
    abschnitt[schluessel] = "" if pfad is None else str(Path(pfad))
    werte[PFADE_SCHLUESSEL] = abschnitt
    einstellungen_schreiben(werte)
    log.info("Pfad gemerkt: %s = %s", schluessel, abschnitt[schluessel] or "(leer)")


# -- Projektwurzel ----------------------------------------------------------

def projektwurzel_vorschlag() -> Path:
    """Der Ordner über dem CWB-Ordner. Dort liegen die Projekte üblicherweise
    nebeneinander, CWB selbst ist eines davon."""
    return CWB_WURZEL.parent


def projektwurzel() -> Path | None:
    """Der eingestellte Projektordner, sonst `None`. Ohne ihn kann CWB keine
    Projektliste aufbauen - dann wird beim Start danach gefragt."""
    gemerkt = _pfad_gemerkt(PROJEKTWURZEL)
    if gemerkt:
        return Path(gemerkt)
    return None


def projektwurzel_merken(pfad: Path | str) -> None:
    pfad_merken(PROJEKTWURZEL, pfad)


# -- Skill-Ordner -----------------------------------------------------------

def skill_ordner_vorschlag() -> Path:
    """Der übliche Ort von Claude Code: `.claude/skills` im Benutzerordner."""
    return Path.home() / ".claude" / "skills"


def skill_ordner() -> Path:
    """Der eingestellte Skill-Ordner, sonst der Vorschlag. Gibt es ihn nicht,
    bleibt die Skill-Liste leer - gebrochen wird nichts."""
    gemerkt = _pfad_gemerkt(SKILLS)
    if gemerkt:
        return Path(gemerkt)
    return skill_ordner_vorschlag()


def skill_ordner_merken(pfad: Path | str) -> None:
    pfad_merken(SKILLS, pfad)


# -- Memory Hub -------------------------------------------------------------

def hub_datenbank_vorschlag() -> Path | None:
    """`memory_hub/memory.db` neben den Projekten, falls es sie dort gibt.
    Der Memory Hub ist kein Teil von CWB; meistens gibt es ihn nicht."""
    wurzel = projektwurzel()
    if wurzel is None:
        return None
    kandidat = wurzel / "memory_hub" / "memory.db"
    return kandidat if kandidat.is_file() else None


def hub_datenbank() -> Path | None:
    """Die eingestellte Memory-Hub-Datenbank oder `None`. `None` ist ein
    gültiger Zustand: ohne Hub arbeitet CWB nur mit dem Projektgedächtnis."""
    gemerkt = _pfad_gemerkt(MEMORY_HUB)
    if gemerkt:
        return Path(gemerkt)
    if gemerkt == "":
        return None  # ausdrücklich abgewählt
    return hub_datenbank_vorschlag()


def hub_datenbank_merken(pfad: Path | str | None) -> None:
    pfad_merken(MEMORY_HUB, pfad)


# -- Code-Index ---------------------------------------------------------------

def code_index_ordner_vorschlag() -> Path:
    """`code_index` neben CWB - dort liegt das Werkzeug fuer die Codesuche,
    falls installiert. Kein Teil von CWB, meistens gibt es ihn nicht."""
    return CWB_WURZEL.parent / "code_index"


def code_index_ordner() -> Path | None:
    """Der eingestellte Code-Index-Ordner, sonst der Vorschlag, falls er
    tatsaechlich existiert, sonst `None`. Ohne ihn bleibt das automatische
    Nachindizieren beim Sitzungsstart einfach aus - nichts haengt davon ab."""
    gemerkt = _pfad_gemerkt(CODE_INDEX)
    if gemerkt:
        return Path(gemerkt)
    vorschlag = code_index_ordner_vorschlag()
    return vorschlag if vorschlag.is_dir() else None


# -- Zusatzprojekte ----------------------------------------------------------
# Projekte ausserhalb der Projektwurzel: von Hand eingetragen im Reiter
# "Projekte" der Einstellungen, mit frei waehlbarem Anzeigenamen. Sie stehen
# nicht unter "pfade", sondern als eigene Liste in einstellungen.json:
#
#   "zusatzprojekte": [
#     {"name": "Lisa", "pfad": "E:/Sonstiges/lisa"}
#   ]

def zusatzprojekte_lesen() -> list[dict]:
    """Die gepflegte Projektliste. Ungueltige Eintraege (ohne Name oder
    Pfad) werden stillschweigend uebergangen."""
    liste = einstellungen_lesen().get(ZUSATZPROJEKTE_SCHLUESSEL)
    if not isinstance(liste, list):
        return []
    ergebnis = []
    for eintrag in liste:
        if not isinstance(eintrag, dict):
            continue
        name = str(eintrag.get("name", "")).strip()
        pfad = str(eintrag.get("pfad", "")).strip()
        if name and pfad:
            ergebnis.append({"name": name, "pfad": pfad})
    return ergebnis


def zusatzprojekte_schreiben(liste: list[dict]) -> None:
    werte = einstellungen_lesen()
    werte[ZUSATZPROJEKTE_SCHLUESSEL] = liste
    einstellungen_schreiben(werte)


def zusatzprojekt_hinzufuegen(name: str, pfad: Path | str) -> None:
    """Nimmt ein Projekt in die gepflegte Liste auf. Steht der Name schon
    dort, wird der alte Eintrag ersetzt."""
    name = name.strip()
    pfad = str(Path(pfad))
    liste = [e for e in zusatzprojekte_lesen() if e["name"] != name]
    liste.append({"name": name, "pfad": pfad})
    zusatzprojekte_schreiben(liste)
    log.info("Zusatzprojekt gemerkt: %s = %s", name, pfad)


def zusatzprojekt_entfernen(name: str) -> None:
    liste = [e for e in zusatzprojekte_lesen() if e["name"] != name]
    zusatzprojekte_schreiben(liste)
    log.info("Zusatzprojekt entfernt: %s", name)


# -- Freigaben ----------------------------------------------------------------
# Ordner ausserhalb des Projekts, in denen core/sicherheit.py (Ordnergrenze)
# ohne Rueckfrage liest und schreibt. Gepflegt im Reiter "Freigaben" der
# Einstellungen, mit Ordnerdialog hinzugefuegt und wieder entfernbar. Die
# Sperrliste fuer Zugangsdaten und die verbotenen Befehle gelten in jeder
# Freigabe unveraendert weiter (core/sicherheit.py).
#
#   "freigaben": [
#     {"name": "Skill-Ordner", "pfad": "C:/Users/Name/.claude/skills"}
#   ]
#
# Fehlt der Schluessel ganz - beim allerersten Aufruf - wird er mit den drei
# bisher fest eingebauten Ausnahmen gefuellt und gleich gesichert. Ist er
# vorhanden, auch als leere Liste, gilt er unveraendert: nur so lassen sich
# die Voreintraege dauerhaft entfernen.

def freigaben_vorgaben() -> list[dict]:
    """Die bisher fest eingebauten Ausnahmen, als Voreintraege der Liste."""
    return [
        {"name": "Skill-Ordner", "pfad": str(Path.home() / ".claude" / "skills")},
        {"name": "Claude-Temp-Ordner", "pfad": str(Path(tempfile.gettempdir()) / "claude")},
        {"name": "cwb-werkzeuge", "pfad": str(Path.home() / ".cwb-werkzeuge")},
    ]


def freigaben_lesen() -> list[dict]:
    """Die gepflegte Freigabenliste. Fehlt der Schluessel ganz, wird er mit
    den Voreintraegen gefuellt; ungueltige Eintraege (ohne Pfad) werden
    stillschweigend uebergangen."""
    werte = einstellungen_lesen()
    liste = werte.get(FREIGABEN_SCHLUESSEL)
    if liste is None:
        vorgaben = freigaben_vorgaben()
        freigaben_schreiben(vorgaben)
        return vorgaben
    if not isinstance(liste, list):
        return []
    ergebnis = []
    for eintrag in liste:
        if not isinstance(eintrag, dict):
            continue
        name = str(eintrag.get("name", "")).strip()
        pfad = str(eintrag.get("pfad", "")).strip()
        if pfad:
            ergebnis.append({"name": name or Path(pfad).name or pfad, "pfad": pfad})
    return ergebnis


def freigaben_mit_zusatz() -> list[dict]:
    """Freigaben-Liste, ergaenzt um den memory_hub-Sondereintrag aus den
    Zusatzprojekten. memory_hub zaehlt zusaetzlich als Freigabe, alle
    anderen Zusatzprojekte bleiben gegeneinander isoliert. Einzige Quelle
    fuer diese Zusammenfuehrung - sowohl die Ordnergrenze-Pruefung als auch
    add_dirs der Sitzung nutzen dieselbe Liste, damit beide nicht
    auseinanderlaufen."""
    memory_hub_eintraege = [
        e for e in zusatzprojekte_lesen() if e.get("name") == "memory_hub"
    ]
    return freigaben_lesen() + memory_hub_eintraege


def freigaben_schreiben(liste: list[dict]) -> None:
    werte = einstellungen_lesen()
    werte[FREIGABEN_SCHLUESSEL] = liste
    einstellungen_schreiben(werte)


def _freigabe_vereinheitlicht(pfad: str) -> str:
    """Vergleichsform eines Freigabepfads, robust gegen Gross-/Kleinschreibung
    und Schreibweise. Loest sich der Pfad nicht auf, bleibt der Text stehen."""
    try:
        return str(Path(pfad).resolve()).lower()
    except (OSError, ValueError):
        return str(pfad).strip().lower()


def freigabe_hinzufuegen(pfad: Path | str) -> None:
    """Nimmt einen Ordner in die Freigabenliste auf. Liegt er schon drin,
    wird der alte Eintrag ersetzt."""
    pfad = str(Path(pfad))
    ziel = _freigabe_vereinheitlicht(pfad)
    liste = [e for e in freigaben_lesen() if _freigabe_vereinheitlicht(e["pfad"]) != ziel]
    liste.append({"name": Path(pfad).name or pfad, "pfad": pfad})
    freigaben_schreiben(liste)
    log.info("Freigabe hinzugefügt: %s", pfad)


def freigabe_entfernen(pfad: Path | str) -> None:
    ziel = _freigabe_vereinheitlicht(str(pfad))
    liste = [e for e in freigaben_lesen() if _freigabe_vereinheitlicht(e["pfad"]) != ziel]
    freigaben_schreiben(liste)
    log.info("Freigabe entfernt: %s", pfad)


# -- Zustand ----------------------------------------------------------------

def pfade_vollstaendig() -> bool:
    """Wahr, sobald ein vorhandener Projektordner eingestellt ist. Nur er
    wird gebraucht; Skills und Memory Hub dürfen fehlen."""
    wurzel = projektwurzel()
    if wurzel is None:
        return False
    if not wurzel.is_dir():
        log.warning("Eingestellte Projektwurzel gibt es nicht: %s", wurzel)
        return False
    return True


if __name__ == "__main__":
    print("Einstellungsdatei :", EINSTELLUNGEN_DATEI)
    print("Projektwurzel     :", projektwurzel() or f"(nicht gesetzt, Vorschlag: {projektwurzel_vorschlag()})")
    print("Skill-Ordner      :", skill_ordner())
    print("Memory Hub        :", hub_datenbank() or "(keiner)")
    print("Vollständig       :", pfade_vollstaendig())
