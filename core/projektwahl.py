"""
CWB - Code Workbench
Projektwahl: erste Ansicht beim Start und beim Wechsel mit F9.

Die Liste wird mit den Pfeiltasten bedient, jede Zeile wird beim Anwaehlen
angesagt; Eingabe oder Doppelklick oeffnet das Projekt.

Die Werkbank selbst kennt dieses Modul nicht: welche Klasse geoeffnet wird,
reicht der Aufrufer als `werkbank_klasse` herein. So bleibt die Projektwahl
unabhaengig von fenster.py, das beim Start als Hauptmodul laeuft.

Aussehen kommt vollstaendig aus stil.qss. Im Python steht keine Gestaltung.
"""

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

try:
    from .grundlagen import (
        OFFENE_FENSTER,
        einstellungen_lesen,
        einstellungen_schreiben,
        stil_verzoegert,
    )
    from .sicherheit import Projekt, projekte_finden
    from .sprache import Sprecher
except ImportError:
    from grundlagen import (
        OFFENE_FENSTER,
        einstellungen_lesen,
        einstellungen_schreiben,
        stil_verzoegert,
    )
    from sicherheit import Projekt, projekte_finden
    from sprache import Sprecher

log = logging.getLogger("cwb.projektwahl")


class ProjektListe(QListWidget):
    """Erste Ansicht: Projekt wählen. Jede Zeile wird beim Anwählen gesagt."""

    gewaehlt = Signal(object)

    def __init__(self, projekte: list[Projekt], sprecher: Sprecher):
        super().__init__()
        self.projekte = projekte
        self.sprecher = sprecher
        self.setObjectName("projektliste")
        self.setAccessibleName("Projektwahl")
        for projekt in projekte:
            eintrag = QListWidgetItem(projekt.name)
            eintrag.setData(Qt.UserRole, projekt)
            self.addItem(eintrag)
        self.currentRowChanged.connect(self._angesagt)
        self.itemDoubleClicked.connect(
            lambda eintrag: self.gewaehlt.emit(eintrag.data(Qt.UserRole))
        )
        if projekte:
            self.setCurrentRow(0)

    def _angesagt(self, zeile: int) -> None:
        if 0 <= zeile < len(self.projekte):
            self.sprecher.sprich(self.projekte[zeile].ansage())

    def keyPressEvent(self, ereignis) -> None:
        if ereignis.key() in (Qt.Key_Return, Qt.Key_Enter):
            eintrag = self.currentItem()
            if eintrag:
                self.gewaehlt.emit(eintrag.data(Qt.UserRole))
            return
        super().keyPressEvent(ereignis)


class Start(QMainWindow):
    """Projektwahl, danach öffnet die Werkbank."""

    def __init__(self, sprecher: Sprecher, werkbank_klasse,
                 automatisch: bool = True):
        super().__init__()
        self.sprecher = sprecher
        self.werkbank_klasse = werkbank_klasse
        self.werkbank = None
        self.setWindowTitle("CWB — Projekt wählen")

        # Läuft schon eine Werkbank, wird sie nach vorn geholt und dieses
        # Startfenster verschwindet wieder.
        offen = [f for f in OFFENE_FENSTER if isinstance(f, werkbank_klasse)]
        if offen:
            vorhanden = offen[-1]
            vorhanden.raise_()
            vorhanden.activateWindow()
            QTimer.singleShot(0, self.close)
            return

        projekte = projekte_finden()

        # Beim Programmstart wird das zuletzt geöffnete Projekt sofort
        # geöffnet, ohne Auswahl. Beim Projektwechsel über F9 (automatisch=False) nicht.
        if automatisch and projekte:
            letztes = einstellungen_lesen().get("letztes_projekt")
            passendes = next((p for p in projekte if p.name == letztes), None)
            if passendes is not None:
                QTimer.singleShot(0, lambda: self._oeffnen(passendes))
                return

        mitte = QWidget()
        aufbau = QVBoxLayout(mitte)

        hinweis = QLabel("Projekt wählen: Pfeiltasten und Eingabe, oder Doppelklick.")
        hinweis.setObjectName("status")
        aufbau.addWidget(hinweis)

        if not projekte:
            aufbau.addWidget(QLabel("Keine Projekte gefunden."))
            self.sprecher.sprich("Keine Projekte gefunden.")
        else:
            self.liste = ProjektListe(projekte, sprecher)
            self.liste.gewaehlt.connect(self._oeffnen)
            aufbau.addWidget(self.liste)
            letztes = einstellungen_lesen().get("letztes_projekt")
            for zeile, eintrag in enumerate(projekte):
                if eintrag.name == letztes:
                    self.liste.setCurrentRow(zeile)
                    break
            QTimer.singleShot(300, self.liste.setFocus)
            self.sprecher.sprich(
                f"{len(projekte)} Projekte. Mit Pfeiltasten wählen, Eingabe öffnet."
            )

        self.setCentralWidget(mitte)

    def resizeEvent(self, ereignis) -> None:
        super().resizeEvent(ereignis)
        stil_verzoegert(self.width(), self.height())

    def _oeffnen(self, projekt: Projekt) -> None:
        if self.werkbank is not None:
            return
        werte = einstellungen_lesen()
        werte["letztes_projekt"] = projekt.name
        einstellungen_schreiben(werte)
        self.sprecher.sprich(f"Öffne {projekt.name}.")
        self.werkbank = self.werkbank_klasse(projekt, self.sprecher)
        OFFENE_FENSTER.append(self.werkbank)
        self.werkbank.showMaximized()
        self.hide()
        QTimer.singleShot(0, self.close)
