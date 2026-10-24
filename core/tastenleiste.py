"""
CWB - Code Workbench
Kachelreihe unter dem Fortschrittsbalken.

Enthaelt nur die staendig gebrauchten Befehle. Jede Kachel ist eine
Schaltflaeche mit eigener Pastellfarbe, einem Symbol und kleinem Text
darunter. Flach und kompakt, die Reihe teilt die Fensterbreite unter sich
auf und hat keine festen Pixelgroessen im Python.

Die Reihe gibt nach, statt das Fenster breit zu halten: die Kacheln
schrumpfen mit, die Aufschrift bricht um (auch nach einem Bindestrich), und
reicht die Breite fuer eine Zeile nicht mehr, rueckt die Reihe in mehrere
Zeilen. Eine Kachel wird nie schmaler als ihr laengstes Wort und nie niedriger
als ihr Inhalt; Aufschriften werden nie mit Auslassungspunkten gekuerzt.
Aendern sich Schrift oder Stilblatt (Skalierung, erstes Anzeigen), rechnet die
Reihe Spalten und Hoehen von selbst neu (`Kachelreihe.neu_berechnen`).

Gestaltung kommt vollstaendig aus stil.qss. Hier steht keine Farbe und
keine Groesse, nur die Nummer der Pastellfarbe je Kachel.

Alle selteneren Befehle bleiben ueber ihre Tastenkuerzel erreichbar,
die Hilfe (F1) liest sie vor.
"""

import logging
import re
from functools import partial
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from .pfade import log_einrichten
except ImportError:
    from pfade import log_einrichten

CWB_WURZEL = Path(__file__).resolve().parent.parent
LOG_DATEI = CWB_WURZEL / "cwb_fehler.log"

log_einrichten()
log = logging.getLogger("cwb.tastenleiste")

# Die Ansage bei Mauszeiger liegt nicht mehr hier: sie gilt fuer das ganze
# Fenster und steht in core/zeigeransage.py. Jede Kachel traegt dafuer nur
# ihren Vorlesetext im barrierefreien Namen.

# Kacheln, deren Sichtbarkeit sich in den Einstellungen (Reiter "Kacheln")
# einzeln abschalten laesst - erkannt an der urspruenglichen Beschriftung,
# die als Kennung erhalten bleibt (core/fenster.py, `_kachel_eintraege`).
# Not-Aus steht bewusst nicht darin: er bleibt immer sichtbar. "Trotzdem hier
# ausfuehren" ebenfalls nicht: die blendet sich von selbst ein und aus,
# je nachdem ob ein Auftrag vorgemerkt ist (core/fenster.py, `_vormerkung_zeigen`).
KACHELN_SCHALTBAR = [
    "Lesen und Schreiben",
    "Brücke",
    "Leitstand",
    "Ansage abbrechen",
    "Letzte Antwort",
    "Bericht-Text kopieren",
    "Bericht-Datei kopieren",
    "Berichtordner öffnen",
    "Warteschlange leeren",
    "Projekt wechseln",
    "Einstellungen",
]

# Die wenigen grossen Kacheln stehen allein in der ersten Zeile und brechen
# nie um; "Neu starten" ist deshalb nicht abschaltbar. Alles andere ist klein
# und rueckt in die Zeilen darunter. Erkannt an der urspruenglichen Beschriftung.
KACHELN_GROSS = ["Orchestrator", "Neu starten", "Not-Aus"]

# Vorbelegung, solange einstellungen.json noch keinen Wert unter
# "sichtbare_kacheln" hat. "Projekt wechseln" fehlt mit Absicht: CWB wechselt
# von selbst, F9 und die einschaltbare Kachel bleiben. Ebenso Bruecke und
# Leitstand: beide laufen immer mit und brauchen keine Kachel.
KACHELN_VOREINSTELLUNG = [
    "Lesen und Schreiben",
    "Bericht-Text kopieren",
    "Einstellungen",
]

# Stand der Kachelvorgabe. Steht in einstellungen.json ein kleinerer Wert,
# stellt CWB die Auswahl einmalig auf KACHELN_VOREINSTELLUNG um und merkt
# sich den neuen Stand; danach gilt nur noch die Wahl des Nutzers.
KACHELN_STAND = 2


class Kachel(QPushButton):
    """Eine flache Kachel: Symbol oben, kleiner Text darunter.

    Die beiden Beschriftungen sind QLabel innerhalb der Schaltflaeche, damit
    Symbol und Text in stil.qss verschieden gross sein koennen. Sie nehmen
    keine Mausklicks an, jeder Klick landet auf der Schaltflaeche selbst.
    """

    def __init__(self, symbol: str, beschriftung: str, taste: str, farbe: str,
                 gross: bool = False):
        super().__init__()
        self.setObjectName("kachel")
        self.setProperty("farbe", farbe)
        self.setProperty("groesse", "gross" if gross else "klein")
        self.gross = gross
        self.setProperty("ansage", beschriftung)
        self.setAccessibleName(beschriftung)
        self.setAccessibleDescription(f"Tastenkürzel {taste}" if taste else "")
        self.setToolTip(f"{beschriftung}  ({taste})" if taste else beschriftung)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Grosse Kacheln: Symbol links, Text daneben - so bleiben sie niedrig.
        # Kleine: Symbol oben, Text darunter.
        aufbau = QHBoxLayout(self) if gross else QVBoxLayout(self)
        aufbau.setContentsMargins(0, 0, 0, 0)
        aufbau.setSpacing(0)

        self.symbol_feld = QLabel(symbol)
        self.symbol_feld.setObjectName("kachelsymbol")
        self.text_feld = QLabel(beschriftung)
        self.text_feld.setObjectName("kacheltext")
        self.text_feld.setWordWrap(True)
        # Die Aufschrift nimmt die Breite, die uebrig bleibt, und bricht um.
        # Die Mindestbreite (laengstes Wort) sichert die Kachel selbst.
        self.text_feld.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.voller_text = beschriftung
        # Eigener Merker statt isHidden(): solange das Fenster noch nicht
        # angezeigt wurde, gilt in Qt jede Kachel als verborgen. Danach liesse
        # sich nicht unterscheiden, welche absichtlich ausgeblendet ist.
        self.verborgen = False

        for feld in (self.symbol_feld, self.text_feld):
            feld.setAlignment(Qt.AlignCenter)
            feld.setAttribute(Qt.WA_TransparentForMouseEvents)
            feld.setFocusPolicy(Qt.NoFocus)
        aufbau.addWidget(self.symbol_feld)
        aufbau.addWidget(self.text_feld, 1 if gross else 0)

    def _woerter(self) -> list[str]:
        """Die Stuecke, an denen die Aufschrift umbrechen darf: Leerstellen
        und - wie in Qt - die Stelle hinter einem Bindestrich."""
        return [w for w in re.split(r"(?<=-)|\s+", self.voller_text) if w]

    def _laengstes_wort(self) -> int:
        mass = QFontMetrics(self.text_feld.font())
        return max((mass.horizontalAdvance(wort) for wort in self._woerter()),
                   default=0)

    def _symbol_breite(self) -> int:
        """Breite des Symbols neben dem Text (nur grosse Kacheln, bei den
        kleinen steht es darueber)."""
        if not self.gross:
            return 0
        mass = QFontMetrics(self.symbol_feld.font())
        return mass.horizontalAdvance(self.symbol_feld.text()) + mass.averageCharWidth() * 2

    def sizeHint(self) -> QSize:
        """Wunschbreite: mindestens so breit, dass das laengste Wort der
        Aufschrift ganz hineinpasst - darunter muesste es abgeschnitten werden.
        Weil das Textfeld selbst keine Breite fordert, muss die Kachel sie
        nennen; daran entscheidet die Reihe, wie viele Kacheln nebeneinander
        passen. Die Hoehe kommt aus `heightForWidth`."""
        masse = super().sizeHint()
        if not self._woerter():
            return masse
        mass = QFontMetrics(self.text_feld.font())
        breite = self._laengstes_wort() + mass.averageCharWidth() * 2 + self._symbol_breite()
        return QSize(max(masse.width(), breite), masse.height())

    def minimumSizeHint(self) -> QSize:
        """Schmalste zumutbare Kachel: ihr laengstes Wort mit etwas Luft, nie
        schmaler als das Symbol. Ohne diese Grenze wuerde ein Wort abgeschnitten
        oder muesste gekuerzt werden."""
        mass = QFontMetrics(self.symbol_feld.font())
        symbol = mass.horizontalAdvance(self.symbol_feld.text()) + mass.averageCharWidth() * 2
        text = QFontMetrics(self.text_feld.font())
        wort = self._laengstes_wort() + text.averageCharWidth() * 2 + self._symbol_breite()
        return QSize(max(symbol, wort), super().minimumSizeHint().height())

    def changeEvent(self, ereignis) -> None:
        super().changeEvent(ereignis)
        # Neue Schrift oder neues Stilblatt aendern Wunschbreite und -hoehe;
        # die Reihe darueber muss das erfahren, sonst rechnet sie mit alten Massen.
        if ereignis.type() in (QEvent.StyleChange, QEvent.FontChange):
            self.updateGeometry()

    def beschriften(self, text: str, ansage: str = "", symbol: str = "") -> None:
        """Aendert den kleinen Text und, wenn angegeben, Vorlesetext und
        Symbol. Der Kurzhinweis geht mit, damit Auge und Ohr dasselbe sagen."""
        self.voller_text = text
        self.text_feld.setText(text)
        self.updateGeometry()
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
    """Reihe der staendig gebrauchten Befehle, die umbrechen darf.

    `eintraege` ist eine Liste aus (symbol, beschriftung, taste, farbe, ziel).
    Die Kacheln teilen sich die verfuegbare Breite gleichmaessig. Wird das
    Fenster so schmal, dass sie nebeneinander nicht mehr lesbar sind, ruecken
    sie in eine zweite und dritte Zeile - die Reihe zwingt das Fenster nie,
    breit zu bleiben.
    """

    def __init__(self, eintraege, gross=KACHELN_GROSS):
        super().__init__()
        self.setObjectName("kachelreihe")
        self.setAccessibleName("Befehlskacheln")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.raster = QGridLayout(self)
        # Zahl der Spalten, die gerade gilt. Erst ein Wechsel raeumt neu ein,
        # sonst wuerde jedes Groessenereignis das Raster umbauen.
        self._spalten = 0
        # Verhindert, dass viele Stil-/Schriftereignisse hintereinander viele
        # Neuberechnungen anstossen: es wird genau eine eingeplant.
        self._neu_geplant = False

        self.kacheln: list[Kachel] = []
        for symbol, beschriftung, taste, farbe, ziel in eintraege:
            if not callable(ziel):
                log.error("Kachel ohne aufrufbares Ziel: %s (%r)", beschriftung, ziel)
                continue
            kachel = Kachel(symbol, beschriftung, taste, farbe,
                            gross=beschriftung in gross)
            # Zwei getrennte Verbindungen: erst die Logzeile, dann das Ziel
            # selbst - unmittelbar, ohne Zwischenschritt. Damit steht im Log
            # der echte Methodenname, und keine Huelle kann eine Ausnahme des
            # Ziels verschlucken.
            kachel.clicked.connect(partial(self._kachel_merken, beschriftung, ziel))
            kachel.clicked.connect(ziel)
            self.kacheln.append(kachel)
            log.info(
                "Kachel angelegt: %s (Taste %s) → %s",
                beschriftung, taste or "keine", getattr(ziel, "__name__", ziel),
            )
        self._einraeumen(len(self.kacheln) or 1)
        log.info(
            "Kacheln insgesamt angelegt: %d von %d", len(self.kacheln), len(eintraege)
        )

    # -- Umbruch ------------------------------------------------------------

    def _sichtbare(self) -> list[Kachel]:
        """Nur die Kacheln, die gerade gezeigt werden. Ausgeblendete zaehlen
        beim Umbruch nicht mit und hinterlassen keine Luecke im Raster."""
        return [kachel for kachel in self.kacheln if not kachel.verborgen]

    def _grosse(self) -> list[Kachel]:
        return [kachel for kachel in self._sichtbare() if kachel.gross]

    def _kleine(self) -> list[Kachel]:
        return [kachel for kachel in self._sichtbare() if not kachel.gross]

    def _wunschbreite(self) -> int:
        """Breite, die eine kleine Kachel gern haette - gemessen an der
        breitesten. Sie kommt aus Schrift und Stilblatt, nicht aus einer festen
        Zahl. Die grossen Kacheln zaehlen nicht mit: sie haben ihre eigene Zeile."""
        return max((kachel.sizeHint().width() for kachel in self._kleine()),
                   default=1)

    def _spalten_berechnen(self) -> int:
        """Wie viele Kacheln nebeneinander passen, ohne dass eine unter ihre
        Wunschbreite gedrueckt wird. Mindestens eine, hoechstens alle."""
        sichtbare = self._kleine()
        if not sichtbare:
            return 1
        rand = self.raster.contentsMargins()
        abstand = max(self.raster.horizontalSpacing(), 0)
        breite = self.width() - rand.left() - rand.right()
        wunsch = self._wunschbreite() + abstand
        if wunsch <= 0 or breite <= 0:
            return len(sichtbare)
        passen = int((breite + abstand) // wunsch)
        return max(1, min(len(sichtbare), passen))

    def _einraeumen(self, spalten: int) -> None:
        """Raeumt die sichtbaren Kacheln ein: die grossen allein in Zeile 0
        (sie teilen die Breite und brechen nie um), die kleinen in `spalten`
        Spalten darunter. Alle Spalten dehnen sich gleich."""
        sichtbare = self._sichtbare()
        if spalten == self._spalten or not sichtbare:
            return
        try:
            grosse, kleine = self._grosse(), self._kleine()
            for spalte in range(self.raster.columnCount()):
                self.raster.setColumnStretch(spalte, 0)
            for kachel in self.kacheln:
                self.raster.removeWidget(kachel)
            # Gemeinsames Raster: jede grosse Kachel ueberspannt gleich viele
            # Spalten, damit Zeile 0 die ganze Breite fuellt.
            gesamt = spalten * len(grosse) if grosse else spalten
            for nummer, kachel in enumerate(grosse):
                self.raster.addWidget(kachel, 0, spalten * nummer, 1, spalten)
            zeile0 = 1 if grosse else 0
            breite = len(grosse) if grosse else 1
            for nummer, kachel in enumerate(kleine):
                self.raster.addWidget(kachel, zeile0 + nummer // spalten,
                                      (nummer % spalten) * breite, 1, breite)
            for spalte in range(gesamt):
                self.raster.setColumnStretch(spalte, 1)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kacheln nicht neu eingeräumt: %s", fehler)
            return
        self._spalten = spalten
        log.info("Kachelreihe umgebrochen: %d Spalten, %d Zeilen", spalten,
                 (1 if grosse else 0) + (len(kleine) + spalten - 1) // spalten)

    def _hoehe_sichern(self) -> None:
        """Macht die Hoehe, die alle Zeilen brauchen, zur Mindesthoehe der
        Reihe. Ohne das drueckt das Layout darueber die Reihe unter ihren
        Inhalt (es rechnet nicht mit der Hoehe fuer die aktuelle Breite), und
        die Kacheln ragen uebereinander. Die Zahl kommt aus dem Raster, nicht
        aus einer festen Groesse."""
        try:
            rand = self.contentsMargins()
            hoehe = (self.raster.totalHeightForWidth(self.width())
                     + rand.top() + rand.bottom())
            if hoehe != self.minimumHeight():
                self.setMinimumHeight(hoehe)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Mindesthöhe der Kachelreihe nicht gesetzt: %s", fehler)

    def resizeEvent(self, ereignis) -> None:
        super().resizeEvent(ereignis)
        self._einraeumen(self._spalten_berechnen())
        self._hoehe_sichern()

    def neu_berechnen(self) -> None:
        """Rechnet Spalten und Hoehen vollstaendig neu: Wunschbreiten aus der
        aktuellen Schrift, Umbruch fuer die aktuelle Breite, Zeilenhoehen aus
        dem Inhalt. Noetig nach dem ersten Anzeigen, nach einem neuen Stilblatt
        (Skalierung) und nach dem Wiederherstellen der gemerkten Geometrie -
        dort aendert sich die Schrift, ohne dass die Reihe ihre Breite aendert
        und darum ein Groessenereignis bekaeme."""
        self._neu_geplant = False
        try:
            for kachel in self.kacheln:
                kachel.updateGeometry()
            self._spalten = 0
            self._einraeumen(self._spalten_berechnen())
            self.raster.invalidate()
            self.raster.activate()
            self._hoehe_sichern()
            self.updateGeometry()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kachelreihe nicht neu berechnet: %s", fehler)

    def event(self, ereignis) -> bool:
        ergebnis = super().event(ereignis)
        if (ereignis.type() in (QEvent.StyleChange, QEvent.FontChange,
                                QEvent.Polish, QEvent.Show)
                and not self._neu_geplant):
            # Erst nach dem Ereignis, wenn alle Kacheln ihre neue Schrift haben.
            self._neu_geplant = True
            QTimer.singleShot(0, self.neu_berechnen)
        return ergebnis

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

    def kachel_zeigen(self, ansage: str, sichtbar: bool) -> None:
        """Blendet eine Kachel ein oder aus. Ausgeblendet ist sie weder zu
        sehen noch mit der Tabulatortaste erreichbar; die uebrigen Kacheln
        ruecken auf, weil das Raster danach neu eingeraeumt wird."""
        kachel = self._kachel_suchen(ansage)
        if kachel is None or kachel.verborgen == (not sichtbar):
            return
        try:
            kachel.verborgen = not sichtbar
            kachel.setVisible(sichtbar)
            # Erzwingt das Neueinraeumen: sonst haelte die gemerkte
            # Spaltenzahl das Raster in seiner alten Aufteilung fest.
            self._spalten = 0
            self._einraeumen(self._spalten_berechnen())
            self._hoehe_sichern()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kachel nicht umgeschaltet (%s): %s", ansage, fehler)
            return
        log.info("Kachel %s: %s", "eingeblendet" if sichtbar else "ausgeblendet",
                 ansage)

    def kachel_faerben(self, ansage: str, farbe: str) -> None:
        """Wechselt die Farbe einer Kachel, etwa wenn sie einen anderen
        Zustand anzeigt."""
        kachel = self._kachel_suchen(ansage)
        if kachel is not None:
            kachel.einfaerben(farbe)
