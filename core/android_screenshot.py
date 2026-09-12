"""
CWB - Code Workbench
Android-Screenshot direkt als Bild in die Windows-Zwischenablage: ersetzt
"adb pull" und manuelles Hochladen.

Zwei sauber getrennte Schritte, bewusst ohne Qt/QClipboard fuer die
Zwischenablage - trotz OleFlushClipboard() und externer Pruefung kam bei
Robert ueber Qt nie ein Bild an, nur Text:

1. `adb exec-out screencap -p` liefert die rohen PNG-Bytes, die als
   temporaere Datei auf die Platte geschrieben werden. Dieser Weg laeuft
   bei Robert seit Stunden zuverlaessig.
2. Ein eigenstaendiger PowerShell-Prozess laedt genau diese Datei und legt
   sie ueber System.Windows.Forms.Clipboard als echtes Bild ab. .NETs
   Clipboard.SetImage() ruft intern SetDataObject(image, copy: true) auf,
   was die Daten sofort an Windows uebergibt (OleSetClipboard +
   OleFlushClipboard) - das Bild bleibt daher auch nach Prozessende in der
   Zwischenablage. Mit Strg+V direkt in einen Chat einfuegbar.

Eigenstaendiges Kommandozeilenwerkzeug. Aus dem Projekt CWB selbst per
#RUN#-Befehl:

    #run# python core\\android_screenshot.py

Aus JEDEM anderen Projekt heraus (der #RUN#-Befehl laeuft sonst im dort
offenen Projektordner, in dem diese Datei nicht liegt) ueber das
Startskript mit absolutem Pfad in .cwb-werkzeuge, unabhaengig vom offenen
Projekt:

    #run# python C:\\Users\\Entwickler\\.cwb-werkzeuge\\android_screenshot.py

adb liefert die Bilddaten ueber subprocess als rohe Bytes - anders als eine
PowerShell-Umleitung (">"), die Binaerdaten durch Zeilenende-Ersetzung
beschaedigen kann, kommt hier nichts durch eine Textkodierung.
"""

import logging
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time

try:
    from .pfade import log_einrichten
except ImportError:
    from pfade import log_einrichten

log_einrichten()
log = logging.getLogger("cwb.android_screenshot")

ZEITLIMIT_S = 20

# Anzahl Versuche und Basis-Wartezeit fuer das Zwischenablage-Schreiben -
# dieselben Werte wie in core/zielfenster.py (ZWISCHENABLAGE_VERSUCHE).
ZWISCHENABLAGE_VERSUCHE = 5
ZWISCHENABLAGE_WARTE_BASIS_S = 0.15


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
    die Windows-Zwischenablage - unabhaengig von Qt/QClipboard, das bei
    Robert trotz OleFlushClipboard() nicht zuverlaessig ankam.
    Clipboard.SetImage() ruft intern SetDataObject(image, copy: true) auf
    und uebergibt die Daten damit sofort an Windows."""
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


def main() -> int:
    try:
        png_daten = _screenshot_holen()
    except RuntimeError as fehler:
        log.error("Android-Screenshot nicht geholt: %s", fehler)
        print(f"FEHLER: {fehler}")
        return 1

    breite, hoehe = _png_masse(png_daten)
    pfad = _screenshot_datei_schreiben(png_daten)
    try:
        erfolg = _mit_wiederholung_in_zwischenablage(pfad)
    finally:
        try:
            os.remove(pfad)
        except OSError:
            pass

    if not erfolg:
        print(
            "FEHLER: Bild kam trotz mehrerer Versuche nicht in der Zwischenablage an. "
            "Vermutlich haelt ein anderer Prozess die Zwischenablage laenger blockiert "
            "(Windows-Zwischenablageverlauf Win+V, OneDrive-Synchronisierung oder ein "
            "anderes Cloud-/Clipboard-Werkzeug) - kein Fehler in diesem Skript, siehe Log."
        )
        return 1

    log.info("Android-Screenshot in die Zwischenablage gelegt (%dx%d)", breite, hoehe)
    print(f"Screenshot in die Zwischenablage gelegt ({breite}x{hoehe}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
