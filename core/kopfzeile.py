"""
CWB - Code Workbench
Kopfzeile des Ausgabefelds.

Eine Reihe ueber dem Ausgabefeld traegt alles, was zum Stand der Arbeit
gehoert, in dieser Reihenfolge (Block 81): das Zeichen fuer aktive
Rueckfrage-Ausnahmen (Internet, Loeschen im Projekt, Installieren), die Zahl
der aktiven Freigaben (Einstellungen, Reiter Freigaben), der Bruecken-Status
(dauerhaft "Brücke: an"/"Brücke: aus", Einstellungen Reiter Verhalten), der
Leitstand-Status (nur sichtbar, solange er fuer dieses Projekt an ist), die
Modellanzeige, die Such-Effizienz, der Kontingent-Zustand (Block 36, zwei
Felder Woche/Sitzung mit echten Prozentzahlen, dauerhaft sichtbar wie die
Modellanzeige), die Warteanzeige mit der Zahl der vorgemerkten Auftraege
(leer, solange keiner wartet), die Eingangsanzeige mit der Zahl der
Auftragsdateien im Eingangsordner, die auf ein anderes Projekt warten
(Block 63, ebenfalls leer im Regelfall), und zuletzt die drei Tokenzaehler.
Die Zaehler stehen unmittelbar nebeneinander in der Reihenfolge "Auftrag",
"Sitzung", "Heute" - gleiche Breite, gleiche Gestalt, ohne Zwischenraum. Die
Schaltflaeche zum Kopieren steht nicht in dieser Reihe (siehe unten). Ein
eigenes Feld fuer die Statusmeldung gibt es nicht; die Meldung wird
gesprochen und steht als Beschreibung an der Kopfzeile selbst.

Jedes Feld zeigt immer sein eigenes Substantiv zusammen mit seinem Wert als
ein zusammenhaengendes Textstueck ("Freigaben 6", "Brücke: an", "Woche
80 % · zurück Do 11:00") - nie eine nackte Zahl und nie ein Wort ohne seinen
Zustand. Eine
Zahl kann dadurch nie faelschlich einem benachbarten Feld zugeschlagen
werden, auch wenn die Reihe eng steht.

Das geltende Schreibrecht ("Nur lesen" / "Lesen und Schreiben") steht nicht
hier, sondern einzig an der Kachel ZUGRIFF_KENNUNG (F10, core/fenster.py) -
eine zweite Anzeige derselben Information waere hier nur Redundanz. Die
Modellwahl (das Auswaehlen) steht nicht hier, sondern in den Einstellungen
(F12, Reiter Verhalten, core/einstellungen.py). Welches Modell dabei
tatsaechlich verbunden ist, zeigt die Modellanzeige hier dauerhaft an
(Block 70, Teil B, `modell_zeigen`) - anders als die uebrigen Felder in
dieser Zeile ist sie nie leer.

Taetigkeit und bearbeitete Datei stehen nicht mehr hier, sondern gross und
fett direkt im Aktivitaetsbalken oben (core/fenster.py, Aktivitaetsbalken).

Alle Felder werden an gleichbleibenden Beispieltexten gemessen und halten
dieses Mass, solange das Fenster breit genug ist: kein Inhalt kann die Groesse
aendern, darum rutscht das Ausgabefeld darunter nie auf und ab und in der Reihe
verschiebt sich nichts. Die Zeile bleibt einzeilig; die Skalierung des ganzen
Stilblatts (core/grundlagen.py, `stil_anwenden`) haelt Schrift und Abstaende
schmaler Fenster klein genug, dass nichts umbricht.

Reicht die Fensterbreite fuer eine einzige Zeile nicht mehr, bricht die Reihe
um (Block 81, Klasse `ZeilenFluss`): Felder ruecken in eine zweite oder
dritte Zeile, statt dass eines gekuerzt oder sein Wort weggelassen wird. Vor
Block 81 schrumpfte stattdessen jedes Feld auf eine wortlose Kurzform
("Brücke" statt "Brücke an", eine nackte Zahl statt "Freigaben 6") - dabei
liess sich eine Zahl nicht mehr sicher ihrem Feld zuordnen, sobald sie direkt
neben einem fremden Feld stand ("6 Brücke" las sich wie eine Zahl zur
Brücke). Jedes Feld zeigt seither immer seinen vollstaendigen Text mit
eigenem Substantiv; nur der Umbruch loest Platzmangel. So erzwingt die
Kopfzeile trotzdem nie eine Mindestbreite - anders als vor Block 49, als die
Beispieltexte zugleich die Untergrenze jedes Feldes waren (Qt-Labels ohne
Zeilenumbruch melden ihre volle Textbreite auch als `minimumSizeHint`,
`setMinimumWidth(0)` aendert daran nichts).

Die Schaltflaeche zum Kopieren steht nicht mehr hier, sondern in einer eigenen
schmalen Zeile direkt ueber dem Ausgabefeld (core/fenster.py) - dort gehoert
sie hin, nicht in die Kopfzeile mit den Zaehlern.

Aussehen kommt vollstaendig aus stil.qss. Im Python steht keine Gestaltung.
"""

import logging

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QWidget,
)

try:
    from .grundlagen import LOG_DATEI  # noqa: F401  (richtet das Log ein)
except ImportError:
    from grundlagen import LOG_DATEI  # noqa: F401

log = logging.getLogger("cwb.kopfzeile")

# Taetigkeit je Zustand, falls die Sitzung keine eigene mitschickt. Steht im
# Aktivitaetsbalken (core/fenster.py), nie ein Dateiname oder Pfad.
ZUSTAND_TAETIGKEIT = {
    "bereit": "wartet",
    "schaerft": "denkt",
    "denkt": "denkt",
    "liest": "liest",
    "sucht": "sucht",
    "schreibt": "schreibt",
    "fuehrt_aus": "führt aus",
    "netz": "liest",
    "wartet": "wartet",
    "fertig": "fertig",
    "abgebrochen": "abgebrochen",
    "fehler": "Fehler",
}

# Aufschrift des Schreibrechts. Nennt dauerhaft den geltenden Zustand, nie
# eine Aufforderung. Angezeigt wird sie einzig an der Kachel ZUGRIFF_KENNUNG
# (F10, core/fenster.py); die beiden Woerter stehen hier, weil fenster.py sie
# von hier bezieht.
ZUGRIFF_NUR_LESEN = "Nur lesen"
ZUGRIFF_SCHREIBEN = "Lesen und Schreiben"

# Warteanzeige: wie viele Auftraege noch hinter dem laufenden stehen. Wartet
# keiner, bleibt das Feld leer und verborgen - eine Null waere nur Laerm. Die
# Breite wird an einer zweistelligen Zahl gemessen und aendert sich nie.
WARTE_BEISPIELE = ("Warten 99",)

# Zeichen fuer die drei Rueckfrage-Ausnahmen (Einstellungen, Reiter
# Verhalten). Bleibt leer, solange keine der drei an ist - die Breite wird
# am laengsten moeglichen Text gemessen, damit nichts in der Reihe springt.
# Block 81: kein Kurzmodus mehr, der volle Wortlaut steht bei wenig Platz
# in einer eigenen Zeile (siehe ZeilenFluss), statt auf das blosse Zeichen
# zu schrumpfen.
SICHERHEITSHINWEIS_BEISPIELE = ("⚠ Internet · Löschen · Installieren",)

# Zahl der aktiven Freigaben (Einstellungen, Reiter Freigaben). Die Breite
# wird an einer zweistelligen Zahl gemessen und aendert sich nie.
FREIGABEN_BEISPIELE = ("Freigaben 99",)

# Statushinweis fuer den Schalter "Bruecke" (Einstellungen, Reiter Verhalten,
# Umschalt+F8, core/fenster.py, Vorhaben "Bruecke" Stufe B3). Block 81:
# dauerhaft sichtbar wie die Modellanzeige, nie nur "Brücke" ohne Zustand -
# das Wort "an"/"aus" steht als eigener zusammenhaengender Text immer dabei,
# damit keine Nachbarzahl faelschlich dazugelesen werden kann.
BRUECKE_BEISPIELE = ("Brücke: an", "Brücke: aus")

# Statushinweis fuer den Schalter "Leitstand" (Einstellungen, Reiter
# Leitstand, Umschalt+F9, core/leitstand.py, Block 72). Bleibt leer, solange
# Leitstand fuer dieses Projekt aus bzw. nicht eingerichtet ist - ab Werk der
# Fall. Anders als Bruecke nicht dauerhaft sichtbar: ein Projekt ohne
# Leitstand soll hier dauerhaft nichts anzeigen muessen.
LEITSTAND_BEISPIELE = ("Leitstand an",)

# Kontingent-Zustand (Block 36): anders als die meisten Felder hier
# dauerhaft sichtbar wie die Modellanzeige - "Woche: unter Warnschwelle"
# ohne RateLimitEvent-Meldung des Agent-SDK, sonst "Woche NN % · zurück
# Do HH:MM" mit der echten Auslastung (Feld "utilization"). Die Breite wird
# am laengsten moeglichen Text gemessen.
KONTINGENT_WOCHE_BEISPIELE = ("Woche 100 % · zurück Mi 11:00", "Woche: unter Warnschwelle")

# Zweites Kontingent-Feld fuer das Fuenf-Stunden-Fenster - verborgen, bis das
# SDK zum ersten Mal eine Meldung dazu schickt (siehe core/sitzung.py,
# _kontingent_zustand_berechnen, "sitzung_anzeige").
KONTINGENT_SITZUNG_BEISPIELE = ("Sitzung 100 % · zurück 11:00",)

# "Such-Effizienz" (Block C10, umbenannt von "Suche gespart"): Grundwert vom
# 21.09.2026 geteilt durch die aktuellen Lesezugriffe (Read, Grep, Glob,
# lesende Bash-Befehle) vor der ersten Dateiänderung, mal 100 - keine
# Token-Ersparnis. 100 % ist der Normalwert, mehr heißt gezielter gesucht,
# weniger heißt umständlicher. Unter 5 Aufträgen seit Block C6 steht ein
# Gedankenstrich statt einer Zahl (siehe such_effizienz_zeigen); die Breite
# wird an beiden Beispielen gemessen. Block 81: zusaetzlich farbig gestuft
# (stil.qss, Eigenschaft "effizienzstufe") - ab 100 % gruenlich, darunter
# roetlich, siehe _such_effizienz_stufe.
SUCH_EFFIZIENZ_BEISPIELE = ("Such-Effizienz –", "Such-Effizienz 999 %")

# Modellanzeige (Block 70, Teil B): der Name des tatsaechlich verbundenen
# Modells (core/modelle.py, anzeige_name) - dauerhaft sichtbar, nie leer, im
# Unterschied zu den meisten anderen Feldern hier. Breite an allen vier
# moeglichen Namen gemessen.
MODELL_BEISPIELE = ("Sonnet 5", "Opus 5", "Haiku 4.5", "Fable 5.1")

# Eingangsanzeige (Block 63): wie viele Auftragsdateien im Eingangsordner auf
# ein ANDERES, nicht offenes Projekt warten (core/eingangsordner.py,
# fremde_projekte) - leer und verborgen, solange keine solche Datei da liegt.
# Nur die Gesamtzahl ist fest breit messbar (die Liste der Projektnamen waere
# beliebig lang und wuerde wieder eine Mindestbreite erzwingen wie vor
# Block 49); die Aufschluesselung je Projekt steht im Kurzhinweis/Vorlesetext.
EINGANG_BEISPIELE = ("Eingang 99",)

# Beispieltexte fuer die festen Breiten der Zahlenfelder rechts. Alle drei
# Zaehler werden an allen drei Texten gemessen und bekommen dieselbe Breite,
# damit sie als gleich grosse Reihe nebeneinander stehen. Block 81: kein
# wortloser Kurzmodus mehr - "Auftrag"/"Sitzung"/"Heute" stehen immer dabei.
AUFTRAG_BEISPIEL = "Auftrag 999.999"
SITZUNG_BEISPIEL = "Sitzung 999.999"
HEUTE_BEISPIEL = "Heute 999.999"
ZAEHLER_BEISPIELE = (AUFTRAG_BEISPIEL, SITZUNG_BEISPIEL, HEUTE_BEISPIEL)


def zahl_lang(anzahl: int) -> str:
    """Volle Zahl mit Punkt als Tausendertrenner: 342858 -> '342.858'."""
    return f"{int(anzahl):,}".replace(",", ".")


def zahl_kurz(anzahl: int) -> str:
    """Grosse Zahlen abgekuerzt, damit die Statuszeile lesbar bleibt:
    1234567 -> '1,2 Mio', kleinere Zahlen unveraendert ausgeschrieben."""
    anzahl = int(anzahl)
    if anzahl >= 1_000_000:
        return f"{anzahl / 1_000_000:.1f}".replace(".", ",") + " Mio"
    return zahl_lang(anzahl)


class Schrumpffeld(QLabel):
    """Ein Feld der Kopfzeile mit fester Wunschbreite, das aber immer den
    vollen Text zeigt - nichts wird mit Auslassungspunkten gekuerzt.

    Solange Platz ist, haelt es die gemessene Wunschbreite - dadurch springt
    in der Reihe nichts, wenn sich der Inhalt aendert.

    Vor dem Messen steht die Wunschbreite auf null: dann meldet das Feld
    seine echte Textbreite, und `masse_festlegen` misst nicht sich selbst.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._voller_text = text
        self._wunschbreite = 0

    def wunschbreite_setzen(self, breite: int) -> None:
        """Uebernimmt das gemessene Mass als Wunsch- und Hoechstbreite."""
        self._wunschbreite = max(0, int(breite))
        self.setMinimumWidth(0)
        self.setMaximumWidth(self._wunschbreite or 16777215)
        self.updateGeometry()

    def masse_zuruecksetzen(self) -> None:
        """Gibt das Feld zum Messen frei: keine Grenze mehr."""
        self._wunschbreite = 0
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        super().setText(self._voller_text)

    def voller_text(self) -> str:
        return self._voller_text

    def setText(self, text: str) -> None:
        self._voller_text = text
        super().setText(text)

    def sizeHint(self) -> QSize:
        masse = super().sizeHint()
        if self._wunschbreite <= 0:
            return masse
        return QSize(self._wunschbreite, masse.height())


class KlickbaresFeld(Schrumpffeld):
    """Wie Schrumpffeld, zusaetzlich mit einem Klick-Signal - fuer die
    Warteanzeige (Block 60): Antippen oder Anklicken der Zahl oeffnet
    "Warteschlange verwalten" direkt, ohne den Umweg ueber Umschalt+F4."""

    geklickt = Signal()

    def mousePressEvent(self, ereignis) -> None:
        if ereignis.button() == Qt.LeftButton:
            self.geklickt.emit()
        super().mousePressEvent(ereignis)


def such_effizienz_stufe(prozent: int | None) -> str:
    """Block 81: ordnet die Such-Effizienz einer von vier Farbstufen zu
    (stil.qss, Eigenschaft "effizienzstufe") - leer, solange noch kein Wert
    vorliegt. Ab 100 % gruenlich, darunter roetlich, in zwei Abstufungen je
    Richtung statt stufenlos: eine echte stufenlose Farbmischung liesse sich
    in Qt-Stylesheets nicht aus einer Zahl berechnen, feste Stufen reichen
    fuer die Einordnung "besser/schlechter als üblich" aus."""
    if prozent is None:
        return ""
    if prozent >= 150:
        return "sehr_gut"
    if prozent >= 100:
        return "gut"
    if prozent >= 70:
        return "mittel"
    return "schlecht"


def such_effizienz_einordnung(prozent: int | None) -> str:
    """Block 81: der barrierefreie Wortlaut zur Zahl - "besser"/"schlechter"/
    "wie üblich" statt nur der nackten Prozentzahl, wie im Auftrag verlangt."""
    if prozent is None:
        return ""
    if prozent == 100:
        return "wie üblich"
    return "besser als üblich" if prozent > 100 else "schlechter als üblich"


class ZeilenFluss(QLayout):
    """Reiht seine Kinder nebeneinander ein und bricht in eine neue Zeile um,
    sobald die Breite nicht mehr reicht (Block 81) - anders als die
    Kachelreihe (core/tastenleiste.py, gleich breite Kacheln in einem
    Raster mit fester Spaltenzahl) muessen hier unterschiedlich breite
    Felder verpackt werden, ein Raster mit gemeinsamen Spaltenbreiten wuerde
    viel Platz verschenken. Erzwingt nie eine Mindestbreite: wie viele
    Zeilen fuer die aktuelle Breite noetig sind, meldet `heightForWidth` an
    das Layout, das die Kopfzeile in core/fenster.py traegt."""

    def __init__(self, parent=None, abstand: int = 6):
        super().__init__(parent)
        self._eintraege: list = []
        self.setSpacing(abstand)

    def addItem(self, item) -> None:
        self._eintraege.append(item)

    def count(self) -> int:
        return len(self._eintraege)

    def itemAt(self, index: int):
        return self._eintraege[index] if 0 <= index < len(self._eintraege) else None

    def takeAt(self, index: int):
        return self._eintraege.pop(index) if 0 <= index < len(self._eintraege) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, breite: int) -> int:
        return self._anordnen(QRect(0, 0, breite, 0), nur_messen=True)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._anordnen(rect, nur_messen=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        groesse = QSize()
        for eintrag in self._eintraege:
            groesse = groesse.expandedTo(eintrag.minimumSize())
        rand = self.contentsMargins()
        groesse += QSize(rand.left() + rand.right(), rand.top() + rand.bottom())
        return groesse

    def _anordnen(self, rect, nur_messen: bool) -> int:
        """Packt jedes sichtbare Element so weit nach rechts, wie es passt,
        und beginnt sonst eine neue Zeile. `nur_messen` berechnet nur die
        noetige Hoehe (heightForWidth), ohne die Kinder zu verschieben -
        gebraucht, solange `rect` noch keine echte Geometrie trägt."""
        x, y = rect.x(), rect.y()
        zeilenhoehe = 0
        abstand = self.spacing()
        for eintrag in self._eintraege:
            widget = eintrag.widget()
            # isHidden() statt isVisible(): ein Feld, das (noch) keinen
            # sichtbaren Vorfahren hat - etwa beim allerersten Einrichten,
            # bevor das Hauptfenster gezeigt wird - meldet isVisible() faelschlich
            # als False, obwohl es niemand absichtlich ausgeblendet hat.
            if widget is not None and widget.isHidden():
                continue
            masse = eintrag.sizeHint()
            naechstes_x = x + masse.width()
            if naechstes_x > rect.right() and zeilenhoehe > 0:
                x = rect.x()
                y += zeilenhoehe + abstand
                naechstes_x = x + masse.width()
                zeilenhoehe = 0
            if not nur_messen:
                eintrag.setGeometry(QRect(QPoint(x, y), masse))
            x = naechstes_x + abstand
            zeilenhoehe = max(zeilenhoehe, masse.height())
        return y + zeilenhoehe - rect.y()


class Ausgabekopf(QWidget):
    """Die Kopfzeile ueber dem Ausgabefeld. Sie zeigt nur an; entschieden wird
    nichts hier. Das Fenster setzt die Werte, die Kopfzeile stellt sie dar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ausgabekopf")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName("Kopfzeile der Ausgabe")

        self.nur_lesen = False
        self._status_text = "Verbinde …"

        # Rohwerte je Feld, damit nach einem Schriftwechsel (masse_festlegen)
        # neu gezeichnet werden kann, ohne dass das Fenster den Wert erneut
        # liefern muss.
        self._sicherheit_internet = False
        self._sicherheit_loeschen = False
        self._sicherheit_installieren = False
        self._freigaben_namen: list = []
        self._bruecke_an = False
        self._leitstand_an = False
        self._kontingent_stufe = "normal"
        self._kontingent_text = "Woche: unter Warnschwelle."
        self._kontingent_woche_anzeige = "Woche: unter Warnschwelle"
        self._kontingent_sitzung_anzeige: str | None = None
        self._such_prozent: int | None = None
        self._modell_lang = ""
        self._warte_anzahl = 0
        self._eingang_fremde: dict = {}
        self._verbrauch: dict = {}
        self._heute = 0
        # Je Feld die bei masse_festlegen gemessene Breite.
        self._breiten: dict = {}
        self._hoehe = 0

        # Block 81: ZeilenFluss statt QHBoxLayout - bricht in eine neue Zeile
        # um, statt ein Feld zu kuerzen oder sein Wort wegzulassen, siehe
        # Modul-Doc. Kein addStretch mehr: die Felder stehen in genau der
        # Reihenfolge da, in der sie unten angelegt werden.
        quer = ZeilenFluss(self, abstand=6)
        quer.setContentsMargins(0, 0, 0, 0)
        # Ohne SetNoConstraint zwingt Qt diesem Widget per Vorgabe die Summe
        # aller Mindestbreiten der Kinder als eigene Mindestbreite auf (hier
        # vor allem durch #zaehlerreihe, siehe unten) - genau die Masche aus
        # Block 49 (core/fenster.py, Fix dort betraf das Hauptfenster; hier
        # betrifft es die Kopfzeile selbst). Das wuerde den Umbruch nie
        # auslösen, weil die Reihe gar nicht erst schmaler werden dürfte.
        quer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        # Die Reihe beginnt mit dem Sicherheitshinweis. Taetigkeit und
        # bearbeitete Datei stehen gross im Aktivitaetsbalken oben
        # (core/fenster.py), das Schreibrecht einzig an der Kachel
        # ZUGRIFF_KENNUNG (F10) - beides steht nicht mehr hier. Kurzer Text,
        # solange mindestens einer der drei Rueckfrage-Schalter aus den
        # Einstellungen (Internet, Loeschen im Projekt, Installieren) an
        # ist. Ab Werk sind alle drei aus, das Feld bleibt dann leer.
        self.sicherheitshinweis = Schrumpffeld("")
        self.sicherheitshinweis.setObjectName("sicherheitshinweis")
        self.sicherheitshinweis.setAccessibleName("Rückfrage-Ausnahmen")
        self.sicherheitshinweis.setAlignment(Qt.AlignCenter)
        self.sicherheitshinweis.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.sicherheitshinweis)

        # Zahl der Ordner, die ausserhalb des Projekts ohne Rueckfrage
        # gelesen und geschrieben werden duerfen (Einstellungen, Reiter
        # Freigaben). Bei keiner Freigabe bleibt das Feld leer.
        self.freigabenanzeige = Schrumpffeld("")
        self.freigabenanzeige.setObjectName("freigabenanzeige")
        self.freigabenanzeige.setAccessibleName("Aktive Freigaben")
        self.freigabenanzeige.setAlignment(Qt.AlignCenter)
        self.freigabenanzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.freigabenanzeige)

        # Statushinweis fuer die Bruecke zu claude.ai im Browser
        # (Einstellungen, Reiter Verhalten, Umschalt+F8). Block 81: anders
        # als zuvor dauerhaft sichtbar wie die Modellanzeige - "Brücke: an"
        # oder "Brücke: aus" steht immer als ein zusammenhaengender Text da,
        # nie nur das blosse Wort "Brücke" ohne Zustand.
        self.bruecke_anzeige = Schrumpffeld("")
        self.bruecke_anzeige.setObjectName("brueckenanzeige")
        self.bruecke_anzeige.setAccessibleName("Brücken-Status")
        self.bruecke_anzeige.setAlignment(Qt.AlignCenter)
        self.bruecke_anzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.bruecke_anzeige)

        # Statushinweis, solange Leitstand fuer dieses Projekt an ist
        # (Einstellungen, Reiter Leitstand, Umschalt+F9). Aus bzw. nicht
        # eingerichtet ist der Normalfall, dann bleibt das Feld leer.
        self.leitstand_anzeige = Schrumpffeld("")
        self.leitstand_anzeige.setObjectName("leitstandanzeige")
        self.leitstand_anzeige.setAccessibleName("Leitstand-Status")
        self.leitstand_anzeige.setAlignment(Qt.AlignCenter)
        self.leitstand_anzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.leitstand_anzeige)

        # Modellanzeige (Block 70, Teil B): der Name des tatsaechlich
        # verbundenen Modells - anders als die meisten Felder hier dauerhaft
        # sichtbar, nie leer. core/fenster.py setzt den Wert ueber
        # modell_zeigen(), sobald die Sitzung (neu) verbunden ist.
        self.modellanzeige = Schrumpffeld("")
        self.modellanzeige.setObjectName("modellanzeige")
        self.modellanzeige.setAccessibleName("Modell")
        self.modellanzeige.setAlignment(Qt.AlignCenter)
        self.modellanzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.modellanzeige)

        # "Such-Effizienz" (Block C10), seit Block 81 zusaetzlich farbig
        # gestuft (stil.qss). Nicht gesprochen - F2 "Wo stehen wir" nennt
        # den Wert stattdessen als Satz.
        self.such_effizienz = Schrumpffeld("")
        self.such_effizienz.setObjectName("such_effizienz")
        self.such_effizienz.setAccessibleName("Such-Effizienz")
        self.such_effizienz.setAlignment(Qt.AlignCenter)
        self.such_effizienz.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.such_effizienz)

        # Kontingent-Zustand, Wochenfenster (Block 36): anders als die
        # meisten Felder hier dauerhaft sichtbar - zeigt entweder die echte
        # Auslastung (core/sitzung.py, "utilization") oder "unter
        # Warnschwelle", solange das SDK noch keine Meldung geschickt hat.
        self.kontingent_anzeige = Schrumpffeld("")
        self.kontingent_anzeige.setObjectName("kontingentanzeige")
        self.kontingent_anzeige.setAccessibleName("Wochenkontingent")
        self.kontingent_anzeige.setAlignment(Qt.AlignCenter)
        self.kontingent_anzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.kontingent_anzeige)

        # Kontingent-Zustand, Fuenf-Stunden-Fenster (Block 36): verborgen,
        # bis das SDK zum ersten Mal eine Meldung dazu schickt - vorher weiss
        # CWB darueber schlicht nichts.
        self.kontingent_sitzung_anzeige = Schrumpffeld("")
        self.kontingent_sitzung_anzeige.setObjectName("kontingentsitzunganzeige")
        self.kontingent_sitzung_anzeige.setAccessibleName("Sitzungskontingent")
        self.kontingent_sitzung_anzeige.setAlignment(Qt.AlignCenter)
        self.kontingent_sitzung_anzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.kontingent_sitzung_anzeige.setVisible(False)
        quer.addWidget(self.kontingent_sitzung_anzeige)

        # Warteanzeige: die Zahl der Auftraege, die hinter dem laufenden
        # stehen. Sie ist leer und verborgen, solange keiner wartet, damit
        # die Zeile im Normalfall ruhig bleibt. Geleert wird die
        # Warteschlange mit F4.
        self.warteanzeige = KlickbaresFeld("")
        self.warteanzeige.setObjectName("warteanzeige")
        self.warteanzeige.setAccessibleName("Warteschlange")
        self.warteanzeige.setAlignment(Qt.AlignCenter)
        self.warteanzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # Antippen/Anklicken oeffnet "Warteschlange verwalten" (Block 60) -
        # der Zeigerwechsel zeigt sehenden Nutzern, dass die Zahl klickbar
        # ist; das Signal `geklickt` verbindet fenster.py.
        self.warteanzeige.setCursor(Qt.PointingHandCursor)
        # Verborgen, solange keiner wartet: ZeilenFluss uebergeht verborgene
        # Felder vollstaendig, sie hinterlassen keine Luecke.
        self.warteanzeige.setVisible(False)
        quer.addWidget(self.warteanzeige)

        # Eingangsanzeige (Block 63): Zahl der Auftragsdateien im
        # Eingangsordner, die auf ein anderes, nicht offenes Projekt warten.
        # Leer und verborgen, solange keine da liegt - der Normalfall.
        self.eingangsanzeige = Schrumpffeld("")
        self.eingangsanzeige.setObjectName("eingangsanzeige")
        self.eingangsanzeige.setAccessibleName("Aufträge für andere Projekte")
        self.eingangsanzeige.setAlignment(Qt.AlignCenter)
        self.eingangsanzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.eingangsanzeige.setVisible(False)
        quer.addWidget(self.eingangsanzeige)

        # Die drei Zaehler sitzen in einer eigenen Reihe ohne Zwischenraum:
        # Auftrag, Sitzung, Heute - gleiche Breite, gleiche Gestalt, direkt
        # aneinander, damit man sie als einen Block liest.
        self.zaehlerreihe = QWidget()
        self.zaehlerreihe.setObjectName("zaehlerreihe")
        self.zaehlerreihe.setAccessibleName("Tokenzähler")
        self.zaehlerreihe.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        reihe = QHBoxLayout(self.zaehlerreihe)
        reihe.setContentsMargins(0, 0, 0, 0)
        reihe.setSpacing(0)

        # Token dieses einen Auftrags
        self.tokenzaehler = Schrumpffeld("Auftrag 0")
        self.tokenzaehler.setObjectName("tokenzaehler")
        self.tokenzaehler.setAccessibleName("Token dieses Auftrags")

        # Gesamtsumme der laufenden Sitzung
        self.sitzungszaehler = Schrumpffeld("Sitzung 0")
        self.sitzungszaehler.setObjectName("sitzungszaehler")
        self.sitzungszaehler.setAccessibleName("Token der ganzen Sitzung")

        # Summe des ganzen Kalendertages, ueber alle Sitzungen und Neustarts
        # hinweg. Sie kommt aus einstellungen.json und faengt um Mitternacht
        # von selbst wieder bei null an.
        self.tageszaehler = Schrumpffeld("Heute 0")
        self.tageszaehler.setObjectName("tageszaehler")
        self.tageszaehler.setAccessibleName("Token heute")

        for zaehler in (self.tokenzaehler, self.sitzungszaehler, self.tageszaehler):
            zaehler.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            zaehler.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            reihe.addWidget(zaehler)

        quer.addWidget(self.zaehlerreihe)

    # -- Masse --------------------------------------------------------------

    def _breite_messen(self, teil: QLabel, beispiele) -> tuple[int, int]:
        """Misst ein Feld an gleichbleibenden Beispieltexten und gibt Breite
        und Hoehe des breitesten zurueck. Der eigene Text bleibt erhalten."""
        merker = teil.text()
        breite = hoehe = 0
        for wort in beispiele:
            teil.setText(wort)
            masse = teil.sizeHint()
            breite = max(breite, masse.width())
            hoehe = max(hoehe, masse.height())
        teil.setText(merker)
        return breite, hoehe

    def masse_festlegen(self) -> None:
        """Legt die Masse der Kopfzeile fest: jedes Feld genau eine Textzeile
        hoch, auf die Breite seiner gleichbleibenden Beispieltexte gemessen.
        Kein Inhalt kann die Groesse eines einzelnen Feldes aendern - weder
        eine grosse Zahl noch ein langer Freigaben-Zaehler.

        Block 81: die Breite ist Wunsch und Obergrenze je Feld, keine
        Untergrenze der ganzen Reihe - reicht die Fensterbreite fuer eine
        Zeile nicht, bricht `ZeilenFluss` selbst in weitere Zeilen um (siehe
        Modul-Doc), ohne dass ein Feld dafuer sein Wort verliert. Zusaetzlich
        besorgt die Skalierung des ganzen Stilblatts (core/grundlagen.py,
        `stil_anwenden`) das Schrumpfen von Schrift und Abstaenden."""
        try:
            felder = (
                ("sicherheitshinweis", self.sicherheitshinweis, SICHERHEITSHINWEIS_BEISPIELE),
                ("freigabenanzeige", self.freigabenanzeige, FREIGABEN_BEISPIELE),
                ("bruecke_anzeige", self.bruecke_anzeige, BRUECKE_BEISPIELE),
                ("leitstand_anzeige", self.leitstand_anzeige, LEITSTAND_BEISPIELE),
                ("modellanzeige", self.modellanzeige, MODELL_BEISPIELE),
                ("such_effizienz", self.such_effizienz, SUCH_EFFIZIENZ_BEISPIELE),
                ("kontingent_anzeige", self.kontingent_anzeige, KONTINGENT_WOCHE_BEISPIELE),
                ("kontingent_sitzung_anzeige", self.kontingent_sitzung_anzeige,
                 KONTINGENT_SITZUNG_BEISPIELE),
                ("warteanzeige", self.warteanzeige, WARTE_BEISPIELE),
                ("eingangsanzeige", self.eingangsanzeige, EINGANG_BEISPIELE),
                ("tokenzaehler", self.tokenzaehler, ZAEHLER_BEISPIELE),
                ("sitzungszaehler", self.sitzungszaehler, ZAEHLER_BEISPIELE),
                ("tageszaehler", self.tageszaehler, ZAEHLER_BEISPIELE),
            )
            breiten = {}
            hoehe = 0
            for name, teil, beispiele in felder:
                # Ohne Grenze messen, sonst misst das Feld seine eigene
                # Wunschbreite vom letzten Mal.
                teil.masse_zuruecksetzen()
                breite, teilhoehe = self._breite_messen(teil, beispiele)
                if breite <= 0 or teilhoehe <= 0:
                    return
                breiten[name] = breite
                hoehe = max(hoehe, teilhoehe)

            self._breiten = breiten
            self._hoehe = hoehe
            self._anzeige_aktualisieren()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Maße der Kopfzeile nicht festgelegt: %s", fehler)

    def _anzeige_aktualisieren(self) -> None:
        """Setzt an jedem Feld die gemessene Wunschbreite und zeichnet alle
        Anzeigen neu. Aufgerufen nach jedem Messen (masse_festlegen). Setzt
        nie die Hoehe der ganzen Reihe fest - wie viele Zeilen sie braucht,
        bestimmt allein `ZeilenFluss` je nach Fensterbreite."""
        if not self._breiten:
            return
        for name, breite in self._breiten.items():
            teil = getattr(self, name)
            teil.wunschbreite_setzen(breite)
            teil.setFixedHeight(self._hoehe)
        self._sicherheitshinweis_zeichnen()
        self._freigaben_zeichnen()
        self._bruecke_zeichnen()
        self._leitstand_zeichnen()
        self._kontingent_zeichnen()
        self._such_effizienz_zeichnen()
        self._modell_zeichnen()
        self._warteschlange_zeichnen()
        self._eingang_fremde_zeichnen()
        self._verbrauch_zeichnen()
        self._tag_zeichnen()

    # -- Warteschlange ------------------------------------------------------

    def warteschlange_zeigen(self, anzahl: int) -> None:
        """Zeigt, wie viele Auftraege hinter dem laufenden warten. Bei null
        bleibt das Feld leer; der volle Wortlaut steht als Beschreibung und
        Kurzhinweis dahinter."""
        self._warte_anzahl = max(0, int(anzahl))
        self._warteschlange_zeichnen()

    def _warteschlange_zeichnen(self) -> None:
        try:
            anzahl = self._warte_anzahl
            text = f"Warten {anzahl}"
            self.warteanzeige.setText(text if anzahl else "")
            self.warteanzeige.setVisible(anzahl > 0)
            if anzahl == 0:
                satz = "Warteschlange leer, es wartet kein Auftrag."
            elif anzahl == 1:
                satz = ("Ein Auftrag wartet. Warteschlange leeren mit F4, "
                         "einzeln verwalten mit Umschalt+F4 oder durch "
                         "Antippen dieser Zahl.")
            else:
                satz = (f"{anzahl} Aufträge warten. Warteschlange leeren mit F4, "
                         "einzeln verwalten mit Umschalt+F4 oder durch "
                         "Antippen dieser Zahl.")
            self.warteanzeige.setToolTip(satz)
            self.warteanzeige.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Warteanzeige nicht gesetzt: %s", fehler)

    # -- Eingangsordner, fremde Projekte (Block 63) --------------------------

    def eingang_fremde_zeigen(self, projekte: dict) -> None:
        """Zeigt, wie viele Auftragsdateien im Eingangsordner auf ein anderes,
        nicht offenes Projekt warten (core/eingangsordner.py,
        fremde_projekte). `projekte` ist ein dict Projektname -> Anzahl; leer
        heisst keine. Nur die Gesamtzahl steht im Feld selbst (feste Breite,
        siehe EINGANG_BEISPIELE), die Aufschluesselung je Projekt im
        Kurzhinweis und Vorlesetext."""
        self._eingang_fremde = dict(projekte)
        self._eingang_fremde_zeichnen()

    def _eingang_fremde_zeichnen(self) -> None:
        try:
            projekte = self._eingang_fremde
            gesamt = sum(projekte.values())
            text = f"Eingang {gesamt}"
            self.eingangsanzeige.setText(text if gesamt else "")
            self.eingangsanzeige.setVisible(gesamt > 0)
            if not projekte:
                satz = "Keine Aufträge für andere Projekte im Eingang."
            else:
                aufzaehlung = ", ".join(f"{name} ({anzahl})" for name, anzahl in projekte.items())
                satz = f"Aufträge für andere Projekte im Eingang: {aufzaehlung}."
            self.eingangsanzeige.setToolTip(satz)
            self.eingangsanzeige.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Eingangsanzeige nicht gesetzt: %s", fehler)

    # -- Statusmeldung ------------------------------------------------------

    @property
    def status_text(self) -> str:
        """Die gemerkte Meldung ohne den angehaengten Nur-Lesen-Hinweis."""
        return self._status_text

    def status_zeigen(self, text: str) -> None:
        """Einzige Stelle, die die Statusmeldung merkt. Ein eigenes Feld hat
        sie nicht mehr; gesprochen wird sie ohnehin ganz."""
        self._status_text = text
        self.status_zeichnen()

    def nur_lesen_setzen(self, an: bool) -> None:
        """Merkt den Nur-Lesen-Zustand fuer die Statusmeldung. Angezeigt wird
        er einzig an der Kachel ZUGRIFF_KENNUNG (F10, core/fenster.py); ein
        zweites Feld dafuer gibt es hier nicht mehr."""
        self.nur_lesen = bool(an)
        self.status_zeichnen()

    def sicherheitshinweis_setzen(
        self,
        internet_ohne_rueckfrage: bool,
        loeschen_ohne_rueckfrage: bool,
        installieren_ohne_rueckfrage: bool = False,
    ) -> None:
        """Zeigt ein kurzes Zeichen, solange mindestens einer der drei
        Rueckfrage-Schalter (Einstellungen, Reiter Verhalten) an ist. Sind
        alle drei aus, bleibt das Feld leer."""
        self._sicherheit_internet = internet_ohne_rueckfrage
        self._sicherheit_loeschen = loeschen_ohne_rueckfrage
        self._sicherheit_installieren = installieren_ohne_rueckfrage
        self._sicherheitshinweis_zeichnen()

    def _sicherheitshinweis_zeichnen(self) -> None:
        try:
            teile = []
            if self._sicherheit_internet:
                teile.append("Internet")
            if self._sicherheit_loeschen:
                teile.append("Löschen")
            if self._sicherheit_installieren:
                teile.append("Installieren")
            if teile:
                self.sicherheitshinweis.setText("⚠ " + " · ".join(teile))
                satz = "Ohne Rückfrage erlaubt: " + " und ".join(teile) + "."
            else:
                self.sicherheitshinweis.setText("")
                satz = "Keine Rückfrage-Ausnahme aktiv."
            # Verborgen statt einer leeren Flaeche (Block 81): sonst stuende
            # bei den meisten Projekten dauerhaft eine leere Box in der Reihe.
            self.sicherheitshinweis.setVisible(bool(teile))
            self.sicherheitshinweis.setToolTip(satz)
            self.sicherheitshinweis.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Sicherheitshinweis nicht gesetzt: %s", fehler)

    def bruecke_zeigen(self, an: bool) -> None:
        """Zeigt den Bruecken-Status als vollstaendiges Wort (Einstellungen,
        Reiter Verhalten, Umschalt+F8). Block 81: anders als die meisten
        Felder hier dauerhaft sichtbar - "Brücke: an" oder "Brücke: aus"
        steht immer als ein Textstueck da, nie das blosse Wort "Brücke"
        ohne seinen Zustand."""
        self._bruecke_an = bool(an)
        self._bruecke_zeichnen()

    def _bruecke_zeichnen(self) -> None:
        try:
            an = self._bruecke_an
            self.bruecke_anzeige.setText("Brücke: an" if an else "Brücke: aus")
            satz = "Brücke an: Claude im Browser kann Aufträge schicken." if an \
                else "Brücke aus."
            self.bruecke_anzeige.setToolTip(satz)
            self.bruecke_anzeige.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Brücken-Statushinweis nicht gesetzt: %s", fehler)

    def leitstand_zeigen(self, an: bool) -> None:
        """Zeigt "Leitstand an", solange der Schalter fuer dieses Projekt an
        ist (Einstellungen, Reiter Leitstand, Umschalt+F9). Aus bzw. nicht
        eingerichtet bleibt das Feld leer - das ist der Normalfall."""
        self._leitstand_an = bool(an)
        self._leitstand_zeichnen()

    def _leitstand_zeichnen(self) -> None:
        try:
            an = self._leitstand_an
            self.leitstand_anzeige.setText("Leitstand an" if an else "")
            # Verborgen statt leerer Flaeche (Block 81): ein Projekt ohne
            # Leitstand soll hier dauerhaft nichts zeigen.
            self.leitstand_anzeige.setVisible(an)
            satz = "Leitstand an: entscheidet nachts selbst über den Nachtplan." if an \
                else "Leitstand aus."
            self.leitstand_anzeige.setToolTip(satz)
            self.leitstand_anzeige.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Leitstand-Statushinweis nicht gesetzt: %s", fehler)

    def kontingent_zeigen(self, stufe: str, text: str, woche_anzeige: str,
                           sitzung_anzeige: str | None) -> None:
        """Zeigt den Kontingent-Zustand (Block 36, core/sitzung.py,
        `kontingent_zustand`). Anders als die meisten Felder hier dauerhaft
        sichtbar wie die Modellanzeige: `woche_anzeige` ist nie leer (z.B.
        "Woche 80 % · zurück Do 11:00" oder "Woche: unter Warnschwelle").
        `sitzung_anzeige` ist None, bis das Fuenf-Stunden-Fenster zum ersten
        Mal gemeldet hat - vorher bleibt das zweite Feld verborgen. `stufe`
        faerbt beide Felder (stil.qss, Eigenschaft "kontingentstufe"):
        "normal" ruhig, "warnung" gelb/orange (90-95 %), "kritisch"/
        "erschoepft" rot. `text` ist der fertige Satz aus der Sitzung, hier
        als Kurzhinweis/Vorlesetext fuer beide Felder verwendet."""
        self._kontingent_stufe = stufe or "normal"
        self._kontingent_text = text or ""
        self._kontingent_woche_anzeige = woche_anzeige or "Woche: unter Warnschwelle"
        self._kontingent_sitzung_anzeige = sitzung_anzeige
        self._kontingent_zeichnen()

    def _kontingent_stufe_setzen(self, feld: QLabel, stufe: str) -> None:
        if str(feld.property("kontingentstufe") or "") != stufe:
            feld.setProperty("kontingentstufe", stufe)
            feld.style().unpolish(feld)
            feld.style().polish(feld)

    def _kontingent_zeichnen(self) -> None:
        try:
            stufe = self._kontingent_stufe
            satz = self._kontingent_text or "Woche: unter Warnschwelle."

            self.kontingent_anzeige.setText(self._kontingent_woche_anzeige)
            self.kontingent_anzeige.setToolTip(satz)
            self.kontingent_anzeige.setAccessibleDescription(satz)
            self._kontingent_stufe_setzen(self.kontingent_anzeige, stufe)

            sitzung_text = self._kontingent_sitzung_anzeige
            self.kontingent_sitzung_anzeige.setText(sitzung_text or "")
            # Verborgen, bis das Fuenf-Stunden-Fenster zum ersten Mal
            # gemeldet hat - vorher weiss CWB darueber schlicht nichts.
            self.kontingent_sitzung_anzeige.setVisible(bool(sitzung_text))
            if sitzung_text:
                self.kontingent_sitzung_anzeige.setToolTip(satz)
                self.kontingent_sitzung_anzeige.setAccessibleDescription(satz)
                self._kontingent_stufe_setzen(self.kontingent_sitzung_anzeige, stufe)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kontingent-Anzeige nicht gesetzt: %s", fehler)

    def freigaben_zeigen(self, namen: list) -> None:
        """Zeigt, wie viele Ordner ausserhalb des Projekts ohne Rueckfrage
        freigegeben sind (Einstellungen, Reiter Freigaben). Bei keiner
        Freigabe bleibt das Feld leer."""
        self._freigaben_namen = list(namen)
        self._freigaben_zeichnen()

    def _freigaben_zeichnen(self) -> None:
        try:
            namen = self._freigaben_namen
            anzahl = len(namen)
            text = f"Freigaben {anzahl}" if anzahl else ""
            self.freigabenanzeige.setText(text)
            # Verborgen statt leerer Flaeche (Block 81): ohne Freigabe soll
            # hier dauerhaft nichts stehen.
            self.freigabenanzeige.setVisible(anzahl > 0)
            if anzahl == 0:
                satz = "Keine Freigabe aktiv."
            else:
                satz = f"{anzahl} Freigaben aktiv: " + ", ".join(namen) + "."
            self.freigabenanzeige.setToolTip(satz)
            self.freigabenanzeige.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Freigabenanzeige nicht gesetzt: %s", fehler)

    def such_effizienz_zeigen(self, prozent: int | None) -> None:
        """Zeigt die Kennzahl "Such-Effizienz" (Block C10): Grundwert vom
        21.09.2026 geteilt durch die aktuellen Lesezugriffe (Read, Grep,
        Glob, lesende Bash-Befehle) vor der ersten Dateiänderung, mal 100.
        100 % ist der Normalwert, mehr heißt gezielter gesucht, weniger
        heißt umständlicher. Keine Token-Ersparnis - reines Nachschauen
        kostet selbst welche. `prozent` ist None, solange weniger als 5
        Aufträge seit Block C6 vorliegen; dann steht ein Gedankenstrich da.
        Nicht gesprochen."""
        self._such_prozent = prozent
        self._such_effizienz_zeichnen()

    def _such_effizienz_zeichnen(self) -> None:
        try:
            prozent = self._such_prozent
            stufe = such_effizienz_stufe(prozent)
            if str(self.such_effizienz.property("effizienzstufe") or "") != stufe:
                self.such_effizienz.setProperty("effizienzstufe", stufe)
                self.such_effizienz.style().unpolish(self.such_effizienz)
                self.such_effizienz.style().polish(self.such_effizienz)
            if prozent is None:
                self.such_effizienz.setText("Such-Effizienz –")
                satz = ("Such-Effizienz: noch nicht ermittelbar, weniger als "
                        "5 Aufträge seit Block C6.")
            else:
                self.such_effizienz.setText(f"Such-Effizienz {prozent} %")
                einordnung = such_effizienz_einordnung(prozent)
                satz = (
                    f"Such-Effizienz {prozent} Prozent, {einordnung}. 100 Prozent "
                    "ist der Normalwert vom 21.09.2026, mehr heißt gezielter "
                    "gesucht, weniger umständlicher. Gemessen werden Lesezugriffe "
                    "(Read, Grep, Glob, lesende Bash-Befehle) vor der ersten "
                    "Dateiänderung - keine Token-Ersparnis."
                )
            self.such_effizienz.setToolTip(satz)
            self.such_effizienz.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Such-Effizienz nicht gesetzt: %s", fehler)

    def modell_zeigen(self, lang: str, kurz: str = "") -> None:
        """Zeigt den Namen des tatsaechlich verbundenen Modells (Block 70,
        Teil B) - anders als die meisten Felder hier dauerhaft, nie leer.
        `lang` kommt fertig aus core/modelle.py (`anzeige_name`); `kurz`
        bleibt als Parameter erhalten, weil core/fenster.py beide Werte aus
        derselben Funktion entpackt, wird seit Block 81 aber nicht mehr
        angezeigt - es gibt keinen Kurzmodus mehr, der ihn bräuchte."""
        self._modell_lang = lang
        self._modell_zeichnen()

    def _modell_zeichnen(self) -> None:
        try:
            self.modellanzeige.setText(self._modell_lang)
            satz = f"Modell {self._modell_lang}." if self._modell_lang else "Modell unbekannt."
            self.modellanzeige.setToolTip(satz)
            self.modellanzeige.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Modellanzeige nicht gesetzt: %s", fehler)

    def status_zeichnen(self) -> None:
        """Legt die gemerkte Meldung samt Nur-Lesen-Zustand als Beschreibung
        und Kurzhinweis an die Kopfzeile. Platz kostet das keinen."""
        zusatz = "   ●  NUR LESEN" if self.nur_lesen else ""
        voll = f"{self._status_text}{zusatz}"
        try:
            self.setToolTip(voll)
            self.setAccessibleDescription(voll)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Statusmeldung nicht gesetzt: %s", fehler)

    # -- Tokenverbrauch -----------------------------------------------------

    def verbrauch_zeigen(self, verbrauch: dict) -> None:
        """Zeigt links die Token dieses Auftrags, rechts die der ganzen
        Sitzung. Wird nicht angesagt, nur angezeigt."""
        self._verbrauch = dict(verbrauch)
        self._verbrauch_zeichnen()
        if "heute" in verbrauch:
            self.tag_zeigen(verbrauch.get("heute", 0))

    def _verbrauch_zeichnen(self) -> None:
        try:
            verbrauch = self._verbrauch
            # Sichtbar sind nur frische Eingabe plus Ausgabe. Die Cache-Werte
            # wiederholen bei jedem Aufruf fast die ganze Unterhaltung und
            # wuerden die Zahl unbrauchbar aufblaehen; sie stehen nur im
            # Kurzhinweis. Die Woerter "Auftrag"/"Sitzung" bleiben immer
            # dabei (Block 81) - nie eine nackte Zahl.
            sitzung = verbrauch.get("sitzung", 0)
            letzter = verbrauch.get("gesamt", 0)
            self.tokenzaehler.setText(f"Auftrag {zahl_kurz(letzter)}")
            self.sitzungszaehler.setText(f"Sitzung {zahl_kurz(sitzung)}")

            auftrag_einzeln = (
                f"Dieser Auftrag {zahl_lang(letzter)} Token ohne Cache — "
                f"Eingabe {zahl_lang(verbrauch.get('eingabe', 0))}, "
                f"Ausgabe {zahl_lang(verbrauch.get('ausgabe', 0))}, "
                f"Cache gelesen {zahl_lang(verbrauch.get('cache_gelesen', 0))}, "
                f"Cache erstellt {zahl_lang(verbrauch.get('cache_erstellt', 0))}"
            )
            sitzung_einzeln = (
                f"Ganze Sitzung {zahl_lang(sitzung)} Token ohne Cache — "
                f"Eingabe {zahl_lang(verbrauch.get('sitzung_eingabe', 0))}, "
                f"Ausgabe {zahl_lang(verbrauch.get('sitzung_ausgabe', 0))}, "
                f"Cache gelesen {zahl_lang(verbrauch.get('sitzung_cache_gelesen', 0))}, "
                f"Cache erstellt {zahl_lang(verbrauch.get('sitzung_cache_erstellt', 0))}"
            )
            self.tokenzaehler.setToolTip(auftrag_einzeln)
            self.tokenzaehler.setAccessibleDescription(auftrag_einzeln)
            self.sitzungszaehler.setToolTip(sitzung_einzeln)
            self.sitzungszaehler.setAccessibleDescription(sitzung_einzeln)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Tokenverbrauch nicht gesetzt: %s", fehler)

    def tag_zeigen(self, heute: int) -> None:
        """Zeigt die Tagessumme rechts neben dem Sitzungszaehler. Sie zaehlt
        ueber alle Sitzungen und Neustarts eines Kalendertages hinweg."""
        self._heute = int(heute)
        self._tag_zeichnen()

    def _tag_zeichnen(self) -> None:
        try:
            heute = self._heute
            text = f"Heute {zahl_kurz(heute)}"
            self.tageszaehler.setText(text)
            satz = (
                f"Heute {zahl_lang(heute)} Token ohne Cache, über alle "
                "Sitzungen des Tages zusammen"
            )
            self.tageszaehler.setToolTip(satz)
            self.tageszaehler.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Tageszähler nicht gesetzt: %s", fehler)
