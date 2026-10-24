"""
CWB - Code Workbench
Tests fuer das Startlayout der Kachelreihe (core/tastenleiste.py): Reihen und
Kacheln ueberlappen sich nie, keine Aufschrift wird gekuerzt, auch nicht nach
dem Wechsel des Stilblatts (Skalierung) beim ersten Anzeigen.

Aufruf: python -m unittest core.test_kachelreihe_layout -v
"""

import logging
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QElapsedTimer
from PySide6.QtWidgets import QApplication, QTextEdit, QVBoxLayout, QWidget

try:
    from . import grundlagen, tastenleiste
except ImportError:
    import grundlagen
    import tastenleiste

log = logging.getLogger("cwb.test_kachelreihe_layout")

EINTRAEGE = [
    ("⛔", "Not-Aus", "F8", "notaus"),
    ("✎", "Lesen und Schreiben", "F10", "nurlesen"),
    ("⇄", "Brücke an", "", "1"),
    ("◎", "Leitstand an", "", "2"),
    ("⧉", "Bericht-Text kopieren", "F6", "3"),
    ("⟳", "Neu starten", "Strg+F4", "5"),
    ("⇄", "Projekt wechseln", "F9", "6"),
    ("⚙", "Einstellungen", "F12", "7"),
]


def _warten(millisekunden: int) -> None:
    uhr = QElapsedTimer()
    uhr.start()
    while uhr.elapsed() < millisekunden:
        QCoreApplication.processEvents()


class KachelreiheLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])
        grundlagen.stil_laden(cls.anwendung)

    def setUp(self):
        grundlagen._letzter_faktor = None
        self._neues_fenster()

    def _neues_fenster(self):
        if getattr(self, "fenster", None) is not None:
            self.fenster.close()
        self.fenster = QWidget()
        aufbau = QVBoxLayout(self.fenster)
        self.reihe = tastenleiste.Kachelreihe(
            [(s, b, t, f, lambda: None) for s, b, t, f in EINTRAEGE]
        )
        aufbau.addWidget(self.reihe)
        aufbau.addStretch(1)

    def tearDown(self):
        self.fenster.close()

    def _pruefen(self, text: str) -> None:
        sichtbar = [k for k in self.reihe.kacheln if not k.verborgen]
        for nr, a in enumerate(sichtbar):
            self.assertLessEqual(a.geometry().bottom(), self.reihe.height(),
                                 f"{text}: {a.voller_text} ragt aus der Reihe")
            self.assertNotIn("…", a.text_feld.text(), f"{text}: gekuerzt")
            self.assertNotIn("...", a.text_feld.text(), f"{text}: gekuerzt")
            self.assertGreaterEqual(
                a.text_feld.height(), a.text_feld.heightForWidth(a.text_feld.width()),
                f"{text}: Text von {a.voller_text} abgeschnitten")
            for b in sichtbar[nr + 1:]:
                self.assertFalse(a.geometry().intersects(b.geometry()),
                                 f"{text}: {a.voller_text} ueberlappt {b.voller_text}")
        self.assertGreaterEqual(
            self.reihe.height(), self.reihe.raster.totalHeightForWidth(self.reihe.width()),
            f"{text}: Reihe niedriger als ihr Inhalt")

    def test_start_klein_dann_skaliert(self):
        for breite, hoehe in ((650, 830), (500, 700), (1200, 850), (320, 600)):
            with self.subTest(breite=breite, hoehe=hoehe):
                self._neues_fenster()
                self.fenster.resize(breite, hoehe)
                self.fenster.show()
                _warten(30)
                self._pruefen("nach show")
                grundlagen.stil_erneuern(breite, hoehe)
                _warten(60)
                self._pruefen("nach Skalierung")

    def test_grosse_schrift_bricht_um_statt_zu_kuerzen(self):
        roh = grundlagen._roh_stil
        grundlagen._roh_stil = roh.replace("11pt", "17pt")
        try:
            self.fenster.resize(650, 830)
            self.fenster.show()
            grundlagen.stil_erneuern(650, 830)
            _warten(60)
            self._pruefen("grosse Schrift")
        finally:
            grundlagen._roh_stil = roh
            grundlagen.stil_erneuern(650, 830)

    def test_grosse_schrift_im_engen_spaltenlayout_ueberlappt_nicht(self):
        """Wie im Bildschirmfoto: Schrift 1,8-fach, Fenster rund 960 breit,
        Kacheln in mehreren Zeilen, darunter streitende Streckfelder. Die Reihe
        darf nie niedriger werden als ihr Inhalt."""
        import re
        roh = grundlagen._roh_stil
        grundlagen._roh_stil = re.sub(
            r"(\d+(?:\.\d+)?)pt", lambda m: f"{float(m.group(1)) * 1.8:.1f}pt", roh)
        try:
            for hoehe in (900, 600):
                with self.subTest(hoehe=hoehe):
                    self._neues_fenster()
                    aufbau = self.fenster.layout()
                    for _ in range(4):
                        aufbau.addWidget(QTextEdit(), 1)
                    self.fenster.resize(960, hoehe)
                    self.fenster.show()
                    grundlagen._letzter_faktor = None
                    grundlagen.stil_erneuern(960, hoehe)
                    grundlagen.stil_anwenden(1.0)
                    _warten(80)
                    self._pruefen("Schrift 1,8")
        finally:
            grundlagen._roh_stil = roh
            grundlagen._letzter_faktor = None
            grundlagen.stil_erneuern(650, 830)

    def test_neu_berechnen_nach_ausblenden(self):
        self.fenster.resize(650, 830)
        self.fenster.show()
        _warten(30)
        self.reihe.kachel_zeigen("Brücke an", False)
        self.reihe.neu_berechnen()
        _warten(30)
        self._pruefen("nach Ausblenden")


if __name__ == "__main__":
    unittest.main()
