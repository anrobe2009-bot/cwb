"""
CWB - Code Workbench
Einstellungsseite (F12, Kachel "Einstellungen").

Sieben Reiter; passt der Inhalt eines Reiters nicht auf die Seite, wird
dort gerollt statt abgeschnitten:

- Sprache   Sprachausgabe in drei Stufen, Ausgabeweg, Stimme, Tempo,
            Probehoeren
- Toene     Hauptschalter und drei Gruppen, je mit Probehoeren
- Verhalten Zwischenablage, Bericht, Mauszeiger-Ansage fuer das ganze
  Fenster (core/zeigeransage.py), drei Rueckfrage-Ausnahmen (Internet,
  Loeschen im Projektordner, Installieren - alle drei ab Werk aus,
  core/sicherheit.py wertet sie aus, core/kopfzeile.py zeigt sie an),
  Tokenverbrauch je Tag
- Skills    reine Anzeige der geladenen Skills, Ordner oeffnen
- Pfade     Projektordner, Skill-Ordner, Memory Hub; dieselben Angaben wie
            bei der Ersteinrichtung, jederzeit aenderbar
- Projekte  gepflegte Zusatzliste: Projekte ausserhalb des Projektordners,
            mit Ordnerdialog hinzugefuegt, frei benannt, entfernbar
- Freigaben gepflegte Liste von Ordnern ausserhalb des Projekts, in denen
            core/sicherheit.py (Ordnergrenze) ohne Rueckfrage liest und
            schreibt - mit Ordnerdialog hinzugefuegt, entfernbar. Skill-
            Ordner, Claude-Temp-Ordner und cwb-werkzeuge stehen darin nur
            noch als Voreintraege. Die Sperrliste fuer Zugangsdaten und
            die verbotenen Befehle gelten in jeder Freigabe unveraendert
            weiter. core/kopfzeile.py zeigt die Anzahl aktiver Freigaben.

Gewechselt wird mit Strg+Tabulator (vorwaerts), Strg+Umschalt+Tabulator
(rueckwaerts) und mit den Pfeiltasten, sobald die Reiterleiste den Fokus hat.
Bei jedem Wechsel sagt CWB den Reiternamen und seine Nummer an.

Jede Aenderung wirkt sofort auf den laufenden Sprecher und wird in
einstellungen.json gesichert. Nichts muss bestaetigt werden.

Alles ist mit der Tastatur erreichbar. Beim Anspringen sagt CWB selbst an,
was unter dem Fokus liegt - unabhaengig davon, ob ein Screenreader laeuft.
Escape schliesst.

Aussehen kommt vollstaendig aus stil.qss. Hier steht keine Farbe und keine
Groesse, nur Objektnamen, ueber die das Stilblatt zugreift.
"""

import logging
import os
import threading
from datetime import date
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from .ersteinrichtung import Pfadzeile
    from .grundlagen import TAGE_AUFBEWAHRT, heutiger_tag, tagesverbrauch_lesen
    from .kopfzeile import zahl_lang
    from .pfade import (
        freigabe_entfernen,
        freigabe_hinzufuegen,
        freigaben_lesen,
        hub_datenbank,
        hub_datenbank_merken,
        log_einrichten,
        projektwurzel,
        projektwurzel_merken,
        projektwurzel_vorschlag,
        skill_ordner,
        skill_ordner_merken,
        zusatzprojekt_entfernen,
        zusatzprojekt_hinzufuegen,
        zusatzprojekte_lesen,
    )
    from .sprache import (
        STUFEN,
        TON_GRUPPEN_PROBE,
        TON_GRUPPEN_STANDARD,
        TON_GRUPPEN_TITEL,
        Sprecher,
    )
except ImportError:
    from ersteinrichtung import Pfadzeile
    from grundlagen import TAGE_AUFBEWAHRT, heutiger_tag, tagesverbrauch_lesen
    from kopfzeile import zahl_lang
    from pfade import (
        freigabe_entfernen,
        freigabe_hinzufuegen,
        freigaben_lesen,
        hub_datenbank,
        hub_datenbank_merken,
        log_einrichten,
        projektwurzel,
        projektwurzel_merken,
        projektwurzel_vorschlag,
        skill_ordner,
        skill_ordner_merken,
        zusatzprojekt_entfernen,
        zusatzprojekt_hinzufuegen,
        zusatzprojekte_lesen,
    )
    from sprache import (
        STUFEN,
        TON_GRUPPEN_PROBE,
        TON_GRUPPEN_STANDARD,
        TON_GRUPPEN_TITEL,
        Sprecher,
    )

CWB_WURZEL = Path(__file__).resolve().parent.parent
LOG_DATEI = CWB_WURZEL / "cwb_fehler.log"

log_einrichten()
log = logging.getLogger("cwb.einstellungen")

# Skills liegen im eingestellten Skill-Ordner (Reiter "Pfade", Vorschlag
# `.claude/skills` im Benutzerordner) und, projektbezogen, im Projekt selbst.
SKILLS_IM_PROJEKT = Path(".claude") / "skills"

# Nur der Kopf einer SKILL.md wird gebraucht; der Rest kann lang sein.
SKILL_KOPF_ZEICHEN = 4000
SKILL_BESCHREIBUNG_ZEICHEN = 160

PROBESATZ = "Größe, Prüfung und Änderung. Fertig, drei Dateien geändert."

# Wartezeit, bevor eine getippte Tempoaenderung gesichert und angesagt wird.
TEMPO_RUHE_MS = 400

AUSGABEWEGE = [
    ("edge", "Edge, natürliche Stimme, braucht Internet"),
    ("sapi", "SAPI, Windows-Bordstimme, immer verfügbar"),
]


# ---------------------------------------------------------------------------
# Skills einlesen - reine Anzeige, es wird nichts geschrieben
# ---------------------------------------------------------------------------

def _kopfangaben(text: str) -> dict:
    """Liest die Angaben aus dem YAML-Kopf einer SKILL.md.

    Bewusst kein YAML-Paket: gebraucht werden nur die flachen Zeilen
    `name:` und `description:` zwischen den beiden Trennlinien."""
    zeilen = text.splitlines()
    if not zeilen or zeilen[0].strip() != "---":
        return {}
    werte: dict[str, str] = {}
    for zeile in zeilen[1:]:
        if zeile.strip() == "---":
            break
        if not zeile[:1].strip() or ":" not in zeile:
            continue
        schluessel, _, wert = zeile.partition(":")
        werte[schluessel.strip().lower()] = wert.strip().strip("\"'")
    return werte


def skills_lesen(ordner: Path, herkunft: str) -> list[dict]:
    """Alle SKILL.md unterhalb eines Ordners, je mit Name, Beschreibung,
    Herkunft und Pfad. Fehlt der Ordner, ist die Liste leer."""
    gefunden: list[dict] = []
    try:
        if not ordner.is_dir():
            return gefunden
        unterordner = sorted(p for p in ordner.iterdir() if p.is_dir())
    except OSError as fehler:
        log.error("Skill-Ordner nicht lesbar (%s): %s", ordner, fehler)
        return gefunden

    for unter in unterordner:
        datei = unter / "SKILL.md"
        if not datei.is_file():
            continue
        try:
            kopf = _kopfangaben(
                datei.read_text(encoding="utf-8", errors="replace")[:SKILL_KOPF_ZEICHEN]
            )
        except OSError as fehler:
            log.error("SKILL.md nicht lesbar (%s): %s", datei, fehler)
            kopf = {}
        beschreibung = kopf.get("description", "")
        if len(beschreibung) > SKILL_BESCHREIBUNG_ZEICHEN:
            beschreibung = beschreibung[:SKILL_BESCHREIBUNG_ZEICHEN].rstrip() + " …"
        gefunden.append(
            {
                "name": kopf.get("name", unter.name),
                "beschreibung": beschreibung or "ohne Beschreibung",
                "herkunft": herkunft,
                "ordner": unter,
            }
        )
    log.info("Skills gefunden in %s: %d", ordner, len(gefunden))
    return gefunden


# ---------------------------------------------------------------------------
# Stimmenliste im Hintergrund holen
# ---------------------------------------------------------------------------

class StimmenLader(QObject):
    """Holt die deutschen Stimmen in einem eigenen Faden.

    Der Abruf geht ins Netz und dauert im schlechten Fall Sekunden; im
    Hauptfaden wuerde die Einstellungsseite so lange stehen bleiben. Das
    Signal traegt das Ergebnis zurueck in den Hauptfaden."""

    fertig = Signal(list)

    def starten(self) -> None:
        threading.Thread(target=self._holen, daemon=True).start()

    def _holen(self) -> None:
        try:
            stimmen = Sprecher.stimmen_auflisten()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Stimmenliste nicht abrufbar: %s", fehler)
            stimmen = []
        self.fertig.emit(stimmen)


# ---------------------------------------------------------------------------
# Bausteine der Seite
# ---------------------------------------------------------------------------

# Deutsche Monatsnamen von Hand: die Spracheinstellung des Systems ist nicht
# verlaesslich, und vorgelesen werden soll der Monat ausgeschrieben.
MONATE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)


def _tag_lesbar(tag: str) -> str:
    """Aus '2026-09-05' wird '5. September 2026'. Laesst sich der Schluessel
    nicht deuten, bleibt er unveraendert stehen."""
    try:
        wann = date.fromisoformat(tag)
    except (TypeError, ValueError):
        return str(tag)
    return f"{wann.day}. {MONATE[wann.month - 1]} {wann.year}"


class Gruppe(QFrame):
    """Eine Karte mit Ueberschrift; die Bereiche der Seite sehen alle gleich
    aus. Der Inhalt kommt ueber `zeile` oder `feld` hinein."""

    def __init__(self, titel: str, hinweis: str = ""):
        super().__init__()
        self.setObjectName("gruppe")
        self.setAccessibleName(titel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.aufbau = QVBoxLayout(self)

        ueberschrift = QLabel(titel)
        ueberschrift.setObjectName("gruppentitel")
        self.aufbau.addWidget(ueberschrift)

        if hinweis:
            zusatz = QLabel(hinweis)
            zusatz.setObjectName("gruppenhinweis")
            zusatz.setWordWrap(True)
            self.aufbau.addWidget(zusatz)

    def feld(self, widget: QWidget) -> QWidget:
        """Ein Bedienelement ueber die volle Breite."""
        self.aufbau.addWidget(widget)
        return widget

    def zeile(self, beschriftung: str, widget: QWidget) -> QWidget:
        """Beschriftung links, Bedienelement rechts. Beide wachsen mit."""
        halter = QWidget()
        halter.setObjectName("gruppenzeile")
        quer = QHBoxLayout(halter)
        quer.setContentsMargins(0, 0, 0, 0)

        text = QLabel(beschriftung)
        text.setObjectName("feldname")
        text.setWordWrap(True)
        quer.addWidget(text, 2)
        quer.addWidget(widget, 3)

        self.aufbau.addWidget(halter)
        return widget

    def nebeneinander(self, links: QWidget, rechts: QWidget) -> None:
        """Zwei Bedienelemente in einer Zeile, etwa Schalter und Probe."""
        halter = QWidget()
        halter.setObjectName("gruppenzeile")
        quer = QHBoxLayout(halter)
        quer.setContentsMargins(0, 0, 0, 0)
        quer.addWidget(links, 3)
        quer.addWidget(rechts, 1)
        self.aufbau.addWidget(halter)


# ---------------------------------------------------------------------------
# Reiterleiste mit Zeilenumbruch: ein QTabWidget versteckt ueberzaehlige
# Reiter hinter Rollpfeilen oder schneidet sie ab, sobald das Fenster
# schmaler ist als die Summe aller Reiterbreiten. Hier bricht die Leiste
# stattdessen in eine zweite Zeile um - jeder Reiter bleibt sichtbar und
# erreichbar, egal wie klein das Fenster oder wie gross die Systemschrift.
# ---------------------------------------------------------------------------

class Fliessraster(QLayout):
    """Reiht seine Kinder nebeneinander und bricht in die naechste Zeile um,
    sobald die Breite nicht mehr reicht - anders als QHBoxLayout, das Kinder
    seitlich abschneidet oder gleichmaessig staucht."""

    def __init__(self, eltern: QWidget | None = None):
        super().__init__(eltern)
        self._eintraege: list = []
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, eintrag) -> None:
        self._eintraege.append(eintrag)

    def count(self) -> int:
        return len(self._eintraege)

    def itemAt(self, index: int):
        if 0 <= index < len(self._eintraege):
            return self._eintraege[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._eintraege):
            return self._eintraege.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, breite: int) -> int:
        return self._auslegen(QRect(0, 0, breite, 0), wirklich=False)

    def setGeometry(self, rechteck: QRect) -> None:
        super().setGeometry(rechteck)
        self._auslegen(rechteck, wirklich=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        groesse = QSize()
        for eintrag in self._eintraege:
            groesse = groesse.expandedTo(eintrag.minimumSize())
        links, oben, rechts, unten = self.getContentsMargins()
        return groesse + QSize(links + rechts, oben + unten)

    def _auslegen(self, rechteck: QRect, wirklich: bool) -> int:
        links, oben, rechts, unten = self.getContentsMargins()
        wirksam = rechteck.adjusted(links, oben, -rechts, -unten)
        x, y = wirksam.x(), wirksam.y()
        zeilenhoehe = 0
        for eintrag in self._eintraege:
            hinweis = eintrag.sizeHint()
            naechstes_x = x + hinweis.width() + self.spacing()
            if naechstes_x - self.spacing() > wirksam.right() and zeilenhoehe > 0:
                x = wirksam.x()
                y = y + zeilenhoehe + self.spacing()
                naechstes_x = x + hinweis.width() + self.spacing()
                zeilenhoehe = 0
            if wirklich:
                eintrag.setGeometry(QRect(x, y, hinweis.width(), hinweis.height()))
            x = naechstes_x
            zeilenhoehe = max(zeilenhoehe, hinweis.height())
        return y + zeilenhoehe - rechteck.y() + unten


class Reiterleiste(QWidget):
    """Ersetzt die Reiterleiste eines QTabWidget: ein einziger Tabulator-
    Stopp fuer die ganze Leiste, Pfeiltasten wechseln den aktiven Reiter -
    wie bei QTabBar. Anders als QTabBar bricht sie bei Platzmangel um,
    statt Reiter seitlich zu verstecken."""

    aktuelleStelleGewechselt = Signal(int)

    def __init__(self, eltern: QWidget | None = None):
        super().__init__(eltern)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._knoepfe: list[QToolButton] = []
        self._stelle = -1
        Fliessraster(self)  # setzt sich als Layout dieses Widgets selbst ein

    def anzahl(self) -> int:
        return len(self._knoepfe)

    def text(self, stelle: int) -> str:
        if 0 <= stelle < len(self._knoepfe):
            return self._knoepfe[stelle].text()
        return ""

    def hinzufuegen(self, titel: str) -> int:
        neue_stelle = len(self._knoepfe)
        knopf = QToolButton(self)
        knopf.setText(titel)
        knopf.setCheckable(True)
        knopf.setFocusPolicy(Qt.NoFocus)
        knopf.clicked.connect(partial(self._angeklickt, neue_stelle))
        self.layout().addWidget(knopf)
        self._knoepfe.append(knopf)
        if self._stelle < 0:
            self.stelle_setzen(0)
        return neue_stelle

    def stelle(self) -> int:
        return self._stelle

    def stelle_setzen(self, stelle: int) -> None:
        if not 0 <= stelle < len(self._knoepfe) or stelle == self._stelle:
            return
        self._stelle = stelle
        for index, knopf in enumerate(self._knoepfe):
            knopf.setChecked(index == stelle)
        self.aktuelleStelleGewechselt.emit(stelle)

    def _angeklickt(self, stelle: int) -> None:
        self.stelle_setzen(stelle)
        self.setFocus()

    def keyPressEvent(self, ereignis) -> None:
        if not self._knoepfe:
            super().keyPressEvent(ereignis)
            return
        if ereignis.key() in (Qt.Key_Right, Qt.Key_Down):
            self.stelle_setzen((self._stelle + 1) % len(self._knoepfe))
            return
        if ereignis.key() in (Qt.Key_Left, Qt.Key_Up):
            self.stelle_setzen((self._stelle - 1) % len(self._knoepfe))
            return
        super().keyPressEvent(ereignis)


class ReiterAnsicht(QWidget):
    """Ersatz fuer QTabWidget aus `Reiterleiste` (umbrechende Reiter) und
    einem QStackedWidget fuer die Seiten. Bietet dieselbe schmale
    Schnittstelle, die der Rest der Datei benutzt: addTab, count,
    currentIndex, setCurrentIndex, tabText, tabBar, currentChanged."""

    currentChanged = Signal(int)

    def __init__(self, eltern: QWidget | None = None):
        super().__init__(eltern)
        aufbau = QVBoxLayout(self)
        aufbau.setContentsMargins(0, 0, 0, 0)
        self._leiste = Reiterleiste(self)
        self._stapel = QStackedWidget(self)
        self._stapel.setObjectName("reiterstapel")
        aufbau.addWidget(self._leiste)
        aufbau.addWidget(self._stapel, 1)
        self._leiste.aktuelleStelleGewechselt.connect(self._stapel.setCurrentIndex)
        self._leiste.aktuelleStelleGewechselt.connect(self.currentChanged)

    def addTab(self, seite: QWidget, titel: str) -> int:
        self._stapel.addWidget(seite)
        return self._leiste.hinzufuegen(titel)

    def count(self) -> int:
        return self._leiste.anzahl()

    def currentIndex(self) -> int:
        return self._leiste.stelle()

    def setCurrentIndex(self, stelle: int) -> None:
        self._leiste.stelle_setzen(stelle)

    def tabText(self, stelle: int) -> str:
        return self._leiste.text(stelle)

    def tabBar(self) -> Reiterleiste:
        return self._leiste


# ---------------------------------------------------------------------------
# Die Seite selbst
# ---------------------------------------------------------------------------

class EinstellungenFenster(QDialog):
    """Einstellungsseite. Liest und schreibt ueber die uebergebenen
    Funktionen, damit dieses Modul nichts von fenster.py wissen muss."""

    def __init__(self, eltern, sprecher, lesen, schreiben, projekt_pfad=None):
        super().__init__(eltern)
        self.sprecher = sprecher
        self._lesen = lesen
        self._schreiben = schreiben
        self._projekt_pfad = Path(projekt_pfad) if projekt_pfad else None
        self._skills: list[dict] = []
        self._verbrauchstage: list[tuple[str, int]] = []
        self._zusatzprojekte: list[dict] = []
        self._freigaben: list[dict] = []

        self.setObjectName("einstellungen")
        self.setWindowTitle("CWB — Einstellungen")
        self.setAccessibleName("Einstellungen")
        self.setAccessibleDescription(
            "Sieben Reiter: Sprache, Töne, Verhalten, Skills, Pfade, Projekte, "
            "Freigaben. Strg und Tabulator wechselt den Reiter, Escape schließt."
        )

        self._aufbauen()
        self._fokusansage_anmelden()
        self._groesse_setzen(eltern)

        self._lader = StimmenLader(self)
        self._lader.fertig.connect(self._stimmen_eintragen)
        self._lader.starten()

    # -- Aufbau -------------------------------------------------------------

    def _groesse_setzen(self, eltern) -> None:
        """Groesse relativ zum Bildschirm, nicht in festen Pixeln: hoechstens
        85 Prozent von Bildschirmbreite und -hoehe, egal wie gross das
        Elternfenster oder die Systemschrift ist. Nach unten laesst sich das
        Fenster deutlich weiter verkleinern, weil jeder Reiterinhalt in
        einem Rollbereich liegt (siehe `_reiterseite`)."""
        bildschirm = self.screen() or QGuiApplication.primaryScreen()
        if bildschirm is None:
            return
        verfuegbar = bildschirm.availableGeometry()
        hoechstbreite = int(verfuegbar.width() * 0.85)
        hoechsthoehe = int(verfuegbar.height() * 0.85)
        try:
            self.setMaximumSize(hoechstbreite, hoechsthoehe)
            self.setMinimumSize(
                min(320, hoechstbreite), min(240, hoechsthoehe)
            )
            breite, hoehe = hoechstbreite, hoechsthoehe
            if eltern is not None:
                breite = min(int(eltern.width() * 0.82), hoechstbreite)
                hoehe = min(int(eltern.height() * 0.88), hoechsthoehe)
            self.resize(breite, hoehe)
        except Exception as fehler:  # noqa: BLE001
            log.warning("Fenstergröße nicht setzbar: %s", fehler)

    def _aufbauen(self) -> None:
        aufbau = QVBoxLayout(self)

        titel = QLabel("Einstellungen")
        titel.setObjectName("einstellungstitel")
        aufbau.addWidget(titel)

        hinweis = QLabel(
            "Strg und Tabulator wechselt den Reiter, Pfeiltasten ebenso. "
            "Tabulator wechselt das Element, Leertaste schaltet um. "
            "Escape schließt. Jede Änderung wirkt sofort."
        )
        hinweis.setObjectName("einstellungshinweis")
        hinweis.setWordWrap(True)
        aufbau.addWidget(hinweis)

        self.reiter = ReiterAnsicht()
        self.reiter.setObjectName("einstellungsreiter")
        self.reiter.setAccessibleName("Bereich")
        self.reiter.setAccessibleDescription(
            "Strg und Tabulator wechselt den Reiter, Pfeiltasten ebenso"
        )
        # Reicht die Breite nicht fuer alle Reiter, bricht die Leiste in eine
        # zweite Zeile um (siehe `Reiterleiste`), statt Reiter zu verstecken.
        self.reiter.tabBar().setObjectName("reiterleiste")
        self.reiter.tabBar().setAccessibleName("Reiter")
        self.reiter.addTab(
            self._reiterseite(self._gruppe_stufe(), self._gruppe_sprache()), "Sprache"
        )
        self.reiter.addTab(self._reiterseite(self._gruppe_toene()), "Töne")
        self.reiter.addTab(self._reiterseite(self._gruppe_verhalten()), "Verhalten")
        self.reiter.addTab(self._reiterseite(self._gruppe_skills()), "Skills")
        self.reiter.addTab(self._reiterseite(self._gruppe_pfade()), "Pfade")
        self.reiter.addTab(self._reiterseite(self._gruppe_projekte()), "Projekte")
        self.reiter.addTab(self._reiterseite(self._gruppe_freigaben()), "Freigaben")
        self.reiter.currentChanged.connect(self._reiter_gewechselt)
        aufbau.addWidget(self.reiter, 1)

        self._reiterkuerzel_anlegen()

        self.schliessen = QPushButton("Schließen")
        self.schliessen.setObjectName("schliessen")
        self.schliessen.setAccessibleName("Schließen")
        self.schliessen.setAccessibleDescription("Schließt die Einstellungen, wie Escape")
        self.schliessen.clicked.connect(self.reject)
        aufbau.addWidget(self.schliessen)

    # -- Reiter -------------------------------------------------------------

    @staticmethod
    def _reiterseite(*gruppen: "Gruppe") -> QWidget:
        """Haengt eine oder mehrere Karten oben in eine Reiterseite und legt
        sie in einen Rollbereich. Die Streckung darunter haelt den Inhalt
        oben, statt ihn ueber die Hoehe zu zerren; reicht die Fensterhoehe
        nicht, wird gerollt statt abgeschnitten - so laesst sich das Fenster
        auch deutlich kleiner ziehen, ohne dass etwas verschwindet."""
        seite = QWidget()
        seite.setObjectName("reiterseite")
        seitenaufbau = QVBoxLayout(seite)
        for gruppe in gruppen:
            seitenaufbau.addWidget(gruppe)
        seitenaufbau.addStretch(1)

        rollbereich = QScrollArea()
        rollbereich.setObjectName("reiterrollbereich")
        rollbereich.setFrameShape(QFrame.NoFrame)
        rollbereich.setWidgetResizable(True)
        rollbereich.setWidget(seite)
        return rollbereich

    def _reiterkuerzel_anlegen(self) -> None:
        """Strg+Tabulator vor, Strg+Umschalt+Tabulator zurueck. Die Pfeiltasten
        beherrscht die Reiterleiste von sich aus, sobald sie den Fokus hat."""
        for folge, ziel in (
            ("Ctrl+Tab", self._reiter_weiter),
            ("Ctrl+Shift+Tab", self._reiter_zurueck),
            ("Ctrl+PgDown", self._reiter_weiter),
            ("Ctrl+PgUp", self._reiter_zurueck),
        ):
            kuerzel = QShortcut(QKeySequence(folge), self)
            kuerzel.setContext(Qt.WindowShortcut)
            kuerzel.activated.connect(ziel)

    def _reiter_weiter(self) -> None:
        self._reiter_springen(1)

    def _reiter_zurueck(self) -> None:
        self._reiter_springen(-1)

    def _reiter_springen(self, schritt: int) -> None:
        anzahl = self.reiter.count()
        if anzahl < 2:
            return
        self.reiter.setCurrentIndex((self.reiter.currentIndex() + schritt) % anzahl)

    def _reiter_gewechselt(self, stelle: int) -> None:
        """Sagt den neuen Reiter an, damit der Wechsel auch ohne Screenreader
        hoerbar ist, und setzt den Fokus auf die Reiterleiste - von dort führen
        Pfeiltasten weiter und Tabulator in den Inhalt."""
        if not 0 <= stelle < self.reiter.count():
            return
        titel = self.reiter.tabText(stelle)
        log.info("Reiter gewechselt: %s", titel)
        self.reiter.tabBar().setFocus()
        self.sprecher.sprich(f"{titel}. Reiter {stelle + 1} von {self.reiter.count()}.")

    # -- Bereich Sprachausgabe ----------------------------------------------

    def _gruppe_stufe(self) -> Gruppe:
        """Wie viel gesprochen wird. Drei Stufen, jede enthaelt die kleinere.
        Die Wahl wirkt sofort und steht in einstellungen.json unter
        'sprache' -> 'stufe'."""
        gruppe = Gruppe(
            "Sprachausgabe",
            "Ab Werk spricht CWB nur Meldungen. Läuft ein Screenreader, liest "
            "der ohnehin vor, worauf der Fokus steht.",
        )

        self.stufen_schalter: dict[int, QRadioButton] = {}
        for stufe, titel, erklaerung in STUFEN:
            schalter = QRadioButton(f"{titel} — {erklaerung}")
            schalter.setObjectName("stufenwahl")
            schalter.setAccessibleName(titel)
            schalter.setAccessibleDescription(erklaerung)
            schalter.setToolTip(erklaerung)
            schalter.setChecked(stufe == self.sprecher.stufe)
            schalter.toggled.connect(partial(self._stufe_gewaehlt, stufe, titel))
            gruppe.feld(schalter)
            self.stufen_schalter[stufe] = schalter
        return gruppe

    def _stufe_gewaehlt(self, stufe: int, titel: str, an: bool) -> None:
        """Die Ansage geht mit `art="immer"` durch: sonst bliebe gerade die
        Wahl der kleinsten Stufe unbestaetigt."""
        if not an:
            return
        try:
            self.sprecher.stufe_setzen(stufe)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Sprachstufe nicht setzbar: %s", fehler)
            return
        log.info("Sprachstufe gewaehlt: %d (%s)", stufe, titel)
        self.sprecher.sprich(f"Sprachausgabe: {titel}.", art="immer")

    # -- Bereich Sprache ----------------------------------------------------

    def _gruppe_sprache(self) -> Gruppe:
        gruppe = Gruppe(
            "Sprache",
            "Stimme und Tempo gelten ab dem nächsten gesprochenen Satz.",
        )

        self.weg_wahl = QComboBox()
        self.weg_wahl.setObjectName("wegwahl")
        self.weg_wahl.setAccessibleName("Ausgabeweg")
        self.weg_wahl.setAccessibleDescription(
            "Edge klingt natürlicher und braucht Internet, SAPI ist immer da"
        )
        for kennung, beschriftung in AUSGABEWEGE:
            self.weg_wahl.addItem(beschriftung, kennung)
        stelle = self.weg_wahl.findData(self.sprecher.weg)
        if stelle < 0:
            # Ein anderer Weg ist eingestellt (etwa NVDA). Er bleibt sichtbar,
            # solange der Nutzer ihn nicht selbst wechselt.
            self.weg_wahl.addItem(f"{self.sprecher.weg}, unverändert lassen",
                                  self.sprecher.weg)
            stelle = self.weg_wahl.count() - 1
        self.weg_wahl.setCurrentIndex(stelle)
        self.weg_wahl.currentIndexChanged.connect(self._weg_gewechselt)
        gruppe.zeile("Ausgabeweg", self.weg_wahl)

        self.stimmen_wahl = QComboBox()
        self.stimmen_wahl.setObjectName("stimmenwahl")
        self.stimmen_wahl.setAccessibleName("Stimme")
        self.stimmen_wahl.setAccessibleDescription(
            "Deutsche Stimmen für den Ausgabeweg Edge"
        )
        self.stimmen_wahl.addItem(f"{self.sprecher.stimme} (Liste wird geladen)",
                                  self.sprecher.stimme)
        self.stimmen_wahl.currentIndexChanged.connect(self._stimme_gewechselt)
        gruppe.zeile("Stimme", self.stimmen_wahl)

        self.tempo_wahl = QSpinBox()
        self.tempo_wahl.setObjectName("tempowahl")
        self.tempo_wahl.setAccessibleName("Sprechtempo")
        self.tempo_wahl.setAccessibleDescription(
            "Null ist die Normalgeschwindigkeit, Pfeiltasten ändern in Fünferschritten"
        )
        self.tempo_wahl.setRange(-50, 80)
        self.tempo_wahl.setSingleStep(5)
        self.tempo_wahl.setSuffix(" Prozent")
        self.tempo_wahl.setValue(int(self.sprecher.tempo))
        self.tempo_wahl.valueChanged.connect(self._tempo_geaendert)
        gruppe.zeile("Tempo", self.tempo_wahl)

        # Wird beim Tippen mehrfach angestossen; gesichert und angesagt wird
        # erst, wenn der Nutzer kurz nicht mehr dreht.
        self._tempo_uhr = QTimer(self)
        self._tempo_uhr.setSingleShot(True)
        self._tempo_uhr.setInterval(TEMPO_RUHE_MS)
        self._tempo_uhr.timeout.connect(self._tempo_uebernehmen)

        probe = QPushButton("Probe hören")
        probe.setObjectName("probe")
        probe.setAccessibleName("Stimme probe hören")
        probe.setAccessibleDescription("Spricht einen Beispielsatz mit den jetzigen Werten")
        probe.clicked.connect(self._stimme_proben)
        gruppe.feld(probe)
        return gruppe

    def _weg_gewechselt(self, _stelle: int) -> None:
        weg = str(self.weg_wahl.currentData())
        try:
            self.sprecher.weg_setzen(weg)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Ausgabeweg nicht setzbar: %s", fehler)
            return
        log.info("Ausgabeweg gewechselt auf %s", self.sprecher.weg)
        self.sprecher.sprich(f"Ausgabeweg {self.sprecher.weg}.")

    def _stimme_gewechselt(self, _stelle: int) -> None:
        stimme = self.stimmen_wahl.currentData()
        if not stimme or stimme == self.sprecher.stimme:
            return
        try:
            self.sprecher.stimme_setzen(str(stimme))
        except Exception as fehler:  # noqa: BLE001
            log.exception("Stimme nicht setzbar: %s", fehler)
            return
        log.info("Stimme gewechselt auf %s", stimme)
        self.sprecher.sprich("Diese Stimme spricht ab jetzt.")

    def _tempo_geaendert(self, _wert: int) -> None:
        self._tempo_uhr.start()

    def _tempo_uebernehmen(self) -> None:
        tempo = int(self.tempo_wahl.value())
        try:
            self.sprecher.stimme_setzen(self.sprecher.stimme, tempo)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Tempo nicht setzbar: %s", fehler)
            return
        log.info("Tempo gesetzt auf %+d Prozent", tempo)
        self.sprecher.sprich(f"Tempo {tempo:+d} Prozent.")

    def _stimme_proben(self) -> None:
        # Probehoeren gilt in jeder Stufe: sonst bliebe die Schaltflaeche stumm.
        self.sprecher.sprich(PROBESATZ, art="immer")

    def _stimmen_eintragen(self, stimmen: list) -> None:
        """Traegt die im Hintergrund geholten Stimmen ein. Laeuft im
        Hauptfaden, weil das Signal aus dem Ladefaden hierher zurueckspringt."""
        if not stimmen:
            self.stimmen_wahl.setItemText(0, f"{self.sprecher.stimme} (Liste nicht abrufbar)")
            log.warning("Keine Stimmen eingetragen, Liste war leer")
            return

        self.stimmen_wahl.blockSignals(True)
        self.stimmen_wahl.clear()
        for name, geschlecht, land in stimmen:
            kurz = name.split("-")[-1].replace("Neural", "")
            self.stimmen_wahl.addItem(f"{kurz}, {geschlecht}, {land}", name)
        stelle = self.stimmen_wahl.findData(self.sprecher.stimme)
        if stelle < 0:
            self.stimmen_wahl.addItem(self.sprecher.stimme, self.sprecher.stimme)
            stelle = self.stimmen_wahl.count() - 1
        self.stimmen_wahl.setCurrentIndex(stelle)
        self.stimmen_wahl.blockSignals(False)
        log.info("Stimmen eingetragen: %d", len(stimmen))

    # -- Bereich Toene ------------------------------------------------------

    def _gruppe_toene(self) -> Gruppe:
        gruppe = Gruppe(
            "Töne",
            "Kurze Signaltöne begleiten die Arbeit. Alle drei Gruppen sind ab Werk "
            "an; wem die Arbeitstöne bei langen Aufträgen zu viel werden, schaltet "
            "nur diese Gruppe ab.",
        )
        werte = self._toene_lesen()

        self.toene_aus = QCheckBox("Alle Töne aus")
        self.toene_aus.setObjectName("toeneaus")
        self.toene_aus.setAccessibleName("Alle Töne aus")
        self.toene_aus.setAccessibleDescription(
            "Hauptschalter, hat Vorrang vor den drei Gruppen"
        )
        self.toene_aus.setChecked(bool(werte.get("alle_aus", False)))
        self.toene_aus.toggled.connect(self._toene_aus_geschaltet)
        gruppe.feld(self.toene_aus)

        self.ton_schalter: dict[str, QCheckBox] = {}
        for kennung, standard in TON_GRUPPEN_STANDARD.items():
            titel = TON_GRUPPEN_TITEL[kennung]
            schalter = QCheckBox(titel)
            schalter.setObjectName("tongruppe")
            schalter.setAccessibleName(titel)
            schalter.setChecked(bool(werte.get(kennung, standard)))
            schalter.toggled.connect(partial(self._tongruppe_geschaltet, kennung))
            self.ton_schalter[kennung] = schalter

            probe = QPushButton("Probe hören")
            probe.setObjectName("probe")
            probe.setAccessibleName(f"{titel} probe hören")
            probe.setAccessibleDescription("Spielt einen Ton dieser Gruppe")
            probe.clicked.connect(partial(self._ton_proben, kennung))

            gruppe.nebeneinander(schalter, probe)
        return gruppe

    def _toene_lesen(self) -> dict:
        werte = self._werte_lesen().get("toene", {})
        return werte if isinstance(werte, dict) else {}

    def _toene_aus_geschaltet(self, an: bool) -> None:
        self._ton_merken("alle_aus", an)
        self.sprecher.sprich("Alle Töne aus." if an else "Töne wieder an.")

    def _tongruppe_geschaltet(self, kennung: str, an: bool) -> None:
        self._ton_merken(kennung, an)
        self.sprecher.sprich(
            f"{TON_GRUPPEN_TITEL[kennung]}: {'an' if an else 'aus'}."
        )

    def _ton_merken(self, schluessel: str, an: bool) -> None:
        werte = self._werte_lesen()
        toene = werte.get("toene")
        if not isinstance(toene, dict):
            toene = {}
        toene[schluessel] = bool(an)
        werte["toene"] = toene
        self._sichern(werte)
        try:
            self.sprecher.toene_uebernehmen(toene)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Toneinstellung nicht übernommen: %s", fehler)

    def _ton_proben(self, kennung: str) -> None:
        """Spielt den Beispielton der Gruppe, auch wenn sie gerade aus ist -
        sonst bliebe die Schaltflaeche stumm und niemand wuesste warum."""
        try:
            self.sprecher.ton_probe(TON_GRUPPEN_PROBE[kennung])
        except Exception as fehler:  # noqa: BLE001
            log.exception("Probeton gescheitert (%s): %s", kennung, fehler)

    # -- Bereich Verhalten --------------------------------------------------

    def _gruppe_verhalten(self) -> Gruppe:
        gruppe = Gruppe("Verhalten", "Was CWB von sich aus tut.")
        werte = self._werte_lesen()

        self.ablage_waechter = self._schalter(
            gruppe,
            "ablage_waechter",
            "Zwischenablage überwachen",
            "Schickt kopierten Text automatisch ab, wenn seine erste Zeile die "
            "Code-Markierung ist. Alles andere bleibt unberührt.",
            bool(werte.get("ablage_waechter", True)),
        )
        self.bericht_kopieren = self._schalter(
            gruppe,
            "bericht_kopieren",
            "Bericht nach jedem Auftrag kopieren",
            "Legt Auftrag, Antwort, geänderte Dateien und Tokenverbrauch in die "
            "Zwischenablage.",
            bool(werte.get("bericht_kopieren", True)),
        )
        self.mauszeiger_ansage = self._schalter(
            gruppe,
            "mauszeiger_ansage",
            "Ansage bei Mauszeiger",
            "Sagt jedes Bedien- und Anzeigefeld an, sobald der Mauszeiger kurz "
            "darauf ruht — im ganzen Fenster und auf dieser Seite.",
            bool(werte.get("mauszeiger_ansage", False)),
        )
        self.internet_ohne_rueckfrage = self._schalter(
            gruppe,
            "internet_ohne_rueckfrage",
            "Internetzugriff ohne Rückfrage erlauben",
            "Befehle und Werkzeuge, die ins Internet gehen (etwa curl, wget, "
            "Websuche), laufen ohne Rückfrage. In der Kopfzeile erscheint "
            "dafür ein Zeichen.",
            bool(werte.get("internet_ohne_rueckfrage", False)),
        )
        self.loeschen_ohne_rueckfrage = self._schalter(
            gruppe,
            "loeschen_ohne_rueckfrage",
            "Löschen ohne Rückfrage erlauben",
            "Gilt nur für Löschbefehle innerhalb des Projektordners. "
            "Außerhalb, bei Installationen, fremden Programmen und Git-Push "
            "wird weiter gefragt. In der Kopfzeile erscheint dafür ein Zeichen.",
            bool(werte.get("loeschen_ohne_rueckfrage", False)),
        )
        self.installieren_ohne_rueckfrage = self._schalter(
            gruppe,
            "installieren_ohne_rueckfrage",
            "Installieren ohne Rückfrage erlauben",
            "Pip, npm und ähnliche Installationen laufen ohne Rückfrage, "
            "auch außerhalb des Projekts. Löschen außerhalb des Projekts, "
            "fremde Programme starten und Git-Push wird weiter gefragt. "
            "In der Kopfzeile erscheint dafür ein Zeichen.",
            bool(werte.get("installieren_ohne_rueckfrage", False)),
        )

        self._verbrauchsliste_anlegen(gruppe)
        return gruppe

    def _verbrauchsliste_anlegen(self, gruppe: Gruppe) -> None:
        """Zeigt den Tokenverbrauch der letzten dreissig Tage als einfache
        Liste: ein Tag, eine Zahl. Reine Anzeige, hier wird nichts geschaltet.
        Die Werte stehen in einstellungen.json unter 'tokenverbrauch'."""
        beschriftung = QLabel(
            f"Tokenverbrauch je Tag (letzte {TAGE_AUFBEWAHRT} Tage, ohne Cache)"
        )
        beschriftung.setObjectName("feldname")
        beschriftung.setWordWrap(True)
        gruppe.feld(beschriftung)

        self.verbrauchsliste = QListWidget()
        self.verbrauchsliste.setObjectName("verbrauchsliste")
        self.verbrauchsliste.setAccessibleName("Tokenverbrauch je Tag")
        self.verbrauchsliste.setAccessibleDescription(
            "Mit Pfeiltasten durchgehen; jeder Eintrag nennt Datum und Zahl"
        )
        try:
            tage = tagesverbrauch_lesen()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Tagesverbrauch nicht anzuzeigen: %s", fehler)
            tage = {}

        self._verbrauchstage = [
            (tag, tage[tag]) for tag in sorted(tage, reverse=True)
        ]
        if not self._verbrauchstage:
            eintrag = QListWidgetItem("Noch nichts verbraucht")
            eintrag.setFlags(Qt.ItemIsEnabled)
            self.verbrauchsliste.addItem(eintrag)
        heute = heutiger_tag()
        for tag, anzahl in self._verbrauchstage:
            zusatz = "  (heute)" if tag == heute else ""
            self.verbrauchsliste.addItem(
                QListWidgetItem(f"{_tag_lesbar(tag)}{zusatz} — {zahl_lang(anzahl)}")
            )
        self.verbrauchsliste.currentRowChanged.connect(self._verbrauchstag_ansagen)
        gruppe.feld(self.verbrauchsliste)

    def _verbrauchstag_ansagen(self, zeile: int) -> None:
        if 0 <= zeile < len(self._verbrauchstage):
            tag, anzahl = self._verbrauchstage[zeile]
            self.sprecher.sprich(f"{_tag_lesbar(tag)}: {zahl_lang(anzahl)} Token.")

    def _schalter(self, gruppe: Gruppe, schluessel: str, titel: str,
                  erklaerung: str, an: bool) -> QCheckBox:
        schalter = QCheckBox(titel)
        schalter.setObjectName("verhaltensschalter")
        schalter.setAccessibleName(titel)
        schalter.setAccessibleDescription(erklaerung)
        schalter.setToolTip(erklaerung)
        schalter.setChecked(an)
        schalter.toggled.connect(partial(self._verhalten_geschaltet, schluessel, titel))
        gruppe.feld(schalter)
        return schalter

    def _verhalten_geschaltet(self, schluessel: str, titel: str, an: bool) -> None:
        werte = self._werte_lesen()
        werte[schluessel] = bool(an)
        self._sichern(werte)
        self.sprecher.sprich(f"{titel}: {'an' if an else 'aus'}.")

    # -- Bereich Skills -----------------------------------------------------

    def _gruppe_skills(self) -> Gruppe:
        gruppe = Gruppe(
            "Skills",
            "Nur zur Ansicht. Skills werden im Ordner abgelegt, nicht hier hochgeladen.",
        )

        self._skills = skills_lesen(skill_ordner(), "Nutzerordner")
        if self._projekt_pfad is not None:
            self._skills += skills_lesen(
                self._projekt_pfad / SKILLS_IM_PROJEKT, "Projektordner"
            )

        self.skill_liste = QListWidget()
        self.skill_liste.setObjectName("skillliste")
        self.skill_liste.setAccessibleName("Geladene Skills")
        self.skill_liste.setAccessibleDescription(
            "Mit Pfeiltasten durchgehen; jeder Eintrag nennt Name, Beschreibung "
            "und Herkunft"
        )
        self.skill_liste.setWordWrap(True)

        if not self._skills:
            eintrag = QListWidgetItem("Kein Skill gefunden")
            eintrag.setFlags(Qt.ItemIsEnabled)
            self.skill_liste.addItem(eintrag)
        for skill in self._skills:
            text = f"{skill['name']} — {skill['beschreibung']}  ({skill['herkunft']})"
            eintrag = QListWidgetItem(text)
            eintrag.setToolTip(str(skill["ordner"]))
            self.skill_liste.addItem(eintrag)
        self.skill_liste.currentRowChanged.connect(self._skill_ansagen)
        gruppe.feld(self.skill_liste)

        oeffnen = QPushButton("Skill-Ordner öffnen")
        oeffnen.setObjectName("probe")
        oeffnen.setAccessibleName("Skill-Ordner öffnen")
        oeffnen.setAccessibleDescription(
            "Öffnet im Explorer den Ordner des gewählten Skills, sonst den "
            "Skill-Ordner im Benutzerverzeichnis"
        )
        oeffnen.clicked.connect(self._skill_ordner_oeffnen)
        gruppe.feld(oeffnen)
        return gruppe

    def _skill_ansagen(self, zeile: int) -> None:
        if 0 <= zeile < len(self._skills):
            skill = self._skills[zeile]
            self.sprecher.sprich(
                f"{skill['name']}. {skill['beschreibung']}. Aus dem {skill['herkunft']}."
            )

    def _skill_ordner_oeffnen(self) -> None:
        zeile = self.skill_liste.currentRow()
        if 0 <= zeile < len(self._skills):
            ordner = Path(self._skills[zeile]["ordner"])
        else:
            ordner = skill_ordner()
        if not ordner.is_dir():
            log.warning("Skill-Ordner fehlt: %s", ordner)
            self.sprecher.sprich("Diesen Ordner gibt es nicht.")
            return
        try:
            os.startfile(str(ordner))  # noqa: S606
        except OSError as fehler:
            log.exception("Explorer nicht zu öffnen (%s): %s", ordner, fehler)
            self.sprecher.sprich("Der Ordner ließ sich nicht öffnen.")
            return
        log.info("Skill-Ordner geöffnet: %s", ordner)
        self.sprecher.sprich(f"Ordner {ordner.name} geöffnet.")

    # -- Bereich Pfade ------------------------------------------------------

    def _gruppe_pfade(self) -> Gruppe:
        """Dieselben drei Angaben wie bei der Ersteinrichtung. Jede Änderung
        wirkt beim nächsten Öffnen der Projektwahl; die Skill-Liste liest den
        Ordner bei jedem Öffnen dieser Seite neu."""
        gruppe = Gruppe(
            "Pfade",
            "Wo CWB sucht. Nur der Projektordner muss stimmen; die beiden "
            "anderen dürfen leer bleiben.",
        )

        self.pfad_wurzel = Pfadzeile(
            "Projektordner",
            "Der Ordner, in dem die Projekte nebeneinander liegen. "
            f"Vorschlag: {projektwurzel_vorschlag()}",
            str(projektwurzel() or ""),
            sprecher=self.sprecher,
        )
        self.pfad_wurzel.geaendert.connect(self._wurzel_gemerkt)
        gruppe.feld(self.pfad_wurzel)

        self.pfad_skills = Pfadzeile(
            "Skill-Ordner",
            "Enthält je Skill einen Unterordner mit SKILL.md.",
            str(skill_ordner()),
            sprecher=self.sprecher,
        )
        self.pfad_skills.geaendert.connect(self._skillordner_gemerkt)
        gruppe.feld(self.pfad_skills)

        hub = hub_datenbank()
        self.pfad_hub = Pfadzeile(
            "Memory Hub",
            "Datei memory.db des projektübergreifenden Gedächtnisses. "
            "Leer heißt: es gibt keinen, CWB arbeitet nur mit dem "
            "Gedächtnis im Projekt.",
            str(hub) if hub else "",
            datei=True,
            sprecher=self.sprecher,
        )
        self.pfad_hub.geaendert.connect(self._hub_gemerkt)
        gruppe.feld(self.pfad_hub)
        return gruppe

    def _wurzel_gemerkt(self, wert: str) -> None:
        if not wert:
            self.sprecher.sprich("Der Projektordner darf nicht leer bleiben.")
            return
        projektwurzel_merken(wert)
        if not Path(wert).is_dir():
            log.warning("Eingestellter Projektordner gibt es nicht: %s", wert)
            self.sprecher.sprich("Gemerkt, aber diesen Ordner gibt es nicht.")
            return
        self.sprecher.sprich("Projektordner gemerkt. Er gilt ab dem nächsten Projektwechsel.")

    def _skillordner_gemerkt(self, wert: str) -> None:
        skill_ordner_merken(wert if wert else None)
        self.sprecher.sprich("Skill-Ordner gemerkt.")

    def _hub_gemerkt(self, wert: str) -> None:
        hub_datenbank_merken(wert if wert else None)
        if not wert:
            self.sprecher.sprich("Kein Memory Hub. Das ist in Ordnung.")
            return
        if not Path(wert).is_file():
            log.warning("Eingestellte Memory-Hub-Datei gibt es nicht: %s", wert)
            self.sprecher.sprich("Gemerkt, aber diese Datei gibt es nicht.")
            return
        self.sprecher.sprich("Memory Hub gemerkt.")

    # -- Bereich Projekte -----------------------------------------------------

    def _gruppe_projekte(self) -> Gruppe:
        """Gepflegte Zusatzliste: Projekte, die nicht unter dem Projektordner
        liegen und deshalb dort nicht von selbst auftauchen (core/sicherheit.py,
        `projekte_finden`). Jeder Eintrag hat Ordner und frei waehlbaren
        Anzeigenamen und erscheint ab dem naechsten Projektwechsel (F9)."""
        gruppe = Gruppe(
            "Projekte",
            "Zusätzliche Projekte, die irgendwo liegen dürfen, nicht nur unter "
            "dem Projektordner. Ordner wählen, Anzeigename eintragen, "
            "hinzufügen — sichtbar ab dem nächsten Projektwechsel.",
        )

        self._zusatzprojekte = zusatzprojekte_lesen()

        self.projekt_liste = QListWidget()
        self.projekt_liste.setObjectName("projekteliste")
        self.projekt_liste.setAccessibleName("Zusätzliche Projekte")
        self.projekt_liste.setAccessibleDescription(
            "Mit Pfeiltasten durchgehen; jeder Eintrag nennt Namen und Pfad"
        )
        self._projektliste_fuellen()
        self.projekt_liste.currentRowChanged.connect(self._projekt_ansagen)
        gruppe.feld(self.projekt_liste)

        self.projekt_pfad_feld = QLineEdit()
        self.projekt_pfad_feld.setObjectName("pfadfeld")
        self.projekt_pfad_feld.setAccessibleName("Ordner des neuen Projekts")
        self.projekt_pfad_feld.setAccessibleDescription(
            "Wird über die Schaltfläche Ordner wählen gefüllt"
        )
        self.projekt_pfad_feld.setReadOnly(True)
        gruppe.zeile("Ordner", self.projekt_pfad_feld)

        ordner_waehlen = QPushButton("Ordner wählen …")
        ordner_waehlen.setObjectName("probe")
        ordner_waehlen.setAccessibleName("Ordner wählen")
        ordner_waehlen.setAccessibleDescription(
            "Öffnet die Ordnerauswahl für das neue Projekt"
        )
        ordner_waehlen.clicked.connect(self._projektordner_waehlen)
        gruppe.feld(ordner_waehlen)

        self.projekt_name_feld = QLineEdit()
        self.projekt_name_feld.setObjectName("pfadfeld")
        self.projekt_name_feld.setAccessibleName("Anzeigename")
        self.projekt_name_feld.setAccessibleDescription(
            "Name, unter dem das Projekt in der Projektwahl erscheint"
        )
        gruppe.zeile("Anzeigename", self.projekt_name_feld)

        hinzufuegen = QPushButton("Hinzufügen")
        hinzufuegen.setObjectName("probe")
        hinzufuegen.setAccessibleName("Projekt hinzufügen")
        hinzufuegen.setAccessibleDescription(
            "Nimmt Ordner und Anzeigename in die Projektliste auf"
        )
        hinzufuegen.clicked.connect(self._projekt_hinzufuegen)
        gruppe.feld(hinzufuegen)

        entfernen = QPushButton("Entfernen")
        entfernen.setObjectName("probe")
        entfernen.setAccessibleName("Projekt entfernen")
        entfernen.setAccessibleDescription(
            "Entfernt das in der Liste gewählte Projekt"
        )
        entfernen.clicked.connect(self._projekt_entfernen)
        gruppe.feld(entfernen)
        return gruppe

    def _projektliste_fuellen(self) -> None:
        self.projekt_liste.clear()
        if not self._zusatzprojekte:
            eintrag = QListWidgetItem("Keine Zusatzprojekte eingetragen")
            eintrag.setFlags(Qt.ItemIsEnabled)
            self.projekt_liste.addItem(eintrag)
            return
        for projekt in self._zusatzprojekte:
            self.projekt_liste.addItem(
                QListWidgetItem(f"{projekt['name']} — {projekt['pfad']}")
            )

    def _projekt_ansagen(self, zeile: int) -> None:
        if 0 <= zeile < len(self._zusatzprojekte):
            projekt = self._zusatzprojekte[zeile]
            self.sprecher.sprich(f"{projekt['name']}, {projekt['pfad']}.")

    def _projektordner_waehlen(self) -> None:
        start = self.projekt_pfad_feld.text().strip() or str(Path.home())
        try:
            gewaehlt = QFileDialog.getExistingDirectory(self, "Projektordner wählen", start)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Ordnerauswahl gescheitert: %s", fehler)
            self.sprecher.sprich("Die Auswahl ließ sich nicht öffnen.")
            return
        if not gewaehlt:
            self.sprecher.sprich("Nichts gewählt.")
            return
        self.projekt_pfad_feld.setText(str(Path(gewaehlt)))
        if not self.projekt_name_feld.text().strip():
            self.projekt_name_feld.setText(Path(gewaehlt).name)
        self.sprecher.sprich(f"Ordner {Path(gewaehlt).name} gewählt.")

    def _projekt_hinzufuegen(self) -> None:
        pfad = self.projekt_pfad_feld.text().strip()
        name = self.projekt_name_feld.text().strip()
        if not pfad:
            self.sprecher.sprich("Erst einen Ordner wählen.")
            return
        if not name:
            self.sprecher.sprich("Der Anzeigename darf nicht leer bleiben.")
            return
        if not Path(pfad).is_dir():
            log.warning("Zu übernehmender Projektordner gibt es nicht: %s", pfad)
            self.sprecher.sprich("Diesen Ordner gibt es nicht.")
            return
        try:
            zusatzprojekt_hinzufuegen(name, pfad)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zusatzprojekt nicht zu merken: %s", fehler)
            self.sprecher.sprich("Das Projekt ließ sich nicht speichern.")
            return
        self._zusatzprojekte = zusatzprojekte_lesen()
        self._projektliste_fuellen()
        self.projekt_pfad_feld.clear()
        self.projekt_name_feld.clear()
        log.info("Zusatzprojekt hinzugefügt: %s (%s)", name, pfad)
        self.sprecher.sprich(f"{name} hinzugefügt. Erscheint ab dem nächsten Projektwechsel.")

    def _projekt_entfernen(self) -> None:
        zeile = self.projekt_liste.currentRow()
        if not (0 <= zeile < len(self._zusatzprojekte)):
            self.sprecher.sprich("Kein Projekt gewählt.")
            return
        projekt = self._zusatzprojekte[zeile]
        try:
            zusatzprojekt_entfernen(projekt["name"])
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zusatzprojekt nicht zu entfernen: %s", fehler)
            self.sprecher.sprich("Das Projekt ließ sich nicht entfernen.")
            return
        self._zusatzprojekte = zusatzprojekte_lesen()
        self._projektliste_fuellen()
        log.info("Zusatzprojekt entfernt: %s", projekt["name"])
        self.sprecher.sprich(f"{projekt['name']} entfernt.")

    # -- Bereich Freigaben ----------------------------------------------------

    def _gruppe_freigaben(self) -> Gruppe:
        """Gepflegte Liste von Ordnern ausserhalb des Projekts, in denen
        core/sicherheit.py (Ordnergrenze) ohne Rueckfrage liest und schreibt.
        Skill-Ordner, Claude-Temp-Ordner und cwb-werkzeuge stehen als
        Voreintraege darin (core/pfade.py, `freigaben_vorgaben`) und lassen
        sich wie jeder andere Eintrag entfernen. Die Sperrliste fuer
        Zugangsdaten und die verbotenen Befehle gelten in jeder Freigabe
        unveraendert weiter."""
        gruppe = Gruppe(
            "Freigaben",
            "Ordner außerhalb des Projekts, in denen Claude Code ohne "
            "Rückfrage lesen und schreiben darf. Ordner wählen, hinzufügen — "
            "die Sperrliste für Zugangsdaten und die verbotenen Befehle "
            "gelten dort unverändert weiter.",
        )

        self._freigaben = freigaben_lesen()

        self.freigaben_liste = QListWidget()
        self.freigaben_liste.setObjectName("freigabenliste")
        self.freigaben_liste.setAccessibleName("Freigegebene Ordner")
        self.freigaben_liste.setAccessibleDescription(
            "Mit Pfeiltasten durchgehen; jeder Eintrag nennt Namen und Pfad"
        )
        self._freigabenliste_fuellen()
        self.freigaben_liste.currentRowChanged.connect(self._freigabe_ansagen)
        gruppe.feld(self.freigaben_liste)

        self.freigabe_pfad_feld = QLineEdit()
        self.freigabe_pfad_feld.setObjectName("pfadfeld")
        self.freigabe_pfad_feld.setAccessibleName("Ordner der neuen Freigabe")
        self.freigabe_pfad_feld.setAccessibleDescription(
            "Wird über die Schaltfläche Ordner wählen gefüllt"
        )
        self.freigabe_pfad_feld.setReadOnly(True)
        gruppe.zeile("Ordner", self.freigabe_pfad_feld)

        ordner_waehlen = QPushButton("Ordner wählen …")
        ordner_waehlen.setObjectName("probe")
        ordner_waehlen.setAccessibleName("Ordner der Freigabe wählen")
        ordner_waehlen.setAccessibleDescription(
            "Öffnet die Ordnerauswahl für die neue Freigabe"
        )
        ordner_waehlen.clicked.connect(self._freigabeordner_waehlen)
        gruppe.feld(ordner_waehlen)

        hinzufuegen = QPushButton("Hinzufügen")
        hinzufuegen.setObjectName("probe")
        hinzufuegen.setAccessibleName("Freigabe hinzufügen")
        hinzufuegen.setAccessibleDescription(
            "Nimmt den gewählten Ordner in die Freigabenliste auf"
        )
        hinzufuegen.clicked.connect(self._freigabe_hinzufuegen)
        gruppe.feld(hinzufuegen)

        entfernen = QPushButton("Entfernen")
        entfernen.setObjectName("probe")
        entfernen.setAccessibleName("Freigabe entfernen")
        entfernen.setAccessibleDescription(
            "Entfernt die in der Liste gewählte Freigabe"
        )
        entfernen.clicked.connect(self._freigabe_entfernen)
        gruppe.feld(entfernen)
        return gruppe

    def _freigabenliste_fuellen(self) -> None:
        self.freigaben_liste.clear()
        if not self._freigaben:
            eintrag = QListWidgetItem("Keine Freigaben eingetragen")
            eintrag.setFlags(Qt.ItemIsEnabled)
            self.freigaben_liste.addItem(eintrag)
            return
        for freigabe in self._freigaben:
            self.freigaben_liste.addItem(
                QListWidgetItem(f"{freigabe['name']} — {freigabe['pfad']}")
            )

    def _freigabe_ansagen(self, zeile: int) -> None:
        if 0 <= zeile < len(self._freigaben):
            freigabe = self._freigaben[zeile]
            self.sprecher.sprich(f"{freigabe['name']}, {freigabe['pfad']}.")

    def _freigabeordner_waehlen(self) -> None:
        start = self.freigabe_pfad_feld.text().strip() or str(Path.home())
        try:
            gewaehlt = QFileDialog.getExistingDirectory(self, "Ordner für Freigabe wählen", start)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Ordnerauswahl gescheitert: %s", fehler)
            self.sprecher.sprich("Die Auswahl ließ sich nicht öffnen.")
            return
        if not gewaehlt:
            self.sprecher.sprich("Nichts gewählt.")
            return
        self.freigabe_pfad_feld.setText(str(Path(gewaehlt)))
        self.sprecher.sprich(f"Ordner {Path(gewaehlt).name} gewählt.")

    def _freigabe_hinzufuegen(self) -> None:
        pfad = self.freigabe_pfad_feld.text().strip()
        if not pfad:
            self.sprecher.sprich("Erst einen Ordner wählen.")
            return
        if not Path(pfad).is_dir():
            log.warning("Zu übernehmender Freigabeordner gibt es nicht: %s", pfad)
            self.sprecher.sprich("Diesen Ordner gibt es nicht.")
            return
        try:
            freigabe_hinzufuegen(pfad)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Freigabe nicht zu merken: %s", fehler)
            self.sprecher.sprich("Die Freigabe ließ sich nicht speichern.")
            return
        self._freigaben = freigaben_lesen()
        self._freigabenliste_fuellen()
        self.freigabe_pfad_feld.clear()
        log.info("Freigabe hinzugefügt: %s", pfad)
        self.sprecher.sprich(f"{Path(pfad).name} als Freigabe hinzugefügt.")

    def _freigabe_entfernen(self) -> None:
        zeile = self.freigaben_liste.currentRow()
        if not (0 <= zeile < len(self._freigaben)):
            self.sprecher.sprich("Keine Freigabe gewählt.")
            return
        freigabe = self._freigaben[zeile]
        try:
            freigabe_entfernen(freigabe["pfad"])
        except Exception as fehler:  # noqa: BLE001
            log.exception("Freigabe nicht zu entfernen: %s", fehler)
            self.sprecher.sprich("Die Freigabe ließ sich nicht entfernen.")
            return
        self._freigaben = freigaben_lesen()
        self._freigabenliste_fuellen()
        log.info("Freigabe entfernt: %s", freigabe["pfad"])
        self.sprecher.sprich(f"{freigabe['name']} entfernt.")

    # -- Einstellungen lesen und schreiben ----------------------------------

    def _werte_lesen(self) -> dict:
        try:
            werte = self._lesen()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Einstellungen nicht lesbar: %s", fehler)
            return {}
        return werte if isinstance(werte, dict) else {}

    def _sichern(self, werte: dict) -> None:
        try:
            self._schreiben(werte)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Einstellungen nicht schreibbar: %s", fehler)

    # -- Ansage beim Anspringen ---------------------------------------------

    def _fokusansage_anmelden(self) -> None:
        """Sagt jedes Bedienelement an, sobald der Fokus darauf springt.

        CWB spricht selbst, damit die Seite auch ohne laufenden Screenreader
        bedienbar bleibt. Die Verbindung haengt an der Anwendung und wird
        beim Schliessen wieder geloest."""
        anwendung = QApplication.instance()
        if anwendung is None:
            return
        anwendung.focusChanged.connect(self._fokus_gewechselt)
        self.finished.connect(self._fokusansage_abmelden)

    def _fokusansage_abmelden(self, _ergebnis: int = 0) -> None:
        anwendung = QApplication.instance()
        if anwendung is None:
            return
        try:
            anwendung.focusChanged.disconnect(self._fokus_gewechselt)
        except (RuntimeError, TypeError):
            pass

    def _fokus_gewechselt(self, _alt, neu) -> None:
        if neu is None or not self.isAncestorOf(neu):
            return
        try:
            self.sprecher.sprich(self._ansage_fuer(neu))
        except Exception as fehler:  # noqa: BLE001
            log.exception("Fokusansage gescheitert: %s", fehler)

    @staticmethod
    def _ansage_fuer(widget: QWidget) -> str:
        """Setzt zusammen, was unter dem Fokus liegt: Name, Zustand,
        Erklaerung. Ohne Zustand wuesste niemand, ob ein Schalter an ist."""
        teile = [str(widget.accessibleName()) or widget.__class__.__name__]
        if isinstance(widget, QRadioButton):
            teile.append("gewählt" if widget.isChecked() else "nicht gewählt")
        elif isinstance(widget, QCheckBox):
            teile.append("an" if widget.isChecked() else "aus")
        elif isinstance(widget, QComboBox):
            teile.append(widget.currentText())
        elif isinstance(widget, QSpinBox):
            teile.append(str(widget.value()))
        elif isinstance(widget, Reiterleiste):
            teile.append(widget.text(widget.stelle()))
        elif isinstance(widget, QListWidget):
            eintrag = widget.currentItem()
            teile.append(eintrag.text() if eintrag else "leer")
        elif isinstance(widget, QLineEdit):
            teile.append(widget.text() or "leer")
        elif isinstance(widget, QPushButton):
            teile.append("Schaltfläche")
        erklaerung = str(widget.accessibleDescription())
        if erklaerung:
            teile.append(erklaerung)
        return ". ".join(teil for teil in teile if teil) + "."
