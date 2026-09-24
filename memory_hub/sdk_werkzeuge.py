"""
CWB - Code Workbench
Memory Hub als eingebauter SDK-MCP-Server (Block 61, Teil A).

Frueher lief memory_hub/memory_mcp.py als eigener, in ~/.claude.json
registrierter Prozess und sprach JSON-RPC ueber stdio. Diese Datei bietet
dieselben sechs Werkzeuge (memory_search, memory_add, memory_list,
memory_forget, memory_aufraeumen, memory_projects) stattdessen ueber das
Claude Agent SDK direkt im CWB-Prozess an (create_sdk_mcp_server) - kein
separater Serverprozess mehr. Die eigentliche Werkzeug-Logik bleibt
unveraendert in memory_mcp.call_tool() und memory_db.py; hier wird sie nur
neu angeboten.

Jeder Aufruf faengt seine eigenen Ausnahmen ab und liefert eine deutsche
Fehlermeldung als Werkzeugergebnis zurueck, statt CWB mitzureissen - das SDK
selbst faengt Ausnahmen aus Werkzeug-Handlern ebenfalls ab (siehe
claude_agent_sdk.create_sdk_mcp_server), diese Schicht sorgt zusaetzlich
fuer eine verstaendliche Meldung und einen Log-Eintrag.
"""

import logging
import os
import sys

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server, tool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory_mcp  # noqa: E402  - reine Werkzeug-Logik, unveraendert

log = logging.getLogger("cwb.memory_hub.sdk")

# Servername, unter dem die Werkzeuge in der Sitzung erscheinen -
# "mcp__memory-hub__memory_search" usw., wie bisher ueber den externen
# Prozess. core/sitzung.py (NACHSCHLAGE_WERKZEUGE) verlaesst sich auf
# genau diesen Namen.
SERVER_NAME = "memory-hub"


def _handler_bauen(name: str):
    """Baut den async-Aufrufer fuer ein einzelnes Werkzeug. Der Name wird
    als Default-Argument gebunden, damit die Schleife in server() nicht
    ueber eine gemeinsame Schleifenvariable stolpert."""

    async def handler(args: dict, _name: str = name) -> dict:
        try:
            text = memory_mcp.call_tool(_name, args)
            return {"content": [{"type": "text", "text": text}]}
        except Exception as fehler:  # noqa: BLE001
            log.exception("Memory-Hub-Werkzeug %s fehlgeschlagen: %s", _name, fehler)
            return {
                "content": [{
                    "type": "text",
                    "text": f"Fehler im Gedächtnis-Werkzeug {_name}: {fehler}",
                }],
                "is_error": True,
            }

    return handler


def server() -> McpSdkServerConfig:
    """Baut den eingebetteten Memory-Hub-Server neu auf. Wird bei jedem
    Verbindungsaufbau frisch gerufen (core/sitzung.py), damit init_db() vor
    der ersten Nutzung sicher gelaufen ist - dieselbe Datenbank, denselben
    Pfad wie zuvor der externe Prozess und wie HubLeser (core/wissen.py)."""
    memory_mcp.db.init_db()
    werkzeuge = [
        tool(eintrag["name"], eintrag["description"], eintrag["inputSchema"])(
            _handler_bauen(eintrag["name"])
        )
        for eintrag in memory_mcp.TOOLS
    ]
    return create_sdk_mcp_server(SERVER_NAME, tools=werkzeuge)
