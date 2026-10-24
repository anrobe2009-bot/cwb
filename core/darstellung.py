"""
CWB - Code Workbench
Zentrale Darstellungs-Grundlage: die einzige Stelle, an der Grundgroessen und
Stufen stehen. Reines Python ohne Qt.

Grundwerte (fuer Sehende): Schrift 10,5 pt, Knoepfe mindestens 34 Pixel hoch,
Abstaende 8 Pixel, Radien 6 Pixel. Drei Stufen vergroessern diese Werte um
einen Faktor: Standard, Gross, Sehr gross.

Wie es wirkt: stil.qss ist als Verhaeltnistabelle geschrieben, bezogen auf die
Grundschrift `STIL_REFERENZ_PT`. `grundlagen.stil_anwenden` multipliziert jede
Mass-Angabe mit (Fensterfaktor * `stil_faktor()`). "Gross" entspricht genau
dem Aussehen vor Einfuehrung der Stufen und ist darum die Vorgabe.

Ausnahmen (`AUSNAHMEN`) bleiben in jeder Stufe gross und farbig: Statusbalken,
Not-Aus, Orchestrator, Neu starten, Zurueck zu Claude Code und das
Waechter-Quadrat. Sie folgen nur dem Fensterfaktor, nie der Stufe.
Zustandsfarben stehen weiter in stil.qss und werden hier nicht beruehrt.
"""

import logging
from pathlib import Path

try:
    from . import pfade
except ImportError:
    import pfade

CWB_WURZEL = Path(__file__).resolve().parent.parent
LOG_DATEI = CWB_WURZEL / "cwb_fehler.log"

pfade.log_einrichten()
log = logging.getLogger("cwb.darstellung")

SCHLUESSEL = "darstellung"

# Grundwerte fuer Sehende.
GRUND_SCHRIFT_PT = 10.5
GRUND_KNOPF_HOEHE_PX = 34
GRUND_ABSTAND_PX = 8
GRUND_RADIUS_PX = 6
MINDEST_KONTRAST = 4.5

# Fenstergroessen (Breite, Hoehe): kleinste zugelassene und Vorschlag fuer
# den ersten Start. Die Arbeitsflaeche rollt, wenn ihr der Platz nicht reicht.
FENSTER_MINDEST = (480, 360)
FENSTER_START = (1200, 850)

# Grundschrift, auf die sich alle Masse in stil.qss beziehen.
STIL_REFERENZ_PT = 17.0

STANDARD = "standard"
GROSS = "gross"
SEHR_GROSS = "sehr_gross"
STUFEN = (STANDARD, GROSS, SEHR_GROSS)
VORGABE = GROSS

STUFEN_NAMEN = {
    STANDARD: "Standard",
    GROSS: "Groß",
    SEHR_GROSS: "Sehr groß",
}

# Faktor auf die Grundwerte. "Gross" ist so gewaehlt, dass die Grundschrift
# genau der Schrift von stil.qss entspricht (bestehende Installation bleibt).
STUFEN_FAKTOR = {
    STANDARD: 1.0,
    GROSS: STIL_REFERENZ_PT / GRUND_SCHRIFT_PT,
    SEHR_GROSS: 2.2,
}

# Teile von Selektoren in stil.qss, deren Regeln nie mit der Stufe wachsen
# oder schrumpfen.
AUSNAHMEN = (
    "#balken",
    "#balkenglanz",
    "#balkentext",
    '#kachel[groesse="gross"]',
    '#kachel[farbe="notaus"]',
    '#kachel[farbe="orchestrator"]',
    '#kachel[farbe="neustart"]',
    "#orch_zurueck",
    "#orch_neustart",
    "#orch_titel",
    "#waechter_platzhalter",
)

_stufe: str | None = None


def stufe_pruefen(wert) -> str:
    return wert if wert in STUFEN else VORGABE


def stufe_lesen() -> str:
    """Gemerkte Stufe; ohne Eintrag die Vorgabe "Gross"."""
    global _stufe
    if _stufe is None:
        try:
            _stufe = stufe_pruefen(pfade.einstellungen_lesen().get(SCHLUESSEL))
        except Exception as fehler:  # noqa: BLE001
            log.exception("Darstellungsstufe nicht gelesen: %s", fehler)
            _stufe = VORGABE
    return _stufe


def stufe_setzen(stufe: str, speichern: bool = True) -> str:
    """Setzt die Stufe und schreibt sie, ohne andere Einstellungen anzutasten,
    nach einstellungen.json."""
    global _stufe
    _stufe = stufe_pruefen(stufe)
    if speichern:
        try:
            werte = pfade.einstellungen_lesen()
            werte[SCHLUESSEL] = _stufe
            pfade.einstellungen_schreiben(werte)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Darstellungsstufe nicht gespeichert: %s", fehler)
    log.info("Darstellungsstufe: %s", _stufe)
    return _stufe


def vergessen() -> None:
    """Fuer Tests: gemerkte Stufe verwerfen, beim naechsten Lesen neu laden."""
    global _stufe
    _stufe = None


def faktor(stufe: str | None = None) -> float:
    """Faktor der Stufe auf die Grundwerte."""
    return STUFEN_FAKTOR[stufe_pruefen(stufe or stufe_lesen())]


def stil_faktor(stufe: str | None = None) -> float:
    """Faktor fuer stil.qss (bezogen auf die Grundschrift der Tabelle)."""
    return GRUND_SCHRIFT_PT * faktor(stufe) / STIL_REFERENZ_PT


def schrift_pt(stufe: str | None = None) -> float:
    return GRUND_SCHRIFT_PT * faktor(stufe)


def knopf_hoehe_px(stufe: str | None = None) -> int:
    return round(GRUND_KNOPF_HOEHE_PX * faktor(stufe))


def abstand_px(stufe: str | None = None) -> int:
    return round(GRUND_ABSTAND_PX * faktor(stufe))


def radius_px(stufe: str | None = None) -> int:
    return round(GRUND_RADIUS_PX * faktor(stufe))


def ist_ausnahme(selektor: str) -> bool:
    """Wahr, wenn eine Regel von stil.qss zu den Ausnahmen gehoert."""
    return any(teil in selektor for teil in AUSNAHMEN)
