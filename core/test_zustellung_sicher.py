"""
CWB - Code Workbench
Tests zur sicheren Zustellung (Block 801): Bruecken-Eintraege werden nur in ein
echtes Chatfenster eingefuegt, nie waehrend Robert tippt, die Zwischenablage
bleibt sauber, unzustellbare Eintraege kommen der Reihe nach und genau einmal
spaeter an, und es gibt hoechstens eine Ansage je Eintrag.

Ohne Fenster, Netz und Ton: Werkzeug, Zwischenablage und Zeitgeber sind
Attrappen.

Aufruf: python -m unittest core.test_zustellung_sicher -v
"""

import tempfile
import unittest
from pathlib import Path

try:
    from . import auftragsjournal as aj
    from . import einfueger, zustellwache
except ImportError:
    import auftragsjournal as aj
    import einfueger
    import zustellwache

CHAT = ("1", "Meine Frage - Claude - Mozilla Firefox", "firefox")
TERMINAL = ("2", "claude - Terminal", "gnome-terminal-server")
FREMD = ("3", "Notizen", "gedit")


class _Ablage:
    def __init__(self, text=""):
        self.text = text
        self.bild = None
        self.verlauf = []

    def setzen(self, text):
        self.text, self.bild = text, None
        self.verlauf.append(text)
        return True

    def lesen(self):
        return self.text

    def leeren(self):
        self.text, self.bild = "", None


class _Werkzeug:
    def __init__(self, ablage, fenster, leerlauf=60000, vorn=None):
        self.ablage = ablage
        self.fenster = {f[0]: f for f in fenster}
        self.aktiv = vorn
        self.leerlauf = leerlauf
        self.tasten = []
        self.eingefuegt = []
        self.aktivierungen = 0

    def fenster_lesen(self, kennung=None):
        return self.fenster.get(kennung or self.aktiv)

    def aktivieren(self, kennung):
        self.aktivierungen += 1
        self.aktiv = kennung
        return True

    def leerlauf_ms(self):
        return self.leerlauf

    def taste(self, name):
        self.tasten.append(name)
        if name == "ctrl+v":
            self.eingefuegt.append(self.ablage.bild or self.ablage.text)
        return True


def _bauen(ablage=None, fenster=(CHAT, TERMINAL, FREMD), **w):
    ablage = ablage or _Ablage()
    werkzeug = _Werkzeug(ablage, fenster, **w)
    geplant = []
    e = einfueger.Einfueger(werkzeug, ablage, lambda ms, f: geplant.append((ms, f)),
                            lambda: True, lambda *_a: None)

    def laufen():
        while geplant:
            geplant.pop(0)[1]()

    return e, ablage, werkzeug, laufen, geplant


def _liefern(e, ziel, text, meldungen=None):
    """Reiht einen Bruecken-Eintrag (mit Rueckruf) ein."""
    liste = meldungen if meldungen is not None else []
    e.naechster_rueckruf = lambda erfolg, grund="": liste.append((erfolg, grund))
    e.hinzufuegen(ziel, text)
    return liste


class KeinFremdesFenster(unittest.TestCase):
    def test_fremdes_fenster_bekommt_weder_text_noch_enter(self):
        e, ablage, werkzeug, laufen, _g = _bauen()
        meldungen = _liefern(e, FREMD, "Bericht")
        laufen()
        self.assertEqual(werkzeug.tasten, [])
        self.assertEqual(werkzeug.aktivierungen, 0)
        self.assertEqual(ablage.verlauf, [])          # nicht einmal angefasst
        self.assertEqual(meldungen, [(False, "kein Chatfenster")])

    def test_terminal_mit_claude_im_titel_ist_kein_chat(self):
        e, ablage, werkzeug, laufen, _g = _bauen()
        meldungen = _liefern(e, TERMINAL, "Bericht")
        laufen()
        self.assertEqual(werkzeug.tasten, [])
        self.assertEqual(meldungen, [(False, "kein Chatfenster")])

    def test_titel_hat_sich_geaendert_dann_wird_frisch_geprueft(self):
        e, ablage, werkzeug, laufen, _g = _bauen()
        werkzeug.fenster["1"] = ("1", "Terminal", "firefox")   # Tab gewechselt
        meldungen = _liefern(e, CHAT, "Bericht")
        laufen()
        self.assertEqual(werkzeug.tasten, [])
        self.assertEqual(meldungen[0][1], "kein Chatfenster")

    def test_verschwundenes_fenster_wird_nicht_beschrieben(self):
        e, ablage, werkzeug, laufen, _g = _bauen()
        del werkzeug.fenster["1"]
        meldungen = _liefern(e, CHAT, "Bericht")
        laufen()
        self.assertEqual(meldungen, [(False, "Zielfenster nicht lesbar")])
        self.assertEqual(werkzeug.tasten, [])

    def test_echter_chat_wird_beliefert(self):
        e, ablage, werkzeug, laufen, _g = _bauen()
        meldungen = _liefern(e, CHAT, "Bericht")
        laufen()
        self.assertEqual(werkzeug.eingefuegt, ["Bericht"])
        self.assertIn("Return", werkzeug.tasten)
        self.assertEqual(meldungen, [(True, "")])

    def test_ohne_bruecken_rueckruf_bleibt_der_alte_weg(self):
        # #RUN#-Ergebnis in das Fenster, aus dem der Auftrag kam (z. B. Notizen)
        e, ablage, werkzeug, laufen, _g = _bauen()
        e.hinzufuegen(FREMD, "Ergebnis")
        laufen()
        self.assertEqual(werkzeug.eingefuegt, ["Ergebnis"])
        self.assertNotIn("Return", werkzeug.tasten)


class RobertTippt(unittest.TestCase):
    def test_zu_kurze_ruhe_haelt_die_zustellung_zurueck(self):
        e, ablage, werkzeug, laufen, _g = _bauen(leerlauf=1000)
        meldungen = _liefern(e, CHAT, "Bericht")
        laufen()
        self.assertEqual(werkzeug.tasten, [])
        self.assertEqual(werkzeug.aktivierungen, 0)
        self.assertEqual(ablage.verlauf, [])
        self.assertFalse(meldungen[0][0])
        self.assertIn("Eingabe laeuft", meldungen[0][1])

    def test_drei_sekunden_ruhe_genuegen_wenn_der_chat_nicht_vorn_ist(self):
        e, ablage, werkzeug, laufen, _g = _bauen(leerlauf=2000, vorn="3")
        meldungen = _liefern(e, CHAT, "Bericht")
        laufen()
        self.assertFalse(meldungen[0][0])
        e2, _a2, _w2, laufen2, _g2 = _bauen(leerlauf=3500, vorn="3")
        meldungen2 = _liefern(e2, CHAT, "Bericht")
        laufen2()
        self.assertEqual(meldungen2, [(True, "")])

    def test_steht_der_chat_vorn_sind_drei_sekunden_noetig(self):
        e, ablage, werkzeug, laufen, _g = _bauen(leerlauf=2000, vorn="1")
        meldungen = _liefern(e, CHAT, "Bericht")
        laufen()
        self.assertFalse(meldungen[0][0])
        e2, _a2, w2, laufen2, _g2 = _bauen(leerlauf=3500, vorn="1")
        meldungen2 = _liefern(e2, CHAT, "Bericht")
        laufen2()
        self.assertEqual(meldungen2, [(True, "")])

    def test_ohne_leerlaufzeit_nicht_in_den_vorn_stehenden_chat(self):
        e, ablage, werkzeug, laufen, _g = _bauen(leerlauf=None, vorn="1")
        meldungen = _liefern(e, CHAT, "Bericht")
        laufen()
        self.assertFalse(meldungen[0][0])
        self.assertEqual(werkzeug.tasten, [])

    def test_ohne_leerlaufzeit_chat_im_hintergrund_erst_nach_drei_sekunden(self):
        e, ablage, werkzeug, laufen, _g = _bauen(leerlauf=None, vorn="3")
        e._chat_vorn_zeit = float("-inf")
        meldungen = _liefern(e, CHAT, "Bericht")
        laufen()
        self.assertEqual(meldungen, [(True, "")])


class ZwischenablageBleibtSauber(unittest.TestCase):
    def test_fremder_inhalt_kommt_nach_dem_lauf_zurueck(self):
        e, ablage, werkzeug, laufen, _g = _bauen(ablage=_Ablage("meine Notiz"))
        _liefern(e, CHAT, "Bericht")
        laufen()
        self.assertEqual(werkzeug.eingefuegt, ["Bericht"])
        self.assertEqual(ablage.text, "meine Notiz")

    def test_misslingen_laesst_nichts_von_uns_liegen(self):
        e, ablage, werkzeug, laufen, _g = _bauen(ablage=_Ablage("meine Notiz"))
        werkzeug.aktivieren = lambda kennung: False
        meldungen = _liefern(e, CHAT, "Bericht 30.")
        laufen()
        self.assertFalse(meldungen[0][0])
        self.assertEqual(ablage.text, "meine Notiz")

    def test_leere_ablage_bleibt_leer(self):
        e, ablage, werkzeug, laufen, _g = _bauen()
        werkzeug.aktivieren = lambda kennung: False
        _liefern(e, CHAT, "30.")
        laufen()
        self.assertEqual(ablage.text, "")

    def test_eigene_reste_werden_nicht_als_fremder_inhalt_zurueckgeschrieben(self):
        e, ablage, werkzeug, laufen, _g = _bauen()
        _liefern(e, CHAT, "Bericht eins")
        laufen()
        ablage.text = "Bericht eins"        # Rest von uns, nicht von Robert
        _liefern(e, CHAT, "Bericht zwei")
        laufen()
        self.assertEqual(ablage.text, "")

    def test_ohne_zustellwache_bleibt_ein_gescheitertes_ergebnis_liegen(self):
        e, ablage, werkzeug, laufen, _g = _bauen()
        werkzeug.aktivieren = lambda kennung: False
        e.hinzufuegen(CHAT, "RUN-Ergebnis")        # kein Rueckruf: alter Weg
        laufen()
        self.assertEqual(ablage.text, "RUN-Ergebnis")


class AbstandUndReihenfolge(unittest.TestCase):
    def test_zwei_sekunden_zwischen_zwei_bruecken_einfuegungen(self):
        e, ablage, werkzeug, laufen, geplant = _bauen()
        _liefern(e, CHAT, "eins")
        _liefern(e, CHAT, "zwei")
        verzoegerungen = []
        while geplant:
            ms, f = geplant.pop(0)
            verzoegerungen.append(ms)
            f()
        self.assertIn(einfueger.ABSTAND_ZWISCHEN_EINFUEGUNGEN_MS, verzoegerungen)
        self.assertEqual(werkzeug.eingefuegt, ["eins", "zwei"])


class _Uhr:
    def __init__(self):
        self.jetzt = 0
        self.eintraege = []

    def planen(self, ms, funktion):
        self.eintraege.append((self.jetzt + ms, len(self.eintraege), funktion))

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


class Nachlieferung(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.datei = Path(self.ordner.name) / "auftragsjournal.log"
        aj.zuruecksetzen()
        aj.einrichten(self.datei)
        self.uhr = _Uhr()
        self.erreichbar = False
        self.zugestellt = []
        self.versuche = []
        self.meldungen = []

        def einreihen(ziel, text, bild, kennung, rueckruf):
            self.versuche.append(text)
            if self.erreichbar:
                self.zugestellt.append(text)
                rueckruf(True, "")
            else:
                rueckruf(False, "Eingabe laeuft")
            return True

        self.wache = zustellwache.Zustellwache(
            einreihen, self.uhr.planen, lambda: CHAT,
            lambda zahl: self.meldungen.append(zahl))

    def tearDown(self):
        aj.zuruecksetzen()
        for h in list(getattr(aj._schreiber, "handlers", [])):
            h.close()
        aj._schreiber = None
        self.ordner.cleanup()

    def _drei_eintraege(self):
        for nummer in (7, 8, 9):
            self.wache.zustellen(nummer, "code", f"Bericht {nummer}", CHAT)
            self.wache.hochgeladen(nummer)

    def test_nachlieferung_in_entstehungsreihenfolge_und_genau_einmal(self):
        self._drei_eintraege()
        self.uhr.vor(400)                 # Chat unerreichbar: Wiederholungen laufen aus
        self.assertEqual(self.zugestellt, [])
        self.erreichbar = True
        self.uhr.vor(200)
        self.assertEqual(self.zugestellt, ["Bericht 7", "Bericht 8", "Bericht 9"])
        vorher = len(self.versuche)
        self.uhr.vor(3600)
        self.assertEqual(len(self.versuche), vorher)       # nichts doppelt, nichts mehr
        self.assertEqual(self.zugestellt.count("Bericht 8"), 1)

    def test_nur_eine_ansage_trotz_vieler_versuche(self):
        self._drei_eintraege()
        self.uhr.vor(3600)
        self.assertGreater(len(self.versuche), 9)
        self.assertEqual(self.meldungen, [3])

    def test_jeder_versuch_steht_im_journal(self):
        self._drei_eintraege()
        self.uhr.vor(600)
        text = self.datei.read_text(encoding="utf-8")
        self.assertIn("nachlieferung", text)
        self.assertIn("gescheitert grund=Eingabe laeuft", text)

    def test_hinweis_entfaellt_wenn_der_bericht_inzwischen_angekommen_ist(self):
        self.wache.zustellen(7, "code", "Bericht 7", CHAT)
        self.wache.hochgeladen(7)
        self.uhr.vor(200)                  # inkl. Hinweis nach 90 s (nicht zustellbar)
        self.erreichbar = True
        self.uhr.vor(300)
        self.assertEqual(self.zugestellt, ["Bericht 7"])
        self.assertNotIn("konnte nicht eingefuegt werden", " ".join(self.zugestellt))

    def test_zeit_hinweise_nach_auftragsende_entfallen(self):
        self.wache.auftrag_beginnt(42)
        self.uhr.vor(15 * 60 + 200)
        self.wache.auftrag_endet(42)
        self.erreichbar = True
        self.uhr.vor(600)
        self.assertEqual(self.zugestellt, [])

    def test_wartende_zaehlt_die_nachlieferung(self):
        self.wache.zustellen(7, "code", "Bericht 7", CHAT)
        self.wache.hochgeladen(7)
        self.uhr.vor(100)
        self.assertGreaterEqual(self.wache.wartende(), 1)
        self.erreichbar = True
        self.uhr.vor(300)
        self.assertEqual(self.wache.wartende(), 0)


if __name__ == "__main__":
    unittest.main()
