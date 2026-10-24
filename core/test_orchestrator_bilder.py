"""
CWB - Code Workbench
Tests fuer Bilder, Neustart-Knopf und flachen Eingabebereich der
Orchestrator-Ansicht sowie die Kachelreihe mit grossen Kacheln.
Alles offscreen; Datenordner und Ablage liegen im Temp-Verzeichnis.

Aufruf: python -m unittest core.test_orchestrator_bilder -v
"""

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

try:
    from . import eingangsordner, grundlagen, orchestrator, orchestrator_ansicht, tastenleiste
    from .sicherheit import Projekt
except ImportError:
    import eingangsordner
    import grundlagen
    import orchestrator
    import orchestrator_ansicht
    import tastenleiste
    from sicherheit import Projekt

log = logging.getLogger("cwb.test_orchestrator_bilder")


class AnsichtBilderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])
        grundlagen.stil_laden(cls.anwendung)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.wurzel = Path(temp.name)
        for p in (mock.patch.object(orchestrator, "ORCH_ORDNER", self.wurzel / "orchestrator"),
                  mock.patch.object(eingangsordner, "EINGANG_ORDNER", self.wurzel / "eingang"),
                  mock.patch.object(orchestrator_ansicht, "ABLAGE_ORDNER", self.wurzel / "ablage")):
            p.start()
            self.addCleanup(p.stop)
        self.sprecher = mock.MagicMock()
        self.a = orchestrator_ansicht.OrchestratorAnsicht(
            Projekt("Test", self.wurzel, False), self.sprecher)
        self.addCleanup(self.a.deleteLater)

    def _bild(self) -> QImage:
        bild = QImage(8, 8, QImage.Format_RGB32)
        bild.fill(QColor("red"))
        return bild

    def test_bild_aus_zwischenablage_wird_angehaengt(self):
        self.a.bild_aus_zwischenablage(self._bild())
        self.assertEqual(len(self.a.bilder), 1)
        self.assertTrue(self.a.bilder[0].exists())
        self.assertTrue(self.a.bild_anzeige.text().startswith("1 Bild angehängt"))
        self.sprecher.ton.assert_called_once()
        self.sprecher.sprich.assert_not_called()      # nur Ton, kein neuer Satz

    def test_eingabefeld_meldet_bild_statt_text(self):
        from PySide6.QtCore import QMimeData
        mime = QMimeData()
        mime.setImageData(self._bild())
        self.a.eingabe.insertFromMimeData(mime)
        self.assertEqual(len(self.a.bilder), 1)
        self.assertEqual(self.a.eingabe.toPlainText(), "")

    def test_dateidialog_haengt_an(self):
        datei = self.wurzel / "x.png"
        self._bild().save(str(datei), "PNG")
        with mock.patch.object(orchestrator_ansicht.QFileDialog, "getOpenFileNames",
                               return_value=([str(datei)], "")):
            self.a.bild_waehlen()
        self.assertEqual(self.a.bilder, [datei])

    def test_entfernen(self):
        self.a.bild_aus_zwischenablage(self._bild())
        self.a.bild_aus_zwischenablage(self._bild())
        self.assertEqual(len(self.a.bilder), 2)
        self.a.bild_entfernen()
        self.assertEqual(len(self.a.bilder), 1)
        self.a.bilder_leeren()
        self.assertEqual(self.a.bilder, [])
        self.assertTrue(self.a.bild_zeile.isHidden())

    def test_senden_gibt_bilder_mit_und_leert_liste(self):
        self.a.bild_aus_zwischenablage(self._bild())
        faden = mock.MagicMock()
        self.a._faden_sicherstellen = lambda: faden
        self.a.eingabe.setPlainText("Schau dir das an")
        self.a.senden()
        text, bilder = faden.auftrag_geben.call_args.args
        self.assertEqual(len(bilder), 1)
        self.assertEqual(self.a.bilder, [])

    def test_bild_ohne_text_wird_nicht_gesendet(self):
        self.a.bild_aus_zwischenablage(self._bild())
        faden = mock.MagicMock()
        self.a._faden_sicherstellen = lambda: faden
        self.a.senden()
        faden.auftrag_geben.assert_not_called()
        self.assertEqual(len(self.a.bilder), 1)

    def test_neustart_knopf_sendet_signal(self):
        gemeldet = []
        self.a.neustart_gewuenscht.connect(lambda: gemeldet.append(1))
        self.a.neustart_knopf.click()
        self.assertEqual(gemeldet, [1])
        self.assertTrue(self.a.neustart_knopf.accessibleName())

    def test_keine_inline_styles(self):
        for w in (self.a.neustart_knopf, self.a.bild_anzeige,
                  self.a.bild_entfernen_knopf, self.a.bild_alle_knopf):
            self.assertEqual(w.styleSheet(), "")
            self.assertTrue(w.accessibleName())

    def test_eingabebereich_flach(self):
        """Senden und Stopp wachsen nicht mit; Hoehe kommt aus dem Inhalt."""
        from PySide6.QtWidgets import QSizePolicy
        for knopf in (self.a.senden_knopf, self.a.stopp_knopf):
            self.assertNotEqual(knopf.sizePolicy().verticalPolicy(), QSizePolicy.Expanding)


class KachelreiheGrossTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])
        grundlagen.stil_laden(cls.anwendung)

    def _reihe(self, breite: int):
        eintraege = [(s, n, "", f, lambda: None) for s, n, f in [
            ("O", "Orchestrator", "orchestrator"), ("N", "Not-Aus", "notaus"),
            ("R", "Neu starten", "neustart"), ("a", "Alpha", "ruhig"),
            ("b", "Beta", "ruhig"), ("c", "Gamma", "ruhig"), ("d", "Delta", "ruhig"),
            ("e", "Epsilon", "ruhig")]]
        reihe = tastenleiste.Kachelreihe(eintraege)
        self.addCleanup(reihe.close)
        reihe.resize(breite, 400)
        reihe.show()
        reihe.neu_berechnen()
        self.anwendung.processEvents()
        return reihe

    def test_grosse_stehen_allein_in_der_ersten_zeile(self):
        for breite in (900, 500):
            with self.subTest(breite=breite):
                reihe = self._reihe(breite)
                zeilen = {k.text_feld.text(): reihe.raster.getItemPosition(
                    reihe.raster.indexOf(k))[0] for k in reihe.kacheln}
                for name in ("Orchestrator", "Not-Aus", "Neu starten"):
                    self.assertEqual(zeilen[name], 0, name)
                for name in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon"):
                    self.assertGreaterEqual(zeilen[name], 1, name)

    def test_keine_ueberlappung(self):
        reihe = self._reihe(500)
        rechtecke = [k.geometry() for k in reihe.kacheln]
        for i, r in enumerate(rechtecke):
            for s in rechtecke[i + 1:]:
                self.assertFalse(r.intersects(s))

    def test_neustart_nicht_abschaltbar(self):
        self.assertNotIn("Neu starten", tastenleiste.KACHELN_SCHALTBAR)
        self.assertIn("Neu starten", tastenleiste.KACHELN_GROSS)


class FensterAufbauTest(unittest.TestCase):
    def test_waechter_liegt_neben_dem_balken(self):
        quelle = (Path(__file__).parent / "fenster.py").read_text(encoding="utf-8")
        self.assertIn("balken_quer.addWidget(self.waechter_platzhalter", quelle)
        self.assertNotIn("kopfleiste", quelle.replace("kopfleiste.", ""))
        self.assertNotIn("statusquer.addWidget(self.waechter_platzhalter", quelle)


if __name__ == "__main__":
    unittest.main()
