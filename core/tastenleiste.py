"""
CWB - Code Workbench
Kachelreihe unter dem Fortschrittsbalken.

Enthaelt nur die staendig gebrauchten Befehle. Jede Kachel ist eine
Schaltflaeche mit eigener Pastellfarbe, einem Symbol und kleinem Text
darunter. Flach und kompakt, die Reihe teilt die Fensterbreite unter sich
auf und hat keine festen Pixelgroessen im Python.

Die Reihe gibt nach, statt das Fenster breit zu halten: die Kacheln
schrumpfen mit, die Aufschrift bricht um und wird zuletzt gekuerzt, und
reicht die Breite fuer eine Zeile nicht mehr, rueckt die Reihe in mehrere
Zeilen. Als letzte Grenze bleibt das Symbol - kleiner wird eine Kachel nicht.
Der Vorlesetext bleibt dabei immer vollstaendig.

Gestaltung kommt vollstaendig aus stil.qss. Hier steht keine Farbe und
keine Groesse, nur die Nummer der Pastellfarbe je Kachel.

Alle selteneren Befehle bleiben ueber ihre Tastenkuerzel erreichbar,
die Hilfe (F1) liest sie vor.
"""

import logging
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QGridLayout,
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
# Not-Aus und die Zugriffsplakette (Nur lesen / Lesen und Schreiben) stehen
# bewusst nicht darin: beide bleiben immer sichtbar. "Trotzdem hier
# ausfuehren" ebenfalls nicht: die blendet sich von selbst ein und aus,
# je nachdem ob ein Auftrag vorgemerkt ist (core/fenster.py, `_vormerkung_zeigen`).
KACHELN_SCHALTBAR = [
    "Ansage abbrechen",
    "Letzte Antwort",
    "Bericht-Text kopieren",
    "Bericht-Datei kopieren",
    "Berichtordner öffnen",
    "Warteschlange leeren",
    "Neu starten",
    "Projekt wechseln",
    "Einstellungen",
]

# Vorbelegung, solange einstellungen.json noch keinen Wert unter
# "sichtbare_kacheln" hat.
KACHELN_VOREINSTELLUNG = [
    "Neu starten",
    "Projekt wechseln",
    "Einstellungen",
    "Bericht-Text kopieren",
]


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
        # Die Aufschrift darf die Kachel nicht breit halten: sie nimmt die
        # Breite, die uebrig bleibt, und wird notfalls gekuerzt.
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
            aufbau.addWidget(feld)

    def sizeHint(self) -> QSize:
        """Wunschbreite: so breit, dass die Aufschrift auf zwei Zeilen passt,
        ohne ein Wort zu trennen. Weil das Textfeld selbst keine Breite
        fordert, muss die Kachel sie nennen - daran entscheidet die Reihe, wie
        viele Kacheln nebeneinander passen."""
        masse = super().sizeHint()
        woerter = self.voller_text.split()
        if not woerter:
            return masse
        mass = QFontMetrics(self.text_feld.font())
        laengstes = max(mass.horizontalAdvance(wort) for wort in woerter)
        haelfte = mass.horizontalAdvance(self.voller_text) // 2
        # Untergrenze sechs Zeichen: darunter waere jede Aufschrift nur noch
        # ein Stummel. Ein einzelnes langes Wort treibt die Breite nicht hoch -
        # es wird lieber gekuerzt, als die ganze Reihe breit zu halten.
        breite = min(laengstes, max(haelfte, mass.averageCharWidth() * 6))
        return QSize(max(masse.width(), breite), masse.height())

    def minimumSizeHint(self) -> QSize:
        """Schmalste zumutbare Kachel: ihr Symbol mit etwas Luft. Ohne diese
        Grenze hielte die Aufschrift die ganze Reihe breiter als das Fenster."""
        mass = QFontMetrics(self.symbol_feld.font())
        breite = mass.horizontalAdvance(self.symbol_feld.text()) + mass.averageCharWidth() * 2
        return QSize(breite, super().minimumSizeHint().height())

    def resizeEvent(self, ereignis) -> None:
        super().resizeEvent(ereignis)
        self._aufschrift_anpassen()

    def _aufschrift_anpassen(self) -> None:
        """Kuerzt die Aufschrift mit Auslassungspunkten, sobald selbst das
        laengste Wort nicht mehr in die Kachel passt. Solange es passt, steht
        sie vollstaendig da und bricht um. Der Vorlesetext bleibt ungekuerzt."""
        breite = self.text_feld.width()
        woerter = self.voller_text.split()
        if breite <= 0 or not woerter:
            return
        try:
            mass = QFontMetrics(self.text_feld.font())
            laengstes = max(woerter, key=mass.horizontalAdvance)
            if mass.horizontalAdvance(laengstes) <= breite:
                self.text_feld.setText(self.voller_text)
            else:
                self.text_feld.setText(
                    mass.elidedText(self.voller_text, Qt.ElideRight, breite)
                )
        except Exception as fehler:  # noqa: BLE001
            log.exception("Aufschrift nicht angepasst (%s): %s", self.voller_text, fehler)

    def beschriften(self, text: str, ansage: str = "", symbol: str = "") -> None:
        """Aendert den kleinen Text und, wenn angegeben, Vorlesetext und
        Symbol. Der Kurzhinweis geht mit, damit Auge und Ohr dasselbe sagen."""
        self.voller_text = text
        self.text_feld.setText(text)
        self._aufschrift_anpassen()
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

    def __init__(self, eintraege):
        super().__init__()
        self.setObjectName("kachelreihe")
        self.setAccessibleName("Befehlskacheln")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.raster = QGridLayout(self)
        # Zahl der Spalten, die gerade gilt. Erst ein Wechsel raeumt neu ein,
        # sonst wuerde jedes Groessenereignis das Raster umbauen.
        self._spalten = 0

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

    def _wunschbreite(self) -> int:
        """Breite, die eine Kachel gern haette - gemessen an der breitesten.
        Sie kommt aus Schrift und Stilblatt, nicht aus einer festen Zahl."""
        return max((kachel.sizeHint().width() for kachel in self._sichtbare()),
                   default=1)

    def _spalten_berechnen(self) -> int:
        """Wie viele Kacheln nebeneinander passen, ohne dass eine unter ihre
        Wunschbreite gedrueckt wird. Mindestens eine, hoechstens alle."""
        sichtbare = self._sichtbare()
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
        """Raeumt die sichtbaren Kacheln in so viele Spalten ein. Alle Spalten
        dehnen sich gleich, damit die Kacheln gleich breit bleiben."""
        sichtbare = self._sichtbare()
        if spalten == self._spalten or not sichtbare:
            return
        try:
            for spalte in range(self.raster.columnCount()):
                self.raster.setColumnStretch(spalte, 0)
            for kachel in self.kacheln:
                self.raster.removeWidget(kachel)
            for nummer, kachel in enumerate(sichtbare):
                self.raster.addWidget(kachel, nummer // spalten, nummer % spalten)
            for spalte in range(spalten):
                self.raster.setColumnStretch(spalte, 1)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kacheln nicht neu eingeräumt: %s", fehler)
            return
        self._spalten = spalten
        log.info("Kachelreihe umgebrochen: %d Spalten, %d Zeilen", spalten,
                 (len(sichtbare) + spalten - 1) // spalten)

    def resizeEvent(self, ereignis) -> None:
        super().resizeEvent(ereignis)
        self._einraeumen(self._spalten_berechnen())

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
