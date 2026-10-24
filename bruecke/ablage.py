# FILE: bruecke/ablage.py
"""Ablagefach der Bruecke: Protokolle, die nie ueberschrieben werden.

Reines sqlite3, ohne MCP - damit auch ohne den MCP-Server testbar
(bruecke/test_ablage.py). server.py reicht den Datenbankpfad herein.
"""
import datetime
import logging
import re
import sqlite3
from typing import Optional

logger = logging.getLogger("bruecke.ablage")

ERLAUBTE_ARTEN = ("bericht", "hinweis", "fehler", "build", "journal")
AUFBEWAHRUNG_TAGE = 14
MAX_EINTRAEGE = 2000
MAX_TEXT = 100_000  # wie MAX_GROESSE in server.py, in Zeichen
LESE_BLOCK = 20_000  # so viel liefert protokoll_lesen ohne "bis" hoechstens


def verbindung(db_pfad: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_pfad)
    conn.row_factory = sqlite3.Row
    return conn


def init(db_pfad: str) -> None:
    with verbindung(db_pfad) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS protokolle (
                nummer INTEGER PRIMARY KEY AUTOINCREMENT,
                zeit TEXT NOT NULL,
                auftrag_nummer INTEGER,
                projekt TEXT,
                art TEXT NOT NULL,
                titel TEXT,
                text TEXT NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_protokolle_zeit ON protokolle (zeit)")


def _jetzt() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def art_pruefen(art: str) -> str:
    art_norm = (art or "").strip().lower()
    if art_norm not in ERLAUBTE_ARTEN:
        raise ValueError(f"art muss eine von {', '.join(ERLAUBTE_ARTEN)} sein.")
    return art_norm


def aufraeumen(conn: sqlite3.Connection, jetzt: Optional[datetime.datetime] = None) -> int:
    """Loescht Eintraege aelter als AUFBEWAHRUNG_TAGE, danach die aeltesten
    ueber MAX_EINTRAEGE hinaus. Gibt die Zahl der geloeschten zurueck."""
    jetzt = jetzt or _jetzt()
    grenze = (jetzt - datetime.timedelta(days=AUFBEWAHRUNG_TAGE)).isoformat()
    geloescht = conn.execute("DELETE FROM protokolle WHERE zeit < ?", (grenze,)).rowcount
    ueberzahl = conn.execute("SELECT COUNT(*) AS n FROM protokolle").fetchone()["n"] - MAX_EINTRAEGE
    if ueberzahl > 0:
        geloescht += conn.execute(
            "DELETE FROM protokolle WHERE nummer IN "
            "(SELECT nummer FROM protokolle ORDER BY nummer ASC LIMIT ?)",
            (ueberzahl,),
        ).rowcount
    if geloescht:
        logger.info("Ablagefach: %d alte Eintraege geloescht", geloescht)
    return geloescht


def ablegen(db_pfad: str, text: str, art: str = "hinweis", projekt: Optional[str] = None,
            auftrag_nummer: Optional[int] = None, titel: Optional[str] = None,
            jetzt: Optional[datetime.datetime] = None) -> int:
    """Legt einen Eintrag ab und gibt seine laufende Nummer zurueck."""
    art_norm = art_pruefen(art)
    if not text or not text.strip():
        raise ValueError("text fehlt.")
    if len(text) > MAX_TEXT:
        raise ValueError(f"text zu lang ({len(text)} Zeichen, erlaubt sind {MAX_TEXT}).")
    jetzt = jetzt or _jetzt()
    with verbindung(db_pfad) as conn:
        cur = conn.execute(
            "INSERT INTO protokolle (zeit, auftrag_nummer, projekt, art, titel, text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (jetzt.isoformat(), auftrag_nummer, (projekt or None), art_norm,
             (titel or None), text),
        )
        nummer = cur.lastrowid
        aufraeumen(conn, jetzt)
    logger.info("Protokoll %d abgelegt (art=%s, auftrag=%s)", nummer, art_norm, auftrag_nummer)
    return nummer


_RELATIV = re.compile(r"^(\d+)\s*([mhdt])$", re.IGNORECASE)


def seit_lesen(seit: str, jetzt: Optional[datetime.datetime] = None) -> str:
    """Wandelt 'seit' in einen ISO-Zeitpunkt (UTC). Erlaubt: ISO-Datum/-Zeit
    oder kurz 30m, 2h, 3d (Minuten, Stunden, Tage)."""
    jetzt = jetzt or _jetzt()
    seit = seit.strip()
    treffer = _RELATIV.match(seit)
    if treffer:
        menge, einheit = int(treffer.group(1)), treffer.group(2).lower()
        delta = {"m": datetime.timedelta(minutes=menge), "h": datetime.timedelta(hours=menge)}.get(
            einheit, datetime.timedelta(days=menge))
        return (jetzt - delta).isoformat()
    try:
        zeit = datetime.datetime.fromisoformat(seit)
    except ValueError:
        raise ValueError("seit muss ein ISO-Zeitpunkt sein (2026-10-21T08:00) oder 30m, 2h, 3d.")
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=datetime.timezone.utc)
    return zeit.astimezone(datetime.timezone.utc).isoformat()


def liste(db_pfad: str, anzahl: int = 20, projekt: Optional[str] = None,
          art: Optional[str] = None, seit: Optional[str] = None) -> str:
    """Kurze Uebersicht, eine Zeile je Eintrag, neueste zuerst. Kein Volltext."""
    anzahl = max(1, min(int(anzahl), 200))
    bedingungen, werte = [], []
    if projekt:
        bedingungen.append("projekt = ?")
        werte.append(projekt)
    if art:
        bedingungen.append("art = ?")
        werte.append(art_pruefen(art))
    if seit:
        bedingungen.append("zeit >= ?")
        werte.append(seit_lesen(seit))
    where = (" WHERE " + " AND ".join(bedingungen)) if bedingungen else ""
    with verbindung(db_pfad) as conn:
        zeilen = conn.execute(
            "SELECT nummer, zeit, auftrag_nummer, projekt, art, titel, LENGTH(text) AS laenge "
            f"FROM protokolle{where} ORDER BY nummer DESC LIMIT ?",
            (*werte, anzahl),
        ).fetchall()
    if not zeilen:
        return "Keine Protokolle gefunden."
    zeilen_text = [
        f"Nr {z['nummer']} | {z['zeit'][:19].replace('T', ' ')} UTC | "
        f"Auftrag {z['auftrag_nummer'] if z['auftrag_nummer'] is not None else '-'} | "
        f"{z['projekt'] or '-'} | {z['art']} | {z['titel'] or '-'} | {z['laenge']} Zeichen"
        for z in zeilen
    ]
    return "\n".join(zeilen_text)


def lesen(db_pfad: str, nummer: int, von: int = 0, bis: Optional[int] = None) -> str:
    """Volltext oder ein Stueck davon (Zeichen von..bis). Ohne 'bis' hoechstens
    LESE_BLOCK Zeichen; der Kopf nennt, wo es weitergeht."""
    with verbindung(db_pfad) as conn:
        zeile = conn.execute("SELECT text FROM protokolle WHERE nummer = ?", (nummer,)).fetchone()
    if zeile is None:
        raise ValueError(f"Protokoll {nummer} gibt es nicht (mehr).")
    text = zeile["text"]
    gesamt = len(text)
    von = max(0, int(von))
    ende = gesamt if bis is None else min(gesamt, int(bis))
    ende = min(ende, von + LESE_BLOCK)
    if von >= gesamt:
        return f"[Protokoll {nummer}: {gesamt} Zeichen, von={von} liegt dahinter]"
    kopf = f"[Protokoll {nummer}: Zeichen {von} bis {ende} von {gesamt}"
    kopf += f", weiter mit von={ende}]" if ende < gesamt else ", Ende]"
    return kopf + "\n" + text[von:ende]
