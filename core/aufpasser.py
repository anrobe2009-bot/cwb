"""
CWB - Code Workbench
Aufpasser: eigener, kleiner Prozess, der CWB (core/fenster.py) startet und
beobachtet. Stirbt CWB hart (Signal, Exitcode ungleich 0), startet er es neu -
hoechstens 3 Mal in 5 Minuten, danach "Neustart-Schutz". Endet CWB sauber
(Exitcode 0) oder durch den Nutzer (SIGTERM/SIGINT/SIGHUP), tut er nichts.
Einen gewollten Neustart (Strg+F4) meldet CWB mit Exitcode 75; den setzt der
Aufpasser sofort um, ohne den Zaehler zu belasten.

Aufruf: python core/aufpasser.py [Argumente fuer fenster.py]
Mit CWB_OHNE_AUFPASSER=1 in cwb_starten.sh startet CWB wie frueher direkt.
"""

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

try:
    from . import absturzschutz
except ImportError:
    import absturzschutz

absturzschutz.log_einrichten()
log = logging.getLogger("cwb.aufpasser")

FENSTER_SKRIPT = Path(__file__).resolve().parent / "fenster.py"


def cwb_starten(argumente: list[str], nach_absturz: bool) -> subprocess.Popen:
    umgebung = dict(os.environ)
    umgebung[absturzschutz.ENV_AUFPASSER] = "1"
    if nach_absturz:
        umgebung[absturzschutz.ENV_NACH_ABSTURZ] = "1"
    else:
        umgebung.pop(absturzschutz.ENV_NACH_ABSTURZ, None)
    return subprocess.Popen([sys.executable, str(FENSTER_SKRIPT), *argumente], env=umgebung)


def beobachten(argumente: list[str], schutz: absturzschutz.NeustartSchutz,
               starten=cwb_starten) -> int:
    """Hauptschleife. `starten` ist austauschbar (Tests): liefert ein Objekt
    mit wait() -> Exitcode. Gibt den Exitcode des Aufpassers zurueck."""
    nach_absturz = False
    while True:
        prozess = starten(argumente, nach_absturz)
        log.info("CWB gestartet (pid %s)", getattr(prozess, "pid", "?"))
        code = prozess.wait()
        urteil = absturzschutz.prozessende_werten(code)
        if urteil == "ende":
            log.info("CWB beendet (Code %s), Aufpasser endet", code)
            return 0
        if urteil == "neustart":
            log.info("CWB bittet um Neustart, wird neu gestartet")
            nach_absturz = False
            continue
        log.error("CWB abgestuerzt (Code %s)", code)
        if not schutz.neustart_erlaubt():
            log.error("Neustart-Schutz: %d Abstuerze in %d Minuten, kein weiterer Neustart",
                      schutz.maximum, int(schutz.fenster_s // 60))
            return 1
        log.warning("CWB wird nach Absturz neu gestartet")
        nach_absturz = True


def main() -> None:
    laufend: list[subprocess.Popen] = []

    def weitergeben(signum, _rahmen) -> None:
        # Der Nutzer beendet den Aufpasser: CWB mitnehmen, nicht neu starten.
        for prozess in laufend:
            try:
                prozess.send_signal(signum)
            except OSError:
                pass

    def starten(argumente, nach_absturz):
        prozess = cwb_starten(argumente, nach_absturz)
        laufend[:] = [prozess]
        return prozess

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, weitergeben)
    schutz = absturzschutz.NeustartSchutz(absturzschutz.NEUSTARTS_DATEI)
    try:
        sys.exit(beobachten(sys.argv[1:], schutz, starten))
    except Exception:  # noqa: BLE001
        log.exception("Aufpasser selbst abgestuerzt")
        sys.exit(1)


if __name__ == "__main__":
    main()
