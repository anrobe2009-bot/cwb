"""
CWB - Code Workbench
End-zu-Ende-Test fuer Werkbank._absenden (core/fenster.py): ein kompletter,
aus dem Chat kopierter #CODE#-Block laeuft durch Markierungserkennung
(core/fenster.py, markierung_erkennen), Blockzeilen-Entfernung
(core/bloecke.py, block_erkennen) und Kopfzeilen-Entfernung (core/bloecke.py,
kopf_metadaten_entfernen) - genau der Weg, auf dem Block 77 einen Aufruf
ohne zugehoerigen Import hinterliess (core/fenster.py rief
kopf_metadaten_entfernen auf, ohne es zu importieren; NameError bei jedem
Auftrag mit Kopfzeilen). Reine Logik-Tests auf core/bloecke.py allein haetten
das nicht gefunden, weil dort kein Code aus core/fenster.py laeuft.

Baut keine echte Werkbank (QMainWindow) auf - zu schwer fuer einen Unit-Test
und unnoetig, da nur der reine Text-/Entscheidungsweg von _absenden geprueft
wird. Stattdessen traegt ein schlankes Objekt die echten, ungebundenen
Methoden _absenden/_block_verarbeiten aus Werkbank und die uebrigen, fuer
diesen Weg noetigen Attribute. _auftrag_starten bleibt ein Mock: er wuerde
echte Claude-Code-Sitzungen anstossen.

Laeuft ohne Qt-Fenster und ohne die echte einstellungen.json anzufassen.

Aufruf: python -m unittest core.test_absenden -v
        (oder, aus dem Ordner core/: python test_absenden.py -v)
"""

import copy
import unittest
from types import SimpleNamespace
from unittest import mock

try:
    from . import bloecke
    from .fenster import MARKIERUNG_CODE, Werkbank
except ImportError:
    import bloecke
    from fenster import MARKIERUNG_CODE, Werkbank


class _AbsendenTraeger:
    """Minimaler Platzhalter fuer Werkbank: traegt die echten Methoden
    _absenden/_block_verarbeiten, aber keine Oberflaeche."""

    _absenden = Werkbank._absenden
    _block_verarbeiten = Werkbank._block_verarbeiten

    def __init__(self, text: str):
        self.eingabe = mock.Mock()
        self.eingabe.toPlainText.return_value = text
        self.projekt = SimpleNamespace(name="CWB_TestEndeZuEnde")
        self.sprecher = mock.Mock()
        self.bilder: list = []
        self._pending_block = None
        self._holt_vorgemerkten = True
        self._sparmodus_aktiv = False
        self._sparmodus_wartend: list = []
        self._auftrag_laeuft = False
        self._kontingent_info = None
        self._warteschlange: list = []
        self._verlauf_anhaengen = mock.Mock()
        self._status_zeigen = mock.Mock()
        self._taetigkeit_zeigen = mock.Mock()
        self._auftrag_starten = mock.Mock()


class AbsendenEndeZuEndeTest(unittest.TestCase):
    """Block 88: der Absende-Pfad eines echten #CODE#-Blocks darf nicht an
    einem fehlenden Import scheitern, und Modell-/Dringend-Kopfzeilen muessen
    tatsaechlich bei _auftrag_starten ankommen."""

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

    def test_block_ohne_kopfzeilen_laeuft_durch(self):
        rohtext = (
            f"{MARKIERUNG_CODE}\nBlock 1\nProjekt: CWB_TestEndeZuEnde\n"
            "Tu etwas Normales.\nEnde Block 1"
        )
        traeger = _AbsendenTraeger(rohtext)

        traeger._absenden()

        traeger._auftrag_starten.assert_called_once()
        _args, kwargs = traeger._auftrag_starten.call_args
        self.assertIsNone(kwargs["modell_wunsch"])
        text_uebergeben = traeger._auftrag_starten.call_args[0][0]
        self.assertIn("Tu etwas Normales.", text_uebergeben)
        self.assertNotIn("Modell:", text_uebergeben)

    def test_block_mit_modell_opus_wird_weitergereicht(self):
        rohtext = (
            f"{MARKIERUNG_CODE}\nBlock 2\nProjekt: CWB_TestEndeZuEnde\n"
            "Modell: Opus\nTu etwas.\nEnde Block 2"
        )
        traeger = _AbsendenTraeger(rohtext)

        traeger._absenden()

        traeger._auftrag_starten.assert_called_once()
        _args, kwargs = traeger._auftrag_starten.call_args
        self.assertEqual(kwargs["modell_wunsch"], "opus")
        text_uebergeben = traeger._auftrag_starten.call_args[0][0]
        self.assertNotIn("Modell:", text_uebergeben)

    def test_block_mit_dringend_ja_umgeht_den_sparmodus(self):
        rohtext = (
            f"{MARKIERUNG_CODE}\nBlock 3\nProjekt: CWB_TestEndeZuEnde\n"
            "Dringend: ja\nTu etwas Eiliges.\nEnde Block 3"
        )
        traeger = _AbsendenTraeger(rohtext)
        traeger._sparmodus_aktiv = True

        traeger._absenden()

        traeger._auftrag_starten.assert_called_once()
        self.assertEqual(traeger._sparmodus_wartend, [])

    def test_ohne_dringend_bleibt_im_sparmodus_haengen(self):
        rohtext = (
            f"{MARKIERUNG_CODE}\nBlock 4\nProjekt: CWB_TestEndeZuEnde\n"
            "Tu etwas, das warten kann.\nEnde Block 4"
        )
        traeger = _AbsendenTraeger(rohtext)
        traeger._sparmodus_aktiv = True

        traeger._absenden()

        traeger._auftrag_starten.assert_not_called()
        self.assertEqual(len(traeger._sparmodus_wartend), 1)

    def test_luecke_und_erhalten_kommen_als_eine_einzige_ansage(self):
        """Block 103: Robert hoert bei der Auftragsannahme zwei sich
        ueberlagernde Stimmen, insbesondere wenn eine Block-Luecken-Warnung
        ("Bloecke X bis Y fehlen") neben "Block N erhalten" steht. Dieser
        Test stellt genau das nach: Block 5 kommt normal an, danach Block 10
        mit einer Luecke (6 bis 9 fehlen). sprecher.sprich() darf dabei fuer
        die Annahme von Block 10 nur EIN einziges Mal aufgerufen werden, mit
        Luecke und Annahme im selben Satz - zwei getrennte Aufrufe koennten
        sich ueberlagern, selbst wenn jeder einzelne Aufruf fuer sich allein
        sauber abspielt."""
        traeger = _AbsendenTraeger(
            f"{MARKIERUNG_CODE}\nBlock 5\nProjekt: CWB_TestEndeZuEnde\n"
            "Tu etwas Normales.\nEnde Block 5"
        )
        traeger._absenden()
        traeger.sprecher.sprich.reset_mock()

        traeger2 = _AbsendenTraeger(
            f"{MARKIERUNG_CODE}\nBlock 10\nProjekt: CWB_TestEndeZuEnde\n"
            "Tu etwas anderes.\nEnde Block 10"
        )
        traeger2._absenden()

        traeger2.sprecher.sprich.assert_called_once()
        satz, kwargs = traeger2.sprecher.sprich.call_args[0][0], traeger2.sprecher.sprich.call_args[1]
        self.assertIn("Block 10", satz)
        self.assertIn("erhalten", satz)
        self.assertIn("Blöcke 6 bis 9 fehlen", satz)
        self.assertEqual(kwargs.get("art"), "auftrag")


if __name__ == "__main__":
    unittest.main()
