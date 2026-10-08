"""
CWB - Code Workbench
Systemweite Hotkeys fuer den Android-Screenshot: Pause-Taste und, als
zweite Belegung, Strg+Umschalt+B.

Ruft ueberall in Windows - unabhaengig davon, welches Fenster gerade vorn
ist - denselben Android-Screenshot-Ablauf aus wie ein #BILD#-Auftrag
(core/fenster.py, _bild_markierung): kein Umweg mehr ueber den Chat.

Registriert wird ueber Win32 RegisterHotKey mit hwnd=NULL - das liefert
WM_HOTKEY als reine Thread-Nachricht, ohne eigenes Fenster. Qt's
Windows-Ereignisschleife holt auch Thread-Nachrichten aus der Warteschlange
und reicht sie vor der eigenen Verarbeitung durch jeden registrierten
nativen Ereignisfilter (QAbstractNativeEventFilter) - deshalb genuegt ein
Filter, ganz ohne eigenen Thread mit eigener Nachrichtenschleife. Per
Standalone-Test (RegisterHotKey + PostThreadMessageW) am 08.10.2026
bestaetigt, dass dieser Weg in der hier installierten PySide6-Fassung
(6.11.1) weiterhin zuverlaessig ankommt.

RegisterHotKey ist pro Taste systemweit exklusiv - haelt ein ANDERER CWB-
Prozess (z.B. ein vergessenes altes Fenster, siehe wissen/tagebuch.md) die
Taste schon, schlaegt die Registrierung hier mit Fehlercode 1409 fehl und
die Taste wirkt in diesem Fenster nicht, ohne dass CWB das von aussen
erkennen koennte. Deshalb die zweite Belegung Strg+Umschalt+B: haelt ein
anderer Prozess ausgerechnet VK_PAUSE, bleibt mit etwas Glück wenigstens
die zweite Kombination frei. `status()` meldet fuer die Einstellungsseite,
welche der beiden Tasten dieser Prozess tatsaechlich bekommen hat.

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
MOD_STRG = 0x0002
MOD_UMSCHALT = 0x0004
VK_PAUSE = 0x13
VK_B = 0x42

# (ID, Modifiertasten, virtuelle Tastenkennung, Anzeigename fuer status()/Log)
_TASTEN = (
    (1, MOD_NOREPEAT, VK_PAUSE, "Pause"),
    (2, MOD_NOREPEAT | MOD_STRG | MOD_UMSCHALT, VK_B, "Strg+Umschalt+B"),
)


class PausenTaste(QAbstractNativeEventFilter):
    """Meldet beide Hotkeys an und ruft `ausgeloest` auf, sobald einer davon
    irgendwo in Windows gedrueckt wird. Die Einstellungspruefung liegt beim
    Aufrufer, nicht hier - siehe Modul-Kopf."""

    def __init__(self, anwendung, ausgeloest):
        super().__init__()
        self._anwendung = anwendung
        self._ausgeloest = ausgeloest
        self._registrierte_ids: set[int] = set()
        self._status: dict[str, bool] = {name: False for _, _, _, name in _TASTEN}

    def registrieren(self) -> bool:
        """Versucht beide Tasten, unabhaengig voneinander - schlaegt eine
        fehl (meist weil ein anderer CWB-Prozess sie schon haelt), bleibt die
        andere trotzdem nutzbar. Gibt True, sobald mindestens eine klappte."""
        for hotkey_id, mods, vk, name in _TASTEN:
            if _user32.RegisterHotKey(None, hotkey_id, mods, vk):
                self._registrierte_ids.add(hotkey_id)
                self._status[name] = True
                log.info("%s als systemweiter Hotkey registriert", name)
            else:
                fehlercode = ctypes.get_last_error()
                log.error(
                    "%s konnte nicht als Hotkey registriert werden (Fehlercode %s) "
                    "- vermutlich von einem anderen Programm oder einem anderen "
                    "CWB-Fenster belegt",
                    name, fehlercode,
                )
        if self._registrierte_ids:
            self._anwendung.installNativeEventFilter(self)
        return bool(self._registrierte_ids)

    def status(self) -> dict[str, bool]:
        """Welche der beiden Tasten dieser Prozess tatsaechlich bekommen hat
        - fuer die Anzeige in den Einstellungen (F12 -> Verhalten)."""
        return dict(self._status)

    def abmelden(self) -> None:
        for hotkey_id, _, _, name in _TASTEN:
            if hotkey_id in self._registrierte_ids:
                _user32.UnregisterHotKey(None, hotkey_id)
                log.info("%s-Hotkey abgemeldet", name)
        self._registrierte_ids.clear()

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            nachricht = wintypes.MSG.from_address(int(message))
            if nachricht.message == WM_HOTKEY and nachricht.wParam in self._registrierte_ids:
                try:
                    self._ausgeloest()
                except Exception as fehler:  # noqa: BLE001
                    log.exception("Auftrag des Screenshot-Hotkeys gescheitert: %s", fehler)
        return False, 0
