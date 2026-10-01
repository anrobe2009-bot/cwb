"""
CWB - Code Workbench
Landkarte: wissen/landkarte.md je Projekt - eine Tabelle Datei/Zeilen/Zweck,
größte Datei zuerst. Claude Code schlägt sehr viel per Suche nach, obwohl eine
Suche rund 40 % teurer ist als reiner Volltext (core/grundlagen.py,
suche_ersparnis_prozent) - die Landkarte sagt auf einen Blick, welche Datei
wofür zuständig ist, ohne dass dafür erst gesucht werden muss. Bisher wurde
sie von Hand per Skript für einzelne Projekte angelegt; dieses Modul baut sie
automatisch beim Verbinden (core/sitzung.py, `_landkarte_anstossen`).

Reines Python ohne Qt, damit es im selben Hintergrund-Thread laufen kann, der
auch wissen.py bedient - anders als der Code-Index (index/indexer.py) braucht
das Zählen von Zeilen und das Lesen der ersten Kommentarzeile keine
ChromaDB/SentenceTransformer-Abhängigkeiten und keinen eigenen Prozess.

Zweck je Datei (Regel aus dem Auftrag, durch den bisherigen Handbestand von
wissen/landkarte.md bestätigt):
- Python: die ERSTE PHYSISCHE ZEILE des Moduldocstrings, also der Text, der
  unmittelbar auf die öffnenden Anführungszeichen folgt - steht dort nichts
  (weil die Anführungszeichen allein auf ihrer Zeile stehen, wie es die
  core/*.py-Kopfzeilen dieses Projekts tun), bleibt Zweck leer. Es wird NICHT
  in die nächste Zeile geschaut.
- Kotlin/Java/JS/TS/CSS/HTML/PS1/BAT: derselbe Grundsatz auf den ersten
  Kommentar am Dateianfang übertragen - bei einem Blockkommentar zählt nur,
  was nach dem öffnenden Zeichen auf derselben Zeile steht.
Alles andere (kein Docstring, kein Kommentar am Anfang, Lesefehler) bleibt
leer - absichtlich, nicht geraten.

Änderungserkennung wie beim Code-Index: ein Manifest aus Datei-Stat
(mtime+Größe) je Projekt im Datenordner (core/pfade.py, LANDKARTE_DATEN) -
neu geschrieben wird nur, wenn sich das Manifest gegenüber dem letzten Lauf
unterscheidet.
"""

import ast
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path

try:
    from .pfade import LANDKARTE_DATEN, log_einrichten
except ImportError:
    from pfade import LANDKARTE_DATEN, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.landkarte")

# Dateiendungen, fuer die die Zweck-Erkennung in diesem Modul eine Regel hat
# (Auftrag, Punkt 2). Alles andere taucht in der Landkarte nicht auf - sie
# soll Code zeigen, keine Daten-, Konfigurations- oder Dokumentationsdateien.
EXTENSIONS = {
    ".py",
    ".kt", ".kts", ".java",
    ".js", ".jsx", ".ts", ".tsx",
    ".css", ".html",
    ".ps1", ".bat",
}

# Ordnernamen, die nie durchsucht werden (Auftrag, Punkt 3).
SKIP_DIRS = {".git", "build", "node_modules", "__pycache__", ".gradle", ".cwb"}

# Testdateien je Sprache, anhand des Dateinamens erkannt.
_TEST_DATEI_MUSTER = re.compile(
    r"^test_.+\.py$"
    r"|^.+_test\.py$"
    r"|^.+\.(test|spec)\.(js|jsx|ts|tsx)$"
    r"|^test.*\.(java|kt|kts)$"
    r"|^.+tests?\.(java|kt|kts)$",
    re.IGNORECASE,
)

# Offensichtlich generierte Dateien, die trotz passender Endung nicht in die
# Landkarte gehoeren (Auftrag, Punkt 3: "generierte Dateien").
_GENERIERTE_DATEINAMEN = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}

# Dateien ueber dieser Groesse werden uebersprungen und geloggt statt
# vollstaendig eingelesen - Schutz vor einer versehentlichen Riesendatei mit
# einer der obigen Endungen (dieselbe Vorsicht wie index/indexer.py,
# MAX_FILE_SIZE, dort allerdings beim Indizieren selbst).
MAX_DATEIGROESSE = 5 * 1024 * 1024

LANDKARTE_HINWEIS = "Vor jeder Suche im Code zuerst wissen/landkarte.md lesen."
LANDKARTE_HINWEIS_BLOCK = (
    f"\n## Landkarte\n{LANDKARTE_HINWEIS} Neue Dateien dort mit einer Zeile eintragen.\n"
)


# ---------------------------------------------------------------------------
# Welche Dateien gehoeren in die Landkarte
# ---------------------------------------------------------------------------

def _ausgeschlossener_name(name: str) -> bool:
    klein = name.lower()
    if _TEST_DATEI_MUSTER.match(name):
        return True
    if ".bak" in klein:
        return True
    if "_vor_" in klein:
        return True
    if "patch_" in klein:
        return True
    if klein in _GENERIERTE_DATEINAMEN:
        return True
    if klein.endswith(".min.js") or klein.endswith(".min.css"):
        return True
    return False


def projekt_dateien(projekt_pfad: Path) -> list[Path]:
    """Alle Dateien im Projekt, die in die Landkarte gehoeren: passende
    Endung, nicht in einem ausgeschlossenen Ordner, kein ausgeschlossener
    Name."""
    ergebnis = []
    for pfad in projekt_pfad.rglob("*"):
        if pfad.suffix.lower() not in EXTENSIONS:
            continue
        if not pfad.is_file():
            continue
        try:
            relativ = pfad.relative_to(projekt_pfad)
        except ValueError:
            continue
        if any(teil in SKIP_DIRS for teil in relativ.parts[:-1]):
            continue
        if _ausgeschlossener_name(pfad.name):
            continue
        ergebnis.append(pfad)
    return ergebnis


# ---------------------------------------------------------------------------
# Zweck je Datei
# ---------------------------------------------------------------------------

def _python_zweck(text: str) -> str:
    try:
        baum = ast.parse(text)
    except SyntaxError:
        return ""
    # clean=False: der rohe Text zwischen den Anfuehrungszeichen, ohne dass
    # ast fuehrende Leerzeilen entfernt - genau diese Leerzeile, wenn die
    # Anfuehrungszeichen allein auf ihrer Zeile stehen, soll ja zu einem
    # leeren Zweck fuehren (siehe Moduldocstring oben).
    docstring = ast.get_docstring(baum, clean=False)
    if not docstring:
        return ""
    return docstring.split("\n", 1)[0].strip()


# (Oeffner, Schliesser) je Dateiendung, in Pruefreihenfolge - spezifischere
# Oeffner (z.B. "/**") muessen vor allgemeineren ("/*") stehen.
_KOMMENTARSTILE: dict[str, list[tuple[str, str | None]]] = {
    ".kt": [("/**", "*/"), ("/*", "*/"), ("//", None)],
    ".kts": [("/**", "*/"), ("/*", "*/"), ("//", None)],
    ".java": [("/**", "*/"), ("/*", "*/"), ("//", None)],
    ".js": [("/**", "*/"), ("/*", "*/"), ("//", None)],
    ".jsx": [("/**", "*/"), ("/*", "*/"), ("//", None)],
    ".ts": [("/**", "*/"), ("/*", "*/"), ("//", None)],
    ".tsx": [("/**", "*/"), ("/*", "*/"), ("//", None)],
    ".css": [("/*", "*/")],
    ".html": [("<!--", "-->")],
    ".ps1": [("<#", "#>"), ("#", None)],
    ".bat": [("::", None), ("rem ", None), ("rem", None)],
}


def _kommentar_zweck(text: str, suffix: str) -> str:
    """Erste Zeile des ersten Kommentars am Dateianfang (Auftrag, Punkt 2).
    Fuehrende Leerzeilen werden uebersprungen; ist die erste nicht-leere
    Zeile kein bekannter Kommentar-Oeffner, bleibt der Zweck leer - es wird
    nicht tiefer in die Datei geschaut."""
    stile = _KOMMENTARSTILE.get(suffix)
    if not stile:
        return ""
    for zeile in text.lstrip("﻿").splitlines():
        kandidat = zeile.strip()
        if not kandidat:
            continue
        vergleich = kandidat.lower() if suffix == ".bat" else kandidat
        for oeffner, schliesser in stile:
            pruefwert = oeffner.lower() if suffix == ".bat" else oeffner
            if not vergleich.startswith(pruefwert):
                continue
            rest = kandidat[len(oeffner):]
            if schliesser and schliesser in rest:
                rest = rest[:rest.index(schliesser)]
            return rest.strip(" \t*").strip()
        return ""
    return ""


def zweck_ermitteln(text: str, suffix: str) -> str:
    if suffix == ".py":
        return _python_zweck(text)
    return _kommentar_zweck(text, suffix)


# ---------------------------------------------------------------------------
# Änderungserkennung (Manifest aus Datei-Stat, wie index/indexer.py)
# ---------------------------------------------------------------------------

def _projekt_schluessel(projekt_pfad: Path) -> str:
    normalisiert = str(projekt_pfad.resolve())
    return "lk_" + hashlib.md5(normalisiert.encode()).hexdigest()[:12]


def _manifest_pfad(projekt_pfad: Path) -> Path:
    return LANDKARTE_DATEN / f"{_projekt_schluessel(projekt_pfad)}.json"


def _manifest_laden(projekt_pfad: Path) -> dict:
    try:
        return json.loads(_manifest_pfad(projekt_pfad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _manifest_speichern(projekt_pfad: Path, manifest: dict) -> None:
    try:
        LANDKARTE_DATEN.mkdir(parents=True, exist_ok=True)
        _manifest_pfad(projekt_pfad).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as fehler:
        log.error("Landkarte-Manifest nicht schreibbar fuer %s: %s", projekt_pfad, fehler)


def _manifest_aus_dateien(projekt_pfad: Path, dateien: list[Path]) -> dict:
    manifest = {}
    for pfad in dateien:
        try:
            stat = pfad.stat()
        except OSError:
            continue
        manifest[str(pfad.relative_to(projekt_pfad))] = [stat.st_mtime, stat.st_size]
    return manifest


# ---------------------------------------------------------------------------
# Landkarte schreiben
# ---------------------------------------------------------------------------

def _zeile_sicher(text: str) -> str:
    """Macht einen Zweck-Text tabellensicher: kein Zeilenumbruch, kein
    Pipe-Zeichen, das die Markdown-Tabelle zerreissen wuerde."""
    return " ".join(text.split()).replace("|", "/")


def _tabellenzeilen(projekt_pfad: Path, dateien: list[Path]) -> list[tuple[str, int, str]]:
    zeilen = []
    for pfad in dateien:
        try:
            groesse = pfad.stat().st_size
        except OSError as fehler:
            log.warning("Landkarte: Datei nicht lesbar, übersprungen: %s (%s)", pfad, fehler)
            continue
        if groesse > MAX_DATEIGROESSE:
            log.warning("Landkarte: übersprungen (zu groß, %d Bytes): %s", groesse, pfad)
            continue
        try:
            text = pfad.read_text(encoding="utf-8", errors="ignore")
        except OSError as fehler:
            log.warning("Landkarte: Datei nicht lesbar, übersprungen: %s (%s)", pfad, fehler)
            continue
        anzahl = len(text.splitlines())
        zweck = _zeile_sicher(zweck_ermitteln(text, pfad.suffix.lower()))
        relativ = str(pfad.relative_to(projekt_pfad))
        zeilen.append((relativ, anzahl, zweck))
    zeilen.sort(key=lambda z: z[1], reverse=True)
    return zeilen


def _landkarte_schreiben(ziel: Path, projekt_name: str,
                          zeilen: list[tuple[str, int, str]]) -> None:
    zeitstempel = datetime.now().strftime("%d.%m.%Y %H:%M")
    teile = [
        f"# Landkarte von {projekt_name}",
        "",
        f"Automatisch erzeugt am {zeitstempel}.",
        "",
        "| Datei | Zeilen | Zweck |",
        "|---|---|---|",
    ]
    for relativ, anzahl, zweck in zeilen:
        teile.append(f"| {relativ} | {anzahl} | {zweck} |")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text("\n".join(teile) + "\n", encoding="utf-8")


def landkarte_erzeugen(projekt_pfad: Path, projekt_name: str) -> bool:
    """Erzeugt oder aktualisiert wissen/landkarte.md im Projekt, aber nur,
    wenn sich seit dem letzten Lauf Dateien geändert haben. Läuft nie laut:
    jeder Fehler landet ausschließlich im Log, nichts wird angesagt oder ins
    Ausgabefeld geschrieben - das ist Sache des Aufrufers (core/sitzung.py),
    der diese Funktion in einem eigenen Hintergrund-Thread aufruft.

    Rückgabe: ob tatsächlich geschrieben wurde (für Tests und Log-Zeilen des
    Aufrufers; die laufende CWB-Oberfläche fragt das nicht ab)."""
    projekt_pfad = Path(projekt_pfad)
    try:
        dateien = projekt_dateien(projekt_pfad)
        manifest_neu = _manifest_aus_dateien(projekt_pfad, dateien)
        # Nur ueberspringen, wenn es schon einen frueheren Lauf gab UND der
        # unveraendert ist - sonst wuerde ein Projekt ganz ohne passende
        # Dateien beim allerersten Lauf nie eine (dann leere) landkarte.md
        # bekommen, weil {} == {} auch ohne Vorlauf wahr waere.
        if _manifest_pfad(projekt_pfad).is_file() and manifest_neu == _manifest_laden(projekt_pfad):
            return False
        zeilen = _tabellenzeilen(projekt_pfad, dateien)
        _landkarte_schreiben(projekt_pfad / "wissen" / "landkarte.md", projekt_name, zeilen)
        _manifest_speichern(projekt_pfad, manifest_neu)
        log.info("Landkarte aktualisiert für %s: %d Dateien", projekt_name, len(zeilen))
        return True
    except Exception as fehler:  # noqa: BLE001
        log.exception("Landkarte für %s nicht erzeugt: %s", projekt_name, fehler)
        return False


# ---------------------------------------------------------------------------
# Hinweis in CLAUDE.md
# ---------------------------------------------------------------------------

def claude_md_hinweis_sicherstellen(projekt_pfad: Path) -> bool:
    """Sorgt dafür, dass CLAUDE.md im Projekt den Hinweis auf die Landkarte
    enthält - sowohl für eine von CWB frisch angelegte Datei (core/wissen.py,
    Wissen.einrichten) als auch für eine bereits bestehende CLAUDE.md eines
    Zusatzprojekts, die nur ergänzt, nie sonst verändert wird. Fehlt die
    Datei ganz, geschieht hier nichts - das Anlegen selbst ist Sache von
    Wissen.einrichten(), diese Funktion läuft danach.

    Rückgabe: ob tatsächlich geschrieben wurde."""
    pfad = Path(projekt_pfad) / "CLAUDE.md"
    try:
        if not pfad.is_file():
            return False
        text = pfad.read_text(encoding="utf-8")
    except OSError as fehler:
        log.error("CLAUDE.md nicht lesbar für Landkarte-Hinweis: %s (%s)", pfad, fehler)
        return False
    if LANDKARTE_HINWEIS in text:
        return False
    try:
        pfad.write_text(text.rstrip("\n") + "\n" + LANDKARTE_HINWEIS_BLOCK, encoding="utf-8")
        log.info("Landkarte-Hinweis in CLAUDE.md ergänzt: %s", pfad)
        return True
    except OSError as fehler:
        log.error("CLAUDE.md nicht schreibbar für Landkarte-Hinweis: %s (%s)", pfad, fehler)
        return False
