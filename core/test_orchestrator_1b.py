"""
CWB - Code Workbench
Tests fuer den Orchestrator, Etappe 1B (Berichte direkt an den Orchestrator,
Warteschlange, Kontingent, Schleifenschutz, F8/Strg+F4):

- Meldung bauen und Kontingent-Zeile mit und ohne Werte,
- Zustellung bei Schalter an und aus, Bruecken-Auftraege werden nicht zugestellt,
- mehrere Meldungen werden als EINE Nachricht gesammelt,
- Roberts Text hat Vorrang, waehrend einer Rueckfrage laeuft nichts weiter,
- Wiederherstellung nach Neustart, keine Doppelzustellung,
- Schleifenzaehler und Rueckfrage,
- F8 stoppt nur die vordere Sitzung, Strg+F4 fragt.

Aufruf: python -m unittest core.test_orchestrator_1b -v
"""

import asyncio
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

try:
    from . import eingangsordner, fenster, kontingent, orchestrator, orchestrator_ansicht
    from .sicherheit import Projekt
except ImportError:
    import eingangsordner
    import fenster
    import kontingent
    import orchestrator
    import orchestrator_ansicht
    from sicherheit import Projekt


ZUSTAND_MIT = {"stufe": "normal", "text": "x", "woche_prozent": 80,
               "woche_anzeige": "Woche 80 % · zurück Do 11:00",
               "sitzung_anzeige": "Sitzung 40 % · zurück 14:00"}
ZUSTAND_GROB = {"stufe": "normal", "text": "x", "woche_prozent": None,
                "woche_anzeige": "Woche: unter Warnschwelle", "sitzung_anzeige": None}


class _Temp(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.wurzel = Path(self._temp.name)
        self.orch = self.wurzel / "orchestrator"
        self.eingang = self.wurzel / "eingang"
        for p in (mock.patch.object(orchestrator, "ORCH_ORDNER", self.orch),
                  mock.patch.object(eingangsordner, "EINGANG_ORDNER", self.eingang),
                  mock.patch.object(kontingent, "DATEI", self.wurzel / "kontingent.json")):
            p.start()
            self.addCleanup(p.stop)
        eingangsordner.sicherstellen()
        orchestrator.SCHLEIFE.zuruecksetzen()
        self.addCleanup(orchestrator.SCHLEIFE.zuruecksetzen)


class KontingentTest(unittest.TestCase):
    def test_zeile_mit_prozentwerten(self):
        zeile = orchestrator.kontingent_zeile(ZUSTAND_MIT)
        self.assertIn("Woche 80 %", zeile)
        self.assertIn("Sitzung 40 %", zeile)
        self.assertTrue(zeile.startswith("Kontingent:"))

    def test_zeile_nur_mit_grober_stufe(self):
        zeile = orchestrator.kontingent_zeile(ZUSTAND_GROB)
        self.assertIn("unter Warnschwelle", zeile)
        self.assertIn("Sitzung noch nicht gemeldet", zeile)
        self.assertNotIn("%", zeile)

    def test_zeile_ohne_werte(self):
        self.assertIn("noch nicht gemeldet", orchestrator.kontingent_zeile(None))
        self.assertIn("noch nicht gemeldet", orchestrator.kontingent_zeile({}))

    def test_waehlen_nimmt_den_mit_echten_werten(self):
        self.assertIs(orchestrator.kontingent_waehlen(ZUSTAND_GROB, ZUSTAND_MIT), ZUSTAND_MIT)
        self.assertIs(orchestrator.kontingent_waehlen(ZUSTAND_GROB, None), ZUSTAND_GROB)
        self.assertIsNone(orchestrator.kontingent_waehlen(None, {}))

    def test_meldung_hat_kopfzeile_bericht_und_kontingent(self):
        text = orchestrator.meldung_bauen(
            1000007, 12, "fertig", "Auftrag 1000007 | Block 12 | Zeit T\nAlles gut",
            orchestrator.kontingent_zeile(ZUSTAND_MIT))
        zeilen = text.splitlines()
        self.assertEqual(zeilen[0], "[CWB-MELDUNG] Auftrag 1000007 | Block 12 | fertig")
        self.assertIn("Alles gut", text)
        self.assertTrue(zeilen[-1].startswith("Kontingent: Woche 80 %"))

    def test_meldung_ohne_block_und_status_fehler(self):
        text = orchestrator.meldung_bauen(5, None, "Fehler", "kaputt")
        self.assertEqual(text.splitlines()[0], "[CWB-MELDUNG] Auftrag 5 | Block - | Fehler")
        self.assertNotIn("Kontingent", text)


class MeldungAusgabeTest(_Temp):
    """Die Meldung traegt die Ausgabe des Auftrags (gekuerzt mit Hinweiszeile)."""

    def test_kurze_ausgabe_steht_ungekuerzt_in_der_meldung(self):
        text = orchestrator.meldung_bauen(7, 3, "fertig", "Terminalausgabe:\nzeile eins", art="RUN")
        self.assertIn("zeile eins", text)
        self.assertNotIn(orchestrator.GEKUERZT_ZEILE, text)

    def test_lange_run_ausgabe_wird_auf_40_zeilen_gekuerzt_mit_hinweis(self):
        roh = "\n".join(f"z{i}" for i in range(100))
        text = orchestrator.meldung_bauen(7, 3, "fertig", roh, art="RUN")
        self.assertIn("z39", text)
        self.assertNotIn("z40", text)
        self.assertEqual(text.splitlines()[-1], "[gekuerzt, voller Bericht per bericht_holen]")

    def test_lange_code_antwort_wird_auf_2000_zeichen_gekuerzt(self):
        text = orchestrator.meldung_bauen(7, 3, "fertig", "a" * 5000, art="CODE")
        zeilen = text.splitlines()
        self.assertEqual(zeilen[1], "a" * 2000)
        self.assertEqual(zeilen[-1], orchestrator.GEKUERZT_ZEILE)

    def test_kennzeile_zaehlt_nicht_zur_ausgabe(self):
        roh = "Auftrag 7 | Block 3 | Zeit T\n" + "\n".join(f"z{i}" for i in range(40))
        text = orchestrator.meldung_bauen(7, 3, "fertig", roh, art="RUN")
        self.assertNotIn(orchestrator.GEKUERZT_ZEILE, text)

    def test_fehlender_bericht_wird_benannt(self):
        for leer in (None, "", "  \n"):
            text = orchestrator.meldung_bauen(7, 3, "fertig", leer, art="RUN")
            self.assertIn("Bericht noch nicht verfuegbar", text)

    def test_systemtext_enthaelt_die_regel(self):
        self.assertIn("Ausgabe nicht gelesen.", orchestrator.REGEL_AUSGABE)
        quelle = Path(orchestrator_ansicht.__file__).read_text(encoding="utf-8")
        self.assertIn("orchestrator.REGEL_AUSGABE", quelle)


class SchlangeTest(_Temp):
    def test_sammeln_ergibt_eine_nachricht(self):
        s = orchestrator.Eingangsschlange()
        s.vormerken(1, "[CWB-MELDUNG] Auftrag 1")
        s.vormerken(2, "[CWB-MELDUNG] Auftrag 2")
        text = s.entnehmen()
        self.assertIn("Auftrag 1", text)
        self.assertIn("Auftrag 2", text)
        self.assertEqual(s.anzahl(), 0)
        self.assertEqual(s.entnehmen(), "")

    def test_nummer_nie_doppelt(self):
        s = orchestrator.Eingangsschlange()
        self.assertTrue(s.vormerken(1, "a"))
        self.assertFalse(s.vormerken(1, "a"))          # wartend
        s.entnehmen()
        self.assertFalse(s.vormerken(1, "a"))          # unterwegs
        s.quittieren()
        self.assertFalse(s.vormerken(1, "a"))          # zugestellt
        self.assertEqual(s.anzahl(), 0)

    def test_wiederherstellung_nach_neustart(self):
        s = orchestrator.Eingangsschlange()
        s.vormerken(1, "eins")
        s.vormerken(2, "zwei")
        s.entnehmen()                                    # 1+2 unterwegs, Absturz
        s.vormerken(3, "drei")
        neu = orchestrator.Eingangsschlange()            # neuer Prozess liest die Platte
        text = neu.entnehmen()
        self.assertLess(text.index("eins"), text.index("zwei"))
        self.assertLess(text.index("zwei"), text.index("drei"))

    def test_zugestelltes_kommt_nach_neustart_nicht_wieder(self):
        s = orchestrator.Eingangsschlange()
        s.vormerken(1, "eins")
        s.entnehmen()
        s.quittieren()
        neu = orchestrator.Eingangsschlange()
        self.assertFalse(neu.vormerken(1, "eins"))
        self.assertEqual(neu.anzahl(), 0)

    def test_zurueckstellen_legt_vorn_ein(self):
        s = orchestrator.Eingangsschlange()
        s.vormerken(1, "eins")
        s.entnehmen()
        s.vormerken(2, "zwei")
        s.zurueckstellen()
        text = s.entnehmen()
        self.assertLess(text.index("eins"), text.index("zwei"))

    def test_kaputte_datei_wirft_nicht(self):
        self.orch.mkdir(parents=True, exist_ok=True)
        orchestrator.eingang_datei().write_text("{kaputt", encoding="utf-8")
        s = orchestrator.Eingangsschlange()
        self.assertEqual(s.anzahl(), 0)
        self.assertTrue(s.vormerken(1, "x"))
        json.loads(orchestrator.eingang_datei().read_text(encoding="utf-8"))


class SchleifeTest(_Temp):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(orchestrator, "einstellungen_lesen",
                              return_value={"orchestrator_schleife_max": 3})
        p.start()
        self.addCleanup(p.stop)

    def test_standard_ist_zwoelf(self):
        with mock.patch.object(orchestrator, "einstellungen_lesen", return_value={}):
            self.assertEqual(orchestrator.schleife_max(), 12)
        with mock.patch.object(orchestrator, "einstellungen_lesen",
                               return_value={"orchestrator_schleife_max": "x"}):
            self.assertEqual(orchestrator.schleife_max(), 12)

    def test_senden_zaehlt_hoch(self):
        for _ in range(2):
            self.assertTrue(orchestrator.auftrag_senden("RUN", "Test", "echo", ["Test"])["ok"])
        self.assertEqual(orchestrator.SCHLEIFE.zaehler, 2)
        self.assertFalse(orchestrator.SCHLEIFE.erreicht())
        orchestrator.auftrag_senden("RUN", "Test", "echo", ["Test"])
        self.assertTrue(orchestrator.SCHLEIFE.erreicht())

    def test_abgelehnter_auftrag_zaehlt_nicht(self):
        orchestrator.auftrag_senden("RUN", "Unbekannt", "echo", ["Test"])
        self.assertEqual(orchestrator.SCHLEIFE.zaehler, 0)

    def test_grenze_fragt_und_nein_haelt_an(self):
        for _ in range(3):
            orchestrator.SCHLEIFE.erhoehen()
        frage = mock.AsyncMock(return_value=False)
        antwort = asyncio.run(orchestrator.schleife_pruefen(frage))
        frage.assert_awaited_once()
        self.assertIn("nicht freigegeben", antwort)
        self.assertTrue(orchestrator.SCHLEIFE.erreicht())

    def test_grenze_fragt_und_ja_setzt_zurueck(self):
        for _ in range(3):
            orchestrator.SCHLEIFE.erhoehen()
        frage = mock.AsyncMock(return_value=True)
        self.assertIsNone(asyncio.run(orchestrator.schleife_pruefen(frage)))
        self.assertEqual(orchestrator.SCHLEIFE.zaehler, 0)

    def test_unter_der_grenze_wird_nicht_gefragt(self):
        frage = mock.AsyncMock(return_value=True)
        self.assertIsNone(asyncio.run(orchestrator.schleife_pruefen(frage)))
        frage.assert_not_awaited()

    def test_ohne_rueckfrageweg_wird_verweigert(self):
        for _ in range(3):
            orchestrator.SCHLEIFE.erhoehen()
        self.assertIn("Schleifenschutz", asyncio.run(orchestrator.schleife_pruefen(None)))


def _ansicht(test, schlange=None):
    a = orchestrator_ansicht.OrchestratorAnsicht(
        Projekt("Test", Path(tempfile.gettempdir()), False), mock.MagicMock(),
        schlange=schlange)
    test.addCleanup(a.deleteLater)
    faden = mock.MagicMock()
    faden.isRunning.return_value = True
    faden.faden_beschaeftigt = False
    a.faden = faden
    return a, faden


class AnsichtZustellungTest(_Temp):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])

    def test_meldung_geht_sofort_an_die_sitzung(self):
        a, faden = _ansicht(self)
        self.assertTrue(a.meldung_annehmen(1000001, "[CWB-MELDUNG] Auftrag 1000001 | x"))
        faden.auftrag_geben.assert_called_once()
        self.assertIn("1000001", faden.auftrag_geben.call_args.args[0])
        self.assertEqual(a.schlange.anzahl(), 0)

    def test_mehrere_meldungen_waehrend_antwort_werden_eine_nachricht(self):
        a, faden = _ansicht(self)
        a.meldung_annehmen(1, "[CWB-MELDUNG] Auftrag 1")
        faden.auftrag_geben.reset_mock()
        a.meldung_annehmen(2, "[CWB-MELDUNG] Auftrag 2")        # Sitzung arbeitet noch
        a.meldung_annehmen(3, "[CWB-MELDUNG] Auftrag 3")
        faden.auftrag_geben.assert_not_called()
        self.assertEqual(a.schlange.anzahl(), 2)
        a._fertig({"antwort": "ok", "fehler": ""})             # erste Antwort fertig
        faden.auftrag_geben.assert_called_once()
        text = faden.auftrag_geben.call_args.args[0]
        self.assertIn("Auftrag 2", text)
        self.assertIn("Auftrag 3", text)

    def test_doppelte_nummer_wird_nicht_zweimal_zugestellt(self):
        a, faden = _ansicht(self)
        a.meldung_annehmen(1, "[CWB-MELDUNG] Auftrag 1")
        a._fertig({"antwort": "ok", "fehler": ""})
        faden.auftrag_geben.reset_mock()
        self.assertFalse(a.meldung_annehmen(1, "[CWB-MELDUNG] Auftrag 1"))
        faden.auftrag_geben.assert_not_called()

    def test_roberts_text_hat_vorrang(self):
        a, faden = _ansicht(self)
        a.eingabe.setPlainText("Robert schreibt")
        a.senden()                                              # Sitzung arbeitet an Roberts Text
        faden.auftrag_geben.reset_mock()
        a.meldung_annehmen(1, "[CWB-MELDUNG] Auftrag 1")
        faden.auftrag_geben.assert_not_called()                 # Meldung wartet
        a._fertig({"antwort": "ok", "fehler": ""})
        self.assertIn("Auftrag 1", faden.auftrag_geben.call_args.args[0])

    def test_waehrend_einer_rueckfrage_laeuft_nichts_weiter(self):
        a, faden = _ansicht(self)
        a._frage("Darf ich?", "Darf ich?")
        a.meldung_annehmen(1, "[CWB-MELDUNG] Auftrag 1")
        faden.auftrag_geben.assert_not_called()
        self.assertEqual(a.schlange.anzahl(), 1)
        a.frage_beantworten(True)
        faden.auftrag_geben.assert_not_called()                 # Sitzung ist ja noch dran
        a._offen = 0
        a.zustellen()
        faden.auftrag_geben.assert_called_once()

    def test_frage_ist_sichtbar_und_wird_gemeldet(self):
        a, _ = _ansicht(self)
        gemeldet = []
        a.frage_gestellt.connect(lambda satz, kurz: gemeldet.append(kurz))
        a._frage("Satz", "Kurz")
        self.assertIn("Eingabe = ja, Escape = nein", a.verlauf.toPlainText())
        self.assertEqual(gemeldet, ["Kurz"])

    def test_fehler_stellt_zurueck_und_stellt_nicht_sofort_neu_zu(self):
        a, faden = _ansicht(self)
        a.meldung_annehmen(1, "[CWB-MELDUNG] Auftrag 1")
        faden.auftrag_geben.reset_mock()
        a._fertig({"antwort": "", "fehler": "kaputt"})
        faden.auftrag_geben.assert_not_called()
        self.assertEqual(a.schlange.anzahl(), 1)

    def test_absturz_haelt_meldung_fest_und_neustart_stellt_zu(self):
        a, faden = _ansicht(self)
        a.meldung_annehmen(1, "[CWB-MELDUNG] Auftrag 1")
        a._abgestuerzt("weg")
        self.assertEqual(a.schlange.anzahl(), 1)
        # neuer Prozess: neue Ansicht liest die Platte und stellt nach
        b, faden_b = _ansicht(self)
        self.assertEqual(b.schlange.anzahl(), 1)
        b.nachholen()
        self.assertIn("Auftrag 1", faden_b.auftrag_geben.call_args.args[0])

    def test_robert_text_setzt_schleifenzaehler_zurueck(self):
        a, _ = _ansicht(self)
        orchestrator.SCHLEIFE.erhoehen()
        a.eingabe.setPlainText("Weiter")
        a.senden()
        self.assertEqual(orchestrator.SCHLEIFE.zaehler, 0)

    def test_kontingent_wird_angezeigt(self):
        a, _ = _ansicht(self)
        a.kontingent_setzen(ZUSTAND_MIT)
        self.assertIn("Woche 80 %", a.kontingent.text())   # SDK-Wert ueberschreibt den Stand
        kontingent.DATEI.unlink()
        a.kontingent_setzen(None)
        self.assertIn("noch nicht gemeldet", a.kontingent.text())

    def test_stopp_stellt_zurueck_und_beruehrt_nur_eigenen_faden(self):
        a, faden = _ansicht(self)
        a.meldung_annehmen(1, "[CWB-MELDUNG] Auftrag 1")
        a.not_aus()
        self.assertEqual(a.schlange.anzahl(), 1)
        faden.not_aus.assert_called_once()

    def _nach_stopp_mit_liegengebliebener_meldung(self):
        a, faden = _ansicht(self)
        a.eingabe.setPlainText("Auftrag losschicken")
        a.senden()
        a.meldung_annehmen(7, "[CWB-MELDUNG] Auftrag 7 | Block - | fertig\nBericht")
        a.not_aus()                      # F8: Meldung bleibt liegen
        a._fertig({"antwort": "", "fehler": "", "abgebrochen": True})
        faden.auftrag_geben.reset_mock()
        return a, faden

    def test_weiter_nach_stopp_stellt_liegengebliebene_meldung_vor_den_text(self):
        a, faden = self._nach_stopp_mit_liegengebliebener_meldung()
        self.assertEqual(a.schlange.anzahl(), 1)
        a.eingabe.setPlainText("Weiter.")
        a.senden()
        faden.auftrag_geben.assert_called_once()
        text = faden.auftrag_geben.call_args.args[0]
        self.assertTrue(text.startswith("[CWB-MELDUNG] Auftrag 7"))
        self.assertTrue(text.endswith("Weiter."))
        self.assertEqual(a.schlange.anzahl(), 0)
        self.assertIn("[CWB-MELDUNG] Auftrag 7", a.verlauf.toPlainText())

    def test_meldung_vor_dem_text_wird_nur_einmal_quittiert(self):
        a, faden = self._nach_stopp_mit_liegengebliebener_meldung()
        a.eingabe.setPlainText("Weiter.")
        a.senden()
        a._fertig({"antwort": "ok", "fehler": ""})
        self.assertEqual(a.schlange.anzahl(), 0)
        self.assertEqual(a.schlange.unterwegs, [])
        self.assertIn("7", a.schlange.zugestellt)
        faden.auftrag_geben.reset_mock()
        a.eingabe.setPlainText("Noch was")
        a.senden()
        self.assertEqual(faden.auftrag_geben.call_args.args[0], "Noch was")

    def test_meldung_bleibt_wenn_sitzung_beschaeftigt(self):
        a, faden = _ansicht(self)
        a.eingabe.setPlainText("Erster")
        a.senden()                                              # Sitzung arbeitet
        a.meldung_annehmen(8, "[CWB-MELDUNG] Auftrag 8")
        faden.auftrag_geben.reset_mock()
        a.eingabe.setPlainText("Zweiter")
        a.senden()
        self.assertEqual(faden.auftrag_geben.call_args.args[0], "Zweiter")
        self.assertEqual(a.schlange.anzahl(), 1)

    def test_abbruch_des_textes_mit_meldung_stellt_meldung_zurueck(self):
        a, faden = self._nach_stopp_mit_liegengebliebener_meldung()
        a.eingabe.setPlainText("Weiter.")
        a.senden()
        a._fertig({"antwort": "", "fehler": "", "abgebrochen": True})
        self.assertEqual(a.schlange.anzahl(), 1)
        self.assertNotIn("7", a.schlange.zugestellt)


class VerlaufDateiTest(_Temp):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])

    def test_neue_eingabe_leert_nur_die_anzeige(self):
        a, faden = _ansicht(self)
        a.eingabe.setPlainText("Erste")
        a.senden()
        a._text("Antwort eins")
        a.eingabe.setPlainText("Zweite")
        a.senden()
        anzeige = a.verlauf.toPlainText()
        self.assertIn("Zweite", anzeige)
        self.assertNotIn("Erste", anzeige)
        self.assertNotIn("Antwort eins", anzeige)
        a._text("Antwort zwei")
        self.assertIn("Antwort zwei", a.verlauf.toPlainText())

    def test_leeren_spricht_nichts_und_beruehrt_die_sitzung_nicht(self):
        a, faden = _ansicht(self)
        a.eingabe.setPlainText("Erste")
        a.senden()
        a.sprecher.reset_mock()
        a.eingabe.setPlainText("Zweite")
        a.senden()
        a.sprecher.sprich.assert_not_called()
        self.assertEqual(faden.auftrag_geben.call_args.args[0], "Zweite")

    def test_alles_steht_in_der_datei_mit_zeitstempel(self):
        a, _ = _ansicht(self)
        a.eingabe.setPlainText("Erste")
        a.senden()
        a._text("Antwort eins")
        a.eingabe.setPlainText("Zweite")
        a.senden()
        inhalt = orchestrator.verlauf_datei().read_text(encoding="utf-8")
        for stueck in ("Erste", "Antwort eins", "Zweite"):
            self.assertIn(stueck, inhalt)
        self.assertRegex(inhalt.splitlines()[0], r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] ")

    def test_schreibfehler_wirft_nicht(self):
        with mock.patch("builtins.open", side_effect=OSError("voll")):
            self.assertFalse(orchestrator.verlauf_anhaengen("antwort", "x"))

    def test_ueber_1_mb_bleiben_nur_die_letzten_eintraege(self):
        orchestrator.ORCH_ORDNER.mkdir(parents=True, exist_ok=True)
        datei = orchestrator.verlauf_datei()
        zeile = "[2026-01-01 00:00:00] antwort: " + "x" * 1000 + "\n"
        datei.write_text(zeile * 1100, encoding="utf-8")        # gut 1 MB
        self.assertTrue(orchestrator.verlauf_anhaengen("antwort", "NEUESTE"))
        self.assertLess(datei.stat().st_size, orchestrator.VERLAUF_MAX_BYTES)
        neu = datei.read_text(encoding="utf-8")
        self.assertIn("NEUESTE", neu)
        self.assertLessEqual(len(neu.splitlines()), orchestrator.VERLAUF_BEHALTEN)
        self.assertFalse(datei.with_name("verlauf_alt.txt").exists())


class FensterHakenTest(_Temp):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])

    def _fenster(self, nummern):
        a, faden = _ansicht(self)
        stapel = mock.MagicMock()
        stapel.currentWidget.return_value = object()
        f = types.SimpleNamespace(_orch_nummern=dict(nummern), _orch_ansicht=a,
                                  _orch_stapel=stapel, faden=None, sprecher=mock.MagicMock())
        return f, a, faden

    def test_orchestrator_auftrag_wird_zugestellt_bei_schalter_an(self):
        f, a, faden = self._fenster({"a.json": 1000009})
        fenster._orch_bericht(f, Path("/x/a.json"), "Ergebnis", 5, "fertig")
        text = faden.auftrag_geben.call_args.args[0]
        self.assertTrue(text.startswith("[CWB-MELDUNG] Auftrag 1000009 | Block 5 | fertig"))
        self.assertIn("Ergebnis", text)
        self.assertIn("Auftrag 1000009 | Block 5 | Zeit", text)   # Kennzeile des Berichts
        self.assertIn("Kontingent:", text)
        self.assertIn("Ergebnis", orchestrator.bericht_holen(1000009))  # Bericht liegt auch im Ordner

    def test_status_fehler_und_abgebrochen(self):
        f, a, faden = self._fenster({"a.json": 1000010})
        fenster._orch_bericht(f, Path("/x/a.json"), "kaputt", None, "Fehler")
        self.assertIn("| Fehler", faden.auftrag_geben.call_args.args[0].splitlines()[0])

    def test_schalter_aus_stellt_nichts_zu(self):
        f = types.SimpleNamespace(_orch_nummern={"a.json": 1000011}, _orch_ansicht=None,
                                  _orch_stapel=None)
        with mock.patch.object(orchestrator, "bericht_ablegen") as ablegen:
            fenster._orch_bericht(f, Path("/x/a.json"), "Ergebnis", 5)
            ablegen.assert_called_once()                       # Bericht im Ordner wie bisher
        self.assertFalse(orchestrator.eingang_datei().exists())  # aber keine Meldung

    def test_bruecken_auftrag_wird_nicht_zugestellt(self):
        f, a, faden = self._fenster({})                         # Bruecke steht nie in _orch_nummern
        fenster._orch_bericht(f, Path("/x/bruecke.json"), "Ergebnis", 5)
        faden.auftrag_geben.assert_not_called()
        self.assertEqual(a.schlange.anzahl(), 0)

    def test_dieselbe_nummer_wird_nicht_doppelt_zugestellt(self):
        f, a, faden = self._fenster({"a.json": 1000012})
        fenster._orch_bericht(f, Path("/x/a.json"), "Ergebnis", 5)
        f._orch_nummern["a.json"] = 1000012                     # Wiederholung desselben Auftrags
        faden.auftrag_geben.reset_mock()
        fenster._orch_bericht(f, Path("/x/a.json"), "Ergebnis", 5)
        faden.auftrag_geben.assert_not_called()

    def test_f8_stoppt_nur_vordere_sitzung(self):
        f, a, _ = self._fenster({})
        f._orch_stapel.currentWidget.return_value = a           # Orchestrator vorn
        self.assertTrue(fenster._orch_im_vordergrund(f))
        f._orch_stapel.currentWidget.return_value = object()
        self.assertFalse(fenster._orch_im_vordergrund(f))

    def test_f8_im_orchestrator_beruehrt_claude_code_nicht(self):
        f, a, _ = self._fenster({})
        f._orch_stapel.currentWidget.return_value = a
        f._terminal_faden = mock.MagicMock()
        f._warteschlange = [("x",)]
        f.faden = mock.MagicMock()
        with mock.patch.object(fenster, "auftragsjournal"), \
                mock.patch.object(fenster, "_orch_stopp") as stopp:
            fenster.Werkbank._not_aus(f)
        stopp.assert_called_once_with(f)
        f.faden.not_aus.assert_not_called()
        f._terminal_faden.not_aus.assert_not_called()
        self.assertEqual(f._warteschlange, [("x",)])

    def test_beschaeftigt_bei_laufendem_orchestrator_oder_offenem_auftrag(self):
        f, a, _ = self._fenster({})
        self.assertFalse(fenster._orch_beschaeftigt(f))
        a._offen = 1
        self.assertTrue(fenster._orch_beschaeftigt(f))
        a._offen = 0
        f._orch_nummern["a.json"] = 1000013
        self.assertTrue(fenster._orch_beschaeftigt(f))
        self.assertFalse(fenster._orch_beschaeftigt(types.SimpleNamespace()))

    def _neustart_fenster(self, beschaeftigt, code_laeuft=False):
        f, a, _ = self._fenster({"a.json": 1} if beschaeftigt else {})
        f._arbeit_laeuft = lambda: code_laeuft
        f._abbruch_bestaetigen = mock.MagicMock(return_value=False)
        f._laeuft_beenden = mock.MagicMock(return_value=False)   # bricht den Neustart danach ab
        return f

    def test_strg_f4_fragt_bei_laufendem_orchestrator_und_nein_bricht_ab(self):
        f = self._neustart_fenster(True)
        fenster.Werkbank._neustart(f)
        f._abbruch_bestaetigen.assert_called_once()
        f._laeuft_beenden.assert_not_called()

    def test_strg_f4_fragt_nicht_ohne_orchestrator_arbeit(self):
        f = self._neustart_fenster(False)
        fenster.Werkbank._neustart(f)
        f._abbruch_bestaetigen.assert_not_called()
        f._laeuft_beenden.assert_called_once()

    def test_strg_f4_fragt_nicht_doppelt_wenn_code_laeuft(self):
        f = self._neustart_fenster(True, code_laeuft=True)
        fenster.Werkbank._neustart(f)
        f._abbruch_bestaetigen.assert_not_called()               # fragt _laeuft_beenden selbst
        f._laeuft_beenden.assert_called_once()


if __name__ == "__main__":
    unittest.main()
