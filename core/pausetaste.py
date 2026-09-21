"""
CWB - Code Workbench
Systemweiter Hotkey auf die Pause-Taste.

Ruft ueberall in Windows - unabhaengig davon, welches Fenster gerade vorn
ist - denselben Android-Screenshot-Ablauf aus wie ein #BILD#-Auftrag
(core/fenster.py, _bild_markierung): kein Umweg mehr ueber den Chat.

Registriert wird ueber Win32 RegisterHotKey mit hwnd=NULL - das liefert
WM_HOTKEY als reine Thread-Nachricht, ohne eigenes Fenster. Qt's
Windows-Ereignisschleife holt auch Thread-Nachrichten aus der Warteschlange
und reicht sie vor der eigenen Verarbeitung durch jeden registrierten
nativen Ereignisfilter (QAbstractNativeEventFilter) - deshalb genuegt ein
Filter, ganz ohne eigenen Thread mit eigener Nachrichtenschleife.

Ob die Einstellung "Pause-Taste holt Screenshot" gerade an ist, prueft der
Aufrufer selbst bei jedem Tastendruck (siehe fenster.py) - genau wie der
Zwischenablage-Waechter seine Einstellung bei jedem Blick neu liest. So
wirkt ein Umschalten in F12 sofort, ohne dass hier neu registriert werden
muss.
"""

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

try:
    from .pfade import log_einrichten
except ImportError:
    from pfade import log_einrichten

log_einrichten()
log = logging.getLogger("cwb.pausetaste")

_user32 = ctypes.WinDLL("user32", use_last_error=True)

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
VK_PAUSE = 0x13
_HOTKEY_ID = 1


class PausenTaste(QAbstractNativeEventFilter):
    """Meldet den Hotkey an und ruft `ausgeloest` auf, sobald die
    Pause-Taste irgendwo in Windows gedrueckt wird. Die Einstellungspruefung
    liegt beim Aufrufer, nicht hier - siehe Modul-Kopf."""

    def __init__(self, anwendung, ausgeloest):
        super().__init__()
        self._anwendung = anwendung
        self._ausgeloest = ausgeloest
        self._registriert = False

    def registrieren(self) -> bool:
        if _user32.RegisterHotKey(None, _HOTKEY_ID, MOD_NOREPEAT, VK_PAUSE):
            self._registriert = True
            self._anwendung.installNativeEventFilter(self)
            log.info("Pause-Taste als systemweiter Hotkey registriert")
            return True
        fehlercode = ctypes.get_last_error()
        log.error(
            "Pause-Taste konnte nicht als Hotkey registriert werden (Fehlercode %s) "
            "- vermutlich von einem anderen Programm belegt",
            fehlercode,
        )
        return False

    def abmelden(self) -> None:
        if self._registriert:
            _user32.UnregisterHotKey(None, _HOTKEY_ID)
            self._registriert = False
            log.info("Pause-Taste-Hotkey abgemeldet")

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            nachricht = wintypes.MSG.from_address(int(message))
            if nachricht.message == WM_HOTKEY and nachricht.wParam == _HOTKEY_ID:
                try:
                    self._ausgeloest()
                except Exception as fehler:  # noqa: BLE001
                    log.exception("Auftrag der Pause-Taste gescheitert: %s", fehler)
        return False, 0
