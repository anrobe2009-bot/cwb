"""
CWB - Code Workbench
Waechter-Anzeige: eigenstaendiger Prozess, unabhaengig vom Hauptfenster.

Ein haengendes oder abgestuerztes CWB kann sich nicht mehr selbst anzeigen -
deshalb dieser zweite, kleine Prozess. core/fenster.py schreibt jede Sekunde
einen Herzschlag nach STATUS_DATEI (core/pfade.py): Zeitstempel, PID, Zustand
("arbeitet"/"bereit"/"beendet"), kurze Auftragsbezeichnung sowie (Block 82)
die globalen Bildschirmkoordinaten/Groesse des Waechter-Platzhalters in der
Statusleiste ueber dem Ausgabefeld und ob CWB gerade minimiert ist. Dieser
Prozess liest die Datei einmal pro Sekunde und legt einen kleinen, rahmenlosen,
immer oben liegenden Farbknopf passgenau auf diesen Platzhalter - Robert
erkennt nur noch grosse Farbflaechen, keine Buchstaben, darum traegt allein
die Farbe die Information; Name/Zustand stehen als Tooltip und
Barrierefreiheitsname dahinter, fuer Screenreader und sehende Mitnutzer:

  GRUEN  "Arbeitet"            - Herzschlag juenger als 5 s, Datei sagt "arbeitet"
  BLAU   "Bereit"              - Herzschlag juenger als 5 s, Datei sagt "bereit"
  ROT    "Haengt"              - Herzschlag aelter als 15 s, Prozess lebt noch
  ROT    "Abgestuerzt"         - Herzschlag aelter als 15 s, Prozess ist weg

Dazwischen (5 bis 15 s) bleibt der zuletzt bekannte Zustand stehen - kein
Alarm fuer eine einzelne verzoegerte Sekunde.

Ist CWB minimiert, blendet sich der Knopf aus - ausser bei Haengt/
Abgestuerzt: dann bleibt er an der zuletzt bekannten Stelle sichtbar, denn
genau dann ist die Anzeige am wichtigsten. Angedockt laesst er sich nicht
mehr mit der Maus verschieben (vorher, als freischwebendes Fenster, schon) -
seine Stelle bestimmt allein CWB ueber den Platzhalter.

Gestartet wird dieser Prozess von core/fenster.py (main(), Schalter
--waechter-anzeige) ueber denselben Startweg wie CWB selbst - das ist im
gepackten Zustand (sys.frozen) wichtig, siehe _waechter_befehl() dort.
Beendet sich von selbst, sobald CWB regulaer schliesst (Zustand "beendet")
oder bereits ein anderer Waechter laeuft (WAECHTER_SPERR_DATEI).
"""

import ctypes
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

try:
    from .pfade import CWB_WURZEL, STATUS_DATEI, WAECHTER_SPERR_DATEI
    from .sprache import Sprecher
except ImportError:
    from pfade import CWB_WURZEL, STATUS_DATEI, WAECHTER_SPERR_DATEI
    from sprache import Sprecher

log = logging.getLogger("cwb.waechter_anzeige")

# Siehe Moduldoku oben: die beiden Schwellen aus Roberts Auftrag.
HERZSCHLAG_FRISCH_SEKUNDEN = 5
HERZSCHLAG_HAENGT_SEKUNDEN = 15
PRUEF_INTERVALL_MS = 1000

HAENGER_SKRIPT = Path.home() / ".cwb-werkzeuge" / "haenger_aufzeichnen.ps1"

WORT_JE_ZUSTAND = {
    "arbeitet": "Arbeitet",
    "bereit": "Bereit",
    "haengt": "Hängt",
    "abgestuerzt": "Abgestürzt",
}

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


def _prozess_lebt(pid: int) -> bool:
    """True, wenn unter dieser Prozessnummer wirklich noch ein laufender
    Prozess steckt - nicht nur ein (nach Programmende moeglicherweise
    wiederverwendeter) Eintrag."""
    if pid <= 0:
        return False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


# ---------------------------------------------------------------------------
# Nur ein Waechter gleichzeitig
# ---------------------------------------------------------------------------

def _bereits_ein_waechter() -> bool:
    try:
        pid = int(WAECHTER_SPERR_DATEI.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return _prozess_lebt(pid)


def _sperre_schreiben() -> None:
    try:
        WAECHTER_SPERR_DATEI.parent.mkdir(parents=True, exist_ok=True)
        WAECHTER_SPERR_DATEI.write_text(str(os.getpid()), encoding="utf-8")
    except OSError as fehler:
        log.error("Sperrdatei fuer Waechter nicht schreibbar: %s", fehler)


def _sperre_entfernen() -> None:
    try:
        WAECHTER_SPERR_DATEI.unlink(missing_ok=True)
    except OSError as fehler:
        log.error("Sperrdatei fuer Waechter nicht loeschbar: %s", fehler)


def _status_lesen() -> dict | None:
    """Eigener, unabhaengiger Lesezugriff auf STATUS_DATEI fuer die
    Platzhalter-Geometrie - getrennt von Waechter.zustand_ermitteln() (das
    die Datei fuer die Zustandsentscheidung selbst liest), damit beide sich
    nicht gegenseitig Parameter aufzwingen."""
    try:
        return json.loads(STATUS_DATEI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Das Fenster selbst
# ---------------------------------------------------------------------------

class WaechterKnopf(QWidget):
    """Kleiner, rahmenloser, immer oben liegender Farbknopf - traegt keinen
    eigenen Text mehr (Block 82): die Farbe ist der einzige Kanal, Wort und
    Erklaerung stehen als Tooltip/Barrierefreiheitsname dahinter. Aussehen
    kommt aus waechter.qss (Farben haengen am Attribut 'zustand', wie
    core/fenster.py das beim Aktivitaetsbalken schon macht) - hier in Python
    nur Geometrie und Zustand, kein Ziehen mehr: die Stelle bestimmt CWB
    ueber den Platzhalter in der Statusleiste (andocken())."""

    def __init__(self, sprecher: Sprecher):
        super().__init__()
        self.sprecher = sprecher
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setObjectName("waechterKnopf")
        self.setAccessibleName("CWB-Zustand")
        self.setWindowTitle("CWB")

        try:
            qss = (CWB_WURZEL / "waechter.qss").read_text(encoding="utf-8")
            self.setStyleSheet(qss)
        except OSError as fehler:
            log.error("waechter.qss nicht lesbar: %s", fehler)

        self._zustand = ""
        self._haenger_ausgeloest = False
        self._letzte_geometrie: tuple[int, int, int, int] | None = None

        # Vorlaeufige Stelle, bis der erste Herzschlag mit Platzhalter-
        # Geometrie da ist - keine feste Pixelgroesse danach, dann kommt
        # Groesse und Stelle allein von CWB (andocken()).
        bildschirm = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(28, 28)
        self.move(bildschirm.right() - 48, bildschirm.top() + 20)

    # -- Geometrie ----------------------------------------------------------

    def andocken(self, x: int, y: int, breite: int, hoehe: int) -> None:
        """Legt den Knopf passgenau auf den gemeldeten Platzhalter und merkt
        sich die Stelle - fuer an_letzter_stelle_zeigen(), falls CWB als
        naechstes haengt oder minimiert wird."""
        self._letzte_geometrie = (x, y, breite, hoehe)
        self.setGeometry(x, y, breite, hoehe)
        if not self.isVisible():
            self.show()

    def an_letzter_stelle_zeigen(self) -> None:
        """Haengt/Abgestuerzt bleiben sichtbar, auch wenn CWB als minimiert
        gemeldet ist oder gar nichts mehr meldet - genau dann ist die
        Anzeige am wichtigsten. Ohne jede bisher bekannte Geometrie (direkt
        nach dem eigenen Start) bleibt die vorlaeufige Stelle von __init__."""
        if self._letzte_geometrie is not None:
            self.setGeometry(*self._letzte_geometrie)
        if not self.isVisible():
            self.show()

    # -- Zustand --------------------------------------------------------------

    def zustand_setzen(self, zustand: str, hinweis: str = "") -> None:
        """Faerbt den Knopf und meldet einen Wechsel per Ton bzw. - nur bei
        Haengt/Abgestuerzt - per kurzer Ansage. Wort und Hinweis stehen als
        Tooltip/Barrierefreiheitsname, nie als sichtbarer Text."""
        wort = WORT_JE_ZUSTAND.get(zustand, zustand)
        self.setToolTip(hinweis or wort)
        self.setAccessibleDescription(f"{wort}. {hinweis}" if hinweis else wort)
        if zustand == self._zustand:
            return
        self._zustand = zustand
        self.setProperty("zustand", zustand)
        self.style().polish(self)
        self._melden(zustand)

    def _melden(self, zustand: str) -> None:
        if zustand == "arbeitet":
            self.sprecher.ton("waechter_arbeitet")
        elif zustand == "bereit":
            self.sprecher.ton("bereit")
        elif zustand == "haengt":
            self.sprecher.ton("wartet")
            self.sprecher.sprich("CWB hängt.", art="fehler")
            self._haenger_aufzeichnen()
        elif zustand == "abgestuerzt":
            self.sprecher.ton("fehler")
            self.sprecher.sprich("CWB ist abgestürzt.", art="fehler")
        if zustand != "haengt":
            self._haenger_ausgeloest = False

    def _haenger_aufzeichnen(self) -> None:
        """Loest die vorhandene py-spy-Aufzeichnung einmal pro Haenger aus -
        ohne dass Robert dafuer Strg+Alt+H druecken muss."""
        if self._haenger_ausgeloest:
            return
        self._haenger_ausgeloest = True
        if not HAENGER_SKRIPT.is_file():
            log.warning("Haenger-Aufzeichnung nicht gefunden: %s", HAENGER_SKRIPT)
            return
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(HAENGER_SKRIPT)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log.info("Haenger-Aufzeichnung ausgeloest: %s", HAENGER_SKRIPT)
        except OSError as fehler:
            log.error("Haenger-Aufzeichnung nicht startbar: %s", fehler)


# ---------------------------------------------------------------------------
# Herzschlag lesen und bewerten
# ---------------------------------------------------------------------------

class Waechter:
    """Liest STATUS_DATEI einmal pro Sekunde und entscheidet den Zustand -
    von der Darstellung getrennt, damit sich die Entscheidung fuer sich
    pruefen laesst (siehe core/test_waechter_anzeige.py)."""

    def __init__(self, fenster: WaechterKnopf):
        self.fenster = fenster
        self._letzter_bekannter = "bereit"
        self._start = time.monotonic()

    def pruefen(self) -> None:
        zustand, hinweis = self.zustand_ermitteln(time.time(), time.monotonic())
        if zustand == "beendet":
            log.info("CWB regulaer beendet, Waechter beendet sich ebenfalls")
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return
        self.fenster.zustand_setzen(zustand, hinweis)
        self._andocken_oder_ausblenden(zustand)

    def zustand_ermitteln(self, jetzt_epoche: float, jetzt_monoton: float) -> tuple[str, str]:
        try:
            daten = json.loads(STATUS_DATEI.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Kurz nach dem eigenen Start normal (CWB schreibt den ersten
            # Herzschlag erst gleich nach dem Start) - danach ein Zeichen,
            # dass CWB verschwunden ist, ohne sich regulaer zu beenden.
            if jetzt_monoton - self._start < HERZSCHLAG_HAENGT_SEKUNDEN:
                return "bereit", "Wartet auf CWB …"
            return "abgestuerzt", "Kein Herzschlag seit dem Start des Wächters."

        rohzustand = str(daten.get("zustand", ""))
        if rohzustand == "beendet":
            return "beendet", ""

        pid = int(daten.get("pid", 0) or 0)
        alter = jetzt_epoche - float(daten.get("zeit", 0) or 0)
        auftrag = str(daten.get("auftrag", "") or "")

        if alter < HERZSCHLAG_FRISCH_SEKUNDEN:
            self._letzter_bekannter = rohzustand if rohzustand in WORT_JE_ZUSTAND else "bereit"
            hinweis = f"Auftrag: {auftrag}" if auftrag else ""
            return self._letzter_bekannter, hinweis

        if alter < HERZSCHLAG_HAENGT_SEKUNDEN:
            # Luecke zwischen frisch und haengt: letzten bekannten Zustand
            # zeigen, noch kein Alarm fuer eine einzelne verspaetete Sekunde.
            return self._letzter_bekannter, ""

        if _prozess_lebt(pid):
            return "haengt", f"Kein Herzschlag seit {int(alter)} Sekunden."
        return "abgestuerzt", f"Prozess {pid} existiert nicht mehr."

    def _andocken_oder_ausblenden(self, zustand: str) -> None:
        """Legt den Knopf auf den von CWB gemeldeten Platzhalter oder
        blendet ihn aus - Block 82, Punkt 3. Haengt/Abgestuerzt bleiben an
        der letzten bekannten Stelle sichtbar, egal was die Datei zuletzt
        zur Geometrie sagt (CWB selbst haengt ja gerade, seine letzte
        Meldung kann veraltet sein)."""
        if zustand in ("haengt", "abgestuerzt"):
            self.fenster.an_letzter_stelle_zeigen()
            return
        daten = _status_lesen()
        if daten is None or daten.get("minimiert", True):
            self.fenster.hide()
            return
        try:
            x, y = int(daten["x"]), int(daten["y"])
            breite, hoehe = int(daten["breite"]), int(daten["hoehe"])
        except (KeyError, TypeError, ValueError):
            self.fenster.hide()
            return
        self.fenster.andocken(x, y, breite, hoehe)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

def main() -> None:
    if _bereits_ein_waechter():
        log.info("Waechter-Anzeige laeuft bereits in einem anderen Prozess, beende mich")
        return
    _sperre_schreiben()
    import atexit
    atexit.register(_sperre_entfernen)

    anwendung = QApplication(sys.argv)
    sprecher = Sprecher()
    fenster = WaechterKnopf(sprecher)
    fenster.show()

    waechter = Waechter(fenster)
    uhr = QTimer(anwendung)
    uhr.setInterval(PRUEF_INTERVALL_MS)
    uhr.timeout.connect(waechter.pruefen)
    uhr.start()
    waechter.pruefen()

    sys.exit(anwendung.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as fehler:  # noqa: BLE001
        log.exception("Waechter-Anzeige abgestürzt: %s", fehler)
