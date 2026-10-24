"""
CWB - Code Workbench
Tests fuer die Chatfenster-Suche des Einfuegers (core/einfueger.py): Nach einem
Neustart ist kein Zielfenster gemerkt - dann sucht CWB den Chat selbst, merkt
ihn sich auch dauerhaft und sagt ehrlich, wenn es keinen gibt. Ohne Fenster:
Werkzeug und Einstellungen sind Attrappen.

Aufruf: python -m unittest core.test_chatsuche -v
"""

import unittest
from unittest import mock

try:
    from . import einfueger
except ImportError:
    import einfueger

CHAT = ("10", "Claude – Mozilla Firefox", "firefox Firefox")
CHAT2 = ("11", "Claude Code – Google Chrome", "google-chrome Google-chrome")
TERMINAL = ("20", "claude - Terminal", "gnome-terminal-server")
ANDERES = ("30", "Notizen", "gedit")


class _Werkzeug:
    def __init__(self, fenster, kandidaten, aktiv=None):
        self.fenster = {f[0]: f for f in fenster}
        self.kandidaten = list(kandidaten)
        self.aktiv = aktiv

    def fenster_lesen(self, kennung=None):
        return self.fenster.get(kennung or self.aktiv)

    def eigene_pid(self, kennung):
        return False

    def chat_kandidaten(self):
        return list(self.kandidaten)


class ChatSucheTests(unittest.TestCase):
    def setUp(self):
        self.gespeichert = []
        self.geladen = None
        for name, ersatz in (
            ("_ziel_laden", lambda: self.geladen),
            ("_ziel_speichern", lambda ziel: self.gespeichert.append(ziel)),
        ):
            p = mock.patch.object(einfueger, name, side_effect=ersatz)
            p.start()
            self.addCleanup(p.stop)
        einfueger._letztes_ziel = None
        einfueger._suche_erfolglos = False
        self.addCleanup(setattr, einfueger, "_letztes_ziel", None)
        self.addCleanup(setattr, einfueger, "_suche_erfolglos", False)

    def test_ohne_ziel_wird_der_chat_gesucht_und_gemerkt(self):
        w = _Werkzeug([CHAT, ANDERES], ["30", "10"])
        self.assertEqual(einfueger.ziel_finden(w), CHAT)
        self.assertEqual(einfueger._letztes_ziel, CHAT)
        self.assertEqual(self.gespeichert, [CHAT])
        self.assertFalse(einfueger.suche_erfolglos())

    def test_mehrere_nimmt_das_zuletzt_aktive(self):
        w = _Werkzeug([CHAT, CHAT2], ["11", "10"])   # Reihenfolge: aktivstes zuerst
        self.assertEqual(einfueger.ziel_finden(w), CHAT2)

    def test_terminal_mit_claude_im_titel_zaehlt_nicht(self):
        w = _Werkzeug([TERMINAL], ["20"])
        self.assertIsNone(einfueger.ziel_finden(w))
        self.assertTrue(einfueger.suche_erfolglos())

    def test_kein_browser_offen_meldet_nichts_gefunden(self):
        w = _Werkzeug([], [])
        self.assertIsNone(einfueger.ziel_finden(w))
        self.assertTrue(einfueger.suche_erfolglos())
        self.assertEqual(self.gespeichert, [])

    def test_gespeichertes_fenster_gilt_sofort_ohne_suche(self):
        self.geladen = ("11", "Claude Code", "")
        w = _Werkzeug([CHAT2], [])                    # Suche fande nichts
        self.assertEqual(einfueger.ziel_finden(w), CHAT2)

    def test_gespeichertes_fenster_das_kein_chat_mehr_ist_wird_verworfen(self):
        self.geladen = ("30", "Claude", "")
        w = _Werkzeug([ANDERES, CHAT], ["10"])
        self.assertEqual(einfueger.ziel_finden(w), CHAT)

    def test_gemerktes_ziel_das_verschwand_wird_ersetzt(self):
        einfueger._letztes_ziel = ("99", "Claude", "firefox")
        w = _Werkzeug([CHAT], ["10"])
        self.assertEqual(einfueger.ziel_finden(w), CHAT)

    def test_ziel_merken_ohne_jedes_ziel_sucht(self):
        w = _Werkzeug([CHAT], ["10"], aktiv=None)
        self.assertEqual(einfueger.ziel_merken(w), CHAT)

    def test_ziel_merken_speichert_aktiven_chat(self):
        w = _Werkzeug([CHAT], [], aktiv="10")
        einfueger.ziel_merken(w)
        self.assertEqual(self.gespeichert, [CHAT])

    def test_ziel_merken_speichert_kein_terminal(self):
        w = _Werkzeug([TERMINAL], [], aktiv="20")
        einfueger.ziel_merken(w)
        self.assertEqual(self.gespeichert, [])

    def test_kandidaten_nach_fensterreihenfolge(self):
        def lauf(befehl, **_kw):
            class _A:
                returncode, stderr = 0, ""
                stdout = ""
            a = _A()
            if befehl[0] == "xdotool":
                a.stdout = "16\n17\n"        # 0x10, 0x11
            else:
                a.stdout = "_NET_CLIENT_LIST_STACKING(WINDOW): window id # 0x11, 0x5, 0x10\n"
            return a
        with mock.patch.object(einfueger.subprocess, "run", side_effect=lauf):
            self.assertEqual(einfueger.XdotoolWerkzeug().chat_kandidaten(), ["16", "17"])


class _Ablage:
    def __init__(self):
        self.text = ""

    def setzen(self, t):
        self.text = t
        return True

    def lesen(self):
        return self.text

    def leeren(self):
        self.text = ""


class _EinfuegerWerkzeug(_Werkzeug):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.tasten = []

    def aktivieren(self, kennung):
        self.aktiv = kennung
        return True

    def taste(self, name):
        self.tasten.append(name)
        return True


class BrueckenEintragTests(ChatSucheTests):
    def _lauf(self, ziel, w):
        ergebnisse = []
        e = einfueger.Einfueger(w, _Ablage(), lambda ms, f: f(), lambda: True,
                                lambda *_: None)
        e.naechster_rueckruf = lambda ok, grund="": ergebnisse.append((ok, grund))
        e.hinzufuegen(ziel, "Bericht")
        return ergebnisse

    def test_verwalteter_eintrag_ohne_ziel_findet_den_chat_und_stellt_zu(self):
        w = _EinfuegerWerkzeug([CHAT], ["10"], aktiv="10")
        self.assertEqual(self._lauf(None, w), [(True, "")])
        self.assertIn("ctrl+v", w.tasten)

    def test_ohne_chat_bleibt_der_eintrag_liegen(self):
        w = _EinfuegerWerkzeug([ANDERES], [], aktiv="30")
        erg = self._lauf(None, w)
        self.assertEqual(erg[0][0], False)
        self.assertTrue(erg[0][1].startswith("kein Zielfenster"))
        self.assertEqual(w.tasten, [])

    def test_veraltetes_ziel_wird_durch_gefundenen_chat_ersetzt(self):
        w = _EinfuegerWerkzeug([CHAT], ["10"], aktiv="10")
        self.assertEqual(self._lauf(("99", "Claude", "firefox"), w), [(True, "")])


if __name__ == "__main__":
    unittest.main()
