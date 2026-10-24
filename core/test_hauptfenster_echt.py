"""
CWB - Code Workbench
Messung im echten Fenster: Das Hauptfenster (ohne Sitzung, mit temporaerem
Datenordner und temporaerer einstellungen.json) wird wirklich angezeigt
(xcb, wenn DISPLAY gesetzt ist, sonst nur offscreen), die Ereignisschleife
laeuft, dann wird die Geometrie aller sichtbaren Widgets in Fensterkoordinaten
verglichen: kein Paar von Geschwistern schneidet sich, kein Kind ragt aus
seinem Elternfeld, keine Beschriftung ist breiter oder hoeher als ihr Feld.
Das gilt fuer drei Fensterbreiten und alle drei Darstellungsstufen.
Je Stufe entsteht ein Bildschirmfoto unter .cwb/bilder/.

Aufruf: .venv/bin/python -m unittest core.test_hauptfenster_echt -v
"""

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Temporaerer Datenordner, bevor irgendein CWB-Modul den Pfad merkt.
_TEMP = tempfile.TemporaryDirectory(prefix="cwb_test_echt_")
os.environ["XDG_DATA_HOME"] = str(Path(_TEMP.name) / "daten")
ECHT = bool(os.environ.get("DISPLAY")) and os.environ.get("CWB_TEST_OFFSCREEN") != "1"
os.environ["QT_QPA_PLATFORM"] = "xcb" if ECHT else "offscreen"

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QRect
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QLabel,
    QScrollBar,
    QWidget,
)

try:
    from . import darstellung, fenster, grundlagen, pfade
    from .sicherheit import Projekt
    from .sprache import Sprecher
except ImportError:
    import darstellung
    import fenster
    import grundlagen
    import pfade
    from sicherheit import Projekt
    from sprache import Sprecher

log = logging.getLogger("cwb.test_hauptfenster_echt")

WURZEL = Path(__file__).resolve().parent.parent
BILDER = WURZEL / ".cwb" / "bilder"
BREITEN = (700, 960, 1400)
HOEHE = 850


def _warten(ms: int) -> None:
    uhr = QElapsedTimer()
    uhr.start()
    while uhr.elapsed() < ms:
        QCoreApplication.processEvents()


class StummerFaden(fenster.SitzungsFaden):
    """Arbeitsfaden ohne Sitzung: laeuft nicht los."""

    def run(self) -> None:
        return


class StummerWaechter:
    def __init__(self, *args, **kwargs):
        pass

    def starten(self) -> None:
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


def _sichtbare_kinder(widget: QWidget) -> list[QWidget]:
    return [k for k in widget.children()
            if isinstance(k, QWidget) and not k.isHidden() and not k.isWindow()
            and not isinstance(k, QScrollBar)]


def _name(widget: QWidget) -> str:
    text = widget.text()[:30] if hasattr(widget, "text") and callable(widget.text) else ""
    return f"{type(widget).__name__}#{widget.objectName()}({text!r})"


def verstoesse_finden(wurzel: QWidget) -> list[str]:
    """Alle Verletzungen unterhalb von `wurzel`: Ueberlappung, Herausragen,
    abgeschnittener Text."""
    fehler: list[str] = []

    def pruefen(eltern: QWidget) -> None:
        if isinstance(eltern, QAbstractScrollArea):
            return
        kinder = _sichtbare_kinder(eltern)
        rahmen = eltern.rect()
        for kind in kinder:
            if not rahmen.contains(kind.geometry()):
                fehler.append(f"ragt heraus: {_name(kind)} {kind.geometry().getRect()}"
                              f" aus {_name(eltern)} {rahmen.getRect()}")
        for i, a in enumerate(kinder):
            for b in kinder[i + 1:]:
                if a.geometry().intersects(b.geometry()):
                    fehler.append(f"ueberlappt: {_name(a)} {a.geometry().getRect()}"
                                  f" mit {_name(b)} {b.geometry().getRect()}")
        for kind in kinder:
            pruefen(kind)

    def text_pruefen(w: QWidget) -> None:
        if isinstance(w, QLabel) and w.text() and not w.pixmap().isNull() is False:
            pass
        if isinstance(w, QLabel) and w.text():
            mass = w.fontMetrics()
            if w.wordWrap():
                laengstes = max((mass.horizontalAdvance(t) for t in w.text().split()),
                                default=0)
                if w.width() < laengstes:
                    fehler.append(f"Wort abgeschnitten: {_name(w)} breite={w.width()}")
                if w.hasHeightForWidth() and w.height() < w.heightForWidth(w.width()):
                    fehler.append(f"Text zu hoch fuer Feld: {_name(w)} "
                                  f"hoehe={w.height()} noetig={w.heightForWidth(w.width())}")
            elif w.width() < mass.horizontalAdvance(w.text()):
                fehler.append(f"Beschriftung breiter als Feld: {_name(w)} "
                              f"breite={w.width()}")
            elif w.height() < mass.height():
                fehler.append(f"Beschriftung hoeher als Feld: {_name(w)} "
                              f"hoehe={w.height()}")
        elif isinstance(w, QAbstractButton) and w.text() and not w.layout():
            if w.width() < w.fontMetrics().horizontalAdvance(w.text()):
                fehler.append(f"Knopftext breiter als Knopf: {_name(w)}")
        if not isinstance(w, QAbstractScrollArea):
            for k in _sichtbare_kinder(w):
                text_pruefen(k)

    pruefen(wurzel)
    text_pruefen(wurzel)
    return fehler


class HauptfensterEchtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])
        cls._einstellungen_alt = pfade.EINSTELLUNGEN_DATEI
        pfade.EINSTELLUNGEN_DATEI = Path(_TEMP.name) / "einstellungen.json"
        pfade.EINSTELLUNGEN_DATEI.write_text("{}", encoding="utf-8")
        cls._faden_alt = fenster.SitzungsFaden
        cls._waechter_alt = fenster.Zwischenablagewaechter
        fenster.SitzungsFaden = StummerFaden
        fenster.Zwischenablagewaechter = StummerWaechter
        grundlagen.stil_laden(cls.anwendung)
        cls.projekt = Projekt("Testprojekt", Path(_TEMP.name) / "projekt", False)
        cls.projekt.pfad.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        pfade.EINSTELLUNGEN_DATEI = cls._einstellungen_alt
        fenster.SitzungsFaden = cls._faden_alt
        fenster.Zwischenablagewaechter = cls._waechter_alt
        darstellung.vergessen()
        _TEMP.cleanup()

    def _fenster(self, breite: int, stufe: str):
        darstellung.stufe_setzen(stufe, speichern=False)
        grundlagen._letzter_faktor = None
        sprecher = Sprecher(weg="stumm", sprechen_an=False, toene_an=False)
        werkbank = fenster.Werkbank(self.projekt, sprecher)
        self.addCleanup(werkbank._schliessen_erzwingen.__class__, False)
        self.addCleanup(self._schliessen, werkbank)
        werkbank.resize(breite, HOEHE)
        werkbank.show()
        # Realistische, lange Statustexte.
        werkbank.laeuft_anzeige.setText("Läuft: Block 1234 · CODE seit 2 Min 14 s")
        werkbank.wartet_anzeige.setText("Wartet: 1235 CODE, 1236 RUN, 1237 CODE, 1238 BILD")
        werkbank.kontingent_sitzung_anzeige.setText("Sitzung: 62 % verbraucht")
        werkbank.kontingent_anzeige.setText("Woche: unter Warnschwelle")
        _warten(500)
        return werkbank

    @staticmethod
    def _schliessen(werkbank) -> None:
        werkbank._schliessen_erzwingen = True
        werkbank.close()

    def _pruefen(self, breite: int, stufe: str, foto: bool = False) -> None:
        werkbank = self._fenster(breite, stufe)
        zentrum = werkbank.centralWidget()
        if ECHT:
            self.assertEqual(werkbank.width(), breite,
                             "Fenstermanager hat die Breite veraendert")
        if foto:
            BILDER.mkdir(parents=True, exist_ok=True)
            werkbank.grab().save(str(BILDER / f"hauptfenster_{stufe}_{breite}.png"))
        fehler = verstoesse_finden(zentrum)
        if os.environ.get("CWB_MESSEN"):
            for zeile in fehler:
                print(f"[{stufe} {breite}] {zeile}", file=sys.stderr)
        self.assertEqual(fehler, [], f"Stufe {stufe}, Breite {breite}")

    def test_keine_ueberlappung(self):
        for stufe in darstellung.STUFEN:
            for breite in BREITEN:
                with self.subTest(stufe=stufe, breite=breite):
                    self._pruefen(breite, stufe, foto=(breite == 960))

    def test_ausnahmen_bleiben_in_jeder_stufe_gleich_gross(self):
        """Statusbalken und Waechter-Quadrat haengen nicht von der Stufe ab."""
        masse = {}
        for stufe in darstellung.STUFEN:
            werkbank = self._fenster(960, stufe)
            masse[stufe] = (werkbank.balken.height(),
                            werkbank.waechter_platzhalter.height(),
                            werkbank.waechter_platzhalter.width())
        for stelle in range(3):
            werte = [m[stelle] for m in masse.values()]
            # Rundung von em mal Schrift darf um einen Pixel abweichen.
            self.assertLessEqual(max(werte) - min(werte), 2, str(masse))

    def test_waechter_sitzt_links_neben_dem_balken_gleich_hoch(self):
        for stufe in darstellung.STUFEN:
            for breite in BREITEN:
                with self.subTest(stufe=stufe, breite=breite):
                    w = self._fenster(breite, stufe)
                    platz, balken = w.waechter_platzhalter, w.balken
                    # Nach dem Skalieren des Stilblatts setzt sich das Layout
                    # in einem spaeteren Durchgang; auf den Endstand warten.
                    for _ in range(20):
                        if (platz.height() == balken.height()
                                and platz.geometry().top() == balken.geometry().top()
                                and platz.geometry().right() < balken.geometry().left()):
                            break
                        _warten(250)
                    self.assertEqual(platz.height(), balken.height())
                    self.assertEqual(platz.width(), platz.height())
                    self.assertLess(platz.geometry().right(), balken.geometry().left())
                    self.assertEqual(platz.geometry().top(), balken.geometry().top())

    def test_grosskacheln_niedrig_und_nicht_abgeschnitten(self):
        for stufe in darstellung.STUFEN:
            for breite in BREITEN:
                with self.subTest(stufe=stufe, breite=breite):
                    w = self._fenster(breite, stufe)
                    for kachel in w.kacheln.kacheln:
                        if kachel.gross and not kachel.verborgen:
                            self.assertLessEqual(kachel.height(), w.balken.height() * 2,
                                                 kachel.voller_text)
                            self.assertGreaterEqual(kachel.height(),
                                                    kachel.text_feld.sizeHint().height())

    def test_modus_wird_genannt(self):
        print(f"\nAnzeige: {'echtes Fenster (xcb)' if ECHT else 'nur offscreen'}",
              file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
