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

Das Einfuegen soll IMMER geschehen, nicht mal so und mal so. Dafuer sorgen
vier Vorkehrungen:

1. Das zuletzt bekannte Ziel bleibt dauerhaft gemerkt und ueberlebt beliebig
   viele Auftraege. War beim Auftragsstart kein fremdes Fenster vorn (weil
   CWB selbst aktiv war), wird das Ziel des vorigen Auftrags weiterbenutzt.
   Nur wenn noch nie ein Ziel bekannt war, bleibt es beim reinen
   Zwischenablage-Verhalten.
2. Der Beobachter laeuft ab Programmstart mit, nicht erst ab dem ersten
   Auftrag - sonst waere genau der erste Auftrag jeder Sitzung blind.
   Zusaetzlich wird bei jedem Merken sofort selbst nachgesehen.
3. Ein Zielfenster gilt als lebendig, solange sein Prozess lebt - auch wenn
   sich der Fenstertitel geaendert hat (Chatfenster benennen sich um). Ist
   die Fensternummer weg, wird das Fenster ueber Prozess und Titel neu
   gesucht.
4. Das Nachvornholen und das Strg+V sind gegen die Fokussperre von Windows
   abgesichert (AttachThreadInput, mehrere Versuche, Warten auf den echten
   Fokuswechsel) und haengende Zusatztasten werden vorher geloest.

Bewusst einfacher als eine feldgenaue Loesung: kein Suchen nach dem
Eingabefeld ueber UI Automation, nur das Zielfenster nach vorn holen und die
Zwischenablage per Strg+V einfuegen. Das trifft in den allermeisten Chat- und
Editor-Fenstern den zuletzt benutzten Fokus.
"""

import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QGuiApplication

try:
    from .pfade import log_einrichten
except ImportError:
    from pfade import log_einrichten

log_einrichten()
log = logging.getLogger("cwb.zielfenster")

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32

# Ohne ausdrueckliche Signaturen behandelt ctypes Rueckgaben als 32-Bit-int.
# Auf 64-Bit-Windows kann eine Fensternummer dabei beschnitten werden - das
# Ergebnis zeigt dann auf nichts, und das Einfuegen scheitert scheinbar
# grundlos. Darum sind alle benutzten Aufrufe hier festgelegt.
_u32.GetForegroundWindow.restype = wintypes.HWND
_u32.GetForegroundWindow.argtypes = []
_u32.IsWindow.argtypes = [wintypes.HWND]
_u32.IsWindowVisible.argtypes = [wintypes.HWND]
_u32.IsIconic.argtypes = [wintypes.HWND]
_u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_u32.SetForegroundWindow.argtypes = [wintypes.HWND]
_u32.BringWindowToTop.argtypes = [wintypes.HWND]
_u32.SetActiveWindow.argtypes = [wintypes.HWND]
_u32.SetActiveWindow.restype = wintypes.HWND
_u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_u32.GetWindowThreadProcessId.restype = wintypes.DWORD
_u32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_u32.GetAsyncKeyState.restype = ctypes.c_short
_u32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
_u32.MapVirtualKeyW.restype = ctypes.c_uint
_k32.GetCurrentThreadId.restype = wintypes.DWORD

VK_STRG = 0x11
VK_V = 0x56
VK_UMSCHALT = 0x10
VK_ALT = 0x12
VK_FENSTER_LINKS = 0x5B
VK_FENSTER_RECHTS = 0x5C

TASTE_LOS = 0x0002
TASTE_SCANCODE_ERWEITERT = 0x0001
EINGABE_TASTATUR = 1
SW_WIEDERHERSTELLEN = 9
LSFW_UNLOCK = 2
ASFW_ANY = -1

# Abstand zwischen zwei Blicken auf das Vordergrundfenster.
BEOBACHTUNGS_ABSTAND_S = 0.5

# Fensterklassen, die nie Ziel sein duerfen: Desktop, Taskleiste, Startmenue
# und die Anmelde-/Rechteabfrage von Windows. Sonst wuerde ein Klick auf den
# Desktop oder eine Rechteanforderung das echte Ziel verdraengen.
KLASSEN_SPERRE = {
    "progman",
    "workerw",
    "shell_traywnd",
    "shell_secondarytraywnd",
    "windows.ui.core.corewindow",
    "credential dialog xaml host",
}

# Nachvornholen: so oft wird es versucht, so lange auf den echten
# Fokuswechsel gewartet.
VORDERGRUND_VERSUCHE = 3
VORDERGRUND_WARTE_S = 0.5
VORDERGRUND_TAKT_S = 0.05
# Ruhe zwischen Fokuswechsel und Strg+V: das Zielfenster braucht einen
# Augenblick, bis der Eingabefokus im Textfeld sitzt.
EINFUEGE_RUHE_S = 0.25

_eigene_pid: int | None = None
_letztes_fremd: tuple | None = None
_ziel: tuple | None = None
_beobachter_laeuft = False


def _eigener_prozess(hwnd) -> bool:
    """Erkennt Fenster von CWB selbst ueber die Prozessnummer, nicht ueber
    den Titel: mehrere Projektfenster gehoeren demselben Prozess."""
    return _pid_von(hwnd) == _eigene_pid_holen()


def _eigene_pid_holen() -> int:
    global _eigene_pid
    if _eigene_pid is None:
        _eigene_pid = os.getpid()
    return _eigene_pid


def _pid_von(hwnd) -> int:
    pid = wintypes.DWORD(0)
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


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


def _klasse_von(hwnd) -> str:
    try:
        puffer = ctypes.create_unicode_buffer(256)
        _u32.GetClassNameW(hwnd, puffer, 256)
        return puffer.value.lower()
    except OSError:
        return ""


def _taugt_als_ziel(hwnd) -> bool:
    """Nur sichtbare, fremde Fenster mit Titel kommen als Ziel in Frage -
    nicht Desktop, Taskleiste oder der Rechteanforderungs-Dialog."""
    if not hwnd or not _u32.IsWindowVisible(hwnd):
        return False
    if _eigener_prozess(hwnd):
        return False
    if _klasse_von(hwnd) in KLASSEN_SPERRE:
        return False
    return bool(_titel_von(hwnd))


def _blick() -> tuple | None:
    """Sieht einmal nach, welches fremde Fenster gerade vorn ist, und merkt
    es als zuletzt gesehen. Wird vom Beobachter im Takt aufgerufen und
    zusaetzlich beim Merken, damit der allererste Auftrag einer Sitzung nicht
    ins Leere greift."""
    global _letztes_fremd
    try:
        hwnd = _u32.GetForegroundWindow()
        if _taugt_als_ziel(hwnd):
            _letztes_fremd = (hwnd, _titel_von(hwnd), _pid_von(hwnd))
    except OSError as fehler:
        log.exception("Vordergrundfenster nicht lesbar: %s", fehler)
    return _letztes_fremd


def _beobachten() -> None:
    while True:
        _blick()
        time.sleep(BEOBACHTUNGS_ABSTAND_S)


def beobachter_starten() -> None:
    """Startet den Hintergrundbeobachter. Mehrfacher Aufruf ist ungefaehrlich.
    Wird beim Programmstart aufgerufen, damit schon der erste Auftrag ein
    Ziel hat."""
    global _beobachter_laeuft
    if _beobachter_laeuft:
        return
    _beobachter_laeuft = True
    threading.Thread(target=_beobachten, daemon=True).start()
    log.info("Fensterbeobachter gestartet")


def letztes_ziel() -> tuple | None:
    """Das zuletzt bekannte Zielfenster - bleibt ueber beliebig viele
    Auftraege hinweg stehen, bis ein neues an seine Stelle tritt."""
    return _ziel


def fenster_merken() -> tuple | None:
    """Merkt sich das zuletzt beobachtete fremde Fenster - aufgerufen, sobald
    eine #RUN#- oder #ADMIN#-Markierung erkannt wird. Ist gerade keins
    bekannt (CWB war selbst vorn, oder der Beobachter hatte noch keinen
    Blick), bleibt das Ziel des vorigen Auftrags bestehen."""
    global _ziel
    beobachter_starten()
    frisch = _blick()
    if frisch is None:
        if _ziel is not None:
            log.info("Kein frisches Zielfenster - bleibe bei: %s", _ziel[1][:60])
        else:
            log.info("Noch kein Zielfenster bekannt - Ergebnis geht in die Zwischenablage")
        return _ziel
    _ziel = frisch
    log.info("Zielfenster gemerkt: %s", _ziel[1][:60])
    return _ziel


def _gleicher_titel(a: str, b: str) -> bool:
    """Chat-Titel aendern sich vorn (Gespraechsname), das Ende bleibt meist
    stehen (Anwendungsname) - darum nur das stabile Ende vergleichen."""
    return bool(a) and bool(b) and a.lower()[-24:] == b.lower()[-24:]


def _fenster_wiederfinden(pid: int, titel: str):
    """Sucht ein Fenster desselben Prozesses (oder mit gleichem Titelende),
    wenn die gemerkte Fensternummer nicht mehr gilt - etwa weil das
    Zielprogramm sein Fenster neu aufgebaut hat."""
    treffer = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _sammeln(hwnd, _lparam):
        if _taugt_als_ziel(hwnd):
            eigen_pid = _pid_von(hwnd)
            if eigen_pid == pid or _gleicher_titel(_titel_von(hwnd), titel):
                treffer.append((hwnd, _titel_von(hwnd), eigen_pid))
        return True

    try:
        _u32.EnumWindows(_sammeln, 0)
    except OSError as fehler:
        log.exception("Fenstersuche fehlgeschlagen: %s", fehler)
        return None
    # Fenster desselben Prozesses haben Vorrang vor blossen Titeltreffern.
    for eintrag in treffer:
        if eintrag[2] == pid:
            return eintrag
    return treffer[0] if treffer else None


def _gueltiges_ziel(ziel: tuple | None) -> tuple | None:
    """Prueft, ob das gemerkte Fenster noch da ist. Fensternummern vergibt
    Windows wieder - darum zaehlt zusaetzlich die Prozessnummer. Passt die
    Nummer nicht mehr, wird ueber Prozess und Titel neu gesucht."""
    if not ziel:
        return None
    hwnd, titel, pid = ziel
    try:
        if _u32.IsWindow(hwnd) and _u32.IsWindowVisible(hwnd) and _pid_von(hwnd) == pid:
            return (hwnd, _titel_von(hwnd) or titel, pid)
    except OSError:
        pass
    ersatz = _fenster_wiederfinden(pid, titel)
    if ersatz is not None:
        log.info("Zielfenster neu gefunden: %s", ersatz[1][:60])
    return ersatz


def _fokus_setzen(hwnd) -> None:
    """Nimmt Windows die Fokussperre: nur der Vordergrundprozess darf den
    Fokus vergeben. Durch das voruebergehende Anhaengen an dessen
    Eingabewarteschlange zaehlt CWB fuer diesen Moment dazu."""
    eigener = _k32.GetCurrentThreadId()
    vorne = _u32.GetForegroundWindow()
    fremder = _u32.GetWindowThreadProcessId(vorne, None) if vorne else 0
    angehaengt = bool(fremder) and fremder != eigener and bool(
        _u32.AttachThreadInput(eigener, fremder, True)
    )
    try:
        _u32.LockSetForegroundWindow(LSFW_UNLOCK)
        _u32.AllowSetForegroundWindow(ASFW_ANY)
        if _u32.IsIconic(hwnd):
            _u32.ShowWindow(hwnd, SW_WIEDERHERSTELLEN)
        _u32.BringWindowToTop(hwnd)
        _u32.SetForegroundWindow(hwnd)
        _u32.SetActiveWindow(hwnd)
    finally:
        if angehaengt:
            _u32.AttachThreadInput(eigener, fremder, False)


def _in_vordergrund(hwnd) -> bool:
    """Holt das Zielfenster nach vorn und wartet, bis Windows den Wechsel
    wirklich vollzogen hat. Ein einzelner Versuch reicht nicht: je nach
    Fokuslage lehnt Windows den ersten Anlauf stillschweigend ab - genau
    daher ruehrt das sprunghafte Verhalten."""
    for versuch in range(1, VORDERGRUND_VERSUCHE + 1):
        try:
            _fokus_setzen(hwnd)
        except OSError as fehler:
            log.exception("Zielfenster nicht nach vorn geholt: %s", fehler)
            return False
        ende = time.monotonic() + VORDERGRUND_WARTE_S
        while time.monotonic() < ende:
            if _u32.GetForegroundWindow() == hwnd:
                if versuch > 1:
                    log.info("Zielfenster erst im %d. Versuch vorn", versuch)
                return True
            time.sleep(VORDERGRUND_TAKT_S)
    return False


class _TASTATUR(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _EINGABE_INHALT(ctypes.Union):
    _fields_ = [("ki", _TASTATUR), ("polster", ctypes.c_ubyte * 32)]


class _EINGABE(ctypes.Structure):
    _fields_ = [("art", wintypes.DWORD), ("inhalt", _EINGABE_INHALT)]


_u32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_EINGABE), ctypes.c_int]
_u32.SendInput.restype = wintypes.UINT


def _taste(vk: int, los: bool) -> _EINGABE:
    scan = _u32.MapVirtualKeyW(vk, 0)
    flaggen = TASTE_LOS if los else 0
    return _EINGABE(
        art=EINGABE_TASTATUR,
        inhalt=_EINGABE_INHALT(ki=_TASTATUR(wVk=vk, wScan=scan, dwFlags=flaggen)),
    )


def _senden(tasten: list) -> bool:
    feld = (_EINGABE * len(tasten))(*tasten)
    gesendet = _u32.SendInput(len(tasten), feld, ctypes.sizeof(_EINGABE))
    if gesendet != len(tasten):
        # Haeufigster Grund: das Zielfenster laeuft mit hoeheren Rechten,
        # dann verweigert Windows die Eingabe aus einem gewoehnlichen Prozess.
        log.warning(
            "Tastendruck nur teilweise angenommen (%d von %d), Windows-Fehler %d",
            gesendet,
            len(tasten),
            _k32.GetLastError(),
        )
        return False
    return True


def _zusatztasten_loesen() -> None:
    """Haengt noch eine Zusatztaste vom Bedienen per Tastenkuerzel fest,
    wuerde aus Strg+V ein Strg+Umschalt+V - in vielen Programmen etwas ganz
    anderes. Darum vorher alles loslassen, was gedrueckt gemeldet wird."""
    los = [
        _taste(vk, True)
        for vk in (VK_UMSCHALT, VK_ALT, VK_FENSTER_LINKS, VK_FENSTER_RECHTS, VK_STRG)
        if _u32.GetAsyncKeyState(vk) & 0x8000
    ]
    if los:
        _senden(los)
        time.sleep(0.05)


def _strg_v() -> bool:
    """Sendet Strg+V ueber SendInput. keybd_event gilt als veraltet und wird
    von Programmen mit eigener Eingabeverarbeitung mitunter uebergangen."""
    _zusatztasten_loesen()
    return _senden(
        [
            _taste(VK_STRG, False),
            _taste(VK_V, False),
            _taste(VK_V, True),
            _taste(VK_STRG, True),
        ]
    )


# Anzahl Versuche und Basis-Wartezeit fuer das Zwischenablage-Schreiben.
# Direkt nach einem UAC-Wechsel (sicherer Desktop) kann der Windows-Aufruf
# hinter QClipboard.setText() stillschweigend fehlschlagen, ohne dass Qt das
# als Python-Ausnahme meldet - das setText() tut dann einfach nichts. Darum
# wird nach jedem Versuch zurueckgelesen und bei Abweichung mit steigender
# Wartezeit erneut versucht.
ZWISCHENABLAGE_VERSUCHE = 5
ZWISCHENABLAGE_WARTE_BASIS_S = 0.15


def _in_zwischenablage_legen(text: str) -> bool:
    """Schreibt `text` in die Zwischenablage und liest ihn sofort zurueck -
    das prueft echten Erfolg, statt nur das Fehlen einer Python-Ausnahme zu
    werten (die es bei einem stillen Win32-Fehlschlag ohnehin nicht gibt).
    Stimmt der zurueckgelesene Text nicht, wird bis zu ZWISCHENABLAGE_VERSUCHE
    mal erneut versucht, mit steigender Wartezeit dazwischen."""
    for versuch in range(1, ZWISCHENABLAGE_VERSUCHE + 1):
        try:
            QGuiApplication.clipboard().setText(text)
            zurueckgelesen = QGuiApplication.clipboard().text()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zwischenablage-Versuch %d fehlgeschlagen: %s", versuch, fehler)
            zurueckgelesen = None
        if zurueckgelesen == text:
            if versuch > 1:
                log.info("Zwischenablage erst im %d. Versuch angekommen", versuch)
            return True
        if versuch < ZWISCHENABLAGE_VERSUCHE:
            wartezeit = ZWISCHENABLAGE_WARTE_BASIS_S * versuch
            log.warning(
                "Zwischenablage-Versuch %d: Text kam nicht an, warte %.2fs", versuch, wartezeit
            )
            time.sleep(wartezeit)
    log.error(
        "Ergebnis nach %d Versuchen nicht in die Zwischenablage gelegt - "
        "vermutlich Zugriffskonflikt rund um eine Rechteanforderung (UAC)",
        ZWISCHENABLAGE_VERSUCHE,
    )
    return False


def datei_in_zwischenablage_legen(pfad: str) -> bool:
    """Legt einen Dateiverweis auf `pfad` in die Zwischenablage - dasselbe
    CF_HDROP-Format, das der Windows-Explorer beim Kopieren einer Datei per
    Strg+C erzeugt und das Chatfenster als Bild annehmen, waehrend rohe
    Bilddaten (CF_DIB/CF_BITMAP ueber QClipboard.setImage()) dort mitunter
    abgelehnt werden (core/android_screenshot.py). Direkt ueber
    QClipboard.setMimeData() im laufenden CWB-Prozess, ohne PowerShell oder
    sonst einen zweiten Prozess - muss auf dem GUI-Thread laufen, wie
    _in_zwischenablage_legen auch. Gleiches Schreiben-zurücklesen-Muster:
    bei Abweichung mit steigender Wartezeit erneut versucht."""
    url = QUrl.fromLocalFile(pfad)
    for versuch in range(1, ZWISCHENABLAGE_VERSUCHE + 1):
        try:
            mime = QMimeData()
            mime.setUrls([url])
            QGuiApplication.clipboard().setMimeData(mime)
            zurueckgelesen = QGuiApplication.clipboard().mimeData().urls()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zwischenablage-Versuch %d (Bild) fehlgeschlagen: %s", versuch, fehler)
            zurueckgelesen = []
        if zurueckgelesen == [url]:
            if versuch > 1:
                log.info("Bild erst im %d. Versuch in der Zwischenablage angekommen", versuch)
            return True
        if versuch < ZWISCHENABLAGE_VERSUCHE:
            wartezeit = ZWISCHENABLAGE_WARTE_BASIS_S * versuch
            log.warning(
                "Zwischenablage-Versuch %d (Bild): Dateiverweis kam nicht an, warte %.2fs",
                versuch, wartezeit,
            )
            time.sleep(wartezeit)
    log.error(
        "Bild nach %d Versuchen nicht in die Zwischenablage gelegt", ZWISCHENABLAGE_VERSUCHE
    )
    return False


def einfuegen(ziel: tuple | None, text: str) -> bool:
    """Legt `text` in die Zwischenablage und fuegt ihn per Strg+V in das
    gemerkte Fenster `ziel` (aus fenster_merken()) ein. Ist kein Ziel
    uebergeben, wird das zuletzt bekannte Ziel benutzt - so landet das
    Ergebnis auch dann im Chatfenster, wenn der Auftrag aus CWB selbst kam.
    Nur wenn ueberhaupt noch nie ein Ziel bekannt war oder es sich nicht mehr
    ansprechen laesst, bleibt der Text in der Zwischenablage liegen.
    Rueckgabe sagt, ob das Einfuegen geklappt hat."""
    if not text:
        return False
    if not _in_zwischenablage_legen(text):
        return False
    ziel = _gueltiges_ziel(ziel or letztes_ziel())
    if not ziel:
        log.info("Kein ansprechbares Zielfenster - Ergebnis bleibt in der Zwischenablage")
        return False
    hwnd, titel, _pid = ziel
    if not _in_vordergrund(hwnd):
        log.warning("Zielfenster liess sich nicht nach vorn holen: %s", titel[:60])
        return False
    time.sleep(EINFUEGE_RUHE_S)
    # Letzte Sicherung: nur einfuegen, wenn das Ziel in diesem Augenblick
    # wirklich noch vorn ist - sonst ginge der Text an ein fremdes Fenster.
    if _u32.GetForegroundWindow() != hwnd:
        log.warning("Fokus vor dem Einfuegen wieder verloren: %s", titel[:60])
        return False
    if not _strg_v():
        log.warning("Strg+V wurde nicht angenommen: %s", titel[:60])
        return False
    log.info("Ergebnis eingefuegt in: %s", titel[:60])
    return True
