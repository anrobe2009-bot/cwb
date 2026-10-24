"""
CWB - Code Workbench
Tests zum Sammeln statt Draengeln (Ergaenzung zu Block 801): Ergebnisse, die
nicht sicher zugestellt werden koennen, warten bei der Zustellwache; nach 20
Sekunden gibt es EINE Ansage; bei ruhiger Luft stellt CWB von selbst zu; die
Zustelltaste (Strg+F8) stellt alle der Reihe nach zu; die Kachel zeigt die Zahl.

Ohne Fenster, Netz und Ton: Einreihen, Pruefung und Zeitgeber sind Attrappen.

Aufruf: python -m unittest core.test_ergebnisse_sammeln -v
"""

import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import auftragsjournal as aj
    from . import fenster, zustellwache
except ImportError:
    import auftragsjournal as aj
    import fenster
    import zustellwache

CHAT = ("1", "Frage - Claude - Mozilla Firefox", "firefox")



def setUpModule():
    import os
    import tempfile
    os.environ["CWB_ANSAGEN_DATEI"] = os.path.join(tempfile.mkdtemp(), "ansagen.json")

class _Uhr:
    def __init__(self):
        self.jetzt = 0
        self.eintraege = []
        self._zaehler = 0

    def planen(self, ms, funktion):
        self._zaehler += 1
        self.eintraege.append((self.jetzt + ms, self._zaehler, funktion))

    def vor(self, sekunden):
        ziel = self.jetzt + int(sekunden * 1000)
        while True:
            faellig = sorted(x for x in self.eintraege if x[0] <= ziel)
            if not faellig:
                break
            eintrag = faellig[0]
            self.eintraege.remove(eintrag)
            self.jetzt = max(self.jetzt, eintrag[0])
            eintrag[2]()
        self.jetzt = ziel


class _Grund(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.datei = Path(self.ordner.name) / "auftragsjournal.log"
        aj.zuruecksetzen()
        aj.einrichten(self.datei)
        self.uhr = _Uhr()
        self.luft_rein = False          # Robert tippt / kein Chat
        self.zugestellt = []            # (Text, Zeitpunkt in ms, Kennung)
        self.versuche = 0
        self.berichte_versucht = 0
        self.ansagen = []
        self.kachel = []
        self.pruefungen = []

        def einreihen(ziel, text, bild, kennung, rueckruf):
            self.versuche += 1
            if text.startswith("Bericht"):
                self.berichte_versucht += 1
            manuell = bool((kennung or {}).get("manuell"))
            if self.luft_rein or manuell:
                self.zugestellt.append((text, self.uhr.jetzt, kennung))
                rueckruf(True, "")
            else:
                rueckruf(False, "Eingabe laeuft (Ruhe 800 ms, noetig 10000)")
            return True

        def pruefen(ziel, manuell=False):
            self.pruefungen.append(manuell)
            if manuell or self.luft_rein:
                return True, ""
            return False, "Eingabe laeuft"

        self.wache = zustellwache.Zustellwache(
            einreihen, self.uhr.planen, lambda: CHAT,
            self.ansagen.append, pruefen, self.kachel.append)

    def tearDown(self):
        aj.zuruecksetzen()
        for h in list(getattr(aj._schreiber, "handlers", [])):
            h.close()
        aj._schreiber = None
        self.ordner.cleanup()

    def liefern(self, *nummern):
        for n in nummern:
            self.wache.zustellen(n, "code", f"Bericht {n}", CHAT)
            self.wache.hochgeladen(n)

    def texte(self):
        return [z[0] for z in self.zugestellt]


class WartetBeiEingabe(_Grund):
    def test_eintrag_bleibt_in_der_warteschlange(self):
        self.liefern(7)
        self.uhr.vor(600)
        self.assertEqual(self.zugestellt, [])
        self.assertEqual(len(self.wache.wartende_ergebnisse()), 1)

    def test_keine_versuche_waehrend_robert_tippt_ausser_dem_festen_takt(self):
        self.liefern(7)
        self.uhr.vor(60)            # erste Versuche + die festen Wiederholungen
        versuche_nach_der_minute = self.berichte_versucht
        self.uhr.vor(3600)
        self.assertEqual(self.berichte_versucht, versuche_nach_der_minute)   # nur geprueft

    def test_ansage_erst_nach_20_sekunden_und_nur_einmal(self):
        self.liefern(7)
        self.uhr.vor(19)
        self.assertEqual(self.ansagen, [])
        self.uhr.vor(2)
        self.assertEqual(self.ansagen, [1])
        self.uhr.vor(3600)
        self.assertEqual(self.ansagen, [1])

    def test_ansage_wiederholt_sich_nur_wenn_die_zahl_steigt(self):
        self.liefern(7, 8)
        self.uhr.vor(30)
        self.assertEqual(self.ansagen, [2])
        self.liefern(9)
        self.uhr.vor(30)
        self.assertEqual(self.ansagen, [2, 3])
        self.uhr.vor(600)
        self.assertEqual(self.ansagen, [2, 3])

    def test_kachel_zaehlt_mit_und_verschwindet(self):
        self.liefern(7, 8)
        self.uhr.vor(5)
        self.assertEqual(self.kachel[-1], 2)
        self.luft_rein = True
        self.uhr.vor(60)
        self.assertEqual(self.kachel[-1], 0)


class StelltBeiRuheVonSelbstZu(_Grund):
    def test_ruhige_luft_stellt_ohne_nachfrage_zu(self):
        self.liefern(7)
        self.uhr.vor(30)
        self.luft_rein = True
        self.uhr.vor(10)
        self.assertEqual(self.texte(), ["Bericht 7"])
        self.assertEqual(self.wache.wartende_ergebnisse(), [])

    def test_sofort_wenn_die_luft_von_anfang_an_rein_ist(self):
        self.luft_rein = True
        self.liefern(7)
        self.assertEqual(self.texte(), ["Bericht 7"])
        self.uhr.vor(3600)
        self.assertEqual(self.ansagen, [])          # nichts gewartet: keine Ansage
        self.assertEqual(self.texte(), ["Bericht 7"])

    def test_reihenfolge_zwei_sekunden_abstand_und_keine_doppelzustellung(self):
        self.liefern(7, 8, 9)
        self.uhr.vor(60)
        self.luft_rein = True
        self.uhr.vor(60)
        self.assertEqual(self.texte(), ["Bericht 7", "Bericht 8", "Bericht 9"])
        zeiten = [z[1] for z in self.zugestellt]
        self.assertTrue(all(b - a >= 2000 for a, b in zip(zeiten, zeiten[1:])), zeiten)
        self.uhr.vor(3600)
        self.assertEqual(len(self.zugestellt), 3)


class ZustellTaste(_Grund):
    def test_taste_stellt_alle_der_reihe_nach_zu_auch_bei_unruhe(self):
        self.liefern(7, 8, 9)
        self.uhr.vor(30)
        self.assertEqual(self.zugestellt, [])        # Robert tippt noch
        zahl, grund = self.wache.vorbereiten_manuell()
        self.assertEqual((zahl, grund), (3, ""))
        self.wache.manuell_starten()
        self.uhr.vor(20)
        self.assertEqual(self.texte(), ["Bericht 7", "Bericht 8", "Bericht 9"])
        zeiten = [z[1] for z in self.zugestellt]
        self.assertTrue(all(b - a >= 2000 for a, b in zip(zeiten, zeiten[1:])), zeiten)
        self.assertTrue(all(z[2].get("manuell") for z in self.zugestellt))
        self.uhr.vor(3600)
        self.assertEqual(len(self.zugestellt), 3)     # nichts doppelt
        self.assertEqual(self.kachel[-1], 0)

    def test_ohne_wartende_meldet_die_taste_null(self):
        self.assertEqual(self.wache.vorbereiten_manuell(), (0, ""))

    def test_kein_chat_erreichbar_wird_gesagt_und_nichts_versucht(self):
        self.liefern(7)
        self.uhr.vor(30)

        def nie(ziel, manuell=False):
            return False, "kein Chatfenster"
        self.wache._pruefen = nie
        zahl, grund = self.wache.vorbereiten_manuell()
        self.assertEqual((zahl, grund), (1, "kein Chatfenster"))

    def test_taste_ohne_erfolg_laeuft_nicht_endlos(self):
        self.liefern(7)
        self.uhr.vor(30)
        self.wache._einreihen = lambda z, t, b, k, r: (r(False, "Strg+V nicht angenommen"), True)[1]
        self.wache.vorbereiten_manuell()
        self.wache.manuell_starten()
        versuche_vorher = self.versuche
        self.uhr.vor(60)
        self.assertEqual(self.wache._manuell, False)
        self.assertEqual(self.versuche, versuche_vorher)


class FensterSeite(unittest.TestCase):
    def _fenster(self, zahl, grund=""):
        f = types.SimpleNamespace()
        f.sprecher = mock.Mock()
        wache = mock.Mock()
        wache.vorbereiten_manuell.return_value = (zahl, grund)
        f._zustellwache_holen = lambda: wache
        f.wache = wache
        return f

    def test_taste_ohne_wartende(self):
        f = self._fenster(0)
        fenster.Werkbank._ergebnisse_zustellen(f)
        self.assertEqual(f.sprecher.sprich.call_args[0][0], "Keine Ergebnisse warten.")
        f.wache.manuell_starten.assert_not_called()

    def test_taste_sagt_vorher_an_und_stellt_zu(self):
        f = self._fenster(3)
        fenster.Werkbank._ergebnisse_zustellen(f)
        self.assertEqual(f.sprecher.sprich.call_args[0][0], "Stelle 3 Ergebnisse zu.")
        f.wache.manuell_starten.assert_called_once()

    def test_taste_nennt_den_grund_wenn_es_nicht_geht(self):
        f = self._fenster(2, "kein Chatfenster")
        fenster.Werkbank._ergebnisse_zustellen(f)
        self.assertIn("kein Chatfenster", f.sprecher.sprich.call_args[0][0])
        f.wache.manuell_starten.assert_not_called()

    def test_ansage_text(self):
        f = types.SimpleNamespace(sprecher=mock.Mock())
        fenster.Werkbank._zustellung_ansagen(f, 3)
        self.assertEqual(f.sprecher.sprich.call_args[0][0],
                         "3 Ergebnisse warten. Mit Strg+F8 zustellen.")
        fenster.Werkbank._zustellung_ansagen(f, 1)
        self.assertEqual(f.sprecher.sprich.call_args[0][0],
                         "Ein Ergebnis wartet. Mit Strg+F8 zustellen.")

    def test_kachel_zeigt_zahl_und_blendet_bei_null_aus(self):
        f = types.SimpleNamespace(kacheln=mock.Mock())
        fenster.Werkbank._zustell_kachel_zeigen(f, 2)
        f.kacheln.kachel_beschriften.assert_called_once()
        self.assertIn("(2)", f.kacheln.kachel_beschriften.call_args[0][1])
        f.kacheln.kachel_zeigen.assert_called_with(fenster.ZUSTELL_KENNUNG, True)
        fenster.Werkbank._zustell_kachel_zeigen(f, 0)
        f.kacheln.kachel_zeigen.assert_called_with(fenster.ZUSTELL_KENNUNG, False)

    def test_taste_ist_belegt_und_nur_einmal_vergeben(self):
        quelle = Path(fenster.__file__).read_text(encoding="utf-8")
        self.assertEqual(quelle.count('("Ctrl+F8", self._ergebnisse_zustellen)'), 1)
        self.assertEqual(quelle.count('"Ctrl+F8"'), 1)


if __name__ == "__main__":
    unittest.main()
