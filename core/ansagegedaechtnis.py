"""
CWB - Code Workbench
Ansagegedaechtnis: merkt sich je Schluessel, was zuletzt als wiederkehrender
Hinweis angesagt wurde ("Es warten Auftraege", "Ergebnisse warten", "unbekanntes
Projekt"), auch ueber einen Neustart hinweg. `pruefen()` sagt nur dann "ansagen",
wenn sich die Lage gegenueber dem Gemerkten geaendert hat. Eine leere Lage gilt
erst als geleert, wenn sie LEER_NOETIG_S Sekunden lang angehalten hat - ein
kurzes Leeren und Wiederkommen (Auftragsdatei wandert von eingang/ nach laeuft/
und zurueck) bleibt still.

Reines Python, keine Oberflaeche.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

try:
    from . import pfade
except ImportError:
    import pfade

log = logging.getLogger("cwb.ansagegedaechtnis")

LEER_NOETIG_S = 120.0
DATEI_NAME = "ansagen.json"

_sperre = threading.Lock()


def _datei() -> Path:
    # Tests setzen CWB_ANSAGEN_DATEI, damit sie das echte Gedaechtnis nie anfassen.
    if os.environ.get("CWB_ANSAGEN_DATEI"):
        return Path(os.environ["CWB_ANSAGEN_DATEI"])
    return Path(pfade.DATENORDNER) / DATEI_NAME


def _lesen(datei: Path) -> dict:
    try:
        daten = json.loads(datei.read_text(encoding="utf-8"))
        return daten if isinstance(daten, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001
        log.exception("Ansagegedaechtnis nicht lesbar: %s", datei)
        return {}


def _schreiben(datei: Path, daten: dict) -> None:
    try:
        datei.parent.mkdir(parents=True, exist_ok=True)
        zwischen = datei.with_suffix(".tmp")
        zwischen.write_text(json.dumps(daten, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        zwischen.replace(datei)
    except Exception:  # noqa: BLE001
        log.exception("Ansagegedaechtnis nicht geschrieben: %s", datei)


def pruefen(schluessel: str, wert: str, datei: Path | None = None,
            jetzt: float | None = None) -> bool:
    """True, wenn `wert` (leer = nichts zu melden) gegenueber dem zuletzt
    Gemerkten neu ist und angesagt werden darf. Merkt sich den Wert dabei."""
    try:
        datei = datei or _datei()
        jetzt = time.time() if jetzt is None else jetzt
        with _sperre:
            daten = _lesen(datei)
            eintrag = daten.get(schluessel)
            if not isinstance(eintrag, dict):
                eintrag = {}
            alt = str(eintrag.get("wert", ""))
            leer_seit = eintrag.get("leer_seit")
            if not wert:
                if alt and leer_seit is None:
                    eintrag["leer_seit"] = jetzt
                    daten[schluessel] = eintrag
                    _schreiben(datei, daten)
                return False
            if leer_seit is not None and jetzt - float(leer_seit) >= LEER_NOETIG_S:
                alt = ""
            neu = alt != wert
            if neu or leer_seit is not None:
                daten[schluessel] = {"wert": wert}
                _schreiben(datei, daten)
            return neu
    except Exception:  # noqa: BLE001
        log.exception("Ansagegedaechtnis: Pruefung fehlgeschlagen (%s)", schluessel)
        return True
