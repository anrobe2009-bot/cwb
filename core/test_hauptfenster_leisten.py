"""
CWB - Code Workbench
Tests fuer die Statuszeilen und die Orchestrator-Knoepfe des Hauptfensters:
kein Text wird abgeschnitten (Kopfzeile, untere Statuszeile), die Zaehler
brechen um, die Orchestrator-Kachel und der Zurueck-Knopf tragen dieselbe
eigene Farbe. Alles offscreen, ohne Datenordner.

Aufruf: python -m unittest core.test_hauptfenster_leisten -v
"""

import logging
import os
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QElapsedTimer
from PySide6.QtWidgets import QApplication, QLabel, QTextEdit, QVBoxLayout, QWidget

try:
    from . import grundlagen, kopfzeile
except ImportError:
    import grundlagen
    import kopfzeile

log = logging.getLogger("cwb.test_hauptfenster_leisten")


def _warten(ms: int) -> None:
    uhr = QElapsedTimer()
    uhr.start()
    while uhr.elapsed() < ms:
        QCoreApplication.processEvents()


class KopfzeileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])
        grundlagen.stil_laden(cls.anwendung)

    def _kopf(self, breite: int):
        roh = grundlagen._roh_stil
        grundlagen._roh_stil = re.sub(
            r"(\d+(?:\.\d+)?)pt", lambda m: f"{float(m.group(1)) * 1.8:.1f}pt", roh)
        self.addCleanup(setattr, grundlagen, "_roh_stil", roh)
        fenster = QWidget()
        self.addCleanup(fenster.close)
        aufbau = QVBoxLayout(fenster)
        kopf = kopfzeile.Ausgabekopf()
        aufbau.addWidget(kopf)
        for _ in range(3):
            aufbau.addWidget(QTextEdit(), 1)
        fenster.resize(breite, 900)
        fenster.show()
        grundlagen._letzter_faktor = None
        grundlagen.stil_erneuern(breite, 900)
        grundlagen.stil_anwenden(1.0)
        kopf.sicherheitshinweis_setzen(True, True, True)
        kopf.bruecke_zeigen(True)
        kopf.leitstand_zeigen(True)
        kopf.freigaben_zeigen(["a"] * 6)
        kopf.modell_zeigen("Sonnet 5.5", "Sonnet 5.5")
        kopf.such_effizienz_zeigen(182)
        kopf.masse_festlegen()
        _warten(80)
        return kopf

    def test_kein_feld_schneidet_text_ab(self):
        for breite in (960, 520):
            with self.subTest(breite=breite):
                kopf = self._kopf(breite)
                felder = [f for f in kopf.findChildren(QLabel)
                          if not f.isHidden() and f.text()]
                self.assertTrue(felder)
                for feld in felder:
                    noetig = feld.fontMetrics().horizontalAdvance(feld.text())
                    self.assertGreaterEqual(
                        feld.width(), noetig, f"{feld.text()!r} abgeschnitten")
                    self.assertLessEqual(feld.geometry().right(), kopf.width())
                self.assertGreaterEqual(
                    kopf.height(), kopf.heightForWidth(kopf.width()))

    def test_lange_modellnamen_werden_nicht_gekuerzt(self):
        # "Sonnet 5.5" ist laenger als alle Beispieltexte, an denen gemessen wird.
        kopf = self._kopf(960)
        self.assertGreaterEqual(
            kopf.modellanzeige.width(),
            kopf.modellanzeige.fontMetrics().horizontalAdvance("Sonnet 5.5"))

    def test_zaehler_brechen_bei_schmaler_breite_um(self):
        kopf = self._kopf(520)
        zaehler = [kopf.tokenzaehler, kopf.sitzungszaehler, kopf.tageszaehler]
        for z in zaehler:
            self.assertLessEqual(z.mapTo(kopf, z.rect().bottomRight()).x(), kopf.width())
        self.assertGreater(kopf.zaehlerreihe.height(), kopf.tokenzaehler.height())


class UmbruchfeldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])

    def test_wunschbreite_ist_die_textbreite_und_bricht_bei_enge(self):
        feld = kopfzeile.Umbruchfeld("Wartet: 12, 15, 17, 21, 22, 23")
        self.addCleanup(feld.close)
        breit = feld.sizeHint()
        self.assertGreaterEqual(
            breit.width(), feld.fontMetrics().horizontalAdvance(feld.text()))
        schmal = feld.heightForWidth(breit.width() // 3)
        self.assertGreater(schmal, breit.height())

    def test_flussreihe_bricht_um_statt_zu_klemmen(self):
        flaeche = QWidget()
        self.addCleanup(flaeche.close)
        fluss = kopfzeile.ZeilenFluss(flaeche)
        felder = [kopfzeile.Umbruchfeld(t) for t in
                  ("Läuft: 375", "Wartet: –", "Sitzung: 12 %", "Woche: unter Warnschwelle")]
        for feld in felder:
            fluss.addWidget(feld)
        flaeche.resize(160, 400)
        flaeche.show()
        _warten(30)
        for a in felder:
            self.assertLessEqual(a.geometry().right(), flaeche.width())
        for nr, a in enumerate(felder):
            for b in felder[nr + 1:]:
                self.assertFalse(a.geometry().intersects(b.geometry()))


if __name__ == "__main__":
    unittest.main()
