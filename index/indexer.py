# indexer.py — ChromaDB-Indexer, Teil von CWB (core/sitzung.py ruft ueber cli.py)
import hashlib
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Dict, List, Optional

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

try:
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
except ImportError:
    raise SystemExit("chromadb nicht installiert. Bitte: pip install -r requirements.txt")

WURZEL = Path(__file__).resolve().parent
LOG_DATEI = WURZEL / "index_fehler.log"
LOG_GROESSE = 500 * 1024
LOG_SICHERUNGEN = 3
LOG_FORM = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def log_einrichten() -> None:
    """Haengt den rotierenden Schreiber einmalig an den Wurzel-Logger.
    Zweiter und jeder weitere Aufruf tut nichts (Musterparallele zu CWB core/pfade.py)."""
    wurzel = logging.getLogger()
    for vorhanden in wurzel.handlers:
        if getattr(vorhanden, "_ci_log", False):
            return
    schreiber = RotatingFileHandler(
        str(LOG_DATEI),
        maxBytes=LOG_GROESSE,
        backupCount=LOG_SICHERUNGEN,
        encoding="utf-8",
    )
    schreiber.setFormatter(logging.Formatter(LOG_FORM))
    schreiber._ci_log = True
    wurzel.addHandler(schreiber)
    wurzel.setLevel(logging.INFO)


log_einrichten()
log = logging.getLogger("cwb.index.indexer")

CHUNK_SIZE    = 800
CHUNK_OVERLAP = 100

# Sicherheitsdeckel gegen versehentliche Riesendateien (Logs, generierte
# HTML-Reports). Deutlich ueber den groessten bekannten Quelldateien - wer
# trotzdem drueber liegt, wird uebersprungen und geloggt statt stillschweigend
# zu fehlen.
MAX_FILE_SIZE = 2 * 1024 * 1024

# all-MiniLM-L6-v2: leicht (~80 MB), schnell, kein ONNX, kein optimum-Paket noetig,
# rechnet lokal ohne API-Schluessel.
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".scss", ".qss",
    ".json", ".yaml", ".yml", ".xml", ".properties",
    ".txt", ".bat", ".sh", ".ps1", ".conf", ".ini",
    ".java", ".kt", ".kts", ".cpp", ".c", ".h", ".cs", ".go", ".rs",
}

SKIP_DIRS = {
    "chroma_db", "__pycache__", ".git", "node_modules",
    ".venv", "venv", "env", "dist", "build",
    ".next", "bin", "obj", ".tox", ".mypy_cache", ".pytest_cache",
    "target", ".idea", ".vs", ".vscode", ".gradle", "gradle", ".kotlin",
    "graphify-out", ".codegraph",
    ".cwb", ".ablage", ".stimmen", ".toene", ".git_alt", "_backup", "sicherung",
}

_CHROMA_DIR = WURZEL / "chroma_db"
_MANIFEST_DIR = WURZEL / "manifeste"
_LOCK_DATEI = WURZEL / ".sperre"

# Ein echter Lauf dauert auch bei einem grossen Projekt selten laenger als
# eine halbe Stunde. Eine aeltere Sperre ist der Rest eines abgestuerzten
# oder gekillten Laufs, keine echte Nebenlaeufigkeit mehr.
LOCK_ALTER_MAX = 60 * 60


def _manifest_pfad(project_path: str) -> Path:
    return _MANIFEST_DIR / f"{_safe_name(project_path)}.json"


def _manifest_laden(project_path: str) -> Dict[str, list]:
    try:
        return json.loads(_manifest_pfad(project_path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _manifest_speichern(project_path: str, manifest: Dict[str, list]) -> None:
    try:
        _MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        _manifest_pfad(project_path).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.error("Manifest nicht schreibbar fuer %s: %s", project_path, e)


def _manifest_aus_liste(project_path: str, dateien: List[Path]) -> Dict[str, list]:
    p = Path(project_path)
    manifest = {}
    for f in dateien:
        try:
            st = f.stat()
        except OSError:
            continue
        manifest[str(f.relative_to(p))] = [st.st_mtime, st.st_size]
    return manifest


def gesperrt() -> bool:
    """True, wenn gerade ein anderer Prozess in die Datenbank schreibt (oder
    das zumindest zuletzt vor weniger als LOCK_ALTER_MAX getan hat). Zwei
    gleichzeitige Schreiber haben schon einmal die HNSW-Segmente einer
    Sammlung unbrauchbar gemacht - seitdem meidet auch die Suche diesen Fall,
    statt eine kryptische ChromaDB-Fehlermeldung durchzureichen."""
    try:
        return time.time() - _LOCK_DATEI.stat().st_mtime < LOCK_ALTER_MAX
    except OSError:
        return False


@contextmanager
def _schreibsperre():
    """Sorgt dafuer, dass immer nur ein Prozess in die Datenbank schreibt.
    Ist schon eine frische Sperre da, wird nicht gewartet: der Aufrufer soll
    es beim naechsten Sitzungsstart oder manuell erneut versuchen, statt eine
    zweite gleichzeitige Schreibsitzung zu riskieren."""
    if gesperrt():
        yield False
        return
    try:
        _LOCK_DATEI.write_text(str(os.getpid()), encoding="utf-8")
    except OSError as e:
        log.error("Sperre nicht schreibbar, mache trotzdem weiter: %s", e)
        yield True
        return
    try:
        yield True
    finally:
        try:
            _LOCK_DATEI.unlink(missing_ok=True)
        except OSError:
            pass


def _embedding_fn():
    return SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        trust_remote_code=False,
    )


def _safe_name(project_path: str) -> str:
    # Normalisieren, damit derselbe Projektpfad mit Schraegstrich/Backslash oder
    # abschliessendem Trenner nicht zwei getrennte Sammlungen erzeugt.
    try:
        normalized = str(Path(project_path).resolve())
    except Exception:
        normalized = str(project_path)
    return "ci_" + hashlib.md5(normalized.encode()).hexdigest()[:12]


def get_collection(project_path: str):
    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
    return client.get_or_create_collection(
        name=_safe_name(project_path),
        embedding_function=_embedding_fn(),
        metadata={"hnsw:space": "cosine"},
    )


def should_index(path: Path) -> bool:
    if path.suffix.lower() == ".md":
        return False
    for part in path.parts:
        if part in SKIP_DIRS:
            return False
    name = path.name
    if name.startswith("backup_") or name.startswith("fix_"):
        return False
    if re.match(r"^bak\d*$", path.suffix.lstrip(".").lower()):
        return False
    if re.search(r"_backup_\d{6,}", name.lower()):
        return False
    return path.suffix.lower() in EXTENSIONS


def _chunk_text(text: str) -> List[tuple]:
    """Liefert (start_char, text) je Stueck - der Zeichen-Offset wird
    gebraucht, um beim Suchen Zeilennummern zu berechnen."""
    if not text.strip():
        return []
    chunks, start = [], 0
    while start < len(text):
        chunk = text[start: start + CHUNK_SIZE]
        if chunk.strip():
            chunks.append((start, chunk))
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def _chunk_id(file_path: str, idx: int) -> str:
    return hashlib.md5(f"{file_path}::{idx}".encode()).hexdigest()


def index_file(collection, file_path: Path, log_fn: Optional[Callable] = None) -> int:
    try:
        groesse = file_path.stat().st_size
    except OSError as e:
        log.error("Nicht lesbar: %s: %s", file_path, e)
        if log_fn:
            log_fn(f"[FEHLER] {file_path.name}: {e}")
        return 0

    if groesse > MAX_FILE_SIZE:
        log.warning("Uebersprungen (zu gross, %d Bytes > Limit %d): %s",
                    groesse, MAX_FILE_SIZE, file_path)
        if log_fn:
            log_fn(f"[UEBERSPRUNGEN, zu gross: {groesse / 1024:.0f} KB] {file_path.name}")
        return 0

    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        log.error("Lesen fehlgeschlagen: %s: %s", file_path, e)
        if log_fn:
            log_fn(f"[FEHLER] {file_path.name}: {e}")
        return 0

    try:
        old = collection.get(where={"source": str(file_path)})
        if old["ids"]:
            collection.delete(ids=old["ids"])
    except Exception:
        pass

    chunks = _chunk_text(text)
    if not chunks:
        return 0

    ids   = [_chunk_id(str(file_path), i) for i in range(len(chunks))]
    docs  = [chunk for _, chunk in chunks]
    metas = [
        {"source": str(file_path), "chunk_idx": i,
         "start_char": start, "end_char": start + len(chunk),
         "file_name": file_path.name, "chunk_type": "source"}
        for i, (start, chunk) in enumerate(chunks)
    ]

    for i in range(0, len(docs), 100):
        collection.add(
            ids=ids[i: i + 100],
            documents=docs[i: i + 100],
            metadatas=metas[i: i + 100],
        )
    return len(docs)


def remove_file(collection, file_path: Path) -> None:
    try:
        old = collection.get(where={"source": str(file_path)})
        if old["ids"]:
            collection.delete(ids=old["ids"])
    except Exception:
        pass


def index_changed(project_path: str, changed_files: List[str], removed_files: List[str],
                   log_fn: Optional[Callable] = None) -> Dict:
    p = Path(project_path)
    if not p.is_dir():
        return {"files": 0, "chunks": 0, "skipped": 0, "removed": 0,
                "error": "Pfad nicht gefunden"}

    collection = get_collection(project_path)
    stats      = {"files": 0, "chunks": 0, "skipped": 0, "removed": 0}

    for rel in removed_files:
        remove_file(collection, p / rel)
        stats["removed"] += 1
        if log_fn:
            log_fn(f"  [entfernt] {rel}")

    total = len(changed_files)
    for i, rel in enumerate(changed_files, 1):
        fpath = p / rel
        if not fpath.is_file() or not should_index(fpath):
            stats["skipped"] += 1
            continue
        n = index_file(collection, fpath, log_fn)
        if n > 0:
            stats["files"]  += 1
            stats["chunks"] += n
            if log_fn:
                log_fn(f"  [{i}/{total}] {rel} ({n} Chunks)")
        else:
            stats["skipped"] += 1

    if log_fn:
        log_fn(f"Fertig: {stats['files']} Dateien, {stats['chunks']} Chunks, "
               f"{stats['removed']} entfernt, {stats['skipped']} uebersprungen")
    log.info("index_changed %s: %s", p, stats)
    return stats


def index_aktualisieren(project_path: str, log_fn: Optional[Callable] = None,
                         voll: bool = False) -> Dict:
    """Der einzige Weg, ein Projekt zu indizieren - fuer den allerersten Lauf
    genauso wie fuer den taeglichen Sitzungsstart. Vergleicht Aenderungszeit
    und Groesse jeder Datei gegen das Manifest vom letzten Lauf (reines
    Datei-Stat, kein Lesen, kein Modell); gibt es noch kein Manifest, gilt
    automatisch jede Datei als neu - das IST dann der Erstindex, ohne
    Sonderfall. `voll=True` erzwingt das (ignoriert ein vorhandenes Manifest),
    z.B. nach einer Aenderung an Chunking oder Dateifiltern.

    Schreibt niemals gleichzeitig mit einem zweiten Lauf (siehe
    _schreibsperre) - ein abgebrochener Schreibvorgang beschaedigt sonst die
    HNSW-Segmente der Sammlung dauerhaft, das hat hausgemacht schon einmal
    getroffen."""
    p = Path(project_path)
    if not p.is_dir():
        return {"files": 0, "chunks": 0, "skipped": 0, "removed": 0, "error": "Pfad nicht gefunden"}

    with _schreibsperre() as erhalten:
        if not erhalten:
            log.warning("index_aktualisieren %s: Sperre aktiv, uebersprungen", p)
            return {"files": 0, "chunks": 0, "skipped": 0, "removed": 0,
                    "uebersprungen_grund": "gesperrt"}

        altes_manifest = {} if voll else _manifest_laden(project_path)
        aktuelle_dateien = [f for f in p.rglob("*") if f.is_file() and should_index(f)]
        neues_manifest = _manifest_aus_liste(project_path, aktuelle_dateien)

        geaendert = [rel for rel, stempel in neues_manifest.items()
                     if altes_manifest.get(rel) != stempel]
        entfernt = [rel for rel in altes_manifest if rel not in neues_manifest]

        if not geaendert and not entfernt:
            log.info("index_aktualisieren %s: keine Aenderungen (%d Dateien geprueft)",
                      p, len(aktuelle_dateien))
            return {"files": 0, "chunks": 0, "skipped": 0, "removed": 0,
                    "geprueft": len(aktuelle_dateien)}

        if log_fn:
            log_fn(f"Indiziere {p}: {len(geaendert)} geaendert/neu, {len(entfernt)} entfernt")
        stats = index_changed(project_path, geaendert, entfernt, log_fn)
        _manifest_speichern(project_path, neues_manifest)
        stats["geprueft"] = len(aktuelle_dateien)
        log.info("index_aktualisieren %s: %s", p, stats)
        return stats


def get_collection_stats(project_path: str) -> Dict:
    if not project_path or not Path(project_path).is_dir():
        return {"chunks": 0}
    try:
        col = get_collection(project_path)
        return {"chunks": col.count()}
    except Exception as e:
        log.error("Stats fehlgeschlagen fuer %s: %s", project_path, e)
        return {"chunks": 0}


def _zeilen_bereich(source: str, start_char: Optional[int], end_char: Optional[int]) -> Optional[tuple]:
    """Rechnet Zeichen-Offsets in Zeilennummern um, indem die Quelldatei neu
    gelesen wird. Liefert None, wenn Metadaten fehlen (aeltere Sammlung vor
    dem start_char-Feld) oder die Datei nicht mehr lesbar ist."""
    if start_char is None or end_char is None:
        return None
    try:
        text = Path(source).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    von = text.count("\n", 0, start_char) + 1
    bis = text.count("\n", 0, min(end_char, len(text))) + 1
    return von, bis


def search(project_path: str, query: str, n_results: int = 5) -> List[Dict]:
    """Semantische Suche in der Sammlung eines Projekts - Grundlage fuer den
    MCP-Server: Frage rein, passendste Codestellen mit Zeilennummern raus."""
    if gesperrt():
        log.warning("search %s: Datenbank gerade gesperrt (laufender Indexlauf)", project_path)
        return []
    col = get_collection(project_path)
    if col.count() == 0:
        return []
    try:
        result = col.query(query_texts=[query], n_results=min(n_results, col.count()))
    except Exception as e:
        log.error("Suche fehlgeschlagen fuer %s: %s", project_path, e)
        return []

    treffer = []
    docs  = result.get("documents",  [[]])[0]
    metas = result.get("metadatas",  [[]])[0]
    dists = result.get("distances",  [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        source = meta.get("source")
        zeilen = _zeilen_bereich(source, meta.get("start_char"), meta.get("end_char"))
        treffer.append({
            "source": source,
            "chunk_idx": meta.get("chunk_idx"),
            "zeile_von": zeilen[0] if zeilen else None,
            "zeile_bis": zeilen[1] if zeilen else None,
            "text": doc,
            "distanz": dist,
        })
    return treffer
