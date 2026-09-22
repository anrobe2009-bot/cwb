"""
CWB - Code Workbench
Baustein 2: Anbindung an Claude Code ueber das Agent-SDK.

Liefert:
- durchgehende Sitzung statt Einzelfragen
- Ereignisse fuer Balken, Ton und Statuszeile
- Berechtigungspruefung ueber sicherheit.Wache
- gesprochene Rueckfrage nur bei Nichtumkehrbarem
- Auftrags-Schaerfung mit Rueckbestaetigung
- Not-Aus
"""

import asyncio
import base64
import logging
import mimetypes
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

try:
    from .modelle import STANDARD as MODELL_STANDARD
    from .modelle import aufbereiten as modelle_aufbereiten
    from .pfade import INDEX_ORDNER, einstellungen_lesen, freigaben_lesen
    from .sicherheit import SCHREIB_WERKZEUGE, Stufe, Urteil, Wache, befehl_schreibt
    from .wissen import (
        HINWEIS_GEDAECHTNIS,
        NACHTRAG_ANWEISUNG,
        Wissen,
        _ohne_dopplungen,
        code_index_vorladen,
    )
except ImportError:
    from modelle import STANDARD as MODELL_STANDARD
    from modelle import aufbereiten as modelle_aufbereiten
    from pfade import INDEX_ORDNER, einstellungen_lesen, freigaben_lesen
    from sicherheit import SCHREIB_WERKZEUGE, Stufe, Urteil, Wache, befehl_schreibt
    from wissen import (
        HINWEIS_GEDAECHTNIS,
        NACHTRAG_ANWEISUNG,
        Wissen,
        _ohne_dopplungen,
        code_index_vorladen,
    )

log = logging.getLogger("cwb.sitzung")

# Laedt das Embedding-Modell des Code-Index einmal pro CWB-Prozess im
# Hintergrund vor (Block C6, Teil A Punkt 3), damit die erste Suche vor
# einem Auftrag nicht auf den Modell-Start warten muss.
code_index_vorladen()


def _unterdruecke_konsolenfenster() -> None:
    """Verhindert, dass die Claude-Code-CLI unter Windows ein eigenes
    Konsolenfenster oeffnet. Das SDK bietet dafuer keine Option in
    ClaudeAgentOptions, daher wird anyio.open_process (das die CLI als
    Unterprozess startet) einmalig um CREATE_NO_WINDOW ergaenzt."""
    if sys.platform != "win32":
        return
    import anyio

    if getattr(anyio.open_process, "_cwb_patched", False):
        return

    original = anyio.open_process
    creationflags = subprocess.CREATE_NO_WINDOW

    async def open_process_ohne_fenster(*args: Any, **kwargs: Any) -> Any:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | creationflags
        return await original(*args, **kwargs)

    open_process_ohne_fenster._cwb_patched = True  # type: ignore[attr-defined]
    anyio.open_process = open_process_ohne_fenster


_unterdruecke_konsolenfenster()


# ---------------------------------------------------------------------------
# Fehlerstrom der CLI
# ---------------------------------------------------------------------------

class Fehlerstrom:
    """Nimmt die stderr-Ausgabe der Claude-Code-CLI auf und schreibt sie ins Log.

    ClaudeAgentOptions bietet dafuer den Rueckruf `stderr`. Ohne ihn leitet das
    SDK stderr des Unterprozesses gar nicht erst um - bei einem Absturz bleibt
    dann nur "Command failed with exit code 1" mit dem Verweis auf eine Ausgabe,
    die nirgends landet. Jede Zeile geht deshalb sofort nach cwb_fehler.log,
    damit auch ein harter Abbruch nichts verschluckt. Zusaetzlich bleiben die
    letzten Zeilen stehen, um sie im Fehlerfall am Stueck zu protokollieren und
    einen kurzen Satz fuer die Ansage daraus zu bilden."""

    GRENZE = 500

    def __init__(self, quelle: str):
        self.quelle = quelle
        self.zeilen: deque[str] = deque(maxlen=self.GRENZE)

    def aufnehmen(self, zeile: str) -> None:
        """Rueckruf fuer ClaudeAgentOptions.stderr. Darf nie werfen."""
        try:
            for teil in str(zeile).splitlines():
                text = teil.rstrip()
                if not text.strip():
                    continue
                self.zeilen.append(text)
                log.warning("CLI-stderr [%s] %s", self.quelle, text)
        except Exception:  # noqa: BLE001
            log.exception("stderr-Rueckruf gescheitert")

    def leeren(self) -> None:
        self.zeilen.clear()

    def protokollieren(self, anlass: str) -> None:
        """Schreibt die gesammelte Ausgabe noch einmal am Stueck ins Log, damit
        sie im Fehlerfall nicht zwischen anderen Zeilen untergeht."""
        if not self.zeilen:
            log.error("%s [%s] - die CLI hat nichts auf stderr ausgegeben",
                      anlass, self.quelle)
            return
        block = "\n".join(self.zeilen)
        log.error("%s [%s] - stderr der CLI, %d Zeilen:\n%s",
                  anlass, self.quelle, len(self.zeilen), block)

    def letzte_meldung(self, zeichen: int = 200) -> str:
        """Die letzte inhaltliche Zeile, gekuerzt - fuer Ansage und Anzeige."""
        for text in reversed(self.zeilen):
            satz = " ".join(text.split())
            if satz:
                return satz[:zeichen]
        return ""

    def ergaenzt(self, meldung: str) -> str:
        """Haengt die letzte stderr-Zeile an eine Fehlermeldung an."""
        letzte = self.letzte_meldung()
        if not letzte:
            return meldung
        return f"{meldung} | CLI meldet: {letzte} (vollstaendig in cwb_fehler.log)"

# Groesste einzelne Nachricht, die das SDK von der CLI annimmt (Vorgabe 1 MB).
NACHRICHT_MAX_BYTES = 32 * 1024 * 1024
# So lange wird nach einem Not-Aus auf den Rest der alten Antwort gewartet,
# damit er nicht in den naechsten Auftrag hineinlaeuft.
STROM_LEEREN_SEKUNDEN = 15
# Hoechstlaufzeit des Code-Index-Hintergrundprozesses (_code_index_warten).
# Grosszuegig, weil ein neues oder grosses Projekt beim allerersten Lauf
# tatsaechlich Minuten braucht - aber endlich, damit ein haengender Prozess
# (z.B. ein Modell-Download ohne Antwort) nicht fuer immer ohne Ergebnis bleibt.
CODE_INDEX_ZEITLIMIT = 30 * 60
# Nach so vielen Auftraegen wird der Kontextblock aus dem Projektgedaechtnis
# erneut vorangestellt (in Kurzfassung, siehe Wissen.kontextblock_kurz).
# Gemessen am 20.09.2026: nach dem ersten Auftrag ruft Claude Code
# memory_search/code_suchen praktisch nie mehr auf, obwohl die Regel dafuer
# in der globalen CLAUDE.md steht - eine feste Auftragszahl ist dafuer
# einfacher verlaesslich als ein Zeitabstand (Sitzungen ohne Pausen wuerden
# nie erinnert) oder eine Themenwechsel-Erkennung (bräuchte einen eigenen
# Modellaufruf je Auftrag). Fuenf hat die Regel laut derselben Messung nicht
# wach gehalten (memory_search seit 11 Uhr kein einziges Mal, code_suchen seit
# 14:41 nicht mehr, bei 789 Grep/Read-Aufrufen); zwei haelt sie deutlich
# praesenter, auf Kosten von etwas mehr Platz je Sitzung.
AUFTRAG_KONTEXT_ALLE = 2


# ---------------------------------------------------------------------------
# Zustaende und Ereignisse
# ---------------------------------------------------------------------------

class Zustand(Enum):
    """Speist Balkenfarbe und Signalton."""
    BEREIT = "bereit"
    SCHAERFT = "schaerft"
    DENKT = "denkt"
    LIEST = "liest"
    SUCHT = "sucht"
    SCHREIBT = "schreibt"
    FUEHRT_AUS = "fuehrt_aus"
    NETZ = "netz"
    WARTET = "wartet"
    FERTIG = "fertig"
    ABGEBROCHEN = "abgebrochen"
    FEHLER = "fehler"


@dataclass
class Ereignis:
    """Ein Schritt. ansage ist kurz und vorlesbar, detail nur auf Abruf.
    pfad ist die Datei, um die es gerade geht - leer, wenn es keine gibt.
    ablehnung markiert eine abgelehnte oder verweigerte Aktion: nur dann
    kommt der volle Wortlaut (detail) ins Ausgabefeld. hinweis markiert eine
    erlaubte Aktion, von der der Nutzer trotzdem einmal erfahren soll
    (gesprochen und als Zeile im Ausgabefeld, ohne Zustandswechsel)."""
    zustand: Zustand
    ansage: str
    detail: str = ""
    pfad: str = ""
    taetigkeit: str = ""
    ablehnung: bool = False
    hinweis: bool = False
    zeitpunkt: datetime = field(default_factory=datetime.now)

    def zeile(self) -> str:
        return f"{self.zeitpunkt.strftime('%H:%M:%S')}  {self.ansage}"


# Werkzeugname -> (Zustand, Verbform fuer die Ansage)
WERKZEUG_ZUSTAND: dict[str, tuple[Zustand, str]] = {
    "Read": (Zustand.LIEST, "Datei gelesen"),
    "Glob": (Zustand.SUCHT, "Dateien gesucht"),
    "Grep": (Zustand.SUCHT, "Inhalt durchsucht"),
    "Write": (Zustand.SCHREIBT, "Datei geschrieben"),
    "Edit": (Zustand.SCHREIBT, "Datei geaendert"),
    "MultiEdit": (Zustand.SCHREIBT, "Datei mehrfach geaendert"),
    "NotebookEdit": (Zustand.SCHREIBT, "Notebook geaendert"),
    "Bash": (Zustand.FUEHRT_AUS, "Befehl ausgefuehrt"),
    "BashOutput": (Zustand.FUEHRT_AUS, "Ausgabe geholt"),
    "KillShell": (Zustand.FUEHRT_AUS, "Prozess beendet"),
    "WebSearch": (Zustand.NETZ, "Im Netz gesucht"),
    "WebFetch": (Zustand.NETZ, "Seite geholt"),
    "TodoWrite": (Zustand.DENKT, "Planung aktualisiert"),
    "Task": (Zustand.DENKT, "Teilaufgabe gestartet"),
}

# Werkzeuge, die einen Pfad im Eingabefeld fuehren
PFAD_FELDER = ("file_path", "path", "notebook_path", "filePath")

# Werkzeugname -> Taetigkeit in einem Wort, Gegenwartsform. Nur das Tun,
# nie ein Ziel: der Dateiname steht in der Oberflaeche in einem eigenen Feld.
WERKZEUG_TAETIGKEIT: dict[str, str] = {
    "Read": "liest",
    "Glob": "sucht",
    "Grep": "sucht",
    "Write": "schreibt",
    "Edit": "schreibt",
    "MultiEdit": "schreibt",
    "NotebookEdit": "schreibt",
    "Bash": "führt aus",
    "BashOutput": "liest",
    "KillShell": "führt aus",
    "WebSearch": "sucht",
    "WebFetch": "liest",
    "TodoWrite": "denkt",
    "Task": "denkt",
}

# Taetigkeit fuer Werkzeuge, die in der Tabelle nicht stehen
TAETIGKEIT_UNBEKANNT = "führt aus"

# Werkzeuge, die immer eine gesprochene Rueckfrage ausloesen (Git hilft hier nicht)
NETZ_WERKZEUGE = {"WebFetch", "WebSearch"}

# Suchpflicht vor Aenderungen (Block C6, Teil B): die MCP-Namen der beiden
# Nachschlage-Werkzeuge, nach dem Muster mcp__<Servername>__<Werkzeug> - die
# Servernamen stammen aus index/mcp_server.py (SERVER_NAME) und der
# Registrierung von memory-hub in ~/.claude.json.
MEMORY_SEARCH_WERKZEUG = "mcp__memory-hub__memory_search"
CODE_SUCHEN_WERKZEUG = "mcp__code-index__code_suchen"
NACHSCHLAGE_WERKZEUGE = {MEMORY_SEARCH_WERKZEUG, CODE_SUCHEN_WERKZEUG}

MELDUNG_SUCHPFLICHT = (
    "Erst nachschlagen: rufe memory_search mit Stichworten zum Auftrag und "
    "code_suchen zur betroffenen Stelle auf, dann aendere."
)


# Ordner fuer das Auftragsprotokoll, relativ zum Projekt
PROTOKOLL_UNTERORDNER = Path(".cwb") / "protokoll"

# Laenge, ab der ein Werkzeugergebnis im Protokoll abgeschnitten wird
PROTOKOLL_ERGEBNIS_LAENGE = 300


# Rueckrufe, die die Oberflaeche setzt
EreignisRuf = Callable[[Ereignis], None]
TextRuf = Callable[[str], None]
FrageRuf = Callable[[str, str], Awaitable[bool]]
VerbrauchRuf = Callable[[dict[str, int]], None]


SYSTEM_ZUSATZ = """Du arbeitest in CWB, einer barrierefreien Oberflaeche.
Der Nutzer ist blind und laesst sich Antworten vorlesen.

Regeln:
- Antworte kurz. Keine langen Erklaerungen, keine Wiederholung des Codes im Chat.
- Nach getaner Arbeit: ein bis drei Saetze, was geaendert wurde. Mehr nicht.
- Strikte Trennung: keine Inline-Scripts, keine Inline-Styles, keine Inline-Event-Handler.
  Scripts in .js, Styles in .css, Handler nur ueber addEventListener.
- Barrierefreiheit hat Vorrang, die Oberflaeche muss fuer sehende Nutzer trotzdem gut aussehen.
- Flexible, responsive Raster. Keine festen Pixelgroessen.
- Jede neue Werkzeugdatei bekommt Fehler-Logging ueber das Modul logging.
- Lies eine Datei, bevor du sie aenderst.
- Wenn etwas unklar, unmoeglich oder unlogisch ist: sag es in einem Satz, statt zu raten.
- Starte keine Hintergrund-Agenten und keine Hintergrund-Befehle. Unteragenten
  sind erlaubt, aber nur im Vordergrund. Beende deine Antwort erst, wenn alle
  Ergebnisse vorliegen."""


# ---------------------------------------------------------------------------
# Sitzung
# ---------------------------------------------------------------------------

class Sitzung:
    """Haelt die Verbindung zu Claude Code fuer ein Projekt."""

    def __init__(
        self,
        wache: Wache,
        bei_ereignis: EreignisRuf | None = None,
        bei_text: TextRuf | None = None,
        bei_rueckfrage: FrageRuf | None = None,
        bei_verbrauch: VerbrauchRuf | None = None,
        modell: str | None = None,
    ):
        self.wache = wache
        self.bei_ereignis = bei_ereignis or (lambda e: None)
        self.bei_text = bei_text or (lambda t: None)
        self.bei_rueckfrage = bei_rueckfrage
        self.bei_verbrauch = bei_verbrauch or (lambda v: None)
        # "default" heisst: kein Modell angeben und Claude Code entscheiden
        # lassen. Alles andere wird unveraendert weitergereicht.
        self.modell = None if (modell or MODELL_STANDARD) == MODELL_STANDARD else modell
        self.modell_name = ""
        # Die vom Abo wirklich angebotenen Modelle, gefuellt beim Verbinden.
        self.modelle: list[dict] = []

        self.klient: ClaudeSDKClient | None = None
        self.wissen: Wissen | None = None
        self.schritte: list[Ereignis] = []
        self.laeuft = False
        self.begonnen: datetime | None = None
        self._abbruch = False
        self._kontext_ausstehend = ""
        # Zaehlt Auftraege seit dem letzten vorangestellten Kontextblock, um
        # ihn alle AUFTRAG_KONTEXT_ALLE Auftraege in Kurzfassung zu
        # wiederholen (siehe auftrag()); wird beim Verbinden neu aufgesetzt.
        self._auftraege_seit_kontext = 0
        # Suchpflicht vor Aenderungen (Block C6, Teil B): welche der beiden
        # Nachschlage-Werkzeuge in dieser Sitzung ueberhaupt verbunden sind
        # (gefuellt beim Verbinden ueber get_mcp_status), ob im laufenden
        # Auftrag schon eines davon aufgerufen wurde, und ob der Hinweis auf
        # fehlende MCP-Server schon einmal vermerkt wurde (nur einmal noetig).
        self._nachschlage_verfuegbar: set[str] = set()
        self._nachschlage_erfuellt = False
        self._suchpflicht_hinweis_gegeben = False
        self.fehlerstrom = Fehlerstrom("Sitzung")
        self.verbrauch = {
            "eingabe": 0, "cache_gelesen": 0, "cache_erstellt": 0, "ausgabe": 0,
            "gesamt": 0, "sitzung": 0,
            "sitzung_eingabe": 0, "sitzung_ausgabe": 0,
            "sitzung_cache_gelesen": 0, "sitzung_cache_erstellt": 0,
        }
        self._protokoll: dict[str, Any] | None = None

    # -- Ereignisse ---------------------------------------------------------

    def _melde(self, zustand: Zustand, ansage: str, detail: str = "",
               pfad: str = "", taetigkeit: str = "", ablehnung: bool = False,
               hinweis: bool = False) -> None:
        ereignis = Ereignis(zustand, ansage, detail, pfad, taetigkeit, ablehnung, hinweis)
        self.schritte.append(ereignis)
        try:
            self.bei_ereignis(ereignis)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Ereignisrueckruf gescheitert: %s", fehler)

    def stand(self) -> str:
        """Antwort auf die Taste 'Wo stehen wir?'."""
        if not self.laeuft:
            return (f"Nichts laeuft gerade. {self.verbrauch['sitzung']} Token in dieser Sitzung, "
                    f"{self.verbrauch['gesamt']} beim letzten Aufruf.")
        anzahl = len(self.schritte)
        dauer = int((datetime.now() - self.begonnen).total_seconds()) if self.begonnen else 0
        letzte = self.schritte[-1].ansage if self.schritte else "gestartet"
        return f"Schritt {anzahl}, laeuft seit {dauer} Sekunden. Zuletzt: {letzte}."

    def _verbrauch_erfassen(self, nachricht: ResultMessage) -> None:
        """Haelt die Tokenwerte des letzten Auftrags fest und summiert die Sitzung.

        Bedeutung der Felder der ResultMessage (usage des Agent SDK, durchgereicht
        aus der Messages-API):
          input_tokens            - frische Eingabe, die nicht aus dem Cache kam
          cache_read_input_tokens - aus dem Prompt-Cache gelesen, wiederholt bei
                                    jedem Aufruf fast die ganze Unterhaltung
          cache_creation_input_tokens - neu in den Cache geschrieben
          output_tokens           - erzeugte Antwort

        Die ResultMessage fasst bereits alle API-Aufrufe eines Auftrags zusammen.
        Als Hauptzahl zaehlen nur frische Eingabe und Ausgabe; die Cache-Werte
        wuerden dieselbe Unterhaltung bei jedem Auftrag erneut mitzaehlen und
        stehen deshalb nur im Kurzhinweis. Die Sitzungssumme addiert die
        Auftragswerte, weil jeder Auftrag eigene frische Tokens verbraucht.
        """
        nutzung = nachricht.usage or {}
        eingabe = int(nutzung.get("input_tokens", 0) or 0)
        cache_gelesen = int(nutzung.get("cache_read_input_tokens", 0) or 0)
        cache_erstellt = int(nutzung.get("cache_creation_input_tokens", 0) or 0)
        ausgabe = int(nutzung.get("output_tokens", 0) or 0)
        vorher = self.verbrauch
        self.verbrauch = {
            "eingabe": eingabe,
            "cache_gelesen": cache_gelesen,
            "cache_erstellt": cache_erstellt,
            "ausgabe": ausgabe,
            "gesamt": eingabe + ausgabe,
            "sitzung": vorher.get("sitzung", 0) + eingabe + ausgabe,
            "sitzung_eingabe": vorher.get("sitzung_eingabe", 0) + eingabe,
            "sitzung_ausgabe": vorher.get("sitzung_ausgabe", 0) + ausgabe,
            "sitzung_cache_gelesen": vorher.get("sitzung_cache_gelesen", 0) + cache_gelesen,
            "sitzung_cache_erstellt": vorher.get("sitzung_cache_erstellt", 0) + cache_erstellt,
        }
        try:
            self.bei_verbrauch(dict(self.verbrauch))
        except Exception as fehler:  # noqa: BLE001
            log.exception("Verbrauchsrueckruf gescheitert: %s", fehler)

    # -- Nur-Lesen-Modus ----------------------------------------------------

    @property
    def nur_lesen(self) -> bool:
        return self.wache.nur_lesen

    def nur_lesen_setzen(self, an: bool) -> str:
        """Schaltet den Nur-Lesen-Modus der Wache. Gibt den Ansagesatz zurueck."""
        satz = self.wache.nur_lesen_setzen(an)
        if not self.laeuft:
            self._melde(Zustand.BEREIT, satz)
        return satz

    # -- Berechtigungen -----------------------------------------------------

    def _pfad_aus_eingabe(self, eingabe: dict[str, Any]) -> str | None:
        for feld in PFAD_FELDER:
            wert = eingabe.get(feld)
            if isinstance(wert, str) and wert:
                return wert
        return None

    def _ist_hintergrund(self, name: str, eingabe: dict[str, Any]) -> bool:
        """Erkennt einen Hintergrundstart: das Parameterfeld run_in_background
        (Bash, Agent) oder das Werkzeug Workflow, das immer im Hintergrund
        laeuft. Ergebnis kommt dann erst in einer spaeteren Antwortrunde nach,
        die auftrag() nach der ersten ResultMessage nicht mehr abholt - der
        Auftrag gilt als fertig, das Ergebnis ist verloren."""
        if eingabe.get("run_in_background") is True:
            return True
        return name == "Workflow"

    def _hintergrund_ablehnen(self, name: str, eingabe: dict[str, Any]) -> None:
        """Lehnt einen Hintergrundstart ab. Geht nur ins Auftragsprotokoll und
        nach cwb_fehler.log - bewusst ohne _melde/Ansage, die Ablehnung soll
        nicht gesprochen werden."""
        ziel = (
            self._pfad_aus_eingabe(eingabe)
            or str(eingabe.get("command") or eingabe.get("prompt") or "")[:200]
            or name
        )
        begruendung = f"Hintergrund gesperrt ({name}), im Vordergrund erneut ausfuehren"
        log.warning("Hintergrund abgelehnt: %s | Ziel: %s", name, ziel)
        self._protokoll_ablehnung_erfassen(ziel, begruendung)

    def _suchpflicht_verletzt(self, name: str, eingabe: dict[str, Any]) -> bool:
        """Wahr, wenn dieser Aufruf eine schreibende Aktion ist, die
        Suchpflicht eingeschaltet ist, in dieser Sitzung mindestens ein
        Nachschlage-Werkzeug verbunden ist und im laufenden Auftrag noch
        keines davon aufgerufen wurde (Block C6, Teil B)."""
        if self._nachschlage_erfuellt or not self._nachschlage_verfuegbar:
            return False
        if not einstellungen_lesen().get("suchpflicht_vor_aenderungen", True):
            return False
        if name in SCHREIB_WERKZEUGE:
            return True
        if name == "Bash":
            return bool(befehl_schreibt(str(eingabe.get("command", ""))))
        return False

    def _suchpflicht_ablehnen(self, name: str, eingabe: dict[str, Any]) -> PermissionResultDeny:
        """Lehnt die erste schreibende Aktion eines Auftrags ab, solange
        weder memory_search noch code_suchen aufgerufen wurden. Geht bewusst
        nicht durch `_melde`: die Ablehnung wird nicht gesprochen oder im
        Ausgabefeld gezeigt (Block C6, Teil B Punkt 8), nur protokolliert."""
        ziel = self._pfad_aus_eingabe(eingabe) or str(eingabe.get("command", "")) or name
        log.info("Suchpflicht: Schreiben abgelehnt vor erster Suche (%s): %s", name, ziel)
        if self._protokoll is not None:
            self._protokoll["suchpflicht_ablehnungen"] += 1
        return PermissionResultDeny(message=MELDUNG_SUCHPFLICHT)

    async def _darf_werkzeug(
        self, name: str, eingabe: dict[str, Any], kontext: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Wird vom SDK vor jedem Werkzeugaufruf gerufen."""
        try:
            if self._ist_hintergrund(name, eingabe):
                self._hintergrund_ablehnen(name, eingabe)
                return PermissionResultDeny(
                    message="Hintergrund ist gesperrt, im Vordergrund erneut ausfuehren."
                )

            urteil = self.wache.darf_werkzeug(name)
            if urteil.verboten:
                ziel = self._pfad_aus_eingabe(eingabe) or name
                return self._ablehnen(urteil, ziel)

            if name in NACHSCHLAGE_WERKZEUGE:
                self._nachschlage_erfuellt = True
            elif name in SCHREIB_WERKZEUGE and self._suchpflicht_verletzt(name, eingabe):
                # Nur-Lesen hat schon vorher (wache.darf_werkzeug) abgelehnt,
                # falls es zutrifft - hier greift die Suchpflicht nur noch,
                # wenn das Schreiben sonst erlaubt waere.
                return self._suchpflicht_ablehnen(name, eingabe)

            pfad = self._pfad_aus_eingabe(eingabe)
            if pfad:
                urteil = self.wache.darf_pfad(pfad)
                if urteil.verboten:
                    return self._ablehnen(urteil, urteil.ziel() or pfad)
                if urteil.hinweis:
                    self._hinweis_geben(urteil, pfad)

            if name == "Bash":
                befehl = str(eingabe.get("command", ""))
                urteil = self.wache.darf_befehl(befehl)
                if urteil.verboten:
                    return self._ablehnen(urteil, befehl)
                if self._suchpflicht_verletzt(name, eingabe):
                    return self._suchpflicht_ablehnen(name, eingabe)
                if urteil.stufe is Stufe.RUECKFRAGE:
                    return await self._frage(urteil.begruendung, befehl)

            if name in NETZ_WERKZEUGE:
                if self.wache.internet_frei():
                    return PermissionResultAllow()
                ziel = str(eingabe.get("url") or eingabe.get("query") or "")
                return await self._frage("Zugriff auf das Internet", ziel)

            return PermissionResultAllow()

        except Exception as fehler:  # noqa: BLE001
            ziel = self._pfad_aus_eingabe(eingabe) or str(eingabe.get("command", "")) or name
            log.exception("Berechtigungspruefung gescheitert fuer %s: %s", ziel, fehler)
            kurz, satz = self._ablehnungssaetze(
                "Pruefung gescheitert, sicherheitshalber abgelehnt", ziel
            )
            self._melde(Zustand.FEHLER, kurz, satz, ziel, ablehnung=True)
            return PermissionResultDeny(message=satz)

    def _kurzes_ziel(self, ziel: str) -> str:
        """Kurzform eines Ziels fuer die Ansage: bei Pfaden nur der Dateiname
        ohne Ordner und Laufwerk, sonst das Ziel selbst, notfalls gekuerzt.
        Der volle Pfad bleibt in Ausgabefeld, Protokoll und Log stehen."""
        ziel = (ziel or "").strip()
        if not ziel:
            return ""
        if "/" in ziel or "\\" in ziel:
            name = Path(ziel).name
            return f"Datei {name}" if name else ziel
        if len(ziel) > 60:
            return ziel[:60].rstrip() + " …"
        return ziel

    def _ablehnungssaetze(self, begruendung: str, ziel: str) -> tuple[str, str]:
        """Baut aus Begruendung und Ziel zwei Saetze: einen kurzen ohne Pfad
        fuer Ansage und Statuszeile, einen vollstaendigen mit Pfad fuer
        Ausgabefeld, Protokoll und Log."""
        ziel = (ziel or "").strip()
        if not ziel or ziel in begruendung:
            return begruendung, begruendung
        kurzziel = self._kurzes_ziel(ziel)
        trenner = ", " if kurzziel.startswith("Datei ") else ": "
        return f"{begruendung}{trenner}{kurzziel}", f"{begruendung}: {ziel}"

    def _ablehnen(self, urteil: Urteil, ziel: str) -> PermissionResultDeny:
        """Harte Ablehnung. Der volle Wortlaut mit Pfad geht ins Ausgabefeld,
        Protokoll und Log; gesprochen und in der Statuszeile steht nur ein
        kurzer Satz ohne Pfad."""
        ziel = (ziel or "").strip()
        kurz, satz = self._ablehnungssaetze(urteil.begruendung, ziel)
        log.warning("Abgelehnt: %s | Ziel: %s", urteil.begruendung, ziel or "(ohne Ziel)")
        self._melde(Zustand.FEHLER, kurz, satz, ziel, ablehnung=True)
        self._protokoll_ablehnung_erfassen(ziel, urteil.begruendung)
        return PermissionResultDeny(message=satz)

    def _hinweis_geben(self, urteil: Urteil, pfad: str) -> None:
        """Erlaubter Vorgang, der trotzdem einmal angesagt wird - etwa der erste
        Zugriff ausserhalb des Projekts in einem Auftrag. Der Zustand bleibt,
        wie er ist (kein Balkenwechsel, kein neuer Ton); gesprochen wird der
        kurze Satz aus dem Urteil, der volle Pfad steht nur im Ausgabefeld,
        Protokoll und Log."""
        zustand = self.schritte[-1].zustand if self.schritte else Zustand.DENKT
        log.info("Hinweis: %s | Ziel: %s", urteil.hinweis, pfad)
        self._melde(
            zustand, urteil.hinweis, f"{urteil.hinweis} Pfad: {pfad}", pfad,
            hinweis=True,
        )
        self._protokoll_hinweis_erfassen(pfad, urteil.hinweis)

    async def _frage(self, grund: str, detail: str) -> PermissionResultAllow | PermissionResultDeny:
        """Gesprochene Ein-Satz-Rueckfrage mit dem betroffenen Pfad oder Befehl.
        Ohne Rueckruf wird abgelehnt. Ergebnis-Ansagen bleiben kurz und ohne
        Pfad; der volle Wortlaut geht ins Ausgabefeld, Protokoll und Log.

        Gesprochen wird ausschliesslich `kurz_satz`, gebaut allein aus `grund`
        (ein kurzer, fest formulierter Anlass wie "Node-Paket installieren
        oder ausfuehren") - nie aus `ziel`, denn dort steht der Befehl oder
        Pfad im vollen Wortlaut. Der volle Satz `satz` geht nur ins
        Ausgabefeld, Protokoll und Log."""
        ziel = (detail or "").strip()
        mit_ziel = f"{grund}: {ziel}" if ziel else grund
        kurz_grund, _ = self._ablehnungssaetze(grund, ziel)

        if self.bei_rueckfrage is None:
            log.warning("Keine Rueckfragestelle gesetzt, abgelehnt: %s", mit_ziel)
            satz = f"Keine Bestaetigung moeglich: {mit_ziel}"
            self._melde(
                Zustand.FEHLER, f"Keine Bestaetigung moeglich, {kurz_grund}", satz, ziel,
                ablehnung=True,
            )
            return PermissionResultDeny(message=satz)

        satz = f"{mit_ziel}. Fortfahren?"
        kurz_satz = f"{grund.strip()}. Fortfahren?"
        log.info("Rueckfrage: %s | Ziel: %s", grund, ziel or "(ohne Ziel)")
        self._melde(Zustand.WARTET, f"Rueckfrage: {kurz_grund}", f"Rueckfrage: {mit_ziel}", ziel)
        try:
            erlaubt = await self.bei_rueckfrage(satz, kurz_satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Rueckfrage gescheitert (%s): %s", mit_ziel, fehler)
            fehlersatz = f"Rueckfrage gescheitert: {mit_ziel}"
            self._melde(
                Zustand.FEHLER, f"Rueckfrage gescheitert, {kurz_grund}", fehlersatz, ziel,
                ablehnung=True,
            )
            return PermissionResultDeny(message=fehlersatz)

        if erlaubt:
            log.info("Freigegeben: %s", mit_ziel)
            self._melde(Zustand.FUEHRT_AUS, f"Freigegeben: {kurz_grund}", f"Freigegeben: {mit_ziel}", ziel)
            self._protokoll_rueckfrage_erfassen(grund, ziel, True)
            return PermissionResultAllow()
        log.warning("Vom Nutzer abgelehnt: %s", mit_ziel)
        self._melde(
            Zustand.ABGEBROCHEN, f"Abgelehnt: {kurz_grund}", f"Abgelehnt: {mit_ziel}", ziel,
            ablehnung=True,
        )
        self._protokoll_rueckfrage_erfassen(grund, ziel, False)
        return PermissionResultDeny(message=f"Vom Nutzer abgelehnt: {mit_ziel}")

    # -- Auftragsprotokoll ----------------------------------------------------

    def _ziel_aus_eingabe(self, name: str, eingabe: dict[str, Any]) -> str:
        pfad = self._pfad_aus_eingabe(eingabe)
        if pfad:
            return pfad
        if name == "Bash":
            return str(eingabe.get("command", ""))
        if name in NETZ_WERKZEUGE:
            return str(eingabe.get("url") or eingabe.get("query") or "")
        return str(eingabe)[:200] if eingabe else ""

    def _protokoll_werkzeug_erfassen(self, block: ToolUseBlock) -> None:
        if self._protokoll is None:
            return
        eintrag = {
            "name": block.name,
            "ziel": self._ziel_aus_eingabe(block.name, block.input or {}),
            "ergebnis": "",
        }
        self._protokoll["werkzeuge"].append(eintrag)
        self._protokoll["werkzeug_index"][block.id] = eintrag

    def _protokoll_ergebnis_text(self, block: ToolResultBlock) -> str:
        inhalt = block.content
        if isinstance(inhalt, list):
            inhalt = " ".join(
                teil.get("text", "") for teil in inhalt if isinstance(teil, dict)
            )
        text = " ".join(str(inhalt or "").split())
        if len(text) > PROTOKOLL_ERGEBNIS_LAENGE:
            text = text[:PROTOKOLL_ERGEBNIS_LAENGE] + " …"
        return f"Fehler: {text}" if block.is_error else (text or "(kein Text)")

    def _protokoll_ergebnisse_erfassen(self, nachricht: UserMessage) -> None:
        if self._protokoll is None or isinstance(nachricht.content, str):
            return
        for block in nachricht.content:
            if not isinstance(block, ToolResultBlock):
                continue
            eintrag = self._protokoll["werkzeug_index"].get(block.tool_use_id)
            if eintrag is not None:
                eintrag["ergebnis"] = self._protokoll_ergebnis_text(block)

    def _protokoll_ablehnung_erfassen(self, ziel: str, begruendung: str) -> None:
        if self._protokoll is None:
            return
        self._protokoll["ablehnungen"].append({"ziel": ziel, "begruendung": begruendung})

    def _protokoll_hinweis_erfassen(self, ziel: str, hinweis: str) -> None:
        if self._protokoll is None:
            return
        self._protokoll["hinweise"].append({"ziel": ziel, "hinweis": hinweis})

    def _protokoll_rueckfrage_erfassen(self, grund: str, ziel: str, antwort: bool) -> None:
        if self._protokoll is None:
            return
        self._protokoll["rueckfragen"].append(
            {"grund": grund, "ziel": ziel, "antwort": "Ja" if antwort else "Nein"}
        )

    def _protokoll_schreiben(self, geaendert: list[str]) -> None:
        """Schreibt das Auftragsprotokoll als Markdown unter .cwb/protokoll/."""
        if self._protokoll is None:
            return
        ordner = self.wache.projekt.pfad / PROTOKOLL_UNTERORDNER
        try:
            ordner.mkdir(parents=True, exist_ok=True)
        except OSError as fehler:
            log.error("Protokollordner nicht anlegbar: %s", fehler)
            return

        beginn: datetime = self._protokoll["beginn"]
        ziel_datei = ordner / f"{beginn.strftime('%Y-%m-%d_%H-%M-%S')}.md"

        zeilen = [f"# Auftrag vom {beginn.strftime('%d.%m.%Y %H:%M:%S')}", ""]

        zeilen.append("## Auftrag")
        zeilen.append(self._protokoll["auftrag"].strip() or "(leer)")
        zeilen.append("")

        zeilen.append("## Werkzeugaufrufe")
        werkzeuge = self._protokoll["werkzeuge"]
        if werkzeuge:
            for nummer, eintrag in enumerate(werkzeuge, 1):
                zeilen.append(f"{nummer}. **{eintrag['name']}** — `{eintrag['ziel'] or '(ohne Ziel)'}`")
                zeilen.append(f"   Ergebnis: {eintrag['ergebnis'] or '(kein Ergebnis erfasst)'}")
        else:
            zeilen.append("Keine Werkzeugaufrufe.")
        zeilen.append("")

        zeilen.append("## Ablehnungen")
        ablehnungen = self._protokoll["ablehnungen"]
        if ablehnungen:
            for eintrag in ablehnungen:
                zeilen.append(f"- `{eintrag['ziel'] or '(ohne Ziel)'}` — {eintrag['begruendung']}")
        else:
            zeilen.append("Keine Ablehnungen.")
        zeilen.append("")

        zeilen.append("## Hinweise")
        hinweise = self._protokoll["hinweise"]
        if hinweise:
            for eintrag in hinweise:
                zeilen.append(f"- `{eintrag['ziel'] or '(ohne Ziel)'}` — {eintrag['hinweis']}")
        else:
            zeilen.append("Keine Hinweise.")
        zeilen.append("")

        zeilen.append("## Rückfragen")
        rueckfragen = self._protokoll["rueckfragen"]
        if rueckfragen:
            for eintrag in rueckfragen:
                zeilen.append(
                    f"- {eintrag['grund']}: `{eintrag['ziel'] or '(ohne Ziel)'}` → {eintrag['antwort']}"
                )
        else:
            zeilen.append("Keine Rückfragen.")
        zeilen.append("")

        zeilen.append("## Geänderte Dateien")
        if geaendert:
            zeilen += [f"- {pfad}" for pfad in geaendert]
        else:
            zeilen.append("Keine Datei geändert.")
        zeilen.append("")

        zeilen.append("## Suchpflicht")
        if self._protokoll["suchpflicht_erforderlich"]:
            erfuellt = "ja" if self._nachschlage_erfuellt else "nein"
            zeilen.append(f"Erforderlich: ja. Erfüllt: {erfuellt}. "
                          f"Abgelehnte Schreibversuche: {self._protokoll['suchpflicht_ablehnungen']}.")
        elif self._nachschlage_verfuegbar:
            zeilen.append("Erforderlich: nein (Schalter aus).")
        else:
            zeilen.append("Erforderlich: nein (kein Nachschlage-Werkzeug in dieser Sitzung verbunden).")
        zeilen.append("")

        zeilen.append("## Tokenverbrauch")
        zeilen.append(
            f"Eingabe: {self.verbrauch['eingabe']}, "
            f"Cache gelesen: {self.verbrauch['cache_gelesen']}, "
            f"Cache erstellt: {self.verbrauch['cache_erstellt']}, "
            f"Ausgabe: {self.verbrauch['ausgabe']}, "
            f"Letzter Aufruf ohne Cache: {self.verbrauch['gesamt']}, "
            f"Sitzung gesamt ohne Cache: {self.verbrauch['sitzung']}"
        )
        zeilen.append("")

        try:
            ziel_datei.write_text("\n".join(zeilen), encoding="utf-8")
            log.info("Auftragsprotokoll geschrieben: %s", ziel_datei)
        except OSError as fehler:
            log.error("Protokoll nicht schreibbar: %s", fehler)

    # -- Verbindung ---------------------------------------------------------

    def _einstellungen(self) -> ClaudeAgentOptions:
        # Wird bei jedem Verbindungsaufbau neu gelesen, damit zwischenzeitlich
        # von Hand (F12, Reiter Freigaben) hinzugekommene Freigaben in die
        # naechste Sitzung uebernommen werden - automatisch traegt niemand mehr
        # etwas ein. Fuer die bereits laufende Sitzung wirkt das nicht - add_dirs
        # geht als Startparameter an den CLI-Unterprozess und laesst sich dort
        # nicht nachtraeglich erweitern.
        zusatzordner = [eintrag["pfad"] for eintrag in freigaben_lesen()]
        return ClaudeAgentOptions(
            cwd=str(self.wache.projekt.pfad),
            add_dirs=zusatzordner,
            system_prompt={"type": "preset", "preset": "claude_code", "append": SYSTEM_ZUSATZ},
            setting_sources=["user", "project"],
            permission_mode="default",
            can_use_tool=self._darf_werkzeug,
            model=self.modell,
            include_partial_messages=False,
            stderr=self.fehlerstrom.aufnehmen,
            # Werkzeugergebnisse mit eingebetteten Bildern ueberschreiten die
            # Vorgabe des SDK (1 MB) leicht; dann stirbt dessen Lesefaden
            # und die Sitzung liefert still nichts mehr (siehe auftrag()).
            max_buffer_size=NACHRICHT_MAX_BYTES,
        )

    async def verbinden(self) -> None:
        if self.klient is not None:
            return
        self.klient = ClaudeSDKClient(options=self._einstellungen())
        try:
            await self.klient.connect()
        except Exception as fehler:  # noqa: BLE001
            self.klient = None
            log.exception("Verbindung gescheitert: %s", fehler)
            self.fehlerstrom.protokollieren("Verbindung gescheitert")
            raise
        await self._modelle_lesen()
        await self._nachschlage_werkzeuge_lesen()

        self.wissen = Wissen(self.wache.projekt.pfad, self.wache.projekt.name)
        self.wissen.einrichten()
        self._kontext_ausstehend = self.wissen.kontextblock()
        self._auftraege_seit_kontext = 0

        self._melde(Zustand.BEREIT, f"Projekt geoeffnet: {self.wache.projekt.name}")
        log.info("Sitzung verbunden fuer %s, Modell %s", self.wache.projekt.pfad, self.modell_name)

        self._code_index_anstossen()

    def _code_index_anstossen(self) -> None:
        """Stoesst das Nachindizieren des offenen Projekts an, ohne die
        Sitzung zu blockieren: erst geaenderte Dateien, bei einem unbekannten
        Projekt (kein Manifest) automatisch alles - das kann bei einem neuen
        oder grossen Projekt Minuten dauern, Robert nimmt das bewusst in Kauf.
        Ein veralteter Index zeigt sonst auf Codestellen, die es nicht mehr
        gibt. Laeuft als eigener Prozess im Hintergrund weiter; eine kurze
        Ansage markiert Start und Ende. Gibt es das Werkzeug nicht oder
        scheitert der Start, wird nur geloggt."""
        cli = INDEX_ORDNER / "cli.py"
        if not cli.is_file():
            return
        pfad = str(self.wache.projekt.pfad)
        name = self.wache.projekt.name
        try:
            prozess = subprocess.Popen(
                [sys.executable, str(cli), pfad],
                cwd=str(INDEX_ORDNER), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as fehler:  # noqa: BLE001
            log.warning("Code-Index nicht gestartet: %s", fehler)
            return
        self._melde(Zustand.DENKT, f"Indiziere {name} fuer die Codesuche …")
        threading.Thread(
            target=self._code_index_warten, args=(prozess, name), daemon=True,
        ).start()

    def _code_index_warten(self, prozess: subprocess.Popen, name: str) -> None:
        """Laeuft in einem eigenen Thread, damit das Warten auf den
        Index-Prozess nichts sonst blockiert. `_melde` darf aus jedem Thread
        gerufen werden - es haengt nur ein Qt-Signal an (siehe core/faden.py).

        Ohne Zeitlimit wuerde ein haengender Index-Prozess (z.B. ein Modell-
        Download ohne Antwort) fuer immer in communicate() stehenbleiben: die
        Start-Ansage waere gesagt, aber nie ein Ergebnis oder ein Fehler -
        Robert wartet dann auf etwas, das nie kommt. Jeder Ausgang meldet
        sich deshalb entweder per `_melde` (hoerbar) oder wenigstens per Log."""
        try:
            ausgabe, fehlerausgabe = prozess.communicate(timeout=CODE_INDEX_ZEITLIMIT)
        except subprocess.TimeoutExpired:
            prozess.kill()
            try:
                prozess.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            log.error("Code-Index-Lauf fuer %s abgebrochen (Zeitueberschreitung)", name)
            self._melde(Zustand.FEHLER, f"Indizieren von {name} abgebrochen (Zeitüberschreitung).")
            return
        except Exception as fehler:  # noqa: BLE001
            log.warning("Code-Index-Prozess fuer %s: %s", name, fehler)
            self._melde(Zustand.FEHLER, f"Indizieren von {name} fehlgeschlagen.")
            return
        if prozess.returncode == 0:
            log.info("Code-Index aktualisiert fuer %s: %s", name, (ausgabe or "").strip())
            if "uebersprungen" not in (ausgabe or ""):
                self._melde(Zustand.FERTIG, f"Index aktuell: {name}")
        else:
            log.warning("Code-Index-Lauf fehlgeschlagen fuer %s (%s): %s",
                        name, prozess.returncode, (fehlerausgabe or "").strip()[:500])
            self._melde(Zustand.FEHLER, f"Indizieren von {name} fehlgeschlagen.")

    async def _modelle_lesen(self) -> None:
        """Holt die Modellliste der laufenden Claude-Code-CLI und loest daraus
        den Namen des gerade benutzten Modells auf.

        Die Liste ist dieselbe, aus der auch `claude --model` waehlt; sie zeigt
        also genau das, was das vorhandene Abo hergibt. Ist sie nicht abrufbar,
        bleibt 'modelle' leer und die Oberflaeche behaelt ihre Rueckfallliste."""
        ziel = self.modell or MODELL_STANDARD
        self.modell_name = ziel
        try:
            info = await self.klient.get_server_info()
        except Exception as fehler:  # noqa: BLE001
            log.warning("Serverinfo nicht abrufbar: %s", fehler)
            return
        roh = (info or {}).get("models", [])
        self.modelle = modelle_aufbereiten(roh)
        log.info("Waehlbare Modelle: %s", [e["wert"] for e in self.modelle])
        for eintrag in roh:
            if eintrag.get("value") == ziel:
                self.modell_name = (
                    eintrag.get("resolvedModel") or eintrag.get("displayName") or ziel
                )
                return

    async def _nachschlage_werkzeuge_lesen(self) -> None:
        """Stellt fest, welche der beiden Nachschlage-Werkzeuge (memory_search,
        code_suchen) in dieser Sitzung ueberhaupt ueber MCP verbunden sind -
        Grundlage fuer die Suchpflicht (Block C6, Teil B Punkt 5 und 7): sind
        die MCP-Server nicht verfuegbar, gilt die Pflicht nicht, statt jeden
        Auftrag in eine Ablehnungsschleife laufen zu lassen. Scheitert die
        Abfrage selbst, wird sicherheitshalber angenommen, dass nichts
        verbunden ist - die Pflicht entfaellt dann, statt zu blockieren."""
        self._nachschlage_verfuegbar = set()
        try:
            status = await self.klient.get_mcp_status()
        except Exception as fehler:  # noqa: BLE001
            log.warning("MCP-Status nicht abrufbar, Suchpflicht entfaellt diese Sitzung: %s", fehler)
            return
        for server in (status or {}).get("mcpServers", []):
            if server.get("status") != "connected":
                continue
            werkzeugnamen = {w.get("name") for w in (server.get("tools") or [])}
            self._nachschlage_verfuegbar |= (werkzeugnamen & NACHSCHLAGE_WERKZEUGE)
        if not self._nachschlage_verfuegbar:
            log.info("Suchpflicht: kein Nachschlage-Werkzeug verbunden, Pflicht entfaellt diese Sitzung")

    async def modell_wechseln(self, wert: str) -> str:
        """Legt ein anderes Modell fest und verbindet die Sitzung sofort neu,
        damit die Wahl schon beim naechsten Auftrag greift. Die bisherige
        Unterhaltung endet dabei; das Projektwissen wird neu mitgegeben.
        Gibt den aufgeloesten Modellnamen zurueck."""
        neu = None if (wert or MODELL_STANDARD) == MODELL_STANDARD else wert
        if neu == self.modell and self.klient is not None:
            return self.modell_name
        await self.trennen()
        self.modell = neu
        await self.verbinden()
        log.info("Modell gewechselt auf %s (%s)", wert, self.modell_name)
        return self.modell_name

    async def trennen(self) -> None:
        if self.klient is None:
            return
        try:
            await self.klient.disconnect()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Trennen gescheitert: %s", fehler)
            self.fehlerstrom.protokollieren("Trennen gescheitert")
        finally:
            self.klient = None

    async def not_aus(self) -> None:
        """Bricht den laufenden Auftrag ab."""
        self._abbruch = True
        if self.klient is None:
            return
        try:
            await self.klient.interrupt()
            self._melde(Zustand.ABGEBROCHEN, "Abgebrochen")
            log.info("Not-Aus ausgeloest")
        except Exception as fehler:  # noqa: BLE001
            log.exception("Not-Aus gescheitert: %s", fehler)
            self.fehlerstrom.protokollieren("Not-Aus gescheitert")

    # -- Auftrags-Schaerfung ------------------------------------------------

    async def schaerfen(self, roh: str) -> str:
        """Verdichtet den diktierten Text zu einem Satz zur Rueckbestaetigung."""
        self._melde(Zustand.SCHAERFT, "Auftrag wird geschaerft")
        anweisung = (
            "Fasse den folgenden diktierten Arbeitsauftrag in EINEM kurzen deutschen Satz "
            "zusammen, hoechstens 25 Woerter, ohne Vorrede, ohne Anfuehrungszeichen. "
            "Nur der Satz.\n\nAuftrag:\n" + roh
        )

        async def alles_ablehnen(name, eingabe, kontext):
            return PermissionResultDeny(message="Bei der Schaerfung sind keine Werkzeuge erlaubt")

        fehlerstrom = Fehlerstrom("Schaerfung")
        einstellungen = ClaudeAgentOptions(
            cwd=str(self.wache.projekt.pfad),
            model="claude-haiku-4-5",
            max_turns=1,
            setting_sources=[],
            can_use_tool=alles_ablehnen,
            stderr=fehlerstrom.aufnehmen,
        )

        teile: list[str] = []
        try:
            async for nachricht in query(prompt=anweisung, options=einstellungen):
                if isinstance(nachricht, AssistantMessage):
                    for block in nachricht.content:
                        if isinstance(block, TextBlock):
                            teile.append(block.text)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Schaerfung gescheitert: %s", fehler)
            fehlerstrom.protokollieren("Schaerfung gescheitert")
            return " ".join(roh.split())[:200]

        satz = " ".join("".join(teile).split())
        return satz or " ".join(roh.split())[:200]

    # -- Bilder -------------------------------------------------------------

    def _bild_block(self, bild: Path) -> dict[str, Any] | None:
        try:
            typ = mimetypes.guess_type(str(bild))[0] or "image/png"
            daten = base64.b64encode(bild.read_bytes()).decode("ascii")
        except OSError as fehler:
            log.error("Bild nicht lesbar %s: %s", bild, fehler)
            return None
        return {"type": "image", "source": {"type": "base64", "media_type": typ, "data": daten}}

    def _bild_sichern(self, bild: Path) -> Path:
        """Legt eine Kopie im Projekt ab, damit der Auftrag nachvollziehbar bleibt."""
        ziel_ordner = self.wache.projekt.pfad / ".cwb" / "bilder"
        try:
            ziel_ordner.mkdir(parents=True, exist_ok=True)
            stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
            ziel = ziel_ordner / f"{stempel}_{bild.name}"
            shutil.copy2(bild, ziel)
            return ziel
        except OSError as fehler:
            log.error("Bild nicht sicherbar %s: %s", bild, fehler)
            return bild

    async def _eingabe(self, text: str, bilder: list[Path]) -> AsyncIterator[dict[str, Any]]:
        inhalt: list[dict[str, Any]] = []
        for bild in bilder:
            block = self._bild_block(self._bild_sichern(bild))
            if block:
                inhalt.append(block)
        inhalt.append({"type": "text", "text": text})
        yield {
            "type": "user",
            "message": {"role": "user", "content": inhalt},
            "parent_tool_use_id": None,
            "session_id": "default",
        }

    # -- Auftrag ------------------------------------------------------------

    async def auftrag(self, text: str, bilder: list[Path] | None = None) -> dict[str, Any]:
        """Fuehrt einen Auftrag aus. Rueckgabe: Bilanz fuer die Ansage."""
        bilder = bilder or []
        await self.verbinden()

        self.fehlerstrom.leeren()
        self._abbruch = False
        self.laeuft = True
        self.begonnen = datetime.now()
        self.schritte.clear()
        self._nachschlage_erfuellt = False
        werte = einstellungen_lesen()
        suchpflicht_erforderlich = (
            bool(self._nachschlage_verfuegbar)
            and werte.get("suchpflicht_vor_aenderungen", True)
        )
        self._protokoll = {
            "auftrag": text,
            "beginn": self.begonnen,
            "werkzeuge": [],
            "werkzeug_index": {},
            "ablehnungen": [],
            "hinweise": [],
            "rueckfragen": [],
            "suchpflicht_erforderlich": suchpflicht_erforderlich,
            "suchpflicht_ablehnungen": 0,
        }

        punkt = self.wache.auftrag_beginnen(text)
        if punkt is None:
            self._melde(Zustand.FEHLER, "Kein Sicherungspunkt moeglich")

        self._melde(Zustand.DENKT, "Auftrag laeuft")
        antwort: list[str] = []
        fehlermeldung = ""
        # Jeder Auftrag endet mit genau einer ResultMessage. Bleibt sie aus,
        # ist der Nachrichtenstrom des SDK tot (etwa nach einem Lesefehler):
        # die Verbindung liefert dann fuer jeden weiteren Auftrag sofort
        # nichts mehr und CWB meldete frueher trotzdem "Fertig".
        ergebnis_da = False
        verbindung_tot = False

        sendetext = text
        self._auftraege_seit_kontext += 1
        block = self._kontext_ausstehend
        self._kontext_ausstehend = ""
        if not block and self._auftraege_seit_kontext >= AUFTRAG_KONTEXT_ALLE:
            block = self.wissen.kontextblock_kurz() if self.wissen else ""
        if block:
            self._auftraege_seit_kontext = 0

        # CWB sucht vor JEDEM Auftrag selbst im Memory Hub (FTS5) und im
        # Code-Index dieses Projekts, statt darauf zu warten, dass Claude Code
        # memory_search/code_suchen von sich aus aufruft (Block C6, Teil A;
        # ersetzt die reine Hub-Stichwortsuche aus Block C5). Abschaltbar
        # ueber F12 -> Verhalten -> "Gedaechtnis vor jedem Auftrag".
        treffer = ""
        if self.wissen and werte.get("gedaechtnis_vor_jedem_auftrag", True):
            treffer, _ = self.wissen.gedaechtnis_vor_auftrag(text)
        if treffer and block:
            treffer = _ohne_dopplungen(block, treffer)
        if treffer:
            block = f"{block}\n\n{treffer}" if block else treffer
        if block and HINWEIS_GEDAECHTNIS.strip() not in block:
            block = f"{block}\n{HINWEIS_GEDAECHTNIS}"

        if block:
            sendetext = (
                "[GEDÄCHTNIS VOR DEM AUFTRAG]\n"
                f"{block}\n\n"
                f"[AUFTRAG]\n{text}"
            )

        if self.wache.nur_lesen:
            sendetext = (
                "[NUR-LESEN-MODUS AN – Write, Edit, MultiEdit, NotebookEdit und jeder "
                "schreibende oder loeschende Bash-Befehl werden abgelehnt. Lies, suche "
                "und antworte; schlage Aenderungen hoechstens vor.]\n\n"
                f"{sendetext}"
            )

        try:
            if bilder:
                await self.klient.query(self._eingabe(sendetext, bilder))
            else:
                await self.klient.query(sendetext)

            async for nachricht in self.klient.receive_response():
                if self._abbruch:
                    break

                if isinstance(nachricht, AssistantMessage):
                    for block in nachricht.content:
                        if isinstance(block, TextBlock):
                            antwort.append(block.text)
                            self.bei_text(block.text)
                        elif isinstance(block, ThinkingBlock):
                            self._melde(Zustand.DENKT, "Ueberlegt")
                        elif isinstance(block, ToolUseBlock):
                            self._melde_werkzeug(block)
                            self._protokoll_werkzeug_erfassen(block)

                elif isinstance(nachricht, UserMessage):
                    self._protokoll_ergebnisse_erfassen(nachricht)

                elif isinstance(nachricht, ResultMessage):
                    ergebnis_da = True
                    self._verbrauch_erfassen(nachricht)
                    if nachricht.is_error:
                        self.fehlerstrom.protokollieren("Claude Code meldet einen Fehler")
                        fehlermeldung = self.fehlerstrom.ergaenzt(
                            str(nachricht.result or "Claude Code meldet einen Fehler")
                        )

        except Exception as fehler:  # noqa: BLE001
            # Ein Fehler aus dem Strom stammt vom Lesefaden des SDK, der
            # danach beendet ist - der Klient ist damit unbrauchbar.
            log.exception("Auftrag gescheitert: %s", fehler)
            self.fehlerstrom.protokollieren("Auftrag gescheitert")
            fehlermeldung = self.fehlerstrom.ergaenzt(str(fehler))
            verbindung_tot = True

        finally:
            self.laeuft = False

        if self._abbruch and not ergebnis_da and not verbindung_tot:
            # Der Rest der abgebrochenen Antwort liegt noch im Strom. Wird er
            # nicht abgeholt, liest der naechste Auftrag ihn als seine
            # Antwort und liefert damit alten Inhalt zum neuen Auftrag.
            verbindung_tot = not await self._strom_leeren()

        if not ergebnis_da and not self._abbruch and not fehlermeldung:
            verbindung_tot = True
            log.error("Auftrag endete ohne Ergebnismeldung - die Sitzung liefert nichts mehr")
            self.fehlerstrom.protokollieren("Sitzung ohne Ergebnis")
            fehlermeldung = self.fehlerstrom.ergaenzt(
                "Die Sitzung hat keine Antwort geliefert. Sie wird neu verbunden; "
                "bitte den Auftrag noch einmal geben."
            )

        geaendert = self.wache.auftrag_bilanz()
        self._protokoll_schreiben(geaendert)

        if fehlermeldung:
            self._melde(Zustand.FEHLER, "Fehler", fehlermeldung)
        elif self._abbruch:
            self._melde(Zustand.ABGEBROCHEN, "Auftrag abgebrochen")
        else:
            self._melde(Zustand.FERTIG, self._bilanz_satz(geaendert))

        if verbindung_tot:
            # Neue Sitzung statt weiterer stiller Leerlaeufe; der Nachtrag
            # entfaellt, eine frische Sitzung weiss nichts vom Auftrag.
            await self._neu_verbinden()
        elif not self._abbruch:
            await self._nachtrag_stellen()

        return {
            "antwort": "\n".join(antwort).strip(),
            "geaendert": geaendert,
            "fehler": fehlermeldung,
            "abgebrochen": self._abbruch,
            "schritte": len(self.schritte),
            "sicherungspunkt": punkt,
        }

    async def _strom_leeren(self) -> bool:
        """Holt nach einem Not-Aus den Rest der alten Antwort bis zur
        ResultMessage ab und verwirft ihn. Rueckgabe: ob der Strom danach
        sauber ist. Kommt binnen STROM_LEEREN_SEKUNDEN kein Ende, gilt die
        Verbindung als tot."""
        if self.klient is None:
            return False

        async def _abholen() -> bool:
            async for nachricht in self.klient.receive_response():
                if isinstance(nachricht, ResultMessage):
                    return True
            return False

        try:
            sauber = await asyncio.wait_for(_abholen(), STROM_LEEREN_SEKUNDEN)
        except asyncio.TimeoutError:
            log.warning("Rest der abgebrochenen Antwort kam nicht binnen %ss",
                        STROM_LEEREN_SEKUNDEN)
            return False
        except Exception as fehler:  # noqa: BLE001
            log.warning("Rest der abgebrochenen Antwort nicht abholbar: %s", fehler)
            return False
        if sauber:
            log.info("Rest der abgebrochenen Antwort verworfen")
        else:
            log.warning("Strom endete nach Not-Aus ohne Ergebnismeldung")
        return sauber

    async def _neu_verbinden(self) -> None:
        """Ersetzt eine unbrauchbar gewordene Sitzung durch eine frische.
        Scheitert das, bleibt klient None und der naechste Auftrag versucht
        es ueber verbinden() erneut."""
        log.warning("Sitzung wird neu verbunden")
        await self.trennen()
        try:
            await self.verbinden()
        except Exception as fehler:  # noqa: BLE001
            log.error("Neu verbinden gescheitert: %s", fehler)

    async def _nachtrag_stellen(self) -> None:
        """Fragt sich selbst nach dem Auftrag kurz ab und schreibt die Antwort
        ins Tagebuch. Zeilen mit [OFFEN] kommen zusaetzlich in die offenen
        Punkte. Laeuft still, ohne Sprachausgabe."""
        if self.wissen is None or self.klient is None:
            return
        try:
            await self.klient.query(NACHTRAG_ANWEISUNG)
            teile: list[str] = []
            async for nachricht in self.klient.receive_response():
                if isinstance(nachricht, AssistantMessage):
                    for block in nachricht.content:
                        if isinstance(block, TextBlock):
                            teile.append(block.text)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Nachtrag gescheitert: %s", fehler)
            return

        zusammenfassung = "".join(teile).strip()
        if not zusammenfassung:
            return

        self.wissen.tagebuch_anhaengen(zusammenfassung)
        for zeile in zusammenfassung.splitlines():
            zeile = zeile.strip()
            if not zeile or "[OFFEN]" not in zeile.upper():
                continue
            text = re.sub(r"\[OFFEN\]\s*", "", zeile, flags=re.IGNORECASE).strip()
            if text:
                self.wissen.offen_anhaengen(text)
        log.info("Tagebuch ergaenzt: %d Zeichen", len(zusammenfassung))

    def _taetigkeit(self, name: str) -> str:
        """Was gerade getan wird, in einem Wort: liest, schreibt, sucht,
        denkt, führt aus. Ohne Ziel - die betroffene Datei meldet 'pfad'."""
        return WERKZEUG_TAETIGKEIT.get(name, TAETIGKEIT_UNBEKANNT)

    def _melde_werkzeug(self, block: ToolUseBlock) -> None:
        zustand, verb = WERKZEUG_ZUSTAND.get(block.name, (Zustand.FUEHRT_AUS, block.name))
        eingabe = block.input or {}
        pfad = self._pfad_aus_eingabe(eingabe)
        if pfad:
            ansage = f"{verb}: {Path(pfad).name}"
        elif block.name == "Bash":
            ansage = f"{verb}: {str(eingabe.get('command',''))[:60]}"
        else:
            ansage = verb
        self._melde(
            zustand, ansage, str(block.input)[:400], pfad or "",
            self._taetigkeit(block.name),
        )

    def _bilanz_satz(self, geaendert: list[str]) -> str:
        anzahl = len(geaendert)
        if anzahl == 0:
            return "Fertig, keine Datei geaendert."
        if anzahl == 1:
            return f"Fertig, eine Datei geaendert: {Path(geaendert[0]).name}."
        return f"Fertig, {anzahl} Dateien geaendert."

    def rueckgaengig(self) -> Urteil:
        return self.wache.rueckgaengig()


# ---------------------------------------------------------------------------
# Selbsttest ohne Oberflaeche
# ---------------------------------------------------------------------------

async def _selbsttest() -> None:
    try:
        from .sicherheit import Projekt, projekte_finden
    except ImportError:
        from sicherheit import Projekt, projekte_finden

    projekte = projekte_finden()
    if not projekte:
        print("Keine Projekte gefunden.")
        return

    print("Projekte:")
    for nummer, p in enumerate(projekte, 1):
        print(f"  {nummer}. {p.ansage()}")

    wahl = input("\nNummer waehlen: ").strip()
    if not wahl.isdigit() or not 1 <= int(wahl) <= len(projekte):
        print("Ungueltige Wahl.")
        return
    projekt = projekte[int(wahl) - 1]

    async def frage(satz: str, kurz_satz: str) -> bool:
        return input(f"\n{satz} [j/n] ").strip().lower().startswith("j")

    sitzung = Sitzung(
        Wache.oeffnen(projekt),
        bei_ereignis=lambda e: print("  *", e.zeile()),
        bei_text=lambda t: print(t, end="", flush=True),
        bei_rueckfrage=frage,
    )

    try:
        while True:
            roh = input("\n\nAuftrag (leer = Ende): ").strip()
            if not roh:
                break

            satz = await sitzung.schaerfen(roh)
            if not input(f"\nVerstanden: {satz}\nAbschicken? [j/n] ").strip().lower().startswith("j"):
                continue

            bilanz = await sitzung.auftrag(roh)
            print("\n---")
            print("Schritte:", bilanz["schritte"])
            print("Geaendert:", ", ".join(bilanz["geaendert"]) or "nichts")
            if bilanz["fehler"]:
                print("Fehler:", bilanz["fehler"])
            if bilanz["geaendert"] and input("Zuruecknehmen? [j/n] ").strip().lower().startswith("j"):
                print(sitzung.rueckgaengig().ansage())
    finally:
        await sitzung.trennen()


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    try:
        asyncio.run(_selbsttest())
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
    except Exception as fehler:  # noqa: BLE001
        log.exception("Selbsttest abgebrochen: %s", fehler)
        print(f"Selbsttest abgebrochen: {fehler}")
