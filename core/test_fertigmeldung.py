"""
CWB - Code Workbench
Tests zur Fertigmeldung bei Bruecken-Auftraegen (Block 737):

- der Bericht eines #CODE#-Bruecken-Auftrags geht hoechstens einmal ins
  Chatfenster (core/fenster.py, _bruecke_bericht_einfuegen) - auch das
  Nachlegen beim Aktivieren (_bericht_nachlegen) fuegt ihn nicht noch einmal
  an,
- die nachgelegte Ansage bricht die "Fertig."-Ansage nicht ab,
- jede Ansage hinterlaesst "Wiedergabe gestartet/beendet/Fehler" im Log
  (core/sprache.py),
- ein fehlgeschlagener Berichts-Upload wird einmal wiederholt, danach ERROR
  (core/bruecke.py, BerichtFaden).

Baut keine echte Werkbank auf: ein schlankes Objekt traegt die echten,
ungebundenen Methoden. Kein Netz, kein Ton, keine einstellungen.json.

Aufruf: python -m unittest core.test_fertigmeldung -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    from . import bruecke, sprache
    from .fenster import Werkbank
except ImportError:
    import bruecke
    import sprache
    from fenster import Werkbank


class _Traeger:
    _bruecke_bericht_einfuegen = Werkbank._bruecke_bericht_einfuegen
    _bericht_nachlegen = Werkbank._bericht_nachlegen
    _ansage_sprechen = Werkbank._ansage_sprechen
    _zustellwache_holen = Werkbank._zustellwache_holen
    _zustellen_versuchen = Werkbank._zustellen_versuchen
    _zustell_einreihen = Werkbank._zustell_einreihen

    def __init__(self):
        self._bruecke_eingefuegt = set()
        self._letzter_bericht_bruecke = None
        self._letzter_bericht = "Bericht"
        self._bericht_wartet = False
        self._bericht_ablegen = mock.Mock(return_value=" Bericht-Text liegt in der Zwischenablage.")
        self.sprecher = mock.Mock()
        self._einfueger = mock.Mock()
        self._einfueger.wartend.return_value = 0
        self._einfueger_holen = mock.Mock(return_value=self._einfueger)
        self._ansagen = []
        self._ablage_hinweis = False
        self._ansage_zeitgeber = mock.Mock()


ZIEL = ("123", "Claude - Chrome", "google-chrome")


class EinmalEinfuegenTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(sys.modules[Werkbank.__module__], "zielfenster")
        self.zf = patcher.start()
        self.addCleanup(patcher.stop)
        self.zf.UNTER_WINDOWS = False
        self.t = _Traeger()

    def test_bericht_geht_einmal_in_den_einfueger(self):
        self.assertTrue(self.t._bruecke_bericht_einfuegen(7, "Text", ZIEL))
        self.t._einfueger.hinzufuegen.assert_called_once_with(ZIEL, "Text")

    def test_zweiter_aufruf_fuer_dieselbe_nummer_fuegt_nicht_erneut_ein(self):
        self.t._bruecke_bericht_einfuegen(7, "Text", ZIEL)
        self.assertFalse(self.t._bruecke_bericht_einfuegen(7, "Text", ZIEL))
        self.assertEqual(self.t._einfueger.hinzufuegen.call_count, 1)

    def test_andere_nummer_wird_eingefuegt(self):
        self.t._bruecke_bericht_einfuegen(7, "A", ZIEL)
        self.t._bruecke_bericht_einfuegen(8, "B", ZIEL)
        self.assertEqual(self.t._einfueger.hinzufuegen.call_count, 2)

    def test_leerer_text_wird_nicht_eingefuegt_und_nicht_vermerkt(self):
        self.assertFalse(self.t._bruecke_bericht_einfuegen(7, "", ZIEL))
        self.assertNotIn(7, self.t._bruecke_eingefuegt)

    def test_windows_weg_nutzt_zielfenster(self):
        self.zf.UNTER_WINDOWS = True
        self.zf.einfuegen.return_value = True
        self.assertTrue(self.t._bruecke_bericht_einfuegen(7, "Text", ZIEL))
        self.zf.einfuegen.assert_called_once_with(ZIEL, "Text")
        self.t._einfueger.hinzufuegen.assert_not_called()

    def test_nachlegen_ueberspringt_schon_eingefuegten_bericht(self):
        self.t._bruecke_bericht_einfuegen(7, "Text", ZIEL)
        self.t._letzter_bericht_bruecke = 7
        self.t._bericht_wartet = True
        self.t._bericht_nachlegen()
        self.t._bericht_ablegen.assert_not_called()
        self.t.sprecher.sprich.assert_not_called()
        self.assertFalse(self.t._bericht_wartet)

    def test_nachlegen_bleibt_fuer_fenster_auftraege_wie_bisher(self):
        self.t._letzter_bericht_bruecke = None
        self.t._bericht_wartet = True
        self.t._bericht_nachlegen()
        self.t._bericht_ablegen.assert_called_once()

    def test_nachgelegte_ansage_unterbricht_nicht(self):
        self.t._bericht_wartet = True
        self.t._bericht_nachlegen()
        _args, kwargs = self.t.sprecher.sprich.call_args
        self.assertIs(kwargs.get("unterbrechen"), False)

    def test_nur_hinweis_ohne_terminalansage_unterbricht_nicht(self):
        self.t._ablage_hinweis = True
        # Der Hinweis wird nur gesagt, wenn die Zwischenablage wirklich etwas enthaelt.
        with mock.patch.object(sys.modules[Werkbank.__module__], "QGuiApplication") as qt:
            qt.clipboard.return_value.text.return_value = "Ergebnis"
            self.t._ansage_sprechen()
        _args, kwargs = self.t.sprecher.sprich.call_args
        self.assertIs(kwargs.get("unterbrechen"), False)
        self.assertIn("Zwischenablage", _args[0])

    def test_hinweis_entfaellt_bei_leerer_zwischenablage(self):
        self.t._ablage_hinweis = True
        with mock.patch.object(sys.modules[Werkbank.__module__], "QGuiApplication") as qt:
            qt.clipboard.return_value.text.return_value = ""
            self.t._ansage_sprechen()
        _args, _kwargs = self.t.sprecher.sprich.call_args
        self.assertNotIn("Zwischenablage", _args[0])

    def test_terminalansage_unterbricht_wie_bisher(self):
        self.t._ansagen = [("Terminalbefehl fertig.", True)]
        self.t._ansage_sprechen()
        _args, kwargs = self.t.sprecher.sprich.call_args
        self.assertIs(kwargs.get("unterbrechen"), True)


class WiedergabeLogTest(unittest.TestCase):
    def _traeger(self, code, mp3_da=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        datei = Path(tmp.name) / "x.mp3"
        if mp3_da:
            datei.write_bytes(b"x")
        return SimpleNamespace(
            weg="edge", _nvda=None, _sapi=None, _sprech_generation=1,
            _letzter_weg="", _aktuell_sprechend=False,
            _pfad_fuer=lambda text: datei,
            _erzeugen=lambda text, ziel: False,
            _abspieler=mock.Mock(spiele=mock.Mock(return_value=code)),
            _wiedergabe_beendet=sprache.Sprecher._wiedergabe_beendet,
        )

    def test_start_und_ende_stehen_im_log(self):
        t = self._traeger(0)
        with self.assertLogs("cwb.sprache", level="INFO") as aufnahme:
            sprache.Sprecher._sprich_jetzt(t, 1, "Fertig.")
        text = "\n".join(aufnahme.output)
        self.assertIn("Wiedergabe gestartet (edge): Fertig.", text)
        self.assertIn("Wiedergabe beendet (edge): Fertig.", text)

    def test_abbruch_per_signal_wird_als_abgebrochen_geloggt(self):
        t = self._traeger(-15)
        with self.assertLogs("cwb.sprache", level="INFO") as aufnahme:
            sprache.Sprecher._sprich_jetzt(t, 1, "Fertig.")
        self.assertIn("Wiedergabe abgebrochen", "\n".join(aufnahme.output))

    def test_fehlercode_ist_ein_error(self):
        t = self._traeger(1)
        with self.assertLogs("cwb.sprache", level="ERROR") as aufnahme:
            sprache.Sprecher._sprich_jetzt(t, 1, "Fertig.")
        self.assertIn("Wiedergabe fehlgeschlagen", "\n".join(aufnahme.output))

    def test_ohne_mp3_und_ohne_sapi_ist_es_ein_error(self):
        t = self._traeger(0, mp3_da=False)
        t._pfad_fuer = lambda text: Path("/nicht/da.mp3")
        with self.assertLogs("cwb.sprache", level="ERROR") as aufnahme:
            sprache.Sprecher._sprich_jetzt(t, 1, "Fertig.")
        self.assertIn("Wiedergabe nicht moeglich", "\n".join(aufnahme.output))

    def test_ueberholte_ansage_wird_als_verworfen_geloggt(self):
        t = self._traeger(0)
        with self.assertLogs("cwb.sprache", level="INFO") as aufnahme:
            sprache.Sprecher._sprich_jetzt(t, 0, "Fertig.")
        self.assertIn("Wiedergabe verworfen", "\n".join(aufnahme.output))
        t._abspieler.spiele.assert_not_called()


class BerichtWiederholungTest(unittest.TestCase):
    def setUp(self):
        self.faden = bruecke.BerichtFaden(5, "Bericht")
        self.ergebnisse = []
        self.faden.fertig_da.connect(self.ergebnisse.append)
        zugang = bruecke.Zugangsdaten("https://x.invalid/geheim/mcp", "tok")
        for p in (
            mock.patch.object(bruecke, "zugangsdaten_lesen", return_value=zugang),
            mock.patch.object(self.faden, "_pausieren"),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_kennzeile_steht_im_hochgeladenen_text(self):
        faden = bruecke.BerichtFaden(7, "Bericht", block=42)
        with mock.patch.object(bruecke, "zugangsdaten_lesen",
                               return_value=bruecke.Zugangsdaten("https://x.invalid/g/mcp", "t")):
            with mock.patch.object(bruecke, "bericht_hochladen") as hoch:
                faden.run()
        text = hoch.call_args.args[2]
        kopf, rest = text.split("\n", 1)
        self.assertTrue(bruecke.KENNZEILE_MUSTER.match(kopf))
        self.assertTrue(kopf.startswith("Auftrag 7 | Block 42 | Zeit "))
        self.assertEqual(rest, "Bericht")

    def test_vorhandene_kennzeile_wird_nicht_verdoppelt(self):
        kopf = "Auftrag 7 | Block - | Zeit 2026-10-22T11:00:00+02:00"
        self.assertEqual(bruecke.mit_kennzeile(7, 3, kopf + "\nx"), kopf + "\nx")
        self.assertTrue(bruecke.mit_kennzeile(7, None, "x").startswith("Auftrag 7 | Block - | Zeit "))

    def test_ohne_nummer_kein_upload(self):
        faden = bruecke.BerichtFaden(None, "Bericht")
        erg = []
        faden.fertig_da.connect(erg.append)
        with mock.patch.object(bruecke, "bericht_hochladen") as hoch:
            with self.assertLogs("cwb.bruecke", level="ERROR"):
                faden.run()
        hoch.assert_not_called()
        self.assertEqual(erg, [False])

    def test_zweiter_versuch_klappt(self):
        with mock.patch.object(bruecke, "bericht_hochladen",
                               side_effect=[bruecke.BrueckenFehler("x"), None]) as hoch:
            self.faden.run()
        self.assertEqual(hoch.call_count, 2)
        self.assertEqual(self.ergebnisse, [True])
        self.faden._pausieren.assert_called_once()

    def test_erfolg_beim_ersten_versuch_wartet_nicht(self):
        with mock.patch.object(bruecke, "bericht_hochladen") as hoch:
            self.faden.run()
        self.assertEqual(hoch.call_count, 1)
        self.assertEqual(self.ergebnisse, [True])
        self.faden._pausieren.assert_not_called()

    def test_zweimal_scheitern_ist_ein_error(self):
        with mock.patch.object(bruecke, "bericht_hochladen",
                               side_effect=bruecke.BrueckenFehler("x")) as hoch:
            with self.assertLogs("cwb.bruecke", level="ERROR"):
                self.faden.run()
        self.assertEqual(hoch.call_count, bruecke.BERICHT_VERSUCHE)
        self.assertEqual(self.ergebnisse, [False])


if __name__ == "__main__":
    unittest.main()
