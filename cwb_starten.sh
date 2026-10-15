#!/usr/bin/env bash
# CWB unter Linux starten: nutzt das venv in .venv, braucht kein Terminal.
# Läuft abgekoppelt im Hintergrund; Fehler landen in cwb_fehler.log bzw.
# cwb_start_ausgabe.log. Mit --vordergrund bleibt der Prozess am Terminal.
set -u
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$WURZEL/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "Kein venv gefunden: $PYTHON" >&2
    exit 1
fi

# Qt auf X11 festlegen (auch unter Wayland über XWayland), außer es ist
# schon etwas gesetzt.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export PYTHONUNBUFFERED=1
cd "$WURZEL" || exit 1

if [ "${1:-}" = "--vordergrund" ]; then
    exec "$PYTHON" "$WURZEL/core/fenster.py"
fi

setsid nohup "$PYTHON" "$WURZEL/core/fenster.py" \
    >"$WURZEL/cwb_start_ausgabe.log" 2>&1 < /dev/null &
disown
