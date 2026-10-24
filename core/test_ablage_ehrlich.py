"""
CWB - Code Workbench
Tests zu "Ansage und Zwischenablage ehrlich": die Ansage nennt Bericht-Datei
oder Bericht-Text nur, wenn die Zwischenablage nach dem Schreiben wirklich
beides enthaelt, und die Bericht-Datei kommt nach dem Einfuegen (der Einfueger
leert die Zwischenablage), nicht davor.

Aufruf: python -m unittest core.test_ablage_ehrlich -v
"""

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

try:
    from . import einfueger, fenster
    from .fenster import Werkbank
except ImportError:
    import einfueger
    import fenster
    from fenster import Werkbank


class _Traeger:
    _bericht_ablegen = Werkbank._bericht_ablegen
    _einfuegen_fertig = Werkbank._einfuegen_fertig

    def __init__(self, datei: Path | None):
        self._letzter_bericht = "Bericht"
        self._letzter_bericht_pfad = datei
        self._ablage_hinweis = False
        self._ansage_zeitgeber = mock.Mock()
        self.sprecher = mock.Mock()


class PruefungTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.addCleanup(self.ordner.cleanup)
        self.datei = Path(self.ordner.name) / "bericht.md"
        self.datei.write_text("x", encoding="utf-8")
        QGuiApplication.clipboard().clear()

    def test_leere_zwischenablage_ist_nicht_ok(self):
        ok, grund = fenster.zwischenablage_enthaelt_datei(self.datei)
        self.assertFalse(ok)
        self.assertTrue(grund)
        self.assertFalse(fenster.zwischenablage_enthaelt_text("Bericht")[0])

    def test_datei_wird_erkannt(self):
        self.assertTrue(fenster.datei_in_zwischenablage(self.datei))
        self.assertEqual(fenster.zwischenablage_enthaelt_datei(self.datei), (True, ""))

    def test_andere_datei_ist_nicht_ok(self):
        fenster.datei_in_zwischenablage(self.datei)
        andere = Path(self.ordner.name) / "andere.md"
        andere.write_text("y", encoding="utf-8")
        self.assertFalse(fenster.zwischenablage_enthaelt_datei(andere)[0])

    def test_text_wird_erkannt(self):
        QGuiApplication.clipboard().setText("Bericht")
        self.assertTrue(fenster.zwischenablage_enthaelt_text("Bericht")[0])
        self.assertFalse(fenster.zwischenablage_enthaelt_text("anderer")[0])


class AnsageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.addCleanup(self.ordner.cleanup)
        self.datei = Path(self.ordner.name) / "bericht.md"
        self.datei.write_text("x", encoding="utf-8")
        QGuiApplication.clipboard().clear()

    def test_datei_belegt_nennt_die_datei(self):
        t = _Traeger(self.datei)
        self.assertIn("Bericht-Datei liegt", t._bericht_ablegen())

    def test_datei_behauptet_aber_leer_nennt_nichts_und_warnt(self):
        t = _Traeger(self.datei)
        modul = sys.modules[Werkbank.__module__]
        # Auch das Zurücklesen der Datei ist angenommen: ob die echte Zwischenablage
        # nach clear() "leer" oder "kein Dateiverweis" meldet, hängt vom Zustand ab.
        with mock.patch.object(modul, "datei_in_zwischenablage", return_value=True), \
                mock.patch.object(modul, "zwischenablage_enthaelt_datei",
                                  return_value=(False, "kein Dateiverweis in der Zwischenablage")), \
                mock.patch.object(modul, "zwischenablage_enthaelt_text",
                                  return_value=(False, "Zwischenablage ist leer")), \
                self.assertLogs("cwb.fenster", level=logging.WARNING) as protokoll:
            satz = t._bericht_ablegen()
        self.assertEqual(satz, "")
        self.assertTrue(any("Bericht-Datei nicht" in z and "Dateiverweis" in z
                            for z in protokoll.output))

    def test_ohne_datei_faellt_auf_geprueften_text_zurueck(self):
        t = _Traeger(None)
        self.assertIn("Bericht-Text liegt", t._bericht_ablegen())
        self.assertEqual(QGuiApplication.clipboard().text(), "Bericht")

    def test_text_nicht_belegt_nennt_nichts(self):
        t = _Traeger(None)
        modul = sys.modules[Werkbank.__module__]
        with mock.patch.object(modul, "zwischenablage_enthaelt_text",
                               return_value=(False, "Zwischenablage ist leer")), \
                self.assertLogs("cwb.fenster", level=logging.WARNING):
            self.assertEqual(t._bericht_ablegen(), "")


class ReihenfolgeTest(unittest.TestCase):
    """Einfueger zuerst, Bericht-Datei danach - sonst leert er sie wieder."""

    class Werkzeug:
        def fenster_lesen(self, kennung=None):
            return ("1", "Claude Chat", "firefox")
        def aktivieren(self, kennung):
            return True
        def taste(self, name):
            return True

    class Ablage:
        def __init__(self, ereignisse):
            self.ereignisse = ereignisse
        def setzen(self, text):
            self.ereignisse.append("text gesetzt")
            return True
        def lesen(self):
            return ""
        def leeren(self):
            self.ereignisse.append("geleert")

    def _lauf(self, scheitern: bool):
        ereignisse = []
        t = _Traeger(Path("/tmp/bericht.md"))
        t._bericht_ablegen = lambda: (ereignisse.append("datei gelegt") or
                                      " Bericht-Datei liegt in der Zwischenablage.")
        modul = sys.modules[Werkbank.__module__]
        with mock.patch.object(modul, "einstellungen_lesen", return_value={}):
            e = einfueger.Einfueger(
                self.Werkzeug(), self.Ablage(ereignisse), lambda ms, f: f(),
                lambda: False, t._einfuegen_fertig)
            e.hinzufuegen(None if scheitern else ("1", "Claude Chat", "firefox"), "Bericht")
        return ereignisse, t

    def test_datei_kommt_nach_dem_einfuegen_nicht_mehr(self):
        # Der Weg "Bericht-Datei in die Zwischenablage" ist entfallen.
        ereignisse, t = self._lauf(scheitern=False)
        self.assertEqual(ereignisse, ["text gesetzt", "geleert"])
        t.sprecher.sprich.assert_not_called()

    def test_gescheitertes_einfuegen_laesst_den_text_liegen(self):
        ereignisse, t = self._lauf(scheitern=True)
        self.assertNotIn("datei gelegt", ereignisse)


if __name__ == "__main__":
    unittest.main()
