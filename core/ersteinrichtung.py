"""
CWB - Code Workbench
Ersteinrichtung: die Pfadfrage beim allerersten Start.

Gefragt wird nach dem Ordner, in dem die Projekte liegen, nach dem
Skill-Ordner und nach der Memory-Hub-Datenbank. Vorgeschlagen wird jeweils
der uebliche Ort; uebernommen wird mit der Eingabetaste. Nur der
Projektordner muss stimmen, die beiden anderen duerfen leer bleiben.

Die Antworten landen in einstellungen.json (siehe pfade.py) und werden nie
wieder gefragt, solange der Projektordner dort steht und es ihn gibt.

Alles ist mit der Tastatur erreichbar, jedes Feld sagt sich beim Anspringen
selbst an. Aussehen kommt vollstaendig aus stil.qss.
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from .pfade import (
        hub_datenbank,
        hub_datenbank_merken,
        projektwurzel,
        projektwurzel_merken,
        projektwurzel_vorschlag,
        skill_ordner,
        skill_ordner_merken,
    )
except ImportError:
    from pfade import (
        hub_datenbank,
        hub_datenbank_merken,
        projektwurzel,
        projektwurzel_merken,
        projektwurzel_vorschlag,
        skill_ordner,
        skill_ordner_merken,
    )

log = logging.getLogger("cwb.ersteinrichtung")


class Pfadzeile(QWidget):
    """Ein Pfadfeld mit Beschriftung und Schaltflaeche zum Suchen.

    Wird sowohl in der Ersteinrichtung als auch im Reiter "Pfade" der
    Einstellungen verwendet. Meldet jede Aenderung ueber `geaendert`."""

    geaendert = Signal(str)

    def __init__(self, titel: str, hinweis: str, wert: str = "",
                 datei: bool = False, sprecher=None):
        super().__init__()
        self.titel = titel
        self.datei = datei
        self.sprecher = sprecher
        self.setObjectName("pfadzeile")

        aufbau = QVBoxLayout(self)
        aufbau.setContentsMargins(0, 0, 0, 0)

        beschriftung = QLabel(titel)
        beschriftung.setObjectName("feldname")
        beschriftung.setWordWrap(True)
        aufbau.addWidget(beschriftung)

        if hinweis:
            zusatz = QLabel(hinweis)
            zusatz.setObjectName("gruppenhinweis")
            zusatz.setWordWrap(True)
            aufbau.addWidget(zusatz)

        quer = QWidget()
        quer.setObjectName("gruppenzeile")
        nebeneinander = QHBoxLayout(quer)
        nebeneinander.setContentsMargins(0, 0, 0, 0)

        self.feld = QLineEdit(wert)
        self.feld.setObjectName("pfadfeld")
        self.feld.setAccessibleName(titel)
        self.feld.setAccessibleDescription(hinweis or titel)
        self.feld.editingFinished.connect(self._getippt)
        nebeneinander.addWidget(self.feld, 4)

        self.suchen = QPushButton("Suchen …")
        self.suchen.setObjectName("probe")
        self.suchen.setAccessibleName(f"{titel} suchen")
        self.suchen.setAccessibleDescription(
            "Öffnet die Ordnerauswahl" if not datei else "Öffnet die Dateiauswahl"
        )
        self.suchen.clicked.connect(self._suchen)
        nebeneinander.addWidget(self.suchen, 1)

        aufbau.addWidget(quer)

    def wert(self) -> str:
        return self.feld.text().strip()

    def setzen(self, wert: str) -> None:
        self.feld.setText(wert)

    def _sagen(self, satz: str) -> None:
        if self.sprecher is not None:
            try:
                # Die Ersteinrichtung führt durch und spricht in jeder Stufe.
                self.sprecher.sprich(satz, art="immer")
            except Exception as fehler:  # noqa: BLE001
                log.exception("Ansage nicht möglich: %s", fehler)

    def _getippt(self) -> None:
        self.geaendert.emit(self.wert())

    def _suchen(self) -> None:
        start = self.wert() or str(Path.home())
        try:
            if self.datei:
                gewaehlt, _ = QFileDialog.getOpenFileName(
                    self, self.titel, start, "Datenbank (*.db *.sqlite *.sqlite3);;Alle (*)"
                )
            else:
                gewaehlt = QFileDialog.getExistingDirectory(self, self.titel, start)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Auswahl nicht möglich (%s): %s", self.titel, fehler)
            self._sagen("Die Auswahl ließ sich nicht öffnen.")
            return
        if not gewaehlt:
            self._sagen("Nichts gewählt, es bleibt wie es war.")
            return
        self.feld.setText(str(Path(gewaehlt)))
        self.geaendert.emit(self.wert())
        self._sagen(f"{self.titel}: {Path(gewaehlt).name}.")


class Ersteinrichtung(QDialog):
    """Fragt beim ersten Start nach den drei Pfaden und merkt sie."""

    def __init__(self, sprecher, eltern=None):
        super().__init__(eltern)
        self.sprecher = sprecher
        self._gesichert = False

        self.setObjectName("einstellungen")
        self.setWindowTitle("CWB — Erste Einrichtung")
        self.setAccessibleName("Erste Einrichtung")
        self.setAccessibleDescription(
            "Drei Pfade: Projektordner, Skill-Ordner, Memory Hub. "
            "Tabulator wechselt das Feld, Eingabetaste übernimmt."
        )

        aufbau = QVBoxLayout(self)

        titel = QLabel("Erste Einrichtung")
        titel.setObjectName("einstellungstitel")
        aufbau.addWidget(titel)

        hinweis = QLabel(
            "CWB weiß noch nicht, wo deine Projekte liegen. Der Vorschlag ist "
            "der Ordner über dem CWB-Ordner. Stimmt er, genügt die Eingabetaste. "
            "Skill-Ordner und Memory Hub dürfen leer bleiben."
        )
        hinweis.setObjectName("einstellungshinweis")
        hinweis.setWordWrap(True)
        aufbau.addWidget(hinweis)

        self.wurzel = Pfadzeile(
            "Projektordner",
            "Der Ordner, in dem deine Projekte nebeneinander liegen.",
            str(projektwurzel() or projektwurzel_vorschlag()),
            sprecher=sprecher,
        )
        aufbau.addWidget(self.wurzel)

        self.skills = Pfadzeile(
            "Skill-Ordner",
            "Enthält je Skill einen Unterordner mit SKILL.md. Darf leer bleiben.",
            str(skill_ordner()),
            sprecher=sprecher,
        )
        aufbau.addWidget(self.skills)

        hub = hub_datenbank()
        self.hub = Pfadzeile(
            "Memory Hub",
            "Datei memory.db des projektübergreifenden Gedächtnisses. "
            "Gibt es keine, bleibt das Feld leer.",
            str(hub) if hub else "",
            datei=True,
            sprecher=sprecher,
        )
        aufbau.addWidget(self.hub)

        self.fertig = QPushButton("Übernehmen und starten")
        self.fertig.setObjectName("schliessen")
        self.fertig.setAccessibleName("Übernehmen und starten")
        self.fertig.setAccessibleDescription("Merkt die Pfade und öffnet die Projektwahl")
        self.fertig.setDefault(True)
        self.fertig.clicked.connect(self.accept)
        aufbau.addWidget(self.fertig)

        self._groesse_setzen()
        QTimer.singleShot(300, self.wurzel.feld.setFocus)
        self._sagen(
            "Erste Einrichtung. Wo liegen deine Projekte? Vorgeschlagen ist "
            f"{Path(self.wurzel.wert()).name}. Eingabetaste übernimmt."
        )

    def _groesse_setzen(self) -> None:
        """Groesse als Anteil des Bildschirms, damit nichts fest in Pixeln
        haengt und die Seite auf jedem Bildschirm passt."""
        try:
            schirm = QGuiApplication.primaryScreen()
            if schirm is None:
                return
            flaeche = schirm.availableGeometry()
            self.resize(int(flaeche.width() * 0.55), int(flaeche.height() * 0.55))
        except Exception as fehler:  # noqa: BLE001
            log.warning("Fenstergröße nicht setzbar: %s", fehler)

    def _sagen(self, satz: str) -> None:
        try:
            # Die Ersteinrichtung führt durch und spricht in jeder Stufe.
            self.sprecher.sprich(satz, art="immer")
        except Exception as fehler:  # noqa: BLE001
            log.exception("Ansage nicht möglich: %s", fehler)

    def sichern(self) -> None:
        """Merkt die drei Pfade. Wird auch beim Schließen mit Escape
        aufgerufen: sonst stünde CWB beim nächsten Start wieder ohne Pfade da."""
        if self._gesichert:
            return
        self._gesichert = True

        wurzel = self.wurzel.wert() or str(projektwurzel_vorschlag())
        projektwurzel_merken(wurzel)

        skills = self.skills.wert()
        skill_ordner_merken(skills if skills else None)

        hub = self.hub.wert()
        hub_datenbank_merken(hub if hub else None)

        if not Path(wurzel).is_dir():
            log.warning("Eingestellter Projektordner gibt es nicht: %s", wurzel)
            self._sagen("Diesen Projektordner gibt es nicht. Er lässt sich in den Einstellungen ändern.")
        else:
            self._sagen(f"Gemerkt. Projekte in {Path(wurzel).name}.")

    def accept(self) -> None:
        self.sichern()
        super().accept()

    def reject(self) -> None:
        self.sichern()
        super().reject()

    def keyPressEvent(self, ereignis) -> None:
        # Eingabetaste im Pfadfeld schließt die Einrichtung ab, statt nur das
        # Feld zu bestätigen.
        if ereignis.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(ereignis)
