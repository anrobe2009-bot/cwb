"""
CWB - Code Workbench
Kontingent des Max-Abos: Stand merken, hochrechnen, anzeigen (Etappe 1).

Das SDK meldet Prozentwerte erst ab seiner Warnschwelle. Darum merkt dieses
Modul einen Stand in kontingent.json (Datenordner): Sitzung und Woche in
Prozent, die beiden Reset-Zeiten, Messzeitpunkt und Quelle (foto, sdk, manuell).
Der Orchestrator traegt ihn per RUN ein, wenn er ein Foto der Nutzungsseite
gelesen hat. Liefert das SDK echte Werte, ueberschreiben sie den Stand.

Aus dem Stand wird gerechnet: Hochrechnung der Woche (lineare Linie seit dem
letzten Wochen-Reset bis zum naechsten) und der Sitzung (5-Stunden-Fenster),
ein Urteil (reicht / knapp / reicht nicht) und eine Stufe
(normal / sparmodus / knapp). Ein Stand, der aelter als 6 Stunden ist oder
dessen Wochen-Reset inzwischen vorbei ist, gilt als veraltet.

Kein automatisches Anhalten von Auftraegen - das ist Etappe 2.

Kommandozeile:
    python core/kontingent.py setzen --sitzung 25 --sitzung-reset 14:00 \
        --woche 7 --woche-reset "Do 10:00"
    python core/kontingent.py zeigen
Alle Zeiten gelten in Europe/Berlin.
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from .pfade import DATENORDNER, einstellungen_lesen, log_einrichten
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pfade import DATENORDNER, einstellungen_lesen, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.kontingent")

ZONE = ZoneInfo("Europe/Berlin")
DATEI = DATENORDNER / "kontingent.json"

QUELLEN = ("foto", "sdk", "manuell")
WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
WOCHENTAGE_LANG = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag",
                   "samstag", "sonntag")

VERALTET_STUNDEN = 6
SITZUNG_FENSTER = timedelta(hours=5)
WOCHE_FENSTER = timedelta(days=7)
# Sehr kurz nach einem Reset waere die Linie ein Zufallswert: der verstrichene
# Anteil des Fensters zaehlt mindestens so viel.
ANTEIL_MINIMUM = 0.05

# Einstellungen (einstellungen.json) und Vorgaben
SCHLUESSEL_SPAR = "kontingent_spar_prozent"
SCHLUESSEL_KNAPP = "kontingent_knapp_prozent"
SCHLUESSEL_WOCHE_RESET = "kontingent_woche_reset"
SPAR_STANDARD = 80
KNAPP_STANDARD = 90
WOCHE_RESET_STANDARD = "Do 10:00"
# Die Hochrechnung der Woche loest den Sparmodus erst fuenf Punkte ueber der
# Stand-Schwelle aus (80 -> 85).
HOCHRECHNUNG_AUFSCHLAG = 5


def jetzt() -> datetime:
    return datetime.now(ZONE)


# -- Zeitangaben --------------------------------------------------------------

def uhrzeit_lesen(text) -> tuple[int, int]:
    """'14:00' oder '9' -> (14, 0). ValueError bei Unsinn."""
    treffer = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?\s*", str(text), re.I)
    if not treffer:
        raise ValueError(f"Uhrzeit nicht lesbar: {text!r}")
    stunde, minute = int(treffer.group(1)), int(treffer.group(2) or 0)
    if stunde > 23 or minute > 59:
        raise ValueError(f"Uhrzeit ausserhalb des Tages: {text!r}")
    return stunde, minute


def wochenreset_lesen(text) -> tuple[int, int, int]:
    """'Do 10:00' oder 'Donnerstag 10:00' -> (3, 10, 0): Wochentag (Mo=0)."""
    teile = str(text).strip().split(None, 1)
    if len(teile) != 2:
        raise ValueError(f"Wochen-Reset nicht lesbar: {text!r}")
    name = teile[0].lower().rstrip(".")
    tag = None
    for nummer, (kurz, lang) in enumerate(zip(WOCHENTAGE, WOCHENTAGE_LANG)):
        if name in (kurz.lower(), lang):
            tag = nummer
    if tag is None:
        raise ValueError(f"Wochentag nicht lesbar: {teile[0]!r}")
    stunde, minute = uhrzeit_lesen(teile[1])
    return tag, stunde, minute


def wochenreset_text(tag: int, stunde: int, minute: int) -> str:
    return f"{WOCHENTAGE[tag]} {stunde:02d}:{minute:02d}"


def _naechster_tagesreset(ab: datetime, stunde: int, minute: int) -> datetime:
    """Naechste Uhrzeit stunde:minute NACH `ab` (Berliner Ortszeit)."""
    ab = ab.astimezone(ZONE)
    kandidat = ab.replace(hour=stunde, minute=minute, second=0, microsecond=0,
                          tzinfo=None)
    if kandidat.replace(tzinfo=ZONE) <= ab:
        kandidat += timedelta(days=1)
    return kandidat.replace(tzinfo=ZONE)


def _naechster_wochenreset(ab: datetime, tag: int, stunde: int, minute: int) -> datetime:
    """Naechster Wochentag/Uhrzeit-Zeitpunkt NACH `ab`. Gerechnet in
    Ortszeit ohne Zeitzonen-Zusatz, damit eine Zeitumstellung die Uhrzeit
    nicht verschiebt."""
    ab = ab.astimezone(ZONE)
    kandidat = ab.replace(hour=stunde, minute=minute, second=0, microsecond=0,
                          tzinfo=None)
    kandidat += timedelta(days=(tag - ab.weekday()) % 7)
    if kandidat.replace(tzinfo=ZONE) <= ab:
        kandidat += timedelta(days=7)
    return kandidat.replace(tzinfo=ZONE)


# -- Datei --------------------------------------------------------------------

def lesen(datei: Path | None = None) -> dict | None:
    """Der gemerkte Stand, oder None: Datei fehlt, ist kaputt oder unvollstaendig
    (keine lesbare Messzeit)."""
    datei = datei or DATEI
    try:
        stand = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fehler:
        log.info("kontingent.json nicht lesbar: %s", fehler)
        return None
    if not isinstance(stand, dict):
        return None
    try:
        datetime.fromisoformat(str(stand.get("gemessen")))
    except ValueError:
        log.warning("kontingent.json ohne gueltige Messzeit - ignoriert")
        return None
    return stand


def _prozent(wert):
    zahl = float(wert)
    if not 0 <= zahl <= 100:
        raise ValueError(f"Prozentwert ausserhalb 0 bis 100: {wert}")
    return round(zahl, 1)


def setzen(sitzung_prozent=None, sitzung_reset=None, woche_prozent=None,
           woche_reset=None, quelle: str = "manuell", gemessen: datetime | None = None,
           datei: Path | None = None) -> dict:
    """Merkt einen Stand. Nicht genannte Felder bleiben aus dem bisherigen
    Stand erhalten; fehlt der Wochen-Reset ganz, gilt die Einstellung."""
    if quelle not in QUELLEN:
        raise ValueError(f"Quelle muss eine von {QUELLEN} sein: {quelle!r}")
    datei = datei or DATEI
    alt = lesen(datei) or {}
    stand = {
        "sitzung_prozent": _prozent(sitzung_prozent) if sitzung_prozent is not None
        else alt.get("sitzung_prozent"),
        "sitzung_reset": alt.get("sitzung_reset"),
        "woche_prozent": _prozent(woche_prozent) if woche_prozent is not None
        else alt.get("woche_prozent"),
        "woche_reset": alt.get("woche_reset") or woche_reset_einstellung(),
        "gemessen": (gemessen or jetzt()).astimezone(ZONE).isoformat(timespec="seconds"),
        "quelle": quelle,
    }
    if sitzung_reset is not None:
        stand["sitzung_reset"] = "{:02d}:{:02d}".format(*uhrzeit_lesen(sitzung_reset))
    if woche_reset is not None:
        stand["woche_reset"] = wochenreset_text(*wochenreset_lesen(woche_reset))
    try:
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_text(json.dumps(stand, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    except OSError as fehler:
        log.error("kontingent.json nicht schreibbar: %s", fehler)
        raise
    return stand


# -- Einstellungen ------------------------------------------------------------

def _einstellung_zahl(schluessel: str, standard: int) -> int:
    try:
        wert = int(einstellungen_lesen().get(schluessel, standard))
    except (TypeError, ValueError):
        return standard
    return wert if 1 <= wert <= 100 else standard


def spar_schwelle() -> int:
    return _einstellung_zahl(SCHLUESSEL_SPAR, SPAR_STANDARD)


def knapp_schwelle() -> int:
    return _einstellung_zahl(SCHLUESSEL_KNAPP, KNAPP_STANDARD)


def woche_reset_einstellung() -> str:
    """Wochen-Reset aus F12 (Vorgabe Do 10:00); Unsinn faellt auf die Vorgabe."""
    wert = einstellungen_lesen().get(SCHLUESSEL_WOCHE_RESET, WOCHE_RESET_STANDARD)
    try:
        return wochenreset_text(*wochenreset_lesen(wert))
    except ValueError:
        return WOCHE_RESET_STANDARD


# -- Rechnung -----------------------------------------------------------------

def alter_text(dauer: timedelta) -> str:
    minuten = max(0, int(dauer.total_seconds() // 60))
    if minuten < 60:
        return f"{minuten} Min."
    if minuten < 48 * 60:
        return f"{minuten // 60} Std."
    return f"{minuten // (24 * 60)} Tage"


def _hochrechnung(prozent, fenster: timedelta, naechster_reset: datetime,
                  gemessen: datetime):
    """Prozent am Fensterende, wenn der Verbrauch so linear weiterlaeuft wie
    seit Fensterbeginn. None ohne Prozentwert."""
    if prozent is None:
        return None
    beginn = naechster_reset - fenster
    anteil = (gemessen - beginn) / fenster
    anteil = min(1.0, max(ANTEIL_MINIMUM, anteil))
    return round(prozent / anteil, 1)


def _urteil(hochgerechnet, grenze_reicht: float) -> str:
    if hochgerechnet is None:
        return "unbekannt"
    if hochgerechnet <= grenze_reicht:
        return "reicht"
    if hochgerechnet <= 100:
        return "knapp"
    return "reicht nicht"


def auswerten(stand: dict | None, zeit: datetime | None = None) -> dict | None:
    """Rechnet aus dem Stand: Alter, veraltet, Hochrechnungen, Urteile, Stufe.
    None ohne Stand. `zeit` ist die Gegenwart (im Test fest vorgegeben)."""
    if not stand:
        return None
    zeit = (zeit or jetzt()).astimezone(ZONE)
    gemessen = datetime.fromisoformat(stand["gemessen"]).astimezone(ZONE)
    dauer = zeit - gemessen
    spar, knapp = spar_schwelle(), knapp_schwelle()

    woche = stand.get("woche_prozent")
    sitzung = stand.get("sitzung_prozent")
    ergebnis = {
        "quelle": stand.get("quelle", "manuell"),
        "gemessen": gemessen,
        "alter": dauer,
        "woche_prozent": woche,
        "sitzung_prozent": sitzung,
        "sitzung_reset": stand.get("sitzung_reset"),
        "woche_reset": stand.get("woche_reset"),
        "woche_hochrechnung": None,
        "woche_urteil": "unbekannt",
        "woche_neu": False,
        "sitzung_hochrechnung": None,
        "sitzung_urteil": "unbekannt",
        "sitzung_neu": False,
    }
    veraltet = dauer > timedelta(hours=VERALTET_STUNDEN)

    try:
        tag, stunde, minute = wochenreset_lesen(
            stand.get("woche_reset") or woche_reset_einstellung())
        woche_reset = _naechster_wochenreset(gemessen, tag, stunde, minute)
        ergebnis["woche_reset_zeit"] = woche_reset
        if zeit >= woche_reset:
            veraltet = True            # seitdem hat die Woche neu begonnen
            ergebnis["woche_neu"] = True
        else:
            ergebnis["woche_hochrechnung"] = _hochrechnung(
                woche, WOCHE_FENSTER, woche_reset, gemessen)
            ergebnis["woche_urteil"] = _urteil(
                ergebnis["woche_hochrechnung"], spar + HOCHRECHNUNG_AUFSCHLAG)
    except ValueError:
        log.warning("Wochen-Reset im Stand nicht lesbar: %r", stand.get("woche_reset"))

    if stand.get("sitzung_reset"):
        try:
            stunde, minute = uhrzeit_lesen(stand["sitzung_reset"])
            sitzung_reset = _naechster_tagesreset(gemessen, stunde, minute)
            ergebnis["sitzung_reset_zeit"] = sitzung_reset
            if zeit >= sitzung_reset:
                ergebnis["sitzung_neu"] = True     # Sitzungsfenster ist vorbei
            else:
                ergebnis["sitzung_hochrechnung"] = _hochrechnung(
                    sitzung, SITZUNG_FENSTER, sitzung_reset, gemessen)
                ergebnis["sitzung_urteil"] = _urteil(
                    ergebnis["sitzung_hochrechnung"], spar + HOCHRECHNUNG_AUFSCHLAG)
        except ValueError:
            log.warning("Sitzungs-Reset im Stand nicht lesbar: %r", stand["sitzung_reset"])

    stufe = "normal"
    sitzung_gilt = None if (sitzung is None or ergebnis["sitzung_neu"]) else sitzung
    woche_gilt = None if ergebnis["woche_neu"] else woche
    hoch = ergebnis["woche_hochrechnung"]
    if ((woche_gilt is not None and woche_gilt > knapp)
            or (sitzung_gilt is not None and sitzung_gilt > knapp)):
        stufe = "knapp"
    elif ((woche_gilt is not None and woche_gilt > spar)
            or (hoch is not None and hoch > spar + HOCHRECHNUNG_AUFSCHLAG)):
        stufe = "sparmodus"
    ergebnis["stufe"] = stufe
    ergebnis["veraltet"] = veraltet
    return ergebnis


def gesamturteil(auswertung: dict) -> str:
    """Ein Wort fuer die Anzeige: schlechtestes Urteil von Woche und Sitzung."""
    rang = {"unbekannt": 0, "reicht": 1, "knapp": 2, "reicht nicht": 3}
    return max((auswertung["woche_urteil"], auswertung["sitzung_urteil"]),
               key=lambda u: rang[u])


# -- SDK ueberschreibt den Stand ----------------------------------------------

def sdk_uebernehmen(zustand: dict | None, datei: Path | None = None) -> dict | None:
    """Das SDK liefert echte Prozentwerte (Warnschwelle ueberschritten): sie
    ersetzen den Stand, Quelle "sdk". `zustand` ist das Ergebnis von
    Sitzung.kontingent_zustand() (die vorhandene Auswertung des
    RateLimitEvent). Ohne Prozentwert bleibt der Stand unberuehrt; gleiche
    Werte werden nicht erneut geschrieben."""
    if not isinstance(zustand, dict):
        return None
    woche = zustand.get("woche_prozent")
    sitzung = zustand.get("sitzung_prozent")
    if woche is None and sitzung is None:
        return None
    alt = lesen(datei) or {}
    if (alt.get("quelle") == "sdk"
            and (woche is None or alt.get("woche_prozent") == woche)
            and (sitzung is None or alt.get("sitzung_prozent") == sitzung)):
        return alt
    try:
        return setzen(
            sitzung_prozent=sitzung,
            sitzung_reset=zustand.get("sitzung_reset"),
            woche_prozent=woche,
            woche_reset=zustand.get("woche_reset"),
            quelle="sdk", datei=datei)
    except (OSError, ValueError) as fehler:
        log.error("SDK-Stand nicht uebernommen: %s", fehler)
        return None


# -- Anzeige ------------------------------------------------------------------

def _zahl(wert) -> str:
    return "?" if wert is None else f"{wert:g}"


def zeile(auswertung: dict | None) -> str:
    """'Kontingent: Woche 7 % · Sitzung 25 % bis 14:00 · reicht (Stand 3 Std.)'
    - bei veraltetem Stand mit Hinweis, bei Sparmodus/knapp mit Stufe."""
    if not auswertung:
        return ""
    teile = []
    if auswertung["woche_prozent"] is not None:
        teile.append(f"Woche {_zahl(auswertung['woche_prozent'])} %")
    if auswertung["sitzung_prozent"] is not None:
        text = f"Sitzung {_zahl(auswertung['sitzung_prozent'])} %"
        if auswertung["sitzung_neu"]:
            text += " (Sitzung inzwischen neu)"
        elif auswertung.get("sitzung_reset"):
            text += f" bis {auswertung['sitzung_reset']}"
        teile.append(text)
    if not teile:
        teile.append("noch keine Prozentwerte")
    teile.append(gesamturteil(auswertung))
    if auswertung["stufe"] != "normal":
        teile.append(auswertung["stufe"])
    stand = f"Stand {alter_text(auswertung['alter'])}"
    if auswertung["quelle"] == "sdk":
        stand += ", SDK"
    if auswertung["veraltet"]:
        stand += ", veraltet, neues Foto nötig"
    return f"Kontingent: {' · '.join(teile)} ({stand})"


def zeilen_zeigen(auswertung: dict | None) -> list[str]:
    """Kurze Zeilen fuer `zeigen` auf der Kommandozeile."""
    if not auswertung:
        return ["Kein Stand gemerkt."]

    def hoch(wert):
        return f"{_zahl(wert)} %"

    return [
        f"Stufe: {auswertung['stufe']}",
        f"Stand: {auswertung['gemessen']:%d.%m. %H:%M}, {alter_text(auswertung['alter'])} alt, "
        f"Quelle {auswertung['quelle']}" + (", VERALTET" if auswertung["veraltet"] else ""),
        f"Woche: {_zahl(auswertung['woche_prozent'])} %, Reset {auswertung['woche_reset'] or '?'}, "
        f"Hochrechnung {hoch(auswertung['woche_hochrechnung'])} ({auswertung['woche_urteil']})"
        + (", Woche inzwischen neu" if auswertung["woche_neu"] else ""),
        f"Sitzung: {_zahl(auswertung['sitzung_prozent'])} %, Reset {auswertung['sitzung_reset'] or '?'}, "
        f"Hochrechnung {hoch(auswertung['sitzung_hochrechnung'])} ({auswertung['sitzung_urteil']})"
        + (", Sitzung inzwischen neu" if auswertung["sitzung_neu"] else ""),
        zeile(auswertung),
    ]


def aktuelle_auswertung(zeit: datetime | None = None, datei: Path | None = None) -> dict | None:
    return auswerten(lesen(datei), zeit)


# -- Kommandozeile --------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kontingent-Stand der CWB")
    unter = parser.add_subparsers(dest="befehl", required=True)
    s = unter.add_parser("setzen", help="Stand eintragen")
    s.add_argument("--sitzung", type=float, help="Sitzung verbraucht, Prozent")
    s.add_argument("--sitzung-reset", help="Sitzungs-Reset, Uhrzeit, z. B. 14:00")
    s.add_argument("--woche", type=float, help="Woche verbraucht, Prozent")
    s.add_argument("--woche-reset", help='Wochen-Reset, z. B. "Do 10:00"')
    s.add_argument("--quelle", choices=QUELLEN, default="foto")
    unter.add_parser("zeigen", help="Stand und Hochrechnung ausgeben")
    return parser


def main(argumente=None) -> int:
    args = _parser().parse_args(argumente)
    try:
        if args.befehl == "setzen":
            if args.sitzung is None and args.woche is None:
                print("Fehler: --sitzung oder --woche angeben.")
                return 2
            setzen(args.sitzung, args.sitzung_reset, args.woche, args.woche_reset,
                   quelle=args.quelle)
            print("Eingetragen. " + zeile(aktuelle_auswertung()))
            return 0
        for text in zeilen_zeigen(aktuelle_auswertung()):
            print(text)
        return 0
    except (ValueError, OSError) as fehler:
        log.error("kontingent %s gescheitert: %s", args.befehl, fehler)
        print(f"Fehler: {fehler}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
