"""Memory Hub - Kernmodul.

Lokale Gedaechtniszentrale fuer Claude. Speichert Fakten, Regeln,
Entscheidungen und Praeferenzen in einer SQLite-Datenbank mit
Volltextsuche. Wird von der GUI und vom MCP-Server gemeinsam genutzt.
"""

import os
import re
import sys
import sqlite3
import datetime

CATEGORIES = ["Regel", "Fakt", "Entscheidung", "Praeferenz",
              "Pfad", "Fehler", "Notiz"]

GLOBAL = "global"

HAS_FTS = True


def base_dir():
    """Ordner der Anwendung - auch als EXE korrekt. Hier liegt nur noch das
    Log; die Datenbank liegt im Datenordner (siehe DB_PATH)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# Die Datenbank liegt unter %LOCALAPPDATA%\CWB, nicht im Programmordner -
# damit Roberts Gedaechtnis jeden Programmwechsel ueberlebt. Den Ort kennt
# core/datenordner.py; das Modul ist bewusst frei von Qt und Log-Einrichtung,
# damit dieser MCP-Server es aus jeder Claude-Code-Sitzung laden kann. Alte
# Bestaende aus dem Programmordner holt daten_umziehen() einmalig herueber.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import datenordner as _datenordner  # noqa: E402

_datenordner.daten_umziehen()
DB_PATH = str(_datenordner.hub_datenbank())


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db():
    """Legt Tabellen und Suchindex an. Mehrfacher Aufruf ist harmlos."""
    global HAS_FTS
    con = connect()
    c = con.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS memories(
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            project  TEXT    NOT NULL DEFAULT 'global',
            category TEXT    NOT NULL DEFAULT 'Notiz',
            content  TEXT    NOT NULL,
            source   TEXT    NOT NULL DEFAULT 'manuell',
            pinned   INTEGER NOT NULL DEFAULT 0,
            created  TEXT    NOT NULL,
            updated  TEXT    NOT NULL
        )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_project ON memories(project)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_category ON memories(category)")
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects(
            name    TEXT PRIMARY KEY,
            folder  TEXT,
            created TEXT NOT NULL,
            updated TEXT NOT NULL
        )""")
    c.execute("INSERT OR IGNORE INTO projects(name, folder, created, updated) "
              "VALUES (?,?,?,?)", (GLOBAL, None, _now(), _now()))
    try:
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content, project, category,
                content='memories', content_rowid='id',
                tokenize="unicode61 remove_diacritics 2"
            )""")
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories BEGIN
              INSERT INTO memories_fts(rowid, content, project, category)
              VALUES (new.id, new.content, new.project, new.category);
            END""")
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories BEGIN
              INSERT INTO memories_fts(memories_fts, rowid, content, project, category)
              VALUES ('delete', old.id, old.content, old.project, old.category);
            END""")
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON memories BEGIN
              INSERT INTO memories_fts(memories_fts, rowid, content, project, category)
              VALUES ('delete', old.id, old.content, old.project, old.category);
              INSERT INTO memories_fts(rowid, content, project, category)
              VALUES (new.id, new.content, new.project, new.category);
            END""")
        HAS_FTS = True
    except sqlite3.OperationalError:
        HAS_FTS = False
    con.commit()
    con.close()
    return HAS_FTS


# ---------------------------------------------------------------- Schreiben

def add_memory(content, category="Notiz", project=GLOBAL,
               source="manuell", pinned=0):
    """Legt einen Eintrag an. Gleicher Text im gleichen Projekt wird
    aktualisiert statt doppelt gespeichert."""
    content = (content or "").strip()
    if not content:
        raise ValueError("Leerer Inhalt.")
    project = (project or GLOBAL).strip() or GLOBAL
    category = category if category in CATEGORIES else "Notiz"
    con = connect()
    c = con.cursor()
    c.execute("SELECT id FROM memories WHERE project=? AND content=?",
              (project, content))
    row = c.fetchone()
    if row:
        c.execute("UPDATE memories SET category=?, updated=? WHERE id=?",
                  (category, _now(), row["id"]))
        con.commit()
        con.close()
        return row["id"]
    ts = _now()
    c.execute("""INSERT INTO memories
                 (project, category, content, source, pinned, created, updated)
                 VALUES (?,?,?,?,?,?,?)""",
              (project, category, content, source, int(pinned), ts, ts))
    new_id = c.lastrowid
    con.commit()
    con.close()
    return new_id


def update_memory(mem_id, content=None, category=None,
                  project=None, pinned=None):
    con = connect()
    c = con.cursor()
    c.execute("SELECT * FROM memories WHERE id=?", (mem_id,))
    row = c.fetchone()
    if not row:
        con.close()
        raise KeyError("Eintrag %s nicht gefunden." % mem_id)
    new = {
        "content": (content if content is not None else row["content"]).strip(),
        "category": category if category in CATEGORIES else row["category"],
        "project": (project or row["project"]).strip() or GLOBAL,
        "pinned": int(row["pinned"] if pinned is None else pinned),
    }
    c.execute("""UPDATE memories SET content=?, category=?, project=?,
                 pinned=?, updated=? WHERE id=?""",
              (new["content"], new["category"], new["project"],
               new["pinned"], _now(), mem_id))
    con.commit()
    con.close()
    return True


def delete_memory(mem_id):
    con = connect()
    c = con.cursor()
    c.execute("DELETE FROM memories WHERE id=?", (mem_id,))
    changed = c.rowcount
    con.commit()
    con.close()
    return changed > 0


def toggle_pin(mem_id):
    con = connect()
    c = con.cursor()
    c.execute("SELECT pinned FROM memories WHERE id=?", (mem_id,))
    row = c.fetchone()
    if not row:
        con.close()
        return None
    val = 0 if row["pinned"] else 1
    c.execute("UPDATE memories SET pinned=?, updated=? WHERE id=?",
              (val, _now(), mem_id))
    con.commit()
    con.close()
    return val


# ------------------------------------------------------------------- Lesen

def get_memory(mem_id):
    con = connect()
    row = con.execute("SELECT * FROM memories WHERE id=?", (mem_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def list_memories(project=None, category=None, limit=500):
    """Alle Eintraege, angeheftete zuerst, danach die neuesten."""
    sql = "SELECT * FROM memories WHERE 1=1"
    args = []
    if project and project != "*":
        sql += " AND project=?"
        args.append(project)
    if category and category != "*":
        sql += " AND category=?"
        args.append(category)
    sql += " ORDER BY pinned DESC, updated DESC LIMIT ?"
    args.append(int(limit))
    con = connect()
    rows = con.execute(sql, args).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _fts_expression(query):
    """Baut aus freiem Text einen gueltigen FTS5-Ausdruck.
    Jedes Wort wird als Praefixsuche behandelt, Sonderzeichen fliegen raus."""
    words = re.findall(r"\w+", query, re.UNICODE)
    words = [w for w in words if len(w) > 1]
    if not words:
        return ""
    return " OR ".join('"%s"*' % w.replace('"', "") for w in words)


def search(query, project=None, limit=20):
    """Volltextsuche. Faellt bei fehlendem FTS5 auf LIKE zurueck."""
    query = (query or "").strip()
    if not query:
        return list_memories(project=project, limit=limit)
    con = connect()
    rows = []
    if HAS_FTS:
        expr = _fts_expression(query)
        if expr:
            sql = ("SELECT m.* FROM memories_fts f "
                   "JOIN memories m ON m.id = f.rowid "
                   "WHERE memories_fts MATCH ?")
            args = [expr]
            if project and project != "*":
                sql += " AND m.project=?"
                args.append(project)
            sql += " ORDER BY m.pinned DESC, bm25(memories_fts) LIMIT ?"
            args.append(int(limit))
            try:
                rows = con.execute(sql, args).fetchall()
            except sqlite3.OperationalError:
                rows = []
    if not rows:
        sql = "SELECT * FROM memories WHERE content LIKE ?"
        args = ["%" + query + "%"]
        if project and project != "*":
            sql += " AND project=?"
            args.append(project)
        sql += " ORDER BY pinned DESC, updated DESC LIMIT ?"
        args.append(int(limit))
        rows = con.execute(sql, args).fetchall()
    con.close()
    return [dict(r) for r in rows]


def projects():
    con = connect()
    rows = con.execute(
        "SELECT project, COUNT(*) AS n FROM memories "
        "GROUP BY project ORDER BY project").fetchall()
    con.close()
    return [(r["project"], r["n"]) for r in rows]


def stats():
    con = connect()
    total = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    pinned = con.execute(
        "SELECT COUNT(*) FROM memories WHERE pinned=1").fetchone()[0]
    con.close()
    return {"total": total, "pinned": pinned,
            "projects": len(list_projects_full()), "db": DB_PATH}


# ------------------------------------------------------- Projektverwaltung

def list_projects_full():
    """Alle Projekte mit Ordner und Eintragszahl, auch ohne Eintraege."""
    con = connect()
    zeilen = con.execute(
        "SELECT p.name AS name, p.folder AS folder, COALESCE(m.n, 0) AS n "
        "FROM projects p LEFT JOIN "
        "(SELECT project, COUNT(*) AS n FROM memories GROUP BY project) m "
        "ON m.project = p.name").fetchall()
    ergebnis = {r["name"]: {"name": r["name"], "folder": r["folder"], "n": r["n"]}
                for r in zeilen}
    for name, n in projects():
        if name not in ergebnis:
            ergebnis[name] = {"name": name, "folder": None, "n": n}
    con.close()
    return sorted(ergebnis.values(), key=lambda r: r["name"])


def project_names():
    """Alle bekannten Projektnamen, auch ohne Eintraege."""
    return sorted({p["name"] for p in list_projects_full()} | {GLOBAL})


def add_project(name, folder=None):
    """Legt ein neues Projekt an, optional mit Ordner."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Leerer Projektname.")
    folder = (folder or "").strip() or None
    if folder and not os.path.isdir(folder):
        raise NotADirectoryError(folder)
    con = connect()
    c = con.cursor()
    c.execute("SELECT name FROM projects WHERE name=?", (name,))
    if c.fetchone():
        con.close()
        raise ValueError("Projekt '%s' gibt es bereits." % name)
    ts = _now()
    c.execute("INSERT INTO projects(name, folder, created, updated) "
              "VALUES (?,?,?,?)", (name, folder, ts, ts))
    con.commit()
    con.close()
    return name


def set_project_folder(name, folder):
    """Setzt oder aendert den Ordner eines Projekts. Legt das Projekt an,
    falls es noch keinen Eintrag in der Projekttabelle hat."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Leerer Projektname.")
    folder = (folder or "").strip() or None
    if folder and not os.path.isdir(folder):
        raise NotADirectoryError(folder)
    con = connect()
    c = con.cursor()
    c.execute("SELECT name FROM projects WHERE name=?", (name,))
    ts = _now()
    if c.fetchone():
        c.execute("UPDATE projects SET folder=?, updated=? WHERE name=?",
                  (folder, ts, name))
    else:
        c.execute("INSERT INTO projects(name, folder, created, updated) "
                  "VALUES (?,?,?,?)", (name, folder, ts, ts))
    con.commit()
    con.close()


def get_project_folder(name):
    name = (name or "").strip()
    if not name:
        return None
    con = connect()
    row = con.execute("SELECT folder FROM projects WHERE name=?",
                      (name,)).fetchone()
    con.close()
    return row["folder"] if row and row["folder"] else None


def rename_project(old, new):
    """Benennt ein Projekt um und verschiebt seine Erinnerungen mit."""
    old = (old or "").strip()
    new = (new or "").strip()
    if not old or not new:
        raise ValueError("Projektname darf nicht leer sein.")
    if old == GLOBAL:
        raise ValueError("Das Projekt 'global' kann nicht umbenannt werden.")
    if old == new:
        return
    con = connect()
    c = con.cursor()
    c.execute("SELECT name FROM projects WHERE name=?", (new,))
    if c.fetchone():
        con.close()
        raise ValueError("Projekt '%s' gibt es bereits." % new)
    ts = _now()
    c.execute("UPDATE memories SET project=?, updated=? WHERE project=?",
              (new, ts, old))
    c.execute("SELECT name FROM projects WHERE name=?", (old,))
    if c.fetchone():
        c.execute("UPDATE projects SET name=?, updated=? WHERE name=?",
                  (new, ts, old))
    else:
        c.execute("INSERT INTO projects(name, folder, created, updated) "
                  "VALUES (?,?,?,?)", (new, None, ts, ts))
    con.commit()
    con.close()


def delete_project(name, delete_memories=False):
    """Loescht ein Projekt. Erinnerungen wandern nach 'global',
    ausser delete_memories ist gesetzt."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Leerer Projektname.")
    if name == GLOBAL:
        raise ValueError("Das Projekt 'global' kann nicht geloescht werden.")
    con = connect()
    c = con.cursor()
    ts = _now()
    if delete_memories:
        c.execute("DELETE FROM memories WHERE project=?", (name,))
    else:
        c.execute("UPDATE memories SET project=?, updated=? WHERE project=?",
                  (GLOBAL, ts, name))
    c.execute("DELETE FROM projects WHERE name=?", (name,))
    con.commit()
    con.close()


# ------------------------------------------------------------------ Export

REGELN_BLOCK = """## Umgang mit dem Gedaechtnis

Diesem Projekt steht der MCP-Server memory-hub zur Verfuegung. Er ist verbindlich zu benutzen.

Vor der Arbeit:
Rufe memory_search mit den Stichworten der Aufgabe auf, bevor du Code liest oder schreibst. Suche zusaetzlich mit project auf global, dort stehen die uebergreifenden Regeln. Was dort steht, gilt. Widerspricht ein Eintrag deinem ersten Einfall, folge dem Eintrag oder frage nach.

Waehrend der Arbeit:
Stoesst du auf eine Falle, die dich Zeit gekostet hat, halte sie fest, sobald sie geloest ist. Nicht erst am Ende.

Nach der Arbeit:
Rufe memory_add auf fuer jede Erkenntnis mit Bestand. Das sind getroffene Entscheidungen samt Begruendung, hartkodierte Pfade und warum sie noetig sind, geloeste Fehlerursachen, Umgehungsloesungen und Praeferenzen des Nutzers.

Nicht eintragen:
Was in den Dateien steht und dort jederzeit nachlesbar ist. Funktionslisten, Dateiinhalte, Zwischenstaende, Vermutungen, alles was nur fuer diese eine Sitzung gilt.

Massstab: Ein Eintrag ist ein vollstaendiger Satz, der in einem halben Jahr ohne jeden Kontext noch verstaendlich ist."""


def export_markdown(project=None, include_global=True, mit_regeln=False):
    """Erzeugt den Markdown-Block, den Claude als Kontext liest.
    mit_regeln haengt REGELN_BLOCK an, gedacht fuer Ziele mit MCP-Server
    (CLAUDE.md), nicht fuer den Export in die Zwischenablage fuer claude.ai."""
    items = list_memories(project=project, limit=1000)
    if project and project != GLOBAL and include_global:
        items = list_memories(project=GLOBAL, limit=1000) + items
    heute = datetime.date.today().strftime("%d.%m.%Y")
    titel = project if project and project != "*" else "Alle Projekte"
    out = ["# Projektgedaechtnis: %s" % titel,
           "",
           "Stand %s. Automatisch erzeugt von Memory Hub." % heute,
           "Diese Angaben gelten als verbindlich fuer die Arbeit an diesem Projekt.",
           ""]
    for cat in CATEGORIES:
        gruppe = [i for i in items if i["category"] == cat]
        if not gruppe:
            continue
        out.append("## %s" % cat)
        out.append("")
        for i in gruppe:
            marke = "**[wichtig]** " if i["pinned"] else ""
            text = i["content"].replace("\n", "\n  ")
            out.append("- %s%s" % (marke, text))
        out.append("")
    if len(out) <= 5:
        out.append("_Noch keine Eintraege._")
    text = "\n".join(out).rstrip() + "\n"
    if mit_regeln:
        text += "\n" + REGELN_BLOCK.rstrip() + "\n"
    return text


START_MARK = "<!-- MEMORY-HUB:START -->"
END_MARK = "<!-- MEMORY-HUB:END -->"


def write_claude_md(folder, project=None, mit_regeln=True):
    """Schreibt CLAUDE.md in den Projektordner. Handgeschriebener Text
    ausserhalb der Marker bleibt unangetastet."""
    if not os.path.isdir(folder):
        raise NotADirectoryError(folder)
    ziel = os.path.join(folder, "CLAUDE.md")
    block = "%s\n%s\n%s" % (START_MARK,
                            export_markdown(project, mit_regeln=mit_regeln),
                            END_MARK)
    alt = ""
    if os.path.exists(ziel):
        with open(ziel, "r", encoding="utf-8", errors="replace") as f:
            alt = f.read()
    if START_MARK in alt and END_MARK in alt:
        vor = alt.split(START_MARK)[0]
        nach = alt.split(END_MARK, 1)[1]
        neu = vor + block + nach
    elif alt.strip():
        neu = alt.rstrip() + "\n\n" + block + "\n"
    else:
        neu = block + "\n"
    with open(ziel, "w", encoding="utf-8") as f:
        f.write(neu)
    return ziel


if __name__ == "__main__":
    init_db()
    print("Datenbank bereit:", DB_PATH)
    print("FTS5 aktiv:", HAS_FTS)
    print(stats())
