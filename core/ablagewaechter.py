"""
CWB - Code Workbench
Waechter ueber der Zwischenablage.

Sieht alle zwei Sekunden nach, ob in der Zwischenablage ein Text steht,
dessen erste Zeile die Code-Markierung ist. Nur dann wird der Text
uebernommen und abgeschickt.

Sobald ein markierter Auftrag uebernommen ist, leert der Waechter die
Zwischenablage. Damit kann derselbe Text nie zweimal auslösen - es gibt
keine Pruefwerte und keine Zeitgrenzen, die Zwischenablage selbst ist die
einzige Sperre. Alles ohne Markierung bleibt unberuehrt: es wird weder
gelesen noch geloescht noch protokolliert.

Dieses Modul kennt fenster.py nicht. Was "Markierung" heisst, ob der
Waechter eingeschaltet ist und was mit einem Auftrag geschieht, kommt
ausschliesslich ueber die drei Funktionen im Aufruf.
"""

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


class Zwischenablagewaechter(QObject):
    """Prueft die Zwischenablage im Hintergrund auf markierte Auftraege.

    `markierung_erkennen` zerlegt einen Text in (Art, Inhalt),
    `aktiv` sagt vor jedem Blick, ob der Waechter eingeschaltet ist,
    `ausfuehren` bekommt den Inhalt eines erkannten Code-Auftrags.
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
        if art != "code" or not inhalt:
            # Kein markierter Auftrag. Hier endet jede Beruehrung mit dem
            # Text: nichts wird behalten und nichts ins Log geschrieben.
            return
        log.info("Wächter: markierter Auftrag erkannt, %d Zeichen", len(inhalt))
        # Erst die Zwischenablage leeren, dann ausfuehren: so kann derselbe
        # Text nicht ein zweites Mal auslösen, auch wenn der Auftrag laenger
        # braucht als der naechste Blick des Timers.
        try:
            zwischenablage.clear()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zwischenablage nicht leerbar: %s", fehler)
        try:
            self._ausfuehren(inhalt)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Auftrag aus der Zwischenablage gescheitert: %s", fehler)
