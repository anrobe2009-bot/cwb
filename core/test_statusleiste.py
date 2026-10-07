"""
CWB - Code Workbench
Unit-Tests fuer Block 82 (Leiste "Läuft"/"Wartet" ueber dem Ausgabefeld):
core/grundlagen.py (auftrags_kennung, reine Formatierung) und core/fenster.py
(Werkbank._laeuft_kennung/_wartet_kennungen/_statusleiste_satz/
_statusleiste_aktualisieren) - geprueft ueber den unbound Aufruf auf einem
nachgebildeten Fenster (types.SimpleNamespace statt echtem Qt-Fenster), wie
schon in core/test_kontingent.py.

Aufruf: python -m unittest core.test_statusleiste -v
"""

import types
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

try:
    from . import fenster, grundlagen
except ImportError:
    import fenster
    import grundlagen


class AuftragsKennungTest(unittest.TestCase):
    """core/grundlagen.py: auftrags_kennung()."""

    def test_mit_blocknummer_zaehlt_nur_die_nummer(self):
        self.assertEqual(
            grundlagen.auftrags_kennung(375, "Eingabe", datetime(2026, 10, 7, 16, 58)),
            "375",
        )

    def test_ohne_blocknummer_zeigt_quelle_und_uhrzeit(self):
        self.assertEqual(
            grundlagen.auftrags_kennung(None, "Eingabe", datetime(2026, 10, 7, 16, 58)),
            "Eingabe 16:58",
        )

    def test_fremdes_projekt_steht_davor(self):
        self.assertEqual(
            grundlagen.auftrags_kennung(37, "Eingang", datetime(2026, 10, 7, 16, 58), "CWB"),
            "CWB 37",
        )

    def test_fremdes_projekt_auch_beim_fallback_davor(self):
        self.assertEqual(
            grundlagen.auftrags_kennung(None, "Eingang", datetime(2026, 10, 7, 16, 58), "CWB"),
            "CWB Eingang 16:58",
        )

    def test_eigenes_projekt_ohne_praefix(self):
        self.assertEqual(
            grundlagen.auftrags_kennung(37, "Eingang", datetime(2026, 10, 7, 16, 58), None),
            "37",
        )


def _fake_faden(laeuft: bool):
    return types.SimpleNamespace(isRunning=lambda: laeuft)


class FakeWerkbank:
    """Nachgebildetes Fenster fuer die unbound Aufrufe unten - nur die
    Attribute, die _laeuft_kennung/_wartet_kennungen tatsaechlich lesen."""

    def __init__(self, projekt_name="CWB"):
        self.projekt = types.SimpleNamespace(name=projekt_name)
        self._kontingent_info = None
        self._auftrag_laeuft = False
        self._terminal_faden = None
        self._bild_faden = None
        self._laufender_block_nummer = None
        self._laufender_quelle = ""
        self._laufender_zeit = None
        self._warteschlange = []
        self._sparmodus_wartend = []

    _laeuft_kennung = fenster.Werkbank._laeuft_kennung
    _wartet_kennungen = fenster.Werkbank._wartet_kennungen
    _statusleiste_satz = fenster.Werkbank._statusleiste_satz
    _statusleiste_aktualisieren = fenster.Werkbank._statusleiste_aktualisieren


class LaeuftKennungTest(unittest.TestCase):
    """core/fenster.py: Werkbank._laeuft_kennung()."""

    def test_nichts_laeuft_ergibt_gedankenstrich(self):
        self.assertEqual(FakeWerkbank()._laeuft_kennung(), "–")

    def test_code_auftrag_zeigt_blocknummer(self):
        fake = FakeWerkbank()
        fake._auftrag_laeuft = True
        fake._laufender_block_nummer = 375
        fake._laufender_quelle = "Eingabe"
        fake._laufender_zeit = datetime(2026, 10, 7, 16, 58)
        self.assertEqual(fake._laeuft_kennung(), "375")

    def test_code_auftrag_ohne_blocknummer_zeigt_fallback(self):
        fake = FakeWerkbank()
        fake._auftrag_laeuft = True
        fake._laufender_quelle = "Eingabe"
        fake._laufender_zeit = datetime(2026, 10, 7, 16, 58)
        self.assertEqual(fake._laeuft_kennung(), "Eingabe 16:58")

    def test_laufendes_terminal_zaehlt_als_laeuft(self):
        fake = FakeWerkbank()
        fake._terminal_faden = _fake_faden(True)
        fake._laufender_block_nummer = 12
        self.assertEqual(fake._laeuft_kennung(), "12")

    def test_laufendes_bild_zaehlt_als_laeuft(self):
        fake = FakeWerkbank()
        fake._bild_faden = _fake_faden(True)
        fake._laufender_block_nummer = 13
        self.assertEqual(fake._laeuft_kennung(), "13")

    def test_beendeter_faden_zaehlt_nicht_als_laeuft(self):
        fake = FakeWerkbank()
        fake._terminal_faden = _fake_faden(False)
        fake._laufender_block_nummer = 12
        self.assertEqual(fake._laeuft_kennung(), "–")

    def test_kontingent_pause_zaehlt_als_laeuft_trotz_auftrag_laeuft_false(self):
        fake = FakeWerkbank()
        fake._kontingent_info = {
            "block_nummer": 77, "quelle": "Eingang",
            "zeit": datetime(2026, 10, 7, 16, 58),
        }
        self.assertEqual(fake._laeuft_kennung(), "77")

    def test_kontingent_pause_geht_vor_laufendem_terminal(self):
        # Kann in der Praxis nicht gleichzeitig vorkommen, aber die Pause
        # soll in jedem Fall Vorrang haben, nicht zufaellig das Terminal.
        fake = FakeWerkbank()
        fake._kontingent_info = {"block_nummer": 77, "quelle": "Eingang", "zeit": None}
        fake._terminal_faden = _fake_faden(True)
        fake._laufender_block_nummer = 12
        self.assertEqual(fake._laeuft_kennung(), "77")


class WartetKennungenTest(unittest.TestCase):
    """core/fenster.py: Werkbank._wartet_kennungen() - drei Quellen:
    self._warteschlange, self._sparmodus_wartend und
    core.eingangsordner.wartende_dateien()."""

    def _eintrag(self, block_nummer, quelle="Eingabe", zeit=None):
        zeit = zeit or datetime(2026, 10, 7, 16, 58)
        return ("Text", [], None, block_nummer, None, None, None, quelle, zeit)

    def test_leer_ergibt_leere_liste(self):
        with patch.object(fenster, "wartende_dateien", return_value=[]):
            self.assertEqual(FakeWerkbank()._wartet_kennungen(), [])

    def test_warteschlange_in_reihenfolge(self):
        fake = FakeWerkbank()
        fake._warteschlange = [self._eintrag(376), self._eintrag(377)]
        with patch.object(fenster, "wartende_dateien", return_value=[]):
            self.assertEqual(fake._wartet_kennungen(), ["376", "377"])

    def test_sparmodus_wartend_kommt_nach_der_warteschlange(self):
        fake = FakeWerkbank()
        fake._warteschlange = [self._eintrag(376)]
        fake._sparmodus_wartend = [self._eintrag(378)]
        with patch.object(fenster, "wartende_dateien", return_value=[]):
            self.assertEqual(fake._wartet_kennungen(), ["376", "378"])

    def test_eingangsordner_datei_ohne_blocknummer_zeigt_quelle_und_zeit(self):
        fake = FakeWerkbank(projekt_name="CWB")
        pfad = types.SimpleNamespace(stat=lambda: types.SimpleNamespace(
            st_mtime=datetime(2026, 10, 7, 16, 58).timestamp()))
        auftrag = types.SimpleNamespace(quelle="lokal", projekt="", art="run", inhalt="dir")
        with patch.object(fenster, "wartende_dateien", return_value=[pfad]), \
             patch.object(fenster, "auftrag_lesen", return_value=auftrag), \
             patch.object(fenster, "block_erkennen", return_value=(None, "dir", True)):
            self.assertEqual(fake._wartet_kennungen(), ["Eingang 16:58"])

    def test_eingangsordner_datei_mit_blocknummer(self):
        fake = FakeWerkbank(projekt_name="CWB")
        pfad = types.SimpleNamespace(stat=lambda: types.SimpleNamespace(st_mtime=0))
        auftrag = types.SimpleNamespace(quelle="lokal", projekt="", art="code",
                                         inhalt="Block 40\nmach etwas")
        with patch.object(fenster, "wartende_dateien", return_value=[pfad]), \
             patch.object(fenster, "auftrag_lesen", return_value=auftrag), \
             patch.object(fenster, "block_erkennen", return_value=(40, "mach etwas", True)):
            self.assertEqual(fake._wartet_kennungen(), ["40"])

    def test_eingangsordner_bruecke_quelle_zeigt_bruecke(self):
        fake = FakeWerkbank(projekt_name="CWB")
        pfad = types.SimpleNamespace(stat=lambda: types.SimpleNamespace(st_mtime=0))
        auftrag = types.SimpleNamespace(quelle=fenster.QUELLE_BRUECKE, projekt="",
                                         art="code", inhalt="x")
        with patch.object(fenster, "wartende_dateien", return_value=[pfad]), \
             patch.object(fenster, "auftrag_lesen", return_value=auftrag), \
             patch.object(fenster, "block_erkennen", return_value=(None, "x", True)), \
             patch.object(fenster, "datetime") as fake_dt:
            fake_dt.fromtimestamp.return_value = datetime(2026, 10, 7, 9, 0)
            self.assertEqual(fake._wartet_kennungen(), ["Brücke 09:00"])

    def test_fremdes_projekt_bekommt_praefix(self):
        fake = FakeWerkbank(projekt_name="CWB")
        pfad = types.SimpleNamespace(stat=lambda: types.SimpleNamespace(st_mtime=0))
        auftrag = types.SimpleNamespace(quelle="lokal", projekt="hausgemacht", art="code",
                                         inhalt="Block 37\nx")
        with patch.object(fenster, "wartende_dateien", return_value=[pfad]), \
             patch.object(fenster, "auftrag_lesen", return_value=auftrag), \
             patch.object(fenster, "block_erkennen", return_value=(37, "x", True)), \
             patch.object(fenster, "projekt_gleichwertig", return_value=False):
            self.assertEqual(fake._wartet_kennungen(), ["hausgemacht 37"])

    def test_eigenes_projekt_bekommt_keinen_praefix(self):
        fake = FakeWerkbank(projekt_name="CWB")
        pfad = types.SimpleNamespace(stat=lambda: types.SimpleNamespace(st_mtime=0))
        auftrag = types.SimpleNamespace(quelle="lokal", projekt="CWB", art="code",
                                         inhalt="Block 37\nx")
        with patch.object(fenster, "wartende_dateien", return_value=[pfad]), \
             patch.object(fenster, "auftrag_lesen", return_value=auftrag), \
             patch.object(fenster, "block_erkennen", return_value=(37, "x", True)), \
             patch.object(fenster, "projekt_gleichwertig", return_value=True):
            self.assertEqual(fake._wartet_kennungen(), ["37"])

    def test_kaputte_datei_wird_uebersprungen(self):
        fake = FakeWerkbank()
        pfad = types.SimpleNamespace()

        def _wirft(*_args, **_kwargs):
            raise fenster.EingangsFehler("kaputt")

        with patch.object(fenster, "wartende_dateien", return_value=[pfad]), \
             patch.object(fenster, "auftrag_lesen", side_effect=_wirft):
            self.assertEqual(fake._wartet_kennungen(), [])


class StatusleisteSatzTest(unittest.TestCase):
    """core/fenster.py: Werkbank._statusleiste_satz() - derselbe Inhalt wie
    die Leiste, als gesprochener Satz fuer F2."""

    def test_ohne_wartende_auftraege(self):
        with patch.object(fenster, "wartende_dateien", return_value=[]):
            self.assertEqual(FakeWerkbank()._statusleiste_satz(), "Läuft: –. Wartet: keiner.")

    def test_mit_wartenden_auftraegen(self):
        fake = FakeWerkbank()
        fake._auftrag_laeuft = True
        fake._laufender_block_nummer = 375
        fake._warteschlange = [
            ("Text", [], None, 376, None, None, None, "Eingabe", datetime(2026, 10, 7, 16, 58)),
        ]
        with patch.object(fenster, "wartende_dateien", return_value=[]):
            self.assertEqual(fake._statusleiste_satz(), "Läuft: 375. Wartet: 376.")


class StatusleisteAktualisierenTest(unittest.TestCase):
    """core/fenster.py: Werkbank._statusleiste_aktualisieren() - zeichnet die
    beiden QLabel-Felder neu, ohne eine echte Qt-Oberflaeche zu brauchen."""

    def test_setzt_text_und_tooltip_an_beiden_feldern(self):
        fake = FakeWerkbank()
        fake._auftrag_laeuft = True
        fake._laufender_block_nummer = 375
        fake.laeuft_anzeige = MagicMock()
        fake.wartet_anzeige = MagicMock()
        with patch.object(fenster, "wartende_dateien", return_value=[]):
            fake._statusleiste_aktualisieren()
        fake.laeuft_anzeige.setText.assert_called_once_with("Läuft: 375")
        fake.wartet_anzeige.setText.assert_called_once_with("Wartet: –")
        fake.laeuft_anzeige.setToolTip.assert_called_once_with("Läuft: 375. Wartet: keiner.")
        fake.wartet_anzeige.setAccessibleDescription.assert_called_once_with(
            "Läuft: 375. Wartet: keiner.")

    def test_fehler_wird_abgefangen_statt_die_sitzung_abzubrechen(self):
        fake = FakeWerkbank()
        fake.laeuft_anzeige = MagicMock()
        fake.laeuft_anzeige.setText.side_effect = RuntimeError("kaputt")
        fake.wartet_anzeige = MagicMock()
        with patch.object(fenster, "wartende_dateien", return_value=[]):
            fake._statusleiste_aktualisieren()  # wirft nicht


if __name__ == "__main__":
    unittest.main()
