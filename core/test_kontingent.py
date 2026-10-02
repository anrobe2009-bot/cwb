"""
CWB - Code Workbench
Unit-Tests fuer die Kontingent-Pause (Max-Abo): core/grundlagen.py
(kontingent_entscheidung, reine Zeitlogik) und core/sitzung.py
(_kontingent_aus_limit, Erkennung einer RateLimitEvent-Meldung). Beide
laufen ohne Qt und ohne laufende SDK-Verbindung - mit nachgebildeten
Limit-Meldungen und fester Uhrzeit statt echtem Kontingent-Ablauf.

Dazu Block 80: core/fenster.py Werkbank._naechstes_fremdes_projekt() und
Werkbank._kontingent_fortsetzen() - geprueft ueber den unbound Aufruf auf
einem nachgebildeten Fenster (types.SimpleNamespace statt echtem Qt-Fenster),
mit allen von fenster.py benutzten Modulfunktionen (einstellungen_lesen,
naechste_fremde_projekt_datei, projekt_gleichwertig, projekte_finden) und
QTimer.singleShot ueberschrieben, damit kein echtes Qt-Fenster und kein
echter Eingangsordner noetig ist.

Aufruf: python -m unittest core.test_kontingent -v
        (oder, aus dem Ordner core/: python test_kontingent.py -v)
"""

import types
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from . import fenster, grundlagen, sitzung
except ImportError:
    import fenster
    import grundlagen
    import sitzung


@dataclass
class FalscheRateLimitInfo:
    """Bildet claude_agent_sdk.RateLimitInfo nach, ohne das SDK zu
    importieren - dieselben Felder, die sitzung._kontingent_aus_limit
    tatsaechlich liest."""
    status: str
    resets_at: int | None = None
    rate_limit_type: str | None = None


class KontingentEntscheidungTest(unittest.TestCase):
    """core/grundlagen.py: kontingent_entscheidung()."""

    def setUp(self):
        self.jetzt = datetime(2026, 10, 1, 12, 0, 0)

    def test_ohne_freigabezeitpunkt_alle_15_minuten(self):
        ergebnis = grundlagen.kontingent_entscheidung(None, self.jetzt)
        self.assertFalse(ergebnis["wochenlimit"])
        self.assertEqual(ergebnis["warte_bis"], self.jetzt + timedelta(minutes=15))
        self.assertIn("alle 15 Minuten", ergebnis["ansage"])
        self.assertIn("15 Minuten", ergebnis["status"])
        self.assertEqual(ergebnis["wartesekunden"], 15 * 60)

    def test_freigabe_in_zwei_stunden_wird_in_zwei_minuten_nachschlag_fortgesetzt(self):
        freigabe = self.jetzt + timedelta(hours=2)
        ergebnis = grundlagen.kontingent_entscheidung(freigabe.timestamp(), self.jetzt)
        self.assertFalse(ergebnis["wochenlimit"])
        erwartet = freigabe + timedelta(minutes=2)
        self.assertEqual(ergebnis["warte_bis"], erwartet)
        self.assertIn(f"{erwartet:%H:%M}", ergebnis["ansage"])
        self.assertIn(f"{erwartet:%H:%M}", ergebnis["status"])

    def test_freigabe_ueber_zwoelf_stunden_gilt_als_wochenlimit(self):
        freigabe = self.jetzt + timedelta(hours=12, minutes=1)
        ergebnis = grundlagen.kontingent_entscheidung(freigabe.timestamp(), self.jetzt)
        self.assertTrue(ergebnis["wochenlimit"])
        self.assertIsNone(ergebnis["warte_bis"])
        self.assertIn("Wochenlimit", ergebnis["grund"])
        self.assertIn(f"{freigabe:%d.%m.%Y %H:%M}", ergebnis["grund"])

    def test_freigabe_genau_zwoelf_stunden_ist_noch_kein_wochenlimit(self):
        freigabe = self.jetzt + timedelta(hours=12)
        ergebnis = grundlagen.kontingent_entscheidung(freigabe.timestamp(), self.jetzt)
        self.assertFalse(ergebnis["wochenlimit"])

    def test_freigabe_in_der_vergangenheit_wartet_mindestens_eine_sekunde(self):
        freigabe = self.jetzt - timedelta(minutes=10)
        ergebnis = grundlagen.kontingent_entscheidung(freigabe.timestamp(), self.jetzt)
        self.assertFalse(ergebnis["wochenlimit"])
        self.assertGreaterEqual(ergebnis["wartesekunden"], 1.0)


class KontingentAusLimitTest(unittest.TestCase):
    """core/sitzung.py: _kontingent_aus_limit() - Erkennung einer
    nachgebildeten RateLimitEvent-Meldung des Agent-SDK."""

    def test_keine_meldung_ergibt_kein_kontingent(self):
        self.assertIsNone(sitzung._kontingent_aus_limit(None))

    def test_erlaubt_ergibt_kein_kontingent(self):
        info = FalscheRateLimitInfo(status="allowed")
        self.assertIsNone(sitzung._kontingent_aus_limit(info))

    def test_warnung_ergibt_noch_kein_kontingent(self):
        info = FalscheRateLimitInfo(status="allowed_warning", resets_at=1234567890)
        self.assertIsNone(sitzung._kontingent_aus_limit(info))

    def test_abgewiesen_ergibt_kontingent_mit_freigabe_und_typ(self):
        info = FalscheRateLimitInfo(
            status="rejected", resets_at=1234567890, rate_limit_type="five_hour"
        )
        ergebnis = sitzung._kontingent_aus_limit(info)
        self.assertEqual(ergebnis["resets_at"], 1234567890)
        self.assertEqual(ergebnis["rate_limit_type"], "five_hour")
        self.assertIn("rejected", ergebnis["quelle"])

    def test_abgewiesenes_wochenlimit_ohne_bekannten_typ(self):
        info = FalscheRateLimitInfo(status="rejected", resets_at=None, rate_limit_type=None)
        ergebnis = sitzung._kontingent_aus_limit(info)
        self.assertIsNone(ergebnis["resets_at"])
        self.assertIsNone(ergebnis["rate_limit_type"])


class SparmodusErforderlichTest(unittest.TestCase):
    """Block 77, Punkt 3: core/sitzung.py, _sparmodus_erforderlich()."""

    def test_keine_meldung_kein_sparmodus(self):
        self.assertFalse(sitzung._sparmodus_erforderlich(None))

    def test_allowed_kein_sparmodus(self):
        self.assertFalse(sitzung._sparmodus_erforderlich({"status": "allowed"}))

    def test_allowed_warning_loest_sparmodus_aus(self):
        self.assertTrue(sitzung._sparmodus_erforderlich({"status": "allowed_warning"}))

    def test_rejected_ist_kein_sparmodus_sondern_kontingent_pause(self):
        self.assertFalse(sitzung._sparmodus_erforderlich({"status": "rejected"}))


class KontingentZustandBerechnenTest(unittest.TestCase):
    """Block 77, Punkt 4: core/sitzung.py, _kontingent_zustand_berechnen()."""

    def test_ohne_jede_meldung_ist_normal_mit_leerem_text(self):
        ergebnis = sitzung._kontingent_zustand_berechnen(None, None)
        self.assertEqual(ergebnis["stufe"], "normal")
        self.assertEqual(ergebnis["text"], "")

    def test_beide_allowed_ist_normal(self):
        ergebnis = sitzung._kontingent_zustand_berechnen(
            {"status": "allowed"}, {"status": "allowed"})
        self.assertEqual(ergebnis["stufe"], "normal")
        self.assertIn("normal", ergebnis["text"].lower())

    def test_woche_knapp_ergibt_knapp(self):
        ergebnis = sitzung._kontingent_zustand_berechnen(
            {"status": "allowed"}, {"status": "allowed_warning"})
        self.assertEqual(ergebnis["stufe"], "knapp")
        self.assertIn("knapp", ergebnis["text"].lower())

    def test_funf_stunden_knapp_ergibt_ebenfalls_knapp(self):
        ergebnis = sitzung._kontingent_zustand_berechnen(
            {"status": "allowed_warning"}, None)
        self.assertEqual(ergebnis["stufe"], "knapp")

    def test_rejected_geht_vor_knapp_und_nennt_uhrzeit(self):
        freigabe = datetime(2026, 10, 1, 18, 30).timestamp()
        ergebnis = sitzung._kontingent_zustand_berechnen(
            {"status": "allowed_warning"}, {"status": "rejected", "resets_at": freigabe})
        self.assertEqual(ergebnis["stufe"], "erschoepft")
        self.assertIn("18:30", ergebnis["text"])

    def test_rejected_ohne_freigabezeit_ohne_uhrzeit_im_text(self):
        ergebnis = sitzung._kontingent_zustand_berechnen(
            None, {"status": "rejected", "resets_at": None})
        self.assertEqual(ergebnis["stufe"], "erschoepft")
        self.assertNotIn(":", ergebnis["text"])


class ModellIstOpusTest(unittest.TestCase):
    """Block 77, Punkt 2: core/fenster.py, _modell_ist_opus() - ob der in
    F12 gewaehlte Standard eine Hochstufung ueberhaupt noch braucht."""

    def test_leer_gilt_als_default_also_opus(self):
        self.assertTrue(fenster._modell_ist_opus(""))

    def test_default_ist_opus(self):
        self.assertTrue(fenster._modell_ist_opus("default"))

    def test_opus_kurzname_ist_opus(self):
        self.assertTrue(fenster._modell_ist_opus("opus"))

    def test_opus_mit_zusatz_ist_opus(self):
        self.assertTrue(fenster._modell_ist_opus("opus[1m]"))

    def test_sonnet_ist_kein_opus(self):
        self.assertFalse(fenster._modell_ist_opus("sonnet"))

    def test_haiku_ist_kein_opus(self):
        self.assertFalse(fenster._modell_ist_opus("haiku"))

    def test_gross_klein_egal(self):
        self.assertTrue(fenster._modell_ist_opus("OPUS"))


class NaechstesFremdesProjektTest(unittest.TestCase):
    """Block 80: core/fenster.py Werkbank._naechstes_fremdes_projekt() -
    gemeinsame Grundlage fuer den Leerlauf-Wechsel und die Pruefung beim
    Ende einer Kontingent-Pause. Alle von fenster.py benutzten
    Modulfunktionen werden ueberschrieben, damit kein echter Eingangsordner
    und keine echten einstellungen.json noetig sind."""

    def _fake(self):
        return types.SimpleNamespace(
            projekt=types.SimpleNamespace(name="CWB"),
            _auto_projekt_unbekannt_angesagt=None,
            sprecher=types.SimpleNamespace(sprich=MagicMock()),
        )

    def test_schalter_aus_fragt_eingangsordner_gar_nicht_erst(self):
        fake = self._fake()
        with patch.object(fenster, "einstellungen_lesen",
                           return_value={"auto_projektwechsel": False}), \
             patch.object(fenster, "naechste_fremde_projekt_datei") as naechste:
            ergebnis = fenster.Werkbank._naechstes_fremdes_projekt(fake)
        self.assertIsNone(ergebnis)
        naechste.assert_not_called()

    def test_kein_wartender_fremder_auftrag_ergibt_none(self):
        fake = self._fake()
        with patch.object(fenster, "einstellungen_lesen",
                           return_value={"auto_projektwechsel": True}), \
             patch.object(fenster, "naechste_fremde_projekt_datei", return_value=None):
            ergebnis = fenster.Werkbank._naechstes_fremdes_projekt(fake)
        self.assertIsNone(ergebnis)

    def test_bekanntes_fremdes_projekt_wird_aufgeloest(self):
        fake = self._fake()
        hausgemacht = types.SimpleNamespace(name="hausgemacht")
        with patch.object(fenster, "einstellungen_lesen",
                           return_value={"auto_projektwechsel": True}), \
             patch.object(fenster, "naechste_fremde_projekt_datei",
                           return_value="hausgemacht"), \
             patch.object(fenster, "projekte_finden",
                           return_value=[fake.projekt, hausgemacht]), \
             patch.object(fenster, "projekt_gleichwertig",
                           side_effect=lambda a, b: a == b):
            ergebnis = fenster.Werkbank._naechstes_fremdes_projekt(fake)
        self.assertIs(ergebnis, hausgemacht)

    def test_unbekanntes_fremdes_projekt_ergibt_none_und_wird_einmalig_angesagt(self):
        fake = self._fake()
        with patch.object(fenster, "einstellungen_lesen",
                           return_value={"auto_projektwechsel": True}), \
             patch.object(fenster, "naechste_fremde_projekt_datei",
                           return_value="unbekannt-xyz"), \
             patch.object(fenster, "projekte_finden", return_value=[fake.projekt]), \
             patch.object(fenster, "projekt_gleichwertig", return_value=False):
            ergebnis = fenster.Werkbank._naechstes_fremdes_projekt(fake)
            self.assertIsNone(ergebnis)
            self.assertEqual(fake.sprecher.sprich.call_count, 1)
            # Zweiter Blick mit demselben unbekannten Namen: keine zweite Ansage.
            ergebnis = fenster.Werkbank._naechstes_fremdes_projekt(fake)
        self.assertIsNone(ergebnis)
        self.assertEqual(fake.sprecher.sprich.call_count, 1)


class KontingentFortsetzenTest(unittest.TestCase):
    """Block 80: core/fenster.py Werkbank._kontingent_fortsetzen() - vor dem
    Fortsetzen muss dieselbe Eingangsreihenfolge-Pruefung laufen wie im
    Leerlauf, sonst wird nach jeder Kontingent-Pause immer das zuletzt
    aktive Projekt bevorzugt (der eigentliche, gemessene Fehler vom
    01.10.2026, Projekt CWB Block 77 vs. hausgemacht Block 76)."""

    def _fake(self, eingang_datei):
        fake = types.SimpleNamespace(
            _kontingent_info={
                "text": "Mach etwas", "bilder": [], "bruecke_nummer": None,
                "block_nummer": 77, "eingang_datei": eingang_datei,
                "modell_wunsch": None, "modell_grund": None,
            },
            sprecher=types.SimpleNamespace(sprich=MagicMock()),
        )
        fake._auftrag_starten = MagicMock()
        fake._auto_projekt_wechseln = MagicMock()
        return fake

    def test_aelterer_fremder_auftrag_fuehrt_zum_wechsel_statt_fortsetzen(self):
        fake = self._fake(eingang_datei=Path("eingang/laeuft/34_hausgemacht.json"))
        hausgemacht = types.SimpleNamespace(name="hausgemacht")
        fake._naechstes_fremdes_projekt = MagicMock(return_value=hausgemacht)
        with patch.object(fenster.QTimer, "singleShot",
                           side_effect=lambda ms, callback: callback()):
            fenster.Werkbank._kontingent_fortsetzen(fake)
        fake._auto_projekt_wechseln.assert_called_once_with(hausgemacht)
        fake._auftrag_starten.assert_not_called()
        self.assertIsNone(fake._kontingent_info)

    def test_kein_wartender_fremder_auftrag_setzt_wie_bisher_fort(self):
        fake = self._fake(eingang_datei=Path("eingang/laeuft/77_cwb.json"))
        fake._naechstes_fremdes_projekt = MagicMock(return_value=None)
        fenster.Werkbank._kontingent_fortsetzen(fake)
        fake._auftrag_starten.assert_called_once()
        fake._auto_projekt_wechseln.assert_not_called()
        self.assertTrue(
            fake._auftrag_starten.call_args.args[0].endswith("Mach etwas")
        )

    def test_auftrag_ohne_eingangsdatei_wird_immer_fortgesetzt(self):
        # Von Hand eingegebene Auftraege haben keine Datei in laeuft/, die
        # ein Wechsel ueberleben liesse - sie duerfen nie zurueckgestellt
        # werden, sonst gingen sie verloren.
        fake = self._fake(eingang_datei=None)
        fake._naechstes_fremdes_projekt = MagicMock()
        fenster.Werkbank._kontingent_fortsetzen(fake)
        fake._naechstes_fremdes_projekt.assert_not_called()
        fake._auftrag_starten.assert_called_once()
        fake._auto_projekt_wechseln.assert_not_called()

    def test_ohne_pause_info_geschieht_nichts(self):
        # F8 (Not-Aus) hat die Pause inzwischen verworfen.
        fake = self._fake(eingang_datei=None)
        fake._kontingent_info = None
        fake._naechstes_fremdes_projekt = MagicMock()
        fenster.Werkbank._kontingent_fortsetzen(fake)
        fake._naechstes_fremdes_projekt.assert_not_called()
        fake._auftrag_starten.assert_not_called()
        fake._auto_projekt_wechseln.assert_not_called()


if __name__ == "__main__":
    unittest.main()
