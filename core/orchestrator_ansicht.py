"""
CWB - Code Workbench
Orchestrator, Etappe 1A: Ansicht und eigene Sitzung.

`OrchestratorFaden` ist ein zweiter `SitzungsFaden` (core/faden.py) mit
eigener Sitzung: eigenes Modell, eigener Systemtext (Standard-Zusatz plus
wissen/orchestrator_anweisung.md), eigene Werkzeuge (core/orchestrator.py)
und der "schlanken" Sitzung ohne Git-Sicherungspunkt, Projektwissen und
Code-Index. Er laeuft parallel zur normalen Sitzung und teilt mit ihr weder
Warteschlange noch Zustandsanzeige: alle seine Signale gehen nur an
`OrchestratorAnsicht`.

`OrchestratorAnsicht` ist die umschaltbare Ansicht im Hauptfenster: Titel mit
Zustand, schreibgeschuetzter Verlauf, Eingabefeld (Strg+Enter sendet - das
Kuerzel liegt im Hauptfenster, siehe Werkbank._senden_taste), Statuszeile.
Gestaltung ausschliesslich in stil.qss (#orch_...).
"""

import html
import logging
import re
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from . import diktat, orchestrator
    from .faden import SitzungsFaden
    from .grundlagen import verlauf_stil_lesen
    from .sicherheit import Projekt, Wache
    from .sitzung import SYSTEM_ZUSATZ, Sitzung
except ImportError:
    import diktat
    import orchestrator
    from faden import SitzungsFaden
    from grundlagen import verlauf_stil_lesen
    from sicherheit import Projekt, Wache
    from sitzung import SYSTEM_ZUSATZ, Sitzung

log = logging.getLogger("cwb.orchestrator_ansicht")

# Vorsatzzeichen je Textart im Verlauf, wie VERLAUF_ARTEN im Hauptfenster:
# die Art liegt nie allein in der Farbe (verlauf.css), das Wort wird mitgelesen.
VORSATZ = {
    "auftrag": "▶  Du: ",
    "antwort": "Orchestrator: ",
    "frage": "❓  FRAGE: ",
    "fehler": "✖  FEHLER: ",
    "hinweis": "—  ",
    "befehl": "",   # die Zeile traegt ihr Vorzeichen (→ / ←) selbst
}

# Dateiendungen fuer Strg+B "Bild anhaengen" (wie BILD_ENDUNGEN im Hauptfenster).
BILD_ENDUNGEN = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

# Ablage fuer Bilder aus der Zwischenablage (wie im Hauptfenster: <CWB>/.ablage).
ABLAGE_ORDNER = Path(__file__).resolve().parent.parent / ".ablage"

# So viel einer Antwort wird hoechstens vorgelesen; der Rest steht im Verlauf.
VORLESEN_MAX_ZEICHEN = 400

# Beschriftung des Vorlese-Knopfs; waehrend des Sprechens das Stopp-Wort.
VORLESEN_WORT = "Vorlesen"
VORLESEN_STOPP_WORT = "■ Lesen"

# Beschriftung des Diktat-Knopfs je Zustand; die Farbe steht in stil.qss
# (#orch_aufnahme[zustand=...]), das Wort traegt den Zustand zusaetzlich.
DIKTAT_WORTE = {"bereit": "● Diktat", "aufnahme": "Aufnahme läuft", "erkennt": "Erkenne…"}
# Tastenkuerzel fuer den Diktat-Knopf (im Hauptfenster frei, nur in dieser Ansicht).
DIKTAT_KUERZEL = "Ctrl+D"

# Zustand der Sitzung (sitzung.Zustand) -> (Titel-Property, Wort im Titel).
# Die Farben stehen ausschliesslich in stil.qss (#orch_titel[zustand=...]).
# Alles Lesende ist "liest" (lila); Denken, Schreiben, Ausfuehren und Netz sind
# "Antworten" (gelb). bereit/fertig/fehler/abgebrochen setzen Ansicht und
# `_fertig` selbst, nicht die Einzelereignisse.
TITEL_ZUSTAND = {
    "liest": ("liest", "liest"),
    "sucht": ("liest", "sucht"),
    "denkt": ("denkt", "denkt"),
    "schaerft": ("denkt", "denkt"),
    "schreibt": ("denkt", "schreibt"),
    "fuehrt_aus": ("denkt", "führt aus"),
    "netz": ("denkt", "denkt"),
}


def vorlese_text(antwort: str, grenze: int = VORLESEN_MAX_ZEICHEN) -> str:
    """Kuerzt eine Antwort fuer die Sprachausgabe an einer Satzgrenze."""
    text = " ".join((antwort or "").split())
    if len(text) <= grenze:
        return text
    kurz = text[:grenze]
    schnitt = max(kurz.rfind(". "), kurz.rfind("! "), kurz.rfind("? "))
    return kurz[:schnitt + 1] if schnitt > grenze // 3 else kurz.rstrip()


def vorlese_saetze(text: str) -> list[str]:
    """Teilt Text in Saetze (und Zeilen), damit der Sprecher sofort beginnt."""
    saetze = []
    for zeile in (text or "").replace("\u2029", "\n").splitlines():
        for satz in re.split(r"(?<=[.!?])\s+", " ".join(zeile.split())):
            if satz.strip():
                saetze.append(satz.strip())
    return saetze


class OrchestratorEingabe(QPlainTextEdit):
    """Eingabefeld, das ein Bild aus der Zwischenablage (Strg+V) nicht als
    Text einfuegt, sondern meldet."""

    bild_eingefuegt = Signal(QImage)

    def canInsertFromMimeData(self, quelle) -> bool:  # noqa: N802
        return quelle.hasImage() or super().canInsertFromMimeData(quelle)

    def insertFromMimeData(self, quelle) -> None:  # noqa: N802
        if quelle.hasImage():
            bild = quelle.imageData()
            if isinstance(bild, QImage) and not bild.isNull():
                self.bild_eingefuegt.emit(bild)
                return
        super().insertFromMimeData(quelle)


class OrchestratorFaden(SitzungsFaden):
    """Arbeitsfaden der Orchestrator-Sitzung."""

    # Befehlsanzeige: Werkzeugname + Eingabe, dann Name + Eingabe + Status + Text
    werkzeug_da = Signal(str, dict)
    werkzeug_ergebnis_da = Signal(str, dict, str, str)

    def __init__(self, projekt: Projekt, modell: str = "", zustand_geber=None):
        super().__init__(projekt, modell or orchestrator.modell())
        self._zustand_geber = zustand_geber

    def _sitzung_bauen(self) -> Sitzung:
        zusatz = SYSTEM_ZUSATZ
        anweisung = orchestrator.anweisung_lesen()
        if anweisung:
            zusatz = f"{SYSTEM_ZUSATZ}\n\n{anweisung}"
        zusatz = f"{zusatz}\n\n{orchestrator.projektliste_text()}"
        startblock = orchestrator.startblock_bauen()
        if startblock:
            zusatz = f"{zusatz}\n\n{startblock}"
        zusatz = f"{zusatz}\n\n{orchestrator.REGEL_AUSGABE}"
        server = {orchestrator.SERVER_NAME: orchestrator.werkzeuge_bauen(
            self._zustand_geber, rueckfrage=self._rueckfrage)}
        return Sitzung(
            # Kein Git-Netz anlegen: die normale Sitzung haelt den Projektstand.
            Wache.oeffnen(self.projekt, git_anlegen=False),
            bei_ereignis=lambda e: self.ereignis_da.emit(
                e.zustand.value, e.ansage, e.detail, e.pfad, e.taetigkeit, e.ablehnung,
                e.hinweis,
            ),
            bei_text=lambda t: self.text_da.emit(t),
            bei_rueckfrage=self._rueckfrage,
            bei_verbrauch=lambda v: self.verbrauch_da.emit(v),
            modell=self.modell,
            system_zusatz=zusatz,
            zusatz_server=server,
            schlank=True,
            bei_werkzeug=lambda n, e: self.werkzeug_da.emit(n, e),
            bei_werkzeug_ergebnis=lambda n, e, s, t: self.werkzeug_ergebnis_da.emit(n, e, s, t),
        )


class _RadFilter(QObject):
    """Schluckt Strg+Mausrad, damit die Schrift aus stil.qss nicht zoomt
    (wie im Hauptfenster)."""

    def eventFilter(self, objekt, ereignis) -> bool:  # noqa: N802
        if ereignis.type() == QEvent.Wheel and ereignis.modifiers() & Qt.ControlModifier:
            return True
        return False


class OrchestratorAnsicht(QWidget):
    """Die Orchestrator-Ansicht. Haelt ihren eigenen Faden; er wird erst beim
    ersten Senden gestartet, damit ein eingeschalteter, aber ungenutzter
    Reiter keine zweite Verbindung belegt."""

    # Satz, Kurzsatz: eine Rueckfrage der Orchestrator-Sitzung. Das Hauptfenster
    # sagt sie an und leitet Eingabe/Escape an `frage_beantworten` weiter.
    frage_gestellt = Signal(str, str)
    # Der grosse Knopf "Zurueck zu Claude Code": das Hauptfenster schaltet um.
    zurueck_gewuenscht = Signal()
    # Der Neustart-Knopf: wie Strg+F4, samt Rueckfrage im Hauptfenster.
    neustart_gewuenscht = Signal()
    # Ergebnisse des Diktat-Arbeitsfadens (Text, Absenden) / Fehlersatz / nichts gehoert.
    diktat_fertig = Signal(str, bool)
    diktat_fehler = Signal(str)
    diktat_leer = Signal()

    # Ein Zustand bleibt mindestens so lange sichtbar, damit ein schneller
    # Wechsel fuer Roberts Farbwahrnehmung nicht verschwindet.
    MINDEST_ANZEIGE_MS = 600

    def __init__(self, projekt: Projekt, sprecher, eltern=None, schlange=None):
        super().__init__(eltern)
        self.projekt = projekt
        self.sprecher = sprecher
        # Meldungen von CWB (Etappe 1B), auf Platte gesichert
        self.schlange = schlange if schlange is not None else orchestrator.Eingangsschlange()
        self._arten: deque[str] = deque()   # "text" oder "meldung", in Sendereihenfolge
        self.faden: OrchestratorFaden | None = None
        self.diktat = diktat.Diktat()       # Aufnahme wird erst beim Druck geoeffnet
        self.diktat_fertig.connect(self._diktat_fertig)
        self.diktat_fehler.connect(self._diktat_fehler)
        self.diktat_leer.connect(self._diktat_leer)
        self.bilder: list[Path] = []        # angehaengt, gehen mit der naechsten Nachricht
        self.frage_offen = False
        self._offen = 0            # gesendete, noch nicht beendete Auftraege
        self._taetigkeit = ""
        self._uhr = time.monotonic          # austauschbar fuer Tests
        self._zustand_seit = None           # Zeitpunkt der letzten sichtbaren Aenderung
        self._zustand_wartet = None         # (zustand, wort), solange die Mindestdauer laeuft
        self._zustand_zeitgeber = QTimer(self)
        self._zustand_zeitgeber.setSingleShot(True)
        self._zustand_zeitgeber.timeout.connect(self._zustand_nachholen)
        self._antwort_teile: list[str] = []
        self._letzte_antwort = ""
        self._liest_vor = False
        self._vorlese_zeitgeber = QTimer(self)
        self._vorlese_zeitgeber.setInterval(250)
        self._vorlese_zeitgeber.timeout.connect(self._vorlesen_pruefen)
        self._aufbauen()
        try:
            self._verlauf_wiederholen()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Orchestrator-Verlauf nicht geladen: %s", fehler)

    # -- Aufbau --------------------------------------------------------------

    def _aufbauen(self) -> None:
        self.setObjectName("orch_ansicht")
        aufbau = QVBoxLayout(self)

        # Gleiche Farbe wie die Orchestrator-Kachel im Hauptfenster; waechst
        # mit dem Inhalt und bricht bei grosser Schrift nicht ab.
        self.zurueck_knopf = QPushButton("Zurück zu Claude Code")
        self.zurueck_knopf.setObjectName("orch_zurueck")
        self.zurueck_knopf.setAccessibleName("Zurück zu Claude Code")
        self.zurueck_knopf.setAccessibleDescription("Wie Strg und O")
        self.zurueck_knopf.setToolTip("Zurück zu Claude Code (Strg+O)")
        self.zurueck_knopf.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.zurueck_knopf.clicked.connect(self.zurueck_gewuenscht.emit)
        # Neustart ist in beiden Ansichten immer da; gleiche Farbe wie die
        # grosse Neustart-Kachel im Hauptfenster.
        self.neustart_knopf = QPushButton("⟳ Neu starten")
        self.neustart_knopf.setObjectName("orch_neustart")
        self.neustart_knopf.setAccessibleName("Neu starten")
        self.neustart_knopf.setAccessibleDescription("Wie Strg und F4. Fragt vorher nach.")
        self.neustart_knopf.setToolTip("Kompletter Neustart (Strg+F4)")
        self.neustart_knopf.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.neustart_knopf.clicked.connect(self.neustart_gewuenscht.emit)
        kopf = QHBoxLayout()
        kopf.setContentsMargins(0, 0, 0, 0)
        kopf.addWidget(self.zurueck_knopf, 1)
        kopf.addWidget(self.neustart_knopf, 0)
        aufbau.addLayout(kopf)

        self.titel = QLabel("Orchestrator: bereit")
        self.titel.setObjectName("orch_titel")
        self.titel.setAccessibleName("Orchestrator Zustand")
        self.titel.setProperty("zustand", "bereit")
        # Der Waechter-Platzhalter des Hauptfensters sitzt in dieser Zeile
        # links neben dem Titel (Werkbank._waechter_platzieren).
        self.titel_zeile = QHBoxLayout()
        self.titel_zeile.setContentsMargins(0, 0, 0, 0)
        self.titel_zeile.addWidget(self.titel, 1)
        aufbau.addLayout(self.titel_zeile)

        self.status = QLabel("Strg+Eingabe sendet. Strg+O wechselt zurück.")
        self.status.setObjectName("orch_status")
        self.status.setAccessibleName("Orchestrator Status")
        self.status.setWordWrap(True)
        aufbau.addWidget(self.status)

        self.kontingent = QLabel("Kontingent: noch nicht gemeldet")
        self.kontingent.setObjectName("orch_kontingent")
        self.kontingent.setAccessibleName("Orchestrator Kontingent")
        self.kontingent.setWordWrap(True)
        aufbau.addWidget(self.kontingent)
        self._kontingent_stufe = "start"    # erster Aufruf bleibt stumm
        self.kontingent_setzen(None)

        self.verlauf = QTextEdit()
        self.verlauf.setObjectName("orch_verlauf")
        self.verlauf.setReadOnly(True)
        self.verlauf.setAccessibleName("Orchestrator-Verlauf")
        self.verlauf.document().setDefaultStyleSheet(verlauf_stil_lesen())
        aufbau.addWidget(self.verlauf, 8)

        zeile = QWidget()
        quer = QHBoxLayout(zeile)
        quer.setContentsMargins(0, 0, 0, 0)

        self.eingabe = OrchestratorEingabe()
        self.eingabe.setObjectName("orch_eingabe")
        self.eingabe.setAccessibleName("Auftrag an den Orchestrator eingeben")
        self.eingabe.bild_eingefuegt.connect(self.bild_aus_zwischenablage)
        quer.addWidget(self.eingabe, 1)

        self.senden_knopf = QPushButton("↑")
        self.senden_knopf.setObjectName("orch_senden")
        self.senden_knopf.setAccessibleName("An den Orchestrator senden")
        self.senden_knopf.setAccessibleDescription("Wie Strg und Eingabetaste")
        self.senden_knopf.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.senden_knopf.clicked.connect(self.senden)
        quer.addWidget(self.senden_knopf)

        self.stopp_knopf = QPushButton("■ Stopp")
        self.stopp_knopf.setObjectName("orch_stopp")
        self.stopp_knopf.setAccessibleName("Orchestrator stoppen")
        self.stopp_knopf.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.stopp_knopf.clicked.connect(self.not_aus)
        quer.addWidget(self.stopp_knopf)

        # Nur Tab-Fokus: ein Mausklick darf dem Verlauf den Fokus nicht nehmen,
        # sonst verblasst oder verschwindet die Markierung.
        self.vorlesen_knopf = QPushButton(VORLESEN_WORT)
        self.vorlesen_knopf.setObjectName("orch_vorlesen")
        self.vorlesen_knopf.setAccessibleName("Markierten Text vorlesen")
        self.vorlesen_knopf.setAccessibleDescription(
            "Liest die Markierung im Verlauf, sonst die letzte Antwort. Nochmal drücken bricht ab.")
        self.vorlesen_knopf.setFocusPolicy(Qt.TabFocus)
        self.vorlesen_knopf.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.vorlesen_knopf.clicked.connect(self.vorlesen)
        # Diktat: ein Druck nimmt auf, der zweite erkennt. Zustand in Farbe UND Wort.
        self.aufnahme_knopf = QPushButton(DIKTAT_WORTE["bereit"])
        self.aufnahme_knopf.setObjectName("orch_aufnahme")
        self.aufnahme_knopf.setAccessibleName("Diktat aufnehmen")
        self.aufnahme_knopf.setAccessibleDescription(
            "Erster Druck startet die Aufnahme, zweiter beendet sie und erkennt. "
            "Wie Strg und D.")
        self.aufnahme_knopf.setToolTip(f"Diktat aufnehmen ({DIKTAT_KUERZEL.replace('Ctrl', 'Strg')})")
        self.aufnahme_knopf.setProperty("zustand", "bereit")
        self.aufnahme_knopf.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.aufnahme_knopf.clicked.connect(self.diktat_umschalten)
        # Eigene Zeile unter dem Verlauf: neben Eingabe, Senden und Stopp liess
        # er dem Eingabefeld bei schmalem Fenster nur einen Streifen.
        vorlese_zeile = QHBoxLayout()
        vorlese_zeile.setContentsMargins(0, 0, 0, 0)
        vorlese_zeile.addWidget(self.vorlesen_knopf)
        vorlese_zeile.addWidget(self.aufnahme_knopf)
        vorlese_zeile.addStretch(1)

        # Anzeige der angehaengten Bilder; nur sichtbar, solange welche da sind.
        self.bild_anzeige = QLabel("")
        self.bild_anzeige.setObjectName("orch_bildanzeige")
        self.bild_anzeige.setAccessibleName("Angehängte Bilder")
        self.bild_anzeige.setWordWrap(True)
        self.bild_entfernen_knopf = QPushButton("Letztes entfernen")
        self.bild_entfernen_knopf.setObjectName("orch_bild_weg")
        self.bild_entfernen_knopf.setAccessibleName("Letztes angehängtes Bild entfernen")
        self.bild_entfernen_knopf.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.bild_entfernen_knopf.clicked.connect(self.bild_entfernen)
        self.bild_alle_knopf = QPushButton("Alle entfernen")
        self.bild_alle_knopf.setObjectName("orch_bild_weg")
        self.bild_alle_knopf.setAccessibleName("Alle angehängten Bilder entfernen")
        self.bild_alle_knopf.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.bild_alle_knopf.clicked.connect(self.bilder_leeren)
        self.bild_zeile = QWidget()
        bild_quer = QHBoxLayout(self.bild_zeile)
        bild_quer.setContentsMargins(0, 0, 0, 0)
        bild_quer.addWidget(self.bild_anzeige, 1)
        bild_quer.addWidget(self.bild_entfernen_knopf)
        bild_quer.addWidget(self.bild_alle_knopf)
        self.bild_zeile.setVisible(False)

        aufbau.addLayout(vorlese_zeile, 0)
        aufbau.addWidget(self.bild_zeile, 0)
        aufbau.addWidget(zeile, 0)

        # Strg+B auch hier, falls das Kuerzel des Hauptfensters nicht greift.
        self._bild_kuerzel = QShortcut(QKeySequence("Ctrl+B"), self)
        self._bild_kuerzel.setContext(Qt.WidgetWithChildrenShortcut)
        self._bild_kuerzel.activated.connect(self.bild_waehlen)

        self._diktat_kuerzel = QShortcut(QKeySequence(DIKTAT_KUERZEL), self)
        self._diktat_kuerzel.setContext(Qt.WidgetWithChildrenShortcut)
        self._diktat_kuerzel.activated.connect(self.diktat_umschalten)

        self._knopfbreite_angleichen()

        self.setTabOrder(self.zurueck_knopf, self.neustart_knopf)
        self.setTabOrder(self.neustart_knopf, self.eingabe)
        self.setTabOrder(self.eingabe, self.senden_knopf)
        self.setTabOrder(self.senden_knopf, self.stopp_knopf)
        self.setTabOrder(self.stopp_knopf, self.bild_entfernen_knopf)
        self.setTabOrder(self.bild_entfernen_knopf, self.bild_alle_knopf)
        self.setTabOrder(self.bild_alle_knopf, self.vorlesen_knopf)
        self.setTabOrder(self.vorlesen_knopf, self.aufnahme_knopf)
        self.setTabOrder(self.aufnahme_knopf, self.verlauf)

        self._rad_filter = _RadFilter(self)
        for feld in (self.verlauf, self.eingabe):
            feld.installEventFilter(self._rad_filter)
            feld.viewport().installEventFilter(self._rad_filter)

    # -- Anzeige -------------------------------------------------------------

    def _zustand_zeigen(self, zustand: str, wort: str) -> None:
        """Zeigt Zustand (Farbe ueber die Property, nur in stil.qss) und Wort.
        Liegt die letzte sichtbare Aenderung noch keine Mindestdauer zurueck,
        wird der neue Zustand zurueckgehalten und danach nachgeholt; kommt in
        der Zwischenzeit ein weiterer, zaehlt nur der letzte."""
        if self._zustand_seit is not None:
            rest = self.MINDEST_ANZEIGE_MS / 1000 - (self._uhr() - self._zustand_seit)
            if rest > 0 and self.titel.property("zustand") != zustand:
                self._zustand_wartet = (zustand, wort)
                self._zustand_zeitgeber.start(int(rest * 1000) + 1)
                return
        self._zustand_wartet = None
        self._zustand_zeitgeber.stop()
        self._zustand_anwenden(zustand, wort)

    def _zustand_nachholen(self) -> None:
        wartet, self._zustand_wartet = self._zustand_wartet, None
        if wartet:
            self._zustand_anwenden(*wartet)

    def _zustand_anwenden(self, zustand: str, wort: str) -> None:
        self.titel.setText(f"Orchestrator: {wort}")
        if self.titel.property("zustand") != zustand:
            self._zustand_seit = self._uhr()
            log.debug("Orchestrator-Titel: %s", zustand)
            self.titel.setProperty("zustand", zustand)
            style = self.titel.style()
            style.unpolish(self.titel)
            style.polish(self.titel)

    def _status_zeigen(self, text: str) -> None:
        self.status.setText(text)

    def _absatz(self, text: str, art: str = "antwort") -> None:
        inhalt = f"{VORSATZ.get(art, '')}{text}".strip()
        if not inhalt:
            return
        art = art if art in VORSATZ else "antwort"
        orchestrator.verlauf_anhaengen(art, inhalt)
        self._anzeigen(inhalt, art)

    def _anzeigen(self, inhalt: str, art: str) -> None:
        """Zeigt einen fertigen Eintrag an, ohne ihn erneut zu speichern."""
        self.verlauf.append(
            f'<div class="{art}">' + html.escape(inhalt).replace("\n", "<br>") + "</div>")
        leiste = self.verlauf.verticalScrollBar()
        leiste.setValue(leiste.maximum())

    def _verlauf_wiederholen(self) -> None:
        """Zeigt beim Oeffnen die letzten Eintraege aus verlauf.txt wieder an,
        auch die Befehlszeilen (nur, wenn der Schalter an ist)."""
        zeigen = orchestrator.befehle_anzeigen()
        for art, text in orchestrator.verlauf_laden():
            if art == orchestrator.BEFEHL_ART and not zeigen:
                continue
            self._anzeigen(text, art if art in VORSATZ else "antwort")

    # -- Bilder -----------------------------------------------------------------

    def _bilder_zeigen(self) -> None:
        anzahl = len(self.bilder)
        self.bild_zeile.setVisible(anzahl > 0)
        namen = ", ".join(b.name for b in self.bilder)
        self.bild_anzeige.setText(
            f"{anzahl} Bild angehängt: {namen}" if anzahl == 1
            else f"{anzahl} Bilder angehängt: {namen}")

    def _bild_angehaengt(self, pfad: Path) -> None:
        self.bilder.append(pfad)
        self._bilder_zeigen()
        self._status_zeigen(self.bild_anzeige.text())
        log.info("Bild angehängt: %s (%d insgesamt)", pfad.name, len(self.bilder))
        try:
            self.sprecher.ton("schreibt")      # kurzer Bestaetigungston, kein Satz
        except Exception as fehler:  # noqa: BLE001
            log.exception("Bestätigungston nicht gespielt: %s", fehler)

    def bild_waehlen(self) -> None:
        """Strg+B: Dateidialog, mehrere Bilder moeglich."""
        muster = "Bilder (" + " ".join(f"*{e}" for e in BILD_ENDUNGEN) + ")"
        pfade, _ = QFileDialog.getOpenFileNames(self, "Bild anhängen", "", muster)
        for pfad in pfade:
            self._bild_angehaengt(Path(pfad))

    def bild_aus_zwischenablage(self, bild: QImage) -> None:
        """Strg+V mit Bild: speichert es unter .ablage und haengt es an."""
        try:
            ABLAGE_ORDNER.mkdir(parents=True, exist_ok=True)
            datei = ABLAGE_ORDNER / f"orch_{time.strftime('%Y%m%d_%H%M%S')}_{len(self.bilder) + 1}.png"
            if not bild.save(str(datei), "PNG"):
                raise OSError("Speichern gescheitert")
        except OSError as fehler:
            log.error("Bild aus Zwischenablage nicht speicherbar: %s", fehler)
            self._status_zeigen("Bild aus der Zwischenablage nicht gespeichert.")
            return
        self._bild_angehaengt(datei)

    def bild_entfernen(self) -> None:
        if self.bilder:
            weg = self.bilder.pop()
            log.info("Bild entfernt: %s", weg.name)
            self._bilder_zeigen()
            self._status_zeigen("Bild entfernt." if self.bilder else "Alle Bilder entfernt.")

    def bilder_leeren(self) -> None:
        if self.bilder:
            self.bilder.clear()
            self._bilder_zeigen()
            self._status_zeigen("Alle Bilder entfernt.")

    # -- Vorlesen --------------------------------------------------------------

    def _vorlese_quelle(self) -> str:
        """Markierung im Verlauf, sonst die letzte Antwort, sonst ''."""
        markiert = self.verlauf.textCursor().selectedText().replace("\u2029", "\n")
        if markiert.strip():
            return markiert
        return self._letzte_antwort

    def vorlesen(self) -> None:
        """Knopf "Vorlesen": zweiter Klick waehrend des Sprechens bricht ab."""
        if self._liest_vor and self.sprecher.spricht():
            self.sprecher.schweig()
            log.info("Vorlesen abgebrochen")
            self._vorlesen_beendet()
            return
        saetze = vorlese_saetze(self._vorlese_quelle())
        if not saetze:
            log.info("Vorlesen: nichts da")
            self.sprecher.sprich("Nichts zum Vorlesen.", art="immer")
            return
        log.info("Vorlesen: %d Sätze", len(saetze))
        self.sprecher.sprich(saetze[0], art="immer")
        for satz in saetze[1:]:
            self.sprecher.sprich(satz, unterbrechen=False, art="immer")
        self._liest_vor = True
        self.vorlesen_knopf.setText(VORLESEN_STOPP_WORT)
        self._vorlese_zeitgeber.start()

    def _vorlesen_pruefen(self) -> None:
        if not self.sprecher.spricht():
            self._vorlesen_beendet()

    def _vorlesen_beendet(self) -> None:
        self._liest_vor = False
        self._vorlese_zeitgeber.stop()
        self.vorlesen_knopf.setText(VORLESEN_WORT)

    def _knopfbreite_angleichen(self) -> None:
        """Stopp und Vorlesen bekommen dieselbe Breite: die der laengsten
        Beschriftung, gemessen mit der Schrift des Stilblatts. Der Wechsel
        "Vorlesen" / "■ Lesen" aendert die Breite so nie."""
        knoepfe = {self.stopp_knopf: (self.stopp_knopf.text(),),
                   self.vorlesen_knopf: (VORLESEN_WORT, VORLESEN_STOPP_WORT)}
        breite = 0
        for knopf, worte in knoepfe.items():
            knopf.setMinimumWidth(0)
            knopf.setMaximumWidth(16777215)
            knopf.ensurePolished()
            gemerkt = knopf.text()
            for wort in worte:
                knopf.setText(wort)
                breite = max(breite, knopf.sizeHint().width())
            knopf.setText(gemerkt)
        for knopf in knoepfe:
            knopf.setFixedWidth(breite)
        # Der Diktat-Knopf bekommt die Breite seiner laengsten Beschriftung,
        # damit der Wechsel der Worte nie etwas verschiebt oder abschneidet.
        knopf = self.aufnahme_knopf
        knopf.setMinimumWidth(0)
        knopf.setMaximumWidth(16777215)
        knopf.ensurePolished()
        gemerkt = knopf.text()
        diktat_breite = 0
        for wort in DIKTAT_WORTE.values():
            knopf.setText(wort)
            diktat_breite = max(diktat_breite, knopf.sizeHint().width())
        knopf.setText(gemerkt)
        knopf.setFixedWidth(diktat_breite)

    # -- Diktat ----------------------------------------------------------------

    def _diktat_zeigen(self, zustand: str) -> None:
        """Wort und Farbe (Property fuer stil.qss) des Diktat-Knopfs."""
        knopf = self.aufnahme_knopf
        knopf.setText(DIKTAT_WORTE[zustand])
        knopf.setProperty("zustand", zustand)
        stil = knopf.style()
        stil.unpolish(knopf)
        stil.polish(knopf)

    def _ton(self, zustand: str) -> None:
        try:
            self.sprecher.ton(zustand)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Ton nicht gespielt: %s", fehler)

    def diktat_umschalten(self) -> None:
        """Knopf und Strg+D: erster Druck startet die Aufnahme, zweiter beendet
        sie und startet die Erkennung. Das Ergebnis kommt als Signal zurueck."""
        if self.diktat.erkennt:
            self._status_zeigen("Die Erkennung läuft noch.")
            return
        if self.diktat.nimmt_auf:
            self._ton("fertig")
            self._diktat_zeigen("erkennt")
            self._status_zeigen("Erkenne…")
            self.diktat.beenden(
                lambda text, senden: self.diktat_fertig.emit(text, senden),
                lambda satz: self.diktat_fehler.emit(satz),
                lambda: self.diktat_leer.emit())
            return
        try:
            self.diktat.starten()
        except diktat.DiktatFehler as fehler:
            self._diktat_fehler(fehler.satz)
            return
        except Exception as fehler:  # noqa: BLE001
            log.exception("Diktat nicht gestartet: %s", type(fehler).__name__)
            self._diktat_fehler("Diktat konnte nicht starten.")
            return
        self._ton("bereit")
        self._diktat_zeigen("aufnahme")
        self._status_zeigen("Aufnahme läuft. Zum Beenden nochmal drücken.")

    def _diktat_fertig(self, text: str, senden: bool) -> None:
        self._diktat_zeigen("bereit")
        if text:
            cursor = self.eingabe.textCursor()
            davor = self.eingabe.toPlainText()[:cursor.position()]
            if davor and not davor[-1].isspace():
                text = " " + text
            self.eingabe.insertPlainText(text)
        self._status_zeigen("Diktat eingefügt.")
        if senden:
            self.senden()

    def _diktat_leer(self) -> None:
        self._diktat_zeigen("bereit")
        self._status_zeigen("Nichts verstanden.")

    def _diktat_fehler(self, satz: str) -> None:
        self._diktat_zeigen("bereit")
        self._status_zeigen(satz)
        log.error("Diktat-Fehler gemeldet")
        self._ton("fehler")
        try:
            self.sprecher.sprich(satz, art="fehler")
        except Exception as fehler:  # noqa: BLE001
            log.exception("Fehlermeldung nicht gesprochen: %s", fehler)

    def changeEvent(self, ereignis) -> None:
        super().changeEvent(ereignis)
        # Neues Stilblatt (Schriftskalierung) oder neue Schrift: Breite neu messen.
        if ereignis.type() in (QEvent.StyleChange, QEvent.FontChange) and hasattr(self, "vorlesen_knopf"):
            # Erst nach dem Ereignis messen: die Knoepfe selbst bekommen das neue
            # Stilblatt erst nach ihrem Elternwidget.
            QTimer.singleShot(0, self._knopfbreite_angleichen)

    def showEvent(self, ereignis) -> None:
        super().showEvent(ereignis)
        self._knopfbreite_angleichen()

    def fokus_setzen(self) -> None:
        self.eingabe.setFocus()

    # -- Faden ---------------------------------------------------------------

    def zustand(self) -> dict:
        """Stand fuer das Werkzeug `status`. Wird aus dem Faden der Orchestrator-
        Sitzung gelesen; die Werte sind einfache Zahlen und Texte."""
        geber = getattr(self, "_fenster_zustand", None)
        if geber is not None:
            try:
                return dict(geber())
            except Exception as fehler:  # noqa: BLE001
                log.exception("Fensterzustand nicht lesbar: %s", fehler)
        return {"projekt": self.projekt.name}

    def fenster_zustand_setzen(self, geber) -> None:
        """Das Hauptfenster gibt hier einen Leser seiner Warteschlange mit
        (Projekt, laeuft, wartet, taetigkeit)."""
        self._fenster_zustand = geber

    def _faden_sicherstellen(self) -> OrchestratorFaden:
        if self.faden is not None and self.faden.isRunning():
            return self.faden
        faden = OrchestratorFaden(self.projekt, zustand_geber=self.zustand)
        faden.ereignis_da.connect(self._ereignis)
        faden.text_da.connect(self._text)
        faden.werkzeug_da.connect(self._werkzeug)
        faden.werkzeug_ergebnis_da.connect(self._werkzeug_ergebnis)
        faden.fertig_da.connect(self._fertig)
        faden.frage_da.connect(self._frage)
        faden.bereit_da.connect(self._bereit)
        faden.abgestuerzt_da.connect(self._abgestuerzt)
        self.faden = faden
        faden.start()
        log.info("Orchestrator-Faden gestartet (Projekt %s, Modell %s)", self.projekt.name,
                 faden.modell)
        return faden

    def senden(self) -> None:
        text = self.eingabe.toPlainText().strip()
        if not text:
            self._status_zeigen("Nichts zu senden." if not self.bilder
                                else "Bilder brauchen einen Text dazu.")
            return
        try:
            faden = self._faden_sicherstellen()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Orchestrator-Faden nicht gestartet: %s", fehler)
            self._absatz(f"Orchestrator nicht gestartet: {fehler}", "fehler")
            self._zustand_zeigen("fehler", "Fehler")
            return
        self.eingabe.clear()
        # Nur die Anzeige wird leer; der Verlauf liegt vollstaendig in
        # verlauf.txt, die Sitzung behaelt ihr Gedaechtnis. Stumm.
        self.verlauf.clear()
        # Wartende Meldungen von CWB gehen vor Roberts Text mit - aber nur, wenn
        # die Sitzung frei ist; sonst bleiben sie in der Schlange.
        meldungen = ""
        if self._offen == 0 and not self.frage_offen:
            meldungen = self.schlange.entnehmen()
        if meldungen:
            kopfzeilen = [z for z in meldungen.splitlines()
                          if z.startswith(orchestrator.MELDUNG_KOPF)]
            self._absatz("\n".join(kopfzeilen) or "Meldung(en) von CWB", "hinweis")
            log.info("Meldungen vor Roberts Text zugestellt (%d Kopfzeile(n))", len(kopfzeilen))
            text_senden = meldungen + orchestrator.MELDUNG_TRENNER + text
        else:
            text_senden = text
        self._absatz(text, "auftrag")
        # Robert hat geschrieben: der Schleifenschutz beginnt von vorn
        orchestrator.SCHLEIFE.zuruecksetzen()
        self._offen += 1
        self._arten.append("text_meldung" if meldungen else "text")
        self._antwort_teile = []
        if self._offen > 1:
            self._status_zeigen(f"Vorgemerkt, {self._offen - 1} davor.")
        else:
            self._zustand_zeigen("denkt", "denkt")
            self._status_zeigen("Gesendet.")
        bilder, self.bilder = list(self.bilder), []
        self._bilder_zeigen()
        faden.auftrag_geben(text_senden, bilder)

    def not_aus(self) -> None:
        """Stopp-Knopf und F8: bricht den laufenden Auftrag ab und verwirft
        wartende. Beruehrt die normale Sitzung nicht."""
        if self.faden is None or not self.faden.isRunning():
            return
        self.faden.wartende_verwerfen()
        self.faden.not_aus()
        # Eine schon uebergebene, aber nicht verarbeitete Meldung bleibt in der
        # Schlange (wird beim naechsten Anlass zugestellt, nicht sofort).
        self._arten.clear()
        self.schlange.zurueckstellen()
        self._offen = 1 if self.faden.faden_beschaeftigt else 0
        if self.frage_offen:
            self.frage_beantworten(False)
        self._absatz("Gestoppt.", "hinweis")
        self._status_zeigen("Gestoppt.")
        self._zustand_zeigen("gestoppt", "gestoppt")

    def beschaeftigt(self) -> bool:
        """Wahr, wenn die Orchestrator-Sitzung arbeitet oder eine Frage offen ist."""
        return self._offen > 0 or self.frage_offen

    def beenden(self) -> None:
        self.diktat.abbrechen()
        self._arten.clear()
        self.schlange.zurueckstellen()
        faden, self.faden = self.faden, None
        if faden is None:
            return
        faden.wartende_verwerfen()
        if self.frage_offen:
            faden.frage_beantworten(False)
        faden.beenden()
        if not faden.wait(5000):
            log.warning("Orchestrator-Faden endete nicht binnen 5 s")

    def frage_beantworten(self, ja: bool) -> None:
        if not self.frage_offen or self.faden is None:
            return
        self.frage_offen = False
        self._absatz("Freigegeben." if ja else "Abgelehnt.", "hinweis")
        self._zustand_zeigen("denkt", "denkt")
        self.sprecher.sprich("Ja." if ja else "Nein.")
        self.faden.frage_beantworten(ja)

    # -- Meldungen von CWB (Etappe 1B) ------------------------------------------

    def meldung_annehmen(self, schluessel, text: str) -> bool:
        """Nimmt die Meldung zu einem fertigen Orchestrator-Auftrag entgegen
        (Schluessel = Auftragsnummer) und stellt sie zu, sobald die Sitzung frei
        ist. False, wenn die Nummer schon bekannt war."""
        neu = self.schlange.vormerken(schluessel, text)
        if neu:
            self._status_zeigen(f"Meldung zu Auftrag {schluessel} vorgemerkt.")
            self.zustellen()
        return neu

    def zustellen(self) -> bool:
        """Gibt ALLE wartenden Meldungen als eine Nachricht an die Sitzung -
        aber nur, wenn sie frei ist: weder arbeitet sie (Roberts Text hat
        Vorrang, er haelt `_offen` hoch) noch wartet eine Rueckfrage auf Robert.
        Rueckgabe: wurde zugestellt."""
        if self._offen > 0 or self.frage_offen or self.schlange.anzahl() == 0:
            return False
        try:
            faden = self._faden_sicherstellen()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Orchestrator-Faden fuer Meldungen nicht gestartet: %s", fehler)
            self._absatz(f"Meldungen warten, Orchestrator nicht gestartet: {fehler}", "fehler")
            return False
        anzahl = self.schlange.anzahl()
        text = self.schlange.entnehmen()
        if not text:
            return False
        kopfzeilen = [z for z in text.splitlines() if z.startswith(orchestrator.MELDUNG_KOPF)]
        self._absatz("\n".join(kopfzeilen) or f"{anzahl} Meldung(en) von CWB", "hinweis")
        self._offen += 1
        self._arten.append("meldung")
        self._antwort_teile = []
        self._zustand_zeigen("denkt", "denkt")
        self._status_zeigen(f"{anzahl} Meldung(en) von CWB zugestellt.")
        faden.auftrag_geben(text, [])
        return True

    def nachholen(self) -> None:
        """Nach dem Start: Meldungen, die der letzte Lauf nicht mehr zustellen
        konnte, jetzt zustellen."""
        self.zustellen()

    def kontingent_setzen(self, zustand: dict | None) -> None:
        zeile, stufe = orchestrator.kontingent_anzeige(zustand)
        self.kontingent.setText(zeile)
        # Beim Wechsel auf "knapp" einmal der Warnton, kein gesprochener Satz.
        if stufe == "knapp" and self._kontingent_stufe not in ("start", "knapp"):
            self.sprecher.ton("wartet")
        self._kontingent_stufe = stufe or "normal"

    def _kontingent_aus_faden(self) -> None:
        sitzung = getattr(self.faden, "sitzung", None) if self.faden is not None else None
        if sitzung is None:
            return
        try:
            self.kontingent_setzen(sitzung.kontingent_zustand())
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kontingent der Orchestrator-Sitzung nicht lesbar: %s", fehler)

    # -- Rueckmeldungen des Fadens (nur dieser Ansicht) -----------------------

    def _ereignis(self, zustand, ansage, detail, pfad, taetigkeit, ablehnung, hinweis) -> None:
        # Farbe des Titels folgt der Taetigkeit - nur, solange ein Auftrag laeuft
        # (spaete Ereignisse nach F8 duerfen das Grau nicht uebermalen).
        farbe = TITEL_ZUSTAND.get(str(zustand))
        if farbe and self._offen > 0 and not self.frage_offen:
            self._zustand_zeigen(*farbe)
        if taetigkeit:
            name = Path(pfad).name if pfad else ""
            self._taetigkeit = f"{taetigkeit} {name}".strip()
            self._status_zeigen(self._taetigkeit)
        if ablehnung and ansage:
            self._absatz(f"{ansage} {detail}".strip(), "hinweis")

    def _befehl_zeigen(self, zeile: str) -> None:
        """Stille Zeile fuer die Befehlsanzeige: nie gesprochen, nie Teil der Antwort."""
        try:
            if orchestrator.befehle_anzeigen():
                self._absatz(zeile, orchestrator.BEFEHL_ART)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Befehlszeile nicht angezeigt: %s", fehler)

    def _werkzeug(self, name: str, eingabe: dict) -> None:
        self._befehl_zeigen(orchestrator.befehl_zeile(name, eingabe))

    def _werkzeug_ergebnis(self, name: str, eingabe: dict, status: str, text: str) -> None:
        self._befehl_zeigen(orchestrator.ergebnis_zeile(name, eingabe, status, text))

    def _text(self, text: str) -> None:
        self._antwort_teile.append(text)
        self._absatz(text, "antwort")

    def _bereit(self) -> None:
        if not self._offen:
            self._zustand_zeigen("bereit", "bereit")

    def _frage(self, satz: str, kurz_satz: str) -> None:
        self.frage_offen = True
        self._zustand_zeigen("wartet", "wartet auf Antwort")
        self._status_zeigen(f"Rückfrage: {satz}   Eingabe = ja, Escape = nein")
        self._absatz(f"{satz}\nEingabe = ja, Escape = nein", "frage")
        self.frage_gestellt.emit(satz, kurz_satz)

    def _fertig(self, bilanz: dict) -> None:
        self._offen = max(0, self._offen - 1)
        art = self._arten.popleft() if self._arten else "text"
        sauber = not (bilanz.get("fehler") or bilanz.get("kontingent")
                      or bilanz.get("abgebrochen"))
        if art in ("meldung", "text_meldung"):
            if sauber:
                self.schlange.quittieren()
            else:
                self.schlange.zurueckstellen()
        self._kontingent_aus_faden()
        try:
            self._fertig_anzeigen(bilanz)
        finally:
            # Erst nach der Anzeige: Roberts Text hat Vorrang (er haelt _offen
            # hoch), und nach einem Fehler oder Abbruch wird nicht sofort neu
            # zugestellt - sonst drehte sich ein Fehler im Kreis.
            if sauber and self._offen == 0:
                self.zustellen()

    def _fertig_anzeigen(self, bilanz: dict) -> None:
        if str(bilanz.get("antwort") or "").strip():
            self._letzte_antwort = str(bilanz["antwort"])
        fehler = str(bilanz.get("fehler") or "")
        if fehler:
            self._absatz(fehler, "fehler")
            self._zustand_zeigen("fehler", "Fehler")
            self._status_zeigen("Fehler.")
            self.sprecher.sprich("Orchestrator: Fehler.", art="fehler")
            return
        if bilanz.get("kontingent"):
            self._absatz("Kontingent erschöpft. Später erneut senden.", "hinweis")
            self._zustand_zeigen("fehler", "Kontingent erschöpft")
            self._status_zeigen("Kontingent erschöpft.")
            self.sprecher.sprich("Orchestrator: Kontingent erschöpft.", art="fehler")
            return
        if bilanz.get("abgebrochen"):
            self._zustand_zeigen("gestoppt", "gestoppt")
            return
        if self._offen:
            self._status_zeigen(f"{self._offen} weitere in Arbeit.")
            return
        antwort = vorlese_text(str(bilanz.get("antwort") or ""))
        self._zustand_zeigen("fertig", "fertig")
        self._status_zeigen("Fertig.")
        self.sprecher.sprich(antwort or "Orchestrator fertig.", art="fertig")

    def _abgestuerzt(self, meldung: str) -> None:
        self._offen = 0
        self.frage_offen = False
        self._arten.clear()
        self.schlange.zurueckstellen()
        self._absatz(f"Der Orchestrator-Faden ist abgestürzt: {meldung}", "fehler")
        self._zustand_zeigen("fehler", "abgestürzt")
        self._status_zeigen("Abgestürzt. Beim nächsten Senden startet er neu.")
        self.sprecher.sprich("Orchestrator abgestürzt.", art="fehler")
