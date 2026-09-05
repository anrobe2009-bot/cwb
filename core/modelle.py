"""
CWB - Code Workbench
Waehlbare Modelle.

Welche Modelle das vorhandene Abo wirklich anbietet, sagt Claude Code selbst.
Die Claude-Code-CLI nimmt bei `--model` einen Kurznamen ("opus", "sonnet") oder
einen vollen Namen entgegen; welche das im eigenen Konto sind, reicht das Agent
SDK ueber `get_server_info()` unter dem Schluessel "models" durch. Genau diese
Liste wird bei jeder Verbindung frisch gelesen. Nichts wird geraten und nichts
angeboten, was das Abo nicht hergibt.

Fest steht in dieser Datei nur zweierlei:

* die deutschen Kurzhinweise, wofuer sich ein Modell eignet - die Beschreibung
  aus der Serverliste ist englisch und wird nur als Rueckfall benutzt,
* eine Rueckfallliste (abgefragt am 05.09.2026), damit das Auswahlfeld schon
  bedienbar ist, bevor die erste Verbindung steht.

Gespeichert wird die Wahl in einstellungen.json unter dem Schluessel "modell".
"""

import logging

try:
    from .grundlagen import einstellungen_lesen, einstellungen_schreiben
except ImportError:
    from grundlagen import einstellungen_lesen, einstellungen_schreiben

log = logging.getLogger("cwb.modelle")

# Schluessel in einstellungen.json
MODELL_SCHLUESSEL = "modell"

# Der Wert, den Claude Code fuer "nimm das voreingestellte Modell" fuehrt.
# Er wird nicht als Modellname weitergereicht, sondern als "nichts angeben".
STANDARD = "default"

# Deutsche Namen und Kurzhinweise. Schluessel ist der Wert, den Claude Code
# fuehrt. Was hier fehlt, bekommt Namen und Hinweis aus der Serverliste.
HINWEISE = {
    "default": (
        "Standard (empfohlen)",
        "Opus 5 mit einer Million Token Vorgeschichte. "
        "Beste Wahl für den Alltag und für schwierige Aufgaben.",
    ),
    "opus[1m]": (
        "Opus (1 Mio Kontext)",
        "Opus 5 mit einer Million Token Vorgeschichte. "
        "Dasselbe wie der Standard, nur ausdrücklich festgelegt.",
    ),
    "opus": (
        "Opus",
        "Opus 5. Beste Wahl für den Alltag und für schwierige Aufgaben.",
    ),
    "claude-fable-5-1[1m]": (
        "Fable",
        "Fable 5.1. Das stärkste Modell, für die schwersten "
        "und die längsten Aufgaben. Teuer und langsamer.",
    ),
    "sonnet": (
        "Sonnet",
        "Sonnet 5. Sparsam und flink für Routinearbeit, "
        "kleine Änderungen und einfache Fragen.",
    ),
    "haiku": (
        "Haiku",
        "Haiku 4.5. Das schnellste Modell, für kurze Fragen "
        "und einfache Handgriffe.",
    ),
}

# Stand 05.09.2026, abgefragt ueber get_server_info(). Nur ein Rueckfall fuer
# die Zeit vor der ersten Verbindung; danach zaehlt allein die Serverliste.
MODELLE_RUECKFALL = [
    {"wert": "default", "name": HINWEISE["default"][0],
     "hinweis": HINWEISE["default"][1], "voll": "claude-opus-5[1m]"},
    {"wert": "opus[1m]", "name": HINWEISE["opus[1m]"][0],
     "hinweis": HINWEISE["opus[1m]"][1], "voll": "claude-opus-5[1m]"},
    {"wert": "claude-fable-5-1[1m]", "name": HINWEISE["claude-fable-5-1[1m]"][0],
     "hinweis": HINWEISE["claude-fable-5-1[1m]"][1], "voll": "claude-fable-5-1"},
    {"wert": "sonnet", "name": HINWEISE["sonnet"][0],
     "hinweis": HINWEISE["sonnet"][1], "voll": "claude-sonnet-5"},
    {"wert": "haiku", "name": HINWEISE["haiku"][0],
     "hinweis": HINWEISE["haiku"][1], "voll": "claude-haiku-4-5-20251001"},
]


def aufbereiten(roh: list) -> list[dict]:
    """Macht aus der Serverliste die Eintraege des Auswahlfelds.

    Jeder Eintrag: 'wert' (was Claude Code als Modell entgegennimmt), 'name'
    (was im Feld steht), 'hinweis' (wofuer sich das Modell eignet) und 'voll'
    (der aufgeloeste Modellname fuer die Anzeige). Kommt nichts Brauchbares
    herein, bleibt die Rueckfallliste stehen."""
    eintraege: list[dict] = []
    try:
        for satz in roh or []:
            wert = (satz or {}).get("value")
            if not wert:
                continue
            name, hinweis = HINWEISE.get(
                wert,
                (satz.get("displayName") or wert, satz.get("description") or ""),
            )
            eintraege.append({
                "wert": wert,
                "name": name,
                "hinweis": hinweis,
                "voll": satz.get("resolvedModel") or wert,
            })
    except Exception as fehler:  # noqa: BLE001
        log.exception("Modellliste nicht lesbar: %s", fehler)
        return list(MODELLE_RUECKFALL)
    if not eintraege:
        log.warning("Serverliste ohne Modelle, Rueckfallliste wird benutzt")
        return list(MODELLE_RUECKFALL)
    return eintraege


def eintrag_suchen(eintraege: list, wert: str) -> dict:
    """Sucht einen Eintrag nach seinem Wert. Nichts gefunden: leerer Eintrag."""
    for eintrag in eintraege or []:
        if eintrag.get("wert") == wert:
            return eintrag
    return {"wert": wert, "name": wert, "hinweis": "", "voll": wert}


def modell_lesen() -> str:
    """Das gemerkte Modell aus einstellungen.json, sonst der Standard."""
    try:
        wert = einstellungen_lesen().get(MODELL_SCHLUESSEL, STANDARD)
        return str(wert) if wert else STANDARD
    except Exception as fehler:  # noqa: BLE001
        log.exception("Modellwahl nicht lesbar: %s", fehler)
        return STANDARD


def modell_merken(wert: str) -> None:
    """Sichert die Modellwahl in einstellungen.json."""
    try:
        werte = einstellungen_lesen()
        werte[MODELL_SCHLUESSEL] = wert or STANDARD
        einstellungen_schreiben(werte)
        log.info("Modellwahl gesichert: %s", wert)
    except Exception as fehler:  # noqa: BLE001
        log.exception("Modellwahl nicht sicherbar: %s", fehler)
