"""
CWB - Code Workbench
Unit-Tests fuer die Kontingent-Pause (Max-Abo): core/grundlagen.py
(kontingent_entscheidung, reine Zeitlogik) und core/sitzung.py
(_kontingent_aus_limit, Erkennung einer RateLimitEvent-Meldung). Beide
laufen ohne Qt und ohne laufende SDK-Verbindung - mit nachgebildeten
Limit-Meldungen und fester Uhrzeit statt echtem Kontingent-Ablauf.

Aufruf: python -m unittest core.test_kontingent -v
        (oder, aus dem Ordner core/: python test_kontingent.py -v)
"""

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta

try:
    from . import grundlagen, sitzung
except ImportError:
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


if __name__ == "__main__":
    unittest.main()
