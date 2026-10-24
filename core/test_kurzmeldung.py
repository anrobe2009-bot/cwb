"""
CWB - Code Workbench
Tests fuer die Kurzmeldung statt Volltext im Chat (core/zustellwache.py,
kurzmeldung_bericht/kurzmeldung_terminal; core/fenster.py, _bericht_zustellen,
_terminal_einfuegen, _bruecke_protokoll_fertig): ein Brueckenbericht geht als
eine Zeile in den Chat, der Volltext ins Ablagefach; Fehler werden genannt; der
Schalter "bericht_voll_im_chat" bringt den Volltext zurueck; ein langes
Terminalergebnis wird gekuerzt.

Aufruf: python -m unittest core.test_kurzmeldung -v
"""

import logging
import types
import unittest
from unittest import mock

try:
    from . import fenster, zustellwache
    from .fenster import Werkbank
except ImportError:
    import fenster
    import zustellwache
    from fenster import Werkbank

log = logging.getLogger("cwb.test_kurzmeldung")


class Zeilen(unittest.TestCase):
    def test_fertig_nennt_nummer_projekt_block_protokoll_zeichen_dateien(self):
        z = zustellwache.kurzmeldung_bericht(826, "maxfriends", 815, "fertig", 42, 4800, 5)
        self.assertEqual(
            z, "CWB: Auftrag 826 fertig (maxfriends, Block 815), Protokoll 42, "
               "4800 Zeichen, 5 Dateien geändert.")

    def test_fehler_wird_genannt_und_bleibt_kurz(self):
        z = zustellwache.kurzmeldung_bericht(826, "hausgemacht", 815, "fehler", 42, 900, 0)
        self.assertEqual(z, "CWB: Auftrag 826 FEHLER (hausgemacht, Block 815), Protokoll 42.")

    def test_abbruch_wird_genannt(self):
        z = zustellwache.kurzmeldung_bericht(7, "CWB", None, "abgebrochen", 3, 10, 0)
        self.assertIn("ABGEBROCHEN (CWB)", z)

    def test_ohne_protokollnummer_verweist_auf_die_bruecke(self):
        z = zustellwache.kurzmeldung_bericht(7, "CWB", None, "fertig", None, 10, 1)
        self.assertIn("bericht_holen", z)
        self.assertIn("1 Datei geändert", z)

    def test_terminal_kurzmeldung(self):
        z = zustellwache.kurzmeldung_terminal(9, "CWB", None, True, 11, 5000)
        self.assertEqual(z, "CWB: Terminalbefehl 9 fertig (CWB), Protokoll 11, 5000 Zeichen.")
        self.assertIn("FEHLER", zustellwache.kurzmeldung_terminal(9, "CWB", None, False, 11, 5000))


class _Traeger:
    """Nur das, was _bericht_zustellen anfasst."""
    _bericht_zustellen = Werkbank._bericht_zustellen
    _bruecke_protokoll_fertig = Werkbank._bruecke_protokoll_fertig

    def __init__(self):
        self.projekt = types.SimpleNamespace(name="maxfriends")
        self.eingefuegt = []
        self.abgelegt = []
        self._bruecke_protokolle = []

    def _bruecke_bericht_einfuegen(self, nummer, text, ziel):
        self.eingefuegt.append((nummer, text, ziel))
        return True

    def _bruecke_protokoll_ablegen(self, text, art="hinweis", auftrag_nummer=None,
                                   titel=None, danach=None):
        self.abgelegt.append((text, art, auftrag_nummer, titel))
        if danach is not None:
            danach(42)


class Bericht(unittest.TestCase):
    VOLL = "Projekt: maxfriends\n" + "x" * 5000

    def _lauf(self, einstellungen, bilanz):
        t = _Traeger()
        modul = fenster
        with mock.patch.object(modul, "einstellungen_lesen", return_value=einstellungen):
            t._bericht_zustellen(826, self.VOLL, bilanz, 815, "ziel")
        return t

    def test_kurzmeldung_statt_volltext(self):
        t = self._lauf({}, {"geaendert": ["a", "b"]})
        self.assertEqual(len(t.eingefuegt), 1)
        text = t.eingefuegt[0][1]
        self.assertNotIn("xxxx", text)
        self.assertLess(len(text), 200)
        self.assertIn("Protokoll 42", text)
        self.assertIn("2 Dateien geändert", text)
        # der Volltext liegt im Ablagefach
        self.assertEqual(t.abgelegt[0][:3], (self.VOLL, "bericht", 826))

    def test_fehler_steht_in_der_zeile(self):
        t = self._lauf({}, {"fehler": "kaputt"})
        self.assertIn("FEHLER", t.eingefuegt[0][1])

    def test_schalter_an_bringt_den_volltext(self):
        t = self._lauf({"bericht_voll_im_chat": True}, {})
        self.assertEqual(t.eingefuegt, [(826, self.VOLL, "ziel")])
        self.assertEqual(t.abgelegt, [])

    def test_rueckruf_nach_dem_ablegen(self):
        t = _Traeger()
        faden = types.SimpleNamespace(danach=mock.Mock(), nummer=7)
        t._bruecke_protokoll_fertig.__wrapped__(t, faden, True) \
            if hasattr(t._bruecke_protokoll_fertig, "__wrapped__") else \
            Werkbank._bruecke_protokoll_fertig(t, faden, True)
        faden.danach.assert_called_once_with(7)
        faden.danach.reset_mock()
        Werkbank._bruecke_protokoll_fertig(t, faden, False)
        faden.danach.assert_called_once_with(None)


class Terminal(unittest.TestCase):
    def _lauf(self, ausgabe, zugang=True):
        t = mock.MagicMock()
        t.projekt = types.SimpleNamespace(name="CWB")
        t._terminal_bruecke_nummer = 5
        t._terminal_eingang_datei = None
        t._terminal_ziel = "ziel"
        t._laufender_block_nummer = None
        t._terminal_faden = types.SimpleNamespace(befehl="echo")
        t._terminal_einfuegen = mock.Mock(return_value=None)
        t._bruecke_protokoll_ablegen = mock.Mock(
            side_effect=lambda text, art, nr, titel, danach=None: danach(11))
        ergebnis = types.SimpleNamespace(ausgabe=ausgabe, fehler="", erfolg=True, code=0)
        with mock.patch.object(fenster, "UNTER_WINDOWS", False, create=True), \
             mock.patch.object(fenster.zielfenster, "UNTER_WINDOWS", False), \
             mock.patch.object(fenster, "zugangsdaten_lesen",
                               return_value=object() if zugang else None), \
             mock.patch.object(fenster, "_journal_endet"), \
             mock.patch.object(fenster, "abschliessen"), \
             mock.patch.object(fenster.auftragsjournal, "schreibe"):
            Werkbank._terminal_fertig.__wrapped__(t, ergebnis) \
                if hasattr(Werkbank._terminal_fertig, "__wrapped__") else \
                Werkbank._terminal_fertig(t, ergebnis)
        return t

    def test_kurzes_ergebnis_bleibt_volltext(self):
        t = self._lauf("ok " * 100)
        t._terminal_einfuegen.assert_called_once()
        self.assertEqual(t._terminal_einfuegen.call_args[0][3], "ok " * 100)
        t._bruecke_protokoll_ablegen.assert_not_called()

    def test_langes_ergebnis_wird_gekuerzt(self):
        lang = "z" * (zustellwache.TERMINAL_KURZ_GRENZE + 1)
        t = self._lauf(lang)
        gesendet = t._terminal_einfuegen.call_args[0][3]
        self.assertNotIn("zzzz", gesendet)
        self.assertIn("Protokoll 11", gesendet)
        self.assertEqual(t._bruecke_protokoll_ablegen.call_args[0][0], lang)

    def test_langes_ergebnis_ohne_bruecke_bleibt_volltext(self):
        lang = "z" * (zustellwache.TERMINAL_KURZ_GRENZE + 1)
        t = self._lauf(lang, zugang=False)
        self.assertEqual(t._terminal_einfuegen.call_args[0][3], lang)


class UhrNachUpload(unittest.TestCase):
    def test_vorher_hochgeladen_startet_die_uhr_sofort(self):
        geplant = []
        wache = zustellwache.Zustellwache(
            lambda *a: False, lambda ms, f: geplant.append(ms), lambda: None)
        wache.hochgeladen(826)
        wache.zustellen(826, "code", "kurz", None)
        self.assertIn(10_000, geplant)


if __name__ == "__main__":
    unittest.main()
