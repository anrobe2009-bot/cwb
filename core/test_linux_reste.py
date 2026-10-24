"""
CWB - Code Workbench
Tests fuer die Linux-Korrekturen (Block 743): Memory-Hub-Ordner anlegen,
Bericht-Datei als Dateiverweis in die Zwischenablage, tote Windows-Pfade in
einstellungen.json, xdg-open statt os.startfile.

Aufruf: python -m unittest core.test_linux_reste -v
"""

import importlib.util
import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

log = logging.getLogger("cwb.test_linux_reste")

WURZEL = Path(__file__).resolve().parent.parent


def _memory_db_laden():
    spec = importlib.util.spec_from_file_location(
        "memory_db_fuer_test", WURZEL / "memory_hub" / "memory_db.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


class MemoryHubOrdner(unittest.TestCase):
    def test_connect_legt_fehlenden_ordner_an(self):
        modul = _memory_db_laden()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "neu" / "memory_hub" / "memory.db"
            with mock.patch.object(modul, "DB_PATH", str(db)):
                modul.init_db()
            self.assertTrue(db.is_file())


class DateiInZwischenablage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        # Sonst haelt Qt beim Beenden noch die Test-Zwischenablage (Signal 11).
        cls._app.clipboard().clear()

    @unittest.skipIf(sys.platform == "win32", "Linux-Zweig")
    def test_bericht_datei_wird_dateiverweis(self):
        from PySide6.QtGui import QGuiApplication
        try:
            from . import fenster
        except ImportError:
            import fenster
        with tempfile.TemporaryDirectory() as tmp:
            datei = Path(tmp) / "bericht.zip"
            datei.write_bytes(b"x")
            self.assertTrue(fenster.datei_in_zwischenablage(datei))
            urls = QGuiApplication.clipboard().mimeData().urls()
            self.assertEqual([u.toLocalFile() for u in urls], [str(datei)])

    @unittest.skipIf(sys.platform == "win32", "Linux-Zweig")
    def test_fehlschlag_wird_gemeldet_fuer_textrueckfall(self):
        try:
            from . import fenster
        except ImportError:
            import fenster
        with mock.patch.object(fenster.zielfenster, "datei_in_zwischenablage_legen",
                               return_value=False):
            self.assertFalse(fenster.datei_in_zwischenablage(Path("/tmp/egal.zip")))

    @unittest.skipIf(sys.platform == "win32", "Linux-Zweig")
    def test_bild_liegt_nur_als_bilddaten_drin(self):
        from PySide6.QtGui import QGuiApplication, QImage
        try:
            from . import zielfenster
        except ImportError:
            import zielfenster
        with tempfile.TemporaryDirectory() as tmp:
            datei = Path(tmp) / "bild.png"
            bild = QImage(4, 4, QImage.Format_RGB32)
            bild.fill(0xFF00AA00)
            self.assertTrue(bild.save(str(datei), "PNG"))
            self.assertTrue(zielfenster.bild_in_zwischenablage_legen(str(datei)))
            mime = QGuiApplication.clipboard().mimeData()
            self.assertTrue(mime.hasImage())
            self.assertEqual(bytes(mime.data("image/png")), datei.read_bytes())
            self.assertFalse(mime.hasUrls())
            self.assertFalse(mime.hasText())
            for format_ in mime.formats():
                self.assertFalse(format_.startswith("text/"), format_)

    @unittest.skipIf(sys.platform == "win32", "Linux-Zweig")
    def test_bild_mit_url_im_gemisch_gilt_als_nicht_abgelegt(self):
        from PySide6.QtCore import QMimeData, QUrl
        from PySide6.QtGui import QGuiApplication, QImage
        try:
            from . import zielfenster
        except ImportError:
            import zielfenster
        with tempfile.TemporaryDirectory() as tmp:
            datei = Path(tmp) / "bild.png"
            QImage(4, 4, QImage.Format_RGB32).save(str(datei), "PNG")
            mime = QMimeData()
            mime.setImageData(QImage(str(datei)))
            mime.setData("image/png", datei.read_bytes())
            mime.setUrls([QUrl.fromLocalFile(str(datei))])
            QGuiApplication.clipboard().setMimeData(mime)
            ok, grund = zielfenster._bild_ablage_pruefen(datei.stat().st_size)
            self.assertFalse(ok)
            self.assertIn("zusaetzliche Formate", grund)

    @unittest.skipIf(sys.platform == "win32", "Linux-Zweig")
    def test_bild_kein_png_wird_abgelehnt(self):
        try:
            from . import zielfenster
        except ImportError:
            import zielfenster
        with tempfile.TemporaryDirectory() as tmp:
            datei = Path(tmp) / "kaputt.png"
            datei.write_bytes(b"kein bild")
            self.assertFalse(zielfenster.bild_in_zwischenablage_legen(str(datei)))
            self.assertFalse(zielfenster.bild_in_zwischenablage_legen(str(Path(tmp) / "fehlt.png")))


class EinstellungenJson(unittest.TestCase):
    def test_keine_windows_pfade_in_freigaben_und_projekten(self):
        daten = json.loads((WURZEL / "einstellungen.json").read_text(encoding="utf-8"))
        for schluessel in ("freigaben", "zusatzprojekte"):
            for eintrag in daten.get(schluessel, []):
                pfad = eintrag.get("pfad", "")
                self.assertNotRegex(pfad, r"^[A-Za-z]:\\", f"{schluessel}: {pfad}")
        namen = [e.get("name") for e in daten.get("zusatzprojekte", [])]
        self.assertIn("maxfriends", namen)


class SkillOrdnerOeffnen(unittest.TestCase):
    def test_einstellungen_nutzt_xdg_open_unter_linux(self):
        quelle = (WURZEL / "core" / "einstellungen.py").read_text(encoding="utf-8")
        self.assertIn('"xdg-open"', quelle)
        self.assertIn('sys.platform == "win32"', quelle)


if __name__ == "__main__":
    unittest.main()
