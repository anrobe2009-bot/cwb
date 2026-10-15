"""
CWB - Code Workbench
Leitstand (Block 72/73, siehe wissen/plan_leitstand.md): nachts oder wenn
Robert nicht da ist, uebernimmt dieses Modul die Rolle der KI im Chat, die
nicht selbststaendig auf Berichte reagieren darf - Chat und Claude Code
bleiben unveraendert im Max-Abo.

Ablauf: die KI im Chat legt abends ueber die Bruecke <Projekt>/wissen/
nachtplan.md ab (nummerierte Schritte, Pruefkriterien, Haltepunkte, Abschnitt
"Grenzen"). Ist der Schalter "leitstand_aktiv" an, fragt core/fenster.py nach
JEDEM abgeschlossenen #CODE#-Auftrag eines Projekts mit nachtplan.md dieses
Modul um eine Entscheidung: Nachtplan, wissen/offen.md und der Bericht des
gerade beendeten Auftrags gehen an einen von zwei waehlbaren Anbietern
(reiner REST-Aufruf, keine eigene SDK-Abhaengigkeit) - nie Code-Dateien, nie
Einkaufs-, Gesundheits- oder Profildaten. Die Antwort ist festes JSON:
{"entscheidung": "weiter"|"wiederholen"|"stopp", "schritt": N, "auftrag":
"<Text>", "grund": "<Satz>"}.

Bei "weiter"/"wiederholen" legt core/fenster.py den naechsten Auftrag als
#CODE#-Block ueber core.eingangsordner.ablegen() ab (Quelle QUELLE_LEITSTAND)
- er laeuft danach wie jeder andere Eingangsordner-Auftrag, inklusive
Kontingent-Warten und automatischem Projektwechsel. Bei "stopp", einem
Haltepunkt, einem erledigten Plan oder einer der Grenzen hier haelt
core/fenster.py an und schreibt <Projekt>/wissen/nachtbericht.md.

Dieses Modul kennt kein fenster.py: Zustand, Grenzen-Werte, die Anbieter-
Aufrufe und die Textbausteine stehen hier rein als Funktionen und ein QThread
fuer den Netzaufruf - die Ablaufsteuerung (welches Projekt, welcher Bericht,
was mit der Entscheidung passiert) liegt in core/fenster.py, wie bei
core/bruecke.py.

Anbieter (Block 73, F12 -> Leitstand, Vorgabe Gemini):
- Gemini: gemini-3.5-flash-lite (ai.google.dev/gemini-api/docs/models, Stand
  01.10.2026: "vorherige Generation" des Flash-Lite-Modells). Mit dem echten
  Schluessel aus LEITSTAND_ZUGANG_DATEI erfolgreich gegengeprueft (REST-
  Aufruf, Antwort "OK" bzw. gueltiges JSON im responseMimeType
  "application/json").
- Anthropic: claude-haiku-4-5-20251001, Messages-API (platform.claude.com/
  docs/en/models/overview, Stand 01.10.2026 per WebFetch geprueft: weiterhin
  das schnellste/guenstigste Modell der aktuellen Reihe, kein schnellerer
  Nachfolger vorhanden - Anthropic nennt dafuer eine Mindest-Retirement ab
  dem 15.10.2026, also schon in rund zwei Wochen; danach kann die Kennung
  ohne weitere Ankuendigung scheitern und muesste neu geprueft werden).
  Gleiches Prompt- und Entscheidungsschema wie bei Gemini, nur ohne dessen
  erzwungenen JSON-Modus (den hat die Messages-API nicht auf diesem einfachen
  Weg) - `_json_dekodieren` faengt einen gaengigen Markdown-Zaun um die
  Antwort zusaetzlich ab. Mangels eines im Datenordner hinterlegten
  Anthropic-Schluessels bei Auftragsende nur mit nachgebildeten Antworten
  getestet (core/test_leitstand.py), nicht mit einem echten Aufruf - das
  REST-Format selbst (Endpunkt, Kopfzeilen, Antwortform samt
  usage.input_tokens/output_tokens) stammt aus der offiziellen
  Schnellstart-Dokumentation, nicht aus Vermutung.
"""

import json
import logging
import re
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

# claude-haiku-4-5-20251001: die vollstaendige, auf Dauer gueltige Kennung
# (platform.claude.com/docs/en/models/overview nennt daneben den kuerzeren
# Alias "claude-haiku-4-5", der zur selben Schnappschuss-Kennung aufloest -
# hier steht die volle Form, weil sie auch nach einer moeglichen spaeteren
# Alias-Aenderung stabil bleibt).
ANTHROPIC_MODELL = "claude-haiku-4-5-20251001"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Reicht fuer eine Entscheidung samt mehrzeiligem Auftragstext; fuer den
# Verbindungstest ("Antworte mit OK") wird ein eigener kleiner Wert benutzt.
ANTHROPIC_MAX_TOKENS = 2048
ANTHROPIC_MAX_TOKENS_TEST = 16

ANBIETER_GEMINI = "gemini"
ANBIETER_ANTHROPIC = "anthropic"
GUELTIGE_ANBIETER = (ANBIETER_GEMINI, ANBIETER_ANTHROPIC)

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
# Absicherung gegen eine Markierung, die der Anbieter versehentlich in den
# Auftragstext selbst schreibt.
VERBOTENE_MARKIERUNGEN = ("#RUN#", "#ADMIN#", "#BILD#")

# Der Anbieter bekommt nie mehr als das hier - kein Code, keine Einkaufs-,
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


def anbieter() -> str:
    """Der gewuenschte Anbieter aus F12 -> Leitstand ("gemini" oder
    "anthropic", Schluessel "leitstand_anbieter"). Ein fehlender oder
    ungueltiger Wert gilt als "gemini" - das ist die Vorgabe ab Werk."""
    wert = str(einstellungen_lesen().get("leitstand_anbieter", ANBIETER_GEMINI)).strip().lower()
    return wert if wert in GUELTIGE_ANBIETER else ANBIETER_GEMINI


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


def _zugangsfeld_lesen(feld: str) -> str | None:
    """Liest `"<feld>=..."` aus LEITSTAND_ZUGANG_DATEI. `None`, wenn die Datei
    fehlt oder das Feld leer ist - der Inhalt wird dabei nie geloggt, nur dass
    das Lesen gelang oder nicht (wie core.bruecke.zugangsdaten_lesen)."""
    try:
        zeilen = LEITSTAND_ZUGANG_DATEI.read_text(encoding="utf-8-sig").splitlines()
    except OSError as fehler:
        log.info("Leitstand-Zugangsdatei nicht lesbar: %s", type(fehler).__name__)
        return None
    for zeile in zeilen:
        schluessel, trenner, wert = zeile.partition("=")
        if trenner and schluessel.strip() == feld and wert.strip():
            return wert.strip()
    log.warning("Leitstand-Zugangsdatei ohne Feld '%s'", feld)
    return None


def api_schluessel_lesen() -> str | None:
    """Der Gemini-Schluessel ("gemini_api_key=...")."""
    return _zugangsfeld_lesen("gemini_api_key")


def anthropic_api_schluessel_lesen() -> str | None:
    """Der Anthropic-Schluessel ("anthropic_api_key=...")."""
    return _zugangsfeld_lesen("anthropic_api_key")


@dataclass
class AnbieterAufloesung:
    anbieter: str
    api_schluessel: str | None
    zurueckgefallen: bool


def wirksamer_anbieter() -> AnbieterAufloesung:
    """Der Anbieter, der tatsaechlich benutzt wird, und sein Schluessel. Ist
    "anthropic" gewaehlt, aber kein Anthropic-Schluessel hinterlegt, faellt
    Leitstand auf Gemini zurueck (`zurueckgefallen=True`) - core/fenster.py
    sagt in diesem Fall "Kein Anthropic-Schlüssel hinterlegt." an, bevor es
    mit Gemini weitermacht. Fehlt danach auch der Gemini-Schluessel, bleibt
    `api_schluessel` `None` - das behandelt der Aufrufer wie bisher."""
    gewuenscht = anbieter()
    if gewuenscht == ANBIETER_ANTHROPIC:
        schluessel = anthropic_api_schluessel_lesen()
        if schluessel is not None:
            return AnbieterAufloesung(ANBIETER_ANTHROPIC, schluessel, False)
        return AnbieterAufloesung(ANBIETER_GEMINI, api_schluessel_lesen(), True)
    return AnbieterAufloesung(ANBIETER_GEMINI, api_schluessel_lesen(), False)


def markierung_verboten(text: str) -> str | None:
    """Die erste gesperrte Markierung, die im Auftragstext steckt, sonst
    `None`. Der Anbieter soll nie #RUN#/#ADMIN#/#BILD# auswaehlen koennen -
    core/fenster.py baut den Block ohnehin immer als #CODE#, das hier faengt
    nur einen Vorschlag ab, der eine dieser Zeichenketten selbst enthaelt."""
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
    # Block 73: Anbieter -> {"aufrufe", "eingabe_token", "ausgabe_token"},
    # ueber alle Projekte einer Nacht hinweg (wie anzahl_auftraege global,
    # nicht je Projekt) - Grundlage der Nutzungs-Zeile im Nachtbericht.
    nutzung: dict = field(default_factory=dict)


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
        nutzung=dict(daten.get("nutzung") or {}),
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


def nutzung_erfassen(zustand: Zustand, benutzter_anbieter: str,
                      eingabe_token: int, ausgabe_token: int) -> None:
    """Zaehlt einen gelungenen Aufruf fuer den Nachtbericht (Block 73): Zahl
    der Aufrufe und die vom Anbieter selbst gemeldeten Eingabe-/Ausgabe-Token,
    je Anbieter aufsummiert ueber die ganze Nacht. Nur eine Schaetzung der
    Kosten, kein Abrechnungsbeleg - wird nicht erfasst, wenn der Aufruf an
    einem Netzfehler oder kaputtem JSON scheiterte (dann ist kein `usage`-Feld
    in der Antwort verlaesslich vorhanden)."""
    eintrag = zustand.nutzung.setdefault(
        benutzter_anbieter, {"aufrufe": 0, "eingabe_token": 0, "ausgabe_token": 0})
    eintrag["aufrufe"] = int(eintrag.get("aufrufe", 0)) + 1
    eintrag["eingabe_token"] = int(eintrag.get("eingabe_token", 0)) + int(eingabe_token)
    eintrag["ausgabe_token"] = int(eintrag.get("ausgabe_token", 0)) + int(ausgabe_token)


_ANBIETER_ANZEIGE = {ANBIETER_GEMINI: "Gemini", ANBIETER_ANTHROPIC: "Anthropic"}


def anbieter_anzeigename(benutzter_anbieter: str) -> str:
    """Lesbarer Name eines Anbieter-Schluessels ("gemini" -> "Gemini"), fuer
    Ansagen und Meldungen ausserhalb dieses Moduls (core/fenster.py)."""
    return _ANBIETER_ANZEIGE.get(benutzter_anbieter, benutzter_anbieter)


def nachtbericht_bauen(projekt_name: str, verlauf: list, haltgrund: str,
                        nutzung: dict | None = None) -> str:
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
    zeilen += ["", "## Nutzung diese Nacht (Schätzung, kein Abrechnungsbeleg)"]
    if nutzung:
        for benutzter_anbieter, werte in nutzung.items():
            name = anbieter_anzeigename(benutzter_anbieter)
            zeilen.append(
                f"- {name}: {werte.get('aufrufe', 0)} Aufrufe, "
                f"~{werte.get('eingabe_token', 0)} Eingabe-Token, "
                f"~{werte.get('ausgabe_token', 0)} Ausgabe-Token."
            )
    else:
        zeilen.append("- (kein Aufruf diese Nacht)")
    zeilen += ["", "## Haltgrund", haltgrund]
    return "\n".join(zeilen) + "\n"


# ---------------------------------------------------------------------------
# Anbieter-Aufrufe
# ---------------------------------------------------------------------------

class LeitstandFehler(Exception):
    """Basisklasse."""


class LeitstandNetzFehler(LeitstandFehler):
    """Anbieter nicht erreichbar oder Zeitueberschreitung."""


class LeitstandAntwortFehler(LeitstandFehler):
    """Antwort ist kein gueltiges Entscheidungs-JSON."""


@dataclass
class Entscheidung:
    entscheidung: str
    schritt: int | None
    auftrag: str
    grund: str


_GUELTIGE_ENTSCHEIDUNGEN = ("weiter", "wiederholen", "stopp")

# Haeufigster Fall, wenn ein Anbieter die geforderte JSON-Antwort trotzdem in
# einen Markdown-Zaun packt ("```json\n{...}\n```") - Gemini mit erzwungenem
# JSON-Modus braucht das nicht, Anthropic ohne diesen Modus gelegentlich schon.
_ZAUN_MUSTER = re.compile(r"^```(?:json)?\s*\n?|\n?```\s*$", re.IGNORECASE)


def _json_dekodieren(text: str) -> dict:
    """`json.loads`, mit einem zweiten Versuch ohne einen umschliessenden
    Markdown-Zaun. Wirft weiterhin `ValueError`, wenn beides scheitert - der
    Aufrufer formt daraus LeitstandAntwortFehler."""
    try:
        return json.loads(text.strip())
    except ValueError:
        pass
    return json.loads(_ZAUN_MUSTER.sub("", text.strip()).strip())


def _gemini_aufrufen(api_schluessel: str, prompt: str, zeitlimit: int,
                      json_erzwingen: bool) -> tuple[str, dict]:
    """Ein POST an GEMINI_URL, gibt (Antworttext, Nutzung) zurueck. Der
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
        text = str(daten["candidates"][0]["content"]["parts"][0]["text"])
        nutzung = daten.get("usageMetadata") or {}
        return text, {
            "eingabe_token": int(nutzung.get("promptTokenCount", 0) or 0),
            "ausgabe_token": int(nutzung.get("candidatesTokenCount", 0) or 0),
        }
    except (ValueError, KeyError, IndexError, TypeError) as fehler:
        log.warning("Leitstand: Gemini-Antwort ohne verwertbaren Text (%s)",
                    type(fehler).__name__)
        raise LeitstandAntwortFehler("Antwort ohne verwertbaren Text") from fehler


def _anthropic_aufrufen(api_schluessel: str, prompt: str, zeitlimit: int,
                         max_tokens: int = ANTHROPIC_MAX_TOKENS) -> tuple[str, dict]:
    """Ein POST an die Messages-API (platform.claude.com/docs/en/get-started),
    gibt (Antworttext, Nutzung) zurueck. Der Schluessel steht nur im Kopf
    "x-api-key", nie im protokollierten Text."""
    headers = {
        "x-api-key": api_schluessel,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": ANTHROPIC_MODELL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        antwort = requests.post(ANTHROPIC_URL, headers=headers, json=body, timeout=zeitlimit)
        antwort.raise_for_status()
    except requests.RequestException as fehler:
        log.info("Leitstand: Anthropic nicht erreichbar (%s)", type(fehler).__name__)
        raise LeitstandNetzFehler(type(fehler).__name__) from fehler
    try:
        daten = antwort.json()
        text = str(daten["content"][0]["text"])
        nutzung = daten.get("usage") or {}
        return text, {
            "eingabe_token": int(nutzung.get("input_tokens", 0) or 0),
            "ausgabe_token": int(nutzung.get("output_tokens", 0) or 0),
        }
    except (ValueError, KeyError, IndexError, TypeError) as fehler:
        log.warning("Leitstand: Anthropic-Antwort ohne verwertbaren Text (%s)",
                    type(fehler).__name__)
        raise LeitstandAntwortFehler("Antwort ohne verwertbaren Text") from fehler


def _aufrufen(benutzter_anbieter: str, api_schluessel: str, prompt: str, zeitlimit: int,
              json_erzwingen: bool) -> tuple[str, dict]:
    if benutzter_anbieter == ANBIETER_ANTHROPIC:
        return _anthropic_aufrufen(api_schluessel, prompt, zeitlimit)
    return _gemini_aufrufen(api_schluessel, prompt, zeitlimit, json_erzwingen)


def entscheidung_abfragen(benutzter_anbieter: str, api_schluessel: str, plan_text: str,
                           offen_text: str, bericht_text: str,
                           zeitlimit: int) -> tuple[Entscheidung, dict]:
    """Fragt den gewaehlten Anbieter nach der naechsten Entscheidung, gibt
    (Entscheidung, Nutzung) zurueck. Wirft LeitstandNetzFehler bei einem
    Netzfehler oder einer Zeitueberschreitung, LeitstandAntwortFehler bei
    kaputtem oder unvollstaendigem JSON. Protokolliert nur Laengen und das
    Ergebnis, nie den vollen Inhalt von Plan, offenen Punkten oder Bericht -
    und nie den Schluessel."""
    prompt = _PROMPT.format(plan=plan_text.strip() or "(leer)",
                             offen=offen_text.strip() or "(leer)",
                             bericht=bericht_text.strip() or "(leer)")
    log.info("Leitstand: %s-Anfrage gesendet (Prompt %d Zeichen)", benutzter_anbieter, len(prompt))
    text, nutzung = _aufrufen(benutzter_anbieter, api_schluessel, prompt, zeitlimit,
                              json_erzwingen=True)
    try:
        geparst = _json_dekodieren(text)
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
    return Entscheidung(entscheidung=wert, schritt=schritt, auftrag=auftrag, grund=grund), nutzung


def verbindungstest(benutzter_anbieter: str, api_schluessel: str,
                     zeitlimit: int = STANDARD_ZEITLIMIT_SEKUNDEN) -> str:
    """Ein harmloser Aufruf ("Antworte mit OK") als Verbindungstest, ohne
    JSON-Modus. Gibt den Antworttext zurueck oder wirft LeitstandNetzFehler/
    LeitstandAntwortFehler."""
    text, _nutzung = _aufrufen(benutzter_anbieter, api_schluessel, "Antworte mit OK",
                                zeitlimit, json_erzwingen=False)
    return text


class EntscheidungsFaden(QThread):
    """Fuehrt genau eine Anbieter-Anfrage in einem eigenen Thread aus, damit
    ein langsamer oder haengender Netzaufruf das Fenster nie blockiert (wie
    core.bruecke.BerichtFaden). `fertig` liefert immer ein dict: bei Erfolg
    {"ok": True, "anbieter", "entscheidung", "schritt", "auftrag", "grund",
    "eingabe_token", "ausgabe_token"}, sonst {"ok": False, "text":
    "<Fehlerklasse>"}."""

    fertig = Signal(dict)

    def __init__(self, benutzter_anbieter: str, api_schluessel: str, plan_text: str,
                 offen_text: str, bericht_text: str, zeitlimit: int, eltern=None):
        super().__init__(eltern)
        self._anbieter = benutzter_anbieter
        self._api_schluessel = api_schluessel
        self._plan_text = plan_text
        self._offen_text = offen_text
        self._bericht_text = bericht_text
        self._zeitlimit = zeitlimit

    def run(self) -> None:
        try:
            entscheidung, nutzung = entscheidung_abfragen(
                self._anbieter, self._api_schluessel, self._plan_text, self._offen_text,
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
            "anbieter": self._anbieter,
            "entscheidung": entscheidung.entscheidung,
            "schritt": entscheidung.schritt,
            "auftrag": entscheidung.auftrag,
            "grund": entscheidung.grund,
            "eingabe_token": nutzung.get("eingabe_token", 0),
            "ausgabe_token": nutzung.get("ausgabe_token", 0),
        })
