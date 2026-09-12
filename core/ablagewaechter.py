"""
CWB - Code Workbench
Waechter ueber der Zwischenablage.

Sieht alle zwei Sekunden nach, ob in der Zwischenablage ein Text steht,
dessen erste Zeile eine der drei Markierungen ist (#code#, #run#, #admin#).
Nur dann wird der Text uebernommen und abgeschickt.

Sobald ein markierter Auftrag uebernommen ist, leert der Waechter die
Zwischenablage. Damit kann derselbe Text nie zweimal auslösen - es gibt
keine Pruefwerte und keine Zeitgrenzen, die Zwischenablage selbst ist die
einzige Sperre. Alles ohne Markierung bleibt unberuehrt: es wird weder
gelesen noch geloescht noch protokolliert.

Dieses Modul kennt fenster.py nicht. Was "Markierung" heisst, ob der
Waechter eingeschaltet ist und was mit einem Auftrag geschieht, kommt
ausschliesslich ueber die drei Funktionen im Aufruf.

QClipboard.text() fragt unter Windows immer die volle Zwischenablage per
OLE ab (OleGetClipboard), egal was tatsaechlich drinliegt - auch wenn dort
gar kein Text steht, sondern zum Beispiel ein Bild, das ein anderes
Programm gerade erst hineinlegt. Faellt dieser Abruf zeitlich mit einem
fremden Schreibvorgang zusammen, kann dessen OleFlushClipboard() mit
CLIPBRD_E_CANT_OPEN (-2147221040) scheitern. Deshalb fragt der Waechter
vorab ueber Win32 IsClipboardFormatAvailable() nur die Formatliste ab -
das braucht laut MSDN keinen exklusiven Zugriff (kein OpenClipboard) - und
ruft QClipboard.text() nur noch auf, wenn dort ueberhaupt ein Textformat
gemeldet wird. Liegt kein Text vor, etwa weil gerade ein Bild dort liegt,
wird die Zwischenablage in diesem Durchlauf gar nicht erst beruehrt.
"""

import ctypes
import logging

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QGuiApplication

try:
    from .pfade import log_einrichten
except ImportError:
    from pfade import log_einrichten

log_einrichten()
log = logging.getLogger("cwb.ablagewaechter")

# Abstand zwischen zwei Blicken in die Zwischenablage.
PRUEF_ABSTAND_MS = 2000

# Windows-Formatkennungen fuer die verbreiteten Textformate (winuser.h).
_CF_TEXT = 1
_CF_UNICODETEXT = 13


def _text_liegt_an() -> bool:
    """Fragt nur die Formatliste der Zwischenablage ab, ohne sie zu oeffnen.

    IsClipboardFormatAvailable() braucht laut MSDN keinen exklusiven
    Zugriff - anders als QClipboard.text(), das intern immer OleGetClipboard()
    aufruft. So laesst sich vorab erkennen, ob ueberhaupt Text vorliegt,
    ohne die Zwischenablage anzufassen, wenn dort zum Beispiel ein Bild
    liegt."""
    try:
        pruefen = ctypes.windll.user32.IsClipboardFormatAvailable
        return bool(pruefen(_CF_UNICODETEXT) or pruefen(_CF_TEXT))
    except OSError as fehler:
        log.warning("Formatpruefung der Zwischenablage fehlgeschlagen: %s", fehler)
        return False


class Zwischenablagewaechter(QObject):
    """Prueft die Zwischenablage im Hintergrund auf markierte Auftraege.

    `markierung_erkennen` zerlegt einen Text in (Art, Inhalt),
    `aktiv` sagt vor jedem Blick, ob der Waechter eingeschaltet ist,
    `ausfuehren` bekommt Art und Inhalt eines erkannten Auftrags
    ("code", "run" oder "admin").
    """

    def __init__(self, markierung_erkennen, aktiv, ausfuehren, eltern=None):
        super().__init__(eltern)
        self._markierung_erkennen = markierung_erkennen
        self._aktiv = aktiv
        self._ausfuehren = ausfuehren
        # Fehler beim Lesen der Ablage nur einmal ins Log, nicht alle zwei
        # Sekunden erneut.
        self._lesefehler_gemeldet = False
        self._uhr = QTimer(self)
        self._uhr.setInterval(PRUEF_ABSTAND_MS)
        self._uhr.timeout.connect(self._nachsehen)

    def starten(self) -> None:
        if not self._uhr.isActive():
            self._uhr.start()
            log.info("Zwischenablage-Wächter läuft, Abstand %d ms", PRUEF_ABSTAND_MS)

    def anhalten(self) -> None:
        self._uhr.stop()
        log.info("Zwischenablage-Wächter angehalten")

    def _eingeschaltet(self) -> bool:
        try:
            return bool(self._aktiv())
        except Exception as fehler:  # noqa: BLE001
            log.exception("Einstellung des Wächters nicht lesbar: %s", fehler)
            return False

    def _nachsehen(self) -> None:
        """Ein Blick in die Zwischenablage. Ohne Markierung endet er still."""
        if not self._eingeschaltet():
            return
        if not _text_liegt_an():
            # Kein Textformat gemeldet - liegt dort z.B. gerade ein Bild
            # eines anderen Programms, wird die Zwischenablage in diesem
            # Durchlauf gar nicht erst angefasst.
            return
        try:
            zwischenablage = QGuiApplication.clipboard()
            text = zwischenablage.text()
        except Exception as fehler:  # noqa: BLE001
            if not self._lesefehler_gemeldet:
                log.exception("Zwischenablage nicht lesbar: %s", fehler)
                self._lesefehler_gemeldet = True
            return
        self._lesefehler_gemeldet = False
        if not text:
            return
        try:
            art, inhalt = self._markierung_erkennen(text)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Markierung nicht prüfbar: %s", fehler)
            return
        if art not in ("code", "run", "admin") or not inhalt:
            # Kein markierter Auftrag. Hier endet jede Beruehrung mit dem
            # Text: nichts wird behalten und nichts ins Log geschrieben.
            return
        log.info("Wächter: markierter Auftrag erkannt (%s), %d Zeichen", art, len(inhalt))
        # Erst die Zwischenablage leeren, dann ausfuehren: so kann derselbe
        # Text nicht ein zweites Mal auslösen, auch wenn der Auftrag laenger
        # braucht als der naechste Blick des Timers.
        try:
            zwischenablage.clear()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zwischenablage nicht leerbar: %s", fehler)
        try:
            self._ausfuehren(art, inhalt)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Auftrag aus der Zwischenablage gescheitert: %s", fehler)
