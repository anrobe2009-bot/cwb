"""
CWB - Code Workbench
Zielfenster: merkt sich das zuletzt aktive fremde Fenster, um dorthin nach
Abschluss eines #RUN#- oder #ADMIN#-Auftrags automatisch einzufuegen.

Reines Python, keine Oberflaeche - wie sicherheit.py. Ein Beobachter im
Hintergrund schreibt mit, welches fremde Fenster (nicht CWB selbst) zuletzt
im Vordergrund stand. Beim Erkennen einer Markierung wird das gemerkt -
unabhaengig davon, ob der Auftrag aus dem eigenen Eingabefeld, aus der
Zwischenablage oder ueber den Zwischenablage-Waechter kam. Ist der Auftrag
fertig, wird ohne weiteres Zutun genau dorthin eingefuegt, statt das
Ergebnis nur in der Zwischenablage liegen zu lassen.

Bewusst einfacher als eine feldgenaue Loesung: kein Suchen nach dem
Eingabefeld ueber UI Automation, nur das Zielfenster nach vorn holen und die
Zwischenablage per Strg+V einfuegen. Das trifft in den allermeisten Chat- und
Editor-Fenstern den zuletzt benutzten Fokus. Ist das Fenster inzwischen zu
oder laesst es sich nicht nach vorn holen, bleibt das Ergebnis in der
Zwischenablage liegen - nichts geht verloren.
"""

import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes

from PySide6.QtGui import QGuiApplication

try:
    from .pfade import log_einrichten
except ImportError:
    from pfade import log_einrichten

log_einrichten()
log = logging.getLogger("cwb.zielfenster")

_u32 = ctypes.windll.user32

VK_STRG = 0x11
VK_V = 0x56
TASTE_LOS = 0x0002
SW_WIEDERHERSTELLEN = 9
LSFW_UNLOCK = 2

# Abstand zwischen zwei Blicken auf das Vordergrundfenster.
BEOBACHTUNGS_ABSTAND_S = 0.5

_eigene_pid: int | None = None
_letztes_fremd: tuple | None = None
_ziel: tuple | None = None
_beobachter_laeuft = False


def _eigener_prozess(hwnd) -> bool:
    """Erkennt Fenster von CWB selbst ueber die Prozessnummer, nicht ueber
    den Titel: mehrere Projektfenster gehoeren demselben Prozess."""
    global _eigene_pid
    if _eigene_pid is None:
        _eigene_pid = os.getpid()
    pid = wintypes.DWORD(0)
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == _eigene_pid


def _titel_von(hwnd) -> str:
    try:
        laenge = _u32.GetWindowTextLengthW(hwnd)
        if laenge <= 0:
            return ""
        puffer = ctypes.create_unicode_buffer(laenge + 1)
        _u32.GetWindowTextW(hwnd, puffer, laenge + 1)
        return puffer.value
    except OSError:
        return ""


def _beobachten() -> None:
    global _letztes_fremd
    while True:
        try:
            hwnd = _u32.GetForegroundWindow()
            if hwnd and not _eigener_prozess(hwnd):
                titel = _titel_von(hwnd)
                if titel:
                    _letztes_fremd = (hwnd, titel)
        except OSError as fehler:
            log.exception("Vordergrundfenster nicht lesbar: %s", fehler)
        time.sleep(BEOBACHTUNGS_ABSTAND_S)


def beobachter_starten() -> None:
    """Startet den Hintergrundbeobachter. Mehrfacher Aufruf ist ungefaehrlich."""
    global _beobachter_laeuft
    if _beobachter_laeuft:
        return
    _beobachter_laeuft = True
    threading.Thread(target=_beobachten, daemon=True).start()
    log.info("Fensterbeobachter gestartet")


def fenster_merken() -> tuple | None:
    """Merkt sich das zuletzt beobachtete fremde Fenster - aufgerufen, sobald
    eine #RUN#- oder #ADMIN#-Markierung erkannt wird. Ohne bisherige
    Beobachtung (kurz nach dem Start) bleibt ein frueher gemerktes Ziel
    bestehen, statt verlorenzugehen."""
    global _ziel
    beobachter_starten()
    if _letztes_fremd is None:
        return _ziel
    _ziel = _letztes_fremd
    log.info("Zielfenster gemerkt: %s", _ziel[1][:60])
    return _ziel


def _lebt_noch(hwnd, titel: str) -> bool:
    """Fensternummern vergibt Windows wieder - darum zusaetzlich der
    Titelvergleich, nur ueber das stabile Ende (Chat-Titel aendern sich oft
    vorn, etwa um den Gespraechsnamen)."""
    try:
        if not _u32.IsWindow(hwnd):
            return False
        jetzt = _titel_von(hwnd)
        return bool(jetzt) and jetzt.lower()[-24:] == titel.lower()[-24:]
    except OSError:
        return False


def _in_vordergrund(hwnd) -> bool:
    try:
        if _u32.IsIconic(hwnd):
            _u32.ShowWindow(hwnd, SW_WIEDERHERSTELLEN)
            time.sleep(0.2)
        _u32.LockSetForegroundWindow(LSFW_UNLOCK)
        _u32.SetForegroundWindow(hwnd)
        _u32.BringWindowToTop(hwnd)
        time.sleep(0.3)
        return _u32.GetForegroundWindow() == hwnd
    except OSError as fehler:
        log.exception("Zielfenster nicht nach vorn geholt: %s", fehler)
        return False


def _strg_v() -> None:
    _u32.keybd_event(VK_STRG, 0, 0, 0)
    _u32.keybd_event(VK_V, 0, 0, 0)
    _u32.keybd_event(VK_V, 0, TASTE_LOS, 0)
    _u32.keybd_event(VK_STRG, 0, TASTE_LOS, 0)


def einfuegen(ziel: tuple | None, text: str) -> bool:
    """Legt `text` in die Zwischenablage und fuegt ihn per Strg+V in das
    gemerkte Fenster `ziel` (aus fenster_merken()) ein. Ohne Ziel oder ist
    das Fenster inzwischen zu oder nicht nach vorn zu holen, bleibt der Text
    nur in der Zwischenablage. Rueckgabe sagt, ob das Einfuegen geklappt hat."""
    if not text:
        return False
    try:
        QGuiApplication.clipboard().setText(text)
    except Exception as fehler:  # noqa: BLE001
        log.exception("Ergebnis nicht in die Zwischenablage gelegt: %s", fehler)
        return False
    if not ziel:
        return False
    hwnd, titel = ziel
    if not _lebt_noch(hwnd, titel):
        log.info("Zielfenster ist inzwischen geschlossen: %s", titel[:60])
        return False
    if not _in_vordergrund(hwnd):
        log.warning("Zielfenster liess sich nicht nach vorn holen: %s", titel[:60])
        return False
    time.sleep(0.15)
    _strg_v()
    log.info("Ergebnis eingefuegt in: %s", titel[:60])
    return True
