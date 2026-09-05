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
from pathlib import Path

CWB_WURZEL = Path(__file__).resolve().parent.parent
EINSTELLUNGEN_DATEI = CWB_WURZEL / "einstellungen.json"
LOG_DATEI = CWB_WURZEL / "cwb_fehler.log"

logging.basicConfig(
    filename=str(LOG_DATEI),
    filemode="a",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("cwb.pfade")

PFADE_SCHLUESSEL = "pfade"
PROJEKTWURZEL = "projektwurzel"
SKILLS = "skills"
MEMORY_HUB = "memory_hub"


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
