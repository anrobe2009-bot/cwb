"""
CWB - Code Workbench
Kopfzeile des Ausgabefelds.

Eine einzige Zeile ueber dem Ausgabefeld traegt alles, was zum Stand der
Arbeit gehoert: das Zeichen fuer aktive Rueckfrage-Ausnahmen (Internet,
Loeschen im Projekt, Installieren), die Zahl der aktiven Freigaben
(Einstellungen, Reiter Freigaben), die Warteanzeige mit der Zahl der
vorgemerkten Auftraege (leer, solange keiner wartet), die drei Tokenzaehler
und, ganz rechts, die kleine Schaltflaeche zum Kopieren. Die Zaehler stehen
unmittelbar nebeneinander in der Reihenfolge "Auftrag", "Sitzung", "Heute" -
gleiche Breite, gleiche Gestalt, ohne Zwischenraum. Ein eigenes Feld fuer die
Statusmeldung gibt es nicht mehr; die Meldung wird gesprochen und steht als
Beschreibung an der Kopfzeile selbst.

Das geltende Schreibrecht ("Nur lesen" / "Lesen und Schreiben") steht nicht
hier, sondern einzig an der Kachel ZUGRIFF_KENNUNG (F10, core/fenster.py) -
eine zweite Anzeige derselben Information waere hier nur Redundanz. Die
Modellwahl steht ebenfalls nicht mehr hier, sondern in den Einstellungen
(F12, Reiter Verhalten, core/einstellungen.py).

Taetigkeit und bearbeitete Datei stehen nicht mehr hier, sondern gross und
fett direkt im Aktivitaetsbalken oben (core/fenster.py, Aktivitaetsbalken).

Alle Felder werden an gleichbleibenden Beispieltexten gemessen und halten
dieses Mass, solange das Fenster breit genug ist: kein Inhalt kann die Groesse
aendern, darum rutscht das Ausgabefeld darunter nie auf und ab und in der Reihe
verschiebt sich nichts. Die Zeile bleibt einzeilig; die Skalierung des ganzen
Stilblatts (core/grundlagen.py, `stil_anwenden`) haelt Schrift und Abstaende
schmaler Fenster klein genug, dass nichts umbricht.

Die Schaltflaeche zum Kopieren steht nicht mehr hier, sondern in einer eigenen
schmalen Zeile direkt ueber dem Ausgabefeld (core/fenster.py) - dort gehoert
sie hin, nicht in die Kopfzeile mit den Zaehlern.

Aussehen kommt vollstaendig aus stil.qss. Im Python steht keine Gestaltung.
"""

import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
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

        quer = QHBoxLayout(self)
        quer.setContentsMargins(0, 0, 0, 0)
        quer.setSpacing(4)

        # Die Zeile beginnt unmittelbar mit dem Sicherheitshinweis. Taetigkeit
        # und bearbeitete Datei stehen gross im Aktivitaetsbalken oben
        # (core/fenster.py), das Schreibrecht einzig an der Kachel
        # ZUGRIFF_KENNUNG (F10) - beides steht nicht mehr hier.
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
        # Verborgen, solange keiner wartet: die feste Breite aus
        # masse_festlegen wuerde sonst als leere Box zwischen Freigaben- und
        # Zaehlerreihe stehen bleiben.
        self.warteanzeige.setVisible(False)
        quer.addWidget(self.warteanzeige)

        # Der freie Platz liegt in der Mitte: dadurch stehen Hinweis, Freigaben
        # und Warteanzeige links, Zaehler und Kopieren-Knopf rechts, ohne dass
        # eines der Felder waechst.
        quer.addStretch(1)

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
        hoch und auf die Breite seiner gleichbleibenden Beispieltexte. Kein
        Inhalt kann die Groesse aendern - weder eine grosse Zahl noch ein
        langer Freigaben-Zaehler.

        Die Breite ist Wunsch und Obergrenze zugleich, keine Untergrenze. Die
        Zeile bleibt einzeilig; das Schrumpfen bei schmalem Fenster besorgt
        die Skalierung des ganzen Stilblatts (core/grundlagen.py,
        `stil_anwenden`), nicht ein Umbruch hier."""
        try:
            felder = (
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

            for teil, breite in gemessen:
                teil.wunschbreite_setzen(breite)
                teil.setFixedHeight(hoehe)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Maße der Kopfzeile nicht festgelegt: %s", fehler)

    # -- Warteschlange ------------------------------------------------------

    def warteschlange_zeigen(self, anzahl: int) -> None:
        """Zeigt, wie viele Auftraege hinter dem laufenden warten. Bei null
        bleibt das Feld leer; der volle Wortlaut steht als Beschreibung und
        Kurzhinweis dahinter."""
        try:
            anzahl = max(0, int(anzahl))
            self.warteanzeige.setText(f"Warten {anzahl}" if anzahl else "")
            self.warteanzeige.setVisible(anzahl > 0)
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
