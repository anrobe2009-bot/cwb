"""
CWB - Code Workbench
Baustein 4: Projektgedächtnis.

Aufteilung:
- CLAUDE.md im Projekt        Grundlagen. Wird von Claude Code immer gelesen.
- wissen/tagebuch.md          wächst mit jeder Arbeitsstunde, neueste unten.
- wissen/offen.md             offene Punkte, das einzige, was immer eingespeist wird.
- wissen/archiv/JJJJ-MM.md    verdichtete alte Tagebucheinträge.

Der Memory Hub bleibt das Archiv. Von dort werden nur Einträge des aktuellen
Projekts gelesen, nie projektübergreifend - ausser 'global'.

Eingespeist wird in Schichten und gedeckelt, damit der Kontext nicht zuwächst.
"""

import logging
import re
import sqlite3
import sys
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

try:
    from .pfade import HUB_DATENBANK, INDEX_ORDNER
except ImportError:
    from pfade import HUB_DATENBANK, INDEX_ORDNER

log = logging.getLogger("cwb.wissen")

# Der Memory Hub liegt fest unter %LOCALAPPDATA%\CWB\memory_hub\ (siehe
# pfade.py, HUB_DATENBANK, und core/datenordner.py).
# Fehlt die Datei - z.B. bei einer frisch verschenkten Kopie ohne eigene
# Geschichte - arbeitet CWB einfach nur mit dem Gedächtnis im Projekt; sie
# entsteht von selbst, sobald der MCP-Server (memory_hub/memory_mcp.py) den
# ersten Eintrag schreibt.

MAX_TAGEBUCH = 40        # jüngste Tagebucheinträge im Kontextblock
MAX_HUB = 40             # Einträge aus dem Memory Hub im Kontextblock
ARCHIV_AB_TAGEN = 60     # ab diesem Alter wird verdichtet

ZEILE_MAX_LAENGE = 350   # jede Zeile im Kontextblock wird hierauf gekappt
BLOCK_MAX_LAENGE = 12000 # Obergrenze für den gesamten Kontextblock

KURZ_TAGEBUCH = 5         # juengste Tagebucheintraege im wiederholten Kurzblock
BLOCK_KURZ_MAX_LAENGE = 2000  # Obergrenze fuer den wiederholten Kurzblock

HINWEIS_GEKUERZT = "\n(Gekürzt. Mehr ist über die Suche erreichbar.)"
HINWEIS_GEDAECHTNIS = (
    "\nDies ist Gedächtnis, keine Aufgabe. Arbeite nur an dem, was jetzt "
    "gefragt wird.\n"
)
HINWEIS_WERKZEUGE = (
    "\ncode_suchen ist bei jeder Codesuche der erste Schritt, nicht nur eine "
    "Möglichkeit neben Grep - Grep erst, wenn code_suchen nichts Brauchbares "
    "findet. Erkenntnisse und Entscheidungen sofort mit memory_add sichern, "
    "nicht nur beim ersten Auftrag einer Sitzung.\n"
)

# Stichwortsuche je Auftrag (siehe Wissen.gedaechtnis_vor_auftrag): CWB sucht
# selbst im Memory Hub und im Code-Index, statt darauf zu warten, dass Claude
# Code memory_search/code_suchen aufruft - das blieb laut Messung vom
# 20.09.2026 ab 11 Uhr ganz aus (Block C6, Teil A; ersetzt den Vorlaeufer aus
# Block C5).
GEDAECHTNIS_VOR_AUFTRAG_MAX_LAENGE = 4000  # Obergrenze fuer den gesamten Block
GEDAECHTNIS_VOR_AUFTRAG_MAX_HUB = 8        # hoechstens so viele Hub-Treffer
GEDAECHTNIS_VOR_AUFTRAG_MAX_CODE = 5       # hoechstens so viele Code-Treffer
AUFTRAGSUCHE_MAX_STICHWORTE = 8   # hoechstens so viele Stichworte je Auftrag
AUFTRAGSUCHE_MIN_WORTLAENGE = 4   # kuerzere Woerter sind meist Fuellwoerter

# Zeilen, die reine Metadaten sind und keine Suchbegriffe liefern sollen:
# "Projekt: CWB" und Blocktitel wie "Block H12 - ...".
_MARKER_ZEILEN = re.compile(
    r"^\s*(projekt\s*:.*|block\s+\S+.*)$", re.IGNORECASE | re.MULTILINE
)

# Code-Index: gedeckelte Suchzeit, damit ein langsamer oder haengender
# Modell-Start den Auftrag nie blockiert (Block C6, Teil A Punkt 3).
CODE_SUCHE_ZEITLIMIT = 3.0

# Deutsche Fuellwoerter, die als Stichwort nichts taugen. Keine Vollstaendigkeit
# noetig - sie sollen nur die haeufigsten Woerter aus Auftragstexten aussieben.
STICHWORT_STOPWORTE = {
    "aber", "alle", "allen", "aller", "alles", "also", "auch", "auf", "aus",
    "bei", "beim", "bin", "bis", "bist", "da", "damit", "dann", "das", "dass",
    "dein", "deine", "dem", "den", "der", "des", "dessen", "dich", "die",
    "dies", "diese", "diesem", "diesen", "dieser", "dieses", "dir", "doch",
    "dort", "durch", "eine", "einem", "einen", "einer", "eines", "einige",
    "euch", "eure", "für", "gegen", "gewesen", "habe", "haben", "hast",
    "hat", "hatte", "hatten", "hier", "hin", "hinter", "ihm", "ihn", "ihnen",
    "ihre", "ihrem", "ihren", "ihrer", "ihres", "immer", "ins", "ist", "jede",
    "jedem", "jeden", "jeder", "jedes", "jener", "jetzt", "kann", "kein",
    "keine", "keinem", "keinen", "keiner", "können", "könnte", "machen",
    "mehr", "mein", "meine", "mich", "mir", "mit", "muss", "müssen", "nach",
    "nicht", "noch", "nun", "nur", "ohne", "schon", "sehr", "sein", "seine",
    "seinem", "seinen", "seiner", "seit", "sich", "sind", "soll", "sollen",
    "sollte", "sonst", "soweit", "sowie", "unser", "unter", "viel", "vom",
    "von", "vor", "wann", "war", "waren", "warum", "was", "weil", "weiter",
    "weitere", "wenn", "werde", "werden", "wie", "wieder", "will", "wird",
    "wirst", "wollen", "wollte", "würde", "würden", "zum", "zur", "zwar",
    "zwischen", "wurde", "wurden", "dabei", "davon", "dafür", "dadurch",
    "dazu", "etwa", "etwas", "ganz", "genau", "gerade", "gleich",
}


def _kappen(zeile: str, laenge: int = ZEILE_MAX_LAENGE) -> str:
    """Kürzt eine einzelne Zeile auf höchstens `laenge` Zeichen."""
    zeile = zeile.rstrip()
    if len(zeile) <= laenge:
        return zeile
    return zeile[: laenge - 1].rstrip() + "…"


def _stichworte(text: str, projektname: str = "",
                 hoechstens: int = AUFTRAGSUCHE_MAX_STICHWORTE) -> list[str]:
    """Zieht die tragenden Stichworte aus einem Auftragstext: Woerter ab
    AUFTRAGSUCHE_MIN_WORTLAENGE Zeichen, ohne Fuellwoerter und ohne den
    Projektnamen selbst (der waere als Suchbegriff nur Rauschen, weil ohnehin
    schon nach dem Projekt gefiltert wird). Laengere Woerter zuerst, weil im
    Deutschen lange (oft zusammengesetzte) Woerter meist die tragfaehigeren
    Suchbegriffe sind."""
    roh = re.findall(r"[A-Za-zÄÖÜäöüß]{" + str(AUFTRAGSUCHE_MIN_WORTLAENGE) + r",}", text)
    projekt_klein = projektname.strip().lower()
    gesehen: dict[str, None] = {}
    for wort in roh:
        klein = wort.lower()
        if klein in STICHWORT_STOPWORTE or klein == projekt_klein:
            continue
        gesehen.setdefault(klein, None)
    einzigartig = sorted(gesehen, key=len, reverse=True)
    return einzigartig[:hoechstens]


def _auftragstext_bereinigt(text: str) -> str:
    """Entfernt Metadatenzeilen ('Projekt: …', 'Block H12 …') aus dem
    Auftragstext, bevor Stichworte gezogen werden - beides ist Einordnung,
    kein Suchbegriff."""
    return _MARKER_ZEILEN.sub("", text)


def _ohne_dopplungen(basis: str, neu: str) -> str:
    """Entfernt aus `neu` jede Aufzaehlungszeile, die (unveraendert) schon in
    `basis` steht - fuer das Zusammenfuehren von Kontextblock und
    Gedaechtnis-vor-Auftrag beim ersten Auftrag einer Sitzung (Block C6,
    Teil A Punkt 2: 'ohne Dopplungen'). Leer gewordene Abschnitte (nur noch
    eine Ueberschrift) werden anschliessend mit entfernt."""
    if not basis.strip() or not neu.strip():
        return neu
    vorhandene = {z.strip() for z in basis.splitlines() if z.strip().startswith("-")}
    behalten = [
        zeile for zeile in neu.splitlines()
        if not (zeile.strip().startswith("-") and zeile.strip() in vorhandene)
    ]
    # Ueberschriften, denen keine Aufzaehlungszeile mehr folgt (weil alle
    # Zeilen darunter Dopplungen waren), fallen mit weg.
    bereinigt: list[str] = []
    for i, zeile in enumerate(behalten):
        if zeile.strip().startswith("##"):
            folgt_inhalt = False
            for weiter in behalten[i + 1:]:
                if weiter.strip().startswith("##"):
                    break
                if weiter.strip().startswith("-"):
                    folgt_inhalt = True
                    break
            if not folgt_inhalt:
                continue
        bereinigt.append(zeile)
    return "\n".join(bereinigt).strip()


# ---------------------------------------------------------------------------
# Code-Index: eigene, direkte Suche vor jedem Auftrag (Block C6, Teil A).
# Das Embedding-Modell wird einmal pro CWB-Prozess im Hintergrund geladen
# (code_index_vorladen(), von sitzung.py beim Laden angestossen), damit die
# erste echte Suche nicht auf den Modell-Start warten muss. Jede Suche selbst
# laeuft in einem eigenen, daemonischen Faden mit Zeitlimit - haengt sie,
# blockiert das nie den Auftrag, es gibt nur keine Code-Treffer.
# ---------------------------------------------------------------------------

_code_index_modul = None  # None = noch nicht versucht, False = gescheitert
_code_index_lock = threading.Lock()
_code_index_lade_faden: threading.Thread | None = None


def _code_index_laden():
    global _code_index_modul
    with _code_index_lock:
        if _code_index_modul is not None:
            return _code_index_modul
        try:
            pfad = str(INDEX_ORDNER)
            if pfad not in sys.path:
                sys.path.insert(0, pfad)
            import indexer  # noqa: PLC0415
            indexer._embedding_fn()  # laedt das Modell einmal vor
            _code_index_modul = indexer
            log.info("Code-Index-Modell geladen")
        except Exception as fehler:  # noqa: BLE001
            log.warning("Code-Index nicht ladbar, Suche vor Auftraegen bleibt aus: %s", fehler)
            _code_index_modul = False
        return _code_index_modul


def code_index_vorladen() -> None:
    """Stoesst das Laden des Embedding-Modells einmal pro CWB-Prozess im
    Hintergrund an. Weitere Aufrufe tun nichts, solange der erste noch laeuft
    oder schon fertig ist."""
    global _code_index_lade_faden
    with _code_index_lock:
        if _code_index_modul is not None or _code_index_lade_faden is not None:
            return
        _code_index_lade_faden = threading.Thread(
            target=_code_index_laden, daemon=True, name="cwb-codeindex-laden"
        )
        _code_index_lade_faden.start()


def _code_index_suchen(projekt_pfad: Path, frage: str, anzahl: int) -> tuple[list[str], bool]:
    """Fragt den Code-Index synchron ab, gedeckelt auf CODE_SUCHE_ZEITLIMIT
    Sekunden (in einem eigenen daemonischen Faden, der bei Zeitueberschreitung
    einfach weiterlaeuft und verworfen wird). Rueckgabe: (Zeilen, ob der
    Code-Index in diesem Prozess ueberhaupt verfuegbar ist)."""
    ergebnis: dict = {}

    def _lauf() -> None:
        try:
            modul = _code_index_laden()
            ergebnis["treffer"] = modul.search(str(projekt_pfad), frage, n_results=anzahl) if modul else []
        except Exception as fehler:  # noqa: BLE001
            ergebnis["fehler"] = fehler

    faden = threading.Thread(target=_lauf, daemon=True, name="cwb-codesuche")
    faden.start()
    faden.join(CODE_SUCHE_ZEITLIMIT)

    verfuegbar = _code_index_modul is not False
    if faden.is_alive():
        log.warning("Code-Index-Suche vor Auftrag laenger als %ss, ohne Treffer weiter",
                    CODE_SUCHE_ZEITLIMIT)
        return [], verfuegbar
    if "fehler" in ergebnis:
        log.warning("Code-Index-Suche vor Auftrag gescheitert: %s", ergebnis["fehler"])
        return [], verfuegbar

    zeilen: list[str] = []
    for treffer in ergebnis.get("treffer") or []:
        quelle = treffer.get("source") or "?"
        try:
            ort = str(Path(quelle).relative_to(projekt_pfad))
        except ValueError:
            ort = Path(quelle).name
        if treffer.get("zeile_von"):
            ort += f":{treffer['zeile_von']}-{treffer['zeile_bis']}"
        text = " ".join((treffer.get("text") or "").split())[:160]
        zeilen.append(f"{ort} — {text}")
    return zeilen, verfuegbar


GRUNDLAGEN_VORLAGE = """# {name}

## Was das Projekt ist
(noch nicht ausgefüllt)

## Aufbau
(noch nicht ausgefüllt)

## Konventionen
- Strikte Trennung: keine Inline-Scripts, keine Inline-Styles, keine Inline-Event-Handler
- Barrierefreiheit hat Vorrang, die Oberfläche muss für sehende Nutzer trotzdem gut aussehen
- Flexible, responsive Raster, keine festen Pixelgrössen
- Jede neue Werkzeugdatei bekommt Fehler-Logging über das Modul logging

## Arbeitsweise
- Lies eine Datei, bevor du sie änderst.
- Antworte kurz. Ein bis drei Sätze zum Ergebnis, keine langen Erklärungen.
- Sag es in einem Satz, wenn etwas unklar, unmöglich oder unlogisch ist.

## Gedächtnis
- Offene Punkte stehen in `wissen/offen.md`.
- Was getan und entschieden wurde, steht in `wissen/tagebuch.md`.
- Beides wird von CWB gepflegt. Schreib nicht selbst hinein, ausser du wirst gefragt.
- CWB stellt vor jedem Auftrag selbst Treffer aus Memory Hub und Code-Index voran
  ("[GEDÄCHTNIS VOR DEM AUFTRAG]"). Das ersetzt eigenes Suchen nicht: rufe vor der
  ersten Änderung trotzdem memory_search und code_suchen auf - ohne das lehnt CWB
  den ersten Schreibversuch technisch ab (Suchpflicht, F12 → Verhalten).
"""

# Wird nach jedem Auftrag als Anschlussfrage gestellt
NACHTRAG_ANWEISUNG = (
    "Fasse den gerade erledigten Auftrag in ein bis drei kurzen Zeilen für das "
    "Projekttagebuch zusammen. Nur Entscheidungen, Änderungen und offene Punkte. "
    "Keine Aufzählung jedes Arbeitsschritts, keine Vorrede. "
    "Steht etwas offen, schreibe die Zeile mit [OFFEN] davor."
)


@dataclass
class Eintrag:
    """Eine Zeile aus Tagebuch, offenen Punkten oder Hub."""
    datum: str
    text: str
    offen: bool = False

    def zeile(self) -> str:
        marke = "[OFFEN] " if self.offen else ""
        return f"{self.datum}  {marke}{self.text}"


# ---------------------------------------------------------------------------
# Memory Hub, lesend und anpassungsfähig
# ---------------------------------------------------------------------------

class HubLeser:
    """Liest aus memory.db. Findet die Spalten selbst, damit nichts bricht."""

    def __init__(self, datenbank: Path | None = None):
        if datenbank is None:
            datenbank = HUB_DATENBANK
        self.datenbank = Path(datenbank) if datenbank else None
        self.tabelle: str | None = None
        self.spalte_projekt: str | None = None
        self.spalte_text: str | None = None
        self.spalte_datum: str | None = None
        self.spalte_aktualisiert: str | None = None
        self.spalte_pinned: str | None = None
        self.fts_tabelle: str | None = None
        if self.datenbank is None:
            log.info("Kein Memory Hub eingestellt, es wird keiner gelesen")
        elif self.datenbank.exists():
            self._erkunden()
        else:
            log.warning("Memory Hub nicht gefunden: %s", self.datenbank)

    def _erkunden(self) -> None:
        try:
            with sqlite3.connect(f"file:{self.datenbank}?mode=ro", uri=True) as verbindung:
                tabellen = [
                    zeile[0]
                    for zeile in verbindung.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                ]
                for tabelle in tabellen:
                    spalten = [
                        zeile[1]
                        for zeile in verbindung.execute(f"PRAGMA table_info('{tabelle}')")
                    ]
                    klein = {s.lower(): s for s in spalten}
                    projekt = next(
                        (klein[k] for k in ("projekt", "project", "bereich", "kategorie")
                         if k in klein), None
                    )
                    text = next(
                        (klein[k] for k in ("text", "inhalt", "content", "eintrag", "notiz")
                         if k in klein), None
                    )
                    if projekt and text:
                        self.tabelle = tabelle
                        self.spalte_projekt = projekt
                        self.spalte_text = text
                        self.spalte_datum = next(
                            (klein[k] for k in ("datum", "date", "zeit", "created", "erstellt",
                                                "timestamp", "zeitstempel") if k in klein), None
                        )
                        self.spalte_aktualisiert = next(
                            (klein[k] for k in ("updated", "aktualisiert", "geaendert")
                             if k in klein), None
                        )
                        self.spalte_pinned = klein.get("pinned")
                        fts_kandidat = f"{tabelle}_fts"
                        if fts_kandidat in tabellen:
                            self.fts_tabelle = fts_kandidat
                        log.info(
                            "Hub erkannt: Tabelle %s, Projekt %s, Text %s, Datum %s, "
                            "Aktualisiert %s, FTS5 %s",
                            tabelle, projekt, text, self.spalte_datum, self.spalte_aktualisiert,
                            self.fts_tabelle or "nein",
                        )
                        return
            log.warning("Keine passende Tabelle im Hub gefunden: %s", tabellen)
        except sqlite3.Error as fehler:
            log.error("Hub nicht lesbar: %s", fehler)

    @property
    def bereit(self) -> bool:
        return bool(self.tabelle and self.spalte_projekt and self.spalte_text)

    def eintraege(self, projekt: str, grenze: int = MAX_HUB) -> list[Eintrag]:
        """Offene Punkte zuerst, dann die jüngsten Einträge. Nur dieses Projekt."""
        if not self.bereit:
            return []

        datum = self.spalte_datum or "rowid"
        befehl = (
            f"SELECT {datum}, {self.spalte_text} FROM {self.tabelle} "
            f"WHERE lower({self.spalte_projekt}) IN (?, 'global') "
            f"ORDER BY {datum} DESC LIMIT ?"
        )
        try:
            with sqlite3.connect(f"file:{self.datenbank}?mode=ro", uri=True) as verbindung:
                zeilen = verbindung.execute(befehl, (projekt.lower(), grenze * 4)).fetchall()
        except sqlite3.Error as fehler:
            log.error("Hub-Abfrage gescheitert: %s", fehler)
            return []

        gefunden = []
        for zeile in zeilen:
            if not zeile[1] or not str(zeile[1]).strip():
                continue
            roh = str(zeile[1]).strip()
            offen = "[OFFEN]" in roh.upper()
            sauber = re.sub(r"\[OFFEN\]\s*", "", roh, flags=re.IGNORECASE).strip()
            gefunden.append(Eintrag(str(zeile[0])[:10], sauber, offen))
        offene = [e for e in gefunden if e.offen]
        rest = [e for e in gefunden if not e.offen]
        return (offene + rest)[:grenze]

    def suchen(self, begriff: str, projekt: str, grenze: int = 20) -> list[Eintrag]:
        if not self.bereit or not begriff.strip():
            return []
        befehl = (
            f"SELECT {self.spalte_datum or 'rowid'}, {self.spalte_text} FROM {self.tabelle} "
            f"WHERE lower({self.spalte_projekt}) IN (?, 'global') "
            f"AND {self.spalte_text} LIKE ? LIMIT ?"
        )
        try:
            with sqlite3.connect(f"file:{self.datenbank}?mode=ro", uri=True) as verbindung:
                zeilen = verbindung.execute(
                    befehl, (projekt.lower(), f"%{begriff}%", grenze)
                ).fetchall()
        except sqlite3.Error as fehler:
            log.error("Hub-Suche gescheitert: %s", fehler)
            return []
        return [Eintrag(str(z[0])[:10], str(z[1]).strip()) for z in zeilen if z[1]]

    def suchen_fts(self, stichworte: list[str], projekt: str, grenze: int = 8) -> list[Eintrag]:
        """Volltextsuche ueber die FTS5-Tabelle des Memory Hub (memory_hub/
        memory_db.py legt sie als '<tabelle>_fts' an), angeheftete und dann
        die besten Treffer zuerst. Ohne FTS5-Tabelle (aeltere oder fremde
        Datenbank) automatisch die gewoehnliche LIKE-Suche je Stichwort."""
        if not self.bereit or not stichworte:
            return []
        if not self.fts_tabelle:
            gefunden: dict[str, Eintrag] = {}
            for wort in stichworte:
                for eintrag in self.suchen(wort, projekt, grenze=grenze):
                    gefunden.setdefault(eintrag.text, eintrag)
                if len(gefunden) >= grenze:
                    break
            return list(gefunden.values())[:grenze]

        ausdruck = " OR ".join(f'"{w}"*' for w in stichworte if w)
        if not ausdruck:
            return []
        datum = self.spalte_datum or "rowid"
        reihenfolge = (
            f"m.{self.spalte_pinned} DESC, bm25({self.fts_tabelle})"
            if self.spalte_pinned else f"bm25({self.fts_tabelle})"
        )
        befehl = (
            f"SELECT m.{datum}, m.{self.spalte_text} FROM {self.fts_tabelle} f "
            f"JOIN {self.tabelle} m ON m.rowid = f.rowid "
            f"WHERE {self.fts_tabelle} MATCH ? "
            f"AND lower(m.{self.spalte_projekt}) IN (?, 'global') "
            f"ORDER BY {reihenfolge} LIMIT ?"
        )
        try:
            with sqlite3.connect(f"file:{self.datenbank}?mode=ro", uri=True) as verbindung:
                zeilen = verbindung.execute(
                    befehl, (ausdruck, projekt.lower(), grenze)
                ).fetchall()
        except sqlite3.Error as fehler:
            log.warning("FTS5-Suche gescheitert, weiche auf LIKE aus: %s", fehler)
            gefunden: dict[str, Eintrag] = {}
            for wort in stichworte:
                for eintrag in self.suchen(wort, projekt, grenze=grenze):
                    gefunden.setdefault(eintrag.text, eintrag)
            return list(gefunden.values())[:grenze]
        return [Eintrag(str(z[0])[:10], str(z[1]).strip()) for z in zeilen if z[1]]

    def eintrag_schreiben(self, projekt: str, text: str, datum: str | None = None) -> bool:
        """Schreibt eine neue Zeile in die Hub-Datenbank, unter Verwendung der
        bereits erkannten Spalten. Fehlt der Hub, ist er nicht erreichbar oder
        schlaegt das Schreiben fehl, wird nur geloggt - die Sitzung darf
        davon nicht beeintraechtigt werden."""
        if not self.bereit:
            log.info("Kein Memory Hub erreichbar, Eintrag nicht geschrieben")
            return False
        spalten = [self.spalte_projekt, self.spalte_text]
        werte = [projekt, text]
        wert_datum = datum or date.today().isoformat()
        if self.spalte_datum:
            spalten.append(self.spalte_datum)
            werte.append(wert_datum)
        if self.spalte_aktualisiert:
            spalten.append(self.spalte_aktualisiert)
            werte.append(wert_datum)
        platzhalter = ", ".join("?" for _ in werte)
        befehl = (
            f"INSERT INTO {self.tabelle} ({', '.join(spalten)}) "
            f"VALUES ({platzhalter})"
        )
        try:
            with sqlite3.connect(str(self.datenbank)) as verbindung:
                verbindung.execute(befehl, werte)
                verbindung.commit()
            log.info("Eintrag in Memory Hub geschrieben (Projekt %s)", projekt)
            return True
        except sqlite3.Error as fehler:
            log.error("Eintrag nicht in Memory Hub schreibbar: %s", fehler)
            return False


# ---------------------------------------------------------------------------
# Wissensschicht im Projekt
# ---------------------------------------------------------------------------

class Wissen:
    """Grundlagen, Tagebuch und offene Punkte eines Projekts."""

    def __init__(self, projekt_pfad: Path, projekt_name: str):
        self.pfad = Path(projekt_pfad)
        self.name = projekt_name
        self.ordner = self.pfad / "wissen"
        self.archiv = self.ordner / "archiv"
        self.grundlagen_datei = self.pfad / "CLAUDE.md"
        self.tagebuch_datei = self.ordner / "tagebuch.md"
        self.offen_datei = self.ordner / "offen.md"
        self.hub = HubLeser()

    # -- Einrichten ---------------------------------------------------------

    def _verschachtelter_vorfahr(self) -> Path | None:
        """Findet einen Vorfahrenordner mit eigenem wissen/tagebuch.md und
        CLAUDE.md. Verhindert, dass ein falsch übergebener Unterordner
        (z.B. core/ statt des Projektwurzelordners) ein eigenes, verwaistes
        Wissen bekommt - so entstand am 09.09.2026 core/wissen."""
        for vorfahr in self.pfad.parents:
            if (vorfahr / "wissen" / "tagebuch.md").exists() and (vorfahr / "CLAUDE.md").exists():
                return vorfahr
        return None

    def einrichten(self) -> bool:
        """Legt Ordner und Dateien an, falls sie fehlen. Ändert nichts Bestehendes."""
        vorfahr = self._verschachtelter_vorfahr()
        if vorfahr is not None:
            log.error(
                "Projektpfad %s liegt unter dem bestehenden Projekt %s - "
                "kein eigenes Wissen angelegt (vermutlich falscher Projektpfad)",
                self.pfad, vorfahr,
            )
            return False
        try:
            self.archiv.mkdir(parents=True, exist_ok=True)
            if not self.grundlagen_datei.exists():
                self.grundlagen_datei.write_text(
                    GRUNDLAGEN_VORLAGE.format(name=self.name), encoding="utf-8"
                )
                log.info("CLAUDE.md angelegt in %s", self.pfad)
            if not self.tagebuch_datei.exists():
                self.tagebuch_datei.write_text(
                    f"# Tagebuch {self.name}\n\n", encoding="utf-8"
                )
            if not self.offen_datei.exists():
                self.offen_datei.write_text(
                    f"# Offene Punkte {self.name}\n\n", encoding="utf-8"
                )
            return True
        except OSError as fehler:
            log.error("Wissensordner nicht anlegbar: %s", fehler)
            return False

    # -- Lesen --------------------------------------------------------------

    def grundlagen(self) -> str:
        try:
            return self.grundlagen_datei.read_text(encoding="utf-8").strip()
        except OSError as fehler:
            log.error("CLAUDE.md nicht lesbar: %s", fehler)
            return ""

    def _zeilen(self, datei: Path) -> list[Eintrag]:
        try:
            roh = datei.read_text(encoding="utf-8").splitlines()
        except OSError as fehler:
            log.error("%s nicht lesbar: %s", datei.name, fehler)
            return []

        gefunden: list[Eintrag] = []
        for zeile in roh:
            zeile = zeile.strip()
            if not zeile or zeile.startswith("#"):
                continue
            treffer = re.match(r"^-?\s*(\d{4}-\d{2}-\d{2})\s+(.*)$", zeile)
            if treffer:
                text = treffer.group(2).strip()
                gefunden.append(
                    Eintrag(treffer.group(1), text.replace("[OFFEN]", "").strip(),
                            "[OFFEN]" in text.upper())
                )
            else:
                gefunden.append(
                    Eintrag("", zeile.lstrip("- ").replace("[OFFEN]", "").strip(),
                            "[OFFEN]" in zeile.upper())
                )
        return gefunden

    def offene_punkte(self) -> list[Eintrag]:
        aus_datei = [e for e in self._zeilen(self.offen_datei)]
        aus_tagebuch = [e for e in self._zeilen(self.tagebuch_datei) if e.offen]
        return aus_datei + aus_tagebuch

    def tagebuch(self, grenze: int = MAX_TAGEBUCH) -> list[Eintrag]:
        alle = self._zeilen(self.tagebuch_datei)
        return alle[-grenze:]

    # -- Kontextblock -------------------------------------------------------

    def kontextblock(self) -> str:
        """Wird der ersten Nachricht einer Sitzung vorangestellt.

        Gedeckelt auf BLOCK_MAX_LAENGE Zeichen, jede Zeile auf ZEILE_MAX_LAENGE.
        Offene Punkte haben Vorrang und werden nie gekürzt, danach füllt das
        Tagebuch (jüngste zuerst) und zuletzt der Memory Hub den Rest des
        Platzes. Wird dabei etwas weggelassen, folgt ein Hinweis auf die Suche.
        """
        kopf = f"# Projektgedächtnis: {self.name}"

        offen = self.offene_punkte()
        offen_teil: list[str] = []
        if offen:
            offen_teil.append("\n## Offene Punkte")
            offen_teil += [_kappen(f"- {e.text}") for e in offen]

        letzte = self.tagebuch()
        tagebuch_zeilen = [_kappen(f"- {e.zeile()}") for e in letzte]

        aus_hub = self.hub.eintraege(self.name)
        hub_zeilen = [_kappen(f"- {e.zeile()}") for e in aus_hub]

        if not offen_teil and not tagebuch_zeilen and not hub_zeilen:
            return ""

        teile = [kopf] + offen_teil
        gekuerzt = False
        rueckhalt = len(HINWEIS_GEKUERZT) + len(HINWEIS_GEDAECHTNIS) + 2

        def _passt_rest(bisher: list[str]) -> int:
            return BLOCK_MAX_LAENGE - len("\n".join(bisher)) - rueckhalt

        # Tagebuch: jüngste zuerst auffüllen, solange Platz reicht.
        if tagebuch_zeilen:
            ueberschrift = f"\n## Zuletzt gearbeitet (letzte {len(letzte)} Einträge)"
            budget = _passt_rest(teile) - len(ueberschrift)
            genommen: list[str] = []
            laenge = 0
            for zeile in reversed(tagebuch_zeilen):
                if laenge + 1 + len(zeile) > budget:
                    gekuerzt = True
                    break
                genommen.append(zeile)
                laenge += 1 + len(zeile)
            genommen.reverse()
            if genommen:
                teile += [ueberschrift] + genommen

        # Memory Hub: höchste Priorität zuerst, solange Platz reicht.
        if hub_zeilen:
            ueberschrift = f"\n## Aus dem Memory Hub ({len(aus_hub)} von vielen)"
            budget = _passt_rest(teile) - len(ueberschrift)
            genommen = []
            laenge = 0
            for zeile in hub_zeilen:
                if laenge + 1 + len(zeile) > budget:
                    gekuerzt = True
                    break
                genommen.append(zeile)
                laenge += 1 + len(zeile)
            if genommen:
                teile += [ueberschrift] + genommen
            if len(genommen) < len(hub_zeilen):
                gekuerzt = True

        if gekuerzt:
            teile.append(HINWEIS_GEKUERZT)
        teile.append(HINWEIS_GEDAECHTNIS)
        return "\n".join(teile)

    def kontextblock_kurz(self) -> str:
        """Wird in derselben Sitzung in regelmaessigen Abstaenden erneut
        vorangestellt (siehe sitzung.py, AUFTRAG_KONTEXT_ALLE), nicht nur dem
        ersten Auftrag: Claude Code ruft memory_search/code_suchen sonst nach
        dem ersten Auftrag praktisch nie wieder auf, obwohl die Regel dafuer
        in der globalen CLAUDE.md steht.

        Deutlich kuerzer als `kontextblock()`: nur die offenen Punkte und die
        juengsten KURZ_TAGEBUCH Tagebucheintraege, gedeckelt auf
        BLOCK_KURZ_MAX_LAENGE Zeichen statt BLOCK_MAX_LAENGE - kein Hub-Anteil,
        das waere fuer eine Erinnerung mitten in der Sitzung zu viel."""
        offen = self.offene_punkte()
        letzte = self.tagebuch(KURZ_TAGEBUCH)
        if not offen and not letzte:
            return ""

        kopf = f"# Projektgedächtnis: {self.name} (Kurzfassung)"
        teile = [kopf]
        rest = BLOCK_KURZ_MAX_LAENGE - len(kopf) - len(HINWEIS_WERKZEUGE)

        if offen:
            ueberschrift = "\n## Offene Punkte"
            budget = rest - len(ueberschrift)
            genommen: list[str] = []
            laenge = 0
            for e in offen:
                zeile = _kappen(f"- {e.text}")
                if laenge + 1 + len(zeile) > budget:
                    break
                genommen.append(zeile)
                laenge += 1 + len(zeile)
            if genommen:
                teile += [ueberschrift] + genommen
                rest -= len(ueberschrift) + laenge

        if letzte:
            ueberschrift = f"\n## Zuletzt gearbeitet (letzte {len(letzte)} Einträge)"
            budget = rest - len(ueberschrift)
            genommen = []
            laenge = 0
            for e in reversed(letzte):
                zeile = _kappen(f"- {e.zeile()}")
                if laenge + 1 + len(zeile) > budget:
                    break
                genommen.append(zeile)
                laenge += 1 + len(zeile)
            genommen.reverse()
            if genommen:
                teile += [ueberschrift] + genommen

        teile.append(HINWEIS_WERKZEUGE)
        return "\n".join(teile)

    def gedaechtnis_vor_auftrag(self, auftragstext: str) -> tuple[str, bool]:
        """Sucht selbststaendig im Memory Hub (FTS5) und im Code-Index dieses
        Projekts nach Stichworten aus dem Auftragstext, damit das Gedaechtnis
        auch dann greift, wenn Claude Code memory_search/code_suchen nicht
        von sich aus aufruft (Messung 20./21.09.2026: praktisch nie). Ersetzt
        die reine Hub-Stichwortsuche aus Block C5.

        Rueckgabe: (Blocktext oder leerer String, ob der Code-Index in diesem
        Prozess ueberhaupt verfuegbar ist - fuer Protokoll/Selbsttest, nicht
        sicherheitsrelevant). Gedeckelt auf GEDAECHTNIS_VOR_AUFTRAG_MAX_LAENGE
        Zeichen."""
        bereinigt = _auftragstext_bereinigt(auftragstext)
        stichworte = _stichworte(bereinigt, self.name)

        teile: list[str] = []
        laenge = 0

        def _anhaengen(zeile: str) -> bool:
            nonlocal laenge
            zeile = _kappen(zeile)
            if laenge + 1 + len(zeile) > GEDAECHTNIS_VOR_AUFTRAG_MAX_LAENGE:
                return False
            teile.append(zeile)
            laenge += 1 + len(zeile)
            return True

        if stichworte:
            hub_treffer = self.hub.suchen_fts(stichworte, self.name, GEDAECHTNIS_VOR_AUFTRAG_MAX_HUB)
            if hub_treffer:
                _anhaengen("## Aus dem Memory Hub")
                for eintrag in hub_treffer:
                    if not _anhaengen(f"- {eintrag.zeile()}"):
                        break

        code_zeilen, code_verfuegbar = _code_index_suchen(
            self.pfad, bereinigt.strip() or auftragstext, GEDAECHTNIS_VOR_AUFTRAG_MAX_CODE
        )
        if code_zeilen:
            _anhaengen("\n## Aus dem Code-Index")
            for zeile in code_zeilen:
                if not _anhaengen(f"- {zeile}"):
                    break

        return ("\n".join(teile), code_verfuegbar)

    # -- Schreiben ----------------------------------------------------------

    def tagebuch_anhaengen(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        heute = date.today().isoformat()
        inhalte = [z.strip() for z in text.splitlines() if z.strip()]
        zeilen = [f"- {heute} {z}" for z in inhalte]
        try:
            with self.tagebuch_datei.open("a", encoding="utf-8") as datei:
                datei.write("\n".join(zeilen) + "\n")
        except OSError as fehler:
            log.error("Tagebuch nicht schreibbar: %s", fehler)
            return False
        for inhalt in inhalte:
            self.hub.eintrag_schreiben(self.name, inhalt, heute)
        return True

    def offen_anhaengen(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        try:
            with self.offen_datei.open("a", encoding="utf-8") as datei:
                datei.write(f"- {date.today().isoformat()} {text}\n")
            return True
        except OSError as fehler:
            log.error("Offene Punkte nicht schreibbar: %s", fehler)
            return False

    def offen_schliessen(self, suchtext: str) -> bool:
        """Entfernt die erste Zeile, die den Suchtext enthält."""
        try:
            zeilen = self.offen_datei.read_text(encoding="utf-8").splitlines()
        except OSError as fehler:
            log.error("Offene Punkte nicht lesbar: %s", fehler)
            return False

        for nummer, zeile in enumerate(zeilen):
            if suchtext.lower() in zeile.lower() and not zeile.startswith("#"):
                erledigt = zeilen.pop(nummer)
                try:
                    self.offen_datei.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
                except OSError as fehler:
                    log.error("Offene Punkte nicht schreibbar: %s", fehler)
                    return False
                self.tagebuch_anhaengen(f"Erledigt: {erledigt.lstrip('- ').strip()}")
                return True
        return False

    # -- Suchen -------------------------------------------------------------

    def suchen(self, begriff: str) -> list[Eintrag]:
        begriff = begriff.strip().lower()
        if not begriff:
            return []
        gefunden = [
            e for e in self._zeilen(self.tagebuch_datei) + self._zeilen(self.offen_datei)
            if begriff in e.text.lower()
        ]
        for datei in sorted(self.archiv.glob("*.md")):
            gefunden += [e for e in self._zeilen(datei) if begriff in e.text.lower()]
        return gefunden + self.hub.suchen(begriff, self.name)

    # -- Verdichten ---------------------------------------------------------

    def zum_verdichten(self, ab_tagen: int = ARCHIV_AB_TAGEN) -> list[Eintrag]:
        """Tagebucheinträge, die alt genug fürs Archiv sind."""
        heute = date.today()
        alt: list[Eintrag] = []
        for eintrag in self._zeilen(self.tagebuch_datei):
            if eintrag.offen or not eintrag.datum:
                continue
            try:
                wann = datetime.strptime(eintrag.datum, "%Y-%m-%d").date()
            except ValueError:
                continue
            if (heute - wann).days >= ab_tagen:
                alt.append(eintrag)
        return alt

    def verdichten(self, zusammenfassung: str, verdichtete: list[Eintrag]) -> bool:
        """Schreibt die Zusammenfassung ins Archiv und entfernt die alten Zeilen."""
        if not verdichtete or not zusammenfassung.strip():
            return False

        monat = verdichtete[0].datum[:7] or date.today().strftime("%Y-%m")
        ziel = self.archiv / f"{monat}.md"
        try:
            with ziel.open("a", encoding="utf-8") as datei:
                datei.write(
                    f"\n## Verdichtet am {date.today().isoformat()} "
                    f"({len(verdichtete)} Einträge)\n{zusammenfassung.strip()}\n"
                )
        except OSError as fehler:
            log.error("Archiv nicht schreibbar: %s", fehler)
            return False

        alte_texte = {e.text for e in verdichtete}
        try:
            zeilen = self.tagebuch_datei.read_text(encoding="utf-8").splitlines()
            behalten = [
                z for z in zeilen
                if z.startswith("#") or not z.strip()
                or not any(t and t in z for t in alte_texte)
            ]
            self.tagebuch_datei.write_text("\n".join(behalten) + "\n", encoding="utf-8")
        except OSError as fehler:
            log.error("Tagebuch nicht kürzbar: %s", fehler)
            return False

        log.info("%d Einträge verdichtet nach %s", len(verdichtete), ziel.name)
        return True


# ---------------------------------------------------------------------------
# Selbsttest
# ---------------------------------------------------------------------------

def _selbsttest() -> None:
    try:
        from .sicherheit import projekte_finden
    except ImportError:
        from sicherheit import projekte_finden

    hub = HubLeser()
    print("Memory Hub:", "erkannt" if hub.bereit else "nicht erkannt")
    if hub.bereit:
        print(f"  Tabelle {hub.tabelle}, Projekt {hub.spalte_projekt}, "
              f"Text {hub.spalte_text}, Datum {hub.spalte_datum}")

    projekte = projekte_finden()
    if not projekte:
        print("Keine Projekte gefunden.")
        return

    print("\nProjekte:")
    for nummer, projekt in enumerate(projekte, 1):
        print(f"  {nummer}. {projekt.name}")

    wahl = input("\nNummer wählen: ").strip()
    if not wahl.isdigit() or not 1 <= int(wahl) <= len(projekte):
        return
    projekt = projekte[int(wahl) - 1]

    wissen = Wissen(projekt.pfad, projekt.name)
    print("\nEinrichten:", "ok" if wissen.einrichten() else "gescheitert")
    print(f"Offene Punkte: {len(wissen.offene_punkte())}")
    print(f"Tagebuch: {len(wissen.tagebuch())} jüngste Einträge")
    print(f"Zum Verdichten: {len(wissen.zum_verdichten())} Einträge")

    block = wissen.kontextblock()
    print(f"\nKontextblock: {len(block)} Zeichen, {len(block.splitlines())} Zeilen")
    print("-" * 60)
    print(block[:1500] or "(leer)")


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    try:
        _selbsttest()
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
    except Exception as fehler:  # noqa: BLE001
        log.exception("Selbsttest abgebrochen: %s", fehler)
        print(f"Selbsttest abgebrochen: {fehler}")
