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
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QRect, QtMsgType, QTimer, qInstallMessageHandler
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
# Wiedereintritts-Sperre: waehrend setStyleSheet() laeuft, loest Qt an
# jedem Widget - auch am Hauptfenster - ein StyleChange-Ereignis aus. Ohne
# diese Sperre wuerde das dortige resizeEvent das fuer ein echtes
# Nutzer-Ziehen halten und die Skalierung erneut anstossen (analog zum
# Wiedereintritts-Schutz in ATB, _apply_scale/_breite_laeuft).
_stil_wird_angewandt = False


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


def stil_wird_angewandt() -> bool:
    """True, waehrend stil_anwenden() gerade setStyleSheet() ausfuehrt."""
    return _stil_wird_angewandt


def stil_anwenden(faktor: float) -> None:
    global _letzter_faktor, _stil_wird_angewandt
    faktor = max(SKALA_MIN, min(SKALA_MAX, faktor))
    if _letzter_faktor is not None and abs(faktor - _letzter_faktor) < 0.02:
        return
    _letzter_faktor = faktor
    anwendung = QApplication.instance()
    if anwendung is not None and _roh_stil:
        _stil_wird_angewandt = True
        try:
            anwendung.setStyleSheet(_stil_skaliert(_roh_stil, faktor))
        finally:
            _stil_wird_angewandt = False


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
# "Such-Effizienz" (Block C10, umbenannt von "Suche gespart"/"teurer als
# Volltext"): wie viele Lesezugriffe (Read, Grep, Glob, lesende
# Bash-Befehle - siehe core/sitzung.py, lesezugriffe_vor_aenderung) ein
# Auftrag im Schnitt braucht, bevor die erste Datei geändert wird, verglichen
# mit dem Grundwert vom 21.09.2026. Eine steigende Zahl heißt: Claude Code
# schaut vor dem Ändern gezielter nach. Das ist kein Maß für gesparte Token -
# reines Nachschauen vor dem Ändern kostet selbst welche.
#
# Grundwert: einmalig aus den Auftragsprotokollen vom 21.09.2026 über alle
# Projekte berechnet (siehe wissen/tagebuch.md, Block C10) und danach nicht
# mehr verändert. "Verlauf" sind die Lesezugriffe der letzten bis zu 15
# Aufträge ab Block C6, ältere fallen beim Anhängen heraus.
# ---------------------------------------------------------------------------

SUCHE_SCHLUESSEL = "suche_gespart"
SUCHE_VERLAUF_LAENGE = 15
SUCHE_MINDEST_AUFTRAEGE = 5


def suche_grundwert_lesen() -> float | None:
    """Der einmalig gemessene Grundwert, oder None, wenn er noch fehlt."""
    eintrag = einstellungen_lesen().get(SUCHE_SCHLUESSEL)
    grundwert = eintrag.get("grundwert") if isinstance(eintrag, dict) else None
    try:
        return float(grundwert) if grundwert is not None else None
    except (TypeError, ValueError):
        return None


def suche_grundwert_setzen(grundwert: float) -> None:
    """Schreibt den Grundwert. Einmalig gedacht - ein zweiter Aufruf
    überschreibt den ersten trotzdem, falls er neu gemessen werden muss."""
    werte = einstellungen_lesen()
    eintrag = werte.get(SUCHE_SCHLUESSEL)
    eintrag = dict(eintrag) if isinstance(eintrag, dict) else {}
    eintrag["grundwert"] = float(grundwert)
    werte[SUCHE_SCHLUESSEL] = eintrag
    einstellungen_schreiben(werte)


def suche_verlauf_lesen() -> list[int]:
    """Die Lesezugriffe der letzten (bis zu 15) Aufträge ab Block C6."""
    eintrag = einstellungen_lesen().get(SUCHE_SCHLUESSEL)
    verlauf = eintrag.get("verlauf") if isinstance(eintrag, dict) else None
    if not isinstance(verlauf, list):
        return []
    sauber: list[int] = []
    for wert in verlauf:
        try:
            sauber.append(int(wert))
        except (TypeError, ValueError):
            continue
    return sauber[-SUCHE_VERLAUF_LAENGE:]


def suche_auftrag_anhaengen(lesezugriffe: int) -> list[int]:
    """Haengt den Wert eines fertigen Auftrags an, behaelt nur die letzten
    15. Schlaegt das Schreiben fehl, laeuft CWB weiter - nur ohne den neuen
    Wert im Verlauf."""
    try:
        lesezugriffe = max(0, int(lesezugriffe))
    except (TypeError, ValueError):
        return suche_verlauf_lesen()
    try:
        werte = einstellungen_lesen()
        eintrag = werte.get(SUCHE_SCHLUESSEL)
        eintrag = dict(eintrag) if isinstance(eintrag, dict) else {}
        verlauf = suche_verlauf_lesen()
        verlauf.append(lesezugriffe)
        verlauf = verlauf[-SUCHE_VERLAUF_LAENGE:]
        eintrag["verlauf"] = verlauf
        werte[SUCHE_SCHLUESSEL] = eintrag
        einstellungen_schreiben(werte)
        return verlauf
    except Exception as fehler:  # noqa: BLE001
        log.exception("Suchverlauf nicht fortgeschrieben: %s", fehler)
        return suche_verlauf_lesen()


def such_effizienz_prozent() -> int | None:
    """Grundwert geteilt durch aktuellen Schnitt mal 100, ganzzahlig. 100 %
    ist der Normalwert vom 21.09.2026: mehr heißt gezielter gesucht (weniger
    Lesezugriffe vor der ersten Änderung als damals), weniger heißt
    umständlicher. None, solange kein Grundwert gesetzt ist oder weniger als
    5 Aufträge seit Block C6 im Verlauf stehen - dann zeigt die Kopfzeile
    "Such-Effizienz –" statt einer Zahl."""
    grundwert = suche_grundwert_lesen()
    verlauf = suche_verlauf_lesen()
    if not grundwert or len(verlauf) < SUCHE_MINDEST_AUFTRAEGE:
        return None
    aktuell = sum(verlauf) / len(verlauf)
    if aktuell <= 0:
        # Kein einziger Lesezugriff vor der ersten Aenderung - effizienter
        # geht es nicht, ein echter Quotient waere aber undefiniert.
        return 999
    return round(grundwert / aktuell * 100)


# ---------------------------------------------------------------------------
# Kontingent-Pause (Max-Abo): das Agent-SDK meldet ein erschoepftes
# Kontingent ueber eine RateLimitEvent-Nachricht mit status="rejected"
# (core/sitzung.py, auftrag()) - kein freier Lauftext, sondern ein
# strukturiertes Feld mit "resets_at" (Unix-Zeitstempel der Freigabe) und
# "rate_limit_type" ("five_hour", "seven_day", ...). kontingent_entscheidung()
# ist reine Logik ohne Oberflaeche, damit core/fenster.py
# (_kontingent_pause_behandeln) sie verwenden und dieses Modul sie ohne Qt
# testen kann.
# ---------------------------------------------------------------------------

KONTINGENT_WOCHENGRENZE_SEKUNDEN = 12 * 3600
KONTINGENT_NACHSCHLAG_SEKUNDEN = 2 * 60
KONTINGENT_UNBEKANNT_WARTE_SEKUNDEN = 15 * 60


def kontingent_entscheidung(resets_at: int | float | None, jetzt: datetime) -> dict:
    """Entscheidet, wie auf ein erschoepftes Kontingent reagiert wird.

    `resets_at` ist der von der RateLimitEvent-Meldung gelieferte
    Unix-Zeitstempel der Freigabe (None, wenn das SDK keinen nennt).

    Liegt die Freigabe mehr als KONTINGENT_WOCHENGRENZE_SEKUNDEN entfernt,
    handelt es sich vermutlich um das Wochenlimit statt des Fuenf-Stunden-
    Fensters: Rueckgabe mit `wochenlimit=True`, `warte_bis=None` - kein
    automatischer Fortsetzungsversuch.

    Sonst: `warte_bis` ist die Freigabe plus KONTINGENT_NACHSCHLAG_SEKUNDEN,
    ohne bekannte Freigabe `jetzt` plus KONTINGENT_UNBEKANNT_WARTE_SEKUNDEN.
    `ansage` und `status` sind fertige Saetze fuer Sprachausgabe und
    Statuszeile, `wartesekunden` (mindestens 1) die Zeit bis `warte_bis`."""
    freigabe = datetime.fromtimestamp(resets_at) if resets_at else None

    if freigabe is not None and (
            freigabe - jetzt).total_seconds() > KONTINGENT_WOCHENGRENZE_SEKUNDEN:
        return {
            "wochenlimit": True,
            "freigabe": freigabe,
            "warte_bis": None,
            "grund": (
                f"Kontingent erschöpft, Freigabe laut Claude Code erst "
                f"{freigabe:%d.%m.%Y %H:%M} Uhr – mehr als 12 Stunden entfernt, "
                "vermutlich das Wochenlimit. Warteschlange angehalten, kein "
                "automatischer Fortsetzungsversuch."
            ),
        }

    if freigabe is not None:
        warte_bis = freigabe + timedelta(seconds=KONTINGENT_NACHSCHLAG_SEKUNDEN)
        ansage = f"Kontingent erschöpft, ich mache um {warte_bis:%H:%M} Uhr weiter."
        status = f"Wartet auf Kontingent, weiter um {warte_bis:%H:%M} Uhr."
    else:
        warte_bis = jetzt + timedelta(seconds=KONTINGENT_UNBEKANNT_WARTE_SEKUNDEN)
        ansage = "Kontingent erschöpft, ich versuche es alle 15 Minuten."
        status = "Wartet auf Kontingent, nächster Versuch in 15 Minuten."

    return {
        "wochenlimit": False,
        "freigabe": freigabe,
        "warte_bis": warte_bis,
        "ansage": ansage,
        "status": status,
        "wartesekunden": max(1.0, (warte_bis - jetzt).total_seconds()),
    }


# ---------------------------------------------------------------------------
# Block 82: Kurzkennung eines Auftrags fuer die neue Leiste "Läuft"/"Wartet"
# ueber dem Ausgabefeld (core/fenster.py) und fuer F2.
# ---------------------------------------------------------------------------

def auftrags_kennung(block_nummer: int | None, quelle: str, zeit: datetime,
                      projekt: str | None = None) -> str:
    """Baut die Kurzkennung eines Auftrags: die Blocknummer aus der zweiten
    Zeile ("Block N" bzw. "# Block N" bei #RUN#/#ADMIN#, core/bloecke.py),
    weil der Chat sie Robert nennt - ohne Blocknummer (z.B. eine eigene
    Eingabe ins Feld ohne "Block N"-Zeile) `quelle` ("Eingabe",
    "Zwischenablage", "Eingang" oder "Brücke") und Uhrzeit, z.B.
    "Eingabe 16:58". `projekt` steht nur davor, wenn der Auftrag zu einem
    anderen als dem hier offenen Projekt gehoert, z.B. "CWB 37" - sonst
    bleibt es weg."""
    kern = str(block_nummer) if block_nummer is not None else f"{quelle} {zeit:%H:%M}"
    return f"{projekt} {kern}" if projekt else kern


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
        log.info(
            "Fenstergeometrie gespeichert: %dx%d bei x=%d, y=%d",
            rechteck.width(),
            rechteck.height(),
            rechteck.x(),
            rechteck.y(),
        )
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
    bildschirme = [
        (b.name(), b.availableGeometry()) for b in QApplication.screens()
    ]
    try:
        rechteck = _fenster_geometrie_gelesen()
        treffer = rechteck is not None and any(
            geo.intersects(rechteck) for _, geo in bildschirme
        )
        log.info(
            "Fenstergeometrie: gemerkt=%s, Bildschirme=%s, Treffer=%s, Fallback=%s",
            rechteck.getRect() if rechteck is not None else None,
            [(name, geo.getRect()) for name, geo in bildschirme],
            treffer,
            not treffer,
        )
        if treffer:
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


def unbehandelte_ausnahme_im_faden(args) -> None:
    """Dasselbe letzte Netz wie `unbehandelte_ausnahme`, aber fuer ungefangene
    Ausnahmen in threading.Thread-Faeden: Pythons Vorgabe dafuer ist
    threading.excepthook, nicht sys.excepthook - ohne eigene Zuweisung landet
    so eine Ausnahme weiterhin auf dem unsichtbaren stderr von pythonw und
    verschwindet spurlos, waehrend der betroffene Faden lautlos stirbt. Wird
    in main() als threading.excepthook gesetzt."""
    log.error(
        "Unbehandelte Ausnahme im Faden %s", args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


_QT_SCHWEREGRAD = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def qt_meldung_behandeln(typ, kontext, nachricht: str) -> None:
    """Letztes Netz fuer Meldungen, die Qt selbst erzeugt (qWarning/qCritical/
    qFatal aus der C++-Seite, z.B. "QObject::startTimer: Timers can only be
    used with threads started with QThread") - ohne eigenen Handler gehen sie
    nach stderr, das unter pythonw.exe ins Nichts fuehrt. Gerade ein
    qFatal() ruft diesen Handler noch VOR dem harten Abbruch auf - genau der
    stille Absturz ohne jeden Traceback, den Robert nicht lesen kann, bekommt
    dadurch wenigstens eine Zeile im Log. Wird in main() als
    qInstallMessageHandler gesetzt."""
    log.log(_QT_SCHWEREGRAD.get(typ, logging.WARNING), "Qt-Meldung: %s", nachricht)


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
                self.sprecher.sprich(SLOT_FEHLER_ANSAGE, art="fehler")
            except Exception:  # noqa: BLE001
                log.exception("Fehleransage nach Slot-Fehler nicht möglich")
            return None

    return huelle
