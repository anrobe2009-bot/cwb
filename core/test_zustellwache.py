"""
CWB - Code Workbench
Tests fuer die Zustellwache (core/zustellwache.py) und die Bild-/Rueckruf-
Erweiterung des Einfuegers (core/einfueger.py): Bild nur ueber die Bruecke,
Wiederholung bei Fehlschlag, keine Doppelzustellung, Hinweis nach 90 Sekunden
und die Zeitwache nach 15 Minuten. Ohne Fenster, Netz und Ton: Einreihen und
Zeitgeber sind Attrappen mit einer Uhr, die sich vorstellen laesst.

Aufruf: python -m unittest core.test_zustellwache -v
"""

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from . import auftragsjournal as aj
    from . import einfueger, fenster, zustellwache
except ImportError:
    import auftragsjournal as aj
    import einfueger
    import fenster
    import zustellwache

BROWSER = ("1", "Claude – Mozilla Firefox", "firefox")


class _Uhr:
    """Zeitgeber mit vorstellbarer Zeit (Millisekunden)."""

    def __init__(self):
        self.jetzt = 0
        self.eintraege = []

    def planen(self, ms, funktion):
        self.eintraege.append((self.jetzt + ms, len(self.eintraege), funktion))

    def vor(self, sekunden):
        ziel = self.jetzt + int(sekunden * 1000)
        while True:
            faellig = sorted(e for e in self.eintraege if e[0] <= ziel)
            if not faellig:
                break
            eintrag = faellig[0]
            self.eintraege.remove(eintrag)
            self.jetzt = max(self.jetzt, eintrag[0])
            eintrag[2]()
        self.jetzt = ziel


class _Einreiher:
    """Nimmt Eintraege an; `antwort` bestimmt, ob und wie der Rueckruf kommt:
    "ja", "nein" oder "offen" (Rueckruf kommt nie)."""

    def __init__(self):
        self.antwort = "ja"
        self.aufrufe = []

    def __call__(self, ziel, text, bild_pfad, kennung, rueckruf):
        self.aufrufe.append((ziel, text, bild_pfad))
        if self.antwort == "ja":
            rueckruf(True, "")
        elif self.antwort == "nein":
            rueckruf(False, "Fokus verloren")
        return True

    def texte(self):
        return [a[1] for a in self.aufrufe]


class _Grund(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.datei = Path(self.ordner.name) / "auftragsjournal.log"
        aj.zuruecksetzen()
        aj.einrichten(self.datei)
        self.uhr = _Uhr()
        self.einreiher = _Einreiher()
        self.wache = zustellwache.Zustellwache(
            self.einreiher, self.uhr.planen, lambda: BROWSER)

    def tearDown(self):
        aj.zuruecksetzen()
        for h in list(getattr(aj._schreiber, "handlers", [])):
            h.close()
        aj._schreiber = None
        self.ordner.cleanup()

    def journal(self):
        return self.datei.read_text(encoding="utf-8") if self.datei.exists() else ""


class Zustellung(_Grund):
    def test_gelungen_wird_nie_erneut_eingereiht(self):
        self.assertTrue(self.wache.zustellen(7, "code", "Bericht", BROWSER))
        self.wache.hochgeladen(7)
        self.uhr.vor(300)
        self.assertEqual(self.einreiher.texte(), ["Bericht"])
        self.assertTrue(self.wache.ist_zugestellt(7, "code"))

    def test_zweiter_aufruf_fuer_dieselbe_nummer_reiht_nichts_ein(self):
        self.wache.zustellen(7, "code", "Bericht", BROWSER)
        self.assertFalse(self.wache.zustellen(7, "code", "Bericht", BROWSER))
        self.assertEqual(len(self.einreiher.aufrufe), 1)

    def test_wiederholung_nach_10_sekunden_klappt(self):
        self.einreiher.antwort = "nein"
        self.wache.zustellen(7, "code", "Bericht", BROWSER)
        self.wache.hochgeladen(7)
        self.uhr.vor(9)
        self.assertEqual(len(self.einreiher.aufrufe), 1)
        self.einreiher.antwort = "ja"
        self.uhr.vor(2)
        self.assertEqual(len(self.einreiher.aufrufe), 2)
        self.uhr.vor(300)
        self.assertEqual(len(self.einreiher.aufrufe), 2)
        self.assertTrue(self.wache.ist_zugestellt(7, "code"))
        self.assertIn("zugestellt", self.journal())

    def test_wiederholungen_nach_10_30_und_60_sekunden_dann_hinweis(self):
        self.einreiher.antwort = "nein"
        self.wache.zustellen(7, "code", "Bericht", BROWSER)
        self.wache.hochgeladen(7)
        self.uhr.vor(11)
        self.assertEqual(len(self.einreiher.aufrufe), 2)
        self.uhr.vor(20)  # 31 s
        self.assertEqual(len(self.einreiher.aufrufe), 3)
        self.uhr.vor(30)  # 61 s
        self.assertEqual(len(self.einreiher.aufrufe), 4)
        self.assertNotIn("CWB-Hinweis", " ".join(self.einreiher.texte()))
        self.uhr.vor(30)  # 91 s
        hinweise = [t for t in self.einreiher.texte() if t.startswith("CWB-Hinweis")]
        self.assertEqual(hinweise, [
            "CWB-Hinweis: Bericht zu Auftrag 7 konnte nicht eingefuegt werden."])
        self.assertIn("zustellung_aufgegeben", self.journal())
        # Jeder Versuch steht im Journal.
        self.assertEqual(self.journal().count("wiederholung="), 3)
        self.assertEqual(self.journal().count("gescheitert grund=Fokus verloren"), 5)

    def test_kein_hinweis_wenn_zugestellt(self):
        self.einreiher.antwort = "nein"
        self.wache.zustellen(7, "code", "Bericht", BROWSER)
        self.wache.hochgeladen(7)
        self.einreiher.antwort = "ja"
        self.uhr.vor(200)
        self.assertFalse([t for t in self.einreiher.texte() if t.startswith("CWB-Hinweis")])

    def test_ausstehender_versuch_wird_nicht_doppelt_eingereiht(self):
        self.einreiher.antwort = "offen"
        self.wache.zustellen(7, "code", "Bericht", BROWSER)
        self.wache.hochgeladen(7)
        self.uhr.vor(70)
        self.assertEqual(len(self.einreiher.aufrufe), 1)
        self.assertIn("uebersprungen", self.journal())

    def test_uhr_laeuft_erst_nach_dem_hochladen(self):
        self.einreiher.antwort = "nein"
        self.wache.zustellen(7, "code", "Bericht", BROWSER)
        self.uhr.vor(60)
        self.assertEqual(len(self.einreiher.aufrufe), 1)
        self.wache.hochgeladen(7)
        self.uhr.vor(11)
        self.assertEqual(len(self.einreiher.aufrufe), 2)

    def test_notstart_ohne_upload(self):
        self.einreiher.antwort = "nein"
        self.wache.zustellen(7, "code", "Bericht", BROWSER)
        self.uhr.vor(zustellwache.UHR_NOTSTART_S + 11)
        self.assertGreaterEqual(len(self.einreiher.aufrufe), 2)

    def test_fehlendes_ziel_nimmt_das_zuletzt_bekannte(self):
        self.wache.zustellen(7, "code", "Bericht", None)
        self.assertEqual(self.einreiher.aufrufe[0][0], BROWSER)

    def test_fehler_beim_einreihen_stoert_nicht(self):
        def kaputt(*_a):
            raise RuntimeError("kaputt")
        wache = zustellwache.Zustellwache(kaputt, self.uhr.planen)
        self.assertFalse(wache.zustellen(7, "code", "Bericht", BROWSER))
        wache.hochgeladen(7)
        self.uhr.vor(200)

    def test_bild_wird_einmal_wiederholt(self):
        self.einreiher.antwort = "nein"
        self.wache.zustellen(9, "bild", "[Bild x.png]", BROWSER, bild_pfad="/tmp/x.png")
        self.uhr.vor(30)
        bilder = [a for a in self.einreiher.aufrufe if a[2] == "/tmp/x.png"]
        self.assertEqual(len(bilder), 2)
        # Danach uebernimmt die Nachlieferung und versucht still weiter.
        self.uhr.vor(600)
        bilder = [a for a in self.einreiher.aufrufe if a[2] == "/tmp/x.png"]
        self.assertGreater(len(bilder), 2)


class Zeitwache(_Grund):
    def test_nach_15_minuten_und_danach_alle_15(self):
        self.wache.auftrag_beginnt(42)
        self.uhr.vor(14 * 60)
        self.assertEqual(self.einreiher.aufrufe, [])
        self.uhr.vor(61)
        self.assertEqual(self.einreiher.texte(),
                         ["CWB-Hinweis: Auftrag 42 laeuft seit 15 Minuten."])
        self.uhr.vor(15 * 60)
        self.assertEqual(self.einreiher.texte()[1],
                         "CWB-Hinweis: Auftrag 42 laeuft seit 30 Minuten.")
        self.assertIn("zeitwache", self.journal())

    def test_fertiger_auftrag_bekommt_keinen_hinweis(self):
        self.wache.auftrag_beginnt(42)
        self.uhr.vor(10 * 60)
        self.wache.auftrag_endet(42)
        self.uhr.vor(3600)
        self.assertEqual(self.einreiher.aufrufe, [])

    def test_hinweis_wird_bei_fehlschlag_wiederholt(self):
        self.einreiher.antwort = "nein"
        self.wache.auftrag_beginnt(42)
        self.uhr.vor(15 * 60 + 11)
        hinweise = [t for t in self.einreiher.texte() if "laeuft seit 15" in t]
        self.assertEqual(len(hinweise), 2)

    def test_neuer_beginn_derselben_nummer_setzt_die_uhr_neu(self):
        self.wache.auftrag_beginnt(42)
        self.uhr.vor(10 * 60)
        self.wache.auftrag_beginnt(42)
        self.uhr.vor(10 * 60)
        self.assertEqual(self.einreiher.aufrufe, [])


# -- Einfueger: Bild und Rueckruf -------------------------------------------------


class HinweisAblage(_Grund):
    """Jeder CWB-Hinweis geht zusaetzlich ins Ablagefach der Bruecke."""

    def setUp(self):
        super().setUp()
        self.abgelegt = []
        self.wache = zustellwache.Zustellwache(
            self.einreiher, self.uhr.planen, lambda: BROWSER,
            ablegen=lambda n, art, text: self.abgelegt.append((n, art, text)))

    def test_zeitwache_hinweis_wird_abgelegt(self):
        self.wache.auftrag_beginnt(5)
        self.uhr.vor(zustellwache.LAUFZEIT_TAKT_MIN * 60 + 1)
        self.assertEqual(len(self.abgelegt), 1)
        self.assertEqual(self.abgelegt[0][:2], (5, "zeit1"))
        self.assertIn("CWB-Hinweis", self.abgelegt[0][2])

    def test_zustellwache_hinweis_wird_abgelegt(self):
        self.einreiher.antwort = "nein"
        self.wache.zustellen(7, "code", "Bericht", BROWSER)
        self.wache.hochgeladen(7)
        self.uhr.vor(zustellwache.HINWEIS_NACH_S + 1)
        self.assertEqual([a[1] for a in self.abgelegt], ["hinweis_code"])

    def test_normales_ergebnis_wird_nicht_abgelegt(self):
        self.wache.zustellen(7, "code", "Bericht", BROWSER)
        self.assertEqual(self.abgelegt, [])

    def test_fehler_beim_ablegen_stoert_die_zustellung_nicht(self):
        def kaputt(*_):
            raise RuntimeError("Ablage kaputt")
        wache = zustellwache.Zustellwache(self.einreiher, self.uhr.planen, lambda: BROWSER,
                                          ablegen=kaputt)
        self.assertTrue(wache.zustellen(9, "hinweis_x", "CWB-Hinweis: x", BROWSER))


class _Ablage:
    def __init__(self):
        self.text = ""
        self.bild = None

    def setzen(self, text):
        self.text, self.bild = text, None
        return True

    def lesen(self):
        return self.text

    def leeren(self):
        self.text, self.bild = "", None


class _Werkzeug:
    def __init__(self, ablage):
        self.ablage = ablage
        self.eingefuegt = []
        self.tasten = []
        self.strg_v_klappt = True
        self.aktiv = None

    def fenster_lesen(self, kennung=None):
        return BROWSER

    def aktivieren(self, kennung):
        self.aktiv = kennung
        return True

    def taste(self, name):
        self.tasten.append(name)
        if name == "ctrl+v":
            if not self.strg_v_klappt:
                return False
            self.eingefuegt.append(self.ablage.bild or self.ablage.text)
        return True


def _einfueger_bauen():
    ablage = _Ablage()
    werkzeug = _Werkzeug(ablage)
    geplant = []

    def bild_setzen(pfad):
        ablage.text, ablage.bild = "", pfad
        return True

    e = einfueger.Einfueger(werkzeug, ablage, lambda ms, f: geplant.append(f),
                            lambda: True, lambda *_a: None, bild_setzen)

    def laufen():
        while geplant:
            geplant.pop(0)()

    return e, ablage, werkzeug, laufen


class EinfuegerBild(unittest.TestCase):
    def test_bild_geht_mit_strg_v_und_enter_ins_fenster(self):
        e, ablage, werkzeug, laufen = _einfueger_bauen()
        meldungen = []
        e.naechster_rueckruf = lambda erfolg, grund="": meldungen.append(erfolg)
        e.hinzufuegen(BROWSER, "[Bild]", "/tmp/b.png")
        laufen()
        self.assertEqual(werkzeug.eingefuegt, ["/tmp/b.png"])
        self.assertIn("Return", werkzeug.tasten)
        self.assertEqual(meldungen, [True])
        self.assertIsNone(ablage.bild)

    def test_bild_nach_text_wird_frisch_gesetzt(self):
        e, ablage, werkzeug, laufen = _einfueger_bauen()
        e.hinzufuegen(BROWSER, "Text")
        e.hinzufuegen(BROWSER, "[Bild]", "/tmp/b.png")
        laufen()
        self.assertEqual(werkzeug.eingefuegt, ["Text", "/tmp/b.png"])

    def test_misserfolg_meldet_false_und_nichts_bleibt_liegen(self):
        e, ablage, werkzeug, laufen = _einfueger_bauen()
        werkzeug.strg_v_klappt = False
        meldungen = []
        e.naechster_rueckruf = lambda erfolg, grund="": meldungen.append((erfolg, grund))
        e.hinzufuegen(BROWSER, "[Bild]", "/tmp/b.png")
        laufen()
        self.assertEqual(meldungen, [(False, "Strg+V nicht angenommen")])
        # Bruecken-Eintrag: der Bericht liegt auf der Bruecke, in der
        # Zwischenablage bleibt nichts liegen.
        self.assertIsNone(ablage.bild)
        self.assertEqual(ablage.text, "")

    def test_kein_ziel_meldet_false(self):
        e, _a, _w, laufen = _einfueger_bauen()
        meldungen = []
        e.naechster_rueckruf = lambda erfolg, grund="": meldungen.append(erfolg)
        # Verwaltete Eintraege suchen den Chat selbst (1.13.3); hier findet
        # die Suche keinen.
        original = einfueger.ziel_finden
        einfueger.ziel_finden = lambda werkzeug=None: None
        self.addCleanup(setattr, einfueger, "ziel_finden", original)
        e.hinzufuegen(None, "Text")
        laufen()
        self.assertEqual(meldungen, [False])

    def test_fehler_im_rueckruf_stoert_nicht(self):
        e, _a, werkzeug, laufen = _einfueger_bauen()

        def kaputt(erfolg, grund=""):
            raise RuntimeError("kaputt")
        e.naechster_rueckruf = kaputt
        e.hinzufuegen(BROWSER, "eins")
        e.hinzufuegen(BROWSER, "zwei")
        laufen()
        self.assertEqual(werkzeug.eingefuegt, ["eins", "zwei"])

    def test_spaeter_zugestellter_text_bleibt_nicht_in_der_ablage(self):
        e, ablage, werkzeug, laufen = _einfueger_bauen()
        werkzeug.strg_v_klappt = False
        e.hinzufuegen(BROWSER, "Bericht")
        laufen()
        self.assertEqual(ablage.text, "Bericht")
        werkzeug.strg_v_klappt = True
        e.hinzufuegen(BROWSER, "Bericht")
        laufen()
        self.assertEqual(ablage.text, "")
        self.assertEqual(werkzeug.eingefuegt, ["Bericht"])


# -- Fenster: Bild nur bei Bruecke ------------------------------------------------


class BildFertig(unittest.TestCase):
    """Werkbank._bild_fertig auf einem nachgebildeten Fenster."""

    def _fenster(self, bruecke_nummer):
        f = types.SimpleNamespace()
        f._bild_bruecke_nummer = bruecke_nummer
        f._bild_eingang_datei = None
        f._bild_ziel = BROWSER
        f._laufender_block_nummer = None
        for name in ("_statusleiste_aktualisieren", "_status_zeigen",
                     "_bruecke_bericht_hochladen", "_bild_hinweis"):
            setattr(f, name, MagicMock())
        f.sprecher = MagicMock()
        f._zustellen_versuchen = MagicMock(return_value=True)
        f._bild_in_chat = lambda n, p: fenster.Werkbank._bild_in_chat(f, n, p)
        return f

    def _ergebnis(self):
        return types.SimpleNamespace(erfolg=True, pfad="/tmp/s.png", breite=10,
                                     hoehe=20, fehler="")

    def test_ohne_bruecke_nur_zwischenablage(self):
        f = self._fenster(None)
        with patch.object(fenster.zielfenster, "bild_in_zwischenablage_legen",
                          return_value=True), \
                patch.object(fenster.zielfenster, "UNTER_WINDOWS", False):
            fenster.Werkbank._bild_fertig(f, self._ergebnis())
        f._zustellen_versuchen.assert_not_called()

    def test_mit_bruecke_geht_das_bild_in_den_chat(self):
        f = self._fenster(55)
        with patch.object(fenster.zielfenster, "bild_in_zwischenablage_legen",
                          return_value=True), \
                patch.object(fenster.zielfenster, "UNTER_WINDOWS", False):
            fenster.Werkbank._bild_fertig(f, self._ergebnis())
        f._zustellen_versuchen.assert_called_once()
        args, kwargs = f._zustellen_versuchen.call_args
        self.assertEqual(args[0], 55)
        self.assertEqual(args[1], "bild")
        self.assertEqual(args[3], BROWSER)
        self.assertEqual(kwargs.get("bild_pfad"), "/tmp/s.png")

    def test_mit_bruecke_unter_windows_bleibt_alles_wie_bisher(self):
        f = self._fenster(55)
        with patch.object(fenster.zielfenster, "bild_in_zwischenablage_legen",
                          return_value=True), \
                patch.object(fenster.zielfenster, "UNTER_WINDOWS", True):
            fenster.Werkbank._bild_fertig(f, self._ergebnis())
        f._zustellen_versuchen.assert_not_called()


class ZeitwacheHaken(unittest.TestCase):
    def test_nur_bruecke_meldet_an_die_wache(self):
        wache = MagicMock()
        f = types.SimpleNamespace(_zustellwache_holen=lambda: wache)
        fenster._zeitwache_melden(f, None, True)
        wache.auftrag_beginnt.assert_not_called()
        fenster._zeitwache_melden(f, 5, True)
        wache.auftrag_beginnt.assert_called_once_with(5)
        fenster._zeitwache_melden(f, 5, False)
        wache.auftrag_endet.assert_called_once_with(5)

    def test_fehler_der_wache_stoert_nicht(self):
        def kaputt():
            raise RuntimeError("kaputt")
        fenster._zeitwache_melden(types.SimpleNamespace(_zustellwache_holen=kaputt), 5, True)


if __name__ == "__main__":
    unittest.main()
