"""
CWB - Code Workbench
Tests fuer core/einfueger.py: Warteschlange, Nicht-Ueberschreiben, Enter nur im
Browser-Fenster, Leeren nach Erfolg, Behalten bei Misserfolg. Ohne Fenster,
Netz und Ton: Werkzeug, Zwischenablage und Zeitgeber sind Attrappen.

Aufruf: python -m unittest core.test_einfueger -v
"""

import unittest

try:
    from . import einfueger
except ImportError:
    import einfueger

BROWSER = ("1", "Claude – Mozilla Firefox", "firefox")
TERMINAL = ("2", "claude - Terminal", "gnome-terminal-server")
ANDERES = ("3", "Notizen", "gedit")


class _Ablage:
    def __init__(self):
        self.text = ""
        self.verlauf = []
        self.annehmen = True

    def setzen(self, text):
        if not self.annehmen:
            return False
        self.text = text
        self.verlauf.append(text)
        return True

    def lesen(self):
        return self.text

    def leeren(self):
        self.text = ""


class _Werkzeug:
    def __init__(self, ablage, fenster):
        self.ablage = ablage
        self.fenster = {f[0]: f for f in fenster}
        self.aktiv = None
        self.tasten = []
        self.eingefuegt = []
        self.aktivieren_klappt = True
        self.strg_v_klappt = True

    def fenster_lesen(self, kennung=None):
        return self.fenster.get(kennung or self.aktiv)

    def aktivieren(self, kennung):
        if not self.aktivieren_klappt:
            return False
        self.aktiv = kennung
        return True

    def taste(self, name):
        self.tasten.append((self.aktiv, name))
        if name == "ctrl+v":
            if not self.strg_v_klappt:
                return False
            self.eingefuegt.append(self.ablage.text)
        return True


def _bauen(fenster=(BROWSER, TERMINAL, ANDERES), enter=True):
    ablage = _Ablage()
    werkzeug = _Werkzeug(ablage, fenster)
    geplant = []
    meldungen = []
    e = einfueger.Einfueger(
        werkzeug, ablage, lambda ms, f: geplant.append(f),
        lambda: enter, lambda erfolge, schlecht: meldungen.append((erfolge, schlecht)),
    )

    def laufen():
        while geplant:
            geplant.pop(0)()

    return e, ablage, werkzeug, laufen, meldungen


class EnterRegel(unittest.TestCase):
    def test_nur_browser_mit_claude(self):
        self.assertTrue(einfueger.enter_passt("Claude – Mozilla Firefox", "firefox"))
        self.assertFalse(einfueger.enter_passt("claude - Terminal", "gnome-terminal-server"))
        self.assertFalse(einfueger.enter_passt("Notizen", "gedit"))
        self.assertFalse(einfueger.enter_passt("Claude", "unbekannt"))
        self.assertFalse(einfueger.enter_passt("Wetter – Firefox", "firefox"))


class Warteschlange(unittest.TestCase):
    def test_nichts_wird_ueberschrieben(self):
        e, ablage, werkzeug, laufen, meldungen = _bauen()
        for text in ("eins", "zwei", "drei"):
            e.hinzufuegen(BROWSER, text)
        # Nur das erste ist in Arbeit, die anderen warten.
        self.assertEqual(ablage.verlauf, ["eins"])
        laufen()
        self.assertEqual(werkzeug.eingefuegt, ["eins", "zwei", "drei"])
        self.assertEqual(ablage.verlauf, ["eins", "zwei", "drei"])
        self.assertEqual(meldungen, [(3, [])])

    def test_leeren_nach_erfolg(self):
        e, ablage, _w, laufen, _m = _bauen()
        e.hinzufuegen(BROWSER, "x")
        laufen()
        self.assertEqual(ablage.text, "")

    def test_enter_nur_im_browser(self):
        for ziel, erwartet in ((BROWSER, True), (TERMINAL, False), (ANDERES, False)):
            e, _a, werkzeug, laufen, _m = _bauen()
            e.hinzufuegen(ziel, "x")
            laufen()
            self.assertEqual(("Return" in [t for _, t in werkzeug.tasten]), erwartet, ziel)

    def test_enter_schalter_aus(self):
        e, _a, werkzeug, laufen, _m = _bauen(enter=False)
        e.hinzufuegen(BROWSER, "x")
        laufen()
        self.assertNotIn("Return", [t for _, t in werkzeug.tasten])


class Misserfolg(unittest.TestCase):
    def test_strg_v_scheitert_text_bleibt(self):
        e, ablage, werkzeug, laufen, meldungen = _bauen()
        werkzeug.strg_v_klappt = False
        e.hinzufuegen(BROWSER, "wichtig")
        laufen()
        self.assertEqual(ablage.text, "wichtig")
        self.assertEqual(meldungen, [(0, ["wichtig"])])

    def test_kein_ziel_text_bleibt(self):
        e, ablage, _w, laufen, meldungen = _bauen()
        e.hinzufuegen(None, "a")
        laufen()
        self.assertEqual(meldungen, [(0, ["a"])])
        self.assertEqual(ablage.text, "a")

    def test_gescheiterte_gehen_nicht_verloren(self):
        e, ablage, werkzeug, laufen, meldungen = _bauen()
        werkzeug.aktivieren_klappt = False
        e.hinzufuegen(BROWSER, "eins")
        e.hinzufuegen(BROWSER, "zwei")
        laufen()
        self.assertEqual(ablage.text, "eins\n\nzwei")
        self.assertEqual(meldungen[-1], (0, ["eins", "zwei"]))

    def test_erfolg_leert_nicht_die_gescheiterten(self):
        e, ablage, werkzeug, laufen, meldungen = _bauen()
        e.hinzufuegen(None, "verloren?")
        e.hinzufuegen(BROWSER, "ok")
        laufen()
        self.assertEqual(ablage.text, "verloren?")
        self.assertEqual(meldungen[-1], (1, ["verloren?"]))

    def test_ablage_nimmt_text_nicht_an(self):
        e, ablage, _w, laufen, meldungen = _bauen()
        ablage.annehmen = False
        e.hinzufuegen(BROWSER, "x")
        laufen()
        self.assertEqual(meldungen[0][0], 0)


class FensterklasseAusXprop(unittest.TestCase):
    """xdotool getwindowclassname fehlt in xdotool 3.20160805: die Klasse
    kommt aus `xprop -id <id> WM_CLASS`."""

    def test_ausgabe_wird_zerlegt(self):
        self.assertEqual(
            einfueger.klasse_aus_xprop('WM_CLASS(STRING) = "google-chrome", "Google-chrome"\n'),
            "google-chrome Google-chrome")
        self.assertEqual(einfueger.klasse_aus_xprop(""), "")
        self.assertEqual(einfueger.klasse_aus_xprop("WM_CLASS:  not found.\n"), "")

    def test_chrome_mit_claude_im_titel_bekommt_enter(self):
        klasse = einfueger.klasse_aus_xprop(
            'WM_CLASS(STRING) = "google-chrome", "Google-chrome"')
        self.assertTrue(einfueger.enter_passt("App - Claude - Google Chrome", klasse))
        terminal = einfueger.klasse_aus_xprop(
            'WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"')
        self.assertFalse(einfueger.enter_passt("claude - Terminal", terminal))

    def test_fenster_lesen_nimmt_xprop_statt_getwindowclassname(self):
        from unittest import mock

        class _Antwort:
            def __init__(self, text, code=0):
                self.stdout, self.stderr, self.returncode = text, "", code

        aufrufe = []

        def falsch_oder_recht(befehl, **_kw):
            aufrufe.append(befehl)
            if befehl[0] == "xprop":
                return _Antwort('WM_CLASS(STRING) = "firefox", "Firefox"\n')
            if befehl[1] == "getwindowname":
                return _Antwort("Claude – Mozilla Firefox\n")
            return _Antwort("", 1)   # alles andere (auch getwindowclassname) scheitert

        with mock.patch.object(einfueger.subprocess, "run", side_effect=falsch_oder_recht):
            fenster = einfueger.XdotoolWerkzeug().fenster_lesen("77")
        self.assertEqual(fenster, ("77", "Claude – Mozilla Firefox", "firefox Firefox"))
        self.assertFalse(any("getwindowclassname" in a for a in aufrufe))

    def test_ohne_xprop_bleibt_klasse_leer_und_kein_absturz(self):
        from unittest import mock

        def lauf(befehl, **_kw):
            if befehl[0] == "xprop":
                raise FileNotFoundError("xprop")

            class _A:
                stdout, stderr, returncode = "Titel\n", "", 0
            return _A()

        with mock.patch.object(einfueger.subprocess, "run", side_effect=lauf):
            fenster = einfueger.XdotoolWerkzeug().fenster_lesen("77")
        self.assertEqual(fenster, ("77", "Titel", ""))


if __name__ == "__main__":
    unittest.main()
