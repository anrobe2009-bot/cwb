"""
CWB - Code Workbench
Waechter ueber der Zwischenablage.

Sieht alle zwei Sekunden nach, ob in der Zwischenablage ein Text steht,
dessen erste Zeile die Code-Markierung ist. Nur dann wird der Text
uebernommen und abgeschickt.

Alles ohne Markierung wird sofort fallengelassen: es wird weder ausgegeben,
noch protokolliert, noch gemerkt. Vom Text bleibt in keinem Fall ein Rest
im Speicher des Waechters - gemerkt werden nur zwei Pruefwerte: der des
zuletzt ausgefuehrten Auftrags und der des zuletzt gesehenen Ablageinhalts.
Zeit spielt keine Rolle. Derselbe Text laeuft erst wieder, wenn die
Zwischenablage zwischendurch etwas anderes enthielt oder ein Auftrag von
anderer Seite dazwischenkam.

Dieses Modul kennt fenster.py nicht. Was "Markierung" heisst, ob der
Waechter eingeschaltet ist und was mit einem Auftrag geschieht, kommt
ausschliesslich ueber die drei Funktionen im Aufruf.
"""

import hashlib
import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QGuiApplication

CWB_WURZEL = Path(__file__).resolve().parent.parent
LOG_DATEI = CWB_WURZEL / "cwb_fehler.log"

logging.basicConfig(
    filename=str(LOG_DATEI),
    filemode="a",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("cwb.ablagewaechter")

# Abstand zwischen zwei Blicken in die Zwischenablage.
PRUEF_ABSTAND_MS = 2000


def _pruefwert(text: str) -> str:
    """Pruefwert eines Textes. Der Text selbst wird nirgends behalten."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Zwischenablagewaechter(QObject):
    """Prueft die Zwischenablage im Hintergrund auf markierte Auftraege.

    `markierung_erkennen` zerlegt einen Text in (Art, Inhalt),
    `aktiv` sagt vor jedem Blick, ob der Waechter eingeschaltet ist,
    `ausfuehren` bekommt den Inhalt eines erkannten Code-Auftrags.
    """

    def __init__(self, markierung_erkennen, aktiv, ausfuehren, eltern=None,
                 pruefwert_lesen=None, pruefwert_merken=None):
        super().__init__(eltern)
        self._markierung_erkennen = markierung_erkennen
        self._aktiv = aktiv
        self._ausfuehren = ausfuehren
        self._pruefwert_merken = pruefwert_merken
        # Pruefwert des zuletzt ausgefuehrten Auftrags, nicht sein Text. Er
        # kommt aus dem Speicher des Aufrufers, damit ein vor dem Neustart
        # ausgefuehrter Text nicht gleich wieder laeuft - die Zwischenablage
        # steht nach dem Neustart ja unveraendert da. Die Sperre laeuft nicht
        # ab; sie faellt erst, wenn ein anderer Ablageinhalt dazwischenliegt.
        self._zuletzt = ""
        # Pruefwert des zuletzt gesehenen Ablageinhalts. None heisst: noch
        # kein Blick getan.
        self._letzter_inhalt = None
        if pruefwert_lesen is not None:
            try:
                self._zuletzt = str(pruefwert_lesen() or "")
            except Exception as fehler:  # noqa: BLE001
                log.exception("Gemerkter Prüfwert nicht lesbar: %s", fehler)
            if self._zuletzt:
                log.info("Wächter kennt den letzten Auftrag: %s", self._zuletzt[:12])
        # Beleg, welche Fassung dieser Datei wirklich laeuft. Ohne ihn laesst
        # sich nicht unterscheiden, ob die Regel greift oder nur ein alter
        # Prozess mit alter Fassung noch offen ist.
        quelle = Path(__file__).resolve()
        log.info(
            "Wächter aus %s (geändert %s), Sperre ohne Zeitgrenze",
            quelle,
            time.strftime("%d.%m.%Y %H:%M:%S",
                          time.localtime(quelle.stat().st_mtime)),
        )
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

    def auftrag_dazwischen(self) -> None:
        """Ein Auftrag von anderer Seite ist gelaufen. Damit ist die Sperre
        aufgehoben: derselbe Text aus der Zwischenablage darf wieder los."""
        if self._zuletzt:
            log.info("Anderer Auftrag dazwischen, Sperre des Wächters aufgehoben")
        self._zuletzt = ""

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
            text = QGuiApplication.clipboard().text()
        except Exception as fehler:  # noqa: BLE001
            if not self._lesefehler_gemeldet:
                log.exception("Zwischenablage nicht lesbar: %s", fehler)
                self._lesefehler_gemeldet = True
            return
        self._lesefehler_gemeldet = False
        # Aenderung des Ablageinhalts erkennen - auch bei unmarkiertem Text,
        # denn auch er ist "etwas anderes dazwischen". Vom Text bleibt dabei
        # nur sein Pruefwert.
        inhaltswert = _pruefwert(text)
        if self._letzter_inhalt is None:
            # Erster Blick nach dem Start. Er hebt die gemerkte Sperre nicht
            # auf, sonst liefe ein vor dem Neustart erledigter Auftrag sofort
            # noch einmal.
            self._letzter_inhalt = inhaltswert
        elif inhaltswert != self._letzter_inhalt:
            self._letzter_inhalt = inhaltswert
            if self._zuletzt:
                log.info("Anderer Ablageinhalt gesehen, Sperre aufgehoben")
            self._zuletzt = ""
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
        pruefwert = _pruefwert(inhalt)
        # Zeit spielt keine Rolle: derselbe Auftrag bleibt gesperrt, solange
        # die Zwischenablage unveraendert daliegt.
        gesperrt = pruefwert == self._zuletzt
        # Jeder Pruefdurchlauf ueber einem markierten Auftrag hinterlaesst
        # eine Zeile: gefundener Pruefwert, gemerkter Pruefwert und die
        # Entscheidung. Der Text selbst steht nie im Log, nur seine Pruefwerte.
        log.info(
            "Prüflauf: gefunden %s, gemerkt %s, Entscheidung %s",
            pruefwert[:12],
            self._zuletzt[:12] or "keiner",
            "abgelehnt (unveränderte Zwischenablage)" if gesperrt else "angenommen",
        )
        if gesperrt:
            return
        self._zuletzt = pruefwert
        if self._pruefwert_merken is not None:
            try:
                self._pruefwert_merken(pruefwert)
            except Exception as fehler:  # noqa: BLE001
                log.exception("Prüfwert nicht sicherbar: %s", fehler)
        log.info(
            "Wächter: markierter Auftrag erkannt, %d Zeichen, Prüfwert %s",
            len(inhalt), pruefwert[:12],
        )
        try:
            self._ausfuehren(inhalt)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Auftrag aus der Zwischenablage gescheitert: %s", fehler)
