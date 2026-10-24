# FILE: bruecke/server.py
"""MCP-Dienst "cwb-bruecke": Warteschlange fuer Auftraege und Berichte
zwischen claude.ai (MCP-Connector) und CWB auf Roberts PC.
Siehe wissen/plan_bruecke.md (Stufe B2) im Projekt max-friends.
"""
import datetime
import logging
import os
import re
import sqlite3
from typing import Optional

from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

import ablage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bruecke")

SECRET_PATH = os.environ["BRUECKE_SECRET_PATH"]
PC_TOKEN = os.environ["BRUECKE_PC_TOKEN"]
BASIS = f"/{SECRET_PATH}"
DB_PFAD = os.environ.get("BRUECKE_DB_PFAD", "/data/bruecke.db")
ERLAUBTE_ARTEN = {"CODE", "RUN", "BILD"}
MAX_GROESSE = 100_000  # 100 KB, siehe Auftrag Stufe B2
# Ohne Quittung (POST /quittung) gilt ein ausgelieferter Auftrag nach dieser
# Zeit als verloren gegangen und wird beim naechsten GET /abholen erneut
# ausgeliefert - CWB erkennt eine erneute Auslieferung an der gleich
# bleibenden Auftragsnummer und legt sie nicht doppelt ab (core/bruecke.py).
QUITTUNG_SCHWELLE_SEKUNDEN = 60


def _verbindung() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PFAD)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _verbindung() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS auftraege (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                projekt TEXT,
                art TEXT NOT NULL,
                text TEXT NOT NULL,
                erstellt_am TEXT NOT NULL,
                abgeholt INTEGER NOT NULL DEFAULT 0,
                abgeholt_am TEXT,
                unterwegs_seit TEXT
            )"""
        )
        # Nachtrag fuer Datenbanken aus der Zeit vor der Quittung (Stufe B4):
        # CREATE TABLE IF NOT EXISTS legt die Spalte bei einer bestehenden
        # Tabelle nicht nach, ALTER TABLE ADD COLUMN scheitert dagegen
        # erwartungsgemaess, wenn sie schon existiert.
        try:
            conn.execute("ALTER TABLE auftraege ADD COLUMN unterwegs_seit TEXT")
        except sqlite3.OperationalError:
            pass
        conn.execute(
            """CREATE TABLE IF NOT EXISTS berichte (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auftrag_id INTEGER,
                text TEXT NOT NULL,
                erstellt_am TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS letzter_abruf (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                zeitpunkt TEXT
            )"""
        )


_init_db()
ablage.init(DB_PFAD)

mcp = MCPServer("cwb-bruecke")


@mcp.tool()
def auftrag_senden(projekt: str, art: str, text: str) -> str:
    """Legt einen Auftrag fuer CWB in die Warteschlange. art ist CODE, RUN oder BILD."""
    art_norm = art.strip().upper()
    if art_norm not in ERLAUBTE_ARTEN:
        logger.warning("auftrag_senden abgelehnt: art=%s", art_norm)
        raise ValueError("Nur CODE, RUN oder BILD sind ueber die Bruecke erlaubt. ADMIN ist gesperrt.")
    groesse = len(text.encode("utf-8"))
    if groesse > MAX_GROESSE:
        logger.warning("auftrag_senden abgelehnt: zu gross (%d Bytes)", groesse)
        raise ValueError(f"Auftrag zu gross ({groesse} Bytes, erlaubt sind {MAX_GROESSE}).")
    jetzt = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _verbindung() as conn:
        cur = conn.execute(
            "INSERT INTO auftraege (projekt, art, text, erstellt_am) VALUES (?, ?, ?, ?)",
            (projekt or None, art_norm, text, jetzt),
        )
        nummer = cur.lastrowid
    logger.info("Auftrag %d gespeichert (art=%s, projekt=%s)", nummer, art_norm, projekt)
    return f"Auftrag Nummer {nummer} gespeichert."


_BLOCK_MUSTER = re.compile(r"^#?\s*Block\s+(\d+)\b", re.IGNORECASE | re.MULTILINE)


# Von CWB (core/bruecke.py, KENNZEILE_MUSTER) als erste Zeile in den Bericht
# geschrieben; dann setzt der Server keine eigene davor.
_KENN_MUSTER = re.compile(r"^Auftrag \d+ \| Block (?:\d+|-) \| Zeit \S.*$")


def _block_nummer(auftrag_text: Optional[str]) -> str:
    """Blocknummer aus dem Auftragstext ("Block 729"), sonst "-"."""
    treffer = _BLOCK_MUSTER.search(auftrag_text or "")
    return treffer.group(1) if treffer else "-"


def _bericht_lesen(auftrag_nummer: Optional[int] = None) -> str:
    """Kern von bericht_holen. Erste Zeile ist immer die Kennung
    "Auftrag N | Block B | Zeit T"; ohne Bericht zu genau dieser Nummer
    (bzw. ohne jeden nummerierten Bericht) bleibt es bei "noch nicht fertig"."""
    with _verbindung() as conn:
        if auftrag_nummer is not None:
            zeile = conn.execute(
                "SELECT auftrag_id, text, erstellt_am FROM berichte "
                "WHERE auftrag_id = ? ORDER BY id DESC LIMIT 1",
                (auftrag_nummer,),
            ).fetchone()
        else:
            zeile = conn.execute(
                "SELECT auftrag_id, text, erstellt_am FROM berichte "
                "WHERE auftrag_id IS NOT NULL ORDER BY auftrag_id DESC, id DESC LIMIT 1"
            ).fetchone()
        if zeile is None:
            return "noch nicht fertig"
        auftrag = conn.execute(
            "SELECT text FROM auftraege WHERE id = ?", (zeile["auftrag_id"],)
        ).fetchone()
    if _KENN_MUSTER.match(zeile["text"].split("\n", 1)[0].rstrip("\r")):
        return zeile["text"]
    block = _block_nummer(auftrag["text"] if auftrag else None)
    return f"Auftrag {zeile['auftrag_id']} | Block {block} | Zeit {zeile['erstellt_am']}\n{zeile['text']}"


@mcp.tool()
def bericht_holen(auftrag_nummer: Optional[int] = None) -> str:
    """Gibt den Bericht samt Kennzeile "Auftrag N | Block B | Zeit T" zurueck
    (hat CWB sie schon in den Text geschrieben, wird sie nicht verdoppelt).
    Ohne Nummer den Bericht des hoechsten Auftrags (bei Gleichstand der juengste
    Upload), Hinweise ohne Auftragsnummer zaehlen nicht. Mit Nummer nur den
    letzten Bericht genau dieser Auftragsnummer, sonst "noch nicht fertig"."""
    return _bericht_lesen(auftrag_nummer)


@mcp.tool()
def protokolle_liste(anzahl: int = 20, projekt: Optional[str] = None,
                     art: Optional[str] = None, seit: Optional[str] = None) -> str:
    """Kurze Uebersicht der Protokolle im Ablagefach, neueste zuerst, je Eintrag
    eine Zeile (Nummer, Zeit, Auftragsnummer, Projekt, Art, Titel, Laenge in
    Zeichen), ohne Volltext. art: bericht, hinweis, fehler, build oder journal.
    seit: ISO-Zeitpunkt oder kurz 30m, 2h, 3d."""
    return ablage.liste(DB_PFAD, anzahl=anzahl, projekt=projekt, art=art, seit=seit)


@mcp.tool()
def protokoll_lesen(nummer: int, von: int = 0, bis: Optional[int] = None) -> str:
    """Volltext eines Protokolls. von/bis sind Zeichenpositionen; ohne bis
    kommen hoechstens 20000 Zeichen, der Kopf nennt, wo es weitergeht."""
    return ablage.lesen(DB_PFAD, nummer, von=von, bis=bis)


@mcp.tool()
def protokoll_ablegen(text: str, art: str = "hinweis", projekt: Optional[str] = None,
                      auftrag_nummer: Optional[int] = None, titel: Optional[str] = None) -> str:
    """Legt einen Eintrag ins Ablagefach (art: bericht, hinweis, fehler, build
    oder journal), auch ohne Auftragsnummer. Nichts wird ueberschrieben."""
    nummer = ablage.ablegen(DB_PFAD, text, art=art, projekt=projekt,
                            auftrag_nummer=auftrag_nummer, titel=titel)
    return f"Protokoll Nummer {nummer} abgelegt."


@mcp.tool()
def status() -> str:
    """Meldet, ob CWB in den letzten 30 Sekunden abgefragt hat und wie viele Auftraege warten."""
    with _verbindung() as conn:
        zeile = conn.execute("SELECT zeitpunkt FROM letzter_abruf WHERE id = 1").fetchone()
        wartend = conn.execute("SELECT COUNT(*) AS n FROM auftraege WHERE abgeholt = 0").fetchone()["n"]
    aktiv = False
    if zeile and zeile["zeitpunkt"]:
        letzter = datetime.datetime.fromisoformat(zeile["zeitpunkt"])
        aktiv = (datetime.datetime.now(datetime.timezone.utc) - letzter).total_seconds() <= 30
    zustand = "in den letzten 30 Sekunden" if aktiv else "seit mehr als 30 Sekunden nicht mehr"
    return f"CWB hat {zustand} abgefragt. {wartend} Auftrag/Auftraege warten."


def _token_gueltig(request: Request) -> bool:
    return request.headers.get("X-PC-Token") == PC_TOKEN


@mcp.custom_route(f"{BASIS}/abholen", methods=["GET"], include_in_schema=False)
async def cwb_abholen(request: Request) -> JSONResponse:
    """Liefert einen wartenden Auftrag aus und markiert ihn als "unterwegs",
    aber noch nicht als endgueltig abgeholt - das geschieht erst durch
    POST /quittung (Stufe B4). Ein Auftrag, der laenger als
    QUITTUNG_SCHWELLE_SEKUNDEN unterwegs ist, ohne quittiert worden zu sein,
    gilt wieder als wartend und wird erneut ausgeliefert; CWB erkennt die
    Wiederholung an der gleichbleibenden Auftragsnummer."""
    if not _token_gueltig(request):
        logger.warning("abholen: ungueltiges oder fehlendes Token")
        return JSONResponse({"fehler": "nicht autorisiert"}, status_code=401)
    jetzt_dt = datetime.datetime.now(datetime.timezone.utc)
    jetzt = jetzt_dt.isoformat()
    schwelle = (jetzt_dt - datetime.timedelta(seconds=QUITTUNG_SCHWELLE_SEKUNDEN)).isoformat()
    with _verbindung() as conn:
        conn.execute(
            "INSERT INTO letzter_abruf (id, zeitpunkt) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET zeitpunkt = excluded.zeitpunkt",
            (jetzt,),
        )
        zeile = conn.execute(
            "SELECT id, projekt, art, text, erstellt_am FROM auftraege "
            "WHERE abgeholt = 0 AND (unterwegs_seit IS NULL OR unterwegs_seit < ?) "
            "ORDER BY id ASC LIMIT 1",
            (schwelle,),
        ).fetchone()
        if zeile is None:
            return JSONResponse({"auftrag": None})
        conn.execute(
            "UPDATE auftraege SET unterwegs_seit = ? WHERE id = ?",
            (jetzt, zeile["id"]),
        )
    logger.info("Auftrag %d an CWB ausgeliefert (unterwegs, Quittung ausstehend)", zeile["id"])
    return JSONResponse(
        {
            "auftrag": {
                "nummer": zeile["id"],
                "projekt": zeile["projekt"],
                "art": zeile["art"],
                "text": zeile["text"],
                "erstellt_am": zeile["erstellt_am"],
            }
        }
    )


@mcp.custom_route(f"{BASIS}/quittung", methods=["POST"], include_in_schema=False)
async def cwb_quittung(request: Request) -> JSONResponse:
    """CWB bestaetigt, dass ein Auftrag erfolgreich im Eingangsordner liegt
    (Stufe B4) - erst danach gilt er endgueltig als abgeholt und wird nicht
    mehr erneut ausgeliefert."""
    if not _token_gueltig(request):
        logger.warning("quittung: ungueltiges oder fehlendes Token")
        return JSONResponse({"fehler": "nicht autorisiert"}, status_code=401)
    try:
        daten = await request.json()
    except Exception:
        return JSONResponse({"fehler": "kein gueltiges JSON"}, status_code=400)
    auftrag_nummer = daten.get("auftrag_nummer")
    if auftrag_nummer is None:
        return JSONResponse({"fehler": "auftrag_nummer fehlt"}, status_code=400)
    jetzt = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _verbindung() as conn:
        conn.execute(
            "UPDATE auftraege SET abgeholt = 1, abgeholt_am = ? WHERE id = ?",
            (jetzt, auftrag_nummer),
        )
    logger.info("Auftrag %s quittiert", auftrag_nummer)
    return JSONResponse({"ok": True})


@mcp.custom_route(f"{BASIS}/bericht", methods=["POST"], include_in_schema=False)
async def bericht_hochladen(request: Request) -> JSONResponse:
    if not _token_gueltig(request):
        logger.warning("bericht_hochladen: ungueltiges oder fehlendes Token")
        return JSONResponse({"fehler": "nicht autorisiert"}, status_code=401)
    rohdaten = await request.body()
    if len(rohdaten) > MAX_GROESSE:
        return JSONResponse({"fehler": "zu gross"}, status_code=413)
    try:
        daten = await request.json()
    except Exception:
        return JSONResponse({"fehler": "kein gueltiges JSON"}, status_code=400)
    text = daten.get("text") or ""
    auftrag_nummer = daten.get("auftrag_nummer")
    if not text:
        return JSONResponse({"fehler": "text fehlt"}, status_code=400)
    jetzt = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _verbindung() as conn:
        conn.execute(
            "INSERT INTO berichte (auftrag_id, text, erstellt_am) VALUES (?, ?, ?)",
            (auftrag_nummer, text, jetzt),
        )
    logger.info("Bericht fuer Auftrag %s gespeichert", auftrag_nummer)
    # Zusaetzlich ins Ablagefach: dort wird nie ueberschrieben, und die KI
    # findet den Bericht ueber protokolle_liste. Ein Fehler hier darf den
    # Upload nicht scheitern lassen (berichte hat ihn ja schon).
    try:
        projekt = None
        if auftrag_nummer is not None:
            with _verbindung() as conn:
                zeile = conn.execute(
                    "SELECT projekt FROM auftraege WHERE id = ?", (auftrag_nummer,)
                ).fetchone()
            projekt = zeile["projekt"] if zeile else None
        titel = f"Bericht Auftrag {auftrag_nummer}" if auftrag_nummer is not None else "Bericht"
        ablage.ablegen(DB_PFAD, text, art="bericht", projekt=projekt,
                       auftrag_nummer=auftrag_nummer, titel=titel)
    except Exception:
        logger.exception("Bericht nicht ins Ablagefach gelegt (Auftrag %s)", auftrag_nummer)
    return JSONResponse({"ok": True})


@mcp.custom_route(f"{BASIS}/protokoll", methods=["POST"], include_in_schema=False)
async def protokoll_hochladen(request: Request) -> JSONResponse:
    """CWB legt Hinweise, Fehler und Buildergebnisse ab (auch ohne Auftrag)."""
    if not _token_gueltig(request):
        logger.warning("protokoll_hochladen: ungueltiges oder fehlendes Token")
        return JSONResponse({"fehler": "nicht autorisiert"}, status_code=401)
    rohdaten = await request.body()
    if len(rohdaten) > MAX_GROESSE:
        return JSONResponse({"fehler": "zu gross"}, status_code=413)
    try:
        daten = await request.json()
    except Exception:
        return JSONResponse({"fehler": "kein gueltiges JSON"}, status_code=400)
    try:
        nummer = ablage.ablegen(
            DB_PFAD, daten.get("text") or "", art=daten.get("art") or "hinweis",
            projekt=daten.get("projekt"), auftrag_nummer=daten.get("auftrag_nummer"),
            titel=daten.get("titel"),
        )
    except ValueError as fehler:
        return JSONResponse({"fehler": str(fehler)}, status_code=400)
    return JSONResponse({"ok": True, "nummer": nummer})


@mcp.custom_route(f"{BASIS}/nachtbericht", methods=["POST"], include_in_schema=False)
async def nachtbericht_hochladen(request: Request) -> JSONResponse:
    """Nachtbericht des Leitstands (core/bruecke.py, nachtbericht_hochladen):
    haengt an keinem Auftrag, landet als Journal-Eintrag im Ablagefach."""
    if not _token_gueltig(request):
        logger.warning("nachtbericht_hochladen: ungueltiges oder fehlendes Token")
        return JSONResponse({"fehler": "nicht autorisiert"}, status_code=401)
    rohdaten = await request.body()
    if len(rohdaten) > MAX_GROESSE:
        return JSONResponse({"fehler": "zu gross"}, status_code=413)
    try:
        daten = await request.json()
    except Exception:
        return JSONResponse({"fehler": "kein gueltiges JSON"}, status_code=400)
    try:
        nummer = ablage.ablegen(DB_PFAD, daten.get("text") or "", art="journal",
                                projekt=daten.get("projekt"), titel="Nachtbericht")
    except ValueError as fehler:
        return JSONResponse({"fehler": str(fehler)}, status_code=400)
    return JSONResponse({"ok": True, "nummer": nummer})


class ProtokollMiddleware(BaseHTTPMiddleware):
    """Protokolliert jede Anfrage ohne den geheimen Pfadteil preiszugeben."""

    async def dispatch(self, request: Request, call_next):
        pfad = request.url.path.replace(SECRET_PATH, "<pfad>")
        try:
            antwort = await call_next(request)
        except Exception:
            logger.exception("Fehler bei %s %s", request.method, pfad)
            raise
        logger.info("%s %s -> %s", request.method, pfad, antwort.status_code)
        return antwort


app = mcp.streamable_http_app(
    streamable_http_path=f"{BASIS}/mcp",
    host="0.0.0.0",
    max_request_body_size=MAX_GROESSE,
)
app.add_middleware(ProtokollMiddleware)
# END: bruecke/server.py
