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
* eine Rueckfallliste (abgefragt am 05.09.2026), damit schon vor der ersten
  Verbindung ein Name aufgeloest werden kann.

Block 662: Es gibt keine Modellwahl in der Oberflaeche mehr (kein F12-Feld,
keine Ablage in einstellungen.json) - der Standard ist immer VOREINSTELLUNG
(Sonnet), ein anderes Modell gilt nur fuer genau einen Auftrag ueber die
Zeile "#MODELL# name" (core/fenster.py, _modell_zeile_verarbeiten).
"""

import logging

log = logging.getLogger("cwb.modelle")

# Der Wert, den Claude Code fuer "nimm das voreingestellte Modell" fuehrt.
# Er wird nicht als Modellname weitergereicht, sondern als "nichts angeben".
# Achtung: Claude Code loest "default" auf Opus auf (laut Serverliste
# claude-opus-5[1m]), also auf ein teureres Modell als Sonnet.
STANDARD = "default"

# Block 661/662: der feste Standard, mit dem jede Sitzung beginnt und auf den
# nach jedem Auftrag ohne eigene "#MODELL#"-Zeile zurueckgefallen wird. Bewusst
# Sonnet und nicht STANDARD, damit nie stillschweigend das teurere Opus laeuft
# - ein anderes Modell gilt nur fuer genau einen Auftrag per "#MODELL# name".
VOREINSTELLUNG = "sonnet"

# Deutsche Namen und Kurzhinweise. Schluessel ist der Wert, den Claude Code
# fuehrt. Was hier fehlt, bekommt Namen und Hinweis aus der Serverliste.
HINWEISE = {
    "default": (
        "Standard von Claude Code (Opus)",
        "Opus 5 mit einer Million Token Vorgeschichte. "
        "Stark, aber teuer im Wochenkontingent.",
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


# Block 70, Teil B: Zuordnung vom tatsaechlich aufgeloesten Modellnamen
# (Sitzung.modell_name, z.B. "claude-sonnet-5", "claude-opus-5[1m]") zu einem
# kurzen deutschen Anzeigenamen fuer die Kopfzeile - lang und schmal (bei
# wenig Platz, core/kopfzeile.py). Nicht verwechseln mit HINWEISE oben: das
# dort ist nach dem CLI-Kurznamen ("sonnet", "opus[1m]") geschluesselt, der
# bei der Auswahl gilt, nicht nach dem aufgeloesten Namen der Verbindung.
ANZEIGE_KURZNAMEN = (
    ("fable", "Fable 5.1", "Fable"),
    ("opus", "Opus 5", "Opus"),
    ("sonnet", "Sonnet 5", "Sonnet"),
    ("haiku", "Haiku 4.5", "Haiku"),
)


def anzeige_name(modell_name: str) -> tuple[str, str]:
    """Macht aus dem aufgeloesten Modellnamen einen kurzen Anzeigenamen fuer
    die Kopfzeile: lang (z.B. "Sonnet 5") und schmal bei wenig Platz (z.B.
    "Sonnet"). Kennt `modell_name` keines der vier Modelle, wird er
    unveraendert in beiden Fassungen gezeigt, statt etwas zu erraten."""
    niedrig = (modell_name or "").lower()
    for muster, lang, kurz in ANZEIGE_KURZNAMEN:
        if muster in niedrig:
            return lang, kurz
    name = modell_name or "unbekannt"
    return name, name


# Block 649: Aliase fuer die Zeile "#MODELL# name" direkt nach der
# Markierungszeile (core/fenster.py, modell_zeile_erkennen) - Gross-/
# Kleinschreibung und Leerraum am Rand sind dabei gleichgueltig. "opus",
# "sonnet" und "haiku" sind feste CLI-Kuerzel, die Claude Code immer kennt
# und die darum direkt zurueckgegeben werden; "fable" hat keines und wird
# stattdessen in der (echten oder ersatzweise der Rueckfall-)Modellliste
# gesucht - so bleibt die Zuordnung richtig, auch wenn sich der Name des
# Fable-Eintrags einmal aendert (Stand heute: "claude-fable-5-1[1m]").
ALIASE_KUERZEL = {
    "opus": "opus", "opus-5": "opus", "opus-5.5": "opus",
    "sonnet": "sonnet", "sonnet-5": "sonnet", "sonnet-5.5": "sonnet",
    "haiku": "haiku", "haiku-5": "haiku", "haiku-5.5": "haiku",
}
ALIASE_SUCHWORT = {"fable": "fable", "fable-5": "fable", "fable-5.1": "fable"}


def modellname_aufloesen(name: str, modelle: list[dict] | None = None) -> str | None:
    """Loest einen von Hand in eine '#MODELL#'-Zeile geschriebenen Namen auf
    das CLI-Kuerzel bzw. den vollen Namen auf, den Claude Code bei
    '--model' entgegennimmt.

    `modelle` ist die Liste der laufenden Verbindung (Sitzung.modelle); ist
    sie leer (vor der ersten Verbindung oder ohne brauchbare Serverantwort),
    gilt ersatzweise MODELLE_RUECKFALL. Eine volle Modell-ID aus dieser
    Liste (Feld 'wert' oder 'voll') wird immer direkt angenommen.

    Unbekannt (nichts passt) gibt None zurueck - der Aufrufer bricht dann
    nichts ab, sondern bleibt beim aktiven Modell."""
    gesucht = (name or "").strip().lower()
    if not gesucht:
        return None
    eintraege = modelle if modelle else MODELLE_RUECKFALL
    kuerzel = ALIASE_KUERZEL.get(gesucht)
    if kuerzel:
        return kuerzel
    suchwort = ALIASE_SUCHWORT.get(gesucht)
    if suchwort:
        for eintrag in eintraege:
            wert = str(eintrag.get("wert") or "")
            voll = str(eintrag.get("voll") or "")
            if suchwort in wert.lower() or suchwort in voll.lower():
                return wert or None
        return None
    for eintrag in eintraege:
        wert = str(eintrag.get("wert") or "")
        voll = str(eintrag.get("voll") or "")
        if gesucht == wert.lower():
            return wert
        if gesucht == voll.lower():
            return voll
    return None


def eintrag_suchen(eintraege: list, wert: str) -> dict:
    """Sucht einen Eintrag nach seinem Wert. Nichts gefunden: leerer Eintrag."""
    for eintrag in eintraege or []:
        if eintrag.get("wert") == wert:
            return eintrag
    return {"wert": wert, "name": wert, "hinweis": "", "voll": wert}
