"""
CWB - Code Workbench
Unit-Test fuer Werkbank._pausetaste_zustand_anwenden (core/fenster.py, Fehler
1409): ist der Schalter "pause_screenshot" aus (Standard), darf
PausenTaste.registrieren() gar nicht erst aufgerufen werden, sonst haelt CWB
die beiden Hotkeys und das eigenstaendige Werkzeug "Pausetaste"
(C:\\Users\\Entwickler\\.cwb-werkzeuge\\pausetaste) bekommt sie nicht mehr.

Baut keine echte Werkbank (QMainWindow) und keine echten Win32-Hotkeys auf -
PausenTaste wird durch ein Mock ersetzt, Werkbank._pausetaste_zustand_anwenden
laeuft als ungebundene Methode auf einem schlanken Platzhalterobjekt.

Aufruf: python -m unittest core.test_pausetaste -v
        (oder, aus dem Ordner core/: python test_pausetaste.py -v)
"""

import unittest
from types import SimpleNamespace
from unittest import mock

try:
    from . import fenster
except ImportError:
    import fenster


class _Traeger:
    """Minimaler Platzhalter fuer Werkbank: traegt nur die echte Methode
    _pausetaste_zustand_anwenden, plus die zwei Attribute, die sie
    anfasst."""

    _pausetaste_zustand_anwenden = fenster.Werkbank._pausetaste_zustand_anwenden

    def __init__(self, pausetaste):
        self._pausetaste = pausetaste
        self.sprecher = mock.Mock()


def _pausetaste_mock(status: dict) -> mock.Mock:
    objekt = mock.Mock()
    objekt.status.return_value = dict(status)
    return objekt


class SchalterAusTest(unittest.TestCase):
    def test_registrieren_wird_nicht_aufgerufen(self):
        pausetaste = _pausetaste_mock({"Pause": False, "Strg+Umschalt+B": False})
        traeger = _Traeger(pausetaste)
        with mock.patch.object(
            fenster, "einstellungen_lesen",
            return_value={"pause_screenshot": False},
        ):
            traeger._pausetaste_zustand_anwenden()
        pausetaste.registrieren.assert_not_called()
        pausetaste.abmelden.assert_not_called()
        traeger.sprecher.sprich.assert_not_called()

    def test_bereits_registriert_wird_abgemeldet(self):
        pausetaste = _pausetaste_mock({"Pause": True, "Strg+Umschalt+B": False})
        traeger = _Traeger(pausetaste)
        with mock.patch.object(
            fenster, "einstellungen_lesen",
            return_value={"pause_screenshot": False},
        ):
            traeger._pausetaste_zustand_anwenden()
        pausetaste.registrieren.assert_not_called()
        pausetaste.abmelden.assert_called_once()


class SchalterAnTest(unittest.TestCase):
    def test_registrieren_wird_aufgerufen(self):
        pausetaste = _pausetaste_mock({"Pause": False, "Strg+Umschalt+B": False})
        pausetaste.registrieren.return_value = True
        traeger = _Traeger(pausetaste)
        with mock.patch.object(
            fenster, "einstellungen_lesen",
            return_value={"pause_screenshot": True},
        ):
            traeger._pausetaste_zustand_anwenden()
        pausetaste.registrieren.assert_called_once()
        pausetaste.abmelden.assert_not_called()

    def test_fehlschlag_wird_angesagt(self):
        pausetaste = _pausetaste_mock({"Pause": False, "Strg+Umschalt+B": False})
        pausetaste.registrieren.return_value = False
        traeger = _Traeger(pausetaste)
        with mock.patch.object(
            fenster, "einstellungen_lesen",
            return_value={"pause_screenshot": True},
        ):
            traeger._pausetaste_zustand_anwenden()
        pausetaste.registrieren.assert_called_once()
        traeger.sprecher.sprich.assert_called_once()
        self.assertEqual(traeger.sprecher.sprich.call_args.kwargs.get("art"), "fehler")

    def test_bereits_registriert_bleibt_unangetastet(self):
        pausetaste = _pausetaste_mock({"Pause": True, "Strg+Umschalt+B": False})
        traeger = _Traeger(pausetaste)
        with mock.patch.object(
            fenster, "einstellungen_lesen",
            return_value={"pause_screenshot": True},
        ):
            traeger._pausetaste_zustand_anwenden()
        pausetaste.registrieren.assert_not_called()
        pausetaste.abmelden.assert_not_called()


if __name__ == "__main__":
    unittest.main()
