"""
CWB - Code Workbench
Unit-Tests fuer core/terminal.py: ein Terminalbefehl, der ganz ohne Ausgabe
haengt, muss trotzdem zuverlaessig enden - sowohl ueber das Zeitlimit als
auch ueber F8 (Not-Aus). Block 106: ein haengender #run#-Befehl (keine
Ausgabe) ueberlebte frueher sowohl das Zeitlimit als auch F8, weil die
Zeitlimit-Pruefung in `for zeile in prozess.stdout:` nur ausgefuehrt wurde,
wenn eine Zeile ankam, und F8 den laufenden Terminalbefehl ueberhaupt nicht
anfasste.

Startet echte, aber kurze Unterprozesse (PowerShell -> Python), um zu
belegen, dass der ganze Prozessbaum wirklich beendet wird - nicht nur eine
Behauptung im Code. Dauert darum laenger als ein reiner Mock-Test, bleibt
aber durch kurze Zeitlimits (2 s) im einstelligen Sekundenbereich.

Aufruf: python -m unittest core.test_terminal -v
        (oder, aus dem Ordner core/: python test_terminal.py -v)
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

try:
    from . import terminal
except ImportError:
    import terminal


def _haengender_befehl(pid_datei: Path) -> str:
    """PowerShell-Befehl, der einen echten Python-Kindprozess startet, der
    seine PID meldet und dann ohne jede Ausgabe haengt - wie der echte
    Unit-Test-Hang aus Block 106."""
    helfer = Path(tempfile.mktemp(suffix=".py", prefix="cwb_test_haenger_"))
    helfer.write_text(
        "import os, time, pathlib\n"
        f"pathlib.Path(r'{pid_datei}').write_text(str(os.getpid()))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    return f'& "{sys.executable}" "{helfer}"'


def _prozess_laeuft(pid: int) -> bool:
    import subprocess
    pruefung = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return str(pid) in pruefung.stdout


class BefehlAusfuehrenTest(unittest.TestCase):
    def test_zeitlimit_beendet_haengenden_befehl_ohne_ausgabe(self):
        """Ohne jede Ausgabe darf die Zeitlimit-Pruefung nicht uebersprungen
        werden - und der Kindprozess (nicht nur PowerShell) muss wirklich
        weg sein."""
        with tempfile.TemporaryDirectory() as ordner:
            pid_datei = Path(ordner) / "pid.txt"
            start = time.monotonic()
            ergebnis = terminal.befehl_ausfuehren(
                _haengender_befehl(pid_datei), Path(ordner), zeitlimit=2,
            )
            dauer = time.monotonic() - start

            self.assertFalse(ergebnis.erfolg)
            self.assertIn("Zeitueberschreitung", ergebnis.fehler)
            self.assertLess(dauer, 10, "Zeitlimit von 2s griff nicht rechtzeitig")

            ende = time.monotonic() + 5
            while time.monotonic() < ende and pid_datei.exists() and not pid_datei.read_text().strip():
                time.sleep(0.1)
            self.assertTrue(pid_datei.exists(), "Kindprozess kam nie zum Schreiben seiner PID")
            pid = int(pid_datei.read_text().strip())
            self.assertFalse(
                _prozess_laeuft(pid),
                f"Python-Kindprozess (PID {pid}) laeuft nach der Zeitueberschreitung weiter",
            )

    def test_not_aus_beendet_haengenden_befehl_sofort(self):
        """F8: das Abbruch-Ereignis muss den Befehl beenden, auch ganz ohne
        Ausgabe und deutlich vor dem eigentlichen Zeitlimit."""
        with tempfile.TemporaryDirectory() as ordner:
            pid_datei = Path(ordner) / "pid.txt"
            abbruch = threading.Event()
            ergebnis_kasten: dict = {}

            def lauf():
                ergebnis_kasten["ergebnis"] = terminal.befehl_ausfuehren(
                    _haengender_befehl(pid_datei), Path(ordner), zeitlimit=120,
                    abbruch=abbruch,
                )

            faden = threading.Thread(target=lauf, daemon=True)
            start = time.monotonic()
            faden.start()

            ende = time.monotonic() + 5
            while time.monotonic() < ende and not (pid_datei.exists() and pid_datei.read_text().strip()):
                time.sleep(0.1)
            self.assertTrue(pid_datei.exists(), "Kindprozess kam nie zum Schreiben seiner PID")
            pid = int(pid_datei.read_text().strip())

            abbruch.set()  # entspricht F8
            faden.join(timeout=10)
            dauer = time.monotonic() - start

            self.assertFalse(faden.is_alive(), "befehl_ausfuehren kehrte nach Not-Aus nicht zurueck")
            ergebnis = ergebnis_kasten["ergebnis"]
            self.assertTrue(ergebnis.abgebrochen)
            self.assertFalse(ergebnis.erfolg)
            self.assertLess(dauer, 15, "Not-Aus griff nicht rechtzeitig (Zeitlimit war 120s)")
            self.assertFalse(
                _prozess_laeuft(pid),
                f"Python-Kindprozess (PID {pid}) laeuft nach Not-Aus weiter",
            )


if __name__ == "__main__":
    unittest.main()
