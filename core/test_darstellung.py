"""
CWB - Code Workbench
Tests fuer die zentrale Darstellungs-Grundlage (core/darstellung.py) und ihre
Wirkung auf das Stilblatt. Schreibt nur in eine temporaere einstellungen.json.

Aufruf: .venv/bin/python -m unittest core.test_darstellung -v
"""

import json
import logging
import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from . import darstellung, grundlagen, pfade
except ImportError:
    import darstellung
    import grundlagen
    import pfade

log = logging.getLogger("cwb.test_darstellung")


def _wert(stil: str, selektor: str, eigenschaft: str) -> float:
    regel = re.search(re.escape(selektor) + r"\s*\{([^}]*)\}", stil)
    treffer = re.search(re.escape(eigenschaft) + r":\s*([\d.]+)", regel.group(1))
    return float(treffer.group(1))


class DarstellungTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        alt = pfade.EINSTELLUNGEN_DATEI
        pfade.EINSTELLUNGEN_DATEI = Path(self._temp.name) / "einstellungen.json"
        self.addCleanup(setattr, pfade, "EINSTELLUNGEN_DATEI", alt)
        self.addCleanup(darstellung.vergessen)
        darstellung.vergessen()
        self.roh = grundlagen.STIL_DATEI.read_text(encoding="utf-8")

    def test_vorgabe_ist_gross_und_aendert_nichts(self):
        self.assertEqual(darstellung.stufe_lesen(), "gross")
        self.assertAlmostEqual(darstellung.stil_faktor(), 1.0)

    def test_grundwerte_fuer_sehende(self):
        self.assertAlmostEqual(darstellung.schrift_pt("standard"), 10.5)
        self.assertGreaterEqual(darstellung.knopf_hoehe_px("standard"), 32)
        self.assertEqual(darstellung.abstand_px("standard"), 8)
        self.assertLess(darstellung.faktor("standard"), darstellung.faktor("gross"))
        self.assertLess(darstellung.faktor("gross"), darstellung.faktor("sehr_gross"))

    def test_unbekannte_stufe_faellt_auf_vorgabe(self):
        pfade.EINSTELLUNGEN_DATEI.write_text('{"darstellung": "riesig"}', encoding="utf-8")
        self.assertEqual(darstellung.stufe_lesen(), "gross")

    def test_stufe_wird_gespeichert_ohne_anderes_zu_loeschen(self):
        pfade.EINSTELLUNGEN_DATEI.write_text('{"modell": "opus"}', encoding="utf-8")
        darstellung.stufe_setzen("sehr_gross")
        gespeichert = json.loads(pfade.EINSTELLUNGEN_DATEI.read_text(encoding="utf-8"))
        self.assertEqual(gespeichert, {"modell": "opus", "darstellung": "sehr_gross"})

    def test_stufe_skaliert_normale_regeln(self):
        darstellung.stufe_setzen("gross", speichern=False)
        gross = grundlagen._stil_skaliert(self.roh, 1.0)
        darstellung.stufe_setzen("standard", speichern=False)
        standard = grundlagen._stil_skaliert(self.roh, 1.0)
        self.assertLess(_wert(standard, "#verlauf, #terminal_verlauf, #eingabe", "font-size"),
                        _wert(gross, "#verlauf, #terminal_verlauf, #eingabe", "font-size"))

    def test_ausnahmen_bleiben_in_jeder_stufe_gleich(self):
        stile = {}
        for stufe in darstellung.STUFEN:
            darstellung.stufe_setzen(stufe, speichern=False)
            stile[stufe] = grundlagen._stil_skaliert(self.roh, 1.0)
        werte = {s: _wert(t, "#balken", "min-height") for s, t in stile.items()}
        self.assertEqual(len(set(werte.values())), 1, str(werte))
        # Waechter-Quadrat in px wie der Balken: in jeder Stufe gleich gross.
        quadrat = {s: _wert(t, "#waechter_platzhalter", "min-width") for s, t in stile.items()}
        self.assertEqual(len(set(quadrat.values())), 1, str(quadrat))

    def test_stufe_aendert_keine_farben(self):
        darstellung.stufe_setzen("standard", speichern=False)
        klein = grundlagen._stil_skaliert(self.roh, 1.0)
        darstellung.stufe_setzen("sehr_gross", speichern=False)
        gross = grundlagen._stil_skaliert(self.roh, 1.0)
        farben = lambda t: re.findall(r"#[0-9a-fA-F]{6}\b", t)
        self.assertEqual(farben(klein), farben(gross))


if __name__ == "__main__":
    unittest.main()
