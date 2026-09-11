"""Code-Index - MCP-Server, Teil von CWB.

Spricht das Model Context Protocol ueber stdio, nach dem Muster von
memory_hub/memory_mcp.py gebaut. Ein Werkzeug: code_suchen - Frage in
natuerlicher Sprache rein, passendste Codestellen (Datei, Zeilen, Text) raus.
Kein Watcher, keine Oberflaeche, keine zweite KI dazwischen.

WICHTIG: Auf stdout darf ausschliesslich JSON-RPC landen.
Jede Diagnose geht in mcp_server.log.
"""

import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import indexer  # noqa: E402

PROTOCOL = "2024-11-05"
SERVER_NAME = "code-index"
SERVER_VERSION = "1.0"
WURZEL = Path(__file__).resolve().parent
LOG_PATH = WURZEL / "mcp_server.log"


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")
            f.flush()
    except Exception:
        pass


def _aktuelles_projekt() -> str:
    """Das offene Projekt ist das Arbeitsverzeichnis, mit dem dieser Server
    gestartet wurde: CWB setzt das Arbeitsverzeichnis der CLI immer auf den
    Projektordner (core/sitzung.py, ClaudeAgentOptions.cwd), ein stdio-MCP-
    Server erbt das als sein eigenes cwd. Es gibt keine feste Projektliste
    mehr - jeder Ordner ist ein gueltiges Projekt, auch ein brandneuer."""
    return str(Path(os.getcwd()).resolve())


TOOLS = [
    {
        "name": "code_suchen",
        "description": (
            "Durchsucht den lokalen Code-Index sinngemaess (keine reine "
            "Textsuche) nach einer Frage in natuerlicher Sprache, z.B. "
            "'wo wird die Spracherkennung gestartet'. Gibt die passendsten "
            "Codestellen zurueck: Dateipfad, Zeilennummern, Textausschnitt. "
            "Sucht automatisch im aktuell geoeffneten Projekt; projektpfad "
            "nur angeben, wenn ein anderes Projekt gemeint ist oder die "
            "Erkennung fehlschlaegt. Vor eigenem Suchen oder komplettem "
            "Lesen von Dateien immer zuerst hiermit versuchen."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "frage": {"type": "string",
                          "description": "Frage oder Suchbegriff in natuerlicher Sprache"},
                "projektpfad": {"type": "string",
                                "description": "Projektordner erzwingen (Standard: aktuelles Projekt)"},
                "anzahl": {"type": "integer",
                           "description": "Hoechstzahl Treffer, Standard 5"}
            },
            "required": ["frage"]
        }
    }
]


def _treffer_formatieren(t, i):
    ort = t["source"] or "?"
    if t.get("zeile_von"):
        ort += f":{t['zeile_von']}-{t['zeile_bis']}"
    return f"[{i}] {ort}\n{t['text'].strip()}"


def call_tool(name, args):
    args = args or {}
    if name == "code_suchen":
        frage = (args.get("frage") or "").strip()
        if not frage:
            return "Fehler: frage ist leer."

        projekt_pfad = args.get("projektpfad") or _aktuelles_projekt()
        anzahl = int(args.get("anzahl") or 5)
        treffer = indexer.search(projekt_pfad, frage, n_results=anzahl)
        if not treffer:
            return f"Keine Treffer in {projekt_pfad}. Ist das Projekt schon indexiert?"

        return "\n\n".join(_treffer_formatieren(t, i + 1) for i, t in enumerate(treffer))
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
    log("--- Start, cwd=%s" % os.getcwd())
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
