"""
CWB - Code Workbench
Grundlagen: Pfade, Log, Einstellungen, Stilblatt-Skalierung, Fensterliste.

Hier steht, was mehrere Fenster gemeinsam brauchen. Es liegt bewusst nicht in
fenster.py: fenster.py wird beim Start unmittelbar aufgerufen und laeuft damit
als Hauptmodul. Holte eine andere Datei etwas von dort, laege fenster.py ein
zweites Mal im Speicher - mit einer zweiten Fensterliste und zweiten Klassen.

Aussehen kommt vollstaendig aus stil.qss. Im Python steht keine Gestaltung.
"""

import functools
import logging
import re
import sys
from datetime import date
from pathlib import Path

from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication

# Die Einstellungsdatei und alle einstellbaren Pfade liegen in pfade.py, weil
# auch Module ohne Oberflaeche (sicherheit.py, wissen.py) dort lesen muessen.
try:
    from .pfade import (
        CWB_WURZEL,
        EINSTELLUNGEN_DATEI,
        LOG_DATEI,
        einstellungen_lesen,
        einstellungen_schreiben,
        log_einrichten,
    )
except ImportError:
    from pfade import (
        CWB_WURZEL,
        EINSTELLUNGEN_DATEI,
        LOG_DATEI,
        einstellungen_lesen,
        einstellungen_schreiben,
        log_einrichten,
    )

STIL_DATEI = CWB_WURZEL / "stil.qss"
VERLAUF_CSS = CWB_WURZEL / "verlauf.css"

log_einrichten()
log = logging.getLogger("cwb.grundlagen")

# Hält alle offenen Fenster fest, damit Python sie nicht wegräumt, solange
# sie sichtbar sind. Ohne diese Liste verschwindet die Werkbank sofort wieder.
OFFENE_FENSTER: list = []


# ---------------------------------------------------------------------------
# Proportionale Skalierung: alle Maße kommen aus stil.qss, hier wird nur ein
# einheitlicher Faktor draufmultipliziert - wie beim Zoomen eines Bildes.
# Verhindert feste Pixelgrößen, ohne dass Python eigene Gestaltung erfindet.
# ---------------------------------------------------------------------------

BASIS_BREITE = 1200
BASIS_HOEHE = 850
SKALA_MIN = 0.6
SKALA_MAX = 3.0
_STIL_MASS_MUSTER = re.compile(r"(\d+(?:\.\d+)?)(pt|px)")

_roh_stil = ""
_letzter_faktor: float | None = None
_stil_zeitgeber: QTimer | None = None


def _stil_skaliert(text: str, faktor: float) -> str:
    def ersetzen(treffer: re.Match) -> str:
        wert = max(1.0, float(treffer.group(1)) * faktor)
        einheit = treffer.group(2)
        return f"{wert:.1f}{einheit}" if einheit == "pt" else f"{round(wert)}{einheit}"

    return _STIL_MASS_MUSTER.sub(ersetzen, text)


def stil_laden(anwendung: QApplication) -> None:
    """Liest stil.qss ein und legt es an. Fehlt die Datei, laeuft CWB ohne
    Gestaltung weiter - bedienbar bleibt es in jedem Fall."""
    global _roh_stil
    try:
        if STIL_DATEI.exists():
            _roh_stil = STIL_DATEI.read_text(encoding="utf-8")
            anwendung.setStyleSheet(_roh_stil)
        else:
            log.warning("stil.qss fehlt, Fenster läuft ohne Gestaltung")
    except OSError as fehler:
        log.error("stil.qss nicht lesbar: %s", fehler)


def stil_anwenden(faktor: float) -> None:
    global _letzter_faktor
    faktor = max(SKALA_MIN, min(SKALA_MAX, faktor))
    if _letzter_faktor is not None and abs(faktor - _letzter_faktor) < 0.02:
        return
    _letzter_faktor = faktor
    anwendung = QApplication.instance()
    if anwendung is not None and _roh_stil:
        anwendung.setStyleSheet(_stil_skaliert(_roh_stil, faktor))


def stil_verzoegert(breite: int, hoehe: int) -> None:
    """Wartet kurz nach dem letzten Größenänderungs-Ereignis, bevor neu
    skaliert wird - verhindert ruckelndes Neuzeichnen waehrend des Ziehens."""
    global _stil_zeitgeber
    faktor = min(breite / BASIS_BREITE, hoehe / BASIS_HOEHE)
    if _stil_zeitgeber is None:
        _stil_zeitgeber = QTimer()
        _stil_zeitgeber.setSingleShot(True)
        _stil_zeitgeber.setInterval(80)
    try:
        _stil_zeitgeber.timeout.disconnect()
    except (TypeError, RuntimeError):
        pass
    _stil_zeitgeber.timeout.connect(lambda: stil_anwenden(faktor))
    _stil_zeitgeber.start()


def stil_erneuern(breite: int, hoehe: int) -> None:
    """Wendet das Stilblatt sofort wieder an, auch wenn sich der Faktor nicht
    geaendert hat. Noetig, um eigenmaechtig gesetzte Schriften zu ueberschreiben."""
    global _letzter_faktor
    _letzter_faktor = None
    stil_anwenden(min(breite / BASIS_BREITE, hoehe / BASIS_HOEHE))


# ---------------------------------------------------------------------------
# Einstellungen: kleine Merkdatei neben stil.qss
# ---------------------------------------------------------------------------

def verlauf_stil_lesen() -> str:
    """Farbregeln der Textarten im Ausgabefeld. Qt gestaltet Textabschnitte
    nicht ueber stil.qss, sondern ueber das Stilblatt des Textdokuments;
    deshalb liegt dieser Teil in verlauf.css. Fehlt sie, bleibt die Ausgabe
    einfarbig - die Vorsatzzeichen unterscheiden die Arten weiterhin."""
    try:
        return VERLAUF_CSS.read_text(encoding="utf-8")
    except OSError as fehler:
        log.error("verlauf.css nicht lesbar: %s", fehler)
        return ""


# `einstellungen_lesen` und `einstellungen_schreiben` kommen aus pfade.py und
# werden hier nur weitergereicht, damit die bisherigen Aufrufer unverändert
# `from grundlagen import einstellungen_lesen` schreiben können.


# ---------------------------------------------------------------------------
# Tokenverbrauch je Kalendertag. Er liegt in einstellungen.json unter
# "tokenverbrauch", mit dem Datum als Schlüssel: {"2026-09-05": 12345}.
# Dadurch zählt er über alle Sitzungen und Neustarts eines Tages hinweg
# zusammen und setzt sich um Mitternacht von selbst zurück - der neue Tag
# bringt einfach einen neuen Schlüssel mit. Gezählt werden wie überall nur
# echte Eingabe- und Ausgabetoken ohne Cache. Aufbewahrt werden die letzten
# dreißig Tage; ältere Einträge fallen beim Schreiben heraus.
# ---------------------------------------------------------------------------

TAGESVERBRAUCH_SCHLUESSEL = "tokenverbrauch"
TAGE_AUFBEWAHRT = 30


def heutiger_tag() -> str:
    """Der heutige Kalendertag als Schlüssel: '2026-09-05'."""
    return date.today().isoformat()


def _tage_saeubern(tage: dict) -> dict:
    """Wirft alles weg, was kein Datum-Zahl-Paar ist, und behält nur die
    jüngsten dreißig Tage. Die Sortierung nach Text reicht, weil das
    ISO-Datum in Textreihenfolge auch die Zeitreihenfolge ist."""
    sauber: dict[str, int] = {}
    for tag, anzahl in tage.items():
        try:
            date.fromisoformat(str(tag))
            sauber[str(tag)] = int(anzahl)
        except (TypeError, ValueError):
            continue
    jung = sorted(sauber, reverse=True)[:TAGE_AUFBEWAHRT]
    return {tag: sauber[tag] for tag in sorted(jung)}


def tagesverbrauch_lesen() -> dict:
    """Alle aufbewahrten Tage, aufsteigend nach Datum: {'2026-09-05': 12345}."""
    tage = einstellungen_lesen().get(TAGESVERBRAUCH_SCHLUESSEL)
    if not isinstance(tage, dict):
        return {}
    try:
        return _tage_saeubern(tage)
    except Exception as fehler:  # noqa: BLE001
        log.exception("Tagesverbrauch nicht lesbar: %s", fehler)
        return {}


def tagesverbrauch_heute() -> int:
    """Was heute bisher verbraucht wurde, über alle Sitzungen zusammen."""
    return int(tagesverbrauch_lesen().get(heutiger_tag(), 0))


def tagesverbrauch_erhoehen(anzahl: int) -> int:
    """Schreibt `anzahl` Token dem heutigen Tag gut und gibt die neue
    Tagessumme zurück. Schlägt das Schreiben fehl, läuft CWB weiter; gemeldet
    wird dann trotzdem die richtige Summe."""
    try:
        anzahl = max(0, int(anzahl))
    except (TypeError, ValueError):
        return tagesverbrauch_heute()
    try:
        werte = einstellungen_lesen()
        tage = werte.get(TAGESVERBRAUCH_SCHLUESSEL)
        tage = _tage_saeubern(tage) if isinstance(tage, dict) else {}
        heute = heutiger_tag()
        tage[heute] = int(tage.get(heute, 0)) + anzahl
        werte[TAGESVERBRAUCH_SCHLUESSEL] = _tage_saeubern(tage)
        einstellungen_schreiben(werte)
        return int(werte[TAGESVERBRAUCH_SCHLUESSEL].get(heute, anzahl))
    except Exception as fehler:  # noqa: BLE001
        log.exception("Tagesverbrauch nicht fortgeschrieben: %s", fehler)
        return tagesverbrauch_heute()


# ---------------------------------------------------------------------------
# Fenstergeometrie der Werkbank: Position und Größe merken sich beim
# Schließen in einstellungen.json unter "fenster", damit das Fenster beim
# nächsten Start wieder genau dort und genauso groß erscheint.
# ---------------------------------------------------------------------------

FENSTER_SCHLUESSEL = "fenster"
FENSTER_BREITE_VORSCHLAG = 1200
FENSTER_HOEHE_VORSCHLAG = 850


def fenster_geometrie_merken(rechteck: QRect) -> None:
    """Sichert Position und Größe der Werkbank. Schlägt das Schreiben fehl,
    läuft CWB trotzdem weiter - nur ohne gemerkte Geometrie."""
    try:
        werte = einstellungen_lesen()
        werte[FENSTER_SCHLUESSEL] = {
            "x": rechteck.x(),
            "y": rechteck.y(),
            "breite": rechteck.width(),
            "hoehe": rechteck.height(),
        }
        einstellungen_schreiben(werte)
    except Exception as fehler:  # noqa: BLE001
        log.exception("Fenstergeometrie nicht sicherbar: %s", fehler)


def _fenster_geometrie_gelesen() -> QRect | None:
    """Die gemerkte Geometrie als QRect, sonst nichts."""
    geo = einstellungen_lesen().get(FENSTER_SCHLUESSEL)
    if not isinstance(geo, dict):
        return None
    try:
        breite, hoehe = int(geo["breite"]), int(geo["hoehe"])
        if breite <= 0 or hoehe <= 0:
            return None
        return QRect(int(geo["x"]), int(geo["y"]), breite, hoehe)
    except (KeyError, TypeError, ValueError):
        return None


def fenster_geometrie_anwenden(fenster) -> None:
    """Stellt die gemerkte Position und Größe wieder her. Fehlt sie, oder
    liegt sie außerhalb jedes sichtbaren Bildschirms, erscheint das Fenster
    stattdessen mittig in Vorschlagsgröße."""
    try:
        rechteck = _fenster_geometrie_gelesen()
        if rechteck is not None and any(
            bildschirm.availableGeometry().intersects(rechteck)
            for bildschirm in QApplication.screens()
        ):
            fenster.setGeometry(rechteck)
            return
    except Exception as fehler:  # noqa: BLE001
        log.exception("Fenstergeometrie nicht lesbar: %s", fehler)
    fenster.resize(FENSTER_BREITE_VORSCHLAG, FENSTER_HOEHE_VORSCHLAG)
    bildschirm = QApplication.primaryScreen()
    if bildschirm is not None:
        rahmen = fenster.frameGeometry()
        rahmen.moveCenter(bildschirm.availableGeometry().center())
        fenster.move(rahmen.topLeft())


# ---------------------------------------------------------------------------
# Fehler sichtbar machen: CWB läuft über pythonw, also ohne Konsole. Alles,
# was Python oder Qt nach stderr schreiben würden, wäre spurlos verloren.
# ---------------------------------------------------------------------------

SLOT_FEHLER_ANSAGE = "Fehler in der Oberfläche, steht im Log"


def unbehandelte_ausnahme(typ, wert, spur) -> None:
    """Letztes Netz: schreibt jede ungefangene Ausnahme mit vollem Traceback
    in cwb_fehler.log. Wird in main() als sys.excepthook gesetzt."""
    if issubclass(typ, KeyboardInterrupt):
        sys.__excepthook__(typ, wert, spur)
        return
    log.error("Unbehandelte Ausnahme", exc_info=(typ, wert, spur))


def slot_geschuetzt(funktion):
    """Hülle für Qt-Slots: fängt jede Ausnahme ab, schreibt sie mit vollem
    Traceback ins Log und sagt dem Nutzer kurz Bescheid.

    Ohne diese Hülle bricht ein Slot mitten in der Arbeit ab, ohne dass
    jemand davon erfährt - Qt reicht die Ausnahme nur an stderr weiter."""

    @functools.wraps(funktion)
    def huelle(self, *args, **kwargs):
        try:
            return funktion(self, *args, **kwargs)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Fehler in %s: %s", funktion.__name__, fehler)
            try:
                self.sprecher.sprich(SLOT_FEHLER_ANSAGE, art="meldung")
            except Exception:  # noqa: BLE001
                log.exception("Fehleransage nach Slot-Fehler nicht möglich")
            return None

    return huelle
