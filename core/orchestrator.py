"""
CWB - Code Workbench
Orchestrator, Etappe 1A: die Logik hinter dem Orchestrator-Reiter.

Der Orchestrator ist eine zweite Claude-Sitzung (core/orchestrator_ansicht.py),
die so arbeitet wie der Chat-Claude, der bisher ueber die Bruecke #RUN#/#CODE#-
Auftraege vergibt - nur ohne Netz und ohne Browser. Dieses Modul kennt weder
Fenster noch Faden. Es enthaelt:

- den Schalter (einstellungen.json -> "orchestrator", Standard aus),
- die drei Werkzeuge auftrag_senden, bericht_holen und status als reine
  Funktionen (testbar ohne Sitzung) und als eingebetteten MCP-Server
  (`werkzeuge_bauen`, nur fuer die Orchestrator-Sitzung),
- den Berichtsspeicher: fertige Berichte lokaler Auftraege liegen unter
  <Datenordner>/orchestrator/berichte/<Nummer>.txt, mit der Kennzeile
  "Auftrag N | Block B | Zeit T" vorweg wie bei der Bruecke.

Auftraege laufen ueber dieselbe Stelle wie Auftraege der Bruecke: den
Eingangsordner (core/eingangsordner.py, `ablegen`). Dort gelten dieselben
Pruefungen und Sicherheitsregeln; #ADMIN# bleibt gesperrt, weil die Quelle
nicht "lokal" ist. Auftragsnummern lokaler Auftraege beginnen bei
LOKAL_AB und liegen damit sicher ueber den Nummern des Bruecken-Servers.
"""

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path

try:
    from . import eingangsordner
    from .pfade import DATENORDNER, einstellungen_lesen, log_einrichten
except ImportError:
    import eingangsordner
    from pfade import DATENORDNER, einstellungen_lesen, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.orchestrator")

# Schluessel in einstellungen.json
SCHALTER = "orchestrator"
MODELL_SCHLUESSEL = "orchestrator_modell"
MODELL_STANDARD = "sonnet"

# Quelle im Eingangsordner und Name des eingebetteten Werkzeug-Servers. Die
# Werkzeuge heissen in der Sitzung "mcp__cwb-orchestrator__<name>".
QUELLE = "orchestrator"
SERVER_NAME = "cwb-orchestrator"

# Lokale Auftragsnummern beginnen hier (Bruecken-Nummern sind dreistellig).
LOKAL_AB = 1_000_000

ARTEN = ("RUN", "CODE")

ORCH_ORDNER = DATENORDNER / "orchestrator"
ANWEISUNG_DATEI = Path(__file__).resolve().parent.parent / "wissen" / "orchestrator_anweisung.md"

STATUS_BERICHTE_ANZAHL = 5

_nummer_sperre = threading.Lock()


def aktiv() -> bool:
    """Wahr, wenn der Orchestrator-Reiter eingeschaltet ist (Standard: aus)."""
    return bool(einstellungen_lesen().get(SCHALTER, False))


def modell() -> str:
    """Modell der Orchestrator-Sitzung (Standard Sonnet)."""
    wert = einstellungen_lesen().get(MODELL_SCHLUESSEL)
    return wert.strip() if isinstance(wert, str) and wert.strip() else MODELL_STANDARD


def anweisung_lesen() -> str:
    """Text von wissen/orchestrator_anweisung.md. Fehlt die Datei oder ist sie
    unlesbar, kommt ein leerer Text zurueck - die Sitzung laeuft dann nur mit
    dem Standard-Systemtext weiter, statt gar nicht zu starten."""
    try:
        return ANWEISUNG_DATEI.read_text(encoding="utf-8").strip()
    except OSError as fehler:
        log.error("Orchestrator-Anweisung nicht lesbar (%s): %s", ANWEISUNG_DATEI, fehler)
        return ""


def projektliste_text(projekte=None) -> str:
    """Abschnitt "Bekannte Projekte" fuer die Anweisung, immer frisch aus der
    Projektverwaltung (einstellungen.json, Zusatzprojekte mit vorhandenem
    Pfad). `projekte` sind Objekte mit `name` und `pfad` (Attrappe im Test).
    Ist die Liste leer oder nicht lesbar, steht das ausdruecklich da."""
    if projekte is None:
        try:
            try:
                from .sicherheit import projekte_finden
            except ImportError:
                from sicherheit import projekte_finden
            projekte = projekte_finden()
        except Exception as fehler:  # noqa: BLE001 - Sitzung soll trotzdem starten
            log.error("Projektliste nicht lesbar: %s", fehler)
            projekte = []
    zeilen = [f"- {p.name}: {p.pfad}" for p in projekte]
    if not zeilen:
        return "## Bekannte Projekte\nKeine Projekte bekannt. Sag das dem Nutzer in einem Satz."
    return "## Bekannte Projekte\n" + "\n".join(zeilen)


# -- Gedaechtnis: Startblock und Uebergaben --------------------------------
# Der Orchestrator ist eine schlanke Sitzung ohne Kontextblock. Beim Start
# bekommt er hier einen kurzen Stand aus dem, was es schon gibt (wissen/offen.md,
# wissen/tagebuch.md, Memory Hub) plus den Hinweis auf die neueste Uebergabe.

CWB_ORDNER = Path(__file__).resolve().parent.parent
UEBERGABEN_ORDNER_NAME = Path("wissen") / "uebergaben"
STARTBLOCK_MAX_ZEICHEN = 6000
STARTBLOCK_ZEILE_MAX = 220
STARTBLOCK_OFFEN_MAX = 12
STARTBLOCK_TAGEBUCH_MAX = 8
STARTBLOCK_HUB_MAX = 14
STARTBLOCK_KOPF = "## Gedächtnis (keine Aufgabe, nichts davon automatisch ausführen)"
HUB_VORRANG = ("regel", "entscheidung", "praeferenz", "präferenz")
_UEBERGABE_NAME = re.compile(r"^uebergabe_(\d{4}-\d\d-\d\d)_(\d{4})\.md$")


def _startzeile(text: str) -> str | None:
    """Eine Zeile fuers Gedaechtnis: einzeilig, gekuerzt; None, wenn leer oder
    ein Schluesselmuster darin steht (dann faellt die ganze Zeile weg)."""
    text = " ".join(str(text or "").split())
    if not text or _GEHEIM_MUSTER.search(text):
        return None
    if len(text) > STARTBLOCK_ZEILE_MAX:
        text = text[:STARTBLOCK_ZEILE_MAX - 1].rstrip() + "…"
    return text


def neueste_uebergabe(ordner: Path | None = None) -> Path | None:
    """Neueste Datei wissen/uebergaben/uebergabe_JJJJ-MM-TT_HHMM.md oder None
    (auch wenn der Ordner fehlt)."""
    ordner = Path(ordner) if ordner else CWB_ORDNER / UEBERGABEN_ORDNER_NAME
    try:
        namen = sorted(p for p in ordner.iterdir() if p.is_file() and _UEBERGABE_NAME.match(p.name))
    except OSError:
        return None
    return namen[-1] if namen else None


def _hub_zeilen(datenbank, projekt: str, anzahl: int) -> list[str]:
    """Hub-Eintraege fuer global und `projekt`: Regeln, Entscheidungen und
    Praeferenzen zuerst, dann Angeheftetes, dann Neueres. Nur lesend."""
    import sqlite3
    if not datenbank or not Path(datenbank).is_file():
        return []
    try:
        with sqlite3.connect(f"file:{datenbank}?mode=ro", uri=True) as verbindung:
            zeilen = verbindung.execute(
                "SELECT category, content FROM memories "
                "WHERE lower(project) IN (?, 'global') "
                "ORDER BY pinned DESC, updated DESC LIMIT ?",
                (projekt.lower(), anzahl * 6),
            ).fetchall()
    except sqlite3.Error as fehler:
        log.error("Startblock: Hub nicht lesbar: %s", fehler)
        return []
    vorn, hinten = [], []
    for kategorie, inhalt in zeilen:
        zeile = _startzeile(inhalt)
        if zeile is None:
            continue
        if str(kategorie).strip().lower() in HUB_VORRANG:
            vorn.append(f"- {kategorie}: {zeile}")
        else:
            hinten.append(f"- {zeile}")
    return (vorn + hinten)[:anzahl]


def startblock_bauen(projekt_pfad=None, projekt_name: str = "CWB", datenbank=None,
                     uebergaben_ordner=None) -> str:
    """Kurzer Gedaechtnisblock fuer den Systemtext der Orchestrator-Sitzung,
    hoechstens STARTBLOCK_MAX_ZEICHEN. Reihenfolge: Uebergabe-Hinweis, offene
    Punkte, Hub (Regeln/Entscheidungen zuerst), Tagebuch. Leere oder fehlende
    Quellen werden uebersprungen; ohne jeden Inhalt kommt "" zurueck. Wirft nie."""
    try:
        try:
            from .wissen import Wissen
            from .pfade import HUB_DATENBANK
        except ImportError:
            from wissen import Wissen
            from pfade import HUB_DATENBANK
        projekt_pfad = Path(projekt_pfad) if projekt_pfad else CWB_ORDNER
        wissen = Wissen(projekt_pfad, projekt_name)
        abschnitte: list[list[str]] = []

        uebergabe = neueste_uebergabe(uebergaben_ordner or projekt_pfad / UEBERGABEN_ORDNER_NAME)
        if uebergabe:
            m = _UEBERGABE_NAME.match(uebergabe.name)
            abschnitte.append([
                "### Letzte Übergabe",
                f"- {uebergabe.name} vom {m.group(1)}, {m.group(2)[:2]}:{m.group(2)[2:]} Uhr "
                f"(wissen/uebergaben/). Inhalt nur auf Anforderung per RUN lesen.",
            ])

        offen = [z for z in (_startzeile(e.text) for e in wissen.offene_punkte()) if z]
        if offen:
            abschnitte.append(["### Offene Punkte (jüngste zuerst)"]
                              + [f"- {z}" for z in reversed(offen[-STARTBLOCK_OFFEN_MAX:])])

        hub = _hub_zeilen(HUB_DATENBANK if datenbank is None else datenbank,
                          projekt_name, STARTBLOCK_HUB_MAX)
        if hub:
            abschnitte.append(["### Memory Hub (global und " + projekt_name + ")"] + hub)

        tage = [z for z in (_startzeile(e.zeile()) for e in wissen.tagebuch(STARTBLOCK_TAGEBUCH_MAX))
                if z]
        if tage:
            abschnitte.append(["### Zuletzt gearbeitet"] + [f"- {z}" for z in reversed(tage)])

        if not abschnitte:
            return ""
        ausgabe = [STARTBLOCK_KOPF]
        laenge = len(STARTBLOCK_KOPF)
        for abschnitt in abschnitte:
            for zeile in abschnitt:
                if laenge + 1 + len(zeile) > STARTBLOCK_MAX_ZEICHEN - 40:
                    ausgabe.append("(gekürzt, mehr per memory_search)")
                    return "\n".join(ausgabe)
                ausgabe.append(zeile)
                laenge += 1 + len(zeile)
        return "\n".join(ausgabe)
    except Exception as fehler:  # noqa: BLE001 - Sitzung soll trotzdem starten
        log.error("Startblock nicht gebaut: %s", fehler)
        return ""


def ist_lokale_nummer(nummer) -> bool:
    try:
        return int(nummer) >= LOKAL_AB
    except (TypeError, ValueError):
        return False


def berichte_ordner() -> Path:
    return ORCH_ORDNER / "berichte"


# -- Nummern ----------------------------------------------------------------

def naechste_nummer() -> int:
    """Vergibt die naechste lokale Auftragsnummer (Zaehler in nummer.txt)."""
    with _nummer_sperre:
        datei = ORCH_ORDNER / "nummer.txt"
        letzte = LOKAL_AB
        try:
            letzte = max(LOKAL_AB, int(datei.read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            pass
        neu = letzte + 1
        try:
            ORCH_ORDNER.mkdir(parents=True, exist_ok=True)
            datei.write_text(str(neu), encoding="utf-8")
        except OSError as fehler:
            log.error("Nummernzaehler nicht schreibbar: %s", fehler)
        return neu


# -- Berichtsspeicher -------------------------------------------------------

def _kennzeile_davor(nummer: int, block, text: str) -> str:
    try:
        from .bruecke import mit_kennzeile
    except ImportError:
        try:
            from bruecke import mit_kennzeile
        except ImportError:
            mit_kennzeile = None
    if mit_kennzeile is not None:
        return mit_kennzeile(nummer, block, text)
    zeit = datetime.now().astimezone().isoformat(timespec="seconds")
    return f"Auftrag {nummer} | Block {block if block else '-'} | Zeit {zeit}\n{text}"


# -- Schleifenschutz (Etappe 1B) ----------------------------------------------

SCHLEIFE_SCHLUESSEL = "orchestrator_schleife_max"
SCHLEIFE_STANDARD = 12


def schleife_max() -> int:
    """Harte Grenze: so viele Auftraege darf der Orchestrator hintereinander
    vergeben, ohne dass Robert etwas geschrieben hat (einstellungen.json,
    Standard 12). Ungueltige Werte fallen auf den Standard zurueck."""
    wert = einstellungen_lesen().get(SCHLEIFE_SCHLUESSEL, SCHLEIFE_STANDARD)
    try:
        wert = int(wert)
    except (TypeError, ValueError):
        return SCHLEIFE_STANDARD
    return wert if wert >= 1 else SCHLEIFE_STANDARD


class Schleifenschutz:
    """Zaehlt die vom Orchestrator vergebenen Auftraege seit Roberts letztem
    Text (oder seiner letzten Ja-Antwort auf die Schleifenfrage). Der Zaehler
    lebt nur im Arbeitsspeicher: nach einem Neustart ist Robert ohnehin da."""

    def __init__(self):
        self._sperre = threading.Lock()
        self.zaehler = 0

    def erreicht(self) -> bool:
        with self._sperre:
            return self.zaehler >= schleife_max()

    def erhoehen(self) -> int:
        with self._sperre:
            self.zaehler += 1
            return self.zaehler

    def zuruecksetzen(self) -> None:
        with self._sperre:
            self.zaehler = 0


SCHLEIFE = Schleifenschutz()


async def schleife_pruefen(rueckfrage=None) -> str | None:
    """None, wenn ein weiterer Auftrag vergeben werden darf. Ist die Grenze
    erreicht, fragt sie Robert (ja/nein, `rueckfrage(satz, kurz_satz)` wie
    Sitzung._frage): bei Ja beginnt der Zaehler neu (None), bei Nein - oder
    ohne Rueckfrage-Weg - kommt der Text zurueck, mit dem das Werkzeug den
    Auftrag verweigert."""
    if not SCHLEIFE.erreicht():
        return None
    grenze = schleife_max()
    log.warning("Schleifenschutz: %d Auftraege ohne Eingabe von Robert", SCHLEIFE.zaehler)
    if rueckfrage is None:
        return (f"Schleifenschutz: {grenze} Auftraege ohne Eingabe von Robert. "
                "Halte an und warte auf Robert.")
    satz = (f"Der Orchestrator hat {grenze} Aufträge hintereinander vergeben, ohne dass "
            "du etwas geschrieben hast. Weitermachen?")
    if await rueckfrage(satz, "Orchestrator: Weitermachen?"):
        SCHLEIFE.zuruecksetzen()
        return None
    return ("Robert hat den Schleifenschutz nicht freigegeben. "
            "Halte an und warte auf Robert.")


# -- Kontingent in Meldungen (Etappe 1B) ---------------------------------------

def kontingent_waehlen(*zustaende) -> dict | None:
    """Nimmt aus mehreren Kontingent-Zustaenden (Sitzung.kontingent_zustand)
    den ersten, der etwas Echtes weiss (Prozentzahl oder erschoepft). Weiss
    keiner etwas, kommt der erste vorhandene zurueck, sonst None."""
    vorhanden = [z for z in zustaende if isinstance(z, dict) and z]
    for z in vorhanden:
        if (z.get("woche_prozent") is not None or z.get("sitzung_anzeige")
                or z.get("stufe") == "erschoepft"):
            return z
    return vorhanden[0] if vorhanden else None


def kontingent_zeile(zustand: dict | None) -> str:
    """Eine Zeile "Kontingent: Woche X % | Sitzung Y %" fuer Meldungen und
    Statusanzeige. Das SDK meldet Prozentwerte erst ab einer eigenen
    Warnschwelle; davor steht dort die grobe Stufe, nie eine erfundene Zahl."""
    if not zustand:
        return "Kontingent: noch nicht gemeldet"
    woche = zustand.get("woche_anzeige") or "Woche: unbekannt"
    sitzung = zustand.get("sitzung_anzeige") or "Sitzung noch nicht gemeldet"
    return f"Kontingent: {woche} | {sitzung}"


def kontingent_anzeige(zustand: dict | None) -> tuple[str, str | None]:
    """Zeile und Stufe fuer die Orchestrator-Ansicht. Echte SDK-Prozentwerte
    (vorhandene Auswertung `zustand`) ueberschreiben zuerst den gemerkten
    Stand (core/kontingent.py); danach kommt die Zeile aus dem Stand. Gibt es
    keinen Stand, bleibt es bei `kontingent_zeile` und die Stufe ist None."""
    try:
        try:
            from . import kontingent
        except ImportError:
            import kontingent
        kontingent.sdk_uebernehmen(zustand)
        auswertung = kontingent.aktuelle_auswertung()
        if auswertung:
            return kontingent.zeile(auswertung), auswertung["stufe"]
    except Exception as fehler:  # noqa: BLE001 - Anzeige darf nie scheitern
        log.error("Kontingent-Stand nicht auswertbar: %s", fehler)
    return kontingent_zeile(zustand), None


# -- Meldungen an den Orchestrator (Etappe 1B) ---------------------------------

MELDUNG_KOPF = "[CWB-MELDUNG]"
MELDUNG_TRENNER = "\n\n---\n\n"
STATUS_WOERTER = ("fertig", "Fehler", "abgebrochen")
ZUGESTELLT_MERKEN = 500


MELDUNG_ZEICHEN_MAX = 2000
MELDUNG_RUN_ZEILEN_MAX = 40
GEKUERZT_ZEILE = "[gekuerzt, voller Bericht per bericht_holen]"
KEIN_BERICHT_ZEILE = "Bericht noch nicht verfuegbar"

# Feste Regel im Systemtext der Orchestrator-Sitzung (immer angehaengt, auch
# wenn wissen/orchestrator_anweisung.md fehlt).
REGEL_AUSGABE = (
    "Regel: Aussagen ueber Inhalt oder Ergebnis eines Auftrags nur, wenn die Ausgabe "
    "in der Meldung steht oder per Werkzeug (bericht_holen) gelesen wurde. "
    "Sonst sage: \"Ausgabe nicht gelesen.\""
)


def bericht_kuerzen(bericht: str, art: str | None = None) -> str:
    """Kuerzt den Bericht fuer die Meldung: bei RUN auf 40 Zeilen oder 2000
    Zeichen, sonst (CODE) auf 2000 Zeichen. Die Kennzeile "Auftrag N | ..." vorn
    zaehlt nicht mit. Wird gekuerzt, folgt eine eigene Hinweiszeile."""
    zeilen = bericht.rstrip().splitlines()
    kennzeile = ""
    if zeilen and zeilen[0].startswith("Auftrag ") and " | Zeit " in zeilen[0]:
        kennzeile = zeilen.pop(0) + "\n"
    text = "\n".join(zeilen)
    gekuerzt = False
    if str(art or "").upper() == "RUN" and len(zeilen) > MELDUNG_RUN_ZEILEN_MAX:
        text = "\n".join(zeilen[:MELDUNG_RUN_ZEILEN_MAX])
        gekuerzt = True
    if len(text) > MELDUNG_ZEICHEN_MAX:
        text = text[:MELDUNG_ZEICHEN_MAX]
        gekuerzt = True
    text = kennzeile + text
    return f"{text.rstrip()}\n{GEKUERZT_ZEILE}" if gekuerzt else text


def meldung_bauen(nummer, block, status: str, bericht: str | None, kontingent: str = "",
                  art: str | None = None) -> str:
    """Text einer Meldung: Kopfzeile, Ausgabe bzw. Bericht (gekuerzt, siehe
    `bericht_kuerzen`; fehlt er, steht "Bericht noch nicht verfuegbar"), dann
    die Kontingent-Zeile, falls gegeben."""
    wort = status if status in STATUS_WOERTER else "fertig"
    inhalt = bericht_kuerzen(bericht, art) if bericht and bericht.strip() else KEIN_BERICHT_ZEILE
    teile = [f"{MELDUNG_KOPF} Auftrag {nummer} | Block {block if block else '-'} | {wort}",
             inhalt]
    if kontingent:
        teile.append(kontingent)
    return "\n".join(teile)


def eingang_datei() -> Path:
    return ORCH_ORDNER / "orchestrator_eingang.json"


class Eingangsschlange:
    """Meldungen fuer die Orchestrator-Sitzung, auf Platte gesichert.

    - `vormerken` reiht eine Meldung ein; die Auftragsnummer ist der
      Schluessel, eine Nummer kommt nie zweimal hinein (auch nicht, wenn sie
      schon zugestellt wurde).
    - `entnehmen` holt ALLE wartenden Meldungen als eine Nachricht und merkt
      sie als "unterwegs".
    - `quittieren` bucht die unterwegs befindlichen als zugestellt,
      `zurueckstellen` legt sie vorn in die Schlange zurueck (Abbruch,
      Fehler, Absturz, Neustart). Nichts geht verloren; im Zweifel kommt eine
      Meldung eher doppelt als gar nicht."""

    def __init__(self, datei: Path | None = None):
        self._datei = datei
        self._sperre = threading.RLock()
        self.wartend: list[dict] = []
        self.unterwegs: list[dict] = []
        self.zugestellt: list[str] = []
        self._laden()

    @property
    def datei(self) -> Path:
        return self._datei or eingang_datei()

    def _laden(self) -> None:
        try:
            roh = json.loads(self.datei.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as fehler:
            log.error("Orchestrator-Eingang nicht lesbar (%s): %s", self.datei, fehler)
            return
        if not isinstance(roh, dict):
            return

        def eintraege(schluessel):
            return [e for e in roh.get(schluessel, [])
                    if isinstance(e, dict) and e.get("schluessel") and e.get("text")]

        # Was beim letzten Ende noch unterwegs war, ist nicht belegt zugestellt:
        # zurueck an die Spitze der Schlange (nur im Speicher, bis zur naechsten
        # Aenderung).
        self.wartend = eintraege("unterwegs") + eintraege("wartend")
        self.zugestellt = [str(s) for s in roh.get("zugestellt", [])][-ZUGESTELLT_MERKEN:]

    def _sichern(self) -> None:
        daten = {"wartend": self.wartend, "unterwegs": self.unterwegs,
                 "zugestellt": self.zugestellt[-ZUGESTELLT_MERKEN:]}
        teil = self.datei.with_suffix(".teil")
        try:
            self.datei.parent.mkdir(parents=True, exist_ok=True)
            teil.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
            teil.replace(self.datei)
        except OSError as fehler:
            log.error("Orchestrator-Eingang nicht schreibbar: %s", fehler)

    def anzahl(self) -> int:
        with self._sperre:
            return len(self.wartend)

    def vormerken(self, schluessel, text: str) -> bool:
        """False, wenn die Nummer schon vorgemerkt, unterwegs oder zugestellt ist."""
        schluessel = str(schluessel)
        with self._sperre:
            bekannt = {e["schluessel"] for e in self.wartend + self.unterwegs}
            if schluessel in bekannt or schluessel in self.zugestellt:
                log.info("Orchestrator-Meldung %s schon bekannt, nicht doppelt", schluessel)
                return False
            self.wartend.append({"schluessel": schluessel, "text": text,
                                 "zeit": datetime.now().isoformat(timespec="seconds")})
            self._sichern()
            return True

    def entnehmen(self) -> str:
        """Alle wartenden Meldungen als eine Nachricht ('' wenn keine)."""
        with self._sperre:
            if not self.wartend:
                return ""
            self.unterwegs = self.unterwegs + self.wartend
            self.wartend = []
            self._sichern()
            return MELDUNG_TRENNER.join(e["text"] for e in self.unterwegs)

    def quittieren(self) -> None:
        with self._sperre:
            if not self.unterwegs:
                return
            self.zugestellt += [e["schluessel"] for e in self.unterwegs]
            self.unterwegs = []
            self._sichern()

    def zurueckstellen(self) -> None:
        with self._sperre:
            if not self.unterwegs:
                return
            self.wartend = self.unterwegs + self.wartend
            self.unterwegs = []
            self._sichern()


def bericht_ablegen(nummer, text: str, block=None) -> Path | None:
    """Legt den fertigen Bericht eines lokalen Auftrags ab (aufgerufen aus
    core/fenster.py, wenn der Auftrag zu Ende ist). Rueckgabe: Pfad oder None."""
    try:
        nummer = int(nummer)
    except (TypeError, ValueError):
        log.error("Bericht ohne gueltige Nummer verworfen: %r", nummer)
        return None
    ziel = berichte_ordner() / f"{nummer}.txt"
    teil = ziel.with_suffix(".teil")
    try:
        berichte_ordner().mkdir(parents=True, exist_ok=True)
        teil.write_text(_kennzeile_davor(nummer, block, text or "(leer)"), encoding="utf-8")
        teil.replace(ziel)
    except OSError as fehler:
        log.error("Bericht %s nicht schreibbar: %s", nummer, fehler)
        return None
    log.info("Orchestrator-Bericht %s abgelegt (%d Zeichen)", nummer, len(text or ""))
    return ziel


VERLAUF_MAX_BYTES = 1024 * 1024
VERLAUF_BEHALTEN = 200      # so viele Eintraege bleiben nach dem Kuerzen


def verlauf_datei() -> Path:
    return ORCH_ORDNER / "verlauf.txt"


def _verlauf_kuerzen(datei: Path) -> None:
    """Ueber VERLAUF_MAX_BYTES: nur die letzten VERLAUF_BEHALTEN Eintraege
    bleiben (ein Eintrag beginnt mit "[Zeitstempel] Art:", mehrzeilige
    Eintraege bleiben ganz). Nichts wird archiviert, die Datei waechst nicht
    still weiter. Der Verlauf geht nie ans Modell zurueck."""
    zeilen = datei.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    anfaenge = [i for i, z in enumerate(zeilen) if _VERLAUF_KOPF.match(z.rstrip("\r\n"))]
    if len(anfaenge) > VERLAUF_BEHALTEN:
        rest = zeilen[anfaenge[-VERLAUF_BEHALTEN]:]
    else:
        rest = zeilen[-VERLAUF_BEHALTEN:]
    teil = datei.with_suffix(".teil")
    teil.write_text("".join(rest), encoding="utf-8")
    teil.replace(datei)
    log.info("Orchestrator-Verlauf gekuerzt: %d von %d Zeilen behalten", len(rest), len(zeilen))


def verlauf_anhaengen(art: str, text: str) -> bool:
    """Haengt einen Verlaufseintrag mit Zeitstempel an verlauf.txt an. Wirft
    nie; bei Fehler nur ein Logeintrag und False."""
    try:
        datei = verlauf_datei()
        datei.parent.mkdir(parents=True, exist_ok=True)
        zeit = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(datei, "a", encoding="utf-8") as ziel:
            ziel.write(f"[{zeit}] {art}: {text}\n")
        if datei.stat().st_size > VERLAUF_MAX_BYTES:
            _verlauf_kuerzen(datei)
        return True
    except Exception as fehler:  # noqa: BLE001
        log.error("Orchestrator-Verlauf nicht geschrieben: %s", fehler)
        return False


# -- Befehlsanzeige ---------------------------------------------------------
# Jeder Werkzeugaufruf des Orchestrators wird als kurze, stille Zeile im
# Verlauf gezeigt ("→ ..." fuer den Aufruf, "← ..." fuer das Ergebnis). Nichts
# davon wird gesprochen, und die Zeilen zaehlen nicht zur Antwort.

BEFEHLE_SCHLUESSEL = "orchestrator_befehle_anzeigen"
BEFEHL_MAX_ZEICHEN = 120
FEHLER_MAX_ZEICHEN = 80
VERBORGEN = "[verborgen]"
BEFEHL_ART = "befehl"
VERLAUF_LADEN_MAX = 60

# Erkennbare Schluessel, Tokens und Kennwoerter. Trifft eines zu, wird die
# ganze Angabe durch VERBORGEN ersetzt, nicht nur der Treffer.
_GEHEIM_MUSTER = re.compile(
    r"\bsk-[A-Za-z0-9_\-]{6,}"
    r"|\bAIza[0-9A-Za-z_\-]{6,}"
    r"|\bBearer\s+\S+"
    r"|(?i:\b[\w\-]*(?:key|token|password|passwort|secret)\s*=)",
)

# Dateien der Sperrliste: ihr Inhalt erscheint nie, auch nicht in Fehlergruenden.
_GEHEIM_DATEIEN = re.compile(r"(^|[\\/])(\.env[\w.\-]*|[\w.\-]*\.(pem|key|p12|pfx)|id_rsa[\w.\-]*"
                             r"|[\w.\-]*(secret|credential)[\w.\-]*)$", re.IGNORECASE)

_VERLAUF_KOPF = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] (\w+): ?(.*)$")


def befehle_anzeigen() -> bool:
    """Schalter F12 -> Verhalten, Vorgabe an."""
    return bool(einstellungen_lesen().get(BEFEHLE_SCHLUESSEL, True))


def verbergen(text: str) -> str:
    """Ersetzt eine Angabe mit erkennbarem Schluessel ganz durch VERBORGEN."""
    text = str(text or "")
    if _GEHEIM_MUSTER.search(text) or _GEHEIM_DATEIEN.search(text.strip()):
        return VERBORGEN
    return text


def kuerzen(text: str, grenze: int = BEFEHL_MAX_ZEICHEN) -> str:
    """Einzeilig, hoechstens `grenze` Zeichen; gekuerzt endet es auf Auslassungspunkte."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= grenze else text[:grenze].rstrip() + "…"


def _angabe(text) -> str:
    return kuerzen(verbergen(text))


def werkzeug_kurzname(name: str) -> str:
    """'mcp__cwb-orchestrator__status' -> 'status'."""
    return str(name or "").rsplit("__", 1)[-1]


def befehl_zeile(name: str, eingabe: dict | None) -> str:
    """Eine Zeile fuer den Aufruf: Werkzeug und Ziel, Befehlstext gekuerzt."""
    eingabe = eingabe or {}
    kurz = werkzeug_kurzname(name)
    if kurz == "auftrag_senden":
        art = str(eingabe.get("art") or "").upper() or "AUFTRAG"
        projekt = _angabe(eingabe.get("projekt") or "?")
        return f"→ {art} an {projekt}: {_angabe(eingabe.get('text'))}"
    if kurz == "bericht_holen":
        nummer = eingabe.get("auftrag_nummer")
        return f"→ holt Bericht Auftrag {nummer}" if nummer else "→ holt Bericht"
    if kurz == "status":
        return "→ fragt den Status ab"
    if kurz in ("Read", "NotebookRead"):
        return f"→ liest {_angabe(Path(str(eingabe.get('file_path') or '')).name)}"
    if kurz in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return f"→ schreibt {_angabe(Path(str(eingabe.get('file_path') or '')).name)}"
    if kurz in ("Grep", "Glob"):
        return f"→ sucht {_angabe(eingabe.get('pattern'))}"
    if kurz == "Bash":
        return f"→ führt aus: {_angabe(eingabe.get('command'))}"
    ziel = eingabe.get("url") or eingabe.get("query") or eingabe.get("file_path") or ""
    return f"→ {kurz} {_angabe(ziel)}".rstrip()


def ergebnis_zeile(name: str, eingabe: dict | None, status: str, text: str = "") -> str:
    """Eine Zeile fuer das Ergebnis. status: 'fertig', 'fehler' oder 'abgelehnt'."""
    if status == "abgelehnt":
        return "← abgelehnt"
    if status == "fehler":
        grund = kuerzen(verbergen(text), FEHLER_MAX_ZEICHEN) or "unbekannt"
        return f"← Fehler: {grund}"
    if werkzeug_kurzname(name) == "bericht_holen" and (eingabe or {}).get("auftrag_nummer"):
        return f"← Bericht Auftrag {eingabe['auftrag_nummer']} gelesen"
    return "← fertig"


def verlauf_laden(maximal: int = VERLAUF_LADEN_MAX) -> list[tuple[str, str]]:
    """Liest die letzten Eintraege aus verlauf.txt als (art, text). Mehrzeilige
    Eintraege werden zusammengesetzt; Zeilen aelterer Verlaeufe ohne
    Befehlszeilen laden unveraendert. Wirft nie."""
    try:
        zeilen = verlauf_datei().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    eintraege: list[list[str]] = []
    for zeile in zeilen:
        treffer = _VERLAUF_KOPF.match(zeile)
        if treffer:
            eintraege.append([treffer.group(1), treffer.group(2)])
        elif eintraege:
            eintraege[-1][1] += "\n" + zeile
    ergebnis = []
    for art, text in eintraege[-maximal:]:
        if art == BEFEHL_ART:
            text = text if text.startswith(("→", "←")) and not _GEHEIM_MUSTER.search(text) \
                else f"{text.split(':', 1)[0]}: {VERBORGEN}"
        ergebnis.append((art, text))
    return ergebnis


def _auftragsdatei(nummer: int) -> tuple[str, str] | None:
    """(Ordnername, Dateiname) der Auftragsdatei zu dieser Nummer, falls sie
    noch in einem der Eingangs-Unterordner liegt; sonst None."""
    try:
        name = json.loads(eingangsordner._nummer_datei(nummer).read_text(encoding="utf-8")) \
            .get("datei", "")
    except (OSError, ValueError, AttributeError):
        return None
    if not name:
        return None
    orte = (
        ("eingang", eingangsordner.EINGANG_ORDNER),
        ("in_bearbeitung", eingangsordner.in_bearbeitung_ordner()),
        ("laeuft", eingangsordner.laeuft_ordner()),
        ("abgelehnt", eingangsordner.abgelehnt_ordner()),
        ("verworfen", eingangsordner.verworfen_ordner()),
        ("unterbrochen", eingangsordner.unterbrochen_ordner()),
        ("erledigt", eingangsordner.erledigt_ordner()),
    )
    for ort, ordner in orte:
        if (ordner / name).exists():
            return ort, name
    return None


def _ablehnungsgrund(name: str) -> str:
    try:
        return (eingangsordner.abgelehnt_ordner() / f"{name}.txt").read_text(
            encoding="utf-8").strip()
    except OSError:
        return ""


# -- Die drei Werkzeuge als reine Funktionen --------------------------------

def projekt_bekannt(projekt: str, namen: list[str] | None = None) -> bool:
    if namen is None:
        try:
            from .sicherheit import projekte_finden
        except ImportError:
            from sicherheit import projekte_finden
        namen = [p.name for p in projekte_finden()]
    return any(eingangsordner.projekt_gleichwertig(projekt, name) for name in namen)


def auftrag_senden(art: str, projekt: str, text: str,
                   projekte: list[str] | None = None) -> dict:
    """Legt einen Auftrag in den Eingangsordner. Rueckgabe: {"ok": True,
    "nummer": N, "meldung": ...} oder {"ok": False, "meldung": Grund}."""
    art_gross = str(art or "").strip().upper()
    if art_gross not in ARTEN:
        return {"ok": False, "meldung": f"Art {art!r} gibt es nicht. Erlaubt: RUN oder CODE."}
    projekt = str(projekt or "").strip()
    if not projekt:
        return {"ok": False, "meldung": "Projekt fehlt."}
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "meldung": "Auftragstext ist leer."}
    if not projekt_bekannt(projekt, projekte):
        return {"ok": False, "meldung": f"Projekt {projekt!r} ist in CWB nicht bekannt."}
    roh = f"#{art_gross}#\n{text}"
    for _versuch in range(5):
        nummer = naechste_nummer()
        try:
            datei = eingangsordner.ablegen(QUELLE, roh, projekt, auftrag_nummer=nummer)
        except OSError as fehler:
            log.error("Auftrag nicht ablegbar: %s", fehler)
            return {"ok": False, "meldung": f"Auftrag nicht ablegbar: {fehler}"}
        if datei is not None:
            log.info("Orchestrator-Auftrag %s (%s, Projekt %s) abgelegt", nummer, art_gross,
                     projekt)
            SCHLEIFE.erhoehen()
            return {"ok": True, "nummer": nummer,
                    "meldung": f"Auftrag {nummer} ({art_gross}, {projekt}) liegt im Eingang."}
    return {"ok": False, "meldung": "Keine freie Auftragsnummer gefunden."}


def _kontingent_gehalten(nummer) -> str | None:
    """'WARTET AUF KONTINGENT bis 14:00', wenn die Kontingentsperre den Auftrag
    haelt (core/kontingentsperre.py), sonst None."""
    try:
        try:
            from . import kontingentsperre
        except ImportError:
            import kontingentsperre
        return kontingentsperre.gehalten_text(nummer)
    except Exception as fehler:  # noqa: BLE001
        log.exception("Kontingent-Vermerk nicht gelesen: %s", fehler)
        return None


def bericht_holen(nummer) -> str:
    """Bericht zu einem lokalen Auftrag, mit Kennzeile vorweg. Ist der Auftrag
    noch nicht fertig, sagt die Antwort, wo er steht."""
    try:
        nummer = int(nummer)
    except (TypeError, ValueError):
        return f"Auftragsnummer {nummer!r} ist keine Zahl."
    try:
        return (berichte_ordner() / f"{nummer}.txt").read_text(encoding="utf-8")
    except OSError:
        pass
    ort = _auftragsdatei(nummer)
    if ort is None:
        return f"Auftrag {nummer}: unbekannt."
    where, name = ort
    if where == "eingang":
        return f"Auftrag {nummer}: noch nicht fertig, wartet im Eingang."
    if where == "in_bearbeitung":
        return f"Auftrag {nummer}: noch nicht fertig, wird gerade angenommen."
    if where == "laeuft":
        gehalten = _kontingent_gehalten(nummer)
        if gehalten:
            return (f"Auftrag {nummer}: {gehalten}. Er startet nach dem Reset von selbst; "
                    "das ist kein Absturz.")
        return f"Auftrag {nummer}: noch nicht fertig, laeuft oder wartet in der Warteschlange."
    if where == "abgelehnt":
        grund = _ablehnungsgrund(name)
        return f"Auftrag {nummer}: abgelehnt" + (f" ({grund})." if grund else ".")
    if where == "verworfen":
        return f"Auftrag {nummer}: verworfen."
    if where == "unterbrochen":
        return (f"Auftrag {nummer}: UNTERBROCHEN - CWB ist waehrend des Auftrags abgestuerzt. "
                "Er wurde nicht wiederholt und hat keinen Bericht; bitte neu bestellen.")
    return f"Auftrag {nummer}: erledigt, aber ohne Bericht abgelegt."


def _zaehlen(ordner: Path) -> int:
    try:
        return sum(1 for p in ordner.glob("*.json") if p.is_file())
    except OSError:
        return 0


def _letzte_berichte(anzahl: int) -> list[int]:
    try:
        nummern = sorted(
            (int(p.stem) for p in berichte_ordner().glob("*.txt") if p.stem.isdigit()),
            reverse=True)
    except OSError:
        return []
    return nummern[:anzahl]


def status(zustand: dict | None = None) -> str:
    """Warteschlange und Lauf in Worten. `zustand` kommt vom Fenster (siehe
    OrchestratorAnsicht): {"projekt": str, "laeuft": bool, "wartet": int,
    "taetigkeit": str}. Ohne Fenster steht nur der Dateistand da."""
    zeilen = []
    if zustand:
        projekt = zustand.get("projekt") or "unbekannt"
        lauf = "ein Auftrag laeuft" if zustand.get("laeuft") else "nichts laeuft"
        zeilen.append(f"Projekt {projekt}: {lauf}, {int(zustand.get('wartet') or 0)} warten "
                      f"in der Warteschlange.")
        if zustand.get("taetigkeit"):
            zeilen.append(f"Zuletzt: {zustand['taetigkeit']}.")
    zeilen.append(
        f"Eingang: {_zaehlen(eingangsordner.EINGANG_ORDNER)} neu, "
        f"{_zaehlen(eingangsordner.laeuft_ordner())} angenommen und noch nicht fertig.")
    berichte = _letzte_berichte(STATUS_BERICHTE_ANZAHL)
    zeilen.append("Fertige Berichte: " + (", ".join(str(n) for n in berichte)
                                          if berichte else "keine") + ".")
    return "\n".join(zeilen)


# -- Eingebetteter MCP-Server -----------------------------------------------

def _antwort(text: str, fehler: bool = False) -> dict:
    ergebnis = {"content": [{"type": "text", "text": text}]}
    if fehler:
        ergebnis["is_error"] = True
    return ergebnis


def werkzeuge_bauen(zustand_geber=None, rueckfrage=None):
    """Baut den eingebetteten Werkzeug-Server (create_sdk_mcp_server) mit
    auftrag_senden, bericht_holen und status - nur fuer die Orchestrator-
    Sitzung; die normale Sitzung bekommt ihn nie. `zustand_geber()` liefert
    das Dict fuer `status` und darf None sein. `rueckfrage(satz, kurz_satz)`
    ist der ja/nein-Weg zu Robert fuer den Schleifenschutz. Jeder Aufruf faengt seine
    Ausnahmen ab und meldet sie als Werkzeugfehler."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    async def senden(args: dict) -> dict:
        try:
            verweigert = await schleife_pruefen(rueckfrage)
            if verweigert:
                return _antwort(verweigert, True)
            ergebnis = auftrag_senden(args.get("art", ""), args.get("projekt", ""),
                                      args.get("text", ""))
            return _antwort(ergebnis["meldung"], not ergebnis["ok"])
        except Exception as fehler:  # noqa: BLE001
            log.exception("auftrag_senden gescheitert: %s", fehler)
            return _antwort(f"auftrag_senden gescheitert: {fehler}", True)

    async def holen(args: dict) -> dict:
        try:
            return _antwort(bericht_holen(args.get("auftrag_nummer")))
        except Exception as fehler:  # noqa: BLE001
            log.exception("bericht_holen gescheitert: %s", fehler)
            return _antwort(f"bericht_holen gescheitert: {fehler}", True)

    async def lage(args: dict) -> dict:
        try:
            zustand = zustand_geber() if zustand_geber else None
            return _antwort(status(zustand))
        except Exception as fehler:  # noqa: BLE001
            log.exception("status gescheitert: %s", fehler)
            return _antwort(f"status gescheitert: {fehler}", True)

    werkzeuge = [
        tool("auftrag_senden",
             "Legt einen Auftrag in die Warteschlange von CWB. art ist RUN (Befehl im "
             "Terminal) oder CODE (Auftrag an Claude Code). Antwort: die Auftragsnummer.",
             {"type": "object",
              "properties": {"art": {"type": "string", "enum": list(ARTEN)},
                             "projekt": {"type": "string"},
                             "text": {"type": "string"}},
              "required": ["art", "projekt", "text"]})(senden),
        tool("bericht_holen",
             "Liest den Bericht zu einer Auftragsnummer (Kennzeile 'Auftrag N | Block B | "
             "Zeit T' vorweg). Ist der Auftrag nicht fertig, sagt die Antwort, wo er steht.",
             {"type": "object",
              "properties": {"auftrag_nummer": {"type": "integer"}},
              "required": ["auftrag_nummer"]})(holen),
        tool("status",
             "Zeigt Warteschlange, laufenden Auftrag und die letzten fertigen Berichte.",
             {"type": "object", "properties": {}})(lage),
    ]
    return create_sdk_mcp_server(SERVER_NAME, tools=werkzeuge)
