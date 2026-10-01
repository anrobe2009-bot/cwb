"""
CWB - Code Workbench
Leitstand (Block 72, siehe wissen/plan_leitstand.md): nachts oder wenn Robert
nicht da ist, uebernimmt dieses Modul die Rolle der KI im Chat, die nicht
selbststaendig auf Berichte reagieren darf - Chat und Claude Code bleiben
unveraendert im Max-Abo.

Ablauf: die KI im Chat legt abends ueber die Bruecke <Projekt>/wissen/
nachtplan.md ab (nummerierte Schritte, Pruefkriterien, Haltepunkte, Abschnitt
"Grenzen"). Ist der Schalter "leitstand_aktiv" an, fragt core/fenster.py nach
JEDEM abgeschlossenen #CODE#-Auftrag eines Projekts mit nachtplan.md dieses
Modul um eine Entscheidung: Nachtplan, wissen/offen.md und der Bericht des
gerade beendeten Auftrags gehen an Gemini (reiner REST-Aufruf, keine eigene
SDK-Abhaengigkeit) - nie Code-Dateien, nie Einkaufs-, Gesundheits- oder
Profildaten. Die Antwort ist festes JSON: {"entscheidung": "weiter"|
"wiederholen"|"stopp", "schritt": N, "auftrag": "<Text>", "grund": "<Satz>"}.

Bei "weiter"/"wiederholen" legt core/fenster.py den naechsten Auftrag als
#CODE#-Block ueber core.eingangsordner.ablegen() ab (Quelle QUELLE_LEITSTAND)
- er laeuft danach wie jeder andere Eingangsordner-Auftrag, inklusive
Kontingent-Warten und automatischem Projektwechsel. Bei "stopp", einem
Haltepunkt, einem erledigten Plan oder einer der Grenzen hier haelt
core/fenster.py an und schreibt <Projekt>/wissen/nachtbericht.md.

Dieses Modul kennt kein fenster.py: Zustand, Grenzen-Werte, der Gemini-Aufruf
und die Textbausteine stehen hier rein als Funktionen und ein QThread fuer den
Netzaufruf - die Ablaufsteuerung (welches Projekt, welcher Bericht, was mit
der Entscheidung passiert) liegt in core/fenster.py, wie bei core/bruecke.py.

Modell: gemini-3.5-flash-lite (ai.google.dev/gemini-api/docs/models, Stand
01.10.2026: "vorherige Generation" des Flash-Lite-Modells, fuer neue Projekte
wird zu 3.5 Flash-Lite oder 3.8 Flash geraten - 3.5 Flash-Lite reicht fuer
eine reine Weiter/Wiederholen/Stopp-Entscheidung). Mit dem echten Schluessel
aus LEITSTAND_ZUGANG_DATEI erfolgreich gegengeprueft (REST-Aufruf, Antwort
"OK" bzw. gueltiges JSON im responseMimeType "application/json").
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal

try:
    from .pfade import (
        LEITSTAND_ZUGANG_DATEI,
        LEITSTAND_ZUSTAND_DATEI,
        einstellungen_lesen,
        log_einrichten,
    )
except ImportError:
    from pfade import (
        LEITSTAND_ZUGANG_DATEI,
        LEITSTAND_ZUSTAND_DATEI,
        einstellungen_lesen,
        log_einrichten,
    )

log_einrichten()
log = logging.getLogger("cwb.leitstand")

QUELLE_LEITSTAND = "leitstand"

GEMINI_MODELL = "gemini-3.5-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODELL}:generateContent"

# Grenzen (wissen/plan_leitstand.md): fest eingebaute Vorgaben, in F12 ->
# Leitstand aenderbar (einstellungen.json, siehe die drei Lese-Funktionen
# unten). Fehlschlaege in Folge und die erlaubten Markierungen sind dagegen
# nicht einstellbar - sie sind Sicherheitsgrenzen, keine Vorlieben.
STANDARD_MAX_AUFTRAEGE_PRO_NACHT = 12
STANDARD_MAX_WIEDERHOLUNGEN_JE_SCHRITT = 2
STANDARD_ZEITLIMIT_SEKUNDEN = 30
MAX_FEHLSCHLAEGE_IN_FOLGE = 2

# Nur #CODE# darf aus einer Leitstand-Entscheidung entstehen - core/fenster.py
# baut den Block selbst (`codeblock_bauen`), das hier ist nur die zusaetzliche
# Absicherung gegen eine Markierung, die Gemini versehentlich in den
# Auftragstext selbst schreibt.
VERBOTENE_MARKIERUNGEN = ("#RUN#", "#ADMIN#", "#BILD#")

# Gemini bekommt nie mehr als das hier - kein Code, keine Einkaufs-,
# Gesundheits- oder Profildaten (wissen/plan_leitstand.md).
_PROMPT = """Du bist der Leitstand eines Entwicklungswerkzeugs (CWB). \
Robert ist gerade nicht da; ein anderes KI-Programm (Claude Code) hat nachts \
einen Schritt eines Nachtplans bearbeitet. Entscheide anhand des Nachtplans, \
der offenen Punkte und des Berichts des gerade beendeten Schritts, wie es \
weitergeht.

Antworte NUR mit einem JSON-Objekt genau in dieser Form, ohne weiteren Text:
{{"entscheidung": "weiter" | "wiederholen" | "stopp", "schritt": <Zahl der \
naechsten oder zu wiederholenden Schrittnummer>, "auftrag": "<vollstaendiger \
Auftragstext fuer Claude Code, auf Deutsch, ohne jede #CODE#/#RUN#/#ADMIN#/\
#BILD#-Markierung>", "grund": "<ein Satz, warum>"}}

Waehle "stopp", wenn der Plan erledigt ist, ein im Plan genannter Haltepunkt \
erreicht ist, eine im Plan genannte Grenze ueberschritten wuerde, oder der \
Bericht einen Fehler zeigt, den du ohne Rueckfrage an Robert nicht sinnvoll \
beheben kannst. Waehle "wiederholen" nur, wenn der letzte Schritt sichtbar \
fehlgeschlagen ist und ein erneuter Versuch mit angepasstem Auftrag \
aussichtsreich ist.

# Nachtplan
{plan}

# Offene Punkte (wissen/offen.md)
{offen}

# Bericht des gerade beendeten Schritts
{bericht}
"""


def aktiv() -> bool:
    return bool(einstellungen_lesen().get("leitstand_aktiv", False))


def max_auftraege_pro_nacht() -> int:
    try:
        return max(1, int(einstellungen_lesen().get(
            "leitstand_max_auftraege", STANDARD_MAX_AUFTRAEGE_PRO_NACHT)))
    except (TypeError, ValueError):
        return STANDARD_MAX_AUFTRAEGE_PRO_NACHT


def max_wiederholungen_je_schritt() -> int:
    try:
        return max(1, int(einstellungen_lesen().get(
            "leitstand_max_wiederholungen", STANDARD_MAX_WIEDERHOLUNGEN_JE_SCHRITT)))
    except (TypeError, ValueError):
        return STANDARD_MAX_WIEDERHOLUNGEN_JE_SCHRITT


def zeitlimit_sekunden() -> int:
    try:
        return max(5, int(einstellungen_lesen().get(
            "leitstand_zeitlimit_sekunden", STANDARD_ZEITLIMIT_SEKUNDEN)))
    except (TypeError, ValueError):
        return STANDARD_ZEITLIMIT_SEKUNDEN


def api_schluessel_lesen() -> str | None:
    """Liest "gemini_api_key=..." aus LEITSTAND_ZUGANG_DATEI. `None`, wenn die
    Datei fehlt oder das Feld leer ist - der Inhalt wird dabei nie geloggt,
    nur dass das Lesen gelang oder nicht (wie core.bruecke.zugangsdaten_lesen)."""
    try:
        zeilen = LEITSTAND_ZUGANG_DATEI.read_text(encoding="utf-8-sig").splitlines()
    except OSError as fehler:
        log.info("Leitstand-Zugangsdatei nicht lesbar: %s", type(fehler).__name__)
        return None
    for zeile in zeilen:
        schluessel, trenner, wert = zeile.partition("=")
        if trenner and schluessel.strip() == "gemini_api_key" and wert.strip():
            return wert.strip()
    log.warning("Leitstand-Zugangsdatei ohne Feld 'gemini_api_key'")
    return None


def markierung_verboten(text: str) -> str | None:
    """Die erste gesperrte Markierung, die im Auftragstext steckt, sonst
    `None`. Gemini soll nie #RUN#/#ADMIN#/#BILD# auswaehlen koennen - core/
    fenster.py baut den Block ohnehin immer als #CODE#, das hier faengt nur
    einen Vorschlag ab, der eine dieser Zeichenketten selbst enthaelt."""
    oben = text.upper()
    for markierung in VERBOTENE_MARKIERUNGEN:
        if markierung in oben:
            return markierung
    return None


def codeblock_bauen(projekt_name: str, nummer: int, auftrag_text: str) -> str:
    """Baut den vollstaendigen #CODE#-Block fuer core.eingangsordner.ablegen()
    - Blocknummer und eine Zeile "Projekt: X" wie im Auftrag gefordert; die
    eigentliche Projektzuordnung geschieht daneben strukturiert ueber den
    Parameter `projekt=` von `ablegen()`, diese Zeile ist nur die fuer
    Menschen lesbare Entsprechung im Blocktext selbst."""
    return (
        f"#CODE#\nBlock {nummer}\nProjekt: {projekt_name}\n\n"
        f"{auftrag_text.strip()}\n\nEnde Block {nummer}"
    )


def aenderung_ausserhalb(projekt_pfad: Path, geaenderte_dateien: list) -> str | None:
    """Der erste Pfad aus `geaenderte_dateien`, der nicht unterhalb von
    `projekt_pfad` liegt, sonst `None`. core/sitzung.py ermittelt diese Liste
    per Git-Diff im Projekt (core/sicherheit.py, Wache.auftrag_bilanz) - ein
    Treffer hier waere darum nur bei einem Git-Submodul oder aehnlichem
    Sonderfall zu erwarten. Eine Freigabe (core/pfade.py, freigaben_lesen)
    ausserhalb des Projekts erlaubt core.sicherheit.Ordnergrenze bewusst ohne
    Rueckfrage und ausserhalb jedes Git-Diffs - eine solche Aenderung sieht
    diese Funktion grundsaetzlich nicht, das ist eine bekannte Luecke dieser
    Grenze, keine vollstaendige Sicherung."""
    try:
        wurzel = Path(projekt_pfad).resolve()
    except OSError:
        return None
    for datei in geaenderte_dateien:
        try:
            kandidat = (wurzel / datei).resolve() if not Path(datei).is_absolute() \
                else Path(datei).resolve()
        except OSError:
            continue
        if kandidat != wurzel and wurzel not in kandidat.parents:
            return str(datei)
    return None


# ---------------------------------------------------------------------------
# Zustand der Nacht
# ---------------------------------------------------------------------------

@dataclass
class Zustand:
    datum: str
    anzahl_auftraege: int = 0
    fehlschlaege_in_folge: int = 0
    wiederholungen: dict = field(default_factory=dict)
    angehalten: dict = field(default_factory=dict)
    verlauf: dict = field(default_factory=dict)


def _heute() -> str:
    return date.today().isoformat()


def zustand_lesen() -> Zustand:
    """Liest LEITSTAND_ZUSTAND_DATEI. Stammt der gemerkte Stand von einem
    frueheren Kalendertag (oder fehlt die Datei), beginnt eine frische Nacht -
    alle Zaehler und Haltepunkte gelten dann nicht mehr fuer den neuen Tag."""
    try:
        daten = json.loads(LEITSTAND_ZUSTAND_DATEI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        daten = {}
    if not isinstance(daten, dict) or daten.get("datum") != _heute():
        return Zustand(datum=_heute())
    return Zustand(
        datum=daten.get("datum", _heute()),
        anzahl_auftraege=int(daten.get("anzahl_auftraege", 0) or 0),
        fehlschlaege_in_folge=int(daten.get("fehlschlaege_in_folge", 0) or 0),
        wiederholungen=dict(daten.get("wiederholungen") or {}),
        angehalten=dict(daten.get("angehalten") or {}),
        verlauf=dict(daten.get("verlauf") or {}),
    )


def zustand_schreiben(zustand: Zustand) -> None:
    try:
        LEITSTAND_ZUSTAND_DATEI.parent.mkdir(parents=True, exist_ok=True)
        LEITSTAND_ZUSTAND_DATEI.write_text(
            json.dumps(zustand.__dict__, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except OSError as fehler:
        log.error("Leitstand-Zustand nicht schreibbar: %s", fehler)


def ist_angehalten(zustand: Zustand, projekt_name: str, plan_mtime: float) -> bool:
    """Wahr, solange fuer `projekt_name` zu genau diesem Plan (gleicher
    Zeitstempel der Datei) schon einmal angehalten wurde - eine neue
    nachtplan.md (anderer Zeitstempel) hebt das auf."""
    gemerkt = zustand.angehalten.get(projekt_name)
    return gemerkt is not None and float(gemerkt) == float(plan_mtime)


def anhalten_merken(zustand: Zustand, projekt_name: str, plan_mtime: float) -> None:
    zustand.angehalten[projekt_name] = plan_mtime


def wiederholung_lesen(zustand: Zustand, projekt_name: str, schritt: int) -> int:
    return int(zustand.wiederholungen.get(f"{projekt_name}::{schritt}", 0))


def wiederholung_erhoehen(zustand: Zustand, projekt_name: str, schritt: int) -> int:
    schluessel = f"{projekt_name}::{schritt}"
    anzahl = int(zustand.wiederholungen.get(schluessel, 0)) + 1
    zustand.wiederholungen[schluessel] = anzahl
    return anzahl


def verlauf_anhaengen(zustand: Zustand, projekt_name: str, schritt, satz: str) -> None:
    eintraege = zustand.verlauf.setdefault(projekt_name, [])
    eintraege.append({
        "zeit": datetime.now().strftime("%H:%M"),
        "schritt": schritt,
        "satz": satz,
    })


def verlauf_abholen(zustand: Zustand, projekt_name: str) -> list:
    return list(zustand.verlauf.get(projekt_name, []))


def verlauf_leeren(zustand: Zustand, projekt_name: str) -> None:
    zustand.verlauf.pop(projekt_name, None)


def nachtbericht_bauen(projekt_name: str, verlauf: list, haltgrund: str) -> str:
    zeilen = [
        "# Nachtbericht",
        "",
        f"Zeit: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Projekt: {projekt_name}",
        "",
        "## Verlauf",
    ]
    if verlauf:
        for eintrag in verlauf:
            schritt = eintrag.get("schritt")
            vorspann = f"Schritt {schritt}" if schritt is not None else "Ohne Schrittnummer"
            zeilen.append(f"- {eintrag.get('zeit', '')} {vorspann}: {eintrag.get('satz', '')}")
    else:
        zeilen.append("- (kein Schritt gelaufen)")
    zeilen += ["", "## Haltgrund", haltgrund]
    return "\n".join(zeilen) + "\n"


# ---------------------------------------------------------------------------
# Gemini-Aufruf
# ---------------------------------------------------------------------------

class LeitstandFehler(Exception):
    """Basisklasse."""


class LeitstandNetzFehler(LeitstandFehler):
    """Gemini nicht erreichbar oder Zeitueberschreitung."""


class LeitstandAntwortFehler(LeitstandFehler):
    """Antwort ist kein gueltiges Entscheidungs-JSON."""


@dataclass
class Entscheidung:
    entscheidung: str
    schritt: int | None
    auftrag: str
    grund: str


_GUELTIGE_ENTSCHEIDUNGEN = ("weiter", "wiederholen", "stopp")


def _gemini_aufrufen(api_schluessel: str, prompt: str, zeitlimit: int,
                      json_erzwingen: bool) -> str:
    """Ein POST an GEMINI_URL, gibt den reinen Antworttext zurueck. Der
    Schluessel steht nur im Abfrageparameter, nie im protokollierten Text -
    ein Netzfehler wird hier nur mit seiner Fehlerklasse geloggt, nie mit dem
    vollen requests-Fehlertext (der die Adresse samt Schluessel enthielte)."""
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if json_erzwingen:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    try:
        antwort = requests.post(
            GEMINI_URL, params={"key": api_schluessel}, json=body, timeout=zeitlimit,
        )
        antwort.raise_for_status()
    except requests.RequestException as fehler:
        log.info("Leitstand: Gemini nicht erreichbar (%s)", type(fehler).__name__)
        raise LeitstandNetzFehler(type(fehler).__name__) from fehler
    try:
        daten = antwort.json()
        return str(daten["candidates"][0]["content"]["parts"][0]["text"])
    except (ValueError, KeyError, IndexError, TypeError) as fehler:
        log.warning("Leitstand: Gemini-Antwort ohne verwertbaren Text (%s)",
                    type(fehler).__name__)
        raise LeitstandAntwortFehler("Antwort ohne verwertbaren Text") from fehler


def entscheidung_abfragen(api_schluessel: str, plan_text: str, offen_text: str,
                           bericht_text: str, zeitlimit: int) -> Entscheidung:
    """Fragt Gemini nach der naechsten Entscheidung. Wirft LeitstandNetzFehler
    bei einem Netzfehler oder einer Zeitueberschreitung, LeitstandAntwortFehler
    bei kaputtem oder unvollstaendigem JSON. Protokolliert nur Laengen und das
    Ergebnis, nie den vollen Inhalt von Plan, offenen Punkten oder Bericht -
    und nie den Schluessel."""
    prompt = _PROMPT.format(plan=plan_text.strip() or "(leer)",
                             offen=offen_text.strip() or "(leer)",
                             bericht=bericht_text.strip() or "(leer)")
    log.info("Leitstand: Gemini-Anfrage gesendet (Prompt %d Zeichen)", len(prompt))
    text = _gemini_aufrufen(api_schluessel, prompt, zeitlimit, json_erzwingen=True)
    try:
        geparst = json.loads(text)
    except ValueError as fehler:
        log.warning("Leitstand: Entscheidung ist kein gueltiges JSON")
        raise LeitstandAntwortFehler("kein gueltiges JSON") from fehler
    if not isinstance(geparst, dict):
        raise LeitstandAntwortFehler("JSON ist kein Objekt")
    wert = str(geparst.get("entscheidung", "")).strip().lower()
    if wert not in _GUELTIGE_ENTSCHEIDUNGEN:
        raise LeitstandAntwortFehler(f"ungueltige Entscheidung: {wert!r}")
    try:
        schritt = int(geparst["schritt"]) if "schritt" in geparst and \
            geparst["schritt"] is not None else None
    except (TypeError, ValueError):
        schritt = None
    auftrag = str(geparst.get("auftrag", "")).strip()
    grund = str(geparst.get("grund", "")).strip() or "(ohne Begruendung)"
    if wert != "stopp" and not auftrag:
        raise LeitstandAntwortFehler("Entscheidung ohne Auftragstext")
    log.info("Leitstand: Entscheidung erhalten (entscheidung=%s, schritt=%s)", wert, schritt)
    return Entscheidung(entscheidung=wert, schritt=schritt, auftrag=auftrag, grund=grund)


def verbindungstest(api_schluessel: str, zeitlimit: int = STANDARD_ZEITLIMIT_SEKUNDEN) -> str:
    """Ein harmloser Aufruf ("Antworte mit OK") als Verbindungstest, ohne
    JSON-Modus. Gibt den Antworttext zurueck oder wirft LeitstandNetzFehler/
    LeitstandAntwortFehler."""
    return _gemini_aufrufen(api_schluessel, "Antworte mit OK", zeitlimit, json_erzwingen=False)


class EntscheidungsFaden(QThread):
    """Fuehrt genau eine Gemini-Anfrage in einem eigenen Thread aus, damit ein
    langsamer oder haengender Netzaufruf das Fenster nie blockiert (wie
    core.bruecke.BerichtFaden). `fertig` liefert immer ein dict: bei Erfolg
    {"ok": True, "entscheidung", "schritt", "auftrag", "grund"}, sonst
    {"ok": False, "text": "<Fehlerklasse>"}."""

    fertig = Signal(dict)

    def __init__(self, api_schluessel: str, plan_text: str, offen_text: str,
                 bericht_text: str, zeitlimit: int, eltern=None):
        super().__init__(eltern)
        self._api_schluessel = api_schluessel
        self._plan_text = plan_text
        self._offen_text = offen_text
        self._bericht_text = bericht_text
        self._zeitlimit = zeitlimit

    def run(self) -> None:
        try:
            entscheidung = entscheidung_abfragen(
                self._api_schluessel, self._plan_text, self._offen_text,
                self._bericht_text, self._zeitlimit,
            )
        except LeitstandFehler as fehler:
            self.fertig.emit({"ok": False, "text": str(fehler) or type(fehler).__name__})
            return
        except Exception as fehler:  # noqa: BLE001
            log.exception("Leitstand: unerwarteter Fehler bei der Entscheidung: %s", fehler)
            self.fertig.emit({"ok": False, "text": "unerwarteter Fehler"})
            return
        self.fertig.emit({
            "ok": True,
            "entscheidung": entscheidung.entscheidung,
            "schritt": entscheidung.schritt,
            "auftrag": entscheidung.auftrag,
            "grund": entscheidung.grund,
        })
