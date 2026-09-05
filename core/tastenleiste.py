"""
CWB - Code Workbench
Kachelreihe unter dem Fortschrittsbalken.

Enthaelt nur die staendig gebrauchten Befehle. Jede Kachel ist eine
Schaltflaeche mit eigener Pastellfarbe, einem Symbol und kleinem Text
darunter. Flach und kompakt, die Reihe teilt die Fensterbreite unter sich
auf und hat keine festen Pixelgroessen im Python.

Gestaltung kommt vollstaendig aus stil.qss. Hier steht keine Farbe und
keine Groesse, nur die Nummer der Pastellfarbe je Kachel.

Alle selteneren Befehle bleiben ueber ihre Tastenkuerzel erreichbar,
die Hilfe (F1) liest sie vor.
"""

import logging
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

CWB_WURZEL = Path(__file__).resolve().parent.parent
LOG_DATEI = CWB_WURZEL / "cwb_fehler.log"

logging.basicConfig(
    filename=str(LOG_DATEI),
    filemode="a",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("cwb.tastenleiste")

# Die Ansage bei Mauszeiger liegt nicht mehr hier: sie gilt fuer das ganze
# Fenster und steht in core/zeigeransage.py. Jede Kachel traegt dafuer nur
# ihren Vorlesetext im barrierefreien Namen.


class Kachel(QPushButton):
    """Eine flache Kachel: Symbol oben, kleiner Text darunter.

    Die beiden Beschriftungen sind QLabel innerhalb der Schaltflaeche, damit
    Symbol und Text in stil.qss verschieden gross sein koennen. Sie nehmen
    keine Mausklicks an, jeder Klick landet auf der Schaltflaeche selbst.
    """

    def __init__(self, symbol: str, beschriftung: str, taste: str, farbe: str):
        super().__init__()
        self.setObjectName("kachel")
        self.setProperty("farbe", farbe)
        self.setProperty("ansage", beschriftung)
        self.setAccessibleName(beschriftung)
        self.setAccessibleDescription(f"Tastenkürzel {taste}" if taste else "")
        self.setToolTip(f"{beschriftung}  ({taste})" if taste else beschriftung)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        aufbau = QVBoxLayout(self)
        aufbau.setContentsMargins(0, 0, 0, 0)
        aufbau.setSpacing(0)

        self.symbol_feld = QLabel(symbol)
        self.symbol_feld.setObjectName("kachelsymbol")
        self.text_feld = QLabel(beschriftung)
        self.text_feld.setObjectName("kacheltext")
        self.text_feld.setWordWrap(True)

        for feld in (self.symbol_feld, self.text_feld):
            feld.setAlignment(Qt.AlignCenter)
            feld.setAttribute(Qt.WA_TransparentForMouseEvents)
            feld.setFocusPolicy(Qt.NoFocus)
            aufbau.addWidget(feld)

    def beschriften(self, text: str, ansage: str = "", symbol: str = "") -> None:
        """Aendert den kleinen Text und, wenn angegeben, Vorlesetext und
        Symbol. Der Kurzhinweis geht mit, damit Auge und Ohr dasselbe sagen."""
        self.text_feld.setText(text)
        if symbol:
            self.symbol_feld.setText(symbol)
        if ansage:
            self.setAccessibleName(ansage)
            taste = str(self.accessibleDescription()).replace("Tastenkürzel ", "")
            self.setToolTip(f"{ansage}  ({taste})" if taste else ansage)

    def einfaerben(self, farbe: str) -> None:
        """Wechselt die Pastellfarbe. Welche Farbe wie aussieht, steht in
        stil.qss; hier steht nur ihre Nummer beziehungsweise ihr Name."""
        if str(self.property("farbe")) == str(farbe):
            return
        self.setProperty("farbe", str(farbe))
        self.style().polish(self)
        self.update()


class Kachelreihe(QWidget):
    """Waagerechte Reihe der staendig gebrauchten Befehle.

    `eintraege` ist eine Liste aus (symbol, beschriftung, taste, farbe, ziel).
    Alle Kacheln teilen sich die verfuegbare Breite gleichmaessig, darum
    passt sich die Reihe jeder Fenstergroesse an.
    """

    def __init__(self, eintraege):
        super().__init__()
        self.setObjectName("kachelreihe")
        self.setAccessibleName("Befehlskacheln")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        aufbau = QHBoxLayout(self)

        self.kacheln: list[Kachel] = []
        for symbol, beschriftung, taste, farbe, ziel in eintraege:
            if not callable(ziel):
                log.error("Kachel ohne aufrufbares Ziel: %s (%r)", beschriftung, ziel)
                continue
            kachel = Kachel(symbol, beschriftung, taste, farbe)
            # Zwei getrennte Verbindungen: erst die Logzeile, dann das Ziel
            # selbst - unmittelbar, ohne Zwischenschritt. Damit steht im Log
            # der echte Methodenname, und keine Huelle kann eine Ausnahme des
            # Ziels verschlucken.
            kachel.clicked.connect(partial(self._kachel_merken, beschriftung, ziel))
            kachel.clicked.connect(ziel)
            aufbau.addWidget(kachel, 1)
            self.kacheln.append(kachel)
            log.info(
                "Kachel angelegt: %s (Taste %s) → %s",
                beschriftung, taste or "keine", getattr(ziel, "__name__", ziel),
            )
        log.info(
            "Kacheln insgesamt angelegt: %d von %d", len(self.kacheln), len(eintraege)
        )

    def _kachel_merken(self, beschriftung: str, ziel) -> None:
        """Schreibt nur die Logzeile, dass der Klick angekommen ist. Das Ziel
        haengt als eigene Verbindung am selben Signal."""
        log.info("Kachel gedrückt: %s → %s", beschriftung,
                 getattr(ziel, "__name__", ziel))

    # -- Laufzeit -----------------------------------------------------------

    def _kachel_suchen(self, ansage: str) -> Kachel | None:
        """Findet eine Kachel ueber ihre urspruengliche Beschriftung. Die
        bleibt als Kennung erhalten, auch wenn die Aufschrift wechselt."""
        for kachel in self.kacheln:
            if str(kachel.property("ansage")) == ansage:
                return kachel
        log.warning("Kachel nicht gefunden: %s", ansage)
        return None

    def kachel_beschriften(self, ansage: str, text: str, neue_ansage: str = "",
                           symbol: str = "") -> None:
        """Aendert Text, Vorlesetext und Symbol einer Kachel."""
        kachel = self._kachel_suchen(ansage)
        if kachel is not None:
            kachel.beschriften(text, neue_ansage, symbol)

    def kachel_faerben(self, ansage: str, farbe: str) -> None:
        """Wechselt die Farbe einer Kachel, etwa wenn sie einen anderen
        Zustand anzeigt."""
        kachel = self._kachel_suchen(ansage)
        if kachel is not None:
            kachel.einfaerben(farbe)
