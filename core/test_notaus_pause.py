"""
CWB - Code Workbench
Tests fuer die Not-Aus-Pause (core/notaus_pause.py und Werkbank._not_aus):
Attrappen und feste Uhrzeiten, kein echtes Fenster, keine echten Faeden.

Aufruf: python -m unittest core.test_notaus_pause -v
"""

import os
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from . import fenster, leitstand, notaus_pause, sprache
except ImportError:
    import fenster
    import leitstand
    import notaus_pause
    import sprache

Werkbank = fenster.Werkbank
T0 = datetime(2026, 10, 23, 12, 0, 0)


class _Uhr(datetime):
    """datetime mit festem now() fuer notaus_pause."""
    fest = T0

    @classmethod
    def now(cls, tz=None):
        return cls.fest


class _Traeger:
    _not_aus = Werkbank._not_aus
    _notaus_pause_beginnen = Werkbank._notaus_pause_beginnen
    _notaus_pause_abbrechen = Werkbank._notaus_pause_abbrechen
    _notaus_pause_ende = Werkbank._notaus_pause_ende
    _abbruch_ruhe = Werkbank._abbruch_ruhe
    _abbruch_rueckfall_planen = Werkbank._abbruch_rueckfall_planen
    _bruecke_zustand_anwenden = Werkbank._bruecke_zustand_anwenden
    _bruecke_umschalten = Werkbank._bruecke_umschalten
    _leitstand_zustand_anwenden = Werkbank._leitstand_zustand_anwenden
    _leitstand_umschalten = Werkbank._leitstand_umschalten

    def __init__(self):
        self.faden = mock.Mock(sitzung=None)
        self.sprecher = mock.Mock()
        self.ausgabekopf = mock.Mock()
        self.kacheln = mock.Mock()
        self._terminal_faden = None
        self._warteschlange = []
        self._kontingent_info = None
        self._kontingent_uhr = mock.Mock()
        self._notaus_uhr = mock.Mock()
        self._abbruch_uhr = mock.Mock()
        self._letzter_zustand = "bereit"
        self._laeuft = lambda: False
        self._zustand_zeigen = mock.Mock(
            side_effect=lambda z: setattr(self, "_letzter_zustand", z))
        self._taetigkeit_zeigen = mock.Mock()
        self._bruecke_starten = mock.Mock()
        self._bruecke_stoppen = mock.Mock()
        self._warteschlange_zeigen = mock.Mock()
        self._status_zeigen = mock.Mock()
        self._verlauf_anhaengen = mock.Mock()


class PauseBasis(unittest.TestCase):
    def setUp(self):
        self.werte = {"bruecke_aktiv": True, "leitstand_aktiv": True}
        self.schreiben = mock.Mock()
        lesen = lambda: dict(self.werte)  # noqa: E731
        for ziel in (fenster, leitstand, notaus_pause):
            p = mock.patch.object(ziel, "einstellungen_lesen", lesen)
            p.start()
            self.addCleanup(p.stop)
        for name, wert in (
                (fenster, ("einstellungen_schreiben", self.schreiben)),
                (fenster, ("auftragsjournal", mock.Mock())),
                (fenster, ("_orch_im_vordergrund", lambda f: False)),
                (fenster, ("verwerfen", mock.Mock())),
                (leitstand, ("wirksamer_anbieter",
                             lambda: types.SimpleNamespace(api_schluessel="x"))),
                (notaus_pause, ("datetime", _Uhr))):
            p = mock.patch.object(name, wert[0], wert[1])
            p.start()
            self.addCleanup(p.stop)
        _Uhr.fest = T0
        notaus_pause.beenden()
        self.addCleanup(notaus_pause.beenden)
        self.t = _Traeger()


class NotAusTest(PauseBasis):
    def test_aendert_die_einstellungsdatei_nicht(self):
        self.t._not_aus()
        self.schreiben.assert_not_called()
        self.assertTrue(self.werte["bruecke_aktiv"])
        self.assertTrue(self.werte["leitstand_aktiv"])

    def test_satz_pause_fuenf_minuten_status_und_timer(self):
        self.t._not_aus()
        satz = self.t.sprecher.sprich.call_args[0][0]
        self.assertEqual(satz, "Not-Aus. Brücke pausiert fünf Minuten.")
        art = self.t.sprecher.sprich.call_args.kwargs.get("art")
        self.assertEqual(art, "hinweis")
        self.assertIn(art, sprache.ERLAUBTE_ARTEN)
        self.t._status_zeigen.assert_called_with("Brücke pausiert bis 12:05")
        self.t._notaus_uhr.start.assert_called_with(300_000)
        self.t.faden.not_aus.assert_called_once()

    def test_bruecke_und_leitstand_ruhen_dann_laufen_sie_wieder(self):
        self.t._not_aus()
        self.assertTrue(notaus_pause.bruecke_pausiert())
        self.assertFalse(leitstand.aktiv())
        self.t._bruecke_stoppen.assert_called()
        _Uhr.fest = T0 + timedelta(minutes=4, seconds=59)
        self.assertTrue(notaus_pause.bruecke_pausiert())
        _Uhr.fest = T0 + timedelta(minutes=5)
        self.assertTrue(leitstand.aktiv())      # Leitstand ohne Timer wieder an
        self.t._bruecke_starten.reset_mock()
        self.t._notaus_pause_ende()
        self.t._bruecke_starten.assert_called_once()
        self.assertFalse(notaus_pause.aktiv())
        self.t._status_zeigen.assert_called_with("Brücke ist wieder an")
        self.t._verlauf_anhaengen.assert_called_with("Brücke ist wieder an", "hinweis")
        self.t.sprecher.ton.assert_called_with("fertig")

    def test_mit_laufendem_auftrag_kein_not_aus_wort_und_nachsatz(self):
        self.t._auftrag_laeuft = True
        self.t._not_aus()
        self.t.sprecher.sprich.assert_not_called()
        self.assertEqual(self.t._notaus_nachsatz, "Brücke pausiert fünf Minuten.")

    def test_pause_ende_spricht_mit_erlaubter_art(self):
        self.t._not_aus()
        _Uhr.fest = T0 + timedelta(minutes=5)
        self.t.sprecher.sprich.reset_mock()
        self.t._notaus_pause_ende()
        args = self.t.sprecher.sprich.call_args
        self.assertEqual(args[0][0], "Brücke ist wieder an.")
        self.assertEqual(args.kwargs, {"unterbrechen": False, "art": "hinweis"})
        self.assertIn("hinweis", sprache.ERLAUBTE_ARTEN)

    def test_pause_ende_setzt_grauen_balken_auf_bereit(self):
        self.t._not_aus()
        self.t._letzter_zustand = "abgebrochen"
        _Uhr.fest = T0 + timedelta(minutes=5)
        self.t._notaus_pause_ende()
        self.t._zustand_zeigen.assert_called_once_with("bereit")

    def test_pause_ende_laeuft_auftrag_balken_unveraendert(self):
        self.t._not_aus()
        self.t._letzter_zustand = "abgebrochen"
        self.t._laeuft = lambda: True
        _Uhr.fest = T0 + timedelta(minutes=5)
        self.t._notaus_pause_ende()
        self.t._zustand_zeigen.assert_not_called()

    def test_pause_ende_fehler_balken_unveraendert(self):
        self.t._not_aus()
        self.t._letzter_zustand = "fehler"
        _Uhr.fest = T0 + timedelta(minutes=5)
        self.t._notaus_pause_ende()
        self.t._zustand_zeigen.assert_not_called()
        self.assertEqual(self.t._letzter_zustand, "fehler")

    def test_rueckfall_nach_abbruch_dauer_null(self):
        self.werte["notaus_pause_minuten"] = 0
        self.t._not_aus()
        self.assertFalse(notaus_pause.aktiv())
        self.t._abbruch_rueckfall_planen()
        self.t._abbruch_uhr.start.assert_called_once_with(
            fenster.ABBRUCH_RUECKFALL_MS)
        self.assertEqual(fenster.ABBRUCH_RUECKFALL_MS, 5000)
        # Zeitgeber feuert: Balken noch grau, nichts laeuft -> bereit
        self.t._letzter_zustand = "abgebrochen"
        self.t._abbruch_ruhe()
        self.t._zustand_zeigen.assert_called_once_with("bereit")
        # kam inzwischen etwas anderes dazwischen, bleibt es
        self.t._zustand_zeigen.reset_mock()
        self.t._letzter_zustand = "schreibt"
        self.t._abbruch_ruhe()
        self.t._zustand_zeigen.assert_not_called()

    def test_rueckfall_zeitgeber_startet_nicht_waehrend_der_pause(self):
        self.t._not_aus()
        self.t._abbruch_rueckfall_planen()
        self.t._abbruch_uhr.start.assert_not_called()

    def test_ende_vor_der_zeit_tut_nichts(self):
        self.t._not_aus()
        _Uhr.fest = T0 + timedelta(minutes=1)
        self.t._notaus_pause_ende()
        self.assertTrue(notaus_pause.bruecke_pausiert())

    def test_vorher_ausgeschaltetes_bleibt_aus(self):
        self.werte["bruecke_aktiv"] = False
        self.werte["leitstand_aktiv"] = False
        self.t._not_aus()
        self.assertFalse(notaus_pause.aktiv())
        self.t._notaus_uhr.start.assert_not_called()
        self.assertEqual(self.t.sprecher.sprich.call_args[0][0], "Not-Aus.")
        _Uhr.fest = T0 + timedelta(hours=1)
        self.t._notaus_pause_ende()
        self.t._bruecke_starten.assert_not_called()

    def test_nur_leitstand_pausiert_bruecke_bleibt_aus(self):
        self.werte["bruecke_aktiv"] = False
        self.t._not_aus()
        self.assertFalse(notaus_pause.bruecke_pausiert())
        self.assertTrue(notaus_pause.leitstand_pausiert())
        self.assertIn("Leitstand pausiert fünf Minuten",
                      self.t.sprecher.sprich.call_args[0][0])

    def test_wert_null_heisst_keine_pause(self):
        self.werte["notaus_pause_minuten"] = 0
        self.t._not_aus()
        self.assertFalse(notaus_pause.aktiv())
        self.assertTrue(leitstand.aktiv())
        self.t._bruecke_stoppen.assert_not_called()
        self.assertEqual(self.t.sprecher.sprich.call_args[0][0], "Not-Aus.")

    def test_dauer_aus_der_einstellung(self):
        self.werte["notaus_pause_minuten"] = 1
        self.t._not_aus()
        self.assertIn("pausiert eine Minute", self.t.sprecher.sprich.call_args[0][0])
        self.werte["notaus_pause_minuten"] = 99
        self.assertEqual(notaus_pause.minuten(), 60)
        self.werte["notaus_pause_minuten"] = "kaputt"
        self.assertEqual(notaus_pause.minuten(), 5)

    def test_neustart_hebt_pause_auf(self):
        self.t._not_aus()
        # Neustart = frischer Prozess: Zustand liegt nur im Speicher.
        notaus_pause._zustand = None
        self.assertFalse(notaus_pause.bruecke_pausiert())
        self.assertTrue(leitstand.aktiv())
        self.schreiben.assert_not_called()

    def test_journal_nennt_die_pause(self):
        self.t._not_aus()
        schritte = [c[0][0] for c in fenster.auftragsjournal.schreibe.call_args_list]
        self.assertIn("notaus_pause", schritte)


class VonHandTest(PauseBasis):
    def test_umschalt_f8_beendet_pause_und_schaltet_an(self):
        self.t._not_aus()
        self.t._bruecke_umschalten()
        self.assertFalse(notaus_pause.aktiv())
        self.schreiben.assert_not_called()
        self.t._bruecke_starten.assert_called()

    def test_umschalt_f9_beendet_pause(self):
        self.t._not_aus()
        self.t._leitstand_umschalten()
        self.assertFalse(notaus_pause.aktiv())
        self.assertTrue(leitstand.aktiv())

    def test_f12_ausschalten_beendet_pause(self):
        self.t._not_aus()
        self.assertTrue(notaus_pause.von_hand_geaendert(
            {"bruecke_aktiv": False, "leitstand_aktiv": True}))
        self.assertFalse(notaus_pause.von_hand_geaendert(
            {"bruecke_aktiv": True, "leitstand_aktiv": True}))

    def test_umschalten_ohne_pause_bleibt_normal(self):
        self.t._bruecke_umschalten()
        self.schreiben.assert_called_once()
        self.assertFalse(self.schreiben.call_args[0][0]["bruecke_aktiv"])


class OrchestratorTest(PauseBasis):
    def test_orchestrator_not_aus_bleibt_unveraendert(self):
        with mock.patch.object(fenster, "_orch_im_vordergrund", lambda f: True), \
                mock.patch.object(fenster, "_orch_stopp") as stopp:
            self.t._not_aus()
        stopp.assert_called_once()
        self.assertFalse(notaus_pause.aktiv())
        self.t.sprecher.sprich.assert_called_with("Orchestrator gestoppt.")
        self.schreiben.assert_not_called()


if __name__ == "__main__":
    unittest.main()
