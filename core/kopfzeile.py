"""
CWB - Code Workbench
Kopfzeile des Ausgabefelds.

Eine einzige Zeile ueber dem Ausgabefeld traegt alles, was zum Stand der
Arbeit gehoert: das Wort "Ausgabe", die farbige Taetigkeitsplakette, den Namen
der bearbeiteten Datei, die Modellwahl, die drei Tokenzaehler und die
Schaltflaeche zum Kopieren. Die Zaehler stehen unmittelbar nebeneinander in
der Reihenfolge "Auftrag", "Sitzung", "Heute" - gleiche Breite, gleiche
Gestalt, ohne Zwischenraum. Ein eigenes Feld
fuer die Statusmeldung gibt es nicht mehr; die Meldung wird gesprochen und
steht als Beschreibung an der Kopfzeile selbst.

Das Modellfeld ist keine feste Anzeige, sondern ein Auswahlfeld: mit Tabulator
erreichbar, mit den Pfeiltasten zu wechseln. Welche Modelle darin stehen, sagt
Claude Code selbst - die Kopfzeile stellt nur dar, was ihr gereicht wird.

Alle Felder haben feste Masse, gemessen an gleichbleibenden Beispieltexten.
Kein Inhalt kann die Groesse aendern, darum rutscht das Ausgabefeld darunter
nie auf und ab und in der Reihe verschiebt sich nichts.

Aussehen kommt vollstaendig aus stil.qss. Im Python steht keine Gestaltung.
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

try:
    from .grundlagen import LOG_DATEI  # noqa: F401  (richtet das Log ein)
except ImportError:
    from grundlagen import LOG_DATEI  # noqa: F401

log = logging.getLogger("cwb.kopfzeile")

# Aufschrift der Taetigkeitsplakette, solange noch nichts getan wurde
KEINE_TAETIGKEIT = "—"

# Taetigkeit je Zustand, falls die Sitzung keine eigene mitschickt. In der
# Plakette steht immer nur das Tun, nie ein Dateiname oder Pfad.
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

# Beispielwoerter, aus denen die feste Breite der Plakette gemessen wird.
# Sie muss das laengste Wort tragen, damit die Breite nie springt.
TAETIGKEIT_BEISPIELE = ("führt aus", "abgebrochen", "verbindet")

# Beispielnamen fuer die feste Breite des Dateifeldes daneben. Das Feld zeigt
# den Namen ungekuerzt, also muss es die langen Namen des Projekts tragen.
DATEI_BEISPIELE = ("ablagewaechter.py", "einstellungen.json", "projektwahl.py")

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

        quer = QHBoxLayout(self)
        quer.setContentsMargins(0, 0, 0, 0)

        titel = QLabel("Ausgabe")
        titel.setObjectName("ausgabetitel")
        quer.addWidget(titel)

        # Farbige Plakette neben "Ausgabe": ausschliesslich die Taetigkeit -
        # denkt, liest, schreibt, führt aus, sucht, wartet. Kein Dateiname,
        # kein Pfad. Die Farbe ist dieselbe wie die des Balkens oben.
        self.taetigkeitsplakette = QLabel(KEINE_TAETIGKEIT)
        self.taetigkeitsplakette.setObjectName("taetigkeitsplakette")
        self.taetigkeitsplakette.setProperty("zustand", "bereit")
        self.taetigkeitsplakette.setAccessibleName("Aktuelle Tätigkeit")
        self.taetigkeitsplakette.setAlignment(Qt.AlignCenter)
        self.taetigkeitsplakette.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        quer.addWidget(self.taetigkeitsplakette)

        # Feld daneben: ausschliesslich der Name der Datei, an der gerade
        # gearbeitet wird - ohne Pfad, ohne Verb und ungekuerzt. Ist keine
        # Datei betroffen, bleibt es leer. Die Breite ist an den langen Namen
        # des Projekts gemessen und aendert sich nie.
        self.dateianzeige = QLabel("")
        self.dateianzeige.setObjectName("dateianzeige")
        self.dateianzeige.setAccessibleName("Bearbeitete Datei")
        self.dateianzeige.setAlignment(Qt.AlignCenter)
        self.dateianzeige.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        quer.addWidget(self.dateianzeige)

        # Der freie Platz liegt in der Mitte: dadurch stehen Datei links und
        # die drei Zahlenfelder rechts, ohne dass eines von ihnen waechst.
        quer.addStretch(1)

        # Modellwahl: anklickbar und mit der Tastatur bedienbar. Mit Tabulator
        # erreichbar, mit Pfeil auf und ab zu wechseln, mit Alt+Pfeil unten
        # aufzuklappen. Zu jedem Eintrag steht ein Hinweis dahinter, wofuer
        # sich das Modell eignet - als Kurzhinweis und fuer den Screenreader.
        # Sie steht vor den Zaehlern, damit die drei Zahlenfelder ununterbrochen
        # beieinander liegen.
        self.modellwahl = QComboBox()
        self.modellwahl.setObjectName("ausgabemodell")
        self.modellwahl.setAccessibleName("Modell wählen")
        self.modellwahl.setFocusPolicy(Qt.StrongFocus)
        self.modellwahl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.modellwahl.currentIndexChanged.connect(self._modell_gewechselt)
        quer.addWidget(self.modellwahl)

        # Die drei Zaehler sitzen in einer eigenen Reihe ohne Zwischenraum:
        # Auftrag, Sitzung, Heute - gleiche Breite, gleiche Gestalt, direkt
        # aneinander, damit man sie als einen Block liest.
        self.zaehlerreihe = QWidget()
        self.zaehlerreihe.setObjectName("zaehlerreihe")
        self.zaehlerreihe.setAccessibleName("Tokenzähler")
        self.zaehlerreihe.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        reihe = QHBoxLayout(self.zaehlerreihe)
        reihe.setContentsMargins(0, 0, 0, 0)
        reihe.setSpacing(0)

        # Token dieses einen Auftrags
        self.tokenzaehler = QLabel("Auftrag 0")
        self.tokenzaehler.setObjectName("tokenzaehler")
        self.tokenzaehler.setAccessibleName("Token dieses Auftrags")

        # Gesamtsumme der laufenden Sitzung
        self.sitzungszaehler = QLabel("Sitzung 0")
        self.sitzungszaehler.setObjectName("sitzungszaehler")
        self.sitzungszaehler.setAccessibleName("Token der ganzen Sitzung")

        # Summe des ganzen Kalendertages, ueber alle Sitzungen und Neustarts
        # hinweg. Sie kommt aus einstellungen.json und faengt um Mitternacht
        # von selbst wieder bei null an.
        self.tageszaehler = QLabel("Heute 0")
        self.tageszaehler.setObjectName("tageszaehler")
        self.tageszaehler.setAccessibleName("Token heute")

        for zaehler in (self.tokenzaehler, self.sitzungszaehler, self.tageszaehler):
            zaehler.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            zaehler.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            reihe.addWidget(zaehler)

        quer.addWidget(self.zaehlerreihe)

        self.kopieren = QPushButton("⧉  Kopieren")
        self.kopieren.setObjectName("kopieren")
        self.kopieren.setAccessibleName("Ganze Ausgabe kopieren")
        self.kopieren.setToolTip("Ganze Ausgabe kopieren (Strg+K)")
        self.kopieren.clicked.connect(self.kopieren_gedrueckt)
        quer.addWidget(self.kopieren)

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
        hoch und auf feste Breite, gemessen an gleichbleibenden Beispieltexten.
        Kein Inhalt kann die Groesse aendern - weder ein langer Dateiname noch
        eine grosse Zahl noch ein langer Modellname."""
        try:
            felder = (
                (self.taetigkeitsplakette, TAETIGKEIT_BEISPIELE),
                (self.dateianzeige, DATEI_BEISPIELE),
                (self.tokenzaehler, ZAEHLER_BEISPIELE),
                (self.sitzungszaehler, ZAEHLER_BEISPIELE),
                (self.tageszaehler, ZAEHLER_BEISPIELE),
            )
            gemessen = []
            hoehe = 0
            for teil, beispiele in felder:
                breite, teilhoehe = self._breite_messen(teil, beispiele)
                if breite <= 0 or teilhoehe <= 0:
                    return
                gemessen.append((teil, breite))
                hoehe = max(hoehe, teilhoehe)

            wahlbreite, wahlhoehe = self._wahl_masse_messen(MODELL_BEISPIELE)
            if wahlbreite <= 0 or wahlhoehe <= 0:
                return
            gemessen.append((self.modellwahl, wahlbreite))
            hoehe = max(hoehe, wahlhoehe)

            for teil, breite in gemessen:
                teil.setFixedWidth(breite)
                teil.setFixedHeight(hoehe)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Maße der Kopfzeile nicht festgelegt: %s", fehler)

    # -- Tätigkeit und Datei ------------------------------------------------

    def zustand_setzen(self, zustand: str) -> None:
        """Faerbt die Plakette wie den Balken oben. Die Farben stehen in
        stil.qss und haengen am Attribut 'zustand'."""
        self.taetigkeitsplakette.setProperty("zustand", zustand)
        self.taetigkeitsplakette.style().polish(self.taetigkeitsplakette)
        self.taetigkeitsplakette.update()

    def taetigkeit_zeigen(self, taetigkeit: str, pfad: str = "") -> None:
        """Fuellt die beiden Felder: die farbige Plakette traegt allein die
        Taetigkeit ('liest'), das Feld daneben allein den Dateinamen ohne Pfad
        und ungekuerzt ('ablagewaechter.py'). Ohne betroffene Datei bleibt es
        leer. Die Anzeige bleibt nach dem Auftrag beim letzten Schritt stehen."""
        try:
            self.taetigkeitsplakette.setText(taetigkeit or KEINE_TAETIGKEIT)
            self.taetigkeitsplakette.setAccessibleDescription(
                taetigkeit or "keine Tätigkeit"
            )
            name = Path(pfad).name if pfad else ""
            self.dateianzeige.setText(name)
            self.dateianzeige.setToolTip(pfad)
            self.dateianzeige.setAccessibleDescription(name or "keine Datei")
        except Exception as fehler:  # noqa: BLE001
            log.exception("Tätigkeitsanzeige nicht gesetzt: %s", fehler)

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
        """Merkt den Nur-Lesen-Zustand und schreibt die Meldung neu."""
        self.nur_lesen = bool(an)
        self.status_zeichnen()

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
