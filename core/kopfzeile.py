"""
CWB - Code Workbench
Kopfzeile des Ausgabefelds.

Eine einzige Zeile ueber dem Ausgabefeld traegt alles, was zum Stand der
Arbeit gehoert: das Zeichen fuer aktive Rueckfrage-Ausnahmen (Internet,
Loeschen im Projekt, Installieren), die Zahl der aktiven Freigaben
(Einstellungen, Reiter Freigaben), die Warteanzeige mit der Zahl der
vorgemerkten Auftraege (leer, solange keiner wartet), die Eingangsanzeige mit
der Zahl der Auftragsdateien im Eingangsordner, die auf ein anderes Projekt
warten (Block 63, ebenfalls leer im Regelfall), die drei Tokenzaehler
und, ganz rechts, die kleine Schaltflaeche zum Kopieren. Die Zaehler stehen
unmittelbar nebeneinander in der Reihenfolge "Auftrag", "Sitzung", "Heute" -
gleiche Breite, gleiche Gestalt, ohne Zwischenraum. Ein eigenes Feld fuer die
Statusmeldung gibt es nicht mehr; die Meldung wird gesprochen und steht als
Beschreibung an der Kopfzeile selbst.

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

Reicht selbst die kleinste Schrift nicht mehr fuer die volle Beschriftung,
wechselt die Kopfzeile in den Schmal-Modus (resizeEvent, `_modus_anwenden`):
kuerzere Texte wie "Brücke" statt "Brücke an" oder nackte Zahlen statt
"Auftrag 999.999". So erzwingt die Kopfzeile nie eine Mindestbreite - anders
als vor Block 49, als die Beispieltexte zugleich die Untergrenze jedes Feldes
waren (Qt-Labels ohne Zeilenumbruch melden ihre volle Textbreite auch als
`minimumSizeHint`, `setMinimumWidth(0)` aendert daran nichts).

Die Schaltflaeche zum Kopieren steht nicht mehr hier, sondern in einer eigenen
schmalen Zeile direkt ueber dem Ausgabefeld (core/fenster.py) - dort gehoert
sie hin, nicht in die Kopfzeile mit den Zaehlern.

Aussehen kommt vollstaendig aus stil.qss. Im Python steht keine Gestaltung.
"""

import logging

from PySide6.QtCore import QSize, Qt, Signal
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
# Bei wenig Platz (Ausgabekopf.resizeEvent) steht nur noch das Zeichen da,
# der volle Wortlaut bleibt als Kurzhinweis und Vorlesetext erhalten.
SICHERHEITSHINWEIS_BEISPIELE = ("⚠ Internet · Löschen · Installieren",)
SICHERHEITSHINWEIS_KURZ_BEISPIELE = ("⚠",)

# Zahl der aktiven Freigaben (Einstellungen, Reiter Freigaben). Die Breite
# wird an einer zweistelligen Zahl gemessen und aendert sich nie.
FREIGABEN_BEISPIELE = ("Freigaben 99",)
FREIGABEN_KURZ_BEISPIELE = ("99",)

# Statushinweis fuer den Schalter "Bruecke" (Einstellungen, Reiter Verhalten,
# Umschalt+F8, core/fenster.py, Vorhaben "Bruecke" Stufe B3). Bleibt leer,
# solange die Bruecke aus ist - ab Werk der Fall.
BRUECKE_BEISPIELE = ("Brücke an",)
BRUECKE_KURZ_BEISPIELE = ("Brücke",)

# "Such-Effizienz" (Block C10, umbenannt von "Suche gespart"): Grundwert vom
# 21.09.2026 geteilt durch die aktuellen Lesezugriffe (Read, Grep, Glob,
# lesende Bash-Befehle) vor der ersten Dateiänderung, mal 100 - keine
# Token-Ersparnis. 100 % ist der Normalwert, mehr heißt gezielter gesucht,
# weniger heißt umständlicher. Unter 5 Aufträgen seit Block C6 steht ein
# Gedankenstrich statt einer Zahl (siehe such_effizienz_zeigen); die Breite
# wird an beiden Beispielen gemessen.
SUCH_EFFIZIENZ_BEISPIELE = ("Such-Effizienz –", "Such-Effizienz 999 %")
SUCH_EFFIZIENZ_KURZ_BEISPIELE = ("–", "999 %")

# Warteanzeige kurz: nur die Zahl, ohne das Wort "Warten".
WARTE_KURZ_BEISPIELE = ("99",)

# Modellanzeige (Block 70, Teil B): der Kurzname des tatsaechlich verbundenen
# Modells (core/modelle.py, anzeige_name) - dauerhaft sichtbar, nie leer, im
# Unterschied zu den anderen Feldern hier. Breite an allen vier moeglichen
# Namen gemessen, lang und schmal.
MODELL_BEISPIELE = ("Sonnet 5", "Opus 5", "Haiku 4.5", "Fable 5.1")
MODELL_KURZ_BEISPIELE = ("Sonnet", "Opus", "Haiku", "Fable")

# Eingangsanzeige (Block 63): wie viele Auftragsdateien im Eingangsordner auf
# ein ANDERES, nicht offenes Projekt warten (core/eingangsordner.py,
# fremde_projekte) - leer, solange keine solche Datei da liegt. Nur die
# Gesamtzahl ist fest breit messbar (die Liste der Projektnamen waere
# beliebig lang und wuerde wieder eine Mindestbreite erzwingen wie vor
# Block 49); die Aufschluesselung je Projekt steht im Kurzhinweis/Vorlesetext.
EINGANG_BEISPIELE = ("Eingang 99",)
EINGANG_KURZ_BEISPIELE = ("99",)

# Beispieltexte fuer die festen Breiten der Zahlenfelder rechts. Alle drei
# Zaehler werden an allen drei Texten gemessen und bekommen dieselbe Breite,
# damit sie als gleich grosse Reihe nebeneinander stehen.
AUFTRAG_BEISPIEL = "Auftrag 999.999"
SITZUNG_BEISPIEL = "Sitzung 999.999"
HEUTE_BEISPIEL = "Heute 999.999"
ZAEHLER_BEISPIELE = (AUFTRAG_BEISPIEL, SITZUNG_BEISPIEL, HEUTE_BEISPIEL)
# Kurzform bei wenig Platz: nur die Zahl, ohne "Auftrag"/"Sitzung"/"Heute" -
# die Reihenfolge und der Kurzhinweis sagen weiterhin, welche Zahl welche ist.
ZAEHLER_KURZ_BEISPIELE = ("999.999",)


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

        # Schmal-Modus: bei wenig Breite weichen die Felder auf kuerzere
        # Texte aus (z. B. "Brücke" statt "Brücke an", Zaehler ohne Wort),
        # damit die Zeile nie eine Mindestbreite erzwingt - siehe
        # resizeEvent und _modus_anwenden. Die Rohwerte stehen in eigenen
        # Feldern, damit beim Wechsel neu gezeichnet werden kann, ohne dass
        # das Fenster den Wert erneut liefern muss.
        self._schmal = False
        self._sicherheit_internet = False
        self._sicherheit_loeschen = False
        self._sicherheit_installieren = False
        self._freigaben_namen: list = []
        self._bruecke_an = False
        self._such_prozent: int | None = None
        self._modell_lang = ""
        self._modell_kurz = ""
        self._warte_anzahl = 0
        self._eingang_fremde: dict = {}
        self._verbrauch: dict = {}
        self._heute = 0
        # Je Feld die bei masse_festlegen gemessene (Breite lang, Breite
        # kurz). Bestimmt, ab wann resizeEvent in den Schmal-Modus wechselt.
        self._breiten: dict = {}
        self._breite_lang_benoetigt = 0
        self._hoehe = 0

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

        # Statushinweis, solange die Bruecke zu claude.ai im Browser an ist
        # (Einstellungen, Reiter Verhalten, Umschalt+F8). Aus ist der
        # Normalfall, dann bleibt das Feld leer.
        self.bruecke_anzeige = Schrumpffeld("")
        self.bruecke_anzeige.setObjectName("brueckenanzeige")
        self.bruecke_anzeige.setAccessibleName("Brücken-Status")
        self.bruecke_anzeige.setAlignment(Qt.AlignCenter)
        self.bruecke_anzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.bruecke_anzeige)

        # "Such-Effizienz" (Block C10): zwischen Freigaben-Zahl und
        # Tokenzaehler, wie in der Kopfzeile vereinbart. Nicht gesprochen -
        # F2 "Wo stehen wir" nennt den Wert stattdessen als Satz.
        self.such_effizienz = Schrumpffeld("")
        self.such_effizienz.setObjectName("such_effizienz")
        self.such_effizienz.setAccessibleName("Such-Effizienz")
        self.such_effizienz.setAlignment(Qt.AlignCenter)
        self.such_effizienz.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.such_effizienz)

        # Modellanzeige (Block 70, Teil B): der Kurzname des tatsaechlich
        # verbundenen Modells - anders als die uebrigen Felder hier dauerhaft
        # sichtbar, nie leer. core/fenster.py setzt den Wert ueber
        # modell_zeigen(), sobald die Sitzung (neu) verbunden ist.
        self.modellanzeige = Schrumpffeld("")
        self.modellanzeige.setObjectName("modellanzeige")
        self.modellanzeige.setAccessibleName("Modell")
        self.modellanzeige.setAlignment(Qt.AlignCenter)
        self.modellanzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        quer.addWidget(self.modellanzeige)

        # Warteanzeige: die Zahl der Auftraege, die hinter dem laufenden
        # stehen. Sie ist leer, solange keiner wartet, damit die Zeile im
        # Normalfall ruhig bleibt. Geleert wird die Warteschlange mit F4.
        self.warteanzeige = KlickbaresFeld("")
        self.warteanzeige.setObjectName("warteanzeige")
        self.warteanzeige.setAccessibleName("Warteschlange")
        self.warteanzeige.setAlignment(Qt.AlignCenter)
        self.warteanzeige.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # Antippen/Anklicken oeffnet "Warteschlange verwalten" (Block 60) -
        # der Zeigerwechsel zeigt sehenden Nutzern, dass die Zahl klickbar
        # ist; das Signal `geklickt` verbindet fenster.py.
        self.warteanzeige.setCursor(Qt.PointingHandCursor)
        # Verborgen, solange keiner wartet: die feste Breite aus
        # masse_festlegen wuerde sonst als leere Box zwischen Freigaben- und
        # Zaehlerreihe stehen bleiben.
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
        hoch, auf die Breite seiner gleichbleibenden Beispieltexte gemessen -
        einmal lang (volle Beschriftung) und einmal kurz (siehe
        _modus_anwenden). Kein Inhalt kann die Groesse aendern - weder eine
        grosse Zahl noch ein langer Freigaben-Zaehler.

        Die Breite ist Wunsch und Obergrenze des jeweils geltenden Modus,
        keine Untergrenze: reicht die Fensterbreite fuer die lange Fassung
        nicht, wechselt resizeEvent in den Schmal-Modus mit kuerzeren
        Texten, statt eine Mindestbreite zu erzwingen. Die Zeile bleibt
        einzeilig; zusaetzlich besorgt die Skalierung des ganzen Stilblatts
        (core/grundlagen.py, `stil_anwenden`) das Schrumpfen von Schrift und
        Abstaenden."""
        try:
            felder = (
                ("sicherheitshinweis", self.sicherheitshinweis,
                 SICHERHEITSHINWEIS_BEISPIELE, SICHERHEITSHINWEIS_KURZ_BEISPIELE),
                ("freigabenanzeige", self.freigabenanzeige,
                 FREIGABEN_BEISPIELE, FREIGABEN_KURZ_BEISPIELE),
                ("bruecke_anzeige", self.bruecke_anzeige,
                 BRUECKE_BEISPIELE, BRUECKE_KURZ_BEISPIELE),
                ("such_effizienz", self.such_effizienz,
                 SUCH_EFFIZIENZ_BEISPIELE, SUCH_EFFIZIENZ_KURZ_BEISPIELE),
                ("modellanzeige", self.modellanzeige,
                 MODELL_BEISPIELE, MODELL_KURZ_BEISPIELE),
                ("warteanzeige", self.warteanzeige,
                 WARTE_BEISPIELE, WARTE_KURZ_BEISPIELE),
                ("eingangsanzeige", self.eingangsanzeige,
                 EINGANG_BEISPIELE, EINGANG_KURZ_BEISPIELE),
                ("tokenzaehler", self.tokenzaehler,
                 ZAEHLER_BEISPIELE, ZAEHLER_KURZ_BEISPIELE),
                ("sitzungszaehler", self.sitzungszaehler,
                 ZAEHLER_BEISPIELE, ZAEHLER_KURZ_BEISPIELE),
                ("tageszaehler", self.tageszaehler,
                 ZAEHLER_BEISPIELE, ZAEHLER_KURZ_BEISPIELE),
            )
            breiten = {}
            hoehe = 0
            for name, teil, lang_beispiele, kurz_beispiele in felder:
                # Ohne Grenze messen, sonst misst das Feld seine eigene
                # Kuerzung vom letzten Mal.
                teil.masse_zuruecksetzen()
                breite_lang, teilhoehe = self._breite_messen(teil, lang_beispiele)
                breite_kurz, teilhoehe_kurz = self._breite_messen(teil, kurz_beispiele)
                if breite_lang <= 0 or teilhoehe <= 0 or breite_kurz <= 0:
                    return
                breiten[name] = (breite_lang, breite_kurz)
                hoehe = max(hoehe, teilhoehe, teilhoehe_kurz)

            self._breiten = breiten
            self._hoehe = hoehe
            # Noetige Breite in der langen Fassung: die vier immer
            # sichtbaren linken Felder, die drei Zaehler und die Abstaende
            # dazwischen (die Warteanzeige bleibt aussen vor, sie ist im
            # Regelfall verborgen und traegt dann nichts zur Breite bei).
            dauerhaft = ("sicherheitshinweis", "freigabenanzeige", "bruecke_anzeige",
                         "such_effizienz", "modellanzeige", "tokenzaehler",
                         "sitzungszaehler", "tageszaehler")
            abstand = self.layout().spacing() if self.layout() else 4
            self._breite_lang_benoetigt = (
                sum(breiten[name][0] for name in dauerhaft)
                + abstand * (len(dauerhaft) - 1)
            )
            self._modus_anwenden()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Maße der Kopfzeile nicht festgelegt: %s", fehler)

    def _modus_anwenden(self) -> None:
        """Setzt an jedem Feld die Wunschbreite des geltenden Modus (lang
        oder schmal) und zeichnet alle Anzeigen mit dem passenden Wortlaut
        neu. Aufgerufen nach jedem Messen und bei jedem Moduswechsel."""
        if not self._breiten:
            return
        for name, (breite_lang, breite_kurz) in self._breiten.items():
            teil = getattr(self, name)
            teil.wunschbreite_setzen(breite_kurz if self._schmal else breite_lang)
            teil.setFixedHeight(self._hoehe)
        self.setFixedHeight(self._hoehe)
        self._sicherheitshinweis_zeichnen()
        self._freigaben_zeichnen()
        self._bruecke_zeichnen()
        self._such_effizienz_zeichnen()
        self._modell_zeichnen()
        self._warteschlange_zeichnen()
        self._eingang_fremde_zeichnen()
        self._verbrauch_zeichnen()
        self._tag_zeichnen()

    def resizeEvent(self, ereignis) -> None:
        super().resizeEvent(ereignis)
        if not self._breite_lang_benoetigt:
            return
        schmal = self.width() < self._breite_lang_benoetigt
        if schmal != self._schmal:
            self._schmal = schmal
            self._modus_anwenden()

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
            text = str(anzahl) if self._schmal else f"Warten {anzahl}"
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
            text = str(gesamt) if self._schmal else f"Eingang {gesamt}"
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
                text = "⚠" if self._schmal else "⚠ " + " · ".join(teile)
                self.sicherheitshinweis.setText(text)
                satz = "Ohne Rückfrage erlaubt: " + " und ".join(teile) + "."
            else:
                self.sicherheitshinweis.setText("")
                satz = "Keine Rückfrage-Ausnahme aktiv."
            self.sicherheitshinweis.setToolTip(satz)
            self.sicherheitshinweis.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Sicherheitshinweis nicht gesetzt: %s", fehler)

    def bruecke_zeigen(self, an: bool) -> None:
        """Zeigt "Brücke an", solange der Schalter an ist (Einstellungen,
        Reiter Verhalten, Umschalt+F8). Aus bleibt das Feld leer - das ist
        der Normalfall."""
        self._bruecke_an = bool(an)
        self._bruecke_zeichnen()

    def _bruecke_zeichnen(self) -> None:
        try:
            an = self._bruecke_an
            text = ("Brücke" if self._schmal else "Brücke an") if an else ""
            self.bruecke_anzeige.setText(text)
            satz = "Brücke an: Claude im Browser kann Aufträge schicken." if an \
                else "Brücke aus."
            self.bruecke_anzeige.setToolTip(satz)
            self.bruecke_anzeige.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Brücken-Statushinweis nicht gesetzt: %s", fehler)

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
            text = (str(anzahl) if self._schmal else f"Freigaben {anzahl}") if anzahl else ""
            self.freigabenanzeige.setText(text)
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
            if prozent is None:
                self.such_effizienz.setText("–" if self._schmal else "Such-Effizienz –")
                satz = ("Such-Effizienz: noch nicht ermittelbar, weniger als "
                        "5 Aufträge seit Block C6.")
            else:
                text = f"{prozent} %" if self._schmal else f"Such-Effizienz {prozent} %"
                self.such_effizienz.setText(text)
                satz = (
                    f"Such-Effizienz {prozent} Prozent. 100 Prozent ist der "
                    "Normalwert vom 21.09.2026, mehr heißt gezielter gesucht, "
                    "weniger umständlicher. Gemessen werden Lesezugriffe "
                    "(Read, Grep, Glob, lesende Bash-Befehle) vor der ersten "
                    "Dateiänderung - keine Token-Ersparnis."
                )
            self.such_effizienz.setToolTip(satz)
            self.such_effizienz.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Such-Effizienz nicht gesetzt: %s", fehler)

    def modell_zeigen(self, lang: str, kurz: str) -> None:
        """Zeigt den Kurznamen des tatsaechlich verbundenen Modells (Block 70,
        Teil B) - anders als die uebrigen Felder hier dauerhaft, nie leer.
        `lang`/`kurz` kommen fertig aus core/modelle.py (`anzeige_name`);
        diese Klasse entscheidet nichts, sie zeigt nur an."""
        self._modell_lang = lang
        self._modell_kurz = kurz
        self._modell_zeichnen()

    def _modell_zeichnen(self) -> None:
        try:
            text = self._modell_kurz if self._schmal else self._modell_lang
            self.modellanzeige.setText(text)
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
            # Kurzhinweis. Bei wenig Platz faellt zusaetzlich das Wort weg -
            # Reihenfolge und Kurzhinweis sagen weiterhin, welche Zahl welche
            # ist ("Zähler ohne Wörter").
            sitzung = verbrauch.get("sitzung", 0)
            letzter = verbrauch.get("gesamt", 0)
            if self._schmal:
                self.tokenzaehler.setText(zahl_kurz(letzter))
                self.sitzungszaehler.setText(zahl_kurz(sitzung))
            else:
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
            text = zahl_kurz(heute) if self._schmal else f"Heute {zahl_kurz(heute)}"
            self.tageszaehler.setText(text)
            satz = (
                f"Heute {zahl_lang(heute)} Token ohne Cache, über alle "
                "Sitzungen des Tages zusammen"
            )
            self.tageszaehler.setToolTip(satz)
            self.tageszaehler.setAccessibleDescription(satz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Tageszähler nicht gesetzt: %s", fehler)
