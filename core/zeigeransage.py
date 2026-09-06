"""
CWB - Code Workbench
Ansage bei Mauszeiger fuer das ganze Fenster.

Ruht der Zeiger etwa eine Drittelsekunde auf einem Bedienelement oder einem
Anzeigefeld, wird dessen Inhalt gesprochen: Kacheln, Kopfzeile, Plakette,
Dateiname, Zaehler, Modellfeld, Eingabefeld, Schaltflaechen und alle Elemente
der Einstellungsseite. Verlaesst der Zeiger das Element oder wandert er
weiter, bricht die laufende Ansage sofort ab.

Es spricht immer nur ein Element. Beim schnellen Darueberfahren kommt gar
nichts, weil die Wartezeit jedes Mal neu beginnt.

Der Filter haengt an der Anwendung, nicht an einzelnen Fenstern. Damit gilt
er ohne Zutun auch fuer die Einstellungsseite und jedes weitere Fenster.
Ob gesprochen wird, entscheidet bei jedem Halt der Schalter
`mauszeiger_ansage` aus einstellungen.json - so wirkt das Umschalten sofort.

Hier steht keine Gestaltung; das Modul hat keine eigene Oberflaeche.
"""

import logging
import re
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QTextEdit,
    QWidget,
)

CWB_WURZEL = Path(__file__).resolve().parent.parent
LOG_DATEI = CWB_WURZEL / "cwb_fehler.log"

logging.basicConfig(
    filename=str(LOG_DATEI),
    filemode="a",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("cwb.zeigeransage")

# Etwa eine Drittelsekunde ruhen, dann wird angesagt.
ANSAGE_VERZOEGERUNG_MS = 330

# Laengster gesprochener Inhalt eines Feldes. Ein voller Verlauf oder ein
# langer Auftrag wird abgeschnitten, sonst redet die Stimme minutenlang.
INHALT_LAENGE = 160

_MARKIERUNG = re.compile(r"<[^>]+>")
_KUERZEL = re.compile(r"&(?=\w)")


def _sauber(text: str) -> str:
    """Nimmt Markierung, Kuerzel-Kaufmannsund und Zeilenumbrueche heraus."""
    if not text:
        return ""
    text = _MARKIERUNG.sub(" ", str(text))
    text = _KUERZEL.sub("", text)
    return " ".join(text.split())


def _kurz(text: str, laenge: int = INHALT_LAENGE) -> str:
    text = _sauber(text)
    if len(text) <= laenge:
        return text
    return text[:laenge].rstrip() + " und weiter"


def _inhalt(element: QWidget) -> str:
    """Der gesprochene Inhalt eines Elements, ohne seinen Namen."""
    if isinstance(element, QComboBox):
        return _sauber(element.currentText())
    if isinstance(element, QAbstractButton):
        teil = _sauber(element.text())
        if element.isCheckable():
            zustand = "an" if element.isChecked() else "aus"
            return f"{teil}, {zustand}" if teil else zustand
        return teil
    if isinstance(element, QLineEdit):
        return _kurz(element.text() or element.placeholderText())
    if isinstance(element, QPlainTextEdit):
        return _kurz(element.toPlainText() or element.placeholderText())
    if isinstance(element, QTextEdit):
        # Der Verlauf ist beliebig lang; hier reicht der Anfang.
        return _kurz(element.toPlainText() or element.placeholderText())
    if isinstance(element, QAbstractSpinBox):
        return _sauber(element.text())
    if isinstance(element, QAbstractSlider):
        return str(element.value())
    if isinstance(element, QProgressBar):
        return _sauber(element.text())
    if isinstance(element, QLabel):
        return _sauber(element.text())
    return ""


def ansagetext(element) -> str:
    """Baut den Satz zu einem Element. Leer heisst: nichts ansagen."""
    if not isinstance(element, QWidget):
        return ""
    try:
        if not element.isVisible():
            return ""
        name = _sauber(element.accessibleName())
        inhalt = _inhalt(element)
        erklaerung = _sauber(element.accessibleDescription())
        hinweis = _sauber(element.toolTip())
    except RuntimeError:
        # Element wurde inzwischen abgeraeumt.
        return ""

    # Reine Sinnbilder wie der Pfeil auf der Sendeschaltflaeche sagen nichts;
    # gesprochen wird dann allein der barrierefreie Name.
    if inhalt and not any(zeichen.isalnum() for zeichen in inhalt):
        inhalt = ""

    if name and inhalt and inhalt.lower() not in name.lower():
        satz = f"{name}: {inhalt}"
    else:
        satz = name or inhalt

    if not satz:
        satz = hinweis
    elif erklaerung and erklaerung.lower() not in satz.lower():
        satz = f"{satz}. {erklaerung}"

    return _kurz(satz, INHALT_LAENGE * 2)


class ZeigerAnsage(QObject):
    """Haengt als Filter an der Anwendung und sagt das Element unter dem
    Zeiger an, sobald dieser kurz stillsteht."""

    def __init__(self, sprecher, einstellungen_lesen, eltern=None):
        super().__init__(eltern)
        self.sprecher = sprecher
        self._einstellungen_lesen = einstellungen_lesen
        self._wartend: QWidget | None = None
        self._spricht = False
        self._laeuft = False

        self._uhr = QTimer(self)
        self._uhr.setSingleShot(True)
        self._uhr.setInterval(ANSAGE_VERZOEGERUNG_MS)
        self._uhr.timeout.connect(self._ansagen)

    # -- An- und Abmelden ---------------------------------------------------

    def starten(self) -> bool:
        """Meldet den Filter bei der Anwendung an. Gilt damit fuer jedes
        Fenster, auch fuer spaeter geoeffnete."""
        anwendung = QApplication.instance()
        if anwendung is None:
            log.error("Keine Anwendung vorhanden, Zeigeransage nicht angemeldet")
            return False
        if self._laeuft:
            return True
        anwendung.installEventFilter(self)
        self._laeuft = True
        log.info("Zeigeransage angemeldet, Wartezeit %d ms", ANSAGE_VERZOEGERUNG_MS)
        return True

    def beenden(self) -> None:
        self._abbrechen()
        anwendung = QApplication.instance()
        if anwendung is not None and self._laeuft:
            anwendung.removeEventFilter(self)
        self._laeuft = False
        log.info("Zeigeransage abgemeldet")

    # -- Ansage -------------------------------------------------------------

    def _erwuenscht(self) -> bool:
        try:
            werte = self._einstellungen_lesen()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Einstellungen nicht lesbar: %s", fehler)
            return False
        return bool(isinstance(werte, dict) and werte.get("mauszeiger_ansage", False))

    def _abbrechen(self) -> None:
        """Haelt die Wartezeit an und bricht eine eigene Ansage sofort ab.
        Fremde Ansagen bleiben unangetastet."""
        self._uhr.stop()
        self._wartend = None
        if self._spricht:
            self._spricht = False
            try:
                self.sprecher.schweig()
            except Exception as fehler:  # noqa: BLE001
                log.exception("Ansage nicht abbrechbar: %s", fehler)

    def _ansagen(self) -> None:
        element = self._wartend
        if element is None:
            return
        try:
            satz = ansagetext(element)
        except RuntimeError:
            self._wartend = None
            return
        if not satz:
            return
        try:
            # Berührtes: erst ab Stufe zwei zu hören (core/sprache.py).
            self.sprecher.sprich(satz, art="beruehrt")
            self._spricht = True
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zeigeransage gescheitert: %s", fehler)

    def _betreten(self, element) -> None:
        if element is self._wartend and self._uhr.isActive():
            return
        # Jeder Wechsel beendet die vorige Ansage, es spricht nur ein Element.
        self._abbrechen()
        if not isinstance(element, QWidget) or not self._erwuenscht():
            return
        if not ansagetext(element):
            return
        self._wartend = element
        self._uhr.start()

    def eventFilter(self, gegenstand, ereignis) -> bool:
        try:
            art = ereignis.type()
            if art in (QEvent.Enter, QEvent.HoverEnter):
                self._betreten(gegenstand)
            elif art in (QEvent.Leave, QEvent.HoverLeave, QEvent.WindowDeactivate):
                if gegenstand is self._wartend or art is QEvent.WindowDeactivate:
                    self._abbrechen()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zeigerfilter gescheitert: %s", fehler)
        return super().eventFilter(gegenstand, ereignis)


_zeigeransage: ZeigerAnsage | None = None


def zeigeransage_einrichten(sprecher, einstellungen_lesen) -> ZeigerAnsage | None:
    """Richtet die Ansage einmal je Programmlauf ein. Ein zweiter Aufruf gibt
    dieselbe Ansage zurueck, damit kein Element doppelt gesprochen wird."""
    global _zeigeransage
    if _zeigeransage is not None:
        return _zeigeransage
    ansage = ZeigerAnsage(sprecher, einstellungen_lesen)
    if not ansage.starten():
        return None
    _zeigeransage = ansage
    return _zeigeransage
