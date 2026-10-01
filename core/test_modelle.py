"""
CWB - Code Workbench
Unit-Tests fuer core/modelle.py: anzeige_name() (Block 70, Teil B).

Aufruf: python -m unittest core.test_modelle -v
"""

import unittest

try:
    from . import modelle
except ImportError:
    import modelle


class AnzeigeNameTest(unittest.TestCase):

    def test_sonnet(self):
        self.assertEqual(modelle.anzeige_name("claude-sonnet-5"), ("Sonnet 5", "Sonnet"))

    def test_opus_mit_kontextzusatz(self):
        self.assertEqual(modelle.anzeige_name("claude-opus-5[1m]"), ("Opus 5", "Opus"))

    def test_haiku(self):
        self.assertEqual(
            modelle.anzeige_name("claude-haiku-4-5-20251001"), ("Haiku 4.5", "Haiku")
        )

    def test_fable(self):
        self.assertEqual(modelle.anzeige_name("claude-fable-5-1"), ("Fable 5.1", "Fable"))

    def test_unbekannter_name_bleibt_unveraendert(self):
        self.assertEqual(modelle.anzeige_name("irgendwas-neues"), ("irgendwas-neues",
                                                                    "irgendwas-neues"))

    def test_leerer_name_ergibt_unbekannt(self):
        self.assertEqual(modelle.anzeige_name(""), ("unbekannt", "unbekannt"))


if __name__ == "__main__":
    unittest.main()
