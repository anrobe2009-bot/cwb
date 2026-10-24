"""
CWB - Code Workbench
Unit-Tests fuer core/waechter_anzeige.py: nur die Entscheidungslogik
(Waechter.zustand_ermitteln, _prozess_lebt) - ohne echtes Qt-Fenster und ohne
echten zweiten Prozess. Simuliert den Haenger-Fall aus dem Auftrag: die
Statusdatei bleibt stehen, waehrend die "vergangene Zeit" wächst.

Aufruf: python -m unittest core.test_waechter_anzeige -v
        (oder, aus dem Ordner core/: python test_waechter_anzeige.py -v)
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from . import waechter_anzeige as wa
except ImportError:
    import waechter_anzeige as wa


class ZustandErmittelnTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.status_datei = Path(self._temp.name) / "status.json"
        self._patch = patch.object(wa, "STATUS_DATEI", self.status_datei)
        self._patch.start()
        self.waechter = wa.Waechter(fenster=None)
        # Fester, bekannter Nullpunkt statt der echten Uhrzeit beim
        # Testlauf - die "no Datei"-Tests unten geben jetzt_monoton relativ
        # dazu an (z.B. 5.0 / 999.0 Sekunden seit dem eigenen Start).
        self.waechter._start = 0.0

    def tearDown(self):
        self._patch.stop()
        self._temp.cleanup()

    def _herzschlag_schreiben(self, zustand: str, alter_sekunden: float, *,
                               jetzt_epoche: float, pid: int | None = None,
                               auftrag: str = "") -> None:
        self.status_datei.write_text(json.dumps({
            "zeit": jetzt_epoche - alter_sekunden,
            "pid": os.getpid() if pid is None else pid,
            "zustand": zustand,
            "auftrag": auftrag,
        }), encoding="utf-8")

    def test_frisch_arbeitet(self):
        jetzt = 1_000_000.0
        self._herzschlag_schreiben("arbeitet", 1.0, jetzt_epoche=jetzt, auftrag="liest x.py")
        zustand, hinweis = self.waechter.zustand_ermitteln(jetzt, jetzt_monoton=100.0)
        self.assertEqual(zustand, "arbeitet")
        self.assertIn("liest x.py", hinweis)

    def test_frisch_bereit(self):
        jetzt = 1_000_000.0
        self._herzschlag_schreiben("bereit", 1.0, jetzt_epoche=jetzt)
        zustand, _ = self.waechter.zustand_ermitteln(jetzt, jetzt_monoton=100.0)
        self.assertEqual(zustand, "bereit")

    def test_luecke_haelt_letzten_bekannten_zustand(self):
        jetzt = 1_000_000.0
        # Erst ein frischer "arbeitet"-Herzschlag, damit er als zuletzt
        # bekannter Zustand gemerkt ist.
        self._herzschlag_schreiben("arbeitet", 1.0, jetzt_epoche=jetzt)
        self.waechter.zustand_ermitteln(jetzt, jetzt_monoton=100.0)
        # Jetzt steht die Datei 10 Sekunden lang (zwischen frisch und
        # haengt) - kein Alarm, der alte Zustand bleibt.
        zustand, hinweis = self.waechter.zustand_ermitteln(jetzt + 10, jetzt_monoton=110.0)
        self.assertEqual(zustand, "arbeitet")
        self.assertEqual(hinweis, "")

    def test_haengt_wenn_prozess_noch_lebt(self):
        jetzt = 1_000_000.0
        self._herzschlag_schreiben("arbeitet", 20.0, jetzt_epoche=jetzt, pid=os.getpid())
        zustand, hinweis = self.waechter.zustand_ermitteln(jetzt, jetzt_monoton=200.0)
        self.assertEqual(zustand, "haengt")
        self.assertIn("20", hinweis)

    def test_abgestuerzt_wenn_prozess_tot(self):
        jetzt = 1_000_000.0
        # Eine Prozessnummer, die es mit sehr hoher Wahrscheinlichkeit nicht
        # (mehr) gibt.
        self._herzschlag_schreiben("arbeitet", 20.0, jetzt_epoche=jetzt, pid=999_999_937)
        zustand, _ = self.waechter.zustand_ermitteln(jetzt, jetzt_monoton=200.0)
        self.assertEqual(zustand, "abgestuerzt")

    def test_regulaer_beendet(self):
        jetzt = 1_000_000.0
        self.status_datei.write_text(json.dumps({
            "zeit": jetzt, "pid": os.getpid(), "zustand": "beendet",
        }), encoding="utf-8")
        zustand, _ = self.waechter.zustand_ermitteln(jetzt, jetzt_monoton=100.0)
        self.assertEqual(zustand, "beendet")

    def test_keine_datei_kurz_nach_eigenem_start(self):
        zustand, _ = self.waechter.zustand_ermitteln(1_000_000.0, jetzt_monoton=5.0)
        self.assertEqual(zustand, "bereit")

    def test_keine_datei_lange_nach_eigenem_start(self):
        zustand, _ = self.waechter.zustand_ermitteln(1_000_000.0, jetzt_monoton=999.0)
        self.assertEqual(zustand, "abgestuerzt")


class ProzessLebtTest(unittest.TestCase):
    def test_eigener_prozess_lebt(self):
        self.assertTrue(wa._prozess_lebt(os.getpid()))

    def test_unwahrscheinliche_pid_lebt_nicht(self):
        self.assertFalse(wa._prozess_lebt(999_999_937))

    def test_pid_null_lebt_nicht(self):
        self.assertFalse(wa._prozess_lebt(0))


if __name__ == "__main__":
    unittest.main()
