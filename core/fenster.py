"""
CWB - Code Workbench
Baustein 3: Hauptfenster (Werkbank) und Programmstart.

Die ständig gebrauchten Befehle liegen als flache Kachelreihe unter dem
Fortschrittsbalken (core/tastenleiste.py), alles Übrige über Tastenkürzel;
F1 liest sie vor. Ruht der Mauszeiger kurz auf einem Bedienelement oder
einem Anzeigefeld, wird dessen Inhalt angesagt - im ganzen Fenster und auf
der Einstellungsseite (core/zeigeransage.py).

Grundregel: gesprochen wird nur, was du wissen musst - fertig, Fehler,
Rückfrage, Abbruch. Alles andere nur auf Tastendruck oder Klick.

Was nicht zum Hauptfenster gehört, liegt daneben: der Arbeitsfaden in
core/faden.py, die Projektwahl in core/projektwahl.py, die Kopfzeile des
Ausgabefelds in core/kopfzeile.py, Pfade und Einstellungen in
core/grundlagen.py.

Aussehen kommt vollständig aus stil.qss. Im Python steht keine Gestaltung.
"""

import functools
import html
import logging
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QFont,
    QGuiApplication,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from .ablagewaechter import Zwischenablagewaechter
    from .einstellungen import EinstellungenFenster
    from .ersteinrichtung import Ersteinrichtung
    from .faden import SitzungsFaden
    from .grundlagen import (
        CWB_WURZEL,
        OFFENE_FENSTER,
        einstellungen_lesen,
        einstellungen_schreiben,
        slot_geschuetzt,
        stil_erneuern,
        stil_laden,
        stil_verzoegert,
        tagesverbrauch_erhoehen,
        tagesverbrauch_heute,
        unbehandelte_ausnahme,
        verlauf_stil_lesen,
    )
    from .kopfzeile import (
        Ausgabekopf,
        ZUGRIFF_NUR_LESEN,
        ZUGRIFF_SCHREIBEN,
        ZUSTAND_TAETIGKEIT,
        zahl_lang,
    )
    from .modelle import (
        MODELLE_RUECKFALL,
        eintrag_suchen,
        modell_lesen,
        modell_merken,
    )
    from .pfade import freigaben_lesen, pfade_vollstaendig
    from .projektwahl import Start
    from .sicherheit import Projekt, Stufe, Wache
    from .sprache import FESTE_SAETZE, Sprecher
    from .tastenleiste import Kachelreihe
    from .terminal import TerminalFaden
    from .zeigeransage import zeigeransage_einrichten
    from .zuordnung import (
        auftrag_vormerken,
        fremdes_projekt_erkennen,
        genanntes_projekt,
        hinweis_auf_projekt,
        vormerkung_abholen,
        vormerkung_einloesen,
        vormerkung_offen,
        vormerkung_verwerfen,
    )
except ImportError:
    from ablagewaechter import Zwischenablagewaechter
    from einstellungen import EinstellungenFenster
    from ersteinrichtung import Ersteinrichtung
    from faden import SitzungsFaden
    from grundlagen import (
        CWB_WURZEL,
        OFFENE_FENSTER,
        einstellungen_lesen,
        einstellungen_schreiben,
        slot_geschuetzt,
        stil_erneuern,
        stil_laden,
        stil_verzoegert,
        tagesverbrauch_erhoehen,
        tagesverbrauch_heute,
        unbehandelte_ausnahme,
        verlauf_stil_lesen,
    )
    from kopfzeile import (
        Ausgabekopf,
        ZUGRIFF_NUR_LESEN,
        ZUGRIFF_SCHREIBEN,
        ZUSTAND_TAETIGKEIT,
        zahl_lang,
    )
    from modelle import (
        MODELLE_RUECKFALL,
        eintrag_suchen,
        modell_lesen,
        modell_merken,
    )
    from pfade import freigaben_lesen, pfade_vollstaendig
    from projektwahl import Start
    from sicherheit import Projekt, Stufe, Wache
    from sprache import FESTE_SAETZE, Sprecher
    from tastenleiste import Kachelreihe
    from terminal import TerminalFaden
    from zeigeransage import zeigeransage_einrichten
    from zuordnung import (
        auftrag_vormerken,
        fremdes_projekt_erkennen,
        genanntes_projekt,
        hinweis_auf_projekt,
        vormerkung_abholen,
        vormerkung_einloesen,
        vormerkung_offen,
        vormerkung_verwerfen,
    )

log = logging.getLogger("cwb.fenster")

BILD_ENDUNGEN = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

# Die Kachel fuer das Schreibrecht nennt immer den geltenden Zustand, nie
# eine Aufforderung: "Lesen und Schreiben" oder "Nur lesen". Die Aufschrift
# beim Aufbau dient zugleich als Kennung, um die Kachel spaeter
# wiederzufinden - sie bleibt gleich, auch wenn die Aufschrift wechselt.
ZUGRIFF_KENNUNG = ZUGRIFF_SCHREIBEN

# Symbol und Farbe je Zustand. Die Farben selbst stehen in stil.qss.
ZUGRIFF_SYMBOL_SCHREIBEN = "✎"
ZUGRIFF_SYMBOL_NUR_LESEN = "⊘"
ZUGRIFF_FARBE_SCHREIBEN = "4"
ZUGRIFF_FARBE_NUR_LESEN = "nurlesen"

# Was beim Umschalten gesprochen wird: nur der neue Zustand.
ZUGRIFF_SATZ_NUR_LESEN = "Nur lesen."
ZUGRIFF_SATZ_SCHREIBEN = "Lesen und Schreiben erlaubt."

# Die Kachel hinter der Projektwarnung. Sie steht nur da, solange ein Auftrag
# vorgemerkt ist, und fuehrt ihn im geoeffneten Projekt aus. Die Aufschrift
# beim Aufbau dient zugleich als Kennung zum Wiederfinden.
TROTZDEM_KENNUNG = "Trotzdem hier ausführen"
TROTZDEM_SYMBOL = "⤓"
TROTZDEM_FARBE = "1"

# Markierungen am Anfang des Eingabefelds. Steht eine davon in der ersten
# Zeile, gilt alles darunter als Auftrag; die Markierungszeile selbst wird
# nicht mit uebergeben. Gross- und Kleinschreibung ist egal.
#
# #CODE# geht wie ein gewoehnlicher Auftrag an Claude Code.
# #RUN# und #ADMIN# laufen dagegen nie ueber Claude Code, sondern direkt als
# PowerShell-Befehl im Projektordner - ohne Modellaufruf, ohne
# Tokenverbrauch. #ADMIN# fragt dafuer immer erst mit dem vollen Befehl
# zurueck und laeuft danach mit erhoehten Rechten (siehe core/terminal.py).
MARKIERUNG_CODE = "#CODE#"
MARKIERUNG_RUN = "#RUN#"
MARKIERUNG_ADMIN = "#ADMIN#"

_MARKIERUNGEN = {
    MARKIERUNG_CODE: "code",
    MARKIERUNG_RUN: "run",
    MARKIERUNG_ADMIN: "admin",
}

# Leerraum, der vor der Markierung stehen darf. Neben den ueblichen
# Leerzeichen und Zeilenumbruechen auch die unsichtbaren Zeichen, die beim
# Kopieren aus Browser oder Editor mitkommen (Byte-Markierung, Nullbreite).
RANDZEICHEN = " \t\r\n\v\f\u00a0\u200b\u200e\u200f\ufeff"


def markierung_erkennen(text: str) -> tuple[str, str]:
    """Zerlegt eine Eingabe in Markierung und Inhalt.

    Rueckgabe: ("code" | "run" | "admin" | "", Inhalt ohne Markierungszeile).
    Leerraum und Leerzeilen vor der Markierung werden uebergangen. Ohne
    Markierung bleibt der Text unveraendert und die Art ist leer - er gilt
    dann als gewoehnlicher Auftrag und wird nie verworfen."""
    ohne_rand = text.lstrip(RANDZEICHEN)
    kopf, _, rest = ohne_rand.partition("\n")
    art = _MARKIERUNGEN.get(kopf.strip(RANDZEICHEN).upper())
    if art:
        return art, rest.strip(RANDZEICHEN)
    return "", text.strip(RANDZEICHEN)


# Hoechstzahl Saetze, die von einer Rueckfrage oder Fehlermeldung gesprochen
# wird. Notbremse in Zeichen fuer Meldungen ganz ohne Satzzeichen, etwa
# Stapelverfolgungen oder JSON-Brocken.
ANSAGE_SAETZE = 2
ANSAGE_ZEICHEN = 240

SATZ_MUSTER = re.compile(r"[^.!?…]+(?:[.!?…]+|$)")

# Datei- und Ordnerpfade in Rueckfragen und Fehlermeldungen: weder Windows-
# ("C:\a\b.py") noch Unix-Schreibweise ("a/b.py") soll die Stimme vorlesen -
# nur der Wortlaut ohne Pfad. Volle Pfade bleiben im Ausgabefeld und im Log.
PFAD_MUSTER = re.compile(r"(?:[A-Za-zÄÖÜäöüß]:[\\/])?(?:[\w.\-]+[\\/])+[\w.\-]+")


def kurzfassen(text: str, saetze: int = ANSAGE_SAETZE) -> str:
    """Kuerzt eine Meldung auf hoechstens zwei Saetze fuer die Sprachausgabe.

    Rueckfragen und Fehlermeldungen muessen gesprochen werden, aber niemand
    will eine Stapelverfolgung oder einen Dateipfad vorgelesen bekommen. Der
    volle Wortlaut bleibt im Ausgabefeld, in der Statuszeile und im Log
    stehen; gekuerzt wird nur, was durch die Stimme geht."""
    sauber = " ".join(PFAD_MUSTER.sub("Datei", str(text)).split())
    if not sauber:
        return ""
    kurz = "".join(SATZ_MUSTER.findall(sauber)[:saetze]).strip() or sauber
    if len(kurz) > ANSAGE_ZEICHEN:
        kurz = kurz[:ANSAGE_ZEICHEN].rstrip() + " …"
    return kurz


# Textarten im Ausgabefeld. Der Schluessel ist zugleich die Klasse in
# verlauf.css, der Wert das Vorsatzzeichen samt Klartextwort - damit die
# Bedeutung nicht nur in der Farbe steckt, sondern auch vorgelesen wird.
VERLAUF_ARTEN = {
    "auftrag": "▶  Auftrag: ",
    "antwort": "",
    "frage": "❓  FRAGE: ",
    "fehler": "✖  FEHLER: ",
    "hinweis": "—  ",
    "terminal": "▸  TERMINAL: ",
}


# Platzwoerter fuer die Ansage der Warteschlange. Gesprochen klingt "Platz
# zwei" natuerlicher als "Platz 2"; ab zwoelf reicht die Ziffer.
PLATZWOERTER = {
    2: "zwei", 3: "drei", 4: "vier", 5: "fünf", 6: "sechs",
    7: "sieben", 8: "acht", 9: "neun", 10: "zehn", 11: "elf",
}


def platzwort(platz: int) -> str:
    """Die Platznummer als gesprochenes Wort, ab zwoelf als Ziffer."""
    return PLATZWOERTER.get(int(platz), str(platz))


# ---------------------------------------------------------------------------
# Aktivitätsbalken: Farbe zeigt den Zustand, ein wandernder Streifen zeigt,
# dass gerade gearbeitet wird
# ---------------------------------------------------------------------------

class Aktivitaetsbalken(QFrame):
    """Der Balken oben. Ein heller Streifen wandert waehrend eines Auftrags
    ruhig und gleichmaessig von links nach rechts und beginnt von vorn.
    Die Farbe (Zustand) kommt weiter aus stil.qss ueber das Attribut.

    Der Balken traegt selbst die laufende Taetigkeit ('liest', 'schreibt', …)
    und dahinter den Dateinamen, gross und fett - die frueheren getrennten
    Felder in der Kopfzeile (core/kopfzeile.py) entfallen dafuer."""

    STREIFEN_ANTEIL = 0.22
    STREIFEN_DAUER_MS = 2600

    def __init__(self, parent=None):
        super().__init__(parent)
        self.glanz = QFrame(self)
        self.glanz.setObjectName("balkenglanz")
        self.glanz.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.glanz.hide()

        self.text = QLabel("", self)
        self.text.setObjectName("balkentext")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.text.raise_()

        self._animation = QPropertyAnimation(self.glanz, b"pos", self)
        self._animation.setDuration(self.STREIFEN_DAUER_MS)
        self._animation.setEasingCurve(QEasingCurve.Linear)
        self._animation.setLoopCount(-1)
        self._laeuft = False

    def _streifen_geometrie_setzen(self) -> None:
        breite = max(30, int(self.width() * self.STREIFEN_ANTEIL))
        self.glanz.setFixedSize(breite, self.height())
        self._animation.setStartValue(QPoint(-breite, 0))
        self._animation.setEndValue(QPoint(self.width(), 0))

    def resizeEvent(self, ereignis) -> None:
        super().resizeEvent(ereignis)
        self._streifen_geometrie_setzen()
        self.text.setGeometry(self.rect())
        if self._laeuft:
            self._animation.start()

    def animation_starten(self) -> None:
        self._laeuft = True
        self._streifen_geometrie_setzen()
        self.glanz.show()
        self._animation.start()

    def animation_stoppen(self) -> None:
        self._laeuft = False
        self._animation.stop()
        self.glanz.hide()

    def zustand_setzen(self, zustand: str) -> None:
        """Faerbt Balken und Text gemeinsam. Die Farben stehen in stil.qss
        und haengen am Attribut 'zustand'."""
        self.setProperty("zustand", zustand)
        self.style().polish(self)
        self.update()
        self.text.setProperty("zustand", zustand)
        self.text.style().polish(self.text)

    def taetigkeit_zeigen(self, taetigkeit: str, pfad: str = "") -> None:
        """Traegt die Taetigkeit ('liest') und dahinter den Dateinamen ohne
        Pfad ('ablagewaechter.py') im Balken ein. Ohne betroffene Datei steht
        nur die Taetigkeit da. Der volle Pfad bleibt als Kurzhinweis."""
        try:
            name = Path(pfad).name if pfad else ""
            text = f"{taetigkeit}  —  {name}" if (taetigkeit and name) else taetigkeit
            self.text.setText(text or "")
            self.text.setToolTip(pfad)
            self.text.setAccessibleDescription(
                f"{taetigkeit or 'keine Tätigkeit'}. {name or 'keine Datei'}."
            )
        except Exception as fehler:  # noqa: BLE001
            log.exception("Tätigkeit im Balken nicht gesetzt: %s", fehler)


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------

class Werkbank(QMainWindow):

    def __init__(self, projekt: Projekt, sprecher: Sprecher):
        super().__init__()
        self.projekt = projekt
        self.sprecher = sprecher
        self.bilder: list[Path] = []
        self.letzte_antwort = ""
        self.letzter_auftrag = ""
        self.letzter_verbrauch: dict = {}
        # Bericht des zuletzt beendeten Auftrags. Er wird gemerkt, damit F6 ihn
        # jederzeit erneut in die Zwischenablage legen kann.
        self._letzter_bericht = ""
        # Wahr, solange ein fertiger Bericht darauf wartet, kopiert zu werden:
        # war das Fenster beim Ende des Auftrags nicht im Vordergrund, wuerde
        # das Kopieren fremdes Kopiergut ueberschreiben.
        self._bericht_wartet = False
        self.frage_offen = False
        # Steht ein #run#- oder #admin#-Befehl auf eine Rueckfrage-Antwort,
        # liegt er hier - unabhaengig von den Rueckfragen aus Claude Code
        # selbst, die ueber den Arbeitsfaden laufen.
        self._pending_terminal: dict | None = None
        # Haelt den laufenden Terminalbefehl, damit er nicht vom Garbage
        # Collector eingesammelt wird, bevor er fertig ist.
        self._terminal_faden: TerminalFaden | None = None
        # Waehrend `_verlauf_anhaengen` schreibt, wandert der Schreibzeiger und
        # loest `_absatz_ansagen` aus. Ohne diese Sperre laese die Stimme jeden
        # einlaufenden Absatz der Antwort mit vor.
        self._verlauf_waechst = False
        self.wechselt = False
        self.start_fenster = None
        self.nur_lesen = False
        # Modellwahl: gemerkt in einstellungen.json, die Liste kommt spaeter
        # von Claude Code selbst. Bis dahin steht die Rueckfallliste im Feld.
        self.modell = modell_lesen()
        self.modelle: list[dict] = list(MODELLE_RUECKFALL)
        # Auftraege, die abgeschickt wurden, bevor der Arbeitsfaden stand.
        # Sie gehen nicht verloren, sondern laufen los, sobald er da ist.
        self._wartende_auftraege: list[tuple[str, list[Path]]] = []
        # Warteschlange: Auftraege, die abgeschickt wurden, waehrend schon
        # einer lief. Sie werden der Reihe nach abgearbeitet, einer nach dem
        # anderen - nichts geht verloren, nichts blockiert. F4 leert sie.
        self._warteschlange: list[tuple[str, list[Path]]] = []
        # Wahr, solange ein Auftrag beim Arbeitsfaden liegt. Nur daran
        # erkennt _absenden, ob der neue Auftrag warten muss.
        self._auftrag_laeuft = False
        # Wahr, solange gerade ein Auftrag des Zwischenablage-Waechters laeuft.
        # Nur daran erkennt _absenden, ob ein Auftrag von anderer Seite kam.
        self._aus_ablage = False
        # Wahr, solange ein vorgemerkter Auftrag aus einem anderen Projekt
        # nachgeholt wird. Nur so wird er nicht erneut als fremd erkannt.
        self._holt_vorgemerkten = False
        # Ausgangsschrift der Textfelder, gemerkt beim Aufbau. Strg+0 stellt sie
        # wieder her, falls doch einmal etwas an der Groesse gedreht hat.
        self._schrift_ausgang: list[tuple[QWidget, QFont]] = []

        # Beleg, welche Fassung der Datei wirklich laeuft. Ohne diese Zeile
        # laesst sich nicht unterscheiden, ob eine Aenderung fehlt oder nur
        # ein alter Prozess noch offen ist.
        quelle = Path(__file__).resolve()
        log.info(
            "Werkbank startet aus %s (geändert %s), _aus_zwischenablage vorhanden: %s",
            quelle,
            datetime.fromtimestamp(quelle.stat().st_mtime).strftime("%d.%m.%Y %H:%M:%S"),
            callable(getattr(self, "_aus_zwischenablage", None)),
        )

        self.setWindowTitle(f"CWB — Projekt: {projekt.name}")

        # Der Faden entsteht vor der Oberflaeche. Sonst kann eine Kachel oder
        # ein Kuerzel schon zuschlagen, waehrend es ihn noch nicht gibt.
        # Angelegt wird er hier, gestartet erst nach dem Aufbau.
        self.faden = SitzungsFaden(projekt, self.modell)
        self.faden.ereignis_da.connect(self._ereignis)
        self.faden.text_da.connect(self._text)
        self.faden.fertig_da.connect(self._fertig)
        self.faden.frage_da.connect(self._frage)
        self.faden.bereit_da.connect(self._bereit)
        self.faden.verbrauch_da.connect(self._verbrauch)
        self.faden.modelle_da.connect(self._modelle_anbieten)

        self._aufbauen()
        self._tasten()

        # Ansage bei Mauszeiger fuer das ganze Fenster. Sie haengt an der
        # Anwendung und gilt darum auch fuer die Einstellungsseite. Ob
        # gesprochen wird, entscheidet der Schalter in den Einstellungen.
        self.zeigeransage = zeigeransage_einrichten(self.sprecher, einstellungen_lesen)
        if self.zeigeransage is None:
            log.error("Ansage bei Mauszeiger konnte nicht eingerichtet werden")

        # Schreibrecht von Anfang an sichtbar: Kachel und Kopfzeile nennen den
        # geltenden Zustand, nicht erst nach dem ersten Umschalten.
        self._zugriff_zeigen()
        # Rueckfrage-Ausnahmen (Internet, Loeschen im Projekt) von Anfang an
        # sichtbar - beide Schalter stehen ab Werk aus.
        self._sicherheitshinweis_aktualisieren()
        # Die Warteanzeige steht von Anfang an richtig da: leer, mit
        # verständlicher Beschreibung für den Screenreader.
        self._warteschlange_zeigen()
        # "Trotzdem hier ausführen" gibt es erst, wenn eine Projektwarnung
        # einen Auftrag zurueckgehalten hat.
        self._vormerkung_zeigen(False)

        self.faden.start()
        self._wartende_absenden()

        # Der Waechter laeuft immer mit; ob er handelt, entscheidet bei jedem
        # Blick die Einstellung - so wirkt das Umschalten sofort.
        self.ablage_waechter = Zwischenablagewaechter(
            markierung_erkennen,
            lambda: einstellungen_lesen().get("ablage_waechter", True),
            self._ablage_auftrag,
            self,
        )
        self.ablage_waechter.starten()

        # Wartet ein Auftrag auf genau dieses Projekt, laeuft er jetzt los.
        # Gehoert die Vormerkung zu einem anderen, verfaellt sie hier.
        QTimer.singleShot(0, self._vorgemerkten_holen)

        # Das Fenster ist sofort bedienbar, die Verbindung laeuft nebenher.
        self._status_zeigen("Verbinde mit Claude Code, Eingabe ist schon moeglich")
        self.eingabe.setEnabled(True)
        self.senden.setEnabled(True)

        self.eingabe.setFocus()

    # -- Aufbau -------------------------------------------------------------

    def _leisten_eintraege(self) -> list[tuple[str, str, object]]:
        """Alle Befehle mit ihrem Tastenkürzel. Grundlage der Hilfe (F1);
        die Kachelreihe zeigt nur die ständig gebrauchten daraus."""
        return [
            ("Strg+Eingabe", "Auftrag abschicken", self._absenden),
            ("F7", "Aus Zwischenablage abschicken", self._aus_zwischenablage),
            ("F8", "Not-Aus, Auftrag abbrechen", self._not_aus),
            ("Escape", "Ansage abbrechen", self.sprecher.schweig),
            ("F3", "Letzte Antwort vorlesen", self._antwort_vorlesen),
            ("F2", "Wo stehen wir", self._wo_stehen_wir),
            ("Strg+L", "Markiertes vorlesen", self._markiertes_vorlesen),
            ("Strg+K", "Ausgabe kopieren", self._verlauf_kopieren),
            ("Strg+0", "Schriftgröße zurücksetzen", self._schrift_zuruecksetzen),
            ("F10", "Nur lesen ein- oder ausschalten", self._nur_lesen_umschalten),
            ("Strg+Z", "Letzten Auftrag zurücknehmen", self._zuruecknehmen),
            ("Strg+B", "Bild anhängen", self._bild_waehlen),
            ("F5", "Zum Eingabefeld, nach Projektwarnung: trotzdem hier ausführen",
             self._f5),
            ("F6", "Bericht erneut kopieren", self._bericht_erneut_kopieren),
            ("F11", "Zum Verlauf", lambda: self._springe(self.verlauf, "Verlauf")),
            ("F1", "Hilfe vorlesen", self._hilfe),
            ("F9", "Projekt wechseln", self._projekt_wechseln),
            ("F4", "Warteschlange leeren", self._warteschlange_leeren),
            ("Strg+F4", "Kompletter Neustart", self._neustart),
            ("F12", "Einstellungen", self._einstellungen_zeigen),
        ]

    def _kachel_eintraege(self) -> list[tuple[str, str, str, str, object]]:
        """Die Kachelreihe unter dem Balken: nur ständig gebrauchte Befehle.
        Reihenfolge (symbol, beschriftung, taste, farbe, ziel). Die Farbnummer
        gehört dauerhaft zur Kachel, damit sie wiedererkennbar bleibt."""
        return [
            # "Abschicken" hat hier keine Kachel: dafuer gibt es den Pfeil
            # neben dem Eingabefeld und Strg+Eingabe.
            # "Aus Zwischenablage" hat keine Kachel mehr: der Waechter holt
            # markierte Auftraege von selbst. F7 bleibt als Notweg.
            ("⏹", "Not-Aus", "F8", "notaus", self._not_aus),
            ("✖", "Ansage abbrechen", "Escape", "2", self.sprecher.schweig),
            ("▶", "Letzte Antwort", "F3", "3", self._antwort_vorlesen),
            # Diese Kachel zeigt den Zustand an, nicht den Befehl: sie heisst
            # so, wie das Schreibrecht gerade steht.
            (ZUGRIFF_SYMBOL_SCHREIBEN, ZUGRIFF_KENNUNG, "F10",
             ZUGRIFF_FARBE_SCHREIBEN, self._nur_lesen_umschalten),
            # Steht nur da, solange ein Auftrag vorgemerkt ist; sonst
            # ausgeblendet (_vormerkung_zeigen).
            (TROTZDEM_SYMBOL, TROTZDEM_KENNUNG, "F5", TROTZDEM_FARBE,
             self._trotzdem_hier),
            ("⏏", "Warteschlange leeren", "F4", "8", self._warteschlange_leeren),
            ("⟳", "Neu starten", "Strg+F4", "5", self._neustart),
            ("⇄", "Projekt wechseln", "F9", "6", self._projekt_wechseln),
            ("⚙", "Einstellungen", "F12", "7", self._einstellungen_zeigen),
        ]

    def _aufbauen(self) -> None:
        mitte = QWidget()
        mitte.setObjectName("arbeitsflaeche")
        aufbau = QVBoxLayout(mitte)

        balken_zeile = QWidget()
        balken_zeile.setObjectName("balkenzeile")
        balken_quer = QHBoxLayout(balken_zeile)
        balken_quer.setContentsMargins(0, 0, 0, 0)

        self.balken = Aktivitaetsbalken()
        self.balken.setObjectName("balken")
        self.balken.setProperty("zustand", "bereit")
        self.balken.setAccessibleName("Aktivitätsanzeige")
        self._letzter_zustand = "bereit"
        balken_quer.addWidget(self.balken, 1)

        self.zeit_anzeige = QLabel("")
        self.zeit_anzeige.setObjectName("zeitanzeige")
        self.zeit_anzeige.setAccessibleName("Verstrichene Zeit")
        balken_quer.addWidget(self.zeit_anzeige)

        aufbau.addWidget(balken_zeile)

        # Kachelreihe direkt unter dem Balken. Sie teilt die Fensterbreite
        # gleichmaessig unter den Kacheln auf und waechst mit dem Fenster.
        self.kacheln = Kachelreihe(self._kachel_eintraege())
        aufbau.addWidget(self.kacheln)

        self._auftrags_beginn: datetime | None = None
        self._auftrags_uhr = QTimer(self)
        self._auftrags_uhr.setInterval(1000)
        self._auftrags_uhr.timeout.connect(self._zeit_aktualisieren)

        # Eine einzige Kopfzeile ueber dem Ausgabefeld traegt alles, was zum
        # Stand der Arbeit gehoert (core/kopfzeile.py).
        self.ausgabekopf = Ausgabekopf()
        self.ausgabekopf.kopieren_gedrueckt.connect(self._verlauf_kopieren)
        self.ausgabekopf.modell_gewaehlt.connect(self._modell_waehlen)
        self.ausgabekopf.modelle_setzen(self.modelle, self.modell)
        aufbau.addWidget(self.ausgabekopf)
        self.ausgabekopf.masse_festlegen()
        # Der Tageszaehler steht schon beim Start richtig da: er kommt aus
        # einstellungen.json und faengt nicht mit jedem Neustart neu an.
        self.ausgabekopf.tag_zeigen(tagesverbrauch_heute())

        # Formatierter Text statt einfachem: nur so lassen sich Auftrag,
        # Antwort und Rueckfrage farblich auseinanderhalten. Die Farben kommen
        # aus verlauf.css, nicht aus dem Python.
        self.verlauf = QTextEdit()
        self.verlauf.setObjectName("verlauf")
        self.verlauf.setReadOnly(True)
        self.verlauf.setAccessibleName("Verlauf")
        self.verlauf.document().setDefaultStyleSheet(verlauf_stil_lesen())
        self.verlauf.cursorPositionChanged.connect(self._absatz_ansagen)
        aufbau.addWidget(self.verlauf, 12)

        eingabezeile = QWidget()
        eingabezeile.setObjectName("eingabezeile")
        eingabequer = QHBoxLayout(eingabezeile)
        eingabequer.setContentsMargins(0, 0, 0, 0)

        self.eingabe = QPlainTextEdit()
        self.eingabe.setObjectName("eingabe")
        self.eingabe.setAccessibleName("Auftrag eingeben")
        eingabequer.addWidget(self.eingabe)

        self.senden = QPushButton("↑")
        self.senden.setObjectName("senden")
        self.senden.setAccessibleName("Auftrag abschicken")
        self.senden.setAccessibleDescription("Wie Strg und Eingabetaste")
        # Senkrecht mitwachsend: der Knopf ist immer genau so hoch wie das
        # Eingabefeld daneben, auch wenn dessen Hoehe sich aendert.
        self.senden.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.senden.clicked.connect(self._absenden)
        eingabequer.addWidget(self.senden)

        # Ohne Streckung: das Eingabefeld bleibt flach (Hoehe aus stil.qss),
        # der ganze uebrige Platz geht an das Ausgabefeld.
        aufbau.addWidget(eingabezeile, 0)

        # Strg+Mausrad wuerde in Verlauf und Eingabefeld die Schrift zoomen und
        # die Groesse aus stil.qss dauerhaft ueberschreiben. Der Filter schluckt
        # das Ereignis, damit es gar nicht erst dazu kommt.
        for feld in (self.verlauf, self.eingabe):
            self._schrift_ausgang.append((feld, QFont(feld.font())))
            feld.installEventFilter(self)
            feld.viewport().installEventFilter(self)

        self.setCentralWidget(mitte)

    def _kuerzel_merken(self, folge: str, ziel) -> None:
        """Schreibt nur die Logzeile, dass die Taste im Fenster angekommen ist.
        Das Ziel haengt als eigene Verbindung am selben Signal und wird nicht
        von hier aus aufgerufen."""
        log.info("Kürzel ausgelöst: %s → %s", folge, getattr(ziel, "__name__", ziel))

    def _tasten(self) -> None:
        kurz = [
            ("Ctrl+Return", self._absenden),
            ("Ctrl+Enter", self._absenden),
            ("Esc", self._escape),
            ("F1", self._hilfe),
            ("F2", self._wo_stehen_wir),
            ("F3", self._antwort_vorlesen),
            ("F5", self._f5),
            ("F6", self._bericht_erneut_kopieren),
            ("F11", lambda: self._springe(self.verlauf, "Verlauf")),
            ("F8", self._not_aus),
            ("F4", self._warteschlange_leeren),
            ("Ctrl+F4", self._neustart),
            ("F7", self._aus_zwischenablage),
            ("Ctrl+Z", self._zuruecknehmen),
            ("Ctrl+B", self._bild_waehlen),
            ("Ctrl+L", self._markiertes_vorlesen),
            ("Ctrl+K", self._verlauf_kopieren),
            ("Ctrl+0", self._schrift_zuruecksetzen),
            ("F10", self._nur_lesen_umschalten),
            ("F9", self._projekt_wechseln),
            ("F12", self._einstellungen_zeigen),
            ("Return", self._enter),
        ]
        # Alle Kuerzel gelten nur im eigenen Fenster, nicht in anderen.
        # Die Kuerzel werden in einer Liste behalten. Ohne eigene Verweise
        # haengen sie nur am Qt-Elternteil; die Liste macht sie zaehlbar und
        # ueberpruefbar.
        self.kuerzel: list[QShortcut] = []
        for folge, ziel in kurz:
            taste = QKeySequence(folge)
            if taste.isEmpty():
                log.error("Kürzel nicht lesbar, wird übergangen: %s", folge)
                continue
            kuerzel = QShortcut(taste, self)
            kuerzel.setContext(Qt.WindowShortcut)
            # Zwei getrennte Verbindungen: erst die Logzeile, dann das Ziel
            # selbst - unmittelbar, ohne Zwischenschritt. So steht im Log der
            # echte Methodenname und kein Huellenname, und nichts kann eine
            # Ausnahme des Ziels unterwegs verschlucken.
            kuerzel.activated.connect(functools.partial(self._kuerzel_merken, folge, ziel))
            kuerzel.activated.connect(ziel)
            self.kuerzel.append(kuerzel)
            log.info(
                "Kürzel angelegt: %s (%s) → %s",
                folge, taste.toString(), getattr(ziel, "__name__", ziel),
            )
        log.info("Kürzel insgesamt angelegt: %d von %d", len(self.kuerzel), len(kurz))

    # -- Ansagen ------------------------------------------------------------

    def _zustand_zeigen(self, zustand: str) -> None:
        if zustand == self._letzter_zustand:
            return
        self._letzter_zustand = zustand
        self.balken.zustand_setzen(zustand)

    def _status_zeigen(self, text: str) -> None:
        """Setzt die Statusmeldung in der Kopfzeile."""
        self.ausgabekopf.status_zeigen(text)

    def _taetigkeit_zeigen(self, taetigkeit: str, pfad: str = "") -> None:
        """Setzt Taetigkeit und Dateiname im Aktivitaetsbalken."""
        self.balken.taetigkeit_zeigen(taetigkeit, pfad)

    def _zugriff_zeigen(self) -> None:
        """Bringt Kachel und Kopfzeile auf den geltenden Zustand. Die Kachel
        nennt und faerbt ihn, die Kopfzeile zeigt ihn dauerhaft an."""
        if self.nur_lesen:
            text, symbol, farbe = (
                ZUGRIFF_NUR_LESEN, ZUGRIFF_SYMBOL_NUR_LESEN, ZUGRIFF_FARBE_NUR_LESEN
            )
        else:
            text, symbol, farbe = (
                ZUGRIFF_SCHREIBEN, ZUGRIFF_SYMBOL_SCHREIBEN, ZUGRIFF_FARBE_SCHREIBEN
            )
        self.kacheln.kachel_beschriften(ZUGRIFF_KENNUNG, text, text, symbol)
        self.kacheln.kachel_faerben(ZUGRIFF_KENNUNG, farbe)
        self.ausgabekopf.nur_lesen_setzen(self.nur_lesen)

    def _sicherheitshinweis_aktualisieren(self) -> None:
        """Liest die drei Rueckfrage-Schalter aus den Einstellungen (Reiter
        Verhalten) und die Freigabenliste (Reiter Freigaben) und zeigt beides
        in der Kopfzeile an. Wird beim Start und nach jedem Schliessen der
        Einstellungsseite aufgerufen."""
        werte = einstellungen_lesen()
        self.ausgabekopf.sicherheitshinweis_setzen(
            bool(werte.get("internet_ohne_rueckfrage", False)),
            bool(werte.get("loeschen_ohne_rueckfrage", False)),
            bool(werte.get("installieren_ohne_rueckfrage", False)),
        )
        try:
            freigaben = [eintrag["name"] for eintrag in freigaben_lesen()]
        except Exception as fehler:  # noqa: BLE001
            log.exception("Freigabenliste nicht lesbar: %s", fehler)
            freigaben = []
        self.ausgabekopf.freigaben_zeigen(freigaben)

    def _nur_lesen_umschalten(self) -> None:
        """Schaltet den Nur-Lesen-Modus um: Schreiben und Loeschen wird
        abgelehnt, Lesen und Suchen bleiben erlaubt."""
        self.nur_lesen = not self.nur_lesen
        try:
            self.faden.nur_lesen_setzen(self.nur_lesen)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Nur-Lesen-Modus nicht weitergereicht: %s", fehler)
        self._zugriff_zeigen()
        log.info("Schreibrecht: %s", ZUGRIFF_NUR_LESEN if self.nur_lesen
                 else ZUGRIFF_SCHREIBEN)
        self.sprecher.sprich(
            ZUGRIFF_SATZ_NUR_LESEN if self.nur_lesen else ZUGRIFF_SATZ_SCHREIBEN
        )

    def _zeit_aktualisieren(self) -> None:
        if self._auftrags_beginn is None:
            return
        sekunden = int((datetime.now() - self._auftrags_beginn).total_seconds())
        self.zeit_anzeige.setText(f"{sekunden} s")

    def _springe(self, feld, name: str) -> None:
        feld.setFocus()
        self.sprecher.sprich(name)

    def _hilfe(self) -> None:
        satz = "Unter dem Balken liegen die Kacheln mit den häufigsten Befehlen. " \
               "Alle Befehle mit Tastenkürzel: " + " ".join(
            f"{taste}: {beschriftung}." for taste, beschriftung, _ in self._leisten_eintraege()
        )
        # Auf Zuruf: eine Vorlesetaste schweigt in keiner Stufe, sonst waere
        # die Taste abgeschaltet statt die Stimme gedaempft.
        self.sprecher.sprich(satz, art="immer")

    def _einstellungen_zeigen(self) -> None:
        """F12: die Einstellungsseite mit Sprache, Tönen, Verhalten und Skills
        (core/einstellungen.py). Jede Änderung wirkt sofort."""
        try:
            fenster = EinstellungenFenster(
                self,
                self.sprecher,
                einstellungen_lesen,
                einstellungen_schreiben,
                self.projekt.pfad,
            )
        except Exception as fehler:  # noqa: BLE001
            log.exception("Einstellungen nicht geöffnet: %s", fehler)
            self.sprecher.sprich("Einstellungen konnten nicht geöffnet werden.",
                                 art="meldung")
            return
        self.sprecher.sprich("Einstellungen.")
        fenster.exec()
        self._sicherheitshinweis_aktualisieren()

    def _wo_stehen_wir(self) -> None:
        if self.faden.sitzung:
            self.sprecher.sprich(self.faden.sitzung.stand(), art="immer")
        else:
            self.sprecher.sprich("Noch nicht verbunden.", art="immer")

    def _antwort_vorlesen(self) -> None:
        self.sprecher.sprich(self.letzte_antwort or "Keine Antwort vorhanden.",
                             art="immer")

    def _markiertes_vorlesen(self) -> None:
        for feld in (self.verlauf, self.eingabe):
            markiert = feld.textCursor().selectedText().replace("\u2029", " ")
            if markiert.strip():
                self.sprecher.sprich(markiert, art="immer")
                return
        self.sprecher.sprich("Nichts markiert.", art="immer")

    def _schrift_zuruecksetzen(self) -> None:
        """Strg+0: Setzt die Schrift aller Textfelder auf den Ausgangswert aus
        stil.qss zurueck, egal was vorher an der Groesse gedreht wurde."""
        try:
            for feld, schrift in self._schrift_ausgang:
                feld.setFont(QFont(schrift))
                feld.style().unpolish(feld)
                feld.style().polish(feld)
                feld.update()
            stil_erneuern(self.width(), self.height())
        except Exception as fehler:  # noqa: BLE001
            log.exception("Schriftgröße nicht zurückgesetzt: %s", fehler)
            self.sprecher.sprich("Schriftgröße konnte nicht zurückgesetzt werden.",
                                 art="meldung")
            return
        self.sprecher.sprich("Schriftgröße zurückgesetzt.")

    def _verlauf_kopieren(self) -> None:
        text = self.verlauf.toPlainText()
        if not text.strip():
            self.sprecher.sprich("Ausgabefenster ist leer.")
            return
        QGuiApplication.clipboard().setText(text)
        self.sprecher.sprich("Ausgabe kopiert.")

    def _absatz_ansagen(self) -> None:
        """Liest den Absatz vor, auf den der Nutzer im Ausgabefeld springt.

        Nur bei eigener Bewegung: waehrend einlaufender Text angehaengt wird,
        wandert der Zeiger von allein - dann bleibt es still, sonst wuerde die
        Antwort doch wieder automatisch vorgelesen."""
        if self._verlauf_waechst or not self.verlauf.hasFocus():
            return
        zeile = self.verlauf.textCursor().block().text().strip()
        if zeile:
            self.sprecher.sprich(zeile)

    def _escape(self) -> None:
        # Laeuft noch eine Ansage, bricht der erste Druck nur sie ab - sonst
        # wuerde er ungewollt zugleich eine offene Rueckfrage mit Nein
        # beantworten, noch bevor die Rueckfrage ueberhaupt zu Ende gesprochen ist.
        if self.frage_offen and not self.sprecher.spricht():
            self._frage_beantworten(False)
            return
        self.sprecher.schweig()

    def _enter(self) -> None:
        if self.frage_offen:
            self._frage_beantworten(True)

    # -- Rückfrage ----------------------------------------------------------

    @slot_geschuetzt
    def _frage(self, satz: str, kurz_satz: str) -> None:
        self.frage_offen = True
        self._zustand_zeigen("wartet")
        self._status_zeigen(f"Rückfrage: {satz}   Eingabe = ja, Escape = nein")
        self._verlauf_anhaengen(
            f"{satz}\nEingabe = ja, Escape = nein", "frage"
        )
        # Gesprochen wird ausschliesslich der fertig gekuerzte kurz_satz aus
        # sitzung.py (Anlass ohne Befehl oder Pfad, hoechstens ein kurzer
        # Satz). Der volle Wortlaut steht in Statuszeile und Ausgabefeld.
        self.sprecher.melde("wartet", kurz_satz, sprechen=True, art="meldung")

    def _frage_beantworten(self, ja: bool) -> None:
        self.frage_offen = False
        self._verlauf_anhaengen("Freigegeben." if ja else "Abgelehnt.", "hinweis")
        self._status_zeigen("Freigegeben." if ja else "Abgelehnt.")
        self.sprecher.sprich("Ja." if ja else "Nein.")
        if self._pending_terminal is not None:
            wartend, self._pending_terminal = self._pending_terminal, None
            if ja:
                self._terminal_starten(wartend["befehl"], wartend["admin"])
            return
        self.faden.frage_beantworten(ja)

    # -- Terminal (#run# und #admin#) ---------------------------------------

    def _terminal_markierung(self, art: str, befehl: str) -> None:
        """Verarbeitet einen #run#- oder #admin#-Auftrag. Laeuft nie ueber
        Claude Code: kein Modellaufruf, kein Tokenverbrauch. Ordnergrenze,
        verbotene Befehle und Sperrliste aus core/sicherheit.py gelten
        unveraendert; #admin# fragt zusaetzlich immer mit dem vollen Befehl
        zurueck, bevor er mit erhoehten Rechten laeuft."""
        befehl = befehl.strip()
        if not befehl:
            self.sprecher.sprich("Nach der Markierung steht kein Befehl.", art="meldung")
            return
        admin = art == "admin"
        wache = Wache(self.projekt)
        wache.nur_lesen = self.nur_lesen
        urteil = wache.darf_befehl(befehl)
        if urteil.verboten:
            satz = urteil.ansage()
            log.warning("Terminalbefehl abgelehnt: %s", befehl)
            self._verlauf_anhaengen(satz, "terminal")
            self._status_zeigen(satz)
            self.sprecher.sprich(kurzfassen(satz), art="meldung")
            return
        if admin or urteil.stufe is Stufe.RUECKFRAGE:
            grund = "Admin-Befehl mit erhöhten Rechten" if admin else urteil.begruendung
            satz = f"{grund}: {befehl}. Fortfahren?"
            kurz_satz = f"{grund}. Fortfahren?"
            self._pending_terminal = {"befehl": befehl, "admin": admin}
            self._frage(satz, kurz_satz)
            return
        self._terminal_starten(befehl, admin)

    def _terminal_starten(self, befehl: str, admin: bool) -> None:
        if self._terminal_faden is not None and self._terminal_faden.isRunning():
            self.sprecher.sprich("Es läuft schon ein Terminalbefehl.", art="meldung")
            return
        art = "admin" if admin else "run"
        satz = "Admin-Befehl läuft…" if admin else "Terminalbefehl läuft…"
        log.info("Terminalbefehl gestartet (%s): %s", art, befehl)
        self._verlauf_anhaengen(befehl, "terminal")
        self._status_zeigen(satz)
        self.sprecher.sprich(satz, art="meldung")
        self._terminal_faden = TerminalFaden(art, befehl, self.projekt.pfad, self)
        self._terminal_faden.fertig_da.connect(self._terminal_fertig)
        self._terminal_faden.start()

    @slot_geschuetzt
    def _terminal_fertig(self, ergebnis) -> None:
        text = ergebnis.ausgabe or ergebnis.fehler or "(keine Ausgabe)"
        kopf = "Terminalausgabe" if ergebnis.erfolg else f"Terminalausgabe (Fehler, Code {ergebnis.code})"
        log.info("Terminalbefehl beendet, Erfolg=%s, Code=%s", ergebnis.erfolg, ergebnis.code)
        self._verlauf_anhaengen(f"{kopf}:\n{text}", "terminal")
        satz = "Terminalbefehl fertig." if ergebnis.erfolg else "Terminalbefehl fehlgeschlagen."
        self._status_zeigen(satz)
        self.sprecher.sprich(satz, art="meldung")

    # -- Modellwahl ---------------------------------------------------------

    @slot_geschuetzt
    def _modelle_anbieten(self, eintraege: list) -> None:
        """Uebernimmt die Liste, die Claude Code selbst gemeldet hat. Nur was
        das vorhandene Abo hergibt, steht danach im Auswahlfeld. Steht die
        gemerkte Wahl nicht mehr darin, faellt sie auf den ersten Eintrag."""
        if not eintraege:
            return
        self.modelle = list(eintraege)
        if not any(e.get("wert") == self.modell for e in self.modelle):
            log.warning("Gemerktes Modell %s wird nicht angeboten", self.modell)
            self.modell = self.modelle[0].get("wert", "")
            modell_merken(self.modell)
        self.ausgabekopf.modelle_setzen(self.modelle, self.modell)

    @slot_geschuetzt
    def _modell_waehlen(self, wert: str) -> None:
        """Der Nutzer hat im Kopf der Ausgabe ein anderes Modell gewaehlt: die
        Wahl wird gesichert, angesagt und die Sitzung sofort neu verbunden,
        damit sie schon beim naechsten Auftrag greift."""
        if not wert or wert == self.modell:
            return
        self.modell = wert
        modell_merken(wert)
        eintrag = eintrag_suchen(self.modelle, wert)
        satz = f"Modell {eintrag.get('name', wert)}. {eintrag.get('hinweis', '')}"
        self._status_zeigen(f"{satz} Sitzung wird neu verbunden.")
        self._verlauf_anhaengen(satz, "hinweis")
        self.sprecher.sprich(f"{satz} Sitzung wird neu verbunden.")
        log.info("Modell gewaehlt: %s", wert)
        self.faden.modell_setzen(wert)

    # -- Ereignisse aus der Sitzung ----------------------------------------

    def _bereit(self) -> None:
        self._zustand_zeigen("bereit")
        modell = self.faden.sitzung.modell_name if self.faden.sitzung else ""
        zusatz = f", Modell {modell}" if modell else ""
        self.ausgabekopf.modell_zeigen(modell)
        self._status_zeigen(f"Bereit — Projekt {self.projekt.name}{zusatz}")
        self.sprecher.melde("bereit", "Bereit.", sprechen=True)

    @slot_geschuetzt
    def _ereignis(self, zustand: str, ansage: str, detail: str,
                  pfad: str = "", taetigkeit: str = "", ablehnung: bool = False) -> None:
        """Waehrend der Arbeit bleibt die Statusmeldung leer: die laufende
        Taetigkeit steht ausschliesslich in der Plakette neben 'Ausgabe',
        farblich passend zum Balken, die betroffene Datei im Feld daneben.
        Die Statusmeldung zeigt nur Ergebnisse.

        Bei einer abgelehnten Aktion (ablehnung=True) ist ansage bewusst kurz
        und ohne Pfad - das ist alles, was gesprochen und in der Statuszeile
        angezeigt wird. Der volle Wortlaut mit Pfad steckt in detail und
        kommt, rot markiert wie ein Fehler, ins Ausgabefeld."""
        self._zustand_zeigen(zustand)
        self._taetigkeit_zeigen(
            taetigkeit or ZUSTAND_TAETIGKEIT.get(zustand, ""), pfad
        )
        if ablehnung:
            self._status_zeigen(ansage)
            self._verlauf_anhaengen(detail or ansage, "fehler")
        elif zustand == "fehler":
            self._status_zeigen(ansage)
            self._verlauf_anhaengen(ansage, "fehler")
        # Waehrend der Arbeit wird nichts gesprochen, nur der Ton wechselt.
        # Fehler und Ablehnungen werden gesprochen, aber auf zwei Saetze gekuerzt.
        gesprochen = kurzfassen(ansage) if (zustand == "fehler" or ablehnung) else ""
        self.sprecher.melde(zustand, gesprochen, sprechen=bool(gesprochen),
                            art="meldung")

    def _verlauf_anhaengen(self, text: str, art: str = "antwort") -> None:
        """Haengt einen Absatz an das Ausgabefeld. Die Art bestimmt die Klasse
        (Farbe aus verlauf.css) und das Vorsatzzeichen; unbekannte Arten
        gelten als gewoehnliche Antwort."""
        if art not in VERLAUF_ARTEN:
            art = "antwort"
        inhalt = f"{VERLAUF_ARTEN[art]}{text}".strip()
        if not inhalt:
            return
        self._verlauf_waechst = True
        try:
            self.verlauf.append(
                f'<div class="{art}">'
                + html.escape(inhalt).replace(chr(10), "<br>")
                + "</div>"
            )
        except Exception as fehler:  # noqa: BLE001
            log.exception("Verlauf nicht ergänzt: %s", fehler)
            return
        finally:
            self._verlauf_waechst = False
        leiste = self.verlauf.verticalScrollBar()
        leiste.setValue(leiste.maximum())

    def _text(self, text: str) -> None:
        self._verlauf_anhaengen(text, "antwort")

    def _verbrauch(self, verbrauch: dict) -> None:
        """Merkt den Verbrauch fuer den Bericht und zeigt ihn in der Kopfzeile.
        Was dieser Auftrag gekostet hat, wird zugleich dem heutigen Kalendertag
        in einstellungen.json gutgeschrieben - so zaehlt der Tageszaehler ueber
        Sitzungen und Neustarts hinweg weiter."""
        verbrauch = dict(verbrauch)
        verbrauch["heute"] = tagesverbrauch_erhoehen(verbrauch.get("gesamt", 0))
        self.letzter_verbrauch = verbrauch
        self.ausgabekopf.verbrauch_zeigen(verbrauch)

    @slot_geschuetzt
    def _fertig(self, bilanz: dict) -> None:
        self.letzte_antwort = bilanz.get("antwort", "")
        # Der Platz beim Arbeitsfaden ist wieder frei; die Bilder wurden schon
        # beim Abschicken uebergeben.
        self._auftrag_laeuft = False
        self._auftrags_uhr.stop()
        self.balken.animation_stoppen()

        # `satz` steht in der Statuszeile und muss in eine Zeile passen.
        # `hinweis` ergaenzt ihn im Ausgabefeld und wird nicht gesprochen.
        # `ansage` ist das Einzige, was durch die Stimme geht.
        hinweis = ""
        if bilanz.get("fehler"):
            self._zustand_zeigen("fehler")
            satz = "Fehler."
            hinweis = f" {bilanz['fehler']}"
            ansage = kurzfassen(f"Fehler. {bilanz['fehler']}")
        elif bilanz.get("abgebrochen"):
            self._zustand_zeigen("abgebrochen")
            satz = "Abgebrochen."
            ansage = satz
        else:
            self._zustand_zeigen("fertig")
            geaendert = bilanz.get("geaendert", [])
            anzahl = len(geaendert)
            if anzahl == 0:
                satz = "Fertig, keine Datei geändert."
            elif anzahl == 1:
                satz = f"Fertig, eine Datei geändert: {Path(geaendert[0]).name}."
            else:
                satz = f"Fertig, {anzahl} Dateien geändert."
            hinweis = " Antwort vorlesen mit F3, zurücknehmen mit Strg Z."
            ansage = satz

        self._status_zeigen(satz)
        self._verlauf_anhaengen(satz + hinweis,
                                "fehler" if bilanz.get("fehler") else "hinweis")
        # Gesprochen wird nur der kurze Ergebnissatz. Der Inhalt des
        # Ausgabefelds wird nie von allein vorgelesen - dafuer gibt es F3.
        self.sprecher.sprich((ansage + self._bericht_kopieren(bilanz)).strip(),
                             art="meldung")

        # Wartet noch ein Auftrag, laeuft er jetzt von allein los.
        self._naechsten_starten()

    def _bericht_bauen(self, bilanz: dict) -> str:
        """Baut den Bericht für die Zwischenablage: Auftrag, Antwort, geänderte
        Dateien und Tokenverbrauch des letzten Aufrufs."""
        teile = [f"Projekt: {self.projekt.name}",
                 f"Zeit: {datetime.now():%d.%m.%Y %H:%M}", ""]
        teile += ["Auftrag:", self.letzter_auftrag or "—", ""]
        teile += ["Antwort:", bilanz.get("antwort") or "—", ""]

        if bilanz.get("fehler"):
            teile += ["Fehler:", str(bilanz["fehler"]), ""]
        elif bilanz.get("abgebrochen"):
            teile += ["Abgebrochen.", ""]

        geaendert = bilanz.get("geaendert") or []
        teile.append("Geänderte Dateien:")
        teile += [f"- {pfad}" for pfad in geaendert] if geaendert else ["- keine"]
        teile.append("")

        verbrauch = self.letzter_verbrauch
        if verbrauch:
            teile += [
                "Tokenverbrauch (ohne Cache gerechnet):",
                f"- Sitzung gesamt: {zahl_lang(verbrauch.get('sitzung', 0))}",
                f"- letzter Aufruf: {zahl_lang(verbrauch.get('gesamt', 0))}",
                f"- letzter Aufruf, Eingabe: {zahl_lang(verbrauch.get('eingabe', 0))}",
                f"- letzter Aufruf, Ausgabe: {zahl_lang(verbrauch.get('ausgabe', 0))}",
                f"- letzter Aufruf, Cache gelesen: {zahl_lang(verbrauch.get('cache_gelesen', 0))}",
                f"- letzter Aufruf, Cache erstellt: {zahl_lang(verbrauch.get('cache_erstellt', 0))}",
            ]
        else:
            teile.append("Tokenverbrauch: keine Daten")
        return "\n".join(teile).strip() + "\n"

    def _bericht_kopieren(self, bilanz: dict) -> str:
        """Legt den Bericht nach jedem Auftrag in die Zwischenablage, sofern in
        den Einstellungen nicht abgeschaltet.

        Kopiert wird nur, wenn das CWB-Fenster im Vordergrund ist. Sonst wuerde
        der Bericht ueberschreiben, was der Nutzer inzwischen anderswo kopiert
        hat; er wird dann gemerkt und beim naechsten Wechsel ins Fenster
        nachgelegt.

        Rückgabe: haengt sich an den Ergebnissatz an, damit Bilanz und
        Zwischenablage-Hinweis in einer einzigen Ansage zusammenkommen statt
        in zwei kurz hintereinander."""
        try:
            self._letzter_bericht = self._bericht_bauen(bilanz)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Bericht nicht gebaut: %s", fehler)
            return " Bericht konnte nicht erstellt werden."
        if not einstellungen_lesen().get("bericht_kopieren", True):
            return ""
        if not self.isActiveWindow():
            self._bericht_wartet = True
            log.info("Bericht vorgemerkt, Fenster ist nicht im Vordergrund")
            return ""
        try:
            QGuiApplication.clipboard().setText(self._letzter_bericht)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Bericht nicht in die Zwischenablage gelegt: %s", fehler)
            return " Bericht konnte nicht kopiert werden."
        return " Bericht liegt in der Zwischenablage."

    def _bericht_nachlegen(self) -> None:
        """Legt einen vorgemerkten Bericht in die Zwischenablage, sobald das
        Fenster wieder im Vordergrund ist, und sagt es an."""
        if not self._bericht_wartet or not self._letzter_bericht:
            return
        self._bericht_wartet = False
        try:
            QGuiApplication.clipboard().setText(self._letzter_bericht)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Vorgemerkter Bericht nicht kopiert: %s", fehler)
            self.sprecher.sprich("Bericht konnte nicht kopiert werden.", art="meldung")
            return
        log.info("Vorgemerkter Bericht in die Zwischenablage gelegt")
        self.sprecher.sprich("Bericht liegt jetzt in der Zwischenablage.",
                             art="meldung")

    @slot_geschuetzt
    def _bericht_erneut_kopieren(self) -> None:
        """F6: legt den Bericht des letzten Auftrags noch einmal in die
        Zwischenablage, egal was inzwischen dort lag."""
        if not self._letzter_bericht:
            self.sprecher.sprich("Es gibt noch keinen Bericht.", art="meldung")
            return
        self._bericht_wartet = False
        try:
            QGuiApplication.clipboard().setText(self._letzter_bericht)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Bericht nicht erneut kopiert: %s", fehler)
            self.sprecher.sprich("Bericht konnte nicht kopiert werden.", art="meldung")
            return
        log.info("Bericht erneut in die Zwischenablage gelegt (F6)")
        self.sprecher.sprich("Bericht liegt jetzt in der Zwischenablage.",
                             art="meldung")

    # -- Bedienung ----------------------------------------------------------

    @slot_geschuetzt
    def _aus_zwischenablage(self) -> None:
        """F7: holt den Text aus der Zwischenablage ins Eingabefeld, sagt die
        erkannte Auftragsart an und schickt ihn sofort ab.

        Notweg von Hand: gewoehnlich holt der Waechter markierte Auftraege von
        selbst, darum gibt es dafuer keine Kachel mehr. Die erste Zeile im Log
        ist der Beleg, dass die Taste ueberhaupt ankommt - vorher
        (Strg+Umschalt+V) verschluckten die Textfelder sie."""
        log.info("Aus Zwischenablage aufgerufen (F7)")
        try:
            text = QGuiApplication.clipboard().text()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zwischenablage nicht lesbar: %s", fehler)
            self.sprecher.sprich("Zwischenablage konnte nicht gelesen werden.",
                                 art="meldung")
            return
        if not text.strip(RANDZEICHEN):
            log.info("Zwischenablage leer")
            self.sprecher.sprich("Zwischenablage ist leer.", art="meldung")
            return
        art, inhalt = markierung_erkennen(text)
        log.info(
            "Zwischenablage: %d Zeichen, Art %r, Inhalt %d Zeichen",
            len(text), art or "ohne Markierung", len(inhalt),
        )
        if art in ("run", "admin"):
            # #run# und #admin# fuellen nie das Eingabefeld: sie laufen direkt
            # im Terminal, ohne Claude Code.
            self.sprecher.sprich("Aus Zwischenablage.", art="meldung")
            self._terminal_markierung(art, inhalt)
            return
        if not inhalt:
            # Nur die Markierung, kein Auftrag darunter: dann gilt der ganze
            # Text als Auftrag, damit nichts stillschweigend verlorengeht.
            inhalt = text.strip(RANDZEICHEN)
            art = ""
        self.eingabe.setPlainText(inhalt if art == "" else text)
        ansage = (
            "Code-Auftrag erkannt." if art == "code" else "Auftrag ohne Markierung."
        )
        self._absenden(vorspann=f"Aus Zwischenablage. {ansage}")

    @slot_geschuetzt
    def _ablage_auftrag(self, art: str, inhalt: str) -> None:
        """Der Wächter hat einen markierten Auftrag gefunden. #run# und
        #admin# laufen direkt im Terminal, ohne Eingabefeld und ohne Claude
        Code. #code# geht wie bisher ueber das Eingabefeld und _absenden.
        Die Zwischenablage ist zu diesem Zeitpunkt schon geleert (siehe
        ablagewaechter.py)."""
        if art in ("run", "admin"):
            self.sprecher.sprich("Auftrag aus der Zwischenablage übernommen.", art="meldung")
            self._terminal_markierung(art, inhalt)
            return
        self.eingabe.setPlainText(inhalt)
        self._aus_ablage = True
        try:
            self._absenden(vorspann="Auftrag angenommen.")
        finally:
            self._aus_ablage = False

    @slot_geschuetzt
    def _absenden(self, vorspann: str = "") -> None:
        """`vorspann` ist der Anfang der Annahme-Ansage, wenn der Aufrufer
        schon einen eigenen Satz gebaut hat (Zwischenablage, Wächter,
        Vormerkung) - der Projekt-Hinweis haengt sich dann daran an, statt
        eine zweite Ansage kurz danach auszuloesen. Leer heisst: normaler
        Weg, die Ansage entsteht ganz in dieser Methode und in
        `_auftrag_starten`."""
        roh = self.eingabe.toPlainText()
        art, text = markierung_erkennen(roh)
        if art in ("run", "admin"):
            # #run# und #admin# laufen nie ueber Claude Code: kein
            # Modellaufruf, kein Tokenverbrauch, direkt im Terminal.
            self.eingabe.clear()
            self._terminal_markierung(art, text)
            return
        if not text:
            self.sprecher.sprich(
                "Nach der Markierung steht nichts." if art else "Nichts eingegeben.",
                art="meldung",
            )
            return
        if not self._holt_vorgemerkten:
            # Zwei Regeln halten einen Auftrag hier auf: er nennt Dateien, die
            # es hier nicht gibt, wohl aber in einem anderen Projekt - oder er
            # nennt den Namen eines anderen Projekts aus der Projektliste. In
            # beiden Faellen wird er vorgemerkt und dort ausgefuehrt, sobald
            # das Projekt geoeffnet wird.
            fremd = (fremdes_projekt_erkennen(text, self.projekt)
                     or genanntes_projekt(text, self.projekt))
            if fremd:
                # Die Warnung haelt niemanden auf: sie merkt den Auftrag nur
                # vor. F9 wechselt zum genannten Projekt, F5 fuehrt ihn hier
                # aus - beides wird mit angesagt, sonst waere die Kachel fuer
                # den blinden Nutzer nicht auffindbar.
                satz = (f"Dieser Auftrag gehört vermutlich zu Projekt {fremd}, "
                        f"geöffnet ist {self.projekt.name}. Mit F9 wechseln, "
                        f"mit F5 trotzdem hier ausführen.")
                auftrag_vormerken(fremd, roh)
                self.eingabe.clear()
                self._vormerkung_zeigen(True)
                self._verlauf_anhaengen(satz, "hinweis")
                self._status_zeigen(satz)
                self.sprecher.sprich(satz, art="meldung")
                return
            # Ein neuer Auftrag hier hebt eine aeltere Vormerkung auf.
            vormerkung_verwerfen()
            self._vormerkung_zeigen(False)
            # Laesst der Auftrag gar nicht erkennen, welches Projekt gemeint
            # ist, wird das geoeffnete kurz angesagt - sonst faellt eine
            # Verwechslung erst am Ergebnis auf.
            if not hinweis_auf_projekt(text, self.projekt):
                hinweis = f"Läuft in {self.projekt.name}."
                vorspann = f"{vorspann} {hinweis}".strip() if vorspann else hinweis
        bilder = list(self.bilder)
        self.bilder.clear()
        self.eingabe.clear()

        if self._auftrag_laeuft:
            # Es laeuft schon einer. Der neue geht nicht verloren und blockiert
            # nichts, sondern reiht sich ein und laeuft los, sobald der
            # vorherige fertig ist.
            self._warteschlange.append((text, bilder))
            self._warteschlange_zeigen()
            satz = f"Auftrag vorgemerkt, Platz {platzwort(len(self._warteschlange) + 1)}."
            if vorspann:
                satz = f"{vorspann} {satz}"
            log.info("Auftrag in die Warteschlange auf Platz %d: %s",
                     len(self._warteschlange) + 1, text[:120])
            self._verlauf_anhaengen(f"{satz} {text}", "hinweis")
            self._status_zeigen(satz)
            self.sprecher.sprich(satz, art="meldung")
            return

        self._auftrag_starten(text, bilder, vorspann=vorspann)

    def _auftrag_starten(self, text: str, bilder: list[Path],
                          vorspann: str = "", ansagen: bool = True) -> None:
        """Uebergibt genau einen Auftrag an den Arbeitsfaden und stellt die
        Anzeige darauf ein. Gerufen wird das von `_absenden` fuer den ersten
        Auftrag und von `_naechsten_starten` fuer jeden aus der Warteschlange.

        `vorspann` ersetzt die Standardansage "Auftrag angenommen", wenn der
        Aufrufer schon einen eigenen Anfangssatz gebaut hat. `ansagen=False`
        schweigt hier ganz, weil `_naechsten_starten` die Ansage zur
        Warteschlange schon selbst gesprochen hat - so laeuft nie mehr als
        eine Ansage pro Auftragsstart los."""
        self._auftrag_laeuft = True
        self._verlauf_anhaengen(text, "auftrag")
        self.letzter_auftrag = text
        self.letzter_verbrauch = {}
        # Die Statuszeile zeigt keine laufende Arbeit an, nur Ergebnisse.
        self._status_zeigen("")
        self._taetigkeit_zeigen("beginnt")
        self._auftrags_beginn = datetime.now()
        self.zeit_anzeige.setText("0 s")
        self._auftrags_uhr.start()
        self.balken.animation_starten()

        faden = getattr(self, "faden", None)
        if faden is None:
            # Der Arbeitsfaden steht noch nicht. Der Auftrag wird gemerkt und
            # in _wartende_absenden nachgereicht, sobald es ihn gibt.
            self._wartende_auftraege.append((text, bilder))
            self._taetigkeit_zeigen("wartet")
            log.info("Auftrag vorgemerkt, Arbeitsfaden fehlt noch: %s", text[:120])
            if ansagen:
                satz = f"{vorspann or 'Auftrag angenommen.'} Verbindung wird noch aufgebaut."
                self.sprecher.sprich(satz, art="meldung")
            return
        if faden.sitzung is None:
            self._taetigkeit_zeigen("verbindet")
            faden.auftrag_geben(text, bilder)
            if ansagen:
                satz = f"{vorspann or 'Auftrag angenommen.'} Verbindung wird noch aufgebaut."
                self.sprecher.sprich(satz, art="meldung")
            return
        if ansagen:
            self.sprecher.sprich(vorspann or "Auftrag angenommen.", art="meldung")
        faden.auftrag_geben(text, bilder)

    def _warteschlange_zeigen(self) -> None:
        """Bringt die Zahl der wartenden Auftraege in die Kopfzeile."""
        try:
            self.ausgabekopf.warteschlange_zeigen(len(self._warteschlange))
        except Exception as fehler:  # noqa: BLE001
            log.exception("Warteschlange nicht angezeigt: %s", fehler)

    def _naechsten_starten(self) -> None:
        """Holt den naechsten Auftrag aus der Warteschlange, sobald der
        vorherige beendet ist. Ist sie leer, geschieht nichts."""
        self._warteschlange_zeigen()
        if not self._warteschlange:
            return
        text, bilder = self._warteschlange.pop(0)
        self._warteschlange_zeigen()
        log.info("Nächster Auftrag aus der Warteschlange: %s", text[:120])
        rest = len(self._warteschlange)
        satz = "Nächster Auftrag aus der Warteschlange."
        if rest:
            satz += f" Danach warten noch {rest}." if rest > 1 else " Danach wartet noch einer."
        # Ohne Unterbrechen: der Ergebnissatz des vorherigen Auftrags darf
        # nicht abgeschnitten werden.
        self.sprecher.sprich(satz, unterbrechen=False, art="meldung")
        self._auftrag_starten(text, bilder, ansagen=False)

    @slot_geschuetzt
    def _warteschlange_leeren(self) -> None:
        """F4: verwirft alle wartenden Auftraege. Der gerade laufende bleibt -
        den beendet der Not-Aus (F8)."""
        anzahl = len(self._warteschlange)
        self._warteschlange.clear()
        self._warteschlange_zeigen()
        if anzahl == 0:
            satz = "Warteschlange ist schon leer."
        elif anzahl == 1:
            satz = "Warteschlange geleert, ein Auftrag verworfen."
        else:
            satz = f"Warteschlange geleert, {anzahl} Aufträge verworfen."
        log.info("Warteschlange geleert: %d Auftraege verworfen", anzahl)
        self._verlauf_anhaengen(satz, "hinweis")
        self._status_zeigen(satz)
        self.sprecher.sprich(satz)

    def _vormerkung_zeigen(self, sichtbar: bool) -> None:
        """Blendet die Kachel "Trotzdem hier ausführen" ein oder aus. Sie steht
        nur da, solange ein Auftrag vorgemerkt ist - sonst zeigte sie auf
        nichts."""
        try:
            self.kacheln.kachel_zeigen(TROTZDEM_KENNUNG, sichtbar)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kachel für die Vormerkung nicht umgeschaltet: %s", fehler)

    @slot_geschuetzt
    def _f5(self) -> None:
        """F5 hat zwei Bedeutungen, je nach Lage: hält die Projektwarnung
        gerade einen Auftrag zurück, führt F5 ihn hier aus. Sonst springt sie
        wie gewohnt ins Eingabefeld."""
        if vormerkung_offen():
            self._trotzdem_hier()
            return
        self._springe(self.eingabe, "Eingabefeld")

    @slot_geschuetzt
    def _trotzdem_hier(self) -> None:
        """F5 nach einer Projektwarnung: der vorgemerkte Auftrag läuft doch im
        geöffneten Projekt. Die Vormerkung ist damit verbraucht, ein
        Projektwechsel holt ihn nicht mehr nach."""
        roh = vormerkung_einloesen()
        self._vormerkung_zeigen(False)
        if not roh:
            satz = "Es ist kein Auftrag vorgemerkt."
            self._status_zeigen(satz)
            self.sprecher.sprich(satz, art="meldung")
            return
        satz = f"Auftrag läuft trotzdem in {self.projekt.name}."
        log.info("%s %s", satz, roh[:120])
        self._verlauf_anhaengen(satz, "hinweis")
        self._status_zeigen(satz)
        self.eingabe.setPlainText(roh)
        # Wie beim Nachholen im richtigen Projekt: die Zuordnungspruefung wird
        # uebergangen, sonst hielte dieselbe Warnung den Auftrag sofort wieder
        # auf.
        self._holt_vorgemerkten = True
        try:
            self._absenden(vorspann=satz)
        finally:
            self._holt_vorgemerkten = False

    @slot_geschuetzt
    def _vorgemerkten_holen(self) -> None:
        """Ein Auftrag, der in einem anderen Projekt abgeschickt wurde, aber
        hierher gehoert, laeuft beim Oeffnen dieses Projekts von allein."""
        roh = vormerkung_abholen(self.projekt.name)
        self._vormerkung_zeigen(False)
        if not roh:
            return
        satz = "Vorgemerkter Auftrag wird jetzt ausgeführt."
        log.info("%s %s", satz, roh[:120])
        self._verlauf_anhaengen(satz, "hinweis")
        self._status_zeigen(satz)
        self.eingabe.setPlainText(roh)
        self._holt_vorgemerkten = True
        try:
            self._absenden(vorspann=satz)
        finally:
            self._holt_vorgemerkten = False

    def _wartende_absenden(self) -> None:
        """Reicht Auftraege nach, die vor dem Arbeitsfaden abgeschickt wurden."""
        if not self._wartende_auftraege:
            return
        wartend, self._wartende_auftraege = self._wartende_auftraege, []
        for text, bilder in wartend:
            log.info("Vorgemerkten Auftrag nachgereicht: %s", text[:120])
            self.faden.auftrag_geben(text, bilder)

    def _not_aus(self) -> None:
        """F8: bricht den laufenden Auftrag ab. Wartende Auftraege werden
        dabei mit verworfen - sonst liefe nach dem Not-Aus der naechste von
        allein los, was niemand erwartet, der eben alles gestoppt hat."""
        verworfen = len(self._warteschlange)
        self._warteschlange.clear()
        self._warteschlange_zeigen()
        satz = "Not-Aus."
        if verworfen == 1:
            satz += " Ein wartender Auftrag verworfen."
        elif verworfen > 1:
            satz += f" {verworfen} wartende Aufträge verworfen."
        log.info("Not-Aus, wartende Auftraege verworfen: %d", verworfen)
        # "Abgebrochen." kommt gleich ueber _fertig - diese Zwischenmeldung
        # bleibt still, sonst spricht CWB zweimal fuer denselben Abbruch.
        self.sprecher.sprich(satz)
        self.faden.not_aus()

    def _zuruecknehmen(self) -> None:
        if not self.faden.sitzung:
            return
        urteil = self.faden.sitzung.rueckgaengig()
        self._status_zeigen(urteil.ansage())
        self.sprecher.sprich(urteil.ansage())

    def _bild_waehlen(self) -> None:
        muster = "Bilder (" + " ".join(f"*{e}" for e in BILD_ENDUNGEN) + ")"
        pfade, _ = QFileDialog.getOpenFileNames(self, "Bild anhängen", "", muster)
        for pfad in pfade:
            self.bilder.append(Path(pfad))
        if pfade:
            anzahl = len(self.bilder)
            self.sprecher.sprich(
                "Ein Bild angehängt." if anzahl == 1 else f"{anzahl} Bilder angehängt."
            )

    def _projekt_wechseln(self) -> None:
        """Faden sauber beenden, Projektwahl öffnen, dieses Fenster schließen."""
        self.wechselt = True
        if self in OFFENE_FENSTER:
            OFFENE_FENSTER.remove(self)
        self.sprecher.sprich("Projekt wechseln.")
        try:
            self.faden.beenden()
            self.faden.wait(5000)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Faden beim Projektwechsel nicht beendet: %s", fehler)
        self.start_fenster = Start(self.sprecher, Werkbank, automatisch=False)
        self.start_fenster.resize(1200, 850)
        self.start_fenster.show()
        self.close()

    def _neustart(self) -> None:
        """Beendet den laufenden Python-Prozess und startet ihn neu - wie ein
        Neuladen einer Seite. Anders als der Projektwechsel (F9) verwirft das
        auch jeden internen Zustand, der nicht in Dateien gesichert ist."""
        self.sprecher.sprich("Kompletter Neustart.")
        self.wechselt = True
        if self in OFFENE_FENSTER:
            OFFENE_FENSTER.remove(self)
        try:
            self.faden.beenden()
            self.faden.wait(5000)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Faden beim Neustart nicht beendet: %s", fehler)
        try:
            # os.execv wartet unter Windows intern auf das Prozessende des
            # neuen Prozesses, bevor der alte sich beendet - das alte Fenster
            # friert dabei ein, statt zu verschwinden. Daher ein eigener,
            # entkoppelter Prozess statt eines echten Prozess-Austauschs.
            subprocess.Popen([sys.executable] + sys.argv, cwd=str(CWB_WURZEL))
        except OSError as fehler:
            log.error("Neustart gescheitert: %s", fehler)
            self.sprecher.sprich("Neustart gescheitert.", art="meldung")
            return
        self.close()
        QApplication.instance().quit()

    def _bild_aus_ablage(self) -> bool:
        ablage = QGuiApplication.clipboard().image()
        if ablage.isNull():
            return False
        ziel = CWB_WURZEL / ".ablage"
        try:
            ziel.mkdir(parents=True, exist_ok=True)
            datei = ziel / f"ablage_{len(self.bilder) + 1}.png"
            ablage.save(str(datei), "PNG")
        except OSError as fehler:
            log.error("Bild aus Zwischenablage nicht speicherbar: %s", fehler)
            return False
        self.bilder.append(datei)
        self.sprecher.sprich("Bild aus Zwischenablage angehängt.")
        return True

    def eventFilter(self, gegenstand, ereignis) -> bool:
        """Haelt Strg+Mausrad von den Textfeldern fern: Qt wuerde damit zoomen
        und die Schriftgroesse aus stil.qss ueberschreiben."""
        art = ereignis.type()
        if art == QEvent.Wheel and (ereignis.modifiers() & Qt.ControlModifier):
            return True
        return super().eventFilter(gegenstand, ereignis)

    def keyPressEvent(self, ereignis) -> None:
        if ereignis.matches(QKeySequence.Paste) and self._bild_aus_ablage():
            return
        super().keyPressEvent(ereignis)

    def changeEvent(self, ereignis) -> None:
        super().changeEvent(ereignis)
        # Zurueck im Vordergrund: ein waehrenddessen fertig gewordener Bericht
        # wird jetzt nachgelegt, ohne fremdes Kopiergut zu ueberschreiben.
        if ereignis.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._bericht_nachlegen()
        # Ein neues Stilblatt bringt eine neue Schriftgroesse mit: die eine
        # Zeile wird dann neu ausgemessen und der Text passend gekuerzt.
        if ereignis.type() in (QEvent.StyleChange, QEvent.FontChange) and hasattr(
            self, "ausgabekopf"
        ):
            self.ausgabekopf.masse_festlegen()
            self.ausgabekopf.status_zeichnen()

    def resizeEvent(self, ereignis) -> None:
        super().resizeEvent(ereignis)
        stil_verzoegert(self.width(), self.height())
        # Die Meldung in der Kopfzeile bleibt einzeilig, also muss die Kuerzung
        # zur neuen Breite passen. Beim allerersten Ereignis steht sie noch nicht.
        if hasattr(self, "ausgabekopf"):
            self.ausgabekopf.status_zeichnen()

    def closeEvent(self, ereignis) -> None:
        if self in OFFENE_FENSTER:
            OFFENE_FENSTER.remove(self)
        try:
            waechter = getattr(self, "ablage_waechter", None)
            if waechter is not None:
                waechter.anhalten()
            self.faden.beenden()
            self.faden.wait(5000)
            if not self.wechselt:
                self.sprecher.beenden()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Beenden gescheitert: %s", fehler)
        super().closeEvent(ereignis)


# ---------------------------------------------------------------------------
# Programmstart
# ---------------------------------------------------------------------------

def main() -> None:
    # Muss vor allem anderen stehen: ab hier landet jeder Absturz im Log
    # statt auf dem unsichtbaren stderr von pythonw.
    sys.excepthook = unbehandelte_ausnahme

    anwendung = QApplication(sys.argv)
    stil_laden(anwendung)

    sprecher = Sprecher()

    # Beim allerersten Start ist noch kein Projektordner gemerkt. Ohne ihn
    # bliebe die Projektwahl leer, deshalb wird vorher gefragt.
    if not pfade_vollstaendig():
        log.info("Kein Projektordner eingestellt, Ersteinrichtung wird gezeigt")
        Ersteinrichtung(sprecher).exec()

    fenster = Start(sprecher, Werkbank)
    fenster.resize(1200, 850)
    fenster.show()

    threading.Thread(
        target=sprecher.vorwaermen,
        args=(FESTE_SAETZE,),
        daemon=True,
    ).start()

    sys.exit(anwendung.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as fehler:  # noqa: BLE001
        log.exception("CWB abgestürzt: %s", fehler)
        print(f"CWB abgestürzt: {fehler}")
