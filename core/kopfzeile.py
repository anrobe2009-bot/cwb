"""
CWB - Code Workbench
Kopfzeile des Ausgabefelds.

Eine einzige Zeile ueber dem Ausgabefeld traegt alles, was zum Stand der
Arbeit gehoert: die Zugriffsplakette mit dem geltenden Schreibrecht
("Nur lesen" oder "Lesen und Schreiben"), das Zeichen fuer aktive Rueckfrage-
Ausnahmen (Internet, Loeschen im Projekt, Installieren), die Zahl der aktiven
Freigaben (Einstellungen, Reiter Freigaben), die Warteanzeige mit der Zahl der
vorgemerkten Auftraege (leer, solange keiner wartet), die Modellwahl, die drei
Tokenzaehler und die Schaltflaeche zum Kopieren. Die Zaehler stehen
unmittelbar nebeneinander in der Reihenfolge "Auftrag", "Sitzung", "Heute" -
gleiche Breite, gleiche Gestalt, ohne Zwischenraum. Ein eigenes Feld fuer die
Statusmeldung gibt es nicht mehr; die Meldung wird gesprochen und steht als
Beschreibung an der Kopfzeile selbst.

Taetigkeit und bearbeitete Datei stehen nicht mehr hier, sondern gross und
fett direkt im Aktivitaetsbalken oben (core/fenster.py, Aktivitaetsbalken).

Das Modellfeld ist keine feste Anzeige, sondern ein Auswahlfeld: mit Tabulator
erreichbar, mit den Pfeiltasten zu wechseln. Welche Modelle darin stehen, sagt
Claude Code selbst - die Kopfzeile stellt nur dar, was ihr gereicht wird.

Alle Felder werden an gleichbleibenden Beispieltexten gemessen und halten
dieses Mass, solange das Fenster breit genug ist: kein Inhalt kann die Groesse
aendern, darum rutscht das Ausgabefeld darunter nie auf und ab und in der Reihe
verschiebt sich nichts. Kein Feld kuerzt seinen Text: Passt die ganze Reihe
nicht mehr nebeneinander, wandern zuerst die Zaehlerreihe, dann der
Kopieren-Knopf in eine zweite Zeile (siehe `Ausgabekopf._zeilen_anordnen`) -
das Fenster zwingt so nie zum Abschneiden von Text.

Aussehen kommt vollstaendig aus stil.qss. Im Python steht keine Gestaltung.
"""

import logging

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
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

# Aufschrift der Zugriffsplakette. Sie nennt dauerhaft den geltenden Zustand,
# nie eine Aufforderung - man soll ablesen koennen, was gerade gilt.
ZUGRIFF_NUR_LESEN = "Nur lesen"
ZUGRIFF_SCHREIBEN = "Lesen und Schreiben"
ZUGRIFF_BEISPIELE = (ZUGRIFF_NUR_LESEN, ZUGRIFF_SCHREIBEN)

# Warteanzeige: wie viele Auftraege noch hinter dem laufenden stehen. Wartet
# keiner, bleibt das Feld leer - eine Null waere nur Laerm. Die Breite wird an
# einer zweistelligen Zahl gemessen und aendert sich nie.
WARTE_BEISPIELE = ("Warten 99",)

# Zeichen fuer die drei Rueckfrage-Ausnahmen (Einstellungen, Reiter
# Verhalten). Bleibt leer, solange keine der drei an ist - die Breite wird
# am laengsten moeglichen Text gemessen, damit nichts in der Reihe springt.
SICHERHEITSHINWEIS_BEISPIELE = ("⚠ Internet · Löschen · Installieren",)

# Zahl der aktiven Freigaben (Einstellungen, Reiter Freigaben). Die Breite
# wird an einer zweistelligen Zahl gemessen und aendert sich nie.
FREIGABEN_BEISPIELE = ("Freigaben 99",)

# Beispieltexte fuer die festen Breiten der Zahlenfelder rechts. Alle drei
# Zaehler werden an allen drei Texten gemessen und bekommen dieselbe Breite,
# damit sie als gleich grosse Reihe nebeneinander stehen.
AUFTRAG_BEISPIEL = "Auftrag 999.999"
SITZUNG_BEISPIEL = "Sitzung 999.999"
HEUTE_BEISPIEL = "Heute 999.999"
ZAEHLER_BEISPIELE = (AUFTRAG_BEISPIEL, SITZUNG_BEISPIEL, HEUTE_BEISPIEL)

# Beispieleintraege fuer die feste Breite des Modell-Auswahlfeldes. Es muss
# den laengsten Namen tragen, damit die Breite beim Wechseln nie springt.
MODELL_BEISPIELE = ("Standard (empfohlen)", "Opus (1 Mio Kontext)")


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
    in der Reihe nichts, wenn sich der Inhalt aendert. Passt die ganze Reihe
    nicht mehr nebeneinander, weichen stattdessen die hinteren Felder in eine
    zweite Zeile aus (siehe `Ausgabekopf._zeilen_anordnen`).

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


class Schrumpfwahl(QComboBox):
    """Auswahlfeld, das unter seine Wunschbreite darf. Wird es schmaler als
    der Modellname, kuerzt Qt den angezeigten Namen von selbst; die Liste
    dahinter bleibt vollstaendig."""

    def minimumSizeHint(self) -> QSize:
        masse = super().minimumSizeHint()
        schmal = self.fontMetrics().averageCharWidth() * 6
        return QSize(min(schmal, masse.width()), masse.height())


class Ausgabekopf(QWidget):
    """Die Kopfzeile ueber dem Ausgabefeld. Sie zeigt nur an; entschieden wird
    nichts hier. Das Fenster setzt die Werte, die Kopfzeile stellt sie dar."""

    kopieren_gedrueckt = Signal()
    # Der Wert des gewaehlten Modells, so wie Claude Code ihn fuehrt
    modell_gewaehlt = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ausgabekopf")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName("Kopfzeile der Ausgabe")

        self.nur_lesen = False
        self._status_text = "Verbinde …"
        self._modell_name = ""
        self._modell_eintraege: list[dict] = []
        self._modell_wert = ""
        # Wandern erst die Zaehlerreihe, dann der Kopieren-Knopf in die
        # zweite Zeile - siehe `_zeilen_anordnen`.
        self._zaehler_unten = False
        self._kopieren_unten = False

        hoch = QVBoxLayout(self)
        hoch.setContentsMargins(0, 0, 0, 0)
        hoch.setSpacing(0)

        erste_zeile = QWidget()
        erste_zeile.setObjectName("ausgabekopfzeile")
        quer = QHBoxLayout(erste_zeile)
        quer.setContentsMargins(0, 0, 0, 0)
        hoch.addWidget(erste_zeile)
        self._zeile1 = quer

        self._zeile2_leiste = QWidget()
        self._zeile2_leiste.setObjectName("ausgabekopfzeile")
        self._zeile2 = QHBoxLayout(self._zeile2_leiste)
        self._zeile2.setContentsMargins(0, 0, 0, 0)
        hoch.addWidget(self._zeile2_leiste)
        self._zeile2_leiste.setVisible(False)

        # Die Zeile beginnt unmittelbar mit der Zugriffsplakette. Taetigkeit
        # und bearbeitete Datei stehen seitdem gross im Aktivitaetsbalken
        # oben (core/fenster.py), nicht mehr hier.
        # Zugriffsplakette: nennt dauerhaft, was gerade gilt - "Nur lesen"
        # oder "Lesen und Schreiben". Die Farbe kommt aus stil.qss und haengt
        # am Attribut 'modus', damit der Zustand auch ohne Lesen auffaellt.
        self.zugriffsplakette = Schrumpffeld(ZUGRIFF_SCHREIBEN)
        self.zugriffsplakette.setObjectName("zugriffsplakette")
        self.zugriffsplakette.setProperty("modus", "schreiben")
        self.zugriffsplakette.setAccessibleName("Zugriffsrecht")
        self.zugriffsplakette.setAlignment(Qt.AlignCenter)
        self.zugriffsplakette.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.zugriffsplakette)

        # Kleines Zeichen, solange mindestens einer der drei Rueckfrage-
        # Schalter aus den Einstellungen (Internet, Loeschen im Projekt,
        # Installieren) an ist. Ab Werk sind alle drei aus, das Feld bleibt
        # dann leer.
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

        # Warteanzeige: die Zahl der Auftraege, die hinter dem laufenden
        # stehen. Sie ist leer, solange keiner wartet, damit die Zeile im
        # Normalfall ruhig bleibt. Geleert wird die Warteschlange mit F4.
        self.warteanzeige = Schrumpffeld("")
        self.warteanzeige.setObjectName("warteanzeige")
        self.warteanzeige.setAccessibleName("Warteschlange")
        self.warteanzeige.setAlignment(Qt.AlignCenter)
        self.warteanzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.warteanzeige)

        # Der freie Platz liegt in der Mitte: dadurch stehen Zugriff, Hinweis
        # und Warteanzeige links, Modellwahl und Zaehler rechts, ohne dass
        # eines der Felder waechst.
        quer.addStretch(1)

        # Modellwahl: anklickbar und mit der Tastatur bedienbar. Mit Tabulator
        # erreichbar, mit Pfeil auf und ab zu wechseln, mit Alt+Pfeil unten
        # aufzuklappen. Zu jedem Eintrag steht ein Hinweis dahinter, wofuer
        # sich das Modell eignet - als Kurzhinweis und fuer den Screenreader.
        # Sie steht vor den Zaehlern, damit die drei Zahlenfelder ununterbrochen
        # beieinander liegen.
        self.modellwahl = Schrumpfwahl()
        self.modellwahl.setObjectName("ausgabemodell")
        self.modellwahl.setAccessibleName("Modell wählen")
        self.modellwahl.setFocusPolicy(Qt.StrongFocus)
        self.modellwahl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.modellwahl.currentIndexChanged.connect(self._modell_gewechselt)
        quer.addWidget(self.modellwahl)

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

        self.kopieren = QPushButton("⧉  Kopieren")
        self.kopieren.setObjectName("kopieren")
        self.kopieren.setAccessibleName("Ganze Ausgabe kopieren")
        self.kopieren.setToolTip("Ganze Ausgabe kopieren (Strg+K)")
        self.kopieren.clicked.connect(self.kopieren_gedrueckt)
        quer.addWidget(self.kopieren)

    def resizeEvent(self, ereignis) -> None:
        super().resizeEvent(ereignis)
        self._zeilen_anordnen()

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

    def _wahl_masse_messen(self, beispiele) -> tuple[int, int]:
        """Misst das Auswahlfeld an gleichbleibenden Beispieleintraegen. Dafuer
        stehen kurz die Beispiele darin; danach wird es aus der gemerkten Liste
        neu gefuellt, damit Hinweise und Auswahl vollstaendig wiederkehren.
        Gemeldet wird dabei nichts."""
        self.modellwahl.blockSignals(True)
        try:
            self.modellwahl.clear()
            for wort in beispiele:
                self.modellwahl.addItem(wort)
            masse = self.modellwahl.sizeHint()
            self._wahl_fuellen()
        finally:
            self.modellwahl.blockSignals(False)
        return masse.width(), masse.height()

    def masse_festlegen(self) -> None:
        """Legt die Masse der Kopfzeile fest: jedes Feld genau eine Textzeile
        hoch und auf die Breite seiner gleichbleibenden Beispieltexte. Kein
        Inhalt kann die Groesse aendern - weder ein langer Dateiname noch eine
        grosse Zahl noch ein langer Modellname.

        Die Breite ist Wunsch und Obergrenze zugleich, keine Untergrenze: passt
        die ganze Reihe nicht mehr nebeneinander, weichen die hinteren Felder
        in eine zweite Zeile aus (siehe `_zeilen_anordnen`), statt dass ein
        Feld seinen Text kuerzt."""
        try:
            felder = (
                (self.zugriffsplakette, ZUGRIFF_BEISPIELE),
                (self.sicherheitshinweis, SICHERHEITSHINWEIS_BEISPIELE),
                (self.freigabenanzeige, FREIGABEN_BEISPIELE),
                (self.warteanzeige, WARTE_BEISPIELE),
                (self.tokenzaehler, ZAEHLER_BEISPIELE),
                (self.sitzungszaehler, ZAEHLER_BEISPIELE),
                (self.tageszaehler, ZAEHLER_BEISPIELE),
            )
            gemessen = []
            hoehe = 0
            for teil, beispiele in felder:
                # Ohne Grenze messen, sonst misst das Feld seine eigene
                # Kuerzung vom letzten Mal.
                teil.masse_zuruecksetzen()
                breite, teilhoehe = self._breite_messen(teil, beispiele)
                if breite <= 0 or teilhoehe <= 0:
                    return
                gemessen.append((teil, breite))
                hoehe = max(hoehe, teilhoehe)

            wahlbreite, wahlhoehe = self._wahl_masse_messen(MODELL_BEISPIELE)
            if wahlbreite <= 0 or wahlhoehe <= 0:
                return
            hoehe = max(hoehe, wahlhoehe)

            for teil, breite in gemessen:
                teil.wunschbreite_setzen(breite)
                teil.setFixedHeight(hoehe)

            # Das Auswahlfeld kuerzt seinen Text von sich aus; es braucht nur
            # die Obergrenze und darf unter sie fallen.
            self.modellwahl.setMinimumWidth(0)
            self.modellwahl.setMaximumWidth(wahlbreite)
            self.modellwahl.setFixedHeight(hoehe)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Maße der Kopfzeile nicht festgelegt: %s", fehler)
        self._zeilen_anordnen()

    def _zeilen_anordnen(self) -> None:
        """Kein Feld kuerzt mehr seinen Text (siehe `Schrumpffeld`); reicht die
        Breite trotzdem nicht fuer eine Zeile, weichen die hinteren Felder in
        eine zweite Zeile aus - zuerst die Zaehlerreihe, dann der Kopieren-
        Knopf. Das Modellfeld kuerzt seinen Namen weiterhin selbst (siehe
        `Schrumpfwahl`) und bleibt darum immer in der ersten Zeile."""
        try:
            abstand = max(self._zeile1.spacing(), 0)
            feste = (
                self.zugriffsplakette, self.sicherheitshinweis,
                self.freigabenanzeige, self.warteanzeige, self.modellwahl,
            )
            breite_fest = sum(feld.sizeHint().width() for feld in feste)
            breite_fest += abstand * len(feste)
            breite_zaehler = self.zaehlerreihe.sizeHint().width() + abstand
            breite_kopieren = self.kopieren.sizeHint().width() + abstand
            verfuegbar = self.width()

            zaehler_unten = breite_fest + breite_zaehler + breite_kopieren > verfuegbar
            kopieren_unten = zaehler_unten and breite_fest + breite_kopieren > verfuegbar

            if zaehler_unten != self._zaehler_unten:
                self._feld_versetzen(self.zaehlerreihe, zaehler_unten)
                self._zaehler_unten = zaehler_unten
            if kopieren_unten != self._kopieren_unten:
                self._feld_versetzen(self.kopieren, kopieren_unten)
                self._kopieren_unten = kopieren_unten
            self._zeile2_leiste.setVisible(self._zaehler_unten or self._kopieren_unten)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kopfzeile nicht in Zeilen aufgeteilt: %s", fehler)

    def _feld_versetzen(self, feld: QWidget, nach_unten: bool) -> None:
        """Verschiebt ein Feld zwischen erster und zweiter Zeile, ohne seinen
        Zustand zu verlieren - beide Zeilen sind Layouts desselben Widgets."""
        if nach_unten:
            self._zeile1.removeWidget(feld)
            self._zeile2.addWidget(feld)
        else:
            self._zeile2.removeWidget(feld)
            self._zeile1.addWidget(feld)

    # -- Warteschlange ------------------------------------------------------

    def warteschlange_zeigen(self, anzahl: int) -> None:
        """Zeigt, wie viele Auftraege hinter dem laufenden warten. Bei null
        bleibt das Feld leer; der volle Wortlaut steht als Beschreibung und
        Kurzhinweis dahinter."""
        try:
            anzahl = max(0, int(anzahl))
            self.warteanzeige.setText(f"Warten {anzahl}" if anzahl else "")
            if anzahl == 0:
                satz = "Warteschlange leer, es wartet kein Auftrag."
            elif anzahl == 1:
                satz = "Ein Auftrag wartet. Warteschlange leeren mit F4."
            else:
                satz = f"{anzahl} Aufträge warten. Warteschlange leeren mit F4."
            self.warteanzeige.setToolTip(satz)
            self.warteanzeige.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Warteanzeige nicht gesetzt: %s", fehler)

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
        """Merkt den Nur-Lesen-Zustand, beschriftet und faerbt die
        Zugriffsplakette und schreibt die Meldung neu."""
        self.nur_lesen = bool(an)
        try:
            text = ZUGRIFF_NUR_LESEN if self.nur_lesen else ZUGRIFF_SCHREIBEN
            self.zugriffsplakette.setText(text)
            self.zugriffsplakette.setProperty(
                "modus", "nur_lesen" if self.nur_lesen else "schreiben"
            )
            hinweis = (
                "Nur lesen: es wird nichts geschrieben und nichts gelöscht."
                if self.nur_lesen
                else "Lesen und Schreiben erlaubt."
            )
            self.zugriffsplakette.setAccessibleDescription(hinweis)
            self.zugriffsplakette.setToolTip(f"{hinweis}  (F10)")
            self.zugriffsplakette.style().polish(self.zugriffsplakette)
            self.zugriffsplakette.update()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zugriffsplakette nicht gesetzt: %s", fehler)
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
        try:
            teile = []
            if internet_ohne_rueckfrage:
                teile.append("Internet")
            if loeschen_ohne_rueckfrage:
                teile.append("Löschen")
            if installieren_ohne_rueckfrage:
                teile.append("Installieren")
            if teile:
                self.sicherheitshinweis.setText("⚠ " + " · ".join(teile))
                satz = "Ohne Rückfrage erlaubt: " + " und ".join(teile) + "."
            else:
                self.sicherheitshinweis.setText("")
                satz = "Keine Rückfrage-Ausnahme aktiv."
            self.sicherheitshinweis.setToolTip(satz)
            self.sicherheitshinweis.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Sicherheitshinweis nicht gesetzt: %s", fehler)

    def freigaben_zeigen(self, namen: list) -> None:
        """Zeigt, wie viele Ordner ausserhalb des Projekts ohne Rueckfrage
        freigegeben sind (Einstellungen, Reiter Freigaben). Bei keiner
        Freigabe bleibt das Feld leer."""
        try:
            anzahl = len(namen)
            self.freigabenanzeige.setText(f"Freigaben {anzahl}" if anzahl else "")
            if anzahl == 0:
                satz = "Keine Freigabe aktiv."
            else:
                satz = f"{anzahl} Freigaben aktiv: " + ", ".join(namen) + "."
            self.freigabenanzeige.setToolTip(satz)
            self.freigabenanzeige.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Freigabenanzeige nicht gesetzt: %s", fehler)

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

    # -- Modellwahl ---------------------------------------------------------

    def modelle_setzen(self, eintraege: list, gewaehlt: str = "") -> None:
        """Fuellt das Auswahlfeld mit den Modellen, die Claude Code anbietet.
        Jeder Eintrag ist ein Woerterbuch mit 'wert', 'name' und 'hinweis'.
        Das Fuellen selbst loest keine Meldung aus - gemeldet wird nur, was
        der Nutzer selbst waehlt."""
        if not eintraege:
            return
        self._modell_eintraege = list(eintraege)
        self._modell_wert = gewaehlt or self._modell_wert
        self.modellwahl.blockSignals(True)
        try:
            self._wahl_fuellen()
        finally:
            self.modellwahl.blockSignals(False)
        self._modell_zeichnen()

    def _wahl_fuellen(self) -> None:
        """Schreibt die gemerkte Liste ins Auswahlfeld, samt Hinweisen und der
        zuletzt gueltigen Auswahl. Ruft niemand von aussen; die Meldungen sind
        beim Aufruf bereits abgeschaltet."""
        try:
            self.modellwahl.clear()
            for nummer, eintrag in enumerate(self._modell_eintraege):
                name = eintrag.get("name") or eintrag.get("wert", "")
                hinweis = eintrag.get("hinweis", "")
                self.modellwahl.addItem(name, eintrag.get("wert", ""))
                # Der Hinweis haengt am Eintrag: sichtbar als Kurzhinweis,
                # hoerbar ueber die Beschreibung im Screenreader.
                self.modellwahl.setItemData(nummer, hinweis, Qt.ToolTipRole)
                self.modellwahl.setItemData(
                    nummer, f"{name}. {hinweis}", Qt.AccessibleDescriptionRole
                )
            stelle = (
                self.modellwahl.findData(self._modell_wert)
                if self._modell_wert else -1
            )
            self.modellwahl.setCurrentIndex(max(0, stelle))
        except Exception as fehler:  # noqa: BLE001
            log.exception("Modellliste nicht gesetzt: %s", fehler)

    def _modell_gewechselt(self, stelle: int) -> None:
        """Der Nutzer hat ein anderes Modell gewaehlt; weitergereicht wird der
        Wert, den Claude Code fuehrt. Was daraufhin geschieht, entscheidet das
        Fenster, nicht die Kopfzeile."""
        try:
            wert = self.modellwahl.itemData(stelle)
            if not wert:
                return
            self._modell_wert = str(wert)
            self._modell_zeichnen()
            self.modell_gewaehlt.emit(self._modell_wert)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Modellwechsel nicht gemeldet: %s", fehler)

    def modell_zeigen(self, modell: str) -> None:
        """Merkt den aufgeloesten Modellnamen, den Claude Code wirklich
        benutzt. Er steht im Kurzhinweis und in der Beschreibung des Feldes."""
        self._modell_name = modell or ""
        self._modell_zeichnen()

    def _modell_zeichnen(self) -> None:
        """Legt Kurzhinweis und Beschreibung ans ganze Auswahlfeld: welches
        Modell laeuft, wofuer es taugt und wie das Feld bedient wird."""
        try:
            hinweis = self.modellwahl.currentData(Qt.ToolTipRole) or ""
            laeuft = f"Modell {self._modell_name}" if self._modell_name else "Modell"
            voll = f"{laeuft}. {hinweis}".strip()
            self.modellwahl.setToolTip(voll)
            self.modellwahl.setAccessibleDescription(
                f"{voll} Mit Pfeil auf und ab ein anderes Modell wählen."
            )
        except Exception as fehler:  # noqa: BLE001
            log.exception("Modellanzeige nicht gesetzt: %s", fehler)

    # -- Tokenverbrauch -----------------------------------------------------

    def verbrauch_zeigen(self, verbrauch: dict) -> None:
        """Zeigt links die Token dieses Auftrags, rechts die der ganzen
        Sitzung. Wird nicht angesagt, nur angezeigt."""
        # Sichtbar sind nur frische Eingabe plus Ausgabe. Die Cache-Werte
        # wiederholen bei jedem Aufruf fast die ganze Unterhaltung und wuerden
        # die Zahl unbrauchbar aufblaehen; sie stehen nur im Kurzhinweis.
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

        if "heute" in verbrauch:
            self.tag_zeigen(verbrauch.get("heute", 0))

    def tag_zeigen(self, heute: int) -> None:
        """Zeigt die Tagessumme rechts neben dem Sitzungszaehler. Sie zaehlt
        ueber alle Sitzungen und Neustarts eines Kalendertages hinweg."""
        try:
            heute = int(heute)
            self.tageszaehler.setText(f"Heute {zahl_kurz(heute)}")
            satz = (
                f"Heute {zahl_lang(heute)} Token ohne Cache, über alle "
                "Sitzungen des Tages zusammen"
            )
            self.tageszaehler.setToolTip(satz)
            self.tageszaehler.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Tageszähler nicht gesetzt: %s", fehler)
