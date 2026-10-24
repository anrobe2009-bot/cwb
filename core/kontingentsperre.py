"""
CWB - Code Workbench
Kontingentsperre (Etappe 2): Torwaechter vor dem Start eines Claude-Code-Auftrags.

Reines Python, keine Oberflaeche. Das Fenster fragt vor jedem #CODE#-Start
`Tor.pruefen()`; die Stufe kommt aus core/kontingent.py:

* normal      - starten wie bisher,
* sparmodus   - starten, aber ein teures Modell (Opus, Fable, "default")
                wird auf Sonnet herabgesetzt,
* knapp       - nicht starten, der Auftrag bleibt in der Warteschlange,
* Stand aelter als 6 Stunden - NICHT sperren, starten mit Hinweis,
* kein Stand  - starten.

Ein laufender Auftrag wird nie angefasst; #RUN#, #ADMIN#, #BILD# und der
Orchestrator-Chat fragen das Tor gar nicht erst (und bekaemen "start").
Nach dem Reset gilt der alte Prozentwert als ueberholt: `kontingent.auswerten`
rechnet mit der Uhrzeit, die Stufe faellt von selbst.

Zwei kleine Dateien im Datenordner:
* kontingent_freigabe.json - "trotzdem starten", gilt fuer genau einen Start,
* kontingent_gehalten.json - Auftragsnummer -> Freigabezeit, nur zur Anzeige
  (Bericht "WARTET AUF KONTINGENT"). Sie steuert nie einen Start; ein
  Neustart kann also nichts doppelt starten.
"""

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

try:
    from . import kontingent
    from .pfade import DATENORDNER, einstellungen_lesen, log_einrichten
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kontingent
    from pfade import DATENORDNER, einstellungen_lesen, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.kontingentsperre")

SCHALTER = "kontingentsperre"
FREIGABE_DATEI = DATENORDNER / "kontingent_freigabe.json"
GEHALTEN_DATEI = DATENORDNER / "kontingent_gehalten.json"
FREIGABE_GUELTIG = timedelta(hours=6)
IMMER_FREI = ("run", "admin", "bild", "orchestrator")
TEURE_MODELLE = ("opus", "fable", "default")
ERSATZ_MODELL = "sonnet"

START, HERAB, HALTEN = "start", "modell_herab", "halten"

# Stelle von modell_wunsch und modell_sticky im Warteschlangeneintrag
# (core/fenster.py, _warteschlange).
POS_WUNSCH, POS_STICKY = 5, 9


@dataclass
class Urteil:
    aktion: str = START
    modell: str | None = None       # nur bei HERAB: das ersetzende Modell
    bis: datetime | None = None     # nur bei HALTEN: fruehestens ab dann
    hinweis: str = ""               # eine kurze Zeile fuer Verlauf und Protokoll
    stufe: str = "normal"


def uhrzeit_text(zeit: datetime | None, jetzt: datetime | None = None) -> str:
    """'14:00', an einem anderen Tag mit Wochentag: 'Do 10:00'."""
    if zeit is None:
        return "dem Reset"
    zeit = zeit.astimezone(kontingent.ZONE)
    jetzt = (jetzt or kontingent.jetzt()).astimezone(kontingent.ZONE)
    if zeit.date() == jetzt.date():
        return f"{zeit:%H:%M}"
    return f"{kontingent.WOCHENTAGE[zeit.weekday()]} {zeit:%H:%M}"


def ist_teuer(modell) -> bool:
    name = str(modell or "").lower()
    return any(teil in name for teil in TEURE_MODELLE)


def freigabezeit(auswertung: dict) -> datetime | None:
    """Fruehestens ab wann die Sperre fallen kann: der Reset der Fenster, die
    gerade ueber der Knapp-Schwelle liegen (bei beiden der spaetere)."""
    knapp = kontingent.knapp_schwelle()
    kandidaten = []
    sitzung = auswertung.get("sitzung_prozent")
    if sitzung is not None and not auswertung.get("sitzung_neu") and sitzung > knapp:
        if auswertung.get("sitzung_reset_zeit"):
            kandidaten.append(auswertung["sitzung_reset_zeit"])
    woche = auswertung.get("woche_prozent")
    if woche is not None and not auswertung.get("woche_neu") and woche > knapp:
        if auswertung.get("woche_reset_zeit"):
            kandidaten.append(auswertung["woche_reset_zeit"])
    return max(kandidaten) if kandidaten else None


def _json_lesen(datei: Path) -> dict:
    try:
        wert = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return wert if isinstance(wert, dict) else {}


def _json_schreiben(datei: Path, wert: dict) -> None:
    try:
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_text(json.dumps(wert, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    except OSError as fehler:
        log.error("%s nicht schreibbar: %s", datei.name, fehler)


# -- Handfreigabe -------------------------------------------------------------

def freigabe_geben(datei: Path | None = None, zeit: datetime | None = None) -> None:
    """'Trotzdem starten': gilt fuer den naechsten Start, einmal."""
    datei = datei or FREIGABE_DATEI
    _json_schreiben(datei, {"gegeben": (zeit or kontingent.jetzt()).isoformat(timespec="seconds")})
    log.info("Kontingentsperre: Handfreigabe fuer den naechsten Auftrag gegeben")


def freigabe_offen(datei: Path | None = None, zeit: datetime | None = None) -> bool:
    inhalt = _json_lesen(datei or FREIGABE_DATEI)
    try:
        gegeben = datetime.fromisoformat(str(inhalt.get("gegeben")))
    except ValueError:
        return False
    return ((zeit or kontingent.jetzt()) - gegeben) <= FREIGABE_GUELTIG


def _freigabe_verbrauchen(datei: Path) -> None:
    try:
        datei.unlink()
    except OSError as fehler:
        log.warning("Handfreigabe nicht geloescht: %s", fehler)


# -- Anzeige der gehaltenen Auftraege ------------------------------------------

def gehalten_vermerken(nummer, bis: datetime | None, datei: Path | None = None) -> None:
    if nummer is None:
        return
    datei = datei or GEHALTEN_DATEI
    inhalt = _json_lesen(datei)
    inhalt[str(nummer)] = "" if bis is None else bis.isoformat(timespec="minutes")
    _json_schreiben(datei, inhalt)


def gehalten_loeschen(nummer, datei: Path | None = None) -> None:
    if nummer is None:
        return
    datei = datei or GEHALTEN_DATEI
    inhalt = _json_lesen(datei)
    if inhalt.pop(str(nummer), None) is not None:
        _json_schreiben(datei, inhalt)


def gehalten_text(nummer, datei: Path | None = None, jetzt: datetime | None = None) -> str | None:
    """'WARTET AUF KONTINGENT bis 14:00' - oder None, wenn nichts gehalten wird."""
    wert = _json_lesen(datei or GEHALTEN_DATEI).get(str(nummer))
    if wert is None:
        return None
    try:
        bis = datetime.fromisoformat(wert)
    except ValueError:
        bis = None
    return f"WARTET AUF KONTINGENT bis {uhrzeit_text(bis, jetzt)}"


# -- Das Tor ------------------------------------------------------------------

class Tor:
    """Entscheidet pro Start. Alles Zeitabhaengige nimmt `zeit` entgegen
    (im Test fest vorgegeben); `auswerter(zeit)` liefert die Auswertung."""

    def __init__(self, auswerter=None, freigabe_datei: Path | None = None, schalter=None):
        self._auswerter = auswerter or (lambda zeit: kontingent.aktuelle_auswertung(zeit))
        self._freigabe_datei = freigabe_datei or FREIGABE_DATEI
        self._schalter = schalter or (lambda: bool(einstellungen_lesen().get(SCHALTER, True)))
        self._haelt = False

    def pruefen(self, modell=None, zeit: datetime | None = None, art: str = "code",
                verbrauchen: bool = True) -> Urteil:
        """`modell` ist der verlangte CLI-Kurzname oder None (= Voreinstellung
        Sonnet). `verbrauchen=False` fragt nur, ohne eine Handfreigabe zu
        verbrauchen (Zeitgeber)."""
        zeit = (zeit or kontingent.jetzt()).astimezone(kontingent.ZONE)
        if art in IMMER_FREI:
            return Urteil()
        try:
            if not self._schalter():
                return Urteil()
            auswertung = self._auswerter(zeit)
        except Exception as fehler:  # noqa: BLE001 - das Tor darf nie den Start verhindern
            log.exception("Kontingentsperre nicht auswertbar, Auftrag startet: %s", fehler)
            return Urteil()
        freigabe = freigabe_offen(self._freigabe_datei, zeit)
        if freigabe and verbrauchen:
            _freigabe_verbrauchen(self._freigabe_datei)
        if not auswertung:
            return Urteil()                 # kein Stand: normal starten
        stufe = auswertung.get("stufe", "normal")
        if auswertung.get("veraltet"):
            hinweis = ("Kontingentstand veraltet (Stand vor "
                       f"{kontingent.alter_text(auswertung['alter'])}), Auftrag startet ohne Sperre.")
            return Urteil(hinweis=hinweis, stufe=stufe)
        if stufe == "knapp":
            if freigabe:
                return Urteil(hinweis="Kontingent knapp, Sperre einmal von Hand aufgehoben.",
                              stufe=stufe)
            bis = freigabezeit(auswertung)
            return Urteil(HALTEN, bis=bis, stufe=stufe,
                          hinweis=f"Wartet auf Kontingent bis {uhrzeit_text(bis, zeit)}.")
        if stufe == "sparmodus" and ist_teuer(modell):
            return Urteil(HERAB, modell=ERSATZ_MODELL, stufe=stufe,
                          hinweis=f"Sparmodus: Modell {modell} auf Sonnet herabgesetzt.")
        return Urteil(stufe=stufe)

    def zustand_melden(self, haelt: bool) -> str | None:
        """'beginn' beim Uebergang in die Sperre, 'weiter' beim Verlassen,
        sonst None - so klingt der Warnton je einmal."""
        if haelt and not self._haelt:
            self._haelt = True
            return "beginn"
        if not haelt and self._haelt:
            self._haelt = False
            return "weiter"
        return None

    @property
    def haelt(self) -> bool:
        return self._haelt


def modell_von(eintrag) -> str | None:
    """Das verlangte Modell eines Warteschlangeneintrags."""
    return eintrag[POS_WUNSCH] or eintrag[POS_STICKY] or None


def schon_vorgemerkt(schlange, eingang_datei) -> bool:
    """Steht die Eingangsdatei schon in der Schlange? (Schutz gegen doppeltes
    Einreihen, etwa wenn derselbe Auftrag nach einem Neustart erneut ankommt.)"""
    if eingang_datei is None:
        return False
    return any(eintrag[4] == eingang_datei for eintrag in schlange)


def naechsten_holen(schlange: list, tor: Tor, zeit: datetime | None = None):
    """Holt den ersten Eintrag, wenn das Tor offen ist: (Eintrag, Urteil).
    Gehalten oder leer: (None, Urteil/None) - die Schlange bleibt unveraendert."""
    if not schlange:
        return None, None
    urteil = tor.pruefen(modell_von(schlange[0]), zeit)
    if urteil.aktion == HALTEN:
        return None, urteil
    return schlange.pop(0), urteil


def eintrag_herabsetzen(eintrag: tuple, urteil: Urteil) -> tuple:
    """Setzt bei HERAB die teuren Modellwuensche des Eintrags auf Sonnet."""
    if urteil.aktion != HERAB:
        return eintrag
    teile = list(eintrag)
    for pos in (POS_WUNSCH, POS_STICKY):
        if ist_teuer(teile[pos]):
            teile[pos] = urteil.modell
    return tuple(teile)


# -- Kommandozeile (fuer den Orchestrator per RUN) ------------------------------

def main(argumente=None) -> int:
    argumente = list(sys.argv[1:] if argumente is None else argumente)
    if argumente[:1] == ["freigeben"]:
        freigabe_geben()
        print("Naechster Auftrag darf trotz knappem Kontingent starten (einmal).")
        return 0
    print("Aufruf: python core/kontingentsperre.py freigeben")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
