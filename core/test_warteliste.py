"""
CWB - Code Workbench
Tests fuer core/warteliste.py (Posten, Vorlesetext, Loeschen nach verworfen/ mit
Journalzeile) und core/ansagegedaechtnis.py (Ansage nur einmal je Lage, ueber
Neustarts hinweg) sowie die auf 3 Sekunden gesenkte Ruhezeit der Zustellung.

Aufruf: python -m unittest core.test_warteliste -v
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from . import ansagegedaechtnis, einfueger, eingangsordner, warteliste
except ImportError:
    import ansagegedaechtnis
    import einfueger
    import eingangsordner
    import warteliste


class Vorlesetext(unittest.TestCase):
    def test_wartender_auftrag(self):
        p = warteliste.Posten(quelle="schlange", projekt="CWB", art="code",
                              nummer=894, block=870, platz=2)
        self.assertEqual(warteliste.vorlesetext(p),
                         "Platz 2, Auftrag 894, Projekt CWB, Code, Block 870")

    def test_laufender_ist_nicht_loeschbar_und_steht_zuerst(self):
        lauf = warteliste.Posten(quelle="laufend", projekt="CWB", art="run", nummer=7)
        wart = warteliste.Posten(quelle="schlange", projekt="CWB")
        warteliste.nummerieren([lauf, wart])
        self.assertFalse(lauf.loeschbar)
        self.assertTrue(wart.loeschbar)
        text = warteliste.vorlesetext(lauf)
        self.assertTrue(text.startswith("Platz 1, läuft gerade, Auftrag 7"))
        self.assertIn("F8", text)
        self.assertEqual(wart.platz, 2)

    def test_ohne_nummer_kommt_die_kennung(self):
        p = warteliste.Posten(quelle="schlange", projekt="CWB", kennung="Eingabe 16:58", platz=1)
        self.assertIn("Auftrag Eingabe 16:58", warteliste.vorlesetext(p))
        self.assertNotIn("Block", warteliste.vorlesetext(p))


class Verwerfen(unittest.TestCase):
    def test_datei_geht_nach_verworfen_mit_grund_und_journalzeile(self):
        with tempfile.TemporaryDirectory() as t:
            wurzel = Path(t)
            datei = wurzel / "laeuft" / "a.json"
            datei.parent.mkdir()
            datei.write_text("{}", encoding="utf-8")
            with patch.object(eingangsordner, "EINGANG_ORDNER", wurzel), \
                    patch.object(warteliste.auftragsjournal, "schreibe") as journal:
                p = warteliste.Posten(quelle="eingang", projekt="CWB", nummer=895,
                                      block=871, datei=datei, platz=3)
                ziel = warteliste.verwerfen_datei(p)
            self.assertEqual(ziel, wurzel / "verworfen" / "a.json")
            self.assertTrue(ziel.exists())
            self.assertFalse(datei.exists())
            self.assertTrue(ziel.with_suffix(".txt").exists())
            self.assertEqual(journal.call_args[0][0], "verworfen")
            self.assertEqual(journal.call_args[1]["nummer"], 895)

    def test_ohne_datei_nur_journalzeile(self):
        with patch.object(warteliste.auftragsjournal, "schreibe") as journal:
            p = warteliste.Posten(quelle="schlange", projekt="CWB", nummer=1, platz=1)
            self.assertIsNone(warteliste.verwerfen_datei(p))
        journal.assert_called_once()


class Gedaechtnis(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.datei = Path(self._t.name) / "ansagen.json"

    def tearDown(self):
        self._t.cleanup()

    def pruefen(self, wert, jetzt):
        return ansagegedaechtnis.pruefen("x", wert, self.datei, jetzt)

    def test_gleiche_lage_wird_nur_einmal_angesagt(self):
        self.assertTrue(self.pruefen("CWB", 0))
        self.assertFalse(self.pruefen("CWB", 5))
        self.assertFalse(self.pruefen("CWB", 500))

    def test_aenderung_wird_wieder_angesagt(self):
        self.assertTrue(self.pruefen("CWB", 0))
        self.assertTrue(self.pruefen("CWB,Schreiber", 1))

    def test_gilt_ueber_neustart_hinweg(self):
        self.assertTrue(self.pruefen("CWB", 0))
        # "Neustart": nichts im Speicher, nur die Datei bleibt.
        self.assertFalse(ansagegedaechtnis.pruefen("x", "CWB", self.datei, 9999))

    def test_kurzes_leeren_und_wiederkommen_bleibt_still(self):
        self.assertTrue(self.pruefen("CWB", 0))
        self.assertFalse(self.pruefen("", 10))
        self.assertFalse(self.pruefen("CWB", 20))

    def test_lange_leere_lage_zaehlt_als_aenderung(self):
        self.assertTrue(self.pruefen("CWB", 0))
        self.assertFalse(self.pruefen("", 10))
        self.assertTrue(self.pruefen("CWB", 10 + ansagegedaechtnis.LEER_NOETIG_S))

    def test_kaputte_datei_sagt_an_statt_zu_schweigen(self):
        self.datei.write_text("{kaputt", encoding="utf-8")
        self.assertTrue(self.pruefen("CWB", 0))


class Dialog(unittest.TestCase):
    """Die Liste selbst, offscreen: Tastatur, Rueckfrage, Ansagen."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _bauen(self, posten, antwort=True):
        try:
            from . import fenster
        except ImportError:
            import fenster
        self.posten = warteliste.nummerieren(list(posten))
        self.gesagt, self.geloescht = [], []

        def loeschen(p):
            self.geloescht.append(p)
            self.posten.remove(p)
            warteliste.nummerieren(self.posten)
            return f"{warteliste.kurzname(p)} gelöscht."

        return fenster.WarteschlangenFenster(
            lambda: list(self.posten), loeschen, lambda frage: antwort,
            self.gesagt.append)

    def _taste(self, d, taste):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        d.keyPressEvent(QKeyEvent(QEvent.KeyPress, taste, Qt.NoModifier))

    def _drei(self):
        return [warteliste.Posten(quelle="laufend", projekt="CWB", nummer=893),
                warteliste.Posten(quelle="schlange", projekt="CWB", nummer=894, block=870),
                warteliste.Posten(quelle="eingang", projekt="CWB", nummer=895, block=871)]

    def test_liste_zeigt_laufenden_zuerst_mit_vorlesetext(self):
        from PySide6.QtCore import Qt
        d = self._bauen(self._drei())
        self.assertEqual(d.liste.count(), 3)
        self.assertIn("läuft gerade", d.liste.item(0).text())
        self.assertEqual(d.liste.item(1).text(),
                         "Platz 2, Auftrag 894, Projekt CWB, Code, Block 870")
        self.assertEqual(d.liste.item(1).data(Qt.AccessibleTextRole), d.liste.item(1).text())

    def test_entf_auf_laufendem_loescht_nicht(self):
        from PySide6.QtCore import Qt
        d = self._bauen(self._drei())
        d.liste.setCurrentRow(0)
        self._taste(d, Qt.Key_Delete)
        self.assertEqual(self.geloescht, [])
        self.assertIn("F8", self.gesagt[-1])

    def test_entf_loescht_nach_rueckfrage_und_sagt_an(self):
        from PySide6.QtCore import Qt
        d = self._bauen(self._drei())
        d.liste.setCurrentRow(1)
        self._taste(d, Qt.Key_Delete)
        self.assertEqual([p.nummer for p in self.geloescht], [894])
        self.assertEqual(self.gesagt[-1], "Auftrag 894 gelöscht.")
        self.assertEqual(d.liste.count(), 2)

    def test_nein_bei_der_rueckfrage_loescht_nichts(self):
        from PySide6.QtCore import Qt
        d = self._bauen(self._drei(), antwort=False)
        d.liste.setCurrentRow(2)
        self._taste(d, Qt.Key_Delete)
        self.assertEqual(self.geloescht, [])
        self.assertEqual(d.liste.count(), 3)

    def test_leer_sagt_keine_wartenden_und_schliesst(self):
        d = self._bauen([])
        self.assertEqual(self.gesagt, ["Keine wartenden Aufträge."])
        self.assertEqual(d.result(), 1)


class Ruhezeit(unittest.TestCase):
    def test_ruhezeit_ist_drei_sekunden(self):
        self.assertEqual(einfueger.RUHE_FREMD_MS, 3000)
        self.assertEqual(einfueger.RUHE_IM_CHAT_MS, 3000)


if __name__ == "__main__":
    unittest.main()
