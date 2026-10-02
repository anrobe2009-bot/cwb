"""
CWB - Code Workbench
Unit-Tests fuer core/sprache.py, Klasse Abspieler: schnelle Folge von
Ansagen darf nie zwei Stimmen gleichzeitig hoerbar machen (Block 102).

Ursache des gemeldeten Fehlers: MCI bindet ein per `open` angelegtes Geraet
an den Faden, der es geoeffnet hat. `stopp()` schickte frueher `stop`/`close`
direkt im aufrufenden Faden (bei `schweig()` meist der Oberflaechen-Faden),
waehrend `open`/`play` immer im Sprech-Faden liefen - das scheiterte dort mit
"Geraet ist nicht geoeffnet", OHNE die Wiedergabe wirklich zu beenden, und
die naechste Ansage startete, waehrend die vorige weiterlief. Diese Tests
pruefen mit einer nachgebildeten winmm.dll (kein echter Ton, kein Netz),
dass `stop`/`close` jetzt ausschliesslich aus dem Faden kommen, der das
jeweilige Geraet geoeffnet hat, und dass `stopp()` erst zurueckkehrt, wenn
die Wiedergabe tatsaechlich beendet ist - zwei Geraete also nie gleichzeitig
offen und "playing" sind.

Aufruf: python -m unittest core.test_sprache -v
        (oder, aus dem Ordner core/: python test_sprache.py -v)
"""

import threading
import time
import unittest
from ctypes import create_unicode_buffer
from pathlib import Path

try:
    from . import sprache
except ImportError:
    import sprache


class FalscherWinmm:
    """Bildet winmm.dll soweit nach, wie Abspieler es benutzt (open/play/
    stop/close/status je Alias), ohne echten Ton. Merkt sich zu jedem
    Befehl, aus welchem Python-Faden er kam, und protokolliert jeden
    Zeitpunkt, an dem ein Geraet offen UND im Modus "playing" war."""

    def __init__(self):
        self.geraete = {}  # alias -> {"modus": str, "offen": bool}
        self.sperre = threading.Lock()
        self.befehle = []  # (faden_id, text, erfolg)
        self.ueberlappung_gesehen = False
        self._ueberlappungs_sperre = threading.Lock()

    def _spielende_offene(self):
        return [a for a, g in self.geraete.items() if g["offen"] and g["modus"] == "playing"]

    def _ueberlappung_pruefen(self):
        if len(self._spielende_offene()) > 1:
            with self._ueberlappungs_sperre:
                self.ueberlappung_gesehen = True

    def mciSendStringW(self, text, puffer, laenge, _):
        faden = threading.get_ident()
        teile = text.split()
        cmd = teile[0]
        erfolg = True
        with self.sperre:
            if cmd == "open":
                alias = teile[-1]
                self.geraete[alias] = {"modus": "stopped", "offen": True}
            elif cmd == "play":
                alias = teile[1]
                geraet = self.geraete.get(alias)
                if geraet is None or not geraet["offen"]:
                    erfolg = False
                else:
                    geraet["modus"] = "playing"
            elif cmd == "stop":
                alias = teile[1]
                geraet = self.geraete.get(alias)
                if geraet is None or not geraet["offen"]:
                    erfolg = False
                else:
                    geraet["modus"] = "stopped"
            elif cmd == "close":
                alias = teile[1]
                geraet = self.geraete.get(alias)
                if geraet is None or not geraet["offen"]:
                    erfolg = False
                else:
                    geraet["offen"] = False
            elif cmd == "status":
                alias = teile[1]
                geraet = self.geraete.get(alias)
                modus = geraet["modus"] if geraet and geraet["offen"] else ""
                if puffer is not None:
                    puffer.value = modus
            else:
                erfolg = False
        self.befehle.append((faden, text, erfolg))
        self._ueberlappung_pruefen()
        return 0 if erfolg else 1

    def mciGetErrorStringW(self, fehlercode, puffer, laenge):
        puffer.value = "Geraet ist nicht geoeffnet"

    def alias_oeffnender_faden(self, alias):
        for faden, text, erfolg in self.befehle:
            if erfolg and text.startswith("open ") and text.rstrip().endswith(f"alias {alias}"):
                return faden
        return None

    def fremdfaden_befehle(self, alias, erwarteter_faden):
        """Alle stop/close-Befehle fuer `alias`, die NICHT aus dem Faden
        kamen, der das Geraet geoeffnet hat."""
        treffer = []
        for faden, text, erfolg in self.befehle:
            if faden == erwarteter_faden:
                continue
            if text in (f"stop {alias}", f"close {alias}"):
                treffer.append((faden, text, erfolg))
        return treffer


def _abspieler_mit_fake(fake):
    ab = sprache.Abspieler()
    ab._winmm = fake
    return ab


class AbspielerTest(unittest.TestCase):
    def test_stopp_aus_fremdem_faden_schickt_keine_mci_befehle(self):
        """stopp() aus einem anderen Faden darf stop/close nicht selbst
        schicken - nur der Sprech-Faden (der das Geraet geoeffnet hat) darf
        das, in _bis_fertig_warten."""
        fake = FalscherWinmm()
        ab = _abspieler_mit_fake(fake)
        sprech_faden_id = {}

        def sprech_faden_lauf():
            sprech_faden_id["wert"] = threading.get_ident()
            ab.spiele(Path("x.mp3"), warten=True)

        t = threading.Thread(target=sprech_faden_lauf)
        t.start()
        # Warten, bis das Geraet wirklich offen und am Spielen ist.
        ende = time.monotonic() + 1.0
        while time.monotonic() < ende and ab._laufend is None:
            time.sleep(0.005)
        self.assertIsNotNone(ab._laufend, "Geraet wurde nicht rechtzeitig geoeffnet")
        alias = ab._laufend

        ab.stopp()  # laeuft im Test-Faden, NICHT im Sprech-Faden
        t.join(timeout=2)

        self.assertIsNone(ab._laufend, "stopp() kehrte zurueck, ohne das Geraet wirklich zu schliessen")
        oeffner = fake.alias_oeffnender_faden(alias)
        self.assertEqual(oeffner, sprech_faden_id["wert"])
        fremd = fake.fremdfaden_befehle(alias, oeffner)
        self.assertEqual(fremd, [], f"stop/close kam aus einem fremden Faden: {fremd}")
        self.assertFalse(fake.ueberlappung_gesehen)

    def test_keine_ueberlappung_bei_schneller_folge(self):
        """Wie im echten Betrieb: EIN Sprech-Faden spielt mehrere Stuecke
        nacheinander (wie _sprech_schleife), ein zweiter Faden unterbricht
        wiederholt per stopp() (wie schweig() aus der Oberflaeche) - nie
        zwei Geraete gleichzeitig offen und 'playing'."""
        fake = FalscherWinmm()
        ab = _abspieler_mit_fake(fake)
        anzahl = 8

        def sprech_faden_lauf():
            for i in range(anzahl):
                ab.spiele(Path(f"{i}.mp3"), warten=True)

        t = threading.Thread(target=sprech_faden_lauf)
        t.start()
        ende = time.monotonic() + 5.0
        while t.is_alive() and time.monotonic() < ende:
            ab.stopp()
            time.sleep(0.02)
        t.join(timeout=1)
        self.assertFalse(t.is_alive(), "Sprech-Faden kam nicht rechtzeitig zu Ende")
        ab.stopp()

        self.assertFalse(fake.ueberlappung_gesehen, "zwei Geraete waren gleichzeitig offen und am Spielen")
        self.assertIsNone(ab._laufend)

    def test_natuerliches_ende_schliesst_im_sprech_faden(self):
        """Spielt ein Stueck zu Ende, ohne Unterbrechung: schliesst sich
        selbst, im Sprech-Faden, kein fremder Zugriff noetig."""
        fake = FalscherWinmm()
        ab = _abspieler_mit_fake(fake)
        sprech_faden_id = {}

        original_status = fake.mciSendStringW

        def mit_auto_ende(text, puffer, laenge, _):
            ergebnis = original_status(text, puffer, laenge, _)
            if text.startswith("play "):
                alias = text.split()[1]
                def beenden():
                    time.sleep(0.05)
                    with fake.sperre:
                        geraet = fake.geraete.get(alias)
                        if geraet and geraet["offen"]:
                            geraet["modus"] = "stopped"
                threading.Thread(target=beenden, daemon=True).start()
            return ergebnis

        fake.mciSendStringW = mit_auto_ende

        def sprech_faden_lauf():
            sprech_faden_id["wert"] = threading.get_ident()
            ab.spiele(Path("x.mp3"), warten=True)

        t = threading.Thread(target=sprech_faden_lauf)
        t.start()
        t.join(timeout=2)

        self.assertIsNone(ab._laufend)
        schliess_befehle = [b for b in fake.befehle if b[1].startswith("close ")]
        self.assertTrue(schliess_befehle, "Geraet wurde nie geschlossen")
        for faden, _text, _erfolg in schliess_befehle:
            self.assertEqual(faden, sprech_faden_id["wert"])
        self.assertFalse(fake.ueberlappung_gesehen)


if __name__ == "__main__":
    unittest.main()
