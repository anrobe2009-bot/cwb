"""
CWB - Code Workbench
Not-Aus-Pause (F8, Hauptfenster): Bruecke und Leitstand ruhen nur kurz,
statt dauerhaft ausgeschaltet zu werden. Reines Python ohne Qt.

Die Pause steht nur im Arbeitsspeicher, nie in einstellungen.json: ein
Neustart hebt sie auf, und die Schalter "bruecke_aktiv" und
"leitstand_aktiv" bleiben vom Not-Aus unberuehrt. Gepausiert wird nur, was
beim Not-Aus an war; von Hand Ausgeschaltetes bleibt aus.
Dauer: Einstellung "notaus_pause_minuten" (Vorgabe 5, gueltig 1 bis 60,
0 = keine Pause).
"""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from .pfade import einstellungen_lesen, log_einrichten
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pfade import einstellungen_lesen, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.notaus_pause")

SCHLUESSEL = "notaus_pause_minuten"
STANDARD_MINUTEN = 5
MAX_MINUTEN = 60

_zustand: dict | None = None


def minuten() -> int:
    """Gewuenschte Pausendauer; ungueltige Werte fallen auf die Vorgabe,
    zu grosse auf das Maximum, negative auf 0 (keine Pause)."""
    try:
        wert = int(einstellungen_lesen().get(SCHLUESSEL, STANDARD_MINUTEN))
    except (TypeError, ValueError):
        return STANDARD_MINUTEN
    return max(0, min(MAX_MINUTEN, wert))


def starten(bruecke_an: bool, leitstand_an: bool, dauer: int | None = None,
            jetzt: datetime | None = None) -> datetime | None:
    """Beginnt die Pause fuer das, was gerade an ist. Gibt das Ende zurueck,
    bei Dauer 0 oder wenn nichts an ist: None (nichts wird pausiert)."""
    global _zustand
    dauer = minuten() if dauer is None else dauer
    if dauer <= 0 or not (bruecke_an or leitstand_an):
        return None
    jetzt = jetzt or datetime.now()
    ende = jetzt + timedelta(minutes=dauer)
    _zustand = {"ende": ende, "bruecke": bool(bruecke_an),
                "leitstand": bool(leitstand_an)}
    log.info("Not-Aus-Pause bis %s (Bruecke=%s, Leitstand=%s)",
             ende.strftime("%H:%M:%S"), bruecke_an, leitstand_an)
    return ende


def beenden() -> bool:
    """Hebt die Pause auf. True, wenn eine eingetragen war."""
    global _zustand
    lief = _zustand is not None
    _zustand = None
    if lief:
        log.info("Not-Aus-Pause beendet")
    return lief


def _laeuft(jetzt: datetime | None) -> bool:
    return _zustand is not None and (jetzt or datetime.now()) < _zustand["ende"]


def aktiv(jetzt: datetime | None = None) -> bool:
    return _laeuft(jetzt)


def bruecke_pausiert(jetzt: datetime | None = None) -> bool:
    return _laeuft(jetzt) and _zustand["bruecke"]


def leitstand_pausiert(jetzt: datetime | None = None) -> bool:
    return _laeuft(jetzt) and _zustand["leitstand"]


def ende() -> datetime | None:
    return _zustand["ende"] if _zustand else None


def abgelaufen(jetzt: datetime | None = None) -> bool:
    """True, wenn eine Pause eingetragen ist, deren Zeit um ist."""
    return _zustand is not None and (jetzt or datetime.now()) >= _zustand["ende"]


def bruecke_eingetragen() -> bool:
    return _zustand is not None and _zustand["bruecke"]


def von_hand_geaendert(werte: dict) -> bool:
    """Prueft nach F12, ob der Nutzer einen pausierten Schalter selbst
    ausgeschaltet hat; dann endet die Pause. (An war er beim Not-Aus ohnehin.)"""
    if _zustand is None:
        return False
    if _zustand["bruecke"] and not bool(werte.get("bruecke_aktiv", True)):
        return True
    return _zustand["leitstand"] and not bool(werte.get("leitstand_aktiv", True))
