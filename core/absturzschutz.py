"""
CWB - Code Workbench
Absturzsicherheit, reines Python ohne Qt: Lauf-Marker (endete der letzte Lauf
sauber?), Absturzprotokoll (crash.log fuer faulthandler), Neustart-Zaehler des
Aufpassers (hoechstens 3 Neustarts in 5 Minuten) und die Entscheidung, wie ein
Prozessende zu werten ist.

Der Marker liegt im Datenordner: beim Start wird er angelegt, beim sauberen
Beenden (atexit, auch beim vorgesehenen Neustart) geloescht. Steht er beim
Start noch da, ist der letzte Lauf hart gestorben.
"""

import json
import logging
import os
import signal
import time
from pathlib import Path

try:
    from .pfade import DATENORDNER, log_einrichten
except ImportError:
    from pfade import DATENORDNER, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.absturzschutz")

MARKER_DATEI = DATENORDNER / "lauf.marker"
CRASH_DATEI = DATENORDNER / "crash.log"
NEUSTARTS_DATEI = DATENORDNER / "aufpasser_neustarts.json"
CRASH_MAX_BYTES = 1024 * 1024

# Exitcode, mit dem CWB dem Aufpasser einen gewollten Neustart (Strg+F4) meldet.
EXIT_NEUSTART = 75
# Umgebungsvariablen zwischen Aufpasser und CWB.
ENV_AUFPASSER = "CWB_AUFPASSER"
ENV_NACH_ABSTURZ = "CWB_NACH_ABSTURZ"

MAX_NEUSTARTS = 3
NEUSTART_FENSTER_S = 300.0

# Signale, die ein Beenden durch den Nutzer bedeuten.
_NUTZER_SIGNALE = {signal.SIGTERM, signal.SIGINT, signal.SIGHUP}

_unsauber_gemerkt: bool | None = None


# -- Lauf-Marker ---------------------------------------------------------------

def lauf_beginnen(marker: Path | None = None) -> bool:
    """Legt den Marker an. True, wenn er schon da war (letzter Lauf unsauber).
    Gibt den Befund nur beim ersten Aufruf je Prozess; danach `unsauber_abholen`."""
    global _unsauber_gemerkt
    marker = marker or MARKER_DATEI
    war_da = marker.exists()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"pid": os.getpid(), "start": time.time()}),
                          encoding="utf-8")
    except OSError as fehler:
        log.error("Lauf-Marker nicht schreibbar: %s", fehler)
    if war_da:
        log.warning("Letzter Lauf endete unsauber")
    else:
        log.info("Letzter Lauf endete sauber")
    _unsauber_gemerkt = war_da
    return war_da


def lauf_beenden_sauber(marker: Path | None = None) -> None:
    marker = marker or MARKER_DATEI
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
    except OSError as fehler:
        log.error("Lauf-Marker nicht loeschbar: %s", fehler)


def unsauber_abholen() -> bool:
    """True genau einmal pro Prozess, wenn der Start auf einen unsauberen Lauf
    folgte - damit ein spaeteres Projektfenster (F9) nicht erneut markiert."""
    global _unsauber_gemerkt
    wert = bool(_unsauber_gemerkt)
    _unsauber_gemerkt = False
    return wert


# -- Absturzprotokoll ------------------------------------------------------------

def crash_datei_oeffnen(pfad: Path | None = None, max_bytes: int = CRASH_MAX_BYTES):
    """Oeffnet die Absturzdatei zum Anhaengen (Aufrufer haelt sie dauerhaft
    offen). Ueber `max_bytes` wird sie vorher geleert, nicht rotiert."""
    pfad = pfad or CRASH_DATEI
    pfad.parent.mkdir(parents=True, exist_ok=True)
    try:
        if pfad.stat().st_size > max_bytes:
            pfad.write_text("", encoding="utf-8")
            log.info("crash.log war groesser als %d Bytes und wurde geleert", max_bytes)
    except FileNotFoundError:
        pass
    datei = open(pfad, "a", encoding="utf-8")
    datei.write(f"--- Lauf {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()} ---\n")
    datei.flush()
    return datei


# -- Aufpasser: Wertung eines Prozessendes und Neustart-Schutz ----------------------

def prozessende_werten(code: int) -> str:
    """'ende' (nichts tun), 'neustart' (gewollt, sofort neu) oder 'absturz'.
    `code` wie bei subprocess: negativ = beendet durch Signal."""
    if code == 0:
        return "ende"
    if code == EXIT_NEUSTART:
        return "neustart"
    if code < 0 and -code in {int(s) for s in _NUTZER_SIGNALE}:
        return "ende"
    return "absturz"


class NeustartSchutz:
    """Zaehlt Absturz-Neustarts: hoechstens `maximum` innerhalb `fenster_s`
    Sekunden. Der Stand liegt in einer Datei, damit ein neu gestarteter
    Aufpasser nicht von vorn zaehlt."""

    def __init__(self, datei: Path | None = None, maximum: int = MAX_NEUSTARTS,
                 fenster_s: float = NEUSTART_FENSTER_S, uhr=time.time):
        self.datei = datei
        self.maximum = maximum
        self.fenster_s = fenster_s
        self.uhr = uhr
        self._zeiten: list[float] = self._lesen()

    def _lesen(self) -> list[float]:
        if self.datei is None:
            return []
        try:
            werte = json.loads(self.datei.read_text(encoding="utf-8"))
            return [float(w) for w in werte]
        except (OSError, ValueError, TypeError):
            return []

    def _schreiben(self) -> None:
        if self.datei is None:
            return
        try:
            self.datei.parent.mkdir(parents=True, exist_ok=True)
            self.datei.write_text(json.dumps(self._zeiten), encoding="utf-8")
        except OSError as fehler:
            log.error("Neustart-Zaehler nicht schreibbar: %s", fehler)

    def neustart_erlaubt(self) -> bool:
        """Verbucht einen Neustart, wenn noch Platz ist. False = Schutz greift."""
        jetzt = self.uhr()
        self._zeiten = [z for z in self._zeiten if jetzt - z < self.fenster_s]
        if len(self._zeiten) >= self.maximum:
            self._schreiben()
            return False
        self._zeiten.append(jetzt)
        self._schreiben()
        return True
