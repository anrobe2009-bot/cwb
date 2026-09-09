"""
CWB - Code Workbench
Terminalbefehle: fuehrt #run#- und #admin#-Auftraege direkt in PowerShell aus,
ohne Claude Code und ohne Modellaufruf.

#run# laeuft als gewoehnlicher Benutzer im Projektordner. Der Befehl wird in
eine temporaere .ps1-Datei geschrieben (UTF-8 ohne Bytereihenfolgezeichen,
Zeilenenden nur LF) und ueber "-File" ausgefuehrt statt ueber "-Command" mit
eingebettetem Text - Mehrzeiler und verschachtelte Anfuehrungszeichen kommen
so zuverlaessig an. Die Ausgabe wird zeilenweise weitergereicht, waehrend der
Befehl noch laeuft.

#admin# braucht erhoehte Rechte. Dafuer gibt es keinen direkten Weg an einen
Kindprozess mit verbundenen Ein-/Ausgaberohren - stattdessen laeuft EIN
dauerhafter, per UAC erhoehter Worker-Prozess (siehe AdminWorkerVerwaltung
und admin_worker_schleife). CWB reicht ihm jeden Auftrag als Auftragsdatei
mit fortlaufender Nummer und HMAC-Unterschrift weiter und liest die Antwort
aus einer zweiten Datei. Der Schluessel entsteht einmal bei Programmstart
(ADMIN_WORKER, unten) und steht in keiner Datei - nur der erhoehte
Worker-Prozess bekommt ihn beim Start als Kommandozeilenargument mit.

Beide Wege laufen in TerminalFaden (eigener Thread), damit weder die
Rechteanforderung noch ein langer Befehl das Fenster haengen laesst.
"""

import ctypes
import hashlib
import hmac
import json
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
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
# CWB wartet auf die Antwort des erhoehten Worker-Prozesses etwas laenger als
# dessen eigenes Zeitlimit: die Zeit fuer die UAC-Rueckfrage und das Anlaufen
# des Prozesses beim allerersten Admin-Befehl muss mit hinein.
ZEITLIMIT_ADMIN_WARTEN = ZEITLIMIT_ADMIN + 60

SW_HIDE = 0

_TEMP = Path(tempfile.gettempdir())
ADMIN_CMD_DATEI = _TEMP / "cwb_admin_cmd.json"
ADMIN_RES_DATEI = _TEMP / "cwb_admin_res.json"
ADMIN_SPERR_DATEI = _TEMP / "cwb_admin_lock"

_shell32 = ctypes.WinDLL("shell32", use_last_error=True)


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


@dataclass
class Ergebnis:
    """Ergebnis eines Terminalbefehls, immer im Ausgabefeld anzeigbar."""
    erfolg: bool
    ausgabe: str
    code: int
    fehler: str = ""


def befehl_ausfuehren(befehl: str, ordner: Path, zeitlimit: int = ZEITLIMIT_RUN,
                       teil_callback=None) -> Ergebnis:
    """Fuehrt einen Befehl als PowerShell-Aufruf im angegebenen Ordner aus.
    Der Befehl wird zuerst in eine temporaere .ps1-Datei geschrieben (UTF-8
    ohne Bytereihenfolgezeichen, Zeilenenden nur LF) und ueber -File
    aufgerufen, damit Mehrzeiler und verschachtelte Anfuehrungszeichen
    zuverlaessig ankommen. Ist `teil_callback` gesetzt, bekommt er jede
    Ausgabezeile sofort, waehrend der Befehl noch laeuft; Stdout und Stderr
    kommen gemeinsam zurueck."""
    vollbefehl = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$OutputEncoding = [System.Text.Encoding]::UTF8; " + befehl
    ).replace("\r\n", "\n").replace("\r", "\n")
    try:
        skript_datei = Path(tempfile.mktemp(suffix=".ps1", prefix="cwb_run_"))
        with open(skript_datei, "w", encoding="utf-8", newline="\n") as datei:
            datei.write(vollbefehl)
            if not vollbefehl.endswith("\n"):
                datei.write("\n")
    except OSError as fehler:
        log.error("Vorbereitung des Terminalbefehls gescheitert: %s (%s)", befehl, fehler)
        return Ergebnis(False, "", -1, str(fehler))

    try:
        prozess = subprocess.Popen(
            [
                "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(skript_datei),
            ],
            cwd=str(ordner),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as fehler:
        log.error("Terminalbefehl nicht startbar: %s (%s)", befehl, fehler)
        try:
            skript_datei.unlink(missing_ok=True)
        except OSError:
            pass
        return Ergebnis(False, "", -1, str(fehler))

    zeilen: list[str] = []
    ablauf = time.monotonic() + zeitlimit
    zeitueberschritten = False
    try:
        for zeile in prozess.stdout:
            zeilen.append(zeile)
            if teil_callback is not None:
                try:
                    teil_callback(zeile)
                except Exception as fehler:  # noqa: BLE001
                    log.exception("Live-Ausgabe nicht weitergereicht: %s", fehler)
            if time.monotonic() > ablauf:
                zeitueberschritten = True
                prozess.kill()
                break
    finally:
        try:
            prozess.stdout.close()
        except OSError:
            pass

    try:
        code = prozess.wait(timeout=10)
    except subprocess.TimeoutExpired:
        prozess.kill()
        code = -1

    try:
        skript_datei.unlink(missing_ok=True)
    except OSError as fehler:
        log.error("Temporaere Datei nicht loeschbar: %s (%s)", skript_datei, fehler)

    ausgabe = "".join(zeilen).strip()
    if zeitueberschritten:
        log.error("Terminalbefehl abgebrochen (Zeitueberschreitung): %s", befehl)
        return Ergebnis(False, ausgabe, -1, f"Zeitueberschreitung nach {zeitlimit} Sekunden")

    log.info("Terminalbefehl beendet, Code %d: %s", code, befehl)
    return Ergebnis(code == 0, ausgabe, code)


def _admin_unterschrift(schluessel: str, auftrag_id: int, befehl: str, ordner: str) -> str:
    """Die Unterschrift ueber einen Admin-Auftrag. Sie geht ueber alle drei
    Felder - ginge sie nur ueber den Befehl, liesse sich das
    Arbeitsverzeichnis nachtraeglich austauschen und derselbe unterschriebene
    Befehl woanders zur Wirkung bringen."""
    rohtext = f"{auftrag_id}\n{befehl}\n{ordner}".encode("utf-8")
    return hmac.new(schluessel.encode("utf-8"), rohtext, hashlib.sha256).hexdigest()


class AdminWorkerVerwaltung:
    """Verwaltet den dauerhaften, erhoehten Admin-Worker-Prozess: den
    Schluessel, mit dem Auftraege unterschrieben werden, die fortlaufende
    Auftragsnummer und das Anstossen des Prozesses.

    Es gibt genau eine Instanz je CWB-Prozess (ADMIN_WORKER, unten) - mehrere
    gleichzeitig offene Projektfenster teilen sich denselben Worker, damit
    die Windows-Rechteanforderung (UAC) nur einmal erscheint, nicht bei
    jedem einzelnen Admin-Befehl neu."""

    def __init__(self) -> None:
        # Bei jedem Programmstart neu gewuerfelt und nur im Speicher
        # gehalten. Ein Auftrag ohne die passende Unterschrift wird vom
        # erhoehten Worker nicht ausgefuehrt.
        self.schluessel = secrets.token_urlsafe(32)
        self._auftrag_id = 0
        self._gestartet = False
        # Schuetzt Zaehler und Auftragsdatei, falls mehrere Projektfenster
        # im selben CWB-Prozess gleichzeitig einen Admin-Befehl abschicken.
        self._sperre = threading.Lock()

    def sperre_schreiben(self) -> None:
        """Haelt fest, dass CWB laeuft - der Worker beendet sich von allein,
        sobald diese Datei eine Weile fehlt (siehe admin_worker_schleife)."""
        try:
            ADMIN_SPERR_DATEI.write_text(str(os.getpid()), encoding="utf-8")
        except OSError as fehler:
            log.error("Sperrdatei fuer Admin-Worker nicht schreibbar: %s", fehler)

    def sperre_entfernen(self) -> None:
        try:
            ADMIN_SPERR_DATEI.unlink(missing_ok=True)
        except OSError as fehler:
            log.error("Sperrdatei fuer Admin-Worker nicht loeschbar: %s", fehler)

    def _sicherstellen(self) -> None:
        """Startet den erhoehten Worker beim ersten Admin-Befehl - danach nie
        wieder in diesem Prozess, auch nicht nach einem abgelehnten
        UAC-Dialog. Ein zweiter Versuch waere ohnehin nutzlos: der Nutzer hat
        gerade erst abgelehnt."""
        if self._gestartet:
            return
        self._gestartet = True
        self.sperre_schreiben()
        skript = Path(sys.argv[0]).resolve()
        parameter = f'"{skript}" --admin-worker --admin-schluessel {self.schluessel}'
        info = _ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(_ShellExecuteInfo)
        info.fMask = 0
        info.hwnd = None
        info.lpVerb = "runas"
        info.lpFile = sys.executable
        info.lpParameters = parameter
        info.lpDirectory = str(skript.parent)
        info.nShow = SW_HIDE
        if not _shell32.ShellExecuteExW(ctypes.byref(info)):
            fehlercode = ctypes.get_last_error()
            log.error("Admin-Worker nicht startbar (Fehler %s)", fehlercode)
        else:
            log.info("Admin-Worker angestossen (%s)", skript)

    def auftrag_ausfuehren(self, befehl: str, ordner: Path,
                           zeitlimit: int = ZEITLIMIT_ADMIN_WARTEN) -> Ergebnis:
        """Reicht einen Befehl an den erhoehten Worker weiter und wartet auf
        die Antwort. Startet den Worker beim allerersten Aufruf; lehnt der
        Nutzer die Rechteanforderung ab, laeuft diese Methode bis zum
        Zeitlimit und meldet dann einen Fehlschlag - kein zweiter Versuch."""
        self._sicherstellen()
        with self._sperre:
            self._auftrag_id += 1
            auftrag_id = self._auftrag_id
            unterschrift = _admin_unterschrift(self.schluessel, auftrag_id, befehl, str(ordner))
            try:
                ADMIN_CMD_DATEI.write_text(
                    json.dumps({"id": auftrag_id, "cmd": befehl, "cwd": str(ordner),
                                "sig": unterschrift}),
                    encoding="utf-8",
                )
            except OSError as fehler:
                log.error("Admin-Auftrag nicht schreibbar: %s", fehler)
                return Ergebnis(False, "", -1, str(fehler))

        ablauf = time.monotonic() + zeitlimit
        while time.monotonic() < ablauf:
            time.sleep(0.25)
            try:
                if not ADMIN_RES_DATEI.exists():
                    continue
                antwort = json.loads(ADMIN_RES_DATEI.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if antwort.get("id") != auftrag_id:
                continue
            try:
                ADMIN_RES_DATEI.unlink(missing_ok=True)
            except OSError:
                pass
            log.info("Admin-Auftrag %d beendet, Code %s", auftrag_id, antwort.get("code"))
            return Ergebnis(
                bool(antwort.get("erfolg")),
                str(antwort.get("ausgabe", "")),
                int(antwort.get("code", -1)),
                str(antwort.get("fehler", "")),
            )

        log.error("Admin-Auftrag %d: keine Antwort innerhalb %d Sekunden", auftrag_id, zeitlimit)
        return Ergebnis(
            False, "", -1,
            "Keine Antwort vom erhöhten Worker (Rechteanforderung abgelehnt oder "
            "Zeitüberschreitung)",
        )


# Eine einzige, geteilte Instanz je Prozess - siehe Klassendoku oben.
ADMIN_WORKER = AdminWorkerVerwaltung()


def admin_worker_schleife(schluessel: str) -> None:
    """Laeuft im erhoehten Worker-Prozess (gestartet mit --admin-worker und
    --admin-schluessel). Nimmt Auftraege nur mit gueltiger Unterschrift und
    einer Nummer an, die groesser ist als die zuletzt ausgefuehrte - Schutz
    dagegen, dass ein alter, richtig unterschriebener Auftrag noch einmal
    abgelegt und wiederholt wird.

    Beendet sich von selbst, sobald die Sperrdatei laenger als fuenf Sekunden
    fehlt: dann laeuft der CWB-Prozess, der diesen Worker angestossen hat,
    nicht mehr."""
    if not schluessel:
        log.error("Admin-Worker ohne Schluessel gestartet, beende mich")
        return
    letzte_id = 0
    fehlt_seit: float | None = None
    log.info("Admin-Worker gestartet (PID %d)", os.getpid())
    while True:
        if not ADMIN_SPERR_DATEI.exists():
            fehlt_seit = fehlt_seit or time.monotonic()
            if time.monotonic() - fehlt_seit > 5:
                log.info("Admin-Worker beendet sich, CWB laeuft nicht mehr")
                return
        else:
            fehlt_seit = None
        try:
            if ADMIN_CMD_DATEI.exists():
                auftrag = json.loads(ADMIN_CMD_DATEI.read_text(encoding="utf-8"))
                try:
                    ADMIN_CMD_DATEI.unlink(missing_ok=True)
                except OSError:
                    pass
                auftrag_id = auftrag.get("id")
                befehl = str(auftrag.get("cmd") or "").strip()
                ordner = str(auftrag.get("cwd") or "") or os.path.expanduser("~")
                echt = (
                    isinstance(auftrag_id, int) and auftrag_id > letzte_id
                    and hmac.compare_digest(
                        str(auftrag.get("sig") or ""),
                        _admin_unterschrift(schluessel, auftrag_id, befehl, ordner),
                    )
                )
                if echt:
                    letzte_id = auftrag_id
                    ergebnis = befehl_ausfuehren(befehl, Path(ordner), ZEITLIMIT_ADMIN)
                    try:
                        ADMIN_RES_DATEI.write_text(
                            json.dumps({
                                "id": auftrag_id, "ausgabe": ergebnis.ausgabe,
                                "code": ergebnis.code, "erfolg": ergebnis.erfolg,
                                "fehler": ergebnis.fehler,
                            }),
                            encoding="utf-8",
                        )
                    except OSError as fehler:
                        log.error("Admin-Ergebnis nicht schreibbar: %s", fehler)
                else:
                    log.warning("Admin-Auftrag abgelehnt (Nummer oder Unterschrift ungueltig)")
        except Exception as fehler:  # noqa: BLE001
            log.exception("Admin-Worker-Schleife: %s", fehler)
        time.sleep(0.25)


class TerminalFaden(QThread):
    """Fuehrt genau einen Terminalbefehl aus - im eigenen Faden, damit weder
    eine UAC-Rueckfrage noch ein langer Befehl das Fenster haengen laesst."""

    fertig_da = Signal(object)
    # Nur bei #run#: jede Ausgabezeile, sobald sie ankommt. #admin# laeuft in
    # einem eigenen, erhoehten Prozess ohne verbundene Rohre - dort gibt es
    # nur das Endergebnis.
    teil_da = Signal(str)

    def __init__(self, art: str, befehl: str, ordner: Path, eltern=None):
        super().__init__(eltern)
        self.art = art
        self.befehl = befehl
        self.ordner = ordner

    def run(self) -> None:
        if self.art == "admin":
            ergebnis = ADMIN_WORKER.auftrag_ausfuehren(self.befehl, self.ordner)
        else:
            ergebnis = befehl_ausfuehren(
                self.befehl, self.ordner, ZEITLIMIT_RUN, teil_callback=self.teil_da.emit
            )
        self.fertig_da.emit(ergebnis)
