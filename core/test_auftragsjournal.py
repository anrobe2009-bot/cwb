"""
CWB - Code Workbench
Tests fuer das Auftragsjournal (core/auftragsjournal.py): Zeilenformat,
Warnungen (DOPPELT, KEIN UPLOAD, KEIN EINFUEGEN), Abfrage und dass ein Fehler
im Journal nie nach aussen dringt.

Aufruf: python -m unittest core.test_auftragsjournal -v
"""

import re
import tempfile
import time
import unittest
from pathlib import Path

try:
    from . import auftragsjournal as aj
    from . import einfueger
except ImportError:
    import auftragsjournal as aj
    import einfueger

ZEILE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \| [^|]+ \| [^|]+ \| [^|]+ \| [^|]+ \| [^|]+ \| .+$")


class JournalGrundTest(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.datei = Path(self.ordner.name) / "auftragsjournal.log"
        aj.zuruecksetzen()
        aj.einrichten(self.datei)
        self._fristen = (aj.UPLOAD_FRIST_S, aj.EINFUEGE_FRIST_S)
        aj.UPLOAD_FRIST_S = 0.05
        aj.EINFUEGE_FRIST_S = 0.05
        aj.projekt_setzen("CWB")

    def tearDown(self):
        aj.UPLOAD_FRIST_S, aj.EINFUEGE_FRIST_S = self._fristen
        aj.zuruecksetzen()
        for h in list(getattr(aj._schreiber, "handlers", [])):
            h.close()
        aj._schreiber = None
        self.ordner.cleanup()

    def zeilen(self) -> list[str]:
        for h in aj._schreiber.handlers:
            h.flush()
        return self.datei.read_text(encoding="utf-8").splitlines()


class FormatTest(JournalGrundTest):
    def test_zeilenformat_mit_sieben_spalten(self):
        aj.angenommen("bruecke", nummer=1234, block=56, art="code")
        aj.gestartet(nummer=1234, block=56, art="code", detail="modell=sonnet")
        zeilen = self.zeilen()
        self.assertEqual(len(zeilen), 2)
        for z in zeilen:
            self.assertRegex(z, ZEILE)
        teile = zeilen[1].split(" | ")
        self.assertEqual(teile[1:6], ["1234", "56", "CWB", "code", "gestartet"])

    def test_fehlende_werte_und_trennzeichen(self):
        aj.schreibe("fehler", "a | b\nc")
        teile = self.zeilen()[0].split(" | ")
        self.assertEqual(len(teile), 7)
        self.assertEqual(teile[1], "-")
        self.assertEqual(teile[6], "a / b c")

    def test_zeilen_ohne_nummer_gehoeren_zum_laufenden_auftrag(self):
        aj.gestartet(nummer=7, block=None, art="code")
        aj.ansage("beendet", "Fertig.")
        self.assertIn(" | 7 | ", self.zeilen()[1])


class WarnungTest(JournalGrundTest):
    def test_zweimal_angenommen_ist_doppelt(self):
        aj.angenommen("bruecke", nummer=5)
        aj.angenommen("bruecke", nummer=5)
        self.assertEqual(sum("WARNUNG" in z and "DOPPELT" in z for z in self.zeilen()), 1)

    def test_andere_quelle_ist_nicht_doppelt(self):
        aj.angenommen("bruecke", nummer=5)
        aj.angenommen("eingang", nummer=5)
        self.assertFalse(any("WARNUNG" in z for z in self.zeilen()))

    def test_zweimal_gestartet_ist_doppelt(self):
        aj.gestartet(nummer=9, art="code")
        aj.gestartet(nummer=9, art="code")
        self.assertTrue(any("WARNUNG" in z and "DOPPELT gestartet" in z for z in self.zeilen()))

    def test_ohne_nummer_keine_doppelt_warnung(self):
        aj.angenommen("eingabefeld")
        aj.angenommen("eingabefeld")
        self.assertFalse(any("WARNUNG" in z for z in self.zeilen()))

    def test_kein_upload_nach_abgeschlossen(self):
        aj.gestartet(nummer=3, art="code")
        aj.abgeschlossen(1.5, erwartet_upload=True)
        time.sleep(0.2)
        self.assertTrue(any("WARNUNG" in z and "KEIN UPLOAD" in z for z in self.zeilen()))

    def test_upload_vorhanden_keine_warnung(self):
        aj.gestartet(nummer=3, art="code")
        aj.abgeschlossen(1.5, erwartet_upload=True)
        aj.bericht_hochgeladen(1, nummer=3, art="code")
        aj.eingefuegt("Chat", True, aj.kennung(3, None, "code"))
        time.sleep(0.2)
        self.assertFalse(any("WARNUNG" in z for z in self.zeilen()))

    def test_kein_einfuegen_nach_hochgeladen_und_zustellbereit(self):
        aj.gestartet(nummer=4, art="code")
        aj.bericht_hochgeladen(1, nummer=4, art="code")
        aj.zustellbereit(nummer=4, art="code")
        time.sleep(0.2)
        self.assertTrue(any("WARNUNG" in z and "KEIN EINFUEGEN" in z for z in self.zeilen()))

    def test_frist_zaehlt_nicht_vor_zustellbereitschaft(self):
        aj.gestartet(nummer=5, art="code")
        aj.bericht_hochgeladen(1, nummer=5, art="code")
        time.sleep(0.2)
        self.assertFalse(any("KEIN EINFUEGEN" in z for z in self.zeilen()))

    def test_frist_beginnt_erst_mit_zustellbereitschaft(self):
        aj.EINFUEGE_FRIST_S = 0.3
        aj.gestartet(nummer=6, art="code")
        aj.bericht_hochgeladen(1, nummer=6, art="code")
        time.sleep(0.4)
        aj.zustellbereit(nummer=6, art="code")
        time.sleep(0.15)
        self.assertFalse(any("KEIN EINFUEGEN" in z for z in self.zeilen()))
        aj.eingefuegt("Chat", True, aj.kennung(6, None, "code"))
        time.sleep(0.4)
        self.assertFalse(any("WARNUNG" in z for z in self.zeilen()))

    def test_eingefuegt_vor_ablauf_keine_warnung(self):
        aj.EINFUEGE_FRIST_S = 0.3
        aj.gestartet(nummer=7, art="code")
        aj.zustellbereit(nummer=7, art="code")
        aj.bericht_hochgeladen(1, nummer=7, art="code")
        time.sleep(0.1)
        aj.eingefuegt("Chat", True, aj.kennung(7, None, "code"))
        time.sleep(0.5)
        self.assertFalse(any("WARNUNG" in z for z in self.zeilen()))

    def test_standardfristen(self):
        self.assertEqual(self._fristen, (60.0, 60.0))


class AbfrageTest(JournalGrundTest):
    def vollstaendig(self, nummer, enter=True):
        aj.angenommen("bruecke", nummer=nummer, art="code")
        aj.gestartet(nummer=nummer, art="code")
        aj.abgeschlossen(12.3, erwartet_upload=True)
        aj.bericht_hochgeladen(1, nummer=nummer, art="code")
        aj.eingefuegt("Claude Chat", enter, aj.kennung(nummer, None, "code"))
        aj.ansage("gestartet", "Fertig.")
        aj.ansage("beendet", "Fertig.")

    def test_letzte_fasst_je_auftrag_zusammen(self):
        self.vollstaendig(10)
        self.vollstaendig(11, enter=False)
        text = aj.letzte(1, self.datei)
        self.assertIn("Auftrag 11", text)
        self.assertNotIn("Auftrag 10", text)
        self.assertIn("eingefuegt ja ohne Enter", text)
        self.assertIn("Ansage ok", text)
        self.assertIn("hochgeladen ja", text)
        self.assertIn("Dauer 12.3 Sekunden", text)
        self.assertNotIn("|", text)

    def test_letzte_zeigt_warnungen(self):
        aj.angenommen("bruecke", nummer=8)
        aj.angenommen("bruecke", nummer=8)
        text = aj.letzte(5, self.datei)
        self.assertIn("angenommen 2", text)
        self.assertIn("Warnungen 1", text)
        self.assertIn("DOPPELT", text)

    def test_auftrag_gibt_alle_zeilen(self):
        self.vollstaendig(20)
        self.vollstaendig(21)
        text = aj.auftrag("20", self.datei)
        self.assertEqual(len(text.splitlines()), 7)
        self.assertNotIn("|", text)
        self.assertIn("eingefuegt", text)

    def test_unbekannter_auftrag(self):
        self.assertIn("nicht im Journal", aj.auftrag("999", self.datei))

    def test_kommandozeile(self):
        self.vollstaendig(30)
        self.assertEqual(aj.main(["--letzte", "1", "--datei", str(self.datei)]), 0)
        self.assertEqual(aj.main(["--auftrag", "30", "--datei", str(self.datei)]), 0)


class ZaehlungUndProjektTest(JournalGrundTest):
    def test_auftraege_ohne_nummer_werden_getrennt_gezaehlt(self):
        for _ in range(2):
            aj.angenommen("kachel", art="bild")
            aj.gestartet(art="bild")
            aj.abgeschlossen(0.6)
        text = aj.letzte(5, self.datei)
        self.assertEqual(text.count("Auftrag -"), 2)
        self.assertNotIn("angenommen 0", text)
        self.assertNotIn("gestartet 2", text)

    def test_bild_ohne_annahme_zeigt_null_nur_wenn_wirklich_keine(self):
        aj.gestartet(art="bild")
        self.assertIn("angenommen 0, gestartet 1", aj.letzte(1, self.datei))

    def test_projekt_kommt_vom_start_nicht_von_der_annahme(self):
        aj.projekt_setzen("CWB")
        aj.angenommen("bruecke", nummer=39, art="code")
        aj.projekt_setzen("hausgemacht")
        aj.gestartet(nummer=39, art="code")
        self.assertIn("Projekt hausgemacht", aj.letzte(1, self.datei))

    def test_spaete_zeilen_tragen_das_projekt_des_auftrags(self):
        aj.projekt_setzen("hausgemacht")
        aj.gestartet(nummer=41, art="code")
        aj.projekt_setzen("CWB")
        aj.bericht_hochgeladen(1, nummer=41, art="code")
        letzte = self.zeilen()[-1]
        self.assertIn("| hausgemacht |", letzte)


class FehlerStoertNichtTest(JournalGrundTest):
    def test_kaputter_schreiber_wirft_nie(self):
        class Kaputt:
            def info(self, *_):
                raise OSError("Platte voll")
        aj._schreiber = Kaputt()
        aj.angenommen("bruecke", nummer=1)
        aj.gestartet(nummer=1)
        aj.schreibe("werkzeug", "anzahl=3")
        aj.abgeschlossen(1.0, erwartet_upload=True)
        aj.bericht_hochgeladen(1, nummer=1)
        aj.eingefuegt("x", True)
        aj.ansage("beendet", "x")
        aj.projekt_setzen(None)

    def test_nicht_beschreibbarer_ort_wirft_nie(self):
        aj.zuruecksetzen()
        aj._schreiber = None
        aj._datei = Path("/gibt/es/nicht/journal.log")
        aj.JOURNAL_DATEI, alt = Path("/gibt/es/nicht/journal.log"), aj.JOURNAL_DATEI
        try:
            aj.schreibe("gestartet", "x")
            aj.angenommen("bruecke", nummer=2)
        finally:
            aj.JOURNAL_DATEI = alt

    def test_abfrage_ohne_datei(self):
        self.assertIn("Keine Auftraege", aj.letzte(3, Path(self.ordner.name) / "fehlt.log"))


class EinfuegerJournalTest(JournalGrundTest):
    class Werkzeug:
        def fenster_lesen(self, kennung=None):
            return ("1", "Claude Chat im Browser", "firefox")
        def aktivieren(self, kennung):
            return True
        def taste(self, name):
            return True

    class Ablage:
        def setzen(self, text):
            return True
        def lesen(self):
            return ""
        def leeren(self):
            pass

    def test_eingefuegt_traegt_die_nummer_des_auftrags(self):
        geplant = []
        e = einfueger.Einfueger(self.Werkzeug(), self.Ablage(),
                                lambda ms, f: geplant.append(f), lambda: True,
                                lambda erfolge, gescheitert: None)
        e.naechste_kennung = aj.kennung(77, None, "code")
        e.hinzufuegen(("1", "Claude Chat im Browser", "firefox"), "Bericht")
        while geplant:
            geplant.pop(0)()
        zeilen = [z for z in self.zeilen() if " | eingefuegt | " in z]
        self.assertEqual(len(zeilen), 1)
        self.assertIn(" | 77 | ", zeilen[0])
        self.assertIn("enter=", zeilen[0])

    def test_gescheitertes_einfuegen_meldet_ablage(self):
        e = einfueger.Einfueger(self.Werkzeug(), self.Ablage(),
                                lambda ms, f: f(), lambda: True,
                                lambda erfolge, gescheitert: None)
        e.naechste_kennung = aj.kennung(78, None, "code")
        e.hinzufuegen(None, "Bericht")
        zeilen = [z for z in self.zeilen() if "ablage_zwischenablage" in z]
        self.assertEqual(len(zeilen), 1)
        self.assertIn(" | 78 | ", zeilen[0])


if __name__ == "__main__":
    unittest.main()
