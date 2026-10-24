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

# Der Aufpasser (core/aufpasser.py) startet CWB und startet es nach einem
# Absturz neu (hoechstens 3 Mal in 5 Minuten). Mit CWB_OHNE_AUFPASSER=1
# startet CWB wie frueher direkt.
if [ "${CWB_OHNE_AUFPASSER:-}" = "1" ]; then
    EINSTIEG="$WURZEL/core/fenster.py"
else
    EINSTIEG="$WURZEL/core/aufpasser.py"
fi

if [ "${1:-}" = "--vordergrund" ]; then
    exec "$PYTHON" "$EINSTIEG"
fi

setsid nohup "$PYTHON" "$EINSTIEG" \
    >"$WURZEL/cwb_start_ausgabe.log" 2>&1 < /dev/null &
disown
