"""
CWB - Code Workbench
Android-Screenshot vom verbundenen Geraet holen. `adb exec-out screencap -p`
liefert die rohen PNG-Bytes - das laeuft bei Robert seit Stunden
zuverlaessig und ist in jeder Variante gleich (_screenshot_holen).

Zwei Wege, das fertige Bild danach zu Robert zu bringen:

VARIANTE A - fester Platz im Downloads-Ordner (Standard). Die Datei landet
immer unter demselben Namen im Downloads-Ordner des Nutzers und wird jedes
Mal ueberschrieben - der Datei-Dialog jedes Chat-Programms schaut dort
ohnehin zuerst nach, Robert muss nie suchen. Kein Zwischenablage-Zugriff,
also auch keine Blockade moeglich.

VARIANTE B - Zwischenablage, mit angehaltenem Waechter. Legt das Bild wie
zuvor per eigenstaendigem PowerShell-Prozess (System.Windows.Forms.Clipboard)
ab, mit Strg+V direkt einfuegbar. Robert bekam dabei zuletzt HRESULT
-2147221040 (CLIPBRD_E_CANT_OPEN) von OleFlushClipboard - auch nach
Abschalten des Windows-Zwischenablageverlaufs. Grund: CWBs eigener
Zwischenablage-Waechter (core/ablagewaechter.py) liest alle zwei Sekunden
clipboard.text() im selben Windows-Sitzungskontext und oeffnet dafuer kurz
die Zwischenablage - faellt das mit dem PowerShell-Zugriff zusammen,
schlaegt einer der beiden fehl. Deshalb wird der Waechter vorher ueber
seinen bestehenden Schalter in einstellungen.json (Schluessel
"ablage_waechter", siehe core/fenster.py) angehalten und danach auf den
vorherigen Wert zurueckgesetzt - ohne dass dieses Skript mit dem
laufenden CWB-Prozess sprechen muesste.

Eigenstaendiges Kommandozeilenwerkzeug. Aus dem Projekt CWB selbst per
#RUN#-Befehl:

    #run# python core\\android_screenshot.py

Aus JEDEM anderen Projekt heraus (der #RUN#-Befehl laeuft sonst im dort
offenen Projektordner, in dem diese Datei nicht liegt) ueber das
Startskript mit absolutem Pfad in .cwb-werkzeuge, unabhaengig vom offenen
Projekt:

    #run# python C:\\Users\\Entwickler\\.cwb-werkzeuge\\android_screenshot.py

Fuer die Zwischenablage-Variante zusaetzlich "--zwischenablage" anhaengen.

adb liefert die Bilddaten ueber subprocess als rohe Bytes - anders als eine
PowerShell-Umleitung (">"), die Binaerdaten durch Zeilenende-Ersetzung
beschaedigen kann, kommt hier nichts durch eine Textkodierung.
"""

import argparse
import contextlib
import ctypes
import logging
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

try:
    from .pfade import einstellungen_lesen, einstellungen_schreiben, log_einrichten
except ImportError:
    from pfade import einstellungen_lesen, einstellungen_schreiben, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.android_screenshot")

ZEITLIMIT_S = 20

# Fester Name im Downloads-Ordner (Variante A) - wird jedes Mal ueberschrieben.
DOWNLOADS_DATEINAME = "android_screenshot.png"

# Anzahl Versuche und Basis-Wartezeit fuer das Zwischenablage-Schreiben
# (Variante B) - dieselben Werte wie in core/zielfenster.py
# (ZWISCHENABLAGE_VERSUCHE).
ZWISCHENABLAGE_VERSUCHE = 5
ZWISCHENABLAGE_WARTE_BASIS_S = 0.15

# Schluessel in einstellungen.json, ueber den core/ablagewaechter.py bei
# jedem Blick prueft, ob er ueberhaupt zugreifen soll (core/fenster.py).
WAECHTER_SCHLUESSEL = "ablage_waechter"


def _screenshot_holen() -> bytes:
    """Holt den rohen PNG-Bildinhalt vom verbundenen Android-Geraet ueber
    adb. subprocess liefert stdout als Bytes ohne jede Textumwandlung."""
    if shutil.which("adb") is None:
        raise RuntimeError(
            "adb wurde nicht gefunden. Android-Platform-Tools installieren "
            "und dem PATH hinzufuegen."
        )
    try:
        ergebnis = subprocess.run(
            ["adb", "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=ZEITLIMIT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as fehler:
        raise RuntimeError(
            f"adb hat nicht innerhalb von {ZEITLIMIT_S} Sekunden geantwortet."
        ) from fehler
    if ergebnis.returncode != 0:
        meldung = ergebnis.stderr.decode("utf-8", "replace").strip() or "unbekannter Fehler"
        raise RuntimeError(f"adb-Screenshot fehlgeschlagen: {meldung}")
    if not ergebnis.stdout:
        raise RuntimeError(
            "adb hat kein Bild geliefert - ist genau ein Geraet verbunden und "
            "USB-Debugging erlaubt?"
        )
    return ergebnis.stdout


def _png_masse(png_daten: bytes) -> tuple[int, int]:
    """Liest Breite und Hoehe direkt aus dem IHDR-Chunk am Dateianfang -
    ohne Bildbibliothek, nur fuer die Meldung an Robert."""
    try:
        breite, hoehe = struct.unpack(">II", png_daten[16:24])
        return breite, hoehe
    except struct.error:
        return 0, 0


# ---------------------------------------------------------------------------
# Variante A - fester Platz im Downloads-Ordner
# ---------------------------------------------------------------------------

class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


# FOLDERID_Downloads - fest von Windows vergeben, kein Wert dieses Rechners.
_FOLDERID_DOWNLOADS = _GUID(
    0x374DE290,
    0x123F,
    0x4565,
    (ctypes.c_byte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B),
)


def _downloads_ordner() -> Path:
    """Ermittelt den echten Downloads-Ordner ueber SHGetKnownFolderPath -
    anders als HOME/Downloads bleibt das auch richtig, wenn Windows den
    Ordner auf einen anderen Platz umgeleitet hat."""
    pfad_zeiger = ctypes.c_wchar_p()
    rueckgabe = ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(_FOLDERID_DOWNLOADS), 0, None, ctypes.byref(pfad_zeiger)
    )
    if rueckgabe != 0 or not pfad_zeiger.value:
        raise RuntimeError("Downloads-Ordner liess sich nicht ermitteln.")
    try:
        return Path(pfad_zeiger.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(pfad_zeiger)


def _in_downloads_ablegen(png_daten: bytes) -> Path:
    """Schreibt die PNG-Bytes unter immer demselben Namen in den
    Downloads-Ordner - vorhandene Datei wird ueberschrieben, Robert muss
    nie suchen."""
    ziel = _downloads_ordner() / DOWNLOADS_DATEINAME
    ziel.write_bytes(png_daten)
    return ziel


# ---------------------------------------------------------------------------
# Variante B - Zwischenablage, mit angehaltenem Waechter
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _waechter_pausiert():
    """Haelt CWBs Zwischenablage-Waechter (core/ablagewaechter.py) ueber
    dessen bestehenden Schalter in einstellungen.json an, solange der Block
    laeuft, und setzt ihn danach auf den vorherigen Wert zurueck. Der
    Waechter liest die Einstellung bei jedem Blick frisch - dieses Skript
    muss dafuer nicht mit dem laufenden CWB-Prozess sprechen."""
    werte = einstellungen_lesen()
    vorher = werte.get(WAECHTER_SCHLUESSEL, True)
    werte[WAECHTER_SCHLUESSEL] = False
    einstellungen_schreiben(werte)
    log.info("Zwischenablage-Wächter für den Screenshot-Vorgang angehalten")
    try:
        yield
    finally:
        werte = einstellungen_lesen()
        werte[WAECHTER_SCHLUESSEL] = vorher
        einstellungen_schreiben(werte)
        log.info("Zwischenablage-Wächter-Schalter zurückgesetzt (%s)", vorher)


def _screenshot_datei_schreiben(png_daten: bytes) -> str:
    """Schreibt die PNG-Bytes in eine temporaere Datei und gibt deren Pfad
    zurueck. Getrennt vom Zwischenablage-Schritt: adb-Abruf und
    Windows-Zwischenablage sind zwei unabhaengige technische Wege."""
    datei = tempfile.NamedTemporaryFile(
        prefix="cwb_android_screenshot_", suffix=".png", delete=False
    )
    try:
        datei.write(png_daten)
    finally:
        datei.close()
    return datei.name


def _datei_in_zwischenablage(pfad: str) -> bool:
    """Legt die fertige Bilddatei per eigenstaendigem PowerShell-Prozess in
    die Windows-Zwischenablage - unabhaengig von Qt/QClipboard.
    Clipboard.SetImage() ruft intern SetDataObject(image, copy: true) auf
    und uebergibt die Daten damit sofort an Windows (OleSetClipboard +
    OleFlushClipboard), das Bild bleibt daher auch nach Prozessende in der
    Zwischenablage."""
    befehl = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        f"$bild = [System.Drawing.Image]::FromFile('{pfad}'); "
        "[System.Windows.Forms.Clipboard]::SetImage($bild); "
        "$bild.Dispose(); "
        "if ([System.Windows.Forms.Clipboard]::ContainsImage()) "
        "{ Write-Output 'JA' } else { Write-Output 'NEIN' }"
    )
    try:
        ergebnis = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", befehl],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as fehler:
        log.error("Zwischenablage-PowerShell fehlgeschlagen: %s", fehler)
        return False
    if ergebnis.returncode != 0:
        meldung = ergebnis.stderr.decode("utf-8", "replace").strip()
        log.error("Zwischenablage-PowerShell-Fehler: %s", meldung)
        return False
    return b"JA" in ergebnis.stdout


def _mit_wiederholung_in_zwischenablage(pfad: str) -> bool:
    """Versucht das Ablegen mehrfach mit steigender Wartezeit, falls ein
    anderer Prozess die Zwischenablage kurzzeitig blockiert."""
    for versuch in range(1, ZWISCHENABLAGE_VERSUCHE + 1):
        if _datei_in_zwischenablage(pfad):
            if versuch > 1:
                log.info("Bild erst im %d. Versuch in der Zwischenablage angekommen", versuch)
            return True
        if versuch < ZWISCHENABLAGE_VERSUCHE:
            wartezeit = ZWISCHENABLAGE_WARTE_BASIS_S * versuch
            log.warning(
                "Zwischenablage-Versuch %d: Bild kam nicht an, warte %.2fs", versuch, wartezeit
            )
            time.sleep(wartezeit)
    log.error(
        "Bild nach %d Versuchen nicht in die Zwischenablage gelegt", ZWISCHENABLAGE_VERSUCHE
    )
    return False


def _ueber_zwischenablage(png_daten: bytes) -> bool:
    pfad = _screenshot_datei_schreiben(png_daten)
    try:
        with _waechter_pausiert():
            return _mit_wiederholung_in_zwischenablage(pfad)
    finally:
        try:
            os.remove(pfad)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Android-Screenshot fuer CWB")
    parser.add_argument(
        "--zwischenablage",
        action="store_true",
        help="Bild zusaetzlich zur Zwischenablage legen (Variante B) statt nur in Downloads",
    )
    argumente = parser.parse_args()

    try:
        png_daten = _screenshot_holen()
    except RuntimeError as fehler:
        log.error("Android-Screenshot nicht geholt: %s", fehler)
        print(f"FEHLER: {fehler}")
        return 1

    breite, hoehe = _png_masse(png_daten)

    if argumente.zwischenablage:
        if not _ueber_zwischenablage(png_daten):
            print(
                "FEHLER: Bild kam trotz mehrerer Versuche nicht in der Zwischenablage an. "
                "Vermutlich haelt ein anderer Prozess die Zwischenablage laenger blockiert "
                "(OneDrive-Synchronisierung oder ein anderes Cloud-/Clipboard-Werkzeug) - "
                "kein Fehler in diesem Skript, siehe Log."
            )
            return 1
        log.info("Android-Screenshot in die Zwischenablage gelegt (%dx%d)", breite, hoehe)
        print(f"Screenshot in die Zwischenablage gelegt ({breite}x{hoehe}).")
        return 0

    try:
        ziel = _in_downloads_ablegen(png_daten)
    except (RuntimeError, OSError) as fehler:
        log.error("Screenshot nicht in Downloads ablegbar: %s", fehler)
        print(f"FEHLER: {fehler}")
        return 1

    log.info("Android-Screenshot nach %s geschrieben (%dx%d)", ziel, breite, hoehe)
    print(f"Screenshot liegt in Downloads: {ziel} ({breite}x{hoehe}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
