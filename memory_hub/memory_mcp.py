"""Memory Hub - MCP-Server.

Spricht das Model Context Protocol ueber stdio, ohne Fremdpakete.
Claude Code und Claude Desktop koennen damit selbst im Gedaechtnis
suchen, ergaenzen und aufraeumen.

WICHTIG: Auf stdout darf ausschliesslich JSON-RPC landen.
Jede Diagnose geht in memory_mcp.log.
"""

import os
import sys
import json
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory_db as db  # noqa: E402

PROTOCOL = "2024-11-05"
SERVER_NAME = "memory-hub"
SERVER_VERSION = "1.0"
LOG_PATH = os.path.join(db.base_dir(), "memory_mcp.log")


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")
            f.flush()
    except Exception:
        pass


TOOLS = [
    {
        "name": "memory_search",
        "description": (
            "Durchsucht das persoenliche Langzeitgedaechtnis des Nutzers nach "
            "Fakten, Regeln, Entscheidungen, Pfaden und Praeferenzen. "
            "Vor JEDER Aufgabe aufrufen, bevor Code gelesen oder geschrieben "
            "wird - nicht erst wenn ein Problem auftritt oder die Aufgabe "
            "kompliziert wirkt. Widerspricht ein Treffer dem ersten Einfall, "
            "gilt der Treffer."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Suchbegriffe, z.B. 'PowerShell Pfad'"},
                "project": {"type": "string",
                            "description": "Projektname; leer lassen fuer alle"},
                "limit": {"type": "integer",
                          "description": "Hoechstzahl Treffer, Standard 20"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "memory_add",
        "description": (
            "Speichert eine neue dauerhafte Erinnerung als EINEN vollstaendigen, "
            "in sich verstaendlichen Satz. Nur nutzen fuer Erkenntnisse mit "
            "Bestand: getroffene Entscheidungen samt Begruendung, feste Pfade, "
            "Praeferenzen des Nutzers, geloeste Fehlerursachen. Niemals "
            "Dateiinhalte, Funktionslisten oder Zwischenstaende, und nichts, "
            "was nur fuer den laufenden Chat gilt."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string",
                            "description": "Die Erinnerung, ein klarer Satz"},
                "category": {"type": "string",
                             "enum": db.CATEGORIES,
                             "description": "Art des Eintrags"},
                "project": {"type": "string",
                            "description": "Projektname; Standard 'global'"}
            },
            "required": ["content"]
        }
    },
    {
        "name": "memory_list",
        "description": (
            "Listet gespeicherte Erinnerungen auf, angeheftete zuerst. "
            "Gut geeignet, um sich zu Beginn einer Sitzung einen Ueberblick "
            "zu verschaffen."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string",
                            "description": "Projektname; leer lassen fuer alle"},
                "category": {"type": "string", "enum": db.CATEGORIES},
                "limit": {"type": "integer", "description": "Standard 50"}
            }
        }
    },
    {
        "name": "memory_forget",
        "description": (
            "Loescht eine Erinnerung anhand ihrer Nummer. Nur ausfuehren, "
            "wenn der Nutzer es ausdruecklich verlangt hat."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Nummer des Eintrags"}
            },
            "required": ["id"]
        }
    },
    {
        "name": "memory_projects",
        "description": ("Nennt alle Projekte im Gedaechtnis samt Eintragszahl "
                        "und zugeordnetem Ordner, falls einer ueber die "
                        "Oberflaeche hinterlegt wurde."),
        "inputSchema": {"type": "object", "properties": {}}
    }
]


def _fmt(items):
    if not items:
        return "Keine Eintraege gefunden."
    zeilen = []
    for i in items:
        marke = " [wichtig]" if i.get("pinned") else ""
        zeilen.append("#%s (%s / %s)%s\n%s"
                      % (i["id"], i["category"], i["project"], marke,
                         i["content"]))
    return "\n\n".join(zeilen)


def call_tool(name, args):
    args = args or {}
    if name == "memory_search":
        items = db.search(args.get("query", ""),
                          project=args.get("project") or None,
                          limit=int(args.get("limit") or 20))
        return _fmt(items)
    if name == "memory_add":
        content = (args.get("content") or "").strip()
        if not content:
            return "Fehler: Inhalt ist leer, nichts gespeichert."
        mid = db.add_memory(content,
                            category=args.get("category") or "Notiz",
                            project=args.get("project") or db.GLOBAL,
                            source="claude")
        return "Gespeichert als Eintrag #%s." % mid
    if name == "memory_list":
        items = db.list_memories(project=args.get("project") or None,
                                 category=args.get("category") or None,
                                 limit=int(args.get("limit") or 50))
        return _fmt(items)
    if name == "memory_forget":
        try:
            mid = int(args.get("id"))
        except (TypeError, ValueError):
            return "Fehler: Keine gueltige Nummer angegeben."
        ok = db.delete_memory(mid)
        return ("Eintrag #%s geloescht." % mid) if ok else \
               ("Eintrag #%s existiert nicht." % mid)
    if name == "memory_projects":
        p = db.list_projects_full()
        if not p:
            return "Noch keine Projekte angelegt."
        zeilen = []
        for proj in p:
            ordner = proj["folder"] or "kein Ordner hinterlegt"
            zeilen.append("%s: %d Eintraege, Ordner: %s"
                          % (proj["name"], proj["n"], ordner))
        return "\n".join(zeilen)
    raise ValueError("Unbekanntes Werkzeug: %s" % name)


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def reply(req_id, result):
    send({"jsonrpc": "2.0", "id": req_id, "result": result})


def fail(req_id, code, message):
    send({"jsonrpc": "2.0", "id": req_id,
          "error": {"code": code, "message": message}})


def handle(msg):
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        reply(req_id, {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}
        })
        return
    if method in ("notifications/initialized", "initialized",
                  "notifications/cancelled"):
        return
    if method == "ping":
        reply(req_id, {})
        return
    if method == "tools/list":
        reply(req_id, {"tools": TOOLS})
        return
    if method == "resources/list":
        reply(req_id, {"resources": []})
        return
    if method == "prompts/list":
        reply(req_id, {"prompts": []})
        return
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            text = call_tool(name, args)
            reply(req_id, {"content": [{"type": "text", "text": text}],
                           "isError": False})
        except Exception as e:
            log("Werkzeugfehler %s: %s" % (name, traceback.format_exc()))
            reply(req_id, {"content": [{"type": "text",
                                        "text": "Fehler: %s" % e}],
                           "isError": True})
        return
    if req_id is not None:
        fail(req_id, -32601, "Methode nicht unterstuetzt: %s" % method)


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    db.init_db()
    log("--- Start, Datenbank %s" % db.DB_PATH)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            log("Kein gueltiges JSON: %s" % line[:200])
            continue
        try:
            handle(msg)
        except Exception:
            log(traceback.format_exc())
            if msg.get("id") is not None:
                fail(msg.get("id"), -32603, "Interner Fehler")
    log("--- Ende")


if __name__ == "__main__":
    main()
