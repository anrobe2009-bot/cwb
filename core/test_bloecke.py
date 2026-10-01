"""
CWB - Code Workbench
Unit-Tests fuer core/bloecke.py (Block 56: Blocknummern, Luecken- und
Vollstaendigkeitspruefung).

Laufen ohne Qt und ohne die echte einstellungen.json anzufassen:
`einstellungen_lesen`/`einstellungen_schreiben` werden durch einen
Speicher im Testprozess ersetzt.

Aufruf: python -m unittest core.test_bloecke -v
        (oder, aus dem Ordner core/: python test_bloecke.py -v)
"""

import copy
import unittest
from unittest import mock

try:
    from . import bloecke
except ImportError:
    import bloecke


class BlockErkennenTest(unittest.TestCase):

    def test_ohne_blockzeile_bleibt_unveraendert(self):
        inhalt = "Lies core/fenster.py und sag mir, wie es funktioniert."
        nummer, bereinigt, vollstaendig = bloecke.block_erkennen("code", inhalt)
        self.assertIsNone(nummer)
        self.assertEqual(bereinigt, inhalt)
        self.assertTrue(vollstaendig)

    def test_code_block_vollstaendig(self):
        inhalt = "Block 56\nProjekt: CWB\nTu etwas.\nEnde Block 56"
        nummer, bereinigt, vollstaendig = bloecke.block_erkennen("code", inhalt)
        self.assertEqual(nummer, 56)
        self.assertTrue(vollstaendig)
        self.assertEqual(bereinigt, "Projekt: CWB\nTu etwas.")

    def test_run_block_als_powershell_kommentar(self):
        inhalt = "# Block 12\npython -m pytest tests -q\n# Ende Block 12"
        nummer, bereinigt, vollstaendig = bloecke.block_erkennen("run", inhalt)
        self.assertEqual(nummer, 12)
        self.assertTrue(vollstaendig)
        self.assertEqual(bereinigt, "python -m pytest tests -q")

    def test_admin_block_gross_klein_und_leerraum_egal(self):
        inhalt = "#   block   9  \nGet-Service\n#ende block 9"
        nummer, bereinigt, vollstaendig = bloecke.block_erkennen("admin", inhalt)
        self.assertEqual(nummer, 9)
        self.assertTrue(vollstaendig)
        self.assertEqual(bereinigt, "Get-Service")

    def test_bild_block_ohne_ende_zeile_ist_vollstaendig(self):
        nummer, bereinigt, vollstaendig = bloecke.block_erkennen("bild", "Block 5")
        self.assertEqual(nummer, 5)
        self.assertTrue(vollstaendig)
        self.assertEqual(bereinigt, "")

    def test_fehlende_ende_zeile_ist_unvollstaendig(self):
        inhalt = "Block 56\nProjekt: CWB\nDer Text bricht hier mitten im Sa"
        nummer, bereinigt, vollstaendig = bloecke.block_erkennen("code", inhalt)
        self.assertEqual(nummer, 56)
        self.assertFalse(vollstaendig)
        self.assertIn("bricht hier mitten im Sa", bereinigt)

    def test_ende_zeile_mit_falscher_nummer_ist_unvollstaendig(self):
        inhalt = "Block 56\nText\nEnde Block 55"
        nummer, bereinigt, vollstaendig = bloecke.block_erkennen("code", inhalt)
        self.assertEqual(nummer, 56)
        self.assertFalse(vollstaendig)

    def test_nur_blockzeile_ohne_rest_ist_unvollstaendig(self):
        nummer, bereinigt, vollstaendig = bloecke.block_erkennen("code", "Block 3")
        self.assertEqual(nummer, 3)
        self.assertFalse(vollstaendig)
        self.assertEqual(bereinigt, "")


class BlockZaehlerTest(unittest.TestCase):

    def setUp(self):
        self._speicher: dict = {}

        def lesen():
            return copy.deepcopy(self._speicher)

        def schreiben(werte):
            self._speicher = copy.deepcopy(werte)

        self._patches = [
            mock.patch.object(bloecke, "einstellungen_lesen", lesen),
            mock.patch.object(bloecke, "einstellungen_schreiben", schreiben),
        ]
        for patch in self._patches:
            patch.start()
        self.addCleanup(mock.patch.stopall)

    def test_erster_block_ohne_luecke(self):
        satz = bloecke.block_zaehler_aktualisieren("CWB", 1)
        self.assertEqual(satz, "")

    def test_fortlaufend_ohne_luecke(self):
        bloecke.block_zaehler_aktualisieren("CWB", 10)
        satz = bloecke.block_zaehler_aktualisieren("CWB", 11)
        self.assertEqual(satz, "")

    def test_einzelne_luecke(self):
        bloecke.block_zaehler_aktualisieren("CWB", 10)
        satz = bloecke.block_zaehler_aktualisieren("CWB", 12)
        self.assertEqual(satz, "Achtung, Block 11 fehlt.")

    def test_mehrere_luecken(self):
        bloecke.block_zaehler_aktualisieren("CWB", 8)
        satz = bloecke.block_zaehler_aktualisieren("CWB", 12)
        self.assertEqual(satz, "Achtung, Blöcke 9 bis 11 fehlen.")

    def test_neubeginn_ohne_warnung(self):
        bloecke.block_zaehler_aktualisieren("CWB", 50)
        satz = bloecke.block_zaehler_aktualisieren("CWB", 3)
        self.assertEqual(satz, "")

    def test_projekte_getrennt(self):
        bloecke.block_zaehler_aktualisieren("CWB", 20)
        satz = bloecke.block_zaehler_aktualisieren("hausgemacht", 1)
        self.assertEqual(satz, "")

    def test_anderer_kalendertag_ohne_warnung(self):
        self._speicher = {
            bloecke.BLOCK_ZAEHLER_SCHLUESSEL: {
                "CWB": {"datum": "2000-01-01", "letzte": 5},
            }
        }
        satz = bloecke.block_zaehler_aktualisieren("CWB", 99)
        self.assertEqual(satz, "")


class NaechsteBlockNummerTest(unittest.TestCase):
    """Block 72 (core/leitstand.py): die Nummer, die ein selbst erzeugter
    Block heute tragen sollte, ohne den Zaehler zu veraendern."""

    def setUp(self):
        self._speicher: dict = {}

        def lesen():
            return copy.deepcopy(self._speicher)

        def schreiben(werte):
            self._speicher = copy.deepcopy(werte)

        self._patches = [
            mock.patch.object(bloecke, "einstellungen_lesen", lesen),
            mock.patch.object(bloecke, "einstellungen_schreiben", schreiben),
        ]
        for patch in self._patches:
            patch.start()
        self.addCleanup(mock.patch.stopall)

    def test_ohne_vorherigen_block_ist_eins(self):
        self.assertEqual(bloecke.naechste_block_nummer("CWB"), 1)

    def test_naechste_nach_bestehendem_zaehler(self):
        bloecke.block_zaehler_aktualisieren("CWB", 10)
        self.assertEqual(bloecke.naechste_block_nummer("CWB"), 11)

    def test_veraendert_den_zaehler_nicht(self):
        bloecke.block_zaehler_aktualisieren("CWB", 10)
        bloecke.naechste_block_nummer("CWB")
        bloecke.naechste_block_nummer("CWB")
        self.assertEqual(bloecke.naechste_block_nummer("CWB"), 11)

    def test_anderer_kalendertag_beginnt_bei_eins(self):
        self._speicher = {
            bloecke.BLOCK_ZAEHLER_SCHLUESSEL: {
                "CWB": {"datum": "2000-01-01", "letzte": 5},
            }
        }
        self.assertEqual(bloecke.naechste_block_nummer("CWB"), 1)


if __name__ == "__main__":
    unittest.main()
