"""
CWB - Code Workbench
Unit-Tests fuer core/leitstand.py (Block 72, siehe wissen/plan_leitstand.md).

Laufen ohne echten Gemini-Aufruf: requests.post wird durch nachgebildete
Antworten ersetzt (unittest.mock). Der Thread EntscheidungsFaden selbst wird
nicht gestartet (keine Qt-Ereignisschleife in Tests, siehe
core/test_bruecke.py) - getestet werden die reinen Funktionen direkt.

Aufruf: python -m unittest core.test_leitstand -v
        (oder, aus dem Ordner core/: python test_leitstand.py -v)
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

try:
    from . import leitstand
except ImportError:
    import leitstand


def _antwort(status=200, text=None, kaputt=False) -> mock.Mock:
    antwort = mock.Mock(spec=requests.Response)
    antwort.status_code = status
    if status >= 400:
        antwort.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    else:
        antwort.raise_for_status.return_value = None
    if kaputt:
        antwort.json.side_effect = ValueError("kein JSON")
    else:
        antwort.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": text}]}}],
        }
    return antwort


class EntscheidungAbfragenTest(unittest.TestCase):

    def _antworten_mit(self, text: str):
        return mock.patch("requests.post", return_value=_antwort(text=text))

    def test_weiter(self):
        gueltig = json.dumps({
            "entscheidung": "weiter", "schritt": 2,
            "auftrag": "Mach Schritt 2.", "grund": "Schritt 1 lief sauber durch.",
        })
        with self._antworten_mit(gueltig):
            e = leitstand.entscheidung_abfragen("schluessel", "Plan", "Offen", "Bericht", 10)
        self.assertEqual(e.entscheidung, "weiter")
        self.assertEqual(e.schritt, 2)
        self.assertEqual(e.auftrag, "Mach Schritt 2.")

    def test_wiederholen(self):
        gueltig = json.dumps({
            "entscheidung": "wiederholen", "schritt": 3,
            "auftrag": "Versuch Schritt 3 erneut, diesmal mit X.", "grund": "Test schlug fehl.",
        })
        with self._antworten_mit(gueltig):
            e = leitstand.entscheidung_abfragen("schluessel", "Plan", "Offen", "Bericht", 10)
        self.assertEqual(e.entscheidung, "wiederholen")
        self.assertEqual(e.schritt, 3)

    def test_stopp(self):
        gueltig = json.dumps({
            "entscheidung": "stopp", "schritt": 4,
            "auftrag": "", "grund": "Plan ist erledigt.",
        })
        with self._antworten_mit(gueltig):
            e = leitstand.entscheidung_abfragen("schluessel", "Plan", "Offen", "Bericht", 10)
        self.assertEqual(e.entscheidung, "stopp")
        self.assertEqual(e.grund, "Plan ist erledigt.")

    def test_kaputtes_json(self):
        with self._antworten_mit("das ist kein JSON{{{"):
            with self.assertRaises(leitstand.LeitstandAntwortFehler):
                leitstand.entscheidung_abfragen("schluessel", "Plan", "Offen", "Bericht", 10)

    def test_ungueltige_entscheidung(self):
        text = json.dumps({"entscheidung": "vielleicht", "schritt": 1,
                            "auftrag": "x", "grund": "x"})
        with self._antworten_mit(text):
            with self.assertRaises(leitstand.LeitstandAntwortFehler):
                leitstand.entscheidung_abfragen("schluessel", "Plan", "Offen", "Bericht", 10)

    def test_fehlender_auftragstext_ausser_bei_stopp(self):
        text = json.dumps({"entscheidung": "weiter", "schritt": 1, "auftrag": "", "grund": "x"})
        with self._antworten_mit(text):
            with self.assertRaises(leitstand.LeitstandAntwortFehler):
                leitstand.entscheidung_abfragen("schluessel", "Plan", "Offen", "Bericht", 10)

    def test_zeitueberschreitung(self):
        with mock.patch("requests.post", side_effect=requests.Timeout("zu lang")):
            with self.assertRaises(leitstand.LeitstandNetzFehler):
                leitstand.entscheidung_abfragen("schluessel", "Plan", "Offen", "Bericht", 10)

    def test_verbindungsfehler(self):
        with mock.patch("requests.post", side_effect=requests.ConnectionError("weg")):
            with self.assertRaises(leitstand.LeitstandNetzFehler):
                leitstand.entscheidung_abfragen("schluessel", "Plan", "Offen", "Bericht", 10)

    def test_http_fehlerstatus(self):
        with mock.patch("requests.post", return_value=_antwort(status=403)):
            with self.assertRaises(leitstand.LeitstandNetzFehler):
                leitstand.entscheidung_abfragen("schluessel", "Plan", "Offen", "Bericht", 10)

    def test_antwort_ohne_verwertbaren_text(self):
        kaputt = mock.Mock(spec=requests.Response)
        kaputt.status_code = 200
        kaputt.raise_for_status.return_value = None
        kaputt.json.return_value = {"candidates": []}
        with mock.patch("requests.post", return_value=kaputt):
            with self.assertRaises(leitstand.LeitstandAntwortFehler):
                leitstand.entscheidung_abfragen("schluessel", "Plan", "Offen", "Bericht", 10)

    def test_schluessel_steht_nie_im_log_oder_im_fehlertext(self):
        with mock.patch("requests.post",
                         side_effect=requests.ConnectionError("https://x/?key=GEHEIM123")):
            try:
                leitstand.entscheidung_abfragen("GEHEIM123", "Plan", "Offen", "Bericht", 10)
            except leitstand.LeitstandNetzFehler as fehler:
                self.assertNotIn("GEHEIM123", str(fehler))


class VerbindungstestTest(unittest.TestCase):

    def test_antwort_ok(self):
        with mock.patch("requests.post", return_value=_antwort(text="OK")):
            self.assertEqual(leitstand.verbindungstest("schluessel"), "OK")


class MarkierungVerbotenTest(unittest.TestCase):

    def test_erkennt_run(self):
        self.assertEqual(leitstand.markierung_verboten("Bitte #RUN# dir -r"), "#RUN#")

    def test_erkennt_admin(self):
        self.assertEqual(leitstand.markierung_verboten("#ADMIN#\nnet user"), "#ADMIN#")

    def test_erkennt_bild(self):
        self.assertEqual(leitstand.markierung_verboten("mach #BILD#"), "#BILD#")

    def test_harmloser_text(self):
        self.assertIsNone(leitstand.markierung_verboten("Baue die Funktion aus."))


class CodeblockBauenTest(unittest.TestCase):

    def test_form(self):
        block = leitstand.codeblock_bauen("CWB", 7, "Tu etwas Sinnvolles.")
        zeilen = block.splitlines()
        self.assertEqual(zeilen[0], "#CODE#")
        self.assertEqual(zeilen[1], "Block 7")
        self.assertEqual(zeilen[2], "Projekt: CWB")
        self.assertIn("Tu etwas Sinnvolles.", block)
        self.assertEqual(zeilen[-1], "Ende Block 7")


class AenderungAusserhalbTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.projekt = Path(self._tmp.name) / "projekt"
        self.projekt.mkdir()

    def test_alles_innerhalb(self):
        self.assertIsNone(leitstand.aenderung_ausserhalb(
            self.projekt, ["core/fenster.py", "wissen/offen.md"]))

    def test_absoluter_pfad_ausserhalb(self):
        ausserhalb = str(Path(self._tmp.name) / "woanders" / "x.py")
        self.assertEqual(
            leitstand.aenderung_ausserhalb(self.projekt, ["core/fenster.py", ausserhalb]),
            ausserhalb,
        )

    def test_relativer_pfad_mit_elternverweis_ausserhalb(self):
        treffer = leitstand.aenderung_ausserhalb(self.projekt, ["../ausserhalb.py"])
        self.assertEqual(treffer, "../ausserhalb.py")


class ZustandTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._datei = Path(self._tmp.name) / "leitstand_zustand.json"
        self._patch = mock.patch.object(leitstand, "LEITSTAND_ZUSTAND_DATEI", self._datei)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_leer_ohne_datei(self):
        zustand = leitstand.zustand_lesen()
        self.assertEqual(zustand.anzahl_auftraege, 0)
        self.assertEqual(zustand.fehlschlaege_in_folge, 0)

    def test_schreiben_und_lesen_rundtrip(self):
        zustand = leitstand.zustand_lesen()
        zustand.anzahl_auftraege = 3
        leitstand.wiederholung_erhoehen(zustand, "CWB", 5)
        leitstand.zustand_schreiben(zustand)
        erneut = leitstand.zustand_lesen()
        self.assertEqual(erneut.anzahl_auftraege, 3)
        self.assertEqual(leitstand.wiederholung_lesen(erneut, "CWB", 5), 1)

    def test_neuer_tag_setzt_zurueck(self):
        zustand = leitstand.zustand_lesen()
        zustand.anzahl_auftraege = 9
        zustand.datum = "2000-01-01"
        leitstand.zustand_schreiben(zustand)
        frisch = leitstand.zustand_lesen()
        self.assertEqual(frisch.anzahl_auftraege, 0)

    def test_angehalten_roundtrip(self):
        zustand = leitstand.zustand_lesen()
        self.assertFalse(leitstand.ist_angehalten(zustand, "CWB", 123.0))
        leitstand.anhalten_merken(zustand, "CWB", 123.0)
        self.assertTrue(leitstand.ist_angehalten(zustand, "CWB", 123.0))
        self.assertFalse(leitstand.ist_angehalten(zustand, "CWB", 456.0))

    def test_wiederholung_grenze(self):
        zustand = leitstand.zustand_lesen()
        self.assertEqual(leitstand.wiederholung_erhoehen(zustand, "CWB", 1), 1)
        self.assertEqual(leitstand.wiederholung_erhoehen(zustand, "CWB", 1), 2)
        self.assertEqual(leitstand.wiederholung_lesen(zustand, "CWB", 2), 0)

    def test_verlauf_anhaengen_und_leeren(self):
        zustand = leitstand.zustand_lesen()
        leitstand.verlauf_anhaengen(zustand, "CWB", 1, "Fertig.")
        self.assertEqual(len(leitstand.verlauf_abholen(zustand, "CWB")), 1)
        leitstand.verlauf_leeren(zustand, "CWB")
        self.assertEqual(leitstand.verlauf_abholen(zustand, "CWB"), [])


class NachtberichtBauenTest(unittest.TestCase):

    def test_enthaelt_haltgrund_und_schritte(self):
        verlauf = [{"zeit": "03:10", "schritt": 2, "satz": "Fertig, 1 Datei geändert."}]
        text = leitstand.nachtbericht_bauen("CWB", verlauf, "Plan erledigt.")
        self.assertIn("# Nachtbericht", text)
        self.assertIn("Schritt 2", text)
        self.assertIn("Fertig, 1 Datei geändert.", text)
        self.assertIn("Plan erledigt.", text)

    def test_ohne_verlauf(self):
        text = leitstand.nachtbericht_bauen("CWB", [], "Kein Gemini-Schlüssel hinterlegt.")
        self.assertIn("kein Schritt gelaufen", text)


class ApiSchluesselLesenTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._datei = Path(self._tmp.name) / "leitstand_zugang.txt"
        self._patch = mock.patch.object(leitstand, "LEITSTAND_ZUGANG_DATEI", self._datei)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_fehlende_datei(self):
        self.assertIsNone(leitstand.api_schluessel_lesen())

    def test_vorhandenes_feld(self):
        self._datei.write_text("gemini_api_key=abc123\n", encoding="utf-8")
        self.assertEqual(leitstand.api_schluessel_lesen(), "abc123")

    def test_fehlendes_feld(self):
        self._datei.write_text("etwas_anderes=x\n", encoding="utf-8")
        self.assertIsNone(leitstand.api_schluessel_lesen())


class GrenzenWerteTest(unittest.TestCase):

    def test_vorgaben_ohne_einstellungen(self):
        with mock.patch.object(leitstand, "einstellungen_lesen", return_value={}):
            self.assertEqual(leitstand.max_auftraege_pro_nacht(),
                              leitstand.STANDARD_MAX_AUFTRAEGE_PRO_NACHT)
            self.assertEqual(leitstand.max_wiederholungen_je_schritt(),
                              leitstand.STANDARD_MAX_WIEDERHOLUNGEN_JE_SCHRITT)
            self.assertEqual(leitstand.zeitlimit_sekunden(),
                              leitstand.STANDARD_ZEITLIMIT_SEKUNDEN)
            self.assertFalse(leitstand.aktiv())

    def test_eigene_werte(self):
        with mock.patch.object(leitstand, "einstellungen_lesen", return_value={
            "leitstand_aktiv": True, "leitstand_max_auftraege": 5,
            "leitstand_max_wiederholungen": 1, "leitstand_zeitlimit_sekunden": 15,
        }):
            self.assertTrue(leitstand.aktiv())
            self.assertEqual(leitstand.max_auftraege_pro_nacht(), 5)
            self.assertEqual(leitstand.max_wiederholungen_je_schritt(), 1)
            self.assertEqual(leitstand.zeitlimit_sekunden(), 15)


if __name__ == "__main__":
    unittest.main()
