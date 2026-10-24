"""
CWB - Code Workbench
Auftragsjournal: schreibt zu jedem Auftrag mit, was CWB damit gemacht hat
(angenommen, gestartet, hochgeladen, eingefuegt, angesagt, abgeschlossen ...),
damit sich Doppelungen, Haenger und fehlende Meldungen mit einem Blick finden
lassen. Es aendert kein Verhalten, es schreibt nur mit.

Datei: auftragsjournal.log im Programmordner, rotierend 1 MB x 3. Eine Zeile je
Schritt, Spalten durch " | " getrennt:
    Zeit mit Millisekunden | Nummer | Block | Projekt | Art | Schritt | Detail
Fehlt ein Wert, steht "-". Warnungen sind eigene Zeilen mit dem Schritt
"WARNUNG" (DOPPELT, KEIN UPLOAD, KEIN EINFUEGEN).

Jede oeffentliche Funktion faengt alle Fehler selbst ab und meldet sie nur im
normalen Log (cwb_fehler.log): ein Fehler im Journal darf nie einen Auftrag
stoeren.

Abfrage (Ausgabe kurz, ohne Sonderzeichen, zum Vorlesen):
    python -m core.auftragsjournal --letzte 5
    python -m core.auftragsjournal --auftrag 1234
"""

import argparse
import logging
import sys
import threading
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    from .pfade import log_einrichten
except ImportError:
    from pfade import log_einrichten

CWB_WURZEL = Path(__file__).resolve().parent.parent
JOURNAL_DATEI = CWB_WURZEL / "auftragsjournal.log"
JOURNAL_GROESSE = 1_000_000
JOURNAL_SICHERUNGEN = 3

# Fristen der Warnungen in Sekunden (Tests setzen sie klein).
UPLOAD_FRIST_S = 60.0
# Zaehlt erst ab dem Moment, in dem Upload UND Zustellbereitschaft (Kurzmeldung
# mit Protokollnummer steht) vorliegen. Die Zustellwache wartet auf Ruhe im
# Eingabefeld (3 s) und wiederholt nach 10/20/... Sekunden, 60 s sind sicher
# mehr als ein gewoehnlicher Ablauf braucht.
EINFUEGE_FRIST_S = 60.0

DETAIL_MAX = 200
TITEL_MAX = 40
LEER = "-"

log_einrichten()
log = logging.getLogger("cwb.auftragsjournal")

_sperre = threading.RLock()
_schreiber: logging.Logger | None = None
_datei: Path = JOURNAL_DATEI
_projekt = LEER
# Auftrag, der gerade laeuft - fuer Zeilen aus Faeden, die ihn nicht kennen
# (Sprachausgabe).
_kontext: dict = {}
_zustaende: dict = {}
_zeitgeber: list = []


# -- Grundlagen ---------------------------------------------------------------


def einrichten(datei: Path | None = None) -> None:
    """Legt den rotierenden Schreiber an; `datei` nur fuer Tests."""
    global _schreiber, _datei
    with _sperre:
        try:
            for h in list(getattr(_schreiber, "handlers", [])):
                _schreiber.removeHandler(h)
                h.close()
        except Exception:  # noqa: BLE001
            log.exception("Auftragsjournal: alter Schreiber nicht geschlossen")
        _datei = Path(datei) if datei else JOURNAL_DATEI
        schreiber = logging.getLogger(f"cwb.auftragsjournal.zeilen.{id(_datei)}.{id(object())}")
        schreiber.setLevel(logging.INFO)
        schreiber.propagate = False
        handler = RotatingFileHandler(
            str(_datei), maxBytes=JOURNAL_GROESSE, backupCount=JOURNAL_SICHERUNGEN,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        schreiber.addHandler(handler)
        _schreiber = schreiber


def zuruecksetzen() -> None:
    """Vergisst den Zustand im Speicher (Tests)."""
    global _kontext, _zustaende, _projekt
    with _sperre:
        for z in _zeitgeber:
            z.cancel()
        _zeitgeber.clear()
        _kontext = {}
        _zustaende = {}
        _projekt = LEER


def _sauber(wert, grenze: int = DETAIL_MAX) -> str:
    text = " ".join(str(wert).replace("|", "/").split())
    return text[:grenze] if text else LEER


def _schluessel(nummer, block) -> str:
    """Wonach ein Auftrag zusammengefasst wird: Nummer, sonst Block."""
    if nummer not in (None, "", LEER):
        return str(nummer)
    if block not in (None, "", LEER):
        return f"b{block}"
    return LEER


def _zustand(schluessel: str) -> dict:
    return _zustaende.setdefault(schluessel, {
        "quellen": set(), "gestartet": 0, "abgeschlossen": False,
        "hochgeladen": False, "eingefuegt": False,
        "zustellbereit": False, "frist_laeuft": False, "projekt": None,
    })


def _zeile(nummer, block, art, schritt: str, detail: str = "") -> None:
    if _schreiber is None:
        # Unter unittest nie ins echte Journal schreiben, sonst stehen die
        # Probelaeufe der anderen Tests darin (Tests richten eine eigene
        # Datei ein, siehe einrichten(datei)).
        if "unittest" in sys.modules:
            return
        einrichten()
    zeit = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    # Projekt des Auftrags, wie beim Start gemerkt: Zeilen, die nach einem
    # Projektwechsel noch zu ihm geschrieben werden, tragen nicht das neue.
    schluessel = _schluessel(nummer, block)
    projekt = (_zustaende.get(schluessel, {}).get("projekt") if schluessel != LEER else None) \
        or _projekt
    teile = (zeit, _sauber(nummer if nummer is not None else LEER),
             _sauber(block if block is not None else LEER), _sauber(projekt),
             _sauber(art or LEER), _sauber(schritt), _sauber(detail))
    _schreiber.info(" | ".join(teile))


def _warnung(nummer, block, art, text: str) -> None:
    _zeile(nummer, block, art, "WARNUNG", text)


def schreibe(schritt: str, detail: str = "", nummer=None, block=None, art=None,
             ohne_kontext: bool = False) -> None:
    """Eine Zeile fuer `schritt`. Fehlen Nummer und Block, gelten die des
    gerade laufenden Auftrags (ausser mit `ohne_kontext`)."""
    try:
        with _sperre:
            if nummer is None and block is None and not ohne_kontext:
                nummer = _kontext.get("nummer")
                block = _kontext.get("block")
                art = art or _kontext.get("art")
            _zeile(nummer, block, art, schritt, detail)
    except Exception:  # noqa: BLE001
        log.exception("Auftragsjournal: Zeile nicht geschrieben (%s)", schritt)


def projekt_setzen(name: str) -> None:
    global _projekt
    try:
        with _sperre:
            _projekt = _sauber(name or LEER)
    except Exception:  # noqa: BLE001
        log.exception("Auftragsjournal: Projekt nicht gesetzt")


def kennung(nummer=None, block=None, art=None) -> dict:
    """Merkzettel fuer Stellen, die spaeter schreiben (Einfueger)."""
    return {"nummer": nummer, "block": block, "art": art}


# -- Schritte mit Pruefung ------------------------------------------------------


def angenommen(quelle: str, nummer=None, block=None, art=None, detail: str = "") -> None:
    """Quelle: bruecke, eingang, zwischenablage, eingabefeld. Zweimal dieselbe
    Nummer aus derselben Quelle ergibt die Warnung DOPPELT."""
    try:
        with _sperre:
            _zeile(nummer, block, art, "angenommen", f"quelle={quelle} {detail}".strip())
            schluessel = _schluessel(nummer, block)
            if schluessel == LEER:
                return
            zustand = _zustand(schluessel)
            if quelle in zustand["quellen"]:
                _warnung(nummer, block, art,
                         f"DOPPELT angenommen, quelle={quelle}, nummer={schluessel}")
            zustand["quellen"].add(quelle)
    except Exception:  # noqa: BLE001
        log.exception("Auftragsjournal: angenommen nicht geschrieben")


def gestartet(nummer=None, block=None, art=None, detail: str = "") -> None:
    """Der Auftrag beginnt: wird zum laufenden Auftrag. Zweimal dieselbe
    Nummer ergibt die Warnung DOPPELT."""
    try:
        with _sperre:
            _kontext.clear()
            _kontext.update(nummer=nummer, block=block, art=art)
            schluessel = _schluessel(nummer, block)
            if schluessel != LEER:
                _zustand(schluessel)["projekt"] = _projekt
            _zeile(nummer, block, art, "gestartet", detail)
            if schluessel == LEER:
                return
            zustand = _zustand(schluessel)
            zustand["gestartet"] += 1
            if zustand["gestartet"] > 1:
                _warnung(nummer, block, art,
                         f"DOPPELT gestartet, nummer={schluessel}, "
                         f"mal={zustand['gestartet']}")
    except Exception:  # noqa: BLE001
        log.exception("Auftragsjournal: gestartet nicht geschrieben")


def _frist(sekunden: float, funktion) -> None:
    z = threading.Timer(sekunden, funktion)
    z.daemon = True
    _zeitgeber.append(z)
    z.start()


def abgeschlossen(dauer_s: float | None = None, erwartet_upload: bool = False,
                  nummer=None, block=None, art=None, detail: str = "") -> None:
    """Der Auftrag ist fertig. Bei Brueckenauftraegen (`erwartet_upload`) kommt
    nach UPLOAD_FRIST_S die Warnung KEIN UPLOAD, wenn bis dahin nichts
    hochgeladen wurde."""
    try:
        with _sperre:
            if nummer is None and block is None:
                nummer, block = _kontext.get("nummer"), _kontext.get("block")
            art = art or _kontext.get("art")
            text = f"dauer_s={dauer_s:.1f}" if dauer_s is not None else ""
            _zeile(nummer, block, art, "abgeschlossen", f"{text} {detail}".strip())
            schluessel = _schluessel(nummer, block)
            zustand = _zustand(schluessel)
            zustand["abgeschlossen"] = True
            if erwartet_upload:
                def pruefen():
                    try:
                        with _sperre:
                            if not _zustand(schluessel)["hochgeladen"]:
                                _warnung(nummer, block, art,
                                         f"KEIN UPLOAD {UPLOAD_FRIST_S:.0f} Sekunden "
                                         f"nach abgeschlossen, nummer={schluessel}")
                    except Exception:  # noqa: BLE001
                        log.exception("Auftragsjournal: Uploadpruefung gescheitert")
                _frist(UPLOAD_FRIST_S, pruefen)
    except Exception:  # noqa: BLE001
        log.exception("Auftragsjournal: abgeschlossen nicht geschrieben")


def _einfuege_frist_pruefen(schluessel: str, nummer, block, art) -> None:
    """Startet die Frist fuers Einfuegen, sobald Upload und Zustellbereitschaft
    vorliegen (die spaetere von beiden zaehlt) und noch nicht eingefuegt ist.
    Wird mit gehaltener Sperre gerufen."""
    zustand = _zustand(schluessel)
    if (not zustand["hochgeladen"] or not zustand["zustellbereit"]
            or zustand["eingefuegt"] or zustand["frist_laeuft"]):
        return
    zustand["frist_laeuft"] = True

    def pruefen():
        try:
            with _sperre:
                if not _zustand(schluessel)["eingefuegt"]:
                    _warnung(nummer, block, art,
                             f"KEIN EINFUEGEN {EINFUEGE_FRIST_S:.0f} Sekunden "
                             f"nach hochgeladen und zustellbereit, nummer={schluessel}")
        except Exception:  # noqa: BLE001
            log.exception("Auftragsjournal: Einfuegepruefung gescheitert")
    _frist(EINFUEGE_FRIST_S, pruefen)


def bericht_hochgeladen(versuch: int, nummer=None, block=None, art=None) -> None:
    """Upload gelungen. Ist auch die Zustellung bereit, muss innerhalb
    EINFUEGE_FRIST_S das Einfuegen vorliegen, sonst Warnung KEIN EINFUEGEN."""
    try:
        with _sperre:
            _zeile(nummer, block, art, "bericht_hochgeladen", f"versuch={versuch}")
            schluessel = _schluessel(nummer, block)
            _zustand(schluessel)["hochgeladen"] = True
            _einfuege_frist_pruefen(schluessel, nummer, block, art)
    except Exception:  # noqa: BLE001
        log.exception("Auftragsjournal: bericht_hochgeladen nicht geschrieben")


def zustellbereit(nummer=None, block=None, art=None) -> None:
    """Das Ergebnis (Kurzmeldung samt Protokollnummer oder Volltext) liegt bei
    der Zustellwache: ab jetzt ist Einfuegen moeglich. Schreibt keine Zeile."""
    try:
        with _sperre:
            schluessel = _schluessel(nummer, block)
            if schluessel == LEER:
                return
            _zustand(schluessel)["zustellbereit"] = True
            _einfuege_frist_pruefen(schluessel, nummer, block, art)
    except Exception:  # noqa: BLE001
        log.exception("Auftragsjournal: zustellbereit nicht vermerkt")


def eingefuegt(titel: str, enter: bool, ziel: dict | None = None) -> None:
    """Das Ergebnis wurde ins Zielfenster eingefuegt."""
    try:
        with _sperre:
            ziel = ziel or {}
            nummer, block, art = ziel.get("nummer"), ziel.get("block"), ziel.get("art")
            if nummer is None and block is None:
                nummer, block = _kontext.get("nummer"), _kontext.get("block")
                art = art or _kontext.get("art")
            _zeile(nummer, block, art, "eingefuegt",
                   f"fenster={_sauber(titel, TITEL_MAX)} enter={'ja' if enter else 'nein'}")
            _zustand(_schluessel(nummer, block))["eingefuegt"] = True
    except Exception:  # noqa: BLE001
        log.exception("Auftragsjournal: eingefuegt nicht geschrieben")


def ansage(zustand: str, text: str = "", grund: str = "") -> None:
    """Sprachausgabe: zustand ist gestartet, beendet oder abgebrochen (mit
    Grund). Gehoert zum gerade laufenden Auftrag."""
    zusatz = f" grund={grund}" if grund else ""
    schreibe("ansage", f"{zustand}{zusatz} text={_sauber(text, 50)}")


# -- Abfrage ---------------------------------------------------------------------


def _alle_zeilen(datei: Path | None = None) -> list[list[str]]:
    datei = Path(datei) if datei else _datei
    pfade = [datei.with_name(f"{datei.name}.{n}")
             for n in range(JOURNAL_SICHERUNGEN, 0, -1)] + [datei]
    zeilen = []
    for pfad in pfade:
        if not pfad.exists():
            continue
        for roh in pfad.read_text(encoding="utf-8", errors="replace").splitlines():
            teile = [t.strip() for t in roh.split(" | ", 6)]
            if len(teile) == 7:
                zeilen.append(teile)
    return zeilen


def _gruppen(zeilen: list[list[str]]) -> dict:
    gruppen: dict = {}
    # Zeilen ohne Nummer und Block gehoeren nicht alle zu einem Auftrag: ein
    # neuer Start (oder eine neue Annahme nach einem Start) beginnt einen neuen.
    ohne = 0
    ohne_gestartet = False
    for z in zeilen:
        schluessel = _schluessel(z[1], z[2])
        if schluessel == LEER:
            if z[5] in ("gestartet", "angenommen") and ohne_gestartet:
                ohne += 1
                ohne_gestartet = False
            if z[5] == "gestartet":
                ohne_gestartet = True
            schluessel = LEER if ohne == 0 else f"{LEER}{ohne}"
        gruppen.setdefault(schluessel, []).append(z)
    return gruppen


def _zusammenfassung(schluessel: str, zeilen: list[list[str]]) -> str:
    def anzahl(schritt):
        return sum(1 for z in zeilen if z[5] == schritt)

    art = next((z[4] for z in zeilen if z[4] != LEER), LEER)
    # Projekt des Starts: beim Annehmen steht noch das vorherige Projekt.
    projekt = next((z[3] for z in zeilen if z[5] == "gestartet" and z[3] != LEER),
                   next((z[3] for z in zeilen if z[3] != LEER), LEER))
    dauer = LEER
    for z in zeilen:
        if z[5] == "abgeschlossen" and "dauer_s=" in z[6]:
            dauer = z[6].split("dauer_s=")[1].split()[0]
    eingefuegt = [z for z in zeilen if z[5] == "eingefuegt"]
    if not eingefuegt:
        eingefuegt_text = "nein"
    elif any("enter=ja" in z[6] for z in eingefuegt):
        eingefuegt_text = "ja mit Enter"
    else:
        eingefuegt_text = "ja ohne Enter"
    ansagen = [z[6] for z in zeilen if z[5] == "ansage"]
    if any(a.startswith("beendet") for a in ansagen):
        ansage = "ok"
    elif any(a.startswith("abgebrochen") for a in ansagen):
        ansage = "abgebrochen"
    elif ansagen:
        ansage = "offen"
    else:
        ansage = "keine"
    warnungen = [z[6] for z in zeilen if z[5] == "WARNUNG"]
    if schluessel.startswith(LEER):
        nummer = LEER
    else:
        nummer = schluessel if not schluessel.startswith("b") else f"Block {schluessel[1:]}"
    text = (f"Auftrag {nummer}, {art}, Projekt {projekt}, "
            f"Dauer {dauer + ' Sekunden' if dauer != LEER else 'unbekannt'}, "
            f"angenommen {anzahl('angenommen')}, gestartet {anzahl('gestartet')}, "
            f"hochgeladen {'ja' if anzahl('bericht_hochgeladen') else 'nein'}, "
            f"eingefuegt {eingefuegt_text}, Ansage {ansage}, "
            f"Warnungen {len(warnungen) if warnungen else 'keine'}.")
    for w in warnungen:
        text += f"\n  Warnung: {w}"
    return text


def letzte(n: int, datei: Path | None = None) -> str:
    gruppen = _gruppen(_alle_zeilen(datei))
    # Nach dem Zeitpunkt der letzten Zeile ordnen, die juengsten zuletzt.
    reihenfolge = sorted(gruppen, key=lambda k: gruppen[k][-1][0])
    auswahl = reihenfolge[-n:] if n > 0 else []
    if not auswahl:
        return "Keine Auftraege im Journal."
    return "\n".join(_zusammenfassung(k, gruppen[k]) for k in auswahl)


def auftrag(nummer: str, datei: Path | None = None) -> str:
    gesucht = str(nummer).strip()
    zeilen = [z for z in _alle_zeilen(datei)
              if z[1] == gesucht or (z[1] == LEER and z[2] == gesucht)
              or _schluessel(z[1], z[2]) == gesucht]
    if not zeilen:
        return f"Auftrag {gesucht} nicht im Journal."
    return "\n".join(f"{z[0][11:]} {z[5]} {z[6]}" for z in zeilen)


def main(argumente: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.auftragsjournal")
    parser.add_argument("--letzte", type=int, metavar="N")
    parser.add_argument("--auftrag", metavar="NUMMER")
    parser.add_argument("--datei", help="andere Journaldatei (Tests)")
    angaben = parser.parse_args(argumente)
    datei = Path(angaben.datei) if angaben.datei else None
    if angaben.auftrag:
        print(auftrag(angaben.auftrag, datei))
    elif angaben.letzte:
        print(letzte(angaben.letzte, datei))
    else:
        parser.print_usage()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
