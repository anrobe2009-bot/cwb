"""
CWB - Code Workbench
Terminalbefehle: fuehrt #run#- und #admin#-Auftraege direkt in PowerShell aus,
ohne Claude Code und ohne Modellaufruf.

#run# laeuft als gewoehnlicher Benutzer im Projektordner. #admin# laeuft mit
erhoehten Rechten ueber eine Windows-Rechteanforderung (UAC) - dafuer gibt es
keinen direkten Weg an einen Kindprozess mit verbundenen Ein-/Ausgaberohren,
darum schreibt der erhoehte Prozess seine Ausgabe in eine temporaere Datei,
die hier wieder eingelesen wird.

Beide laufen in TerminalFaden (eigener Thread), damit weder die
Rechteanforderung noch ein langer Befehl das Fenster haengen laesst.
"""

import ctypes
import logging
import subprocess
import tempfile
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

try:
    from .pfade import log_einrichten
except ImportError:
    from pfade import log_einrichten

log_einrichten()
log = logging.getLogger("cwb.terminal")

# Hoechstlaufzeit eines Befehls, bevor er abgebrochen wird.
ZEITLIMIT_RUN = 120
ZEITLIMIT_ADMIN = 300

WAIT_TIMEOUT = 0x00000102
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_HIDE = 0

_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hKeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


_shell32.ShellExecuteExW.restype = wintypes.BOOL
_shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.GetExitCodeProcess.restype = wintypes.BOOL
_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]


@dataclass
class Ergebnis:
    """Ergebnis eines Terminalbefehls, immer im Ausgabefeld anzeigbar."""
    erfolg: bool
    ausgabe: str
    code: int
    fehler: str = ""


def befehl_ausfuehren(befehl: str, ordner: Path, zeitlimit: int = ZEITLIMIT_RUN) -> Ergebnis:
    """Fuehrt einen Befehl als PowerShell-Aufruf im Projektordner aus, ohne
    erhoehte Rechte. Der Befehl wird zuerst in eine temporaere .ps1-Datei
    geschrieben und ueber -File aufgerufen (statt -Command), damit
    Mehrzeiler und verschachtelte Anfuehrungszeichen zuverlaessig ankommen.
    Stdout und Stderr kommen gemeinsam zurueck."""
    vollbefehl = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$OutputEncoding = [System.Text.Encoding]::UTF8; " + befehl
    )
    try:
        skript_datei = Path(tempfile.mktemp(suffix=".ps1", prefix="cwb_run_"))
        skript_datei.write_text(vollbefehl, encoding="utf-8")
    except OSError as fehler:
        log.error("Vorbereitung des Terminalbefehls gescheitert: %s (%s)", befehl, fehler)
        return Ergebnis(False, "", -1, str(fehler))

    try:
        prozess = subprocess.run(
            [
                "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(skript_datei),
            ],
            cwd=str(ordner),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=zeitlimit,
        )
    except subprocess.TimeoutExpired:
        log.error("Terminalbefehl abgebrochen (Zeitueberschreitung): %s", befehl)
        return Ergebnis(False, "", -1, f"Zeitueberschreitung nach {zeitlimit} Sekunden")
    except OSError as fehler:
        log.error("Terminalbefehl nicht startbar: %s (%s)", befehl, fehler)
        return Ergebnis(False, "", -1, str(fehler))
    finally:
        try:
            skript_datei.unlink(missing_ok=True)
        except OSError as fehler:
            log.error("Temporaere Datei nicht loeschbar: %s (%s)", skript_datei, fehler)

    ausgabe = ((prozess.stdout or "") + (prozess.stderr or "")).strip()
    log.info("Terminalbefehl beendet, Code %d: %s", prozess.returncode, befehl)
    return Ergebnis(prozess.returncode == 0, ausgabe, prozess.returncode)


def admin_befehl_ausfuehren(befehl: str, ordner: Path, zeitlimit: int = ZEITLIMIT_ADMIN) -> Ergebnis:
    """Fuehrt einen Befehl mit erhoehten Rechten aus. Windows fragt dafuer
    immer per UAC nach; lehnt der Nutzer dort ab, gilt der Befehl als
    fehlgeschlagen. Die Ausgabe des erhoehten Prozesses kommt ueber eine
    temporaere Datei zurueck, die danach geloescht wird."""
    try:
        skript_datei = Path(tempfile.mktemp(suffix=".ps1", prefix="cwb_admin_"))
        ausgabe_datei = Path(tempfile.mktemp(suffix=".txt", prefix="cwb_admin_"))
        code_datei = Path(tempfile.mktemp(suffix=".txt", prefix="cwb_admin_"))
        skript = (
            f"Set-Location -LiteralPath '{ordner}'\n"
            f"{befehl} *>&1 | Out-File -LiteralPath '{ausgabe_datei}' -Encoding utf8\n"
            f"$LASTEXITCODE | Out-File -LiteralPath '{code_datei}' -Encoding utf8\n"
        )
        skript_datei.write_text(skript, encoding="utf-8")
    except OSError as fehler:
        log.error("Vorbereitung des Admin-Befehls gescheitert: %s (%s)", befehl, fehler)
        return Ergebnis(False, "", -1, str(fehler))

    parameter = (
        "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass "
        f'-File "{skript_datei}"'
    )
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(_ShellExecuteInfo)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = "powershell.exe"
    info.lpParameters = parameter
    info.lpDirectory = str(ordner)
    info.nShow = SW_HIDE

    exit_code = -1
    try:
        if not _shell32.ShellExecuteExW(ctypes.byref(info)):
            fehlercode = ctypes.get_last_error()
            log.error(
                "Rechteanforderung abgelehnt oder fehlgeschlagen (Fehler %s): %s",
                fehlercode, befehl,
            )
            return Ergebnis(False, "", -1, "Rechteanforderung abgelehnt oder fehlgeschlagen")

        warte_ergebnis = _kernel32.WaitForSingleObject(info.hProcess, zeitlimit * 1000)
        if warte_ergebnis == WAIT_TIMEOUT:
            _kernel32.TerminateProcess(info.hProcess, 1)
            _kernel32.CloseHandle(info.hProcess)
            log.error("Admin-Befehl abgebrochen (Zeitueberschreitung): %s", befehl)
            return Ergebnis(False, "", -1, f"Zeitueberschreitung nach {zeitlimit} Sekunden")

        code = wintypes.DWORD()
        _kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        _kernel32.CloseHandle(info.hProcess)
        exit_code = code.value
    except OSError as fehler:
        log.error("Admin-Befehl nicht ausfuehrbar: %s (%s)", befehl, fehler)
        return Ergebnis(False, "", -1, str(fehler))

    ausgabe = ""
    try:
        if ausgabe_datei.exists():
            ausgabe = ausgabe_datei.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as fehler:
        log.error("Ausgabe des Admin-Befehls nicht lesbar: %s", fehler)
    try:
        if code_datei.exists():
            text = code_datei.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                exit_code = int(text)
    except (OSError, ValueError) as fehler:
        log.error("Exit-Code des Admin-Befehls nicht lesbar: %s", fehler)

    for datei in (skript_datei, ausgabe_datei, code_datei):
        try:
            datei.unlink(missing_ok=True)
        except OSError as fehler:
            log.error("Temporaere Datei nicht loeschbar: %s (%s)", datei, fehler)

    log.info("Admin-Befehl beendet, Code %d: %s", exit_code, befehl)
    return Ergebnis(exit_code == 0, ausgabe, exit_code)


class TerminalFaden(QThread):
    """Fuehrt genau einen Terminalbefehl aus - im eigenen Faden, damit weder
    eine UAC-Rueckfrage noch ein langer Befehl das Fenster haengen laesst."""

    fertig_da = Signal(object)

    def __init__(self, art: str, befehl: str, ordner: Path, eltern=None):
        super().__init__(eltern)
        self.art = art
        self.befehl = befehl
        self.ordner = ordner

    def run(self) -> None:
        if self.art == "admin":
            ergebnis = admin_befehl_ausfuehren(self.befehl, self.ordner)
        else:
            ergebnis = befehl_ausfuehren(self.befehl, self.ordner)
        self.fertig_da.emit(ergebnis)
