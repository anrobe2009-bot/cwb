"""
CWB - Code Workbench
Android-Screenshot direkt als Bild in die Windows-Zwischenablage: ersetzt
"adb pull" und manuelles Hochladen. Ruft `adb exec-out screencap -p` auf dem
verbundenen Android-Geraet auf und legt das PNG als echtes Bild in die
Zwischenablage - mit Strg+V direkt in einen Chat einfuegbar.

Eigenstaendiges Kommandozeilenwerkzeug. Aus dem Projekt CWB selbst per
#RUN#-Befehl:

    #run# python core\\android_screenshot.py

Aus JEDEM anderen Projekt heraus (der #RUN#-Befehl laeuft sonst im dort
offenen Projektordner, in dem diese Datei nicht liegt) ueber das
Startskript mit absolutem Pfad in .cwb-werkzeuge, unabhaengig vom offenen
Projekt:

    #run# python C:\\Users\\Entwickler\\.cwb-werkzeuge\\android_screenshot.py

Fuer die Zwischenablage reicht QClipboard.setImage() allein nicht: Qt
uebergibt Bilddaten unter Windows per verzoegertem OLE-Rendering - der
eigentliche Bildtransfer an das Betriebssystem passiert erst, wenn ein
anderer Prozess zugreift oder OleFlushClipboard() das erzwingt. Beendet
sich dieses Skript vorher, ist das Bild nie wirklich angekommen, obwohl
Qt keine Ausnahme meldet. Deshalb wird nach setImage() OleFlushClipboard()
per ctypes aufgerufen. Die Ruecklese-Pruefung darf ausserdem NICHT ueber
dasselbe QClipboard-Objekt laufen, das gerade geschrieben hat - das gibt
auch dann "Erfolg" zurueck, wenn nur Qts interner Cache gefuellt ist, aber
nie etwas an Windows uebergeben wurde. Stattdessen prueft ein eigener
PowerShell-Prozess (System.Windows.Forms.Clipboard.ContainsImage()) die
echte Zwischenablage von aussen.

adb liefert die Bilddaten ueber subprocess als rohe Bytes - anders als eine
PowerShell-Umleitung (">"), die Binaerdaten durch Zeilenende-Ersetzung
beschaedigen kann, kommt hier nichts durch eine Textkodierung.
"""

import ctypes
import logging
import shutil
import subprocess
import sys
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


def _clipboard_hat_bild_extern() -> bool:
    """Prueft unabhaengig von Qt, ob wirklich ein Bild in der Windows-
    Zwischenablage liegt - ueber einen eigenen PowerShell-Prozess und
    System.Windows.Forms.Clipboard, nicht ueber das QClipboard-Objekt, das
    das Bild selbst gesetzt hat. Eine Pruefung mit demselben Objekt wuerde
    auch dann "vorhanden" melden, wenn nur Qts interner Cache gefuellt ist."""
    befehl = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "if ([System.Windows.Forms.Clipboard]::ContainsImage()) "
        "{ Write-Output 'JA' } else { Write-Output 'NEIN' }"
    )
    try:
        ergebnis = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", befehl],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as fehler:
        log.warning("Unabhaengige Zwischenablage-Pruefung fehlgeschlagen: %s", fehler)
        return False
    return b"JA" in ergebnis.stdout


def _bild_in_zwischenablage(png_daten: bytes) -> tuple[bool, int, int]:
    """Legt PNG-Bilddaten als echtes Bild in die Windows-Zwischenablage.
    QClipboard.setImage() uebergibt die Daten unter Windows per verzoegertem
    OLE-Rendering - OleFlushClipboard() erzwingt die sofortige Uebergabe an
    das Betriebssystem, statt darauf zu warten, dass ein anderer Prozess
    zugreift (der dann laengst beendete Python-Prozess koennte gar nicht
    mehr antworten). Geprueft wird ueber einen unabhaengigen, externen
    Prozess (_clipboard_hat_bild_extern), nicht ueber Qt selbst. Bei
    Abweichung wird bis zu ZWISCHENABLAGE_VERSUCHE mal erneut versucht, mit
    steigender Wartezeit."""
    from PySide6.QtGui import QGuiApplication, QImage

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    bild = QImage.fromData(png_daten, "PNG")
    if bild.isNull():
        raise RuntimeError("Die Bilddaten vom Geraet liessen sich nicht lesen.")

    for versuch in range(1, ZWISCHENABLAGE_VERSUCHE + 1):
        QGuiApplication.clipboard().setImage(bild)
        for _ in range(5):
            app.processEvents()
        try:
            ctypes.windll.ole32.OleFlushClipboard()
        except OSError as fehler:
            log.warning("OleFlushClipboard fehlgeschlagen: %s", fehler)
        if _clipboard_hat_bild_extern():
            if versuch > 1:
                log.info("Bild erst im %d. Versuch in der Zwischenablage angekommen", versuch)
            return True, bild.width(), bild.height()
        if versuch < ZWISCHENABLAGE_VERSUCHE:
            wartezeit = ZWISCHENABLAGE_WARTE_BASIS_S * versuch
            log.warning(
                "Zwischenablage-Versuch %d: Bild kam nicht an, warte %.2fs", versuch, wartezeit
            )
            time.sleep(wartezeit)
    log.error(
        "Bild nach %d Versuchen nicht in die Zwischenablage gelegt", ZWISCHENABLAGE_VERSUCHE
    )
    return False, bild.width(), bild.height()


def main() -> int:
    try:
        png_daten = _screenshot_holen()
    except RuntimeError as fehler:
        log.error("Android-Screenshot nicht geholt: %s", fehler)
        print(f"FEHLER: {fehler}")
        return 1

    try:
        erfolg, breite, hoehe = _bild_in_zwischenablage(png_daten)
    except RuntimeError as fehler:
        log.error("Screenshot nicht in die Zwischenablage gelegt: %s", fehler)
        print(f"FEHLER: {fehler}")
        return 1

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
