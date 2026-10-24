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

import atexit
import ctypes
import faulthandler
import functools
import html
import json
import logging
import os
import re
import struct
import subprocess
import sys
import threading
import time
import zipfile
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    Qt,
    QThread,
    QTimer,
    Signal,
    qInstallMessageHandler,
)
from PySide6.QtGui import (
    QFont,
    QGuiApplication,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from . import absturzschutz
    from .ablagewaechter import Zwischenablagewaechter
    from .android_screenshot import ZEITLIMIT_S as BILD_ZEITLIMIT_S, screenshot_ablegen
    from .bloecke import block_erkennen, block_zaehler_aktualisieren, kopf_metadaten_entfernen, \
        naechste_block_nummer
    from .bruecke import QUELLE_BRUECKE, BerichtFaden, BrueckenFaden, \
        NachtberichtFaden, ProtokollFaden, zugangsdaten_lesen
    from .datenordner import erstuebernahme
    from .eingangsordner import AuftragSpaeter, Eingangswaechter, EingangsFehler, ablegen, \
        abschliessen, auftrag_lesen, bericht_vermerken, naechste_fremde_projekt_datei, \
        unterbrochene_markieren, \
        projekt_gleichwertig, unbekannte_verwerfen, verwerfen, wartende_dateien, bekannt_unter, \
        wieder_aufnehmen
    from .einstellungen import EinstellungenFenster
    from .ersteinrichtung import Ersteinrichtung
    from .faden import SitzungsFaden
    from . import darstellung, kontingentsperre, leitstand, notaus_pause, orchestrator
    from .orchestrator_ansicht import OrchestratorAnsicht
    from .grundlagen import (
        CWB_WURZEL,
        OFFENE_FENSTER,
        auftrags_kennung,
        einstellungen_lesen,
        einstellungen_schreiben,
        fenster_geometrie_merken,
        kontingent_entscheidung,
        slot_geschuetzt,
        stil_erneuern,
        stil_laden,
        stil_verzoegert,
        stil_wird_angewandt,
        such_effizienz_prozent,
        tagesverbrauch_erhoehen,
        tagesverbrauch_heute,
        qt_meldung_behandeln,
        unbehandelte_ausnahme,
        unbehandelte_ausnahme_im_faden,
        verlauf_stil_lesen,
    )
    from .kopfzeile import (
        Ausgabekopf,
        Ausgabetext,
        Umbruchfeld,
        ZeilenFluss,
        ZUGRIFF_NUR_LESEN,
        ZUGRIFF_SCHREIBEN,
        ZUSTAND_TAETIGKEIT,
        zahl_lang,
    )
    from .modelle import (
        MODELLE_RUECKFALL,
        VOREINSTELLUNG as MODELL_VOREINSTELLUNG,
        anzeige_name,
        eintrag_suchen,
        modellname_aufloesen,
    )
    from .pausetaste import PausenTaste
    from .pfade import EINSTELLUNGEN_DATEI, STATUS_DATEI, VERSION, \
        freigaben_lesen, pfade_vollstaendig
    from .projektwahl import Start
    from .sicherheit import Projekt, Stufe, Wache, projekte_finden
    from .sprache import FESTE_SAETZE, Sprecher
    from .tastenleiste import KACHELN_SCHALTBAR, KACHELN_STAND, KACHELN_VOREINSTELLUNG, Kachelreihe
    from .terminal import ADMIN_WORKER, TerminalFaden, admin_worker_schleife
    from .zeigeransage import zeigeransage_einrichten
    from . import ansagegedaechtnis, auftragsjournal, einfueger, warteliste, zielfenster, zustellwache
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
    import absturzschutz
    from ablagewaechter import Zwischenablagewaechter
    from android_screenshot import ZEITLIMIT_S as BILD_ZEITLIMIT_S, screenshot_ablegen
    from bloecke import block_erkennen, block_zaehler_aktualisieren, kopf_metadaten_entfernen, \
        naechste_block_nummer
    from bruecke import QUELLE_BRUECKE, BerichtFaden, BrueckenFaden, \
        NachtberichtFaden, ProtokollFaden, zugangsdaten_lesen
    from datenordner import erstuebernahme
    from eingangsordner import AuftragSpaeter, Eingangswaechter, EingangsFehler, ablegen, \
        abschliessen, auftrag_lesen, bericht_vermerken, naechste_fremde_projekt_datei, \
        unterbrochene_markieren, \
        projekt_gleichwertig, unbekannte_verwerfen, verwerfen, wartende_dateien, bekannt_unter, \
        wieder_aufnehmen
    from einstellungen import EinstellungenFenster
    from ersteinrichtung import Ersteinrichtung
    from faden import SitzungsFaden
    import darstellung
    import kontingentsperre
    import leitstand
    import notaus_pause
    import orchestrator
    from orchestrator_ansicht import OrchestratorAnsicht
    from grundlagen import (
        CWB_WURZEL,
        OFFENE_FENSTER,
        auftrags_kennung,
        einstellungen_lesen,
        einstellungen_schreiben,
        fenster_geometrie_merken,
        kontingent_entscheidung,
        slot_geschuetzt,
        stil_erneuern,
        stil_laden,
        stil_verzoegert,
        stil_wird_angewandt,
        such_effizienz_prozent,
        tagesverbrauch_erhoehen,
        tagesverbrauch_heute,
        qt_meldung_behandeln,
        unbehandelte_ausnahme,
        unbehandelte_ausnahme_im_faden,
        verlauf_stil_lesen,
    )
    from kopfzeile import (
        Ausgabekopf,
        Ausgabetext,
        Umbruchfeld,
        ZeilenFluss,
        ZUGRIFF_NUR_LESEN,
        ZUGRIFF_SCHREIBEN,
        ZUSTAND_TAETIGKEIT,
        zahl_lang,
    )
    from modelle import (
        MODELLE_RUECKFALL,
        VOREINSTELLUNG as MODELL_VOREINSTELLUNG,
        anzeige_name,
        eintrag_suchen,
        modellname_aufloesen,
    )
    from pausetaste import PausenTaste
    from pfade import EINSTELLUNGEN_DATEI, STATUS_DATEI, VERSION, \
        freigaben_lesen, pfade_vollstaendig
    from projektwahl import Start
    from sicherheit import Projekt, Stufe, Wache, projekte_finden
    from sprache import FESTE_SAETZE, Sprecher
    from tastenleiste import KACHELN_SCHALTBAR, KACHELN_STAND, KACHELN_VOREINSTELLUNG, Kachelreihe
    from terminal import ADMIN_WORKER, TerminalFaden, admin_worker_schleife
    from zeigeransage import zeigeransage_einrichten
    import ansagegedaechtnis
    import auftragsjournal
    import einfueger
    import warteliste
    import zielfenster
    import zustellwache
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
ZUSTELL_KENNUNG = "Ergebnisse zustellen"
ZUSTELL_SYMBOL = "📤"
ZUSTELL_FARBE = "4"
WARTE_KENNUNG = "Warteschlange"
WARTE_SYMBOL = "☰"
WARTE_FARBE = "5"
TROTZDEM_KENNUNG = "Trotzdem hier ausführen"
TROTZDEM_SYMBOL = "⤓"
TROTZDEM_FARBE = "1"

# Kachel fuer den Schalter "Bruecke" (Vorhaben "Bruecke" Stufe B3, siehe
# wissen/plan_bruecke.md). Die Aufschrift beim Aufbau dient zugleich als
# Kennung zum Wiederfinden, genau wie bei TROTZDEM_KENNUNG/ZUGRIFF_KENNUNG.
BRUECKE_KENNUNG = "Brücke"
BRUECKE_SYMBOL_AUS = "🌉"
BRUECKE_SYMBOL_AN = "🛰"
BRUECKE_FARBE_AUS = "1"
BRUECKE_FARBE_AN = "4"

# Kachel fuer den Schalter "Leitstand" (Block 72, siehe
# wissen/plan_leitstand.md). Die Aufschrift beim Aufbau dient zugleich als
# Kennung zum Wiederfinden, genau wie bei BRUECKE_KENNUNG.
# Kachel zum Umschalten in die Orchestrator-Ansicht (wie Strg+O). Eigene Farbe
# "orchestrator" in stil.qss, die zu keiner Zustandsfarbe gehoert. Sichtbar
# nur, solange der Schalter "orchestrator" an ist (_kacheln_sichtbarkeit_anwenden).
ORCH_KENNUNG = "Orchestrator"
ORCH_SYMBOL = "⇆"
ORCH_FARBE = "orchestrator"
LEITSTAND_KENNUNG = "Leitstand"
LEITSTAND_SYMBOL_AUS = "🌙"
LEITSTAND_SYMBOL_AN = "🛸"
LEITSTAND_FARBE_AUS = "1"
LEITSTAND_FARBE_AN = "4"

# Kontingent-Pause (Max-Abo): bricht ein Auftrag mit einer RateLimitEvent-
# Meldung status="rejected" ab (core/sitzung.py, auftrag()), haelt CWB die
# Warteschlange an statt den Auftrag als gescheitert zu werten. Die
# Zeitentscheidung (Wochenlimit oder Fuenf-Stunden-Fenster, wann der naechste
# Versuch startet) liegt reiner Logik wegen in core/grundlagen.py,
# kontingent_entscheidung() - hier nur der Vorspann fuer den
# Fortsetzungsversuch.
KONTINGENT_VORSPANN = (
    "Das Kontingent war erschöpft. Setze genau dort fort, wo du aufgehört "
    "hast; prüfe dafür wissen/offen.md und git status.\n\n"
)

# Ordner fuer die Berichtdateien, relativ zum Projekt. Der Bericht liegt schon
# in der Zwischenablage; fuer den Fall, dass daraus beim Einfuegen im Chat nur
# eine leere Anlage wird, gibt es ihn zusaetzlich als Datei zum Hochladen.
# Die Datei ist ein ZIP mit der Textdatei darin: einzeln hochgeladene
# Textdateien kamen im Chat regelmaessig leer an, verpackt kommen sie durch.
# Eine lose Textdatei daneben braucht niemand - vorgelesen wird aus dem
# Speicher (_letzter_bericht), nicht von der Platte.
BERICHT_UNTERORDNER = Path(".cwb") / "bericht"
# So viele Berichtdateien bleiben liegen, aeltere werden beim naechsten
# Speichern entfernt - sonst sammeln sich dort Hunderte an.
BERICHTE_BEHALTEN = 30

# Markierungen am Anfang des Eingabefelds. Steht eine davon in der ersten
# Zeile, gilt alles darunter als Auftrag; die Markierungszeile selbst wird
# nicht mit uebergeben. Gross- und Kleinschreibung ist egal.
#
# #CODE# geht wie ein gewoehnlicher Auftrag an Claude Code.
# #RUN# und #ADMIN# laufen dagegen nie ueber Claude Code, sondern direkt als
# PowerShell-Befehl im Projektordner - ohne Modellaufruf, ohne
# Tokenverbrauch. #ADMIN# fragt dafuer immer erst mit dem vollen Befehl
# zurueck und laeuft danach mit erhoehten Rechten (siehe core/terminal.py).
# #BILD# braucht keinen Befehlstext dahinter: die Markierung allein holt
# einen Screenshot vom verbundenen Android-Geraet (core/android_screenshot.py,
# BildFaden unten) und legt einen Dateiverweis in die Zwischenablage - ohne
# Claude Code, ohne Terminal, ohne jede Text-Rueckspielung ins Zielfenster.
MARKIERUNG_CODE = "#CODE#"
MARKIERUNG_RUN = "#RUN#"
MARKIERUNG_ADMIN = "#ADMIN#"
MARKIERUNG_BILD = "#BILD#"

# #RUN#-Befehle, die ihr Ergebnis selbst als Bild in die Zwischenablage legen
# (core/android_screenshot.py, auch ueber das Startskript in
# .cwb-werkzeuge). Fuer sie darf die Text-Rueckspielung unten in
# _terminal_fertig() das Bild nicht mit der gedruckten Meldung ueberschreiben.
# Bleibt fuer den alten #RUN#-Aufrufweg bestehen - #BILD# unten braucht diese
# Ausnahme nicht mehr, weil es nie ueber das Terminal laeuft.
BEFEHLE_OHNE_TEXT_RUECKSPIELUNG = ("android_screenshot.py",)

# Ergebnisse, die binnen dieser Zeit nacheinander fertig werden, bekommen
# nur eine gemeinsame Ansage (Linux, siehe _ansage_sammeln).
ANSAGE_SAMMELZEIT_MS = 1500
# Nach einem Abbruch ohne Not-Aus-Pause faellt der graue Balken nach dieser
# Zeit auf den Ruhezustand "bereit" zurueck.
ABBRUCH_RUECKFALL_MS = 5000


class _QtZwischenablage:
    """Zwischenablage fuer den Einfueger (core/einfueger.py)."""

    def setzen(self, text: str) -> bool:
        return zielfenster._in_zwischenablage_legen(text)

    def lesen(self) -> str:
        return QGuiApplication.clipboard().text()

    def leeren(self) -> None:
        QGuiApplication.clipboard().clear()

_MARKIERUNGEN = {
    MARKIERUNG_CODE: "code",
    MARKIERUNG_RUN: "run",
    MARKIERUNG_ADMIN: "admin",
    MARKIERUNG_BILD: "bild",
}

# Leerraum, der vor der Markierung stehen darf. Neben den ueblichen
# Leerzeichen und Zeilenumbruechen auch die unsichtbaren Zeichen, die beim
# Kopieren aus Browser oder Editor mitkommen (Byte-Markierung, Nullbreite).
RANDZEICHEN = " \t\r\n\v\f\u00a0\u200b\u200e\u200f\ufeff"


def markierung_erkennen(text: str) -> tuple[str, str]:
    """Zerlegt eine Eingabe in Markierung und Inhalt.

    Rueckgabe: ("code" | "run" | "admin" | "bild" | "", Inhalt ohne
    Markierungszeile). Leerraum und Leerzeilen vor der Markierung werden
    uebergangen. Ohne Markierung bleibt der Text unveraendert und die Art ist
    leer - er gilt dann als gewoehnlicher Auftrag und wird nie verworfen. Bei
    "bild" ist ein leerer Inhalt der Normalfall: die Markierung allein loest
    schon aus, es gehoert kein Befehlstext dahinter."""
    ohne_rand = text.lstrip(RANDZEICHEN)
    kopf, _, rest = ohne_rand.partition("\n")
    art = _MARKIERUNGEN.get(kopf.strip(RANDZEICHEN).upper())
    if art:
        return art, rest.strip(RANDZEICHEN)
    return "", text.strip(RANDZEICHEN)


# Block 649: "#MODELL# name" als optionale zweite Zeile direkt nach einer
# Markierung (#CODE#/#RUN#/#ADMIN#/#BILD#) - markierung_erkennen() oben hat
# die erste Zeile da schon entfernt, diese Zeile ist jetzt die erste von
# `inhalt`. Steht sie nicht an dieser Stelle, bleibt sie unangetastet und
# gilt als gewoehnlicher Auftragstext.
_MODELL_ZEILE_MUSTER = re.compile(r"^#MODELL#\s*(.+?)\s*$", re.IGNORECASE)


def modell_zeile_erkennen(inhalt: str) -> tuple[str, str | None]:
    """Zerlegt den Auftragsinhalt in (Inhalt ohne '#MODELL#'-Zeile, roher
    Modellname oder None). Die Zeile muss die allererste von `inhalt` sein -
    steht sie weiter unten, wird sie nicht erkannt und bleibt als normaler
    Text stehen, statt irgendwo im Auftrag herausgegriffen zu werden."""
    kopf, trenner, rest = inhalt.partition("\n")
    treffer = _MODELL_ZEILE_MUSTER.match(kopf.strip(RANDZEICHEN))
    if not treffer:
        return inhalt, None
    if not trenner:
        return "", treffer.group(1).strip()
    return rest.strip(RANDZEICHEN), treffer.group(1).strip()


class BildFaden(QThread):
    """#BILD#/Pause-Taste/Strg+Umschalt+B: holt den Android-Screenshot in
    einem eigenen Thread (core/android_screenshot.py, screenshot_ablegen) -
    der adb-Aufruf darf das Fenster nicht haengen lassen. Legt die Datei nur
    unter wissen\\bilder\\ im uebergebenen Projektordner ab, ruehrt die
    Zwischenablage nicht an: QClipboard darf nur auf dem GUI-Thread laufen,
    das erledigt _bild_fertig() unten nach fertig_da."""

    fertig_da = Signal(object)

    def __init__(self, projekt_ordner: Path, eltern=None):
        super().__init__(eltern)
        self._projekt_ordner = projekt_ordner

    def run(self) -> None:
        self.fertig_da.emit(screenshot_ablegen(self._projekt_ordner))


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
    # Werkzeugaufrufe waehrend des Auftrags: kein Vorsatzzeichen, der Satz
    # beginnt schon mit der Taetigkeit ("liest fenster.py"). Wird nicht
    # gesprochen, nur farblich passend zum Aktivitaetsbalken mitgefuehrt.
    "liest": "",
    "sucht": "",
    "schreibt": "",
    "fuehrt_aus": "",
    "netz": "",
    "denkt": "",
}

# Zustaende, die einen echten Werkzeugaufruf markieren (siehe
# sitzung.WERKZEUG_ZUSTAND) - fuer diese, und nur wenn eine Taetigkeit
# mitkommt, entsteht eine eigene Zeile im Ausgabefeld.
WERKZEUG_ZUSTAENDE = {"liest", "sucht", "schreibt", "fuehrt_aus", "netz", "denkt"}


# Platzwoerter fuer die Ansage der Warteschlange. Gesprochen klingt "Platz
# zwei" natuerlicher als "Platz 2"; ab zwoelf reicht die Ziffer.
PLATZWOERTER = {
    2: "zwei", 3: "drei", 4: "vier", 5: "fünf", 6: "sechs",
    7: "sieben", 8: "acht", 9: "neun", 10: "zehn", 11: "elf",
}


def platzwort(platz: int) -> str:
    """Die Platznummer als gesprochenes Wort, ab zwoelf als Ziffer."""
    return PLATZWOERTER.get(int(platz), str(platz))


# Block 77, Punkt 2: ab wie vielen Fehlschlaegen eines Auftrags aus Eingang/
# Bruecke/Leitstand in Folge der naechste (dritte) Versuch mit Opus laeuft.
HOCHSTUFUNG_AB_FEHLSCHLAEGEN = 2


def _modell_ist_opus(wert: str) -> bool:
    """Block 77, Punkt 2: ob der in F12 gewaehlte Standard (CLI-Kurzname wie
    "default"/"opus[1m]"/"opus"/"sonnet"/"haiku") schon Opus ist - dann
    hochstuft nichts mehr. "default"/leer zaehlt mit: core/modelle.py loest
    ihn (Stand 05.09.2026) auf Opus auf."""
    wert = (wert or "default").lower()
    return wert in ("", "default") or "opus" in wert


def datei_in_zwischenablage(pfad: Path) -> bool:
    """Legt eine Datei als Dateiverweis in die Windows-Zwischenablage
    (CF_HDROP) - so, wie beim Kopieren einer Datei im Explorer. Andere
    Programme (etwa ein Chat-Fenster) fuegen sie damit ueber Strg+V als
    echten Anhang ein, nicht als Text.

    Unter Linux gibt es kein pywin32: dort geht derselbe Dateiverweis ueber
    QMimeData.setUrls (zielfenster.datei_in_zwischenablage_legen). Schlaegt
    das fehl, legt der Aufrufer den Text hinein."""
    if sys.platform != "win32":
        return bool(zielfenster.datei_in_zwischenablage_legen(str(pfad)))
    try:
        import win32clipboard
        import win32con
    except ImportError as fehler:
        log.error("pywin32 fehlt, Datei nicht in Zwischenablage legbar: %s", fehler)
        return False
    dateiliste = (str(pfad) + "\0\0").encode("utf-16le")
    # DROPFILES-Kopf (20 Byte): Offset zur Dateiliste, Bildpunkt (ungenutzt),
    # kein Nicht-Client-Modus, Dateiliste in UTF-16 (fWide=1).
    kopf = struct.pack("<Iiiii", 20, 0, 0, 0, 1)
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_HDROP, kopf + dateiliste)
        finally:
            win32clipboard.CloseClipboard()
    except Exception as fehler:  # noqa: BLE001
        log.exception("Datei nicht in die Zwischenablage gelegt (%s): %s", pfad, fehler)
        return False
    return True


def zwischenablage_enthaelt_datei(pfad: Path) -> tuple[bool, str]:
    """Liest die Zwischenablage zurueck: liegt dort wirklich ein Dateiverweis
    auf `pfad`? Rueckgabe (ok, Grund); der Grund ist nur bei ok=False belegt.
    Muss auf dem GUI-Thread laufen. Eine Ansage darf die Datei nur nennen,
    wenn diese Pruefung ok ist."""
    try:
        mime = QGuiApplication.clipboard().mimeData()
        if mime is None:
            return False, "Zwischenablage ist leer"
        if not mime.hasUrls():
            return False, "kein Dateiverweis in der Zwischenablage"
        gesucht = Path(pfad).resolve()
        for url in mime.urls():
            if url.isLocalFile() and Path(url.toLocalFile()).resolve() == gesucht:
                return True, ""
        return False, "Dateiverweis zeigt auf eine andere Datei"
    except Exception as fehler:  # noqa: BLE001
        log.exception("Zwischenablage nicht pruefbar: %s", fehler)
        return False, f"Pruefung fehlgeschlagen ({fehler})"


def zwischenablage_enthaelt_text(text: str) -> tuple[bool, str]:
    """Wie `zwischenablage_enthaelt_datei`, fuer einen Text."""
    try:
        gelesen = QGuiApplication.clipboard().text()
    except Exception as fehler:  # noqa: BLE001
        log.exception("Zwischenablage nicht pruefbar: %s", fehler)
        return False, f"Pruefung fehlgeschlagen ({fehler})"
    if not gelesen:
        return False, "Zwischenablage ist leer"
    if gelesen != text:
        return False, "Zwischenablage enthaelt anderen Text"
    return True, ""


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
# Warteschlange einzeln verwalten
# ---------------------------------------------------------------------------

# Ein Eintrag in self._warteschlange/self._sparmodus_wartend: Auftragstext,
# Bilder, Bruecken-/Blocknummer, Eingangsordner-Datei, Modellwunsch/-grund
# und - seit Block 82 - Quelle und Zeitpunkt der Annahme (core/grundlagen.py,
# auftrags_kennung) fuer die Leiste "Wartet: ..." ueber dem Ausgabefeld.
WARTESCHLANGEN_EINTRAG = tuple[
    str, list[Path], int | None, int | None, Path | None, str | None, str | None,
    str, datetime,
]


class WarteschlangenFenster(QDialog):
    """Die Warteschlange als Liste (Umschalt+F4, Kachel "Warteschlange"): der
    laufende Auftrag steht als erster Eintrag (nicht loeschbar, dafuer gibt es
    F8), danach jeder wartende mit Platz, Auftragsnummer, Projekt, Art und
    Blocknummer. Entf loescht den gewaehlten nach Rueckfrage, Esc schliesst.
    Das Fenster haelt keinen eigenen Zustand: `sammeln` liefert die aktuellen
    Posten (core/warteliste.py), `loeschen` setzt das Loeschen im Hauptfenster
    um und liefert die Ansage danach, `fragen` stellt die Rueckfrage und
    `ansagen` spricht. Rechtsklick bietet zusaetzlich "Löschen"."""

    def __init__(self, sammeln, loeschen, fragen, ansagen, eltern=None):
        super().__init__(eltern)
        self._sammeln = sammeln
        self._loeschen = loeschen
        self._fragen = fragen
        self._ansagen = ansagen
        self._posten: list = []
        self.setWindowTitle("Warteschlange verwalten")
        self.setAccessibleName("Warteschlange verwalten")

        aufbau = QVBoxLayout(self)

        hinweis = QLabel(
            "Pfeiltasten wählen einen Auftrag, Entf löscht ihn nach Rückfrage, "
            "Esc schließt. Der laufende Auftrag lässt sich nicht löschen, "
            "dafür gibt es F8."
        )
        hinweis.setObjectName("warteschlange_hinweis")
        hinweis.setWordWrap(True)
        aufbau.addWidget(hinweis)

        self.liste = QListWidget(self)
        self.liste.setAccessibleName("Wartende Aufträge")
        self.liste.setContextMenuPolicy(Qt.CustomContextMenu)
        self.liste.customContextMenuRequested.connect(self._kontextmenue)
        aufbau.addWidget(self.liste)

        knopfreihe = QHBoxLayout()
        self.entfernen = QPushButton("Entfernen")
        self.entfernen.setAccessibleName("Ausgewählten Auftrag löschen")
        self.entfernen.clicked.connect(self._entfernen)
        self.schliessen = QPushButton("Schließen")
        self.schliessen.setAccessibleName("Schließen")
        self.schliessen.clicked.connect(self.accept)
        knopfreihe.addWidget(self.entfernen)
        knopfreihe.addWidget(self.schliessen)
        aufbau.addLayout(knopfreihe)

        self._liste_fuellen(0)
        self.liste.setFocus()

    def _liste_fuellen(self, zeile: int = 0) -> None:
        self._posten = list(self._sammeln())
        self.liste.clear()
        for posten in self._posten:
            text = warteliste.vorlesetext(posten)
            eintrag = QListWidgetItem(text)
            eintrag.setData(Qt.AccessibleTextRole, text)
            self.liste.addItem(eintrag)
        if not self._posten:
            self._ansagen("Keine wartenden Aufträge.")
            self.accept()
            return
        self.liste.setCurrentRow(max(0, min(zeile, len(self._posten) - 1)))

    def keyPressEvent(self, ereignis) -> None:
        if ereignis.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._entfernen()
            return
        super().keyPressEvent(ereignis)

    def _entfernen(self) -> None:
        zeile = self.liste.currentRow()
        if zeile < 0 or zeile >= len(self._posten):
            return
        posten = self._posten[zeile]
        if not posten.loeschbar:
            self._ansagen("Der laufende Auftrag lässt sich nicht löschen. "
                          "Zum Abbrechen F8 drücken.")
            return
        frage = f"{warteliste.kurzname(posten)} löschen?"
        if not self._fragen(frage):
            self._ansagen("Nicht gelöscht.")
            return
        satz = self._loeschen(posten)
        if satz:
            self._ansagen(satz)
        self._liste_fuellen(zeile)

    def _kontextmenue(self, position) -> None:
        eintrag = self.liste.itemAt(position)
        if eintrag is None:
            return
        self.liste.setCurrentItem(eintrag)
        menue = QMenu(self.liste)
        loeschen = menue.addAction("Löschen")
        gewaehlt = menue.exec(self.liste.mapToGlobal(position))
        if gewaehlt == loeschen:
            self._entfernen()


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------

def _journal_beginnt(fenster, art: str, nummer=None, block=None, detail: str = "") -> None:
    """Auftragsjournal: ein Auftrag beginnt (code, run, admin, bild)."""
    try:
        fenster._journal_beginn = datetime.now()
        fenster._journal_werkzeuge = 0
        auftragsjournal.gestartet(nummer=nummer, block=block, art=art, detail=detail)
    except Exception as fehler:  # noqa: BLE001
        log.exception("Auftragsjournal (beginnt): %s", fehler)
    _zeitwache_melden(fenster, nummer, True)


def _journal_endet(fenster, bruecke_nummer, block, art: str | None,
                   erfolg_text: str = "") -> None:
    """Auftragsjournal: Werkzeugzahl und Abschluss mit Dauer."""
    try:
        dauer = None
        beginn = getattr(fenster, "_journal_beginn", None)
        if beginn is not None:
            dauer = (datetime.now() - beginn).total_seconds()
        werkzeuge = getattr(fenster, "_journal_werkzeuge", 0)
        if werkzeuge:
            auftragsjournal.schreibe("werkzeug", f"anzahl={werkzeuge}",
                                     nummer=bruecke_nummer, block=block, art=art)
        auftragsjournal.abgeschlossen(
            dauer, erwartet_upload=bruecke_nummer is not None,
            nummer=bruecke_nummer, block=block, art=art, detail=erfolg_text)
    except Exception as fehler:  # noqa: BLE001
        log.exception("Auftragsjournal (endet): %s", fehler)
    _zeitwache_melden(fenster, bruecke_nummer, False)


def _zeitwache_melden(fenster, nummer, beginnt: bool) -> None:
    """Zeitwache (core/zustellwache.py): nur Brueckenauftraege. Ein Fehler
    hier stoert den Auftrag nie."""
    try:
        if nummer is None:
            return
        holer = getattr(fenster, "_zustellwache_holen", None)
        if holer is None:
            return
        wache = holer()
        if beginnt:
            wache.auftrag_beginnt(nummer)
        else:
            wache.auftrag_endet(nummer)
    except Exception as fehler:  # noqa: BLE001
        log.exception("Zeitwache: %s", fehler)


def _einfuegen_mit_kennung(einfueger_objekt, ziel, text: str, kennung: dict) -> None:
    """hinzufuegen() mit Merkzettel fuers Auftragsjournal; der Aufruf selbst
    bleibt unveraendert."""
    try:
        einfueger_objekt.naechste_kennung = kennung
    except Exception as fehler:  # noqa: BLE001
        log.exception("Auftragsjournal (Kennung): %s", fehler)
    einfueger_objekt.hinzufuegen(ziel, text)


# -- Orchestrator-Haken (core/orchestrator.py, Etappe 1A) ------------------
# Als Modulfunktionen mit getattr statt als Methoden: sie stehen in Wegen, die
# jedes Fenster durchlaeuft (Auftragsende, Not-Aus, Schliessen), und muessen
# ohne eingeschalteten Orchestrator (keine Ansicht, keine Nummernliste)
# wirkungslos bleiben.

def _orch_nummern_von(fenster) -> dict:
    nummern = getattr(fenster, "_orch_nummern", None)
    return nummern if isinstance(nummern, dict) else {}


def _orch_ansicht_von(fenster):
    ansicht = getattr(fenster, "_orch_ansicht", None)
    return ansicht if isinstance(ansicht, OrchestratorAnsicht) else None


def _orch_frage_offen(fenster) -> bool:
    ansicht = _orch_ansicht_von(fenster)
    return ansicht is not None and ansicht.frage_offen


def _orch_stopp(fenster) -> None:
    ansicht = _orch_ansicht_von(fenster)
    if ansicht is not None:
        try:
            ansicht.not_aus()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Orchestrator nicht gestoppt: %s", fehler)


def _orch_beenden(fenster) -> None:
    ansicht = _orch_ansicht_von(fenster)
    if ansicht is not None:
        try:
            ansicht.beenden()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Orchestrator-Faden nicht beendet: %s", fehler)


def _orch_im_vordergrund(fenster) -> bool:
    """Wahr, wenn gerade die Orchestrator-Ansicht sichtbar ist (Auswahl fuer F8)."""
    ansicht = _orch_ansicht_von(fenster)
    stapel = getattr(fenster, "_orch_stapel", None)
    return (ansicht is not None and stapel is not None
            and stapel.currentWidget() is ansicht)


def _orch_beschaeftigt(fenster) -> bool:
    """Wahr, wenn der Orchestrator arbeitet oder ein von ihm vergebener Auftrag
    noch nicht zu Ende ist (fuer die Rueckfrage vor Strg+F4)."""
    ansicht = _orch_ansicht_von(fenster)
    return ansicht is not None and (ansicht.beschaeftigt() or bool(_orch_nummern_von(fenster)))


def _orch_kontingent_von(fenster):
    """Kontingent-Zustand: erst die Code-Sitzung, dann die des Orchestrators."""
    zustaende = []
    for faden in (getattr(fenster, "faden", None),
                  getattr(_orch_ansicht_von(fenster), "faden", None)):
        sitzung = getattr(faden, "sitzung", None)
        if sitzung is not None:
            try:
                zustaende.append(sitzung.kontingent_zustand())
            except Exception as fehler:  # noqa: BLE001
                log.exception("Kontingent nicht lesbar: %s", fehler)
    return orchestrator.kontingent_waehlen(*zustaende)


def _orch_ist(fenster, eingang_datei) -> bool:
    """Wahr, wenn diese Auftragsdatei ein Orchestrator-Auftrag ist."""
    name = getattr(eingang_datei, "name", None)
    return isinstance(name, str) and name in _orch_nummern_von(fenster)


def _orch_bericht(fenster, eingang_datei, text: str, block=None,
                  status: str = "fertig", art: str | None = None) -> None:
    """Legt den Bericht eines beendeten Orchestrator-Auftrags ab und gibt ihn
    als Meldung direkt an die Orchestrator-Sitzung (Etappe 1B). Nur Auftraege
    mit Quelle "orchestrator" kommen hier an - Bruecken-Auftraege laufen
    weiter ueber den alten Weg. Ein Fehler hier darf den Abschluss des
    Auftrags nie verhindern."""
    if not _orch_ist(fenster, eingang_datei):
        return
    nummer = _orch_nummern_von(fenster).pop(eingang_datei.name)
    abgelegt = None
    try:
        abgelegt = orchestrator.bericht_ablegen(nummer, text, block)
    except Exception as fehler:  # noqa: BLE001
        log.exception("Orchestrator-Bericht %s nicht abgelegt: %s", nummer, fehler)
    ansicht = _orch_ansicht_von(fenster)
    if ansicht is None:
        return
    try:
        zustand = _orch_kontingent_von(fenster)
        ansicht.kontingent_setzen(zustand)
        bericht = orchestrator.bericht_holen(nummer) if abgelegt else None
        ansicht.meldung_annehmen(nummer, orchestrator.meldung_bauen(
            nummer, block, status, bericht, orchestrator.kontingent_zeile(zustand), art))
    except Exception as fehler:  # noqa: BLE001
        log.exception("Orchestrator-Meldung %s nicht zugestellt: %s", nummer, fehler)


class Werkbank(QMainWindow):

    def __init__(self, projekt: Projekt, sprecher: Sprecher):
        super().__init__()
        self.projekt = projekt
        self.sprecher = sprecher
        self._erste_anzeige_erledigt = False
        # Nur fuers Auftragsjournal (core/auftragsjournal.py): Beginn des
        # laufenden Auftrags und Zahl der Werkzeugaufrufe.
        self._journal_beginn: datetime | None = None
        self._journal_werkzeuge = 0
        auftragsjournal.projekt_setzen(projekt.name)
        self.bilder: list[Path] = []
        self.letzte_antwort = ""
        self.letzter_auftrag = ""
        self.letzter_verbrauch: dict = {}
        # Bericht des zuletzt beendeten Auftrags. Er wird gemerkt, damit F6 ihn
        # jederzeit erneut in die Zwischenablage legen kann.
        self._letzter_bericht = ""
        # Pfad der zuletzt gespeicherten Berichtdatei unter .cwb/bericht/ -
        # damit sich die Datei erneut als Dateiverweis in die Zwischenablage
        # legen laesst (Strg+F7), ohne den Bericht neu zu bauen.
        self._letzter_bericht_pfad: Path | None = None
        # Wahr, solange ein fertiger Bericht darauf wartet, kopiert zu werden:
        # war das Fenster beim Ende des Auftrags nicht im Vordergrund, wuerde
        # das Kopieren fremdes Kopiergut ueberschreiben.
        self._bericht_wartet = False
        # Bruecken-Nummern, deren Bericht schon in ein fremdes Fenster
        # eingefuegt wurde (nur #CODE#, siehe _bruecke_bericht_einfuegen):
        # jeder Bericht geht hoechstens einmal in den Chat. Dazu die Nummer
        # des Berichts in `_letzter_bericht` (None bei Fenster-Auftraegen) und
        # das beim Auftragsstart gemerkte Zielfenster.
        self._bruecke_eingefuegt: set = set()
        self._letzter_bericht_bruecke: int | None = None
        self._code_ziel: tuple | None = None
        self.frage_offen = False
        # Steht ein #run#- oder #admin#-Befehl auf eine Rueckfrage-Antwort,
        # liegt er hier - unabhaengig von den Rueckfragen aus Claude Code
        # selbst, die ueber den Arbeitsfaden laufen.
        self._pending_terminal: dict | None = None
        # Ein Block, dessen "Ende Block N"-Zeile fehlte (core/bloecke.py) -
        # er wurde NICHT ausgefuehrt, sondern liegt hier zur Entscheidung:
        # F5 fuehrt ihn trotzdem aus, Escape verwirft ihn. Ein neu
        # ankommender Block ueberschreibt eine aeltere Vormerkung, so wie bei
        # der Projektwarnung (siehe _vormerkung_zeigen).
        self._pending_block: dict | None = None
        # Die letzten zehn angenommenen Auftraege an Claude Code (Art "code"
        # oder ohne Markierung, geglaetteter Text, Zeitpunkt) - einzige
        # Grundlage der Dublettensperre, siehe _dublette_abgewiesen.
        # Waechter, F7 und das Eingabefeld tragen hier ein; "run", "admin"
        # und "bild" laufen an dieser Stelle nie vorbei, weil sie nie an
        # Claude Code gehen.
        self._auftragsverlauf: deque[tuple[str, str, datetime]] = deque(maxlen=10)
        # Haelt den laufenden Terminalbefehl, damit er nicht vom Garbage
        # Collector eingesammelt wird, bevor er fertig ist.
        self._terminal_faden: TerminalFaden | None = None
        # Haelt den laufenden #BILD#-Auftrag, aus demselben Grund.
        self._bild_faden: BildFaden | None = None
        # Bruecke zu claude.ai im Browser (core/bruecke.py, Vorhaben
        # "Bruecke" Stufe B3): laeuft nur, solange der Schalter an ist
        # (siehe _bruecke_zustand_anwenden). Die drei Nummer-Felder tragen
        # die auftrag_nummer eines laufenden Bruecken-Auftrags vom Eingang
        # bis zum Abschluss mit - None heisst "kein Bruecken-Auftrag". Ein
        # #CODE#-Auftrag kann in der Warteschlange stehen, darum traegt dort
        # jeder Eintrag seine eigene Nummer mit (siehe _warteschlange).
        self.bruecke_faden: BrueckenFaden | None = None
        self.leitstand_faden: leitstand.EntscheidungsFaden | None = None
        self._leitstand_plan_mtime: float | None = None
        self._nachtberichte: list[NachtberichtFaden] = []
        self._bruecke_berichte: list[BerichtFaden] = []
        self._bruecke_protokolle: list[ProtokollFaden] = []
        self._bruecke_code_nummer: int | None = None
        self._terminal_bruecke_nummer: int | None = None
        self._bild_bruecke_nummer: int | None = None
        self._bild_ziel = None
        # Orchestrator (core/orchestrator.py, Etappe 1A): Dateiname der
        # Auftragsdatei -> lokale Auftragsnummer, solange der Auftrag laeuft.
        # Leer und unbenutzt, solange der Schalter "orchestrator" aus ist.
        self._orch_nummern: dict[str, int] = {}
        self._orch_ansicht = None
        self._orch_stapel = None
        # Die Blocknummer (core/bloecke.py, "Block N") eines laufenden oder
        # wartenden #CODE#-Auftrags, bis _fertig() sie in den Bericht
        # uebernimmt - None, wenn der Auftrag keine Nummer trug.
        self._aktueller_block_nummer: int | None = None
        # Block 82: Kennung des GERADE LAUFENDEN Auftrags (CODE, RUN, ADMIN
        # oder BILD - nie zwei davon gleichzeitig) fuer die neue Leiste
        # "Läuft: ..." ueber dem Ausgabefeld und fuer F2 - gesetzt in
        # _auftrag_starten/_terminal_starten/_bild_markierung, gelesen in
        # _laeuft_kennung(). Bleibt nach Abschluss unveraendert stehen (wie
        # _laufender_modell_wunsch) statt eigens zurueckgesetzt zu werden:
        # _laeuft_kennung() prueft ohnehin zuerst, ob ueberhaupt noch etwas
        # laeuft, ein veralteter Wert wird also nie angezeigt.
        self._laufender_block_nummer: int | None = None
        self._laufender_quelle: str = ""
        self._laufender_zeit: datetime | None = None
        # Block 77, Punkte 1/2: der einmalige Modellwunsch (CLI-Kurzname wie
        # "opus") des gerade laufenden oder wartenden Auftrags sowie, nur bei
        # einer Hochstufung nach Fehlschlaegen (nicht bei einer ausdruecklichen
        # "Modell:"-Zeile), ein kurzer Grund fuer Ansage und Bericht - beide
        # None im Regelfall. Gesetzt in _auftrag_starten, verbraucht in
        # _fertig (Bericht) bzw. _kontingent_pause_behandeln (Fortsetzung).
        self._laufender_modell_wunsch: str | None = None
        self._laufender_modell_grund: str | None = None
        # Block 649: Hinweistext, wenn die Zeile "#MODELL# name" einen
        # unbekannten Namen nannte (dann leer) - landet im Bericht (_fertig)
        # genauso wie ein spaeter async gemeldeter Fehlschlag des
        # Modellwechsels selbst (core/faden.py, bilanz["modell_hinweis"]).
        self._laufender_modell_hinweis: str = ""
        # Block 70, Teil A: die laeuft/-Datei (core/eingangsordner.py) eines
        # laufenden oder wartenden Auftrags aus dem Eingangsordner - None,
        # wenn der Auftrag ueber die Zwischenablage oder das Eingabefeld kam.
        # Erst wenn der Auftrag wirklich abgeschlossen ist (Bericht
        # geschrieben oder hochgeladen), verschiebt abschliessen() die Datei
        # nach erledigt/ - vorher gilt sie als nicht erledigt und wird nach
        # einem Absturz oder Projektwechsel wieder aufgenommen.
        self._eingang_code_datei: Path | None = None
        self._terminal_eingang_datei: Path | None = None
        self._bild_eingang_datei: Path | None = None
        # Bildanhaenge des gerade laufenden Auftrags - fuer den Fall, dass
        # ihn _fertig() wegen einer Kontingent-Pause fortsetzen muss.
        self._aktuelle_bilder: list[Path] = []
        # Kontingent-Pause (Max-Abo): None ausserhalb einer Pause. Haelt den
        # pausierten Auftrag (Text, Bilder, Bruecken-/Blocknummer) sowie die
        # zuletzt gemeldete Freigabezeit, bis _kontingent_fortsetzen() ihn
        # erneut startet (core/fenster.py, _fertig).
        self._kontingent_info: dict | None = None
        self._kontingent_uhr = QTimer(self)
        self._kontingent_uhr.setSingleShot(True)
        self._kontingent_uhr.timeout.connect(self._kontingent_fortsetzen)
        # Kontingentsperre (Etappe 2, core/kontingentsperre.py): Torwaechter vor
        # jedem Code-Start. Gehaltene Auftraege bleiben in self._warteschlange;
        # der Zeitgeber prueft jede Minute, ob die Sperre gefallen ist.
        self._kontingent_tor = kontingentsperre.Tor()
        # Not-Aus-Pause (core/notaus_pause.py): Zeitgeber fuer das Ende.
        self._notaus_uhr = QTimer(self)
        self._notaus_uhr.setSingleShot(True)
        self._notaus_uhr.timeout.connect(self._notaus_pause_ende)
        self._abbruch_uhr = QTimer(self)
        self._abbruch_uhr.setSingleShot(True)
        self._abbruch_uhr.timeout.connect(self._abbruch_ruhe)
        self._kontingent_sperre_uhr = QTimer(self)
        self._kontingent_sperre_uhr.setInterval(60_000)
        self._kontingent_sperre_uhr.timeout.connect(self._kontingent_sperre_pruefen)
        # Das fremde Fenster, das beim Erkennen der Markierung zuletzt vorn
        # war - dorthin geht das Ergebnis automatisch zurueck (zielfenster.py).
        self._terminal_ziel: tuple | None = None
        # Claude-Lauf und Terminalbefehle haben je einen eigenen Ausgabebereich
        # (self.verlauf bzw. self.terminal_verlauf) und je eine eigene
        # Zustandsanzeige; keiner leert oder ueberschreibt den anderen.
        self._terminal_beginn: datetime | None = None
        self._bild_beginn: datetime | None = None
        self._letzte_terminal_ausgabe = ""
        # Waehrend `_verlauf_anhaengen` schreibt, wandert der Schreibzeiger und
        # loest `_absatz_ansagen` aus. Ohne diese Sperre laese die Stimme jeden
        # einlaufenden Absatz der Antwort mit vor.
        self._verlauf_waechst = False
        self.wechselt = False
        self.start_fenster = None
        self.nur_lesen = False
        # Block 662: kein Modellfeld mehr in der Oberflaeche - der Standard
        # ist immer Sonnet (core/modelle.py, VOREINSTELLUNG), unabhaengig von
        # einstellungen.json. Ein anderes Modell gilt nur fuer genau einen
        # Auftrag ueber die Zeile "#MODELL# name" (_modell_zeile_verarbeiten,
        # _auftrag_starten). Die Liste der waehlbaren Modelle kommt spaeter
        # von Claude Code selbst; bis dahin steht die Rueckfallliste im Feld.
        self.modell = MODELL_VOREINSTELLUNG
        self.modelle: list[dict] = list(MODELLE_RUECKFALL)
        # Block 70, Teil B: (aufgeloester Name, abweichend?, erwarteter Name)
        # der letzten Modell-Ansage - verhindert, dass ein erneuter Verbindungs-
        # aufbau mit unveraendertem Modell (z.B. nach einer Kontingent-Pause)
        # dieselbe Ansage wiederholt.
        self._modell_angesagt: tuple | None = None
        # Block 77, Punkt 1: haelt mit, wieviele der naechsten Meldungen aus
        # _modell_verbunden zu einem einmaligen Modellwechsel fuer genau
        # einen Auftrag gehoeren (Hinwechsel und Ruecklwechsel zum Standard,
        # siehe _auftrag_starten) - sie werden dort stumm gehalten, die eigene
        # Ansage ("Modell X für Block N.") uebernimmt _auftrag_starten selbst.
        self._modell_eigenauftrag_rest = 0
        # Block 77, Punkt 2: wieviele Auftraege aus Eingang/Bruecke/Leitstand
        # (also mit gesetzter eingang_datei, siehe _absenden) in Folge mit
        # einem Fehler endeten - ab 2 laeuft der naechste (dritte) mit Opus,
        # siehe _absenden und _fertig. Ein manuell abgeschickter Auftrag
        # (Zwischenablage/Eingabefeld) zaehlt nicht mit und setzt ihn auch
        # nicht zurueck.
        self._fehlschlaege_eingang_folge = 0
        # Block 77, Punkt 3: Sparmodus bei knappem Wochenkontingent -
        # solange an, laufen nur noch Auftraege mit der Zeile "Dringend: ja"
        # (siehe _absenden), alle anderen sammeln sich in
        # self._sparmodus_wartend statt in self._warteschlange und werden
        # erst eingereiht, wenn die Warnung endet (siehe _sparmodus_setzen).
        self._sparmodus_aktiv = False
        self._sparmodus_wartend: list[WARTESCHLANGEN_EINTRAG] = []
        # Block 36: je eine einmalige Ansage beim Ueberschreiten von 90 %
        # bzw. 95 % Wochenauslastung - zurueckgesetzt, sobald die Auslastung
        # wieder unter 90 % faellt (neue Woche), damit eine spaetere
        # Ueberschreitung erneut angesagt wird. Siehe
        # _kontingent_anzeige_aktualisieren().
        self._kontingent_warnung_90_gegeben = False
        self._kontingent_warnung_95_gegeben = False
        # Auftraege, die abgeschickt wurden, bevor der Arbeitsfaden stand.
        # Sie gehen nicht verloren, sondern laufen los, sobald er da ist.
        self._wartende_auftraege: list[tuple[str, list[Path]]] = []
        # Warteschlange: Auftraege, die abgeschickt wurden, waehrend schon
        # einer lief. Sie werden der Reihe nach abgearbeitet, einer nach dem
        # anderen - nichts geht verloren, nichts blockiert. F4 leert sie. Das
        # dritte Tupelglied ist die Bruecken-auftrag_nummer (None ausser bei
        # einem #CODE#-Auftrag aus der Bruecke, core/bruecke.py), das vierte
        # die Blocknummer (core/bloecke.py, "Block N", None ohne Nummer), das
        # fuenfte die laeuft/-Datei aus dem Eingangsordner (core/
        # eingangsordner.py, Block 70 Teil A, None ausser bei einem Auftrag
        # von dort) - erst abschliessen() auf diese Datei macht den Auftrag
        # endgueltig erledigt, nicht schon das Einreihen hier. Das sechste und
        # siebte Glied sind Modellwunsch und -grund fuer genau diesen einen
        # Auftrag (Block 77, Punkt 1/2, core/bloecke.py "Modell: …" bzw.
        # Hochstufung nach Fehlschlaegen) - beide None ohne Wunsch. Das achte
        # und neunte Glied sind Quelle und Zeitpunkt der Annahme (Block 82,
        # siehe WARTESCHLANGEN_EINTRAG oben).
        self._warteschlange: list[WARTESCHLANGEN_EINTRAG] = []
        # Wahr, solange ein Auftrag beim Arbeitsfaden liegt. Nur daran
        # erkennt _absenden, ob der neue Auftrag warten muss.
        self._auftrag_laeuft = False
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

        self.setWindowTitle(f"CWB {VERSION} — Projekt: {projekt.name}")

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
        self.faden.modell_verbunden_da.connect(self._modell_verbunden)
        self.faden.abgestuerzt_da.connect(self._faden_abgestuerzt)
        self._schliessen_erzwingen = False
        self._letzte_taetigkeit = ""
        self._letzte_taetigkeit_zeit = None

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
        # Modellanzeige von Anfang an sichtbar, auch vor der ersten Verbindung
        # (Block 70, Teil B): zunaechst mit der gemerkten Wahl, _modell_verbunden
        # ersetzt sie durch den tatsaechlich aufgeloesten Namen, sobald die
        # Sitzung steht.
        voll = eintrag_suchen(self.modelle, self.modell).get("voll") or self.modell
        self.ausgabekopf.modell_zeigen(*anzeige_name(voll))
        # Die Warteanzeige steht von Anfang an richtig da: leer, mit
        # verständlicher Beschreibung für den Screenreader.
        self._warteschlange_zeigen()
        # "Trotzdem hier ausführen" gibt es erst, wenn eine Projektwarnung
        # einen Auftrag zurueckgehalten hat.
        self._vormerkung_zeigen(False)
        self._zustell_kachel_zeigen(0)
        self._warte_kachel_zeigen(0)

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

        # Eingangsordner (core/eingangsordner.py, Vorhaben "Bruecke", Stufe
        # B1, siehe wissen/plan_bruecke.md): Auftraege, die als Datei statt
        # ueber die Zwischenablage hereinkommen - Zeitschaltung, von Hand,
        # spaeter die Bruecke zu claude.ai im Browser. Laeuft bei gesperrter
        # Sitzung genauso weiter wie der Arbeitsfaden selbst.
        # Block 63: Namen der fremden Projekte, fuer die zuletzt angesagt
        # wurde, dass Auftraege im Eingang warten - verhindert, dass dieselbe
        # Ansage bei jedem Blick des Waechters (alle paar Sekunden) wiederholt
        # wird. Nur bei Stillstand aktualisiert (siehe _eingang_fremde_melden);
        # laeuft gerade ein Auftrag, bleibt der alte Stand stehen, damit die
        # Ansage nachgeholt wird, sobald wieder Ruhe ist.
        self._eingang_fremde_angesagt: frozenset = frozenset()
        # Block 70, Teil C: der Rohname aus dem Feld "projekt" der aeltesten
        # wartenden Fremddatei, fuer die zuletzt "unbekanntes Projekt"
        # angesagt wurde - verhindert, dass dieselbe Ansage bei jedem Blick
        # wiederholt wird, solange sich daran nichts aendert.
        self._auto_projekt_unbekannt_angesagt: str | None = None
        self.eingang_waechter = Eingangswaechter(
            markierung_erkennen,
            lambda: True,
            lambda: self.projekt.name,
            self._eingang_auftrag,
            self,
            fremde_melden=self._eingang_fremde_melden,
        )
        self.eingang_waechter.starten()

        # Block 70, Teil A: Auftraege aus dem Eingangsordner oder der Bruecke,
        # die beim letzten Mal nicht fertig wurden - sei es durch Absturz,
        # kompletten Neustart (Strg+F4) oder Projektwechsel (F9), der den
        # Faden und die Warteschlange dieses Fensters mitnimmt. Ihre Datei
        # liegt noch in core/eingangsordner.py, laeuft_ordner(), weil nur ein
        # echter Abschluss (abschliessen(), siehe _fertig/_terminal_fertig/
        # _bild_fertig) sie je nach erledigt/ verschiebt - verarbeiten()
        # selbst tut das nicht mehr.
        self._nach_unsauberem_ende_behandeln()
        wieder_aufgenommen, befehle_verworfen, wegen_alter_uebersprungen = wieder_aufnehmen(
            markierung_erkennen, self.projekt.name, self._eingang_auftrag,
            bereits_erledigt=self._bericht_fuer_block_vorhanden)
        if wieder_aufgenommen:
            satz = (f"{wieder_aufgenommen} Aufträge wieder aufgenommen."
                     if wieder_aufgenommen > 1 else "Ein Auftrag wieder aufgenommen.")
            log.info("Beim Start wieder aufgenommen: %d Auftraege", wieder_aufgenommen)
            self._verlauf_anhaengen(satz, "hinweis")
            self.sprecher.sprich(satz, art="hinweis")
        if befehle_verworfen:
            # #RUN#/#ADMIN# werden beim Wiederaufnehmen nie automatisch
            # erneut angestossen (core/eingangsordner.py, wieder_aufnehmen) -
            # sie koennten schon gewirkt oder ein eigenes Programm gestartet
            # haben. Die Datei liegt jetzt in abgelehnt/, der Nutzer entscheidet,
            # ob er sie erneut schickt.
            satz = (f"{befehle_verworfen} Befehle aus dem letzten Mal wurden NICHT "
                     "automatisch wiederholt, bitte bei Bedarf erneut senden."
                     if befehle_verworfen > 1 else
                     "Ein Befehl aus dem letzten Mal wurde NICHT automatisch wiederholt, "
                     "bitte bei Bedarf erneut senden.")
            log.info("Beim Start verworfen: %d #RUN#/#ADMIN#-Befehle", befehle_verworfen)
            self._verlauf_anhaengen(satz, "hinweis")
            self.sprecher.sprich(satz, art="hinweis")
        if wegen_alter_uebersprungen:
            # Block 70, Nachbesserung: core/eingangsordner.py wieder_aufnehmen()
            # hat eine oder mehrere Dateien als vermutlich schon erledigt
            # eingestuft (zu alt oder Bericht zur Blocknummer schon vorhanden)
            # und NICHT erneut angestossen - Begruendung steht im Log.
            satz = (f"{wegen_alter_uebersprungen} Aufträge aus dem letzten Mal wurden als "
                     "vermutlich schon erledigt übersprungen, nicht erneut gestartet."
                     if wegen_alter_uebersprungen > 1 else
                     "Ein Auftrag aus dem letzten Mal wurde als vermutlich schon erledigt "
                     "übersprungen, nicht erneut gestartet.")
            log.info("Beim Start übersprungen (vermutlich schon erledigt): %d Auftraege",
                     wegen_alter_uebersprungen)
            self._verlauf_anhaengen(satz, "hinweis")
            self.sprecher.sprich(satz, art="hinweis")

        # Bruecke zu claude.ai im Browser (core/bruecke.py, Vorhaben
        # "Bruecke" Stufe B3): laeuft nur, solange der Schalter "bruecke_aktiv"
        # an ist (F12 -> Verhalten, Kachel/Umschalt+F8). Ab Werk aus - dieser
        # Aufruf bringt Thread, Kachel und Kopfzeile von Anfang an auf den
        # gemerkten Stand, auch wenn er aus einer frueheren Sitzung noch an war.
        self._bruecke_zustand_anwenden()

        # Leitstand (core/leitstand.py, Block 72): bringt Kachel und
        # Kopfzeile auf den Stand des Schalters "leitstand_aktiv", ohne beim
        # stillen Start selbst etwas anzusagen - reagiert erst nach dem
        # naechsten abgeschlossenen Auftrag.
        self._leitstand_zustand_anwenden()

        # Systemweite Hotkeys fuer den Screenshot (core/pausetaste.py):
        # Pause-Taste und, als zweite Belegung, Strg+Umschalt+B - beide
        # loesen denselben Ablauf wie #BILD# aus, egal welches Fenster
        # gerade vorn ist. Jede der beiden Tasten ist systemweit exklusiv:
        # haelt sie schon ein anderes Programm oder ein vergessenes altes
        # CWB-Fenster, schlaegt nur ihre Registrierung fehl, CWB bleibt
        # bedienbar, nur ohne diese eine Taste (status() in F12 -> Verhalten
        # zeigt, welche der beiden hier tatsaechlich wirkt). Standard AUS
        # (Schalter "pause_screenshot"): angemeldet wird nur, wenn er an ist -
        # sonst bleiben beide Tasten frei fuer das eigenstaendige Werkzeug
        # "Pausetaste" (siehe core/pausetaste.py).
        self._pausetaste = PausenTaste(QApplication.instance(), self._pause_ausgeloest)
        self._pausetaste_zustand_anwenden()

        # Der Fensterbeobachter laeuft ab jetzt mit, nicht erst ab dem ersten
        # #run#/#admin#-Auftrag: sonst haette genau der erste Auftrag einer
        # Sitzung noch kein Zielfenster und das Ergebnis laege nur in der
        # Zwischenablage (siehe zielfenster.py).
        zielfenster.beobachter_starten()

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
            ("Strg+D", "Diktat im Orchestrator aufnehmen oder beenden",
             lambda: self._orch_ansicht is not None
             and self._orch_ansicht.diktat_umschalten()),
            ("F5", "Zum Eingabefeld, nach Projektwarnung oder unvollständigem "
             "Block: trotzdem ausführen", self._f5),
            ("F6", "Bericht-Text kopieren", self._bericht_erneut_kopieren),
            ("Strg+F6", "Berichtordner öffnen", self._berichtordner_oeffnen),
            ("Strg+F7", "Bericht-Datei kopieren", self._berichtdatei_kopieren),
            ("Strg+F8", "Wartende Ergebnisse zustellen", self._ergebnisse_zustellen),
            ("F11", "Zum Claude-Verlauf",
             lambda: self._springe(self.verlauf, "Claude-Verlauf")),
            ("Strg+F11", "Zur Terminal-Ausgabe",
             lambda: self._springe(self.terminal_verlauf, "Terminal-Ausgabe")),
            ("Umschalt+F3", "Terminal-Ausgabe vorlesen", self._terminal_ausgabe_vorlesen),
            ("F1", "Hilfe vorlesen", self._hilfe),
            ("F9", "Projekt wechseln", self._projekt_wechseln),
            ("F4", "Warteschlange leeren", self._warteschlange_leeren),
            ("Umschalt+F4", "Warteschlange einzeln verwalten", self._warteschlange_verwalten),
            ("Strg+F4", "Kompletter Neustart", self._neustart),
            ("F12", "Einstellungen", self._einstellungen_zeigen),
            ("Umschalt+F8", "Brücke ein- oder ausschalten", self._bruecke_umschalten),
            ("Umschalt+F9", "Leitstand ein- oder ausschalten", self._leitstand_umschalten),
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
            (ORCH_SYMBOL, ORCH_KENNUNG, "Strg+O", ORCH_FARBE, self._orch_umschalten),
            ("⏹", "Not-Aus", "F8", "notaus", self._not_aus),
            ("✖", "Ansage abbrechen", "Escape", "ruhig", self.sprecher.schweig),
            ("▶", "Letzte Antwort", "F3", "ruhig", self._antwort_vorlesen),
            # Diese Kachel zeigt den Zustand an, nicht den Befehl: sie heisst
            # so, wie das Schreibrecht gerade steht.
            (ZUGRIFF_SYMBOL_SCHREIBEN, ZUGRIFF_KENNUNG, "F10",
             ZUGRIFF_FARBE_SCHREIBEN, self._nur_lesen_umschalten),
            # Zeigt den Zustand des Schalters "Bruecke" (F12 -> Verhalten),
            # ab Werk aus.
            (BRUECKE_SYMBOL_AUS, BRUECKE_KENNUNG, "Umschalt+F8",
             BRUECKE_FARBE_AUS, self._bruecke_umschalten),
            # Zeigt den Zustand des Schalters "Leitstand" (F12 -> Leitstand),
            # ab Werk aus.
            (LEITSTAND_SYMBOL_AUS, LEITSTAND_KENNUNG, "Umschalt+F9",
             LEITSTAND_FARBE_AUS, self._leitstand_umschalten),
            # Steht nur da, solange ein Auftrag vorgemerkt ist; sonst
            # ausgeblendet (_vormerkung_zeigen).
            (TROTZDEM_SYMBOL, TROTZDEM_KENNUNG, "F5", TROTZDEM_FARBE,
             self._trotzdem_hier),
            ("⧉", "Bericht-Text kopieren", "F6", "ruhig", self._bericht_erneut_kopieren),
            ("📎", "Bericht-Datei kopieren", "Strg+F7", "ruhig", self._berichtdatei_kopieren),
            ("📁", "Berichtordner öffnen", "Strg+F6", "ruhig", self._berichtordner_oeffnen),
            # Steht nur da, solange Ergebnisse auf Zustellung warten
            # (_zustell_kachel_zeigen); sonst ausgeblendet.
            (ZUSTELL_SYMBOL, ZUSTELL_KENNUNG, "Strg+F8", ZUSTELL_FARBE,
             self._ergebnisse_zustellen),
            # Steht nur da, solange etwas wartet (_warte_kachel_zeigen).
            (WARTE_SYMBOL, WARTE_KENNUNG, "Umschalt+F4", WARTE_FARBE,
             self._warteschlange_verwalten),
            ("⏏", "Warteschlange leeren", "F4", "ruhig", self._warteschlange_leeren),
            ("⟳", "Neu starten", "Strg+F4", "neustart", self._neustart),
            ("⇄", "Projekt wechseln", "F9", "ruhig", self._projekt_wechseln),
            ("⚙", "Einstellungen", "F12", "ruhig", self._einstellungen_zeigen),
        ]

    def _kachelvorgabe_migrieren(self) -> None:
        """Einmalig (Stand KACHELN_STAND): stellt die Kachelauswahl auf die
        schlanke Vorgabe um und schaltet Brücke und Leitstand ein. Danach
        gilt nur noch die Wahl des Nutzers."""
        try:
            werte = einstellungen_lesen()
            if int(werte.get("kacheln_stand", 0) or 0) >= KACHELN_STAND:
                return
            werte["sichtbare_kacheln"] = list(KACHELN_VOREINSTELLUNG)
            werte["bruecke_aktiv"] = True
            werte["leitstand_aktiv"] = True
            werte["kacheln_stand"] = KACHELN_STAND
            einstellungen_schreiben(werte)
            log.info("Kachelvorgabe auf Stand %d umgestellt", KACHELN_STAND)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kachelvorgabe nicht umgestellt: %s", fehler)

    def _kacheln_sichtbarkeit_anwenden(self) -> None:
        """Blendet die abschaltbaren Kacheln nach der gemerkten Auswahl ein
        oder aus (Einstellungen, Reiter Kacheln, Schlüssel "sichtbare_kacheln"
        in einstellungen.json). Not-Aus, Zugriffsplakette und "Trotzdem hier
        ausführen" bleiben davon unberührt, ebenso jedes Tastenkürzel."""
        self._kachelvorgabe_migrieren()
        sichtbare = einstellungen_lesen().get("sichtbare_kacheln")
        if not isinstance(sichtbare, list):
            sichtbare = KACHELN_VOREINSTELLUNG
        # Das Ein-/Ausblenden von Kacheln raeumt nur die Kachelreihe neu ein.
        # Die Fenstergroesse wird dabei nicht mehr gemessen und zurueckgesetzt
        # (das war die Quelle unnoetiger resizeEvent-Kaskaden) - die
        # Fenstergroesse aendert sich programmatisch nur noch beim Start
        # (fenster_geometrie_anwenden) und durch aktives Ziehen am Rahmen.
        for name in KACHELN_SCHALTBAR:
            try:
                self.kacheln.kachel_zeigen(name, name in sichtbare)
            except Exception as fehler:  # noqa: BLE001
                log.exception("Kachel-Sichtbarkeit nicht angewendet (%s): %s", name, fehler)
        # Die Orchestrator-Kachel haengt allein am Schalter "orchestrator".
        try:
            self.kacheln.kachel_zeigen(ORCH_KENNUNG, bool(orchestrator.aktiv()))
            self.kacheln.kachel_beschriften(
                ORCH_KENNUNG, ORCH_KENNUNG,
                "Orchestrator. Wechselt zur Orchestrator-Ansicht, Strg O.")
        except Exception as fehler:  # noqa: BLE001
            log.exception("Orchestrator-Kachel nicht eingestellt: %s", fehler)

    def _aufbauen(self) -> None:
        mitte = QWidget()
        mitte.setObjectName("arbeitsflaeche")
        aufbau = QVBoxLayout(mitte)
        # Ohne diese Zeile setzt Qt die Mindestbreite/-hoehe des Fensters
        # automatisch auf die Summe der Breiten aller Kindelemente in voller
        # (ungeskalierter) Schriftgroesse - das Fenster liesse sich dann nie
        # unter diesen Wert ziehen, auch nicht durch Andocken (Windows-Taste
        # + Pfeil) oder die Skalierung des Stilblatts (stil_anwenden), weil
        # die dafuer noetige Groessenaenderung gar nicht erst zugelassen
        # wuerde. SetNoConstraint gibt diese Grenze frei; die Kindelemente
        # (Kachelreihe, Ausgabekopf) weichen bei wenig Platz selbst aus
        # (Umbruch bzw. kuerzere Texte), siehe core/tastenleiste.py und
        # core/kopfzeile.py.
        aufbau.setSizeConstraint(QLayout.SetNoConstraint)

        balken_zeile = QWidget()
        balken_zeile.setObjectName("balkenzeile")
        balken_quer = QHBoxLayout(balken_zeile)
        balken_quer.setContentsMargins(0, 0, 0, 0)

        # Reine Platzflaeche fuer den Waechter-Farbknopf (eigener Prozess,
        # core/waechter_anzeige.py): fest links neben dem Statusbalken, gleich
        # hoch. Mit Ansicht Orchestrator zieht sie neben dessen Titel um
        # (_waechter_platzieren).
        self.waechter_platzhalter = QWidget()
        self.waechter_platzhalter.setObjectName("waechter_platzhalter")
        self.waechter_platzhalter.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._balken_quer = balken_quer
        balken_quer.addWidget(self.waechter_platzhalter, 0, Qt.AlignVCenter)

        self.balken = Aktivitaetsbalken()
        self.balken.setObjectName("balken")
        self.balken.setProperty("zustand", "bereit")
        self.balken.setAccessibleName("Aktivitätsanzeige")
        self._letzter_zustand = "bereit"
        balken_quer.addWidget(self.balken, 1, Qt.AlignVCenter)

        self.zeit_anzeige = QLabel("")
        self.zeit_anzeige.setObjectName("zeitanzeige")
        self.zeit_anzeige.setAccessibleName("Verstrichene Zeit")
        balken_quer.addWidget(self.zeit_anzeige)

        aufbau.addWidget(balken_zeile)

        # Kachelreihe direkt unter dem Balken. Sie teilt die Fensterbreite
        # gleichmaessig unter den Kacheln auf und waechst mit dem Fenster.
        self.kacheln = Kachelreihe(self._kachel_eintraege())
        aufbau.addWidget(self.kacheln)
        self._kacheln_sichtbarkeit_anwenden()

        self._auftrags_beginn: datetime | None = None
        self._auftrags_uhr = QTimer(self)
        self._auftrags_uhr.setInterval(1000)
        self._auftrags_uhr.timeout.connect(self._zeit_aktualisieren)
        # Zustandsanzeigen der beiden Ausgabebereiche, sekundenweise.
        self._bereiche_uhr = QTimer(self)
        self._bereiche_uhr.setInterval(1000)
        self._bereiche_uhr.timeout.connect(self._bereiche_aktualisieren)
        self._bereiche_uhr.start()
        # Herzschlag fuer den blinden Nutzer: jede Minute, solange etwas arbeitet.
        self._herzschlag_uhr = QTimer(self)
        self._herzschlag_uhr.setInterval(60000)
        self._herzschlag_uhr.timeout.connect(self._herzschlag_ansagen)
        self._herzschlag_uhr.start()

        # Eine einzige Kopfzeile ueber dem Ausgabefeld traegt alles, was zum
        # Stand der Arbeit gehoert (core/kopfzeile.py).
        self.ausgabekopf = Ausgabekopf()
        aufbau.addWidget(self.ausgabekopf)
        # Antippen/Anklicken der Warteanzeige oeffnet direkt "Warteschlange
        # verwalten" (Block 60) - derselbe Weg wie Umschalt+F4, nur ohne
        # Tastatur erreichbar.
        self.ausgabekopf.warteanzeige.geklickt.connect(self._warteschlange_verwalten)
        # Merkt sich Schriftart und -groesse, mit der die Kopfzeile zuletzt
        # ausgemessen wurde (siehe changeEvent): so wird bei Stil-Ereignissen
        # ohne echte Schriftaenderung nicht unnoetig neu gemessen.
        self._kopf_schrift_merker = None
        self.ausgabekopf.masse_festlegen()
        # Der Tageszaehler steht schon beim Start richtig da: er kommt aus
        # einstellungen.json und faengt nicht mit jedem Neustart neu an.
        self.ausgabekopf.tag_zeigen(tagesverbrauch_heute())
        # "Such-Effizienz" (Block C10) ebenso: der Verlauf steht schon aus
        # frueheren Auftraegen in einstellungen.json.
        self.ausgabekopf.such_effizienz_zeigen(such_effizienz_prozent())

        # Formatierter Text statt einfachem: nur so lassen sich Auftrag,
        # Antwort und Rueckfrage farblich auseinanderhalten. Die Farben kommen
        # aus verlauf.css, nicht aus dem Python.
        # Block 82: durchgehende Leiste ueber dem Ausgabefeld. LINKS der
        # Platzhalter fuer den Waechter-Farbknopf (core/waechter_anzeige.py,
        # eigener Prozess, siehe _waechter_platzhalter_geometrie/
        # _herzschlag_schreiben), dann "Läuft: ..."/"Wartet: ...". RECHTS die
        # Kontingent-Anzeige (hierher verlegt aus der Kopfzeile, vorher dort
        # core/kopfzeile.py Ausgabekopf.kontingent_zeigen) und ganz aussen der
        # (von hier verschobene, vorher auf self.verlauf schwebende)
        # Kopieren-Knopf. Eine eigene Zeile statt eines Overlays, weil sie
        # mehrere variabel lange Texte tragen muss, die sonst mit dem Knopf
        # kollidieren wuerden.
        statusleiste = QWidget()
        statusleiste.setObjectName("statusleiste")
        statusquer = QHBoxLayout(statusleiste)
        statusquer.setContentsMargins(0, 0, 0, 0)
        # Alle Felder rechts vom Waechter stehen in einer umbrechenden Reihe:
        # reicht die Breite nicht, rueckt ein Feld in die naechste Zeile, statt
        # abgeschnitten zu werden (Sicherheit bei grosser Schrift und schmalem
        # Fenster).
        statusfluss_flaeche = QWidget()
        statusfluss_flaeche.setObjectName("statusfluss")
        statusfluss_flaeche.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        statusfluss = ZeilenFluss(statusfluss_flaeche, abstand=6)
        statusfluss.setContentsMargins(0, 0, 0, 0)
        statusfluss.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        # Reine Platzflaeche: der eigenstaendige Waechter-Prozess legt sich
        # per Fenstergeometrie passgenau darauf (kein Qt-Kind, ein zweiter
        # Prozess ueberlebt auch einen haengenden/abgestuerzten CWB). Ohne
        # eigenen Text/Tooltip - die Farbe und ihr Name stehen am Waechter-
        # Fenster selbst (Barrierefreiheitsname dort). Quadratisch aus
        # stil.qss, oben buendig, wenn die Reihe mehrzeilig wird.
        statusquer.addWidget(statusfluss_flaeche, 1)

        self.laeuft_anzeige = Umbruchfeld("Läuft: –")
        self.laeuft_anzeige.setObjectName("laeuft_anzeige")
        self.laeuft_anzeige.setAccessibleName("Läuft")
        statusfluss.addWidget(self.laeuft_anzeige)

        self.wartet_anzeige = Umbruchfeld("Wartet: –")
        self.wartet_anzeige.setObjectName("wartet_anzeige")
        self.wartet_anzeige.setAccessibleName("Wartet")
        statusfluss.addWidget(self.wartet_anzeige)

        # Kontingent-Zustand (Block 36/37, Felder und Faerbung von hierher
        # aus core/kopfzeile.py verlegt - dort stand nur noch die doppelte
        # Anzeige): Sitzung (Fuenf-Stunden-Fenster) zuerst, dann Woche. Ohne
        # bekannte Prozentzahl steht ein ruhiger Platzhalter statt einer
        # erfundenen Zahl - siehe _kontingent_zeigen.
        self.kontingent_sitzung_anzeige = Umbruchfeld("Sitzung: –")
        self.kontingent_sitzung_anzeige.setObjectName("kontingentsitzunganzeige")
        self.kontingent_sitzung_anzeige.setAccessibleName("Sitzungskontingent")
        statusfluss.addWidget(self.kontingent_sitzung_anzeige)

        self.kontingent_anzeige = Umbruchfeld("Woche: unter Warnschwelle")
        self.kontingent_anzeige.setObjectName("kontingentanzeige")
        self.kontingent_anzeige.setAccessibleName("Wochenkontingent")
        statusfluss.addWidget(self.kontingent_anzeige)

        self.kopieren = QPushButton("⧉ Kopieren")
        self.kopieren.setObjectName("kopieren")
        self.kopieren.setAccessibleName("Ganze Ausgabe kopieren")
        self.kopieren.setToolTip("Ganze Ausgabe kopieren (Strg+K)")
        self.kopieren.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.kopieren.clicked.connect(self._verlauf_kopieren)
        statusfluss.addWidget(self.kopieren)

        aufbau.addWidget(statusleiste)

        # Zwei Bereiche untereinander, je mit eigener Ueberschrift, die
        # zugleich die Zustandsanzeige ist ("Claude: bereit" / "Terminal:
        # laeuft seit 12 Sekunden"). Claude bekommt den groesseren Teil.
        self.claude_zustand = QLabel("Claude: bereit")
        self.claude_zustand.setObjectName("bereichstitel")
        self.claude_zustand.setAccessibleName("Claude Zustand")
        aufbau.addWidget(self.claude_zustand)

        self.verlauf = Ausgabetext()
        self.verlauf.setObjectName("verlauf")
        self.verlauf.setReadOnly(True)
        self.verlauf.setAccessibleName("Claude-Verlauf")
        self.verlauf.document().setDefaultStyleSheet(verlauf_stil_lesen())
        self.verlauf.cursorPositionChanged.connect(self._absatz_ansagen)
        aufbau.addWidget(self.verlauf, 8)

        self.terminal_zustand = QLabel("Terminal: bereit")
        self.terminal_zustand.setObjectName("bereichstitel")
        self.terminal_zustand.setAccessibleName("Terminal Zustand")
        aufbau.addWidget(self.terminal_zustand)

        self.terminal_verlauf = Ausgabetext()
        self.terminal_verlauf.setObjectName("terminal_verlauf")
        self.terminal_verlauf.setReadOnly(True)
        self.terminal_verlauf.setAccessibleName("Terminal-Ausgabe")
        self.terminal_verlauf.document().setDefaultStyleSheet(verlauf_stil_lesen())
        self.terminal_verlauf.cursorPositionChanged.connect(self._absatz_ansagen)
        aufbau.addWidget(self.terminal_verlauf, 4)

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
        for feld in (self.verlauf, self.terminal_verlauf, self.eingabe):
            self._schrift_ausgang.append((feld, QFont(feld.font())))
            feld.installEventFilter(self)
            feld.viewport().installEventFilter(self)

        # Rollbereich als Sicherung: Weil das Fenster kleiner werden darf als
        # die Mindesthoehe der Arbeitsflaeche (SetNoConstraint oben), quetschte
        # Qt die Reihen sonst unter ihre Mindesthoehe, und Kachelreihe,
        # Kopfzeile und Statuszeile lagen uebereinander. Jetzt rollt die
        # Flaeche, sobald der Platz nicht reicht; reicht er, ist nichts zu sehen.
        rolle = QScrollArea()
        rolle.setObjectName("arbeitsrolle")
        rolle.setAccessibleName("Arbeitsfläche")
        rolle.setWidgetResizable(True)
        rolle.setFrameShape(QFrame.NoFrame)
        rolle.setFocusPolicy(Qt.NoFocus)
        rolle.setWidget(mitte)
        self._arbeitsflaeche = rolle
        huelle = QWidget()
        huelle.setObjectName("huelle")
        huellenaufbau = QVBoxLayout(huelle)
        huellenaufbau.setContentsMargins(0, 0, 0, 0)
        self._huelle_layout = huellenaufbau
        if orchestrator.aktiv():
            self._orch_einrichten(rolle)
        else:
            huellenaufbau.addWidget(rolle, 1)
        self.setCentralWidget(huelle)
        # Dieselbe Sperre wie bei `aufbau` oben, jetzt fuer das Fenster
        # selbst: ohne sie uebernaehme QMainWindow die (ungeskalierte)
        # Mindestgroesse von `mitte` unveraendert als eigene, vom
        # Fenstermanager erzwungene Untergrenze - das Fenster liesse sich
        # dann trotz allem nicht auf ein Drittel Bildschirmbreite
        # verkleinern. Stattdessen eine kleine, feste Untergrenze (Block 49):
        # klein genug, dass sie beim Ziel von etwa 600x540 nicht selbst zur
        # Grenze wird.
        if self.layout() is not None:
            self.layout().setSizeConstraint(QLayout.SetNoConstraint)
        self.setMinimumSize(*darstellung.FENSTER_MINDEST)

    def _kuerzel_merken(self, folge: str, ziel) -> None:
        """Schreibt nur die Logzeile, dass die Taste im Fenster angekommen ist.
        Das Ziel haengt als eigene Verbindung am selben Signal und wird nicht
        von hier aus aufgerufen."""
        log.info("Kürzel ausgelöst: %s → %s", folge, getattr(ziel, "__name__", ziel))

    def _tasten(self) -> None:
        # Mit eingeschaltetem Orchestrator sendet Strg+Eingabe je nach Ansicht
        # an Claude Code oder an den Orchestrator (zwei Kuerzel mit derselben
        # Taste wuerden sich gegenseitig sperren). Aus: unveraendert.
        senden_ziel = self._senden_taste if self._orch_ansicht is not None else self._absenden
        kurz = [
            ("Ctrl+Return", senden_ziel),
            ("Ctrl+Enter", senden_ziel),
            ("Esc", self._escape),
            ("F1", self._hilfe),
            ("F2", self._wo_stehen_wir),
            ("F3", self._antwort_vorlesen),
            ("F5", self._f5),
            ("F6", self._bericht_erneut_kopieren),
            ("Ctrl+F6", self._berichtordner_oeffnen),
            ("Ctrl+F7", self._berichtdatei_kopieren),
            ("Ctrl+F8", self._ergebnisse_zustellen),
            ("F11", lambda: self._springe(self.verlauf, "Claude-Verlauf")),
            ("Ctrl+F11", lambda: self._springe(self.terminal_verlauf, "Terminal-Ausgabe")),
            ("Shift+F3", self._terminal_ausgabe_vorlesen),
            ("F8", self._not_aus),
            ("F4", self._warteschlange_leeren),
            ("Shift+F4", self._warteschlange_verwalten),
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
            ("Shift+F8", self._bruecke_umschalten),
            ("Shift+F9", self._leitstand_umschalten),
            ("Ctrl+Shift+K", self._kontingent_freigeben),
            ("Return", self._enter),
        ]
        if self._orch_ansicht is not None:
            kurz.append(("Ctrl+O", self._orch_umschalten))
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
        if taetigkeit:
            name = Path(pfad).name if pfad else ""
            self._letzte_taetigkeit = f"{taetigkeit} {name}".strip()
            self._letzte_taetigkeit_zeit = datetime.now()
            self._band_beschreibung_aktualisieren()

    def _auftrag_aktiv(self) -> bool:
        """Wahr, solange dieses Fenster irgendeinen Auftrag abarbeitet - einen
        Claude-Auftrag (#CODE#, self._auftrag_laeuft) oder einen Terminal-/
        Admin-Befehl bzw. Screenshot (#RUN#/#ADMIN#/#BILD#, eigene Faeden).
        Einzige Stelle, die der Herzschlag fuer core/waechter_anzeige.py
        (Modulende dieser Datei, _herzschlag_schreiben) befragt."""
        return self._laeuft()

    def _code_laeuft(self) -> bool:
        """Wahr, solange ein Claude-Auftrag (#CODE#) belegt ist: der Arbeitsfaden
        meldet sich beschaeftigt, das Fenster hat einen Auftrag uebergeben
        (`_auftrag_laeuft`, schon vor der ersten Rueckmeldung des Fadens) oder
        die Sitzung wartet auf ein erschoepftes Kontingent."""
        faden = getattr(self, "faden", None)
        return bool(
            getattr(faden, "faden_beschaeftigt", False)
            or getattr(self, "_auftrag_laeuft", False)
            or getattr(self, "_kontingent_info", None) is not None
        )

    def _bericht_laedt_hoch(self) -> bool:
        """Wahr, solange ein Bruecken- oder Nachtbericht noch hochgeladen wird."""
        for liste in (getattr(self, "_bruecke_berichte", ()),
                      getattr(self, "_nachtberichte", ())):
            for faden in list(liste):
                try:
                    if faden.isRunning():
                        return True
                except Exception as fehler:  # noqa: BLE001
                    log.exception("Hochladefaden nicht befragt: %s", fehler)
        return False

    def _arbeit_laeuft(self) -> bool:
        """Wie `_laeuft`, aber ohne Berichtupload: das, was ein Abbruch
        (Projektwechsel, Schliessen) tatsaechlich beenden muss."""
        try:
            return bool(
                self._code_laeuft()
                or (self._terminal_faden is not None and self._terminal_faden.isRunning())
                or (self._bild_faden is not None and self._bild_faden.isRunning())
            )
        except Exception as fehler:  # noqa: BLE001
            log.exception("Laufzustand nicht bestimmbar: %s", fehler)
            return True  # im Zweifel gilt: es laeuft - lieber warten als doppelt starten

    def _laeuft(self) -> bool:
        """EINZIGE Wahrheit darueber, ob dieses Fenster arbeitet: Claude-Auftrag,
        Terminal- oder Bildlauf oder ein offener Berichtupload. Band, Kopfzeile,
        F2, `_absenden` und der Projektwechsel lesen nur diesen Wert."""
        return self._arbeit_laeuft() or self._bericht_laedt_hoch()

    def _laeuft_art(self) -> str:
        """Art dessen, was gerade laeuft - fuer F2 und den Herzschlag."""
        if self._code_laeuft():
            return "Code"
        if self._terminal_faden is not None and self._terminal_faden.isRunning():
            return "Admin" if getattr(self._terminal_faden, "art", "") == "admin" else "Run"
        if self._bild_faden is not None and self._bild_faden.isRunning():
            return "Bild"
        if self._bericht_laedt_hoch():
            return "Berichtupload"
        return ""

    @staticmethod
    def _dauer_wort(sekunden: int) -> str:
        if sekunden < 60:
            return f"{sekunden} Sekunden"
        minuten = sekunden // 60
        return "einer Minute" if minuten == 1 else f"{minuten} Minuten"

    def _laeuft_satz(self) -> str:
        """Der Satz fuer F2, solange etwas laeuft: Nummer, Art, Projekt, seit wann."""
        sekunden = self._sekunden_seit_beginn(self._laeuft_art())
        satz = (f"Es läuft {self._laeuft_kennung()}, Art {self._laeuft_art()}, "
                f"Projekt {self.projekt.name}, seit {self._dauer_wort(sekunden)}.")
        zuletzt = getattr(self, "_letzte_taetigkeit", "")
        if zuletzt:
            satz += f" Zuletzt: {zuletzt}."
        return satz

    # -- Projektwechsel/Schliessen bei laufendem Auftrag ---------------------

    FADEN_ENDE_WARTEZEIT_MS = 30000

    def _abbruch_bestaetigen(self, frage: str) -> bool:
        """Fragt (gesprochen und als Dialog), ob der laufende Auftrag abgebrochen
        werden darf. Vorgabe ist Nein."""
        try:
            self.sprecher.sprich(frage, art="frage")
            antwort = QMessageBox.question(
                self, "CWB", frage, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            return antwort == QMessageBox.Yes
        except Exception as fehler:  # noqa: BLE001
            log.exception("Abbruchfrage fehlgeschlagen: %s", fehler)
            return False

    def _laeuft_beenden(self, anlass: str) -> bool:
        """Wahr, wenn nichts mehr laeuft und der Wechsel/das Schliessen
        weitergehen darf. Laeuft etwas, wird NICHT still weitergemacht: erst
        fragen, dann Not-Aus, wartende Auftraege im Faden verwerfen und auf das
        echte Ende des Fadens warten. Endet er nicht, bleibt es bei Falsch -
        es startet nie ein zweiter Lauf neben dem alten."""
        try:
            if not self._arbeit_laeuft():
                return True
            nummer = getattr(self, "_laufender_block_nummer", None)
            name = f"Auftrag {nummer}" if nummer is not None else "Ein Auftrag"
            if not self._abbruch_bestaetigen(f"{name} läuft noch. Abbrechen und {anlass}?"):
                log.info("%s abgelehnt: Auftrag laeuft noch", anlass)
                return False
            auftragsjournal.schreibe("abgebrochen", f"grund={anlass}", ohne_kontext=True)
            faden = self.faden
            if self._terminal_faden is not None and self._terminal_faden.isRunning():
                self._terminal_faden.not_aus()
            faden.not_aus()
            faden.frage_beantworten(False)   # gibt eine offene Rueckfrage frei
            faden.wartende_verwerfen()
            faden.beenden()
            ende = faden.wait(self.FADEN_ENDE_WARTEZEIT_MS)
            for nebenfaden in (self._terminal_faden, self._bild_faden):
                if nebenfaden is not None and nebenfaden.isRunning():
                    ende = nebenfaden.wait(self.FADEN_ENDE_WARTEZEIT_MS) and ende
            if not ende:
                log.error("Lauf endete nicht innerhalb von %d ms (%s)",
                          self.FADEN_ENDE_WARTEZEIT_MS, anlass)
                self._schliessen_erzwingen = True
                self.sprecher.sprich(
                    "Der Auftrag lässt sich nicht beenden, es wird nicht gewechselt.",
                    art="fehler")
                return False
            return True
        except Exception as fehler:  # noqa: BLE001
            log.exception("Laufenden Auftrag nicht beendet (%s): %s", anlass, fehler)
            self._schliessen_erzwingen = True
            return False

    def _faden_abgestuerzt(self, fehler: str) -> None:
        """Der Arbeitsfaden ist tot: Zustand zuruecksetzen, Warteschlange
        freigeben (Dateien im Eingang bleiben in laeuft/ und laufen nach dem
        Neustart weiter), ansagen."""
        try:
            nummer, self._bruecke_code_nummer = self._bruecke_code_nummer, None
            self._auftrag_laeuft = False
            self._aktueller_block_nummer = None
            self._eingang_code_datei = None
            self._auftrags_uhr.stop()
            self.balken.animation_stoppen()
            self._zustand_zeigen("fehler")
            verworfen = len(self._warteschlange) + len(self._sparmodus_wartend)
            self._warteschlange.clear()
            self._sparmodus_wartend = []
            self._warteschlange_zeigen()
            if nummer is not None:
                self._bruecke_bericht_hochladen(
                    nummer, f"Arbeitsfaden abgestürzt: {fehler}. Bitte CWB neu starten.")
            self._bruecke_protokoll_ablegen(
                f"Arbeitsfaden abgestürzt: {fehler}", "fehler", nummer, "Arbeitsfaden abgestürzt")
            satz = "Arbeitsfaden abgestürzt."
            if verworfen:
                satz += f" {verworfen} wartende Aufträge freigegeben."
            satz += " Bitte CWB neu starten."
            auftragsjournal.schreibe("fehler", f"faden abgestuerzt: {fehler}"[:120],
                                     ohne_kontext=True)
            self._status_zeigen(satz)
            self._verlauf_anhaengen(satz, "fehler")
            self.sprecher.sprich(satz, art="fehler")
            self._statusleiste_aktualisieren()
        except Exception as fehler2:  # noqa: BLE001
            log.exception("Fadenabsturz nicht aufgefangen: %s", fehler2)

    def _herzschlag_ansagen(self) -> None:
        """Alle 60 Sekunden, solange ein Auftrag arbeitet: kurze Ansage fuer
        den blinden Nutzer. Abschaltbar (Einstellungen, Verhalten)."""
        try:
            if not self._arbeit_laeuft():
                return
            self._band_beschreibung_aktualisieren()
            if not einstellungen_lesen().get("herzschlag_ansage", True):
                return
            teile = []
            if self._code_laeuft():
                sekunden = self._sekunden_seit_beginn("Code")
                if sekunden >= 55:
                    satz = f"Claude läuft seit {self._dauer_wort(sekunden)}"
                    zuletzt = getattr(self, "_letzte_taetigkeit", "")
                    teile.append(satz + (f", zuletzt {zuletzt}." if zuletzt else "."))
            if self._terminal_aktiv():
                sekunden = self._sekunden_seit_beginn("Run")
                if sekunden >= 55:
                    teile.append(f"Terminal läuft seit {self._dauer_wort(sekunden)}.")
            if teile:
                self.sprecher.sprich(" ".join(teile), unterbrechen=False, art="immer")
        except Exception as fehler:  # noqa: BLE001
            log.exception("Herzschlag-Ansage fehlgeschlagen: %s", fehler)

    def _band_beschreibung_aktualisieren(self) -> None:
        """Zugaenglichkeitstext des Bandes: was zuletzt war und seit wann."""
        try:
            zuletzt = getattr(self, "_letzte_taetigkeit", "")
            zeit = getattr(self, "_letzte_taetigkeit_zeit", None)
            teile = []
            if self._code_laeuft():
                teile.append(f"Claude läuft seit {self._dauer_wort(self._sekunden_seit_beginn())}.")
            if self._terminal_aktiv():
                teile.append("Terminal läuft seit "
                             f"{self._dauer_wort(self._sekunden_seit_beginn('Run'))}.")
            if zuletzt:
                um = zeit.strftime("%H:%M:%S") if zeit else "unbekannt"
                teile.append(f"Zuletzt: {zuletzt} um {um}.")
            self.balken.setAccessibleDescription(" ".join(teile))
        except Exception as fehler:  # noqa: BLE001
            log.exception("Band-Beschreibung nicht gesetzt: %s", fehler)

    def _sekunden_seit_beginn(self, art: str = "Code") -> int:
        """Sekunden seit Start der Quelle `art` (Code, Run/Admin, Bild)."""
        merker = {"Code": "_auftrags_beginn", "Run": "_terminal_beginn",
                  "Admin": "_terminal_beginn", "Bild": "_bild_beginn"}.get(art, "")
        beginn = getattr(self, merker, None) if merker else None
        return max(0, int((datetime.now() - beginn).total_seconds())) if beginn else 0

    def _laeuft_seit_minuten(self) -> int:
        beginn = getattr(self, "_auftrags_beginn", None)
        if beginn is None:
            return 0
        return max(0, int((datetime.now() - beginn).total_seconds() // 60))

    def _auftrag_kurz(self) -> str:
        """Kurze Bezeichnung des laufenden Auftrags fuer den Herzschlag -
        nur zur Anzeige/zum Nachsehen, nichts haengt an ihrem genauen Text."""
        if self._auftrag_laeuft:
            return self.balken.text.text() or "Claude-Auftrag"
        if self._terminal_faden is not None and self._terminal_faden.isRunning():
            return "Terminalbefehl"
        if self._bild_faden is not None and self._bild_faden.isRunning():
            return "Screenshot"
        return ""

    def _zugriff_zeigen(self) -> None:
        """Bringt Kachel und Kopfzeile auf den geltenden Zustand. Die Kachel
        nennt und faerbt ihn als einzige dauerhafte Anzeige; die Kopfzeile
        haengt den Zustand nur an die gesprochene Statusmeldung."""
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
        satz = f"CWB, Version {VERSION}. " \
               "Unter dem Balken liegen die Kacheln mit den häufigsten Befehlen. " \
               "Alle Befehle mit Tastenkürzel: " + " ".join(
            f"{taste}: {beschriftung}." for taste, beschriftung, _ in self._leisten_eintraege()
        ) + " Pause oder Strg+Umschalt+B: Screenshot vom Telefon, systemweit, " \
            "unabhängig vom Fenster."
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
                pausetaste_status=self._pausetaste.status(),
            )
        except Exception as fehler:  # noqa: BLE001
            log.exception("Einstellungen nicht geöffnet: %s", fehler)
            self.sprecher.sprich("Einstellungen konnten nicht geöffnet werden.",
                                 art="fehler")
            return
        self.sprecher.sprich("Einstellungen.")
        fenster.exec()
        self._sicherheitshinweis_aktualisieren()
        self._kacheln_sichtbarkeit_anwenden()
        if notaus_pause.von_hand_geaendert(einstellungen_lesen()):
            self._notaus_pause_abbrechen()
        self._bruecke_zustand_anwenden()
        self._leitstand_zustand_anwenden()
        self._pausetaste_zustand_anwenden()

    def _wo_stehen_wir(self) -> None:
        # Block 82: "Läuft: ..."/"Wartet: ..." gehoert zu fenster.py (mehrere
        # Warteschlangen, Eingangsordner), nicht zu Sitzung.stand() - darum
        # hier angehaengt statt dort eingebaut.
        sitzung = self.faden.sitzung
        if self._laeuft():
            # Nie "Nichts laeuft", solange die Leiste "Läuft: N" zeigt.
            satz = self._laeuft_satz()
            if sitzung is not None and getattr(sitzung, "laeuft", False):
                satz += f" {sitzung.stand()}"
        elif sitzung:
            satz = sitzung.stand()
        else:
            satz = "Noch nicht verbunden."
        self.sprecher.sprich(f"{satz} {self._statusleiste_satz()}", art="immer")

    def _antwort_vorlesen(self) -> None:
        self.sprecher.sprich(self.letzte_antwort or "Keine Antwort vorhanden.",
                             art="immer")

    def _terminal_ausgabe_vorlesen(self) -> None:
        """Umschalt+F3: liest die letzte Terminalausgabe vor (F3 liest Claude)."""
        self.sprecher.sprich(
            self._letzte_terminal_ausgabe or "Keine Terminal-Ausgabe vorhanden.",
            art="immer")

    def _markiertes_vorlesen(self) -> None:
        for feld in (self.verlauf, self.terminal_verlauf, self.eingabe):
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
                                 art="fehler")
            return
        self.sprecher.sprich("Schriftgröße zurückgesetzt.")

    def _verlauf_kopieren(self) -> None:
        # Kopiert den Bereich, in dem der Fokus steht; sonst den Claude-Verlauf.
        feld, name = self.verlauf, "Claude-Ausgabe"
        if self.terminal_verlauf.hasFocus():
            feld, name = self.terminal_verlauf, "Terminal-Ausgabe"
        text = feld.toPlainText()
        if not text.strip():
            self.sprecher.sprich(f"{name} ist leer.")
            return
        QGuiApplication.clipboard().setText(text)
        self.sprecher.sprich(f"{name} kopiert.")

    def _absatz_ansagen(self) -> None:
        """Liest den Absatz vor, auf den der Nutzer im Ausgabefeld springt.

        Nur bei eigener Bewegung: waehrend einlaufender Text angehaengt wird,
        wandert der Zeiger von allein - dann bleibt es still, sonst wuerde die
        Antwort doch wieder automatisch vorgelesen."""
        feld = next((f for f in (self.verlauf, self.terminal_verlauf) if f.hasFocus()), None)
        if self._verlauf_waechst or feld is None:
            return
        zeile = feld.textCursor().block().text().strip()
        if zeile:
            self.sprecher.sprich(zeile)

    def _escape(self) -> None:
        # Laeuft noch eine Ansage, bricht der erste Druck nur sie ab - sonst
        # wuerde er ungewollt zugleich eine offene Rueckfrage mit Nein
        # beantworten, noch bevor die Rueckfrage ueberhaupt zu Ende gesprochen ist.
        if self.frage_offen and not self.sprecher.spricht():
            self._frage_beantworten(False)
            return
        if _orch_frage_offen(self) and not self.sprecher.spricht():
            self._orch_ansicht.frage_beantworten(False)
            return
        if self._pending_block is not None and not self.sprecher.spricht():
            self._block_verwerfen()
            return
        self.sprecher.schweig()

    def _enter(self) -> None:
        if self.frage_offen:
            self._frage_beantworten(True)
        elif _orch_frage_offen(self):
            self._orch_ansicht.frage_beantworten(True)

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
        self.sprecher.melde("wartet", kurz_satz, sprechen=True, art="frage")

    @slot_geschuetzt
    def _frage_beantworten(self, ja: bool) -> None:
        self.frage_offen = False
        self._verlauf_anhaengen("Freigegeben." if ja else "Abgelehnt.", "hinweis")
        self._status_zeigen("Freigegeben." if ja else "Abgelehnt.")
        self.sprecher.sprich("Ja." if ja else "Nein.")
        if self._pending_terminal is not None:
            wartend, self._pending_terminal = self._pending_terminal, None
            if ja:
                self._terminal_starten(wartend["befehl"], wartend["admin"],
                                        bruecke_nummer=wartend.get("bruecke_nummer"),
                                        eingang_datei=wartend.get("eingang_datei"),
                                        block_nummer=wartend.get("block_nummer"),
                                        quelle=wartend.get("quelle", ""))
            elif wartend.get("eingang_datei") is not None:
                verwerfen(wartend["eingang_datei"], "Rückfrage mit Nein beantwortet")
            return
        self.faden.frage_beantworten(ja)

    # -- Terminal (#run# und #admin#) ---------------------------------------

    def _terminal_markierung(self, art: str, befehl: str, *,
                              bruecke_nummer: int | None = None,
                              eingang_datei: Path | None = None,
                              block_nummer: int | None = None,
                              quelle: str = "Eingabe") -> None:
        """Verarbeitet einen #run#- oder #admin#-Auftrag. Laeuft nie ueber
        Claude Code: kein Modellaufruf, kein Tokenverbrauch. Ordnergrenze,
        verbotene Befehle und Sperrliste aus core/sicherheit.py gelten
        unveraendert; #admin# fragt mit dem vollen Befehl zurueck, bevor er
        mit erhoehten Rechten laeuft - aber nur, wenn der Schalter
        rueckfrage_bei_befehl an ist. `bruecke_nummer` kommt nur aus der
        Bruecke (core/bruecke.py) und wird bis zum Abschluss mitgefuehrt,
        auch ueber eine Rueckfrage hinweg (siehe _pending_terminal).
        `block_nummer`/`quelle` (Block 82) dienen nur der Anzeige ("Läuft: ...",
        core/fenster.py _laeuft_kennung) und werden ebenso durch eine
        Rueckfrage hindurch mitgefuehrt."""
        # Das fremde Fenster, aus dem der Auftrag kam (Zwischenablage,
        # Waechter oder das Fenster, aus dem gerade zu CWB gewechselt wurde),
        # steht jetzt fest - CWB selbst ist zu diesem Zeitpunkt im
        # Vordergrund und darf hier nicht mit gemerkt werden.
        self._terminal_ziel = (zielfenster.fenster_merken() if zielfenster.UNTER_WINDOWS
                               else einfueger.ziel_merken())
        befehl = befehl.strip()
        if not befehl:
            self.sprecher.sprich("Nach der Markierung steht kein Befehl.", art="fehler")
            if eingang_datei is not None:
                verwerfen(eingang_datei, "Nach der Markierung stand kein Befehl")
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
            self.sprecher.sprich(kurzfassen(satz), art="fehler")
            if eingang_datei is not None:
                verwerfen(eingang_datei, satz)
            return
        rueckfrage_an = einstellungen_lesen().get("rueckfrage_bei_befehl", False)
        if (admin or urteil.stufe is Stufe.RUECKFRAGE) and rueckfrage_an:
            grund = "Admin-Befehl mit erhöhten Rechten" if admin else urteil.begruendung
            satz = f"{grund}: {befehl}. Fortfahren?"
            kurz_satz = f"{grund}. Fortfahren?"
            self._pending_terminal = {"befehl": befehl, "admin": admin,
                                       "bruecke_nummer": bruecke_nummer,
                                       "eingang_datei": eingang_datei,
                                       "block_nummer": block_nummer, "quelle": quelle}
            self._frage(satz, kurz_satz)
            return
        self._terminal_starten(befehl, admin, bruecke_nummer=bruecke_nummer,
                                eingang_datei=eingang_datei, block_nummer=block_nummer,
                                quelle=quelle)

    def _terminal_starten(self, befehl: str, admin: bool, *,
                           bruecke_nummer: int | None = None,
                           eingang_datei: Path | None = None,
                           block_nummer: int | None = None,
                           quelle: str = "Eingabe") -> None:
        if self._terminal_faden is not None and self._terminal_faden.isRunning():
            self.sprecher.sprich("Es läuft schon ein Terminalbefehl.", art="fehler")
            if eingang_datei is not None:
                verwerfen(eingang_datei, "Terminal war beim Start belegt")
            return
        self._terminal_bruecke_nummer = bruecke_nummer
        self._terminal_eingang_datei = eingang_datei
        # Block 82: Kennung fuer "Läuft: ..." - siehe Docstring von
        # self._laufender_block_nummer in __init__.
        self._laufender_block_nummer = block_nummer
        self._laufender_quelle = quelle
        self._laufender_zeit = datetime.now()
        self._terminal_beginn = self._laufender_zeit
        self._statusleiste_aktualisieren()
        art = "admin" if admin else "run"
        satz = "Admin-Befehl läuft…" if admin else "Terminalbefehl läuft…"
        log.info("Terminalbefehl gestartet (%s): %s", art, befehl)
        # Diese Methode ist der einzige Weg, auf dem ein Terminalbefehl
        # losgeht - egal ob #run# oder #admin#, aus dem Eingabefeld, aus der
        # Zwischenablage, vom Waechter, nach einer Rueckfrage oder aus einer
        # Vormerkung. Darum steht das Leeren genau hier und nirgends sonst -
        # und leert nur den Terminalbereich, nie den Claude-Verlauf.
        self._ausgabe_leeren(f"Terminalbefehl ({art})", self.terminal_verlauf)
        self._verlauf_anhaengen(befehl, "terminal")
        self._status_zeigen(satz)
        self.sprecher.sprich(satz, art="meldung")  # stumm: Zwischenmeldung
        _journal_beginnt(self, art, bruecke_nummer, block_nummer)
        self._terminal_faden = TerminalFaden(art, befehl, self.projekt.pfad, self)
        self._terminal_faden.fertig_da.connect(self._terminal_fertig)
        self._terminal_faden.teil_da.connect(self._terminal_teil)
        self._terminal_faden.admin_wartet_auf_uac.connect(self._admin_uac_hinweis)
        self._terminal_faden.start()

    @slot_geschuetzt
    def _admin_uac_hinweis(self) -> None:
        """Ertoent, kurz bevor Windows den UAC-Dialog fuer den erhoehten
        Admin-Worker zeigt - macht hoerbar, dass jetzt eine Reaktion noetig
        ist, statt dass CWB scheinbar haengt."""
        self.sprecher.ton("wartet")
        self.sprecher.sprich("Bitte Rechteanforderung von Windows bestätigen.", art="meldung")

    @slot_geschuetzt
    def _terminal_teil(self, zeile: str) -> None:
        """Nur bei #run#: eine Ausgabezeile, waehrend der Befehl noch laeuft.
        #admin# laeuft im erhoehten Worker-Prozess ohne verbundene Rohre und
        meldet sich erst am Ende ueber _terminal_fertig."""
        zeile = zeile.rstrip("\n")
        if zeile:
            self._verlauf_anhaengen(zeile, "terminal")

    @slot_geschuetzt
    def _terminal_fertig(self, ergebnis) -> None:
        # Block 82: "Läuft: ..." zeigt wieder "–", sobald self._terminal_faden
        # nicht mehr laeuft (_laeuft_kennung prueft das zuerst).
        self._statusleiste_aktualisieren()
        # Gehoerte der Befehl zur Bruecke (core/bruecke.py), wird die Ausgabe
        # weiter unten zusaetzlich dorthin hochgeladen - die Rueckspielung ins
        # zuletzt aktive fremde Fenster (Zwischenablage + Strg+V) laeuft
        # trotzdem mit, genau wie bei allen anderen Wegen.
        bruecke_nummer, self._terminal_bruecke_nummer = self._terminal_bruecke_nummer, None
        # Block 70, Teil A: der Befehl ist jetzt wirklich fertig (Erfolg oder
        # Fehler) - erst jetzt gilt sein Eingangsordner-Auftrag als erledigt.
        eingang_datei, self._terminal_eingang_datei = self._terminal_eingang_datei, None
        if eingang_datei is not None:
            abschliessen(eingang_datei)
        text = ergebnis.ausgabe or ergebnis.fehler or "(keine Ausgabe)"
        kopf = "Terminalausgabe" if ergebnis.erfolg else f"Terminalausgabe (Fehler, Code {ergebnis.code})"
        orch = _orch_ist(self, eingang_datei)
        _orch_bericht(self, eingang_datei, f"{kopf}:\n{text}",
                      status="fertig" if ergebnis.erfolg else "Fehler", art="RUN")
        log.info("Terminalbefehl beendet, Erfolg=%s, Code=%s", ergebnis.erfolg, ergebnis.code)
        _journal_endet(self, bruecke_nummer, self._laufender_block_nummer, None,
                            f"erfolg={'ja' if ergebnis.erfolg else 'nein'} code={ergebnis.code}")
        if not ergebnis.erfolg:
            auftragsjournal.schreibe("fehler", f"terminalbefehl code={ergebnis.code}",
                                     nummer=bruecke_nummer, block=self._laufender_block_nummer)
        self._verlauf_anhaengen(f"{kopf}:\n{text}", "terminal")
        self._letzte_terminal_ausgabe = text
        satz = "Terminalbefehl fertig." if ergebnis.erfolg else "Terminalbefehl fehlgeschlagen."
        befehl_lief = self._terminal_faden.befehl if self._terminal_faden else ""
        marker_treffer = next(
            (m for m in BEFEHLE_OHNE_TEXT_RUECKSPIELUNG if m in befehl_lief), None
        )
        bild_bleibt = ergebnis.erfolg and marker_treffer is not None
        if marker_treffer and not ergebnis.erfolg:
            log.info(
                "Text-Rueckspielung NICHT uebersprungen: Marker '%s' im Befehl gefunden, "
                "aber Befehl fehlgeschlagen (Code %s): %s",
                marker_treffer, ergebnis.code, befehl_lief,
            )
        elif bild_bleibt:
            log.info(
                "Text-Rueckspielung uebersprungen: Marker '%s' im Befehl gefunden: %s",
                marker_treffer, befehl_lief,
            )
        else:
            log.info(
                "Text-Rueckspielung normal ausgefuehrt: kein Marker aus "
                "BEFEHLE_OHNE_TEXT_RUECKSPIELUNG im Befehl gefunden: %s",
                befehl_lief,
            )
        if bruecke_nummer is not None:
            # Hochladen an die Bruecke - zusaetzlich zur Rueckspielung unten,
            # nicht statt ihr (wissen/plan_bruecke.md, Stufe B3).
            self._bruecke_bericht_hochladen(bruecke_nummer, text)
        # Ergebnis geht automatisch in das Fenster zurueck, aus dem der
        # Auftrag kam (siehe zielfenster.py) - das gilt gleich fuer Auftraege
        # aus dem Eingabefeld, der Zwischenablage und der Bruecke. Ist beim
        # Auftragsstart keins gemerkt worden, nimmt zielfenster.einfuegen()
        # das zuletzt bekannte Ziel. Nur wenn noch nie eins bekannt war,
        # bleibt das Ergebnis in der Zwischenablage liegen.
        if orch:
            # Orchestrator-Auftrag: das Ergebnis liegt im Berichtsspeicher
            # (bericht_holen), nichts wird in ein fremdes Fenster eingefuegt.
            satz += " Ergebnis an den Orchestrator."
        elif bild_bleibt:
            # Das Skript hat sein Bild schon selbst in die Zwischenablage
            # gelegt - die Text-Rueckspielung wuerde es sofort wieder mit der
            # gedruckten Meldung ueberschreiben, darum bleibt sie hier aus.
            satz += " Bild liegt in der Zwischenablage."
        elif (len(text) > zustellwache.TERMINAL_KURZ_GRENZE
              and zugangsdaten_lesen() is not None):
            # Zu lang fuer den Chat: Volltext ins Ablagefach, in den Chat nur
            # die Kurzmeldung (mit Protokollnummer, sobald abgelegt).
            ziel, block, erfolg = self._terminal_ziel, self._laufender_block_nummer, ergebnis.erfolg
            projekt, zeichen = self.projekt.name, len(text)

            def senden(protokoll) -> None:
                meldung = zustellwache.kurzmeldung_terminal(
                    bruecke_nummer, projekt, block, erfolg, protokoll, zeichen)
                self._terminal_einfuegen(bruecke_nummer, block, ziel, meldung)

            self._bruecke_protokoll_ablegen(text, "build", bruecke_nummer,
                                            "Terminalergebnis", danach=senden)
            satz += " Langes Ergebnis im Ablagefach, Kurzmeldung geht in den Chat."
        else:
            eingefuegt = self._terminal_einfuegen(
                bruecke_nummer, self._laufender_block_nummer, self._terminal_ziel, text)
            if eingefuegt is True:
                satz += " Ergebnis eingefügt."
            elif eingefuegt is False:
                satz += " Ergebnis liegt in der Zwischenablage."
        if bruecke_nummer is not None:
            satz += " Auch an Brücke hochgeladen."
        self._terminal_ziel = None
        self._status_zeigen(satz)
        # Abschluss eines #run#/#admin#-Auftrags - die eine Ansage am Ende.
        if zielfenster.UNTER_WINDOWS:
            self.sprecher.sprich(satz, art="fertig" if ergebnis.erfolg else "fehler")
        else:
            self._ansage_sammeln(satz, ergebnis.erfolg)
        self._bereiche_aktualisieren(terminal_fertig=True)

    def _terminal_einfuegen(self, bruecke_nummer, block, ziel, text: str):
        """Fuegt ein Terminalergebnis (oder seine Kurzmeldung) ins Chatfenster
        ein. Windows: True/False je nach Erfolg. Linux: Warteschlange, ein
        Ergebnis nach dem anderen (None); die Ansage kommt gesammelt aus
        _einfuegen_fertig."""
        if zielfenster.UNTER_WINDOWS:
            return bool(zielfenster.einfuegen(ziel, text))
        zugestellt = None
        if bruecke_nummer is not None:
            zugestellt = self._zustellen_versuchen(bruecke_nummer, "run", text, ziel)
        if zugestellt is None:
            _einfuegen_mit_kennung(
                self._einfueger_holen(), ziel, text,
                auftragsjournal.kennung(bruecke_nummer, block, "run"))
        return None

    # -- Ergebnisse einfuegen (Linux) ----------------------------------------

    def _einfueger_holen(self):
        """Legt die Einfuege-Warteschlange beim ersten Gebrauch an."""
        if getattr(self, "_einfueger", None) is None:
            self._einfueger = einfueger.Einfueger(
                einfueger.XdotoolWerkzeug(),
                _QtZwischenablage(),
                lambda ms, funktion: QTimer.singleShot(ms, funktion),
                lambda: bool(einstellungen_lesen().get("ergebnis_enter", True)),
                self._einfuegen_fertig,
                zielfenster.bild_in_zwischenablage_legen,
            )
            self._ansagen: list = []
            self._ablage_hinweis = False
            self._ansage_zeitgeber = QTimer(self)
            self._ansage_zeitgeber.setSingleShot(True)
            self._ansage_zeitgeber.timeout.connect(self._ansage_sprechen)
        return self._einfueger

    def _einfuegen_fertig(self, erfolge: int, gescheitert: list) -> None:
        if gescheitert:
            self._ablage_hinweis = True
            self._ansage_zeitgeber.start(ANSAGE_SAMMELZEIT_MS)


    def _ansage_sammeln(self, satz: str, erfolg: bool) -> None:
        self._einfueger_holen()
        self._ansagen.append((satz, erfolg))
        self._ansage_zeitgeber.start(ANSAGE_SAMMELZEIT_MS)

    @slot_geschuetzt
    def _ansage_sprechen(self) -> None:
        """Eine gemeinsame Ansage fuer alle Ergebnisse, die kurz nacheinander
        fertig wurden. Laeuft die Warteschlange noch, wird weiter gesammelt."""
        if self._einfueger is not None and self._einfueger.wartend():
            self._ansage_zeitgeber.start(ANSAGE_SAMMELZEIT_MS)
            return
        ansagen, self._ansagen = self._ansagen, []
        hinweis, self._ablage_hinweis = self._ablage_hinweis, False
        if not ansagen and not hinweis:
            return
        if len(ansagen) == 1:
            satz = ansagen[0][0]
        elif ansagen:
            schlecht = sum(1 for _, erfolg in ansagen if not erfolg)
            satz = f"{len(ansagen)} Terminalbefehle fertig."
            if schlecht:
                satz += f" {schlecht} davon fehlgeschlagen."
        else:
            satz = ""
        if hinweis:
            if QGuiApplication.clipboard().text():
                satz = (satz + " Ergebnis liegt in der Zwischenablage.").strip()
            else:
                log.warning("Ergebnis nicht in der Zwischenablage: sie ist leer, "
                            "die Ansage nennt sie nicht")
        # Gibt es nur den Zwischenablage-Hinweis (kein Terminalbefehl dahinter,
        # z.B. nach einem Bruecken-Bericht), darf er eine laufende
        # "Fertig."-Ansage nicht abbrechen.
        self.sprecher.sprich(satz, unterbrechen=bool(ansagen),
                             art="fertig" if all(e for _, e in ansagen) else "fehler")

    # -- Bild (#BILD#) --------------------------------------------------------

    def _pausetaste_zustand_anwenden(self) -> None:
        """Bringt die beiden systemweiten Screenshot-Hotkeys (core/pausetaste.py)
        auf den Stand des Schalters "pause_screenshot" (einstellungen.json).
        Aufgerufen beim Start und nach jedem Schliessen der Einstellungen
        (F12), genau wie `_bruecke_zustand_anwenden`. Ist der Schalter aus,
        wird gar nicht erst angemeldet - keine Ansage, kein Fehler im Log,
        die Tasten bleiben frei fuer das eigenstaendige Werkzeug
        "Pausetaste"."""
        an = bool(einstellungen_lesen().get("pause_screenshot", False))
        registriert = any(self._pausetaste.status().values())
        if an and not registriert:
            if not self._pausetaste.registrieren():
                self.sprecher.sprich(
                    "Weder Pause-Taste noch Strg+Umschalt+B für den Screenshot "
                    "konnten eingerichtet werden, vermutlich von einem anderen "
                    "Programm oder einem anderen CWB-Fenster belegt.",
                    art="fehler",
                )
            else:
                fehlende = [name for name, an2 in self._pausetaste.status().items()
                            if not an2]
                if fehlende:
                    self.sprecher.sprich(
                        f"{' und '.join(fehlende)} für den Screenshot konnte nicht "
                        "eingerichtet werden, vermutlich von einem anderen Programm "
                        "oder einem anderen CWB-Fenster belegt.",
                        art="fehler",
                    )
        elif not an and registriert:
            self._pausetaste.abmelden()

    @slot_geschuetzt
    def _pause_ausgeloest(self) -> None:
        """Aufgerufen von einem der beiden systemweiten Screenshot-Hotkeys
        (Pause-Taste oder Strg+Umschalt+B, core/pausetaste.py), egal welches
        Fenster gerade vorn ist. Ruft exakt denselben Ablauf wie ein
        #BILD#-Auftrag auf - keine zweite Logik. Ist die Einstellung
        "Pause-Taste holt Screenshot" (F12 → Verhalten) aus, bleiben beide
        Tasten wirkungslos; geprueft wird das bei jedem Tastendruck neu,
        damit ein Umschalten sofort wirkt. Seit Block 657 Standard AUS: das
        eigenstaendige Werkzeug "Pausetaste"
        (%USERPROFILE%\\.cwb-werkzeuge\\pausetaste) uebernimmt die
        Taste, dieser Weg hier funktionierte nur einmal pro CWB-Lauf
        zuverlaessig."""
        if not einstellungen_lesen().get("pause_screenshot", False):
            return
        log.info("Screenshot-Hotkey ausgeloest")
        self._bild_markierung()

    def _bild_markierung(self, *, bruecke_nummer: int | None = None,
                          eingang_datei: Path | None = None,
                          block_nummer: int | None = None,
                          quelle: str = "Eingabe",
                          angenommen_vermerkt: bool = False) -> None:
        """Verarbeitet einen #BILD#-Auftrag: die Markierung allein genuegt,
        es gehoert kein Befehlstext dahinter. Laeuft nie ueber Claude Code
        und nie ueber das Terminal - kein Ausgabefeld wird belegt, keine
        Zwischenablage mit Text ueberschrieben, kein Ergebnis in ein fremdes
        Fenster zurueckgespielt. Danach steht nur ein Dateiverweis auf den
        Screenshot in der Zwischenablage (core/android_screenshot.py).
        `bruecke_nummer` kommt nur aus der Bruecke (core/bruecke.py) - die
        Bilddatei selbst laesst sich darueber nicht hochladen (die Brücke
        kennt nur Text), darum bekommt sie dort nur eine kurze Textmeldung.
        `block_nummer`/`quelle` (Block 82) dienen nur der Anzeige
        ("Läuft: ...", core/fenster.py _laeuft_kennung); ohne expliziten
        Aufrufer (Pause-Taste) gilt "Eingabe"."""
        if self._bild_faden is not None and self._bild_faden.isRunning():
            self.sprecher.sprich("Es läuft schon ein Screenshot-Auftrag.", art="fehler")
            if eingang_datei is not None:
                verwerfen(eingang_datei, "Screenshot-Weg war beim Start belegt")
            return
        if not angenommen_vermerkt and bruecke_nummer is None and eingang_datei is None:
            # Kachel, Pause-Taste, Zwischenablage: ohne diese Zeile fehlte im
            # Journal die Annahme (Eingabefeld, Bruecke und Eingang schreiben
            # sie selbst und melden angenommen_vermerkt).
            auftragsjournal.angenommen(
                "pausetaste" if quelle == "Eingabe" else quelle.lower(),
                block=block_nummer, art="bild")
        self._bild_bruecke_nummer = bruecke_nummer
        self._bild_eingang_datei = eingang_datei
        # Nur ueber die Bruecke (Linux): Chatfenster jetzt merken, solange der
        # Nutzer noch dort ist - das Bild geht am Ende dorthin.
        self._bild_ziel = None
        if bruecke_nummer is not None and not zielfenster.UNTER_WINDOWS:
            try:
                self._bild_ziel = einfueger.ziel_merken()
            except Exception as fehler:  # noqa: BLE001
                log.exception("Zielfenster fuer Bild nicht gemerkt: %s", fehler)
        self._laufender_block_nummer = block_nummer
        self._laufender_quelle = quelle
        self._laufender_zeit = datetime.now()
        self._bild_beginn = self._laufender_zeit
        self._statusleiste_aktualisieren()
        log.info("Bild-Auftrag gestartet (#BILD#)")
        self._status_zeigen("Screenshot wird geholt…")
        self.sprecher.sprich("Screenshot wird geholt…", art="meldung")  # stumm: Zwischenmeldung
        _journal_beginnt(self, "bild", bruecke_nummer, block_nummer)
        self._bild_faden = BildFaden(self.projekt.pfad, self)
        self._bild_faden.fertig_da.connect(self._bild_fertig)
        self._bild_faden.start()

    @slot_geschuetzt
    def _bild_fertig(self, ergebnis) -> None:
        # Block 82: "Läuft: ..." zeigt wieder "–", sobald self._bild_faden
        # nicht mehr laeuft (_laeuft_kennung prueft das zuerst).
        self._statusleiste_aktualisieren()
        # Gehoerte der Auftrag zur Bruecke (core/bruecke.py): die Bilddatei
        # selbst kann dorthin nicht hochgeladen werden (nur Text), darum nur
        # eine kurze Textmeldung - der lokale Ablauf (Zwischenablage, Ansage)
        # bleibt unveraendert, ein blinder Nutzer am PC profitiert ja genauso.
        bruecke_nummer, self._bild_bruecke_nummer = self._bild_bruecke_nummer, None
        # Block 70, Teil A: der Screenshot-Auftrag ist jetzt wirklich fertig
        # (Erfolg oder Fehler) - erst jetzt gilt sein Eingangsordner-Auftrag
        # als erledigt.
        eingang_datei, self._bild_eingang_datei = self._bild_eingang_datei, None
        if eingang_datei is not None:
            abschliessen(eingang_datei)
        _journal_endet(self, bruecke_nummer, self._laufender_block_nummer, "bild",
                            f"erfolg={'ja' if ergebnis.erfolg else 'nein'}")
        if ergebnis.erfolg:
            log.info(
                "Screenshot bereit: %s (%dx%d)", ergebnis.pfad, ergebnis.breite, ergebnis.hoehe
            )
            # Bild erst hier in die Zwischenablage legen: dieser Slot
            # laeuft auf dem GUI-Thread (fertig_da-Signal), waehrend der
            # BildFaden-Thread QClipboard nicht anfassen darf. Unter Linux
            # nur als image/png-Daten (kein Dateipfad, sonst lehnt Chrome ab),
            # unter Windows als Dateiverweis (zielfenster.bild_in_zwischenablage_legen).
            if not zielfenster.bild_in_zwischenablage_legen(str(ergebnis.pfad)):
                log.error("Screenshot nicht in die Zwischenablage gelegt: %s", ergebnis.pfad)
                self._status_zeigen(f"Screenshot liegt nur unter: {ergebnis.pfad}")
                self.sprecher.sprich("Fehler. Bild nicht in der Zwischenablage.", art="fehler")
                if bruecke_nummer is not None:
                    self._bruecke_bericht_hochladen(
                        bruecke_nummer,
                        f"Fehler. Bild nicht in der Zwischenablage: {ergebnis.pfad}",
                    )
                    self._bild_hinweis(bruecke_nummer, "Bild nicht in der Zwischenablage.")
                return
            self._status_zeigen(f"Screenshot bereit: {ergebnis.pfad}")
            # Die eine kurze Ansage - kein Text geht ins Ausgabefeld, die
            # Zwischenablage traegt schon das Bild und bleibt
            # unangetastet.
            self.sprecher.sprich("Screenshot bereit.", art="fertig")
            if bruecke_nummer is not None:
                self._bruecke_bericht_hochladen(
                    bruecke_nummer,
                    f"Screenshot bereit ({ergebnis.breite}x{ergebnis.hoehe}). Die Bilddatei "
                    f"selbst lässt sich über die Brücke nicht hochladen, nur diese Meldung.",
                )
                # Nur Brueckenauftraege: das Bild selbst in den Chat.
                self._bild_in_chat(bruecke_nummer, str(ergebnis.pfad))
        else:
            log.error("Screenshot fehlgeschlagen: %s", ergebnis.fehler)
            self._status_zeigen(f"Screenshot fehlgeschlagen: {ergebnis.fehler}")
            self.sprecher.sprich(
                kurzfassen(ergebnis.fehler) or "Screenshot fehlgeschlagen.", art="fehler"
            )
            if bruecke_nummer is not None:
                self._bruecke_bericht_hochladen(
                    bruecke_nummer, f"Screenshot fehlgeschlagen: {ergebnis.fehler}")
                self._bild_hinweis(bruecke_nummer, str(ergebnis.fehler or "unbekannt"))

    # -- Modellwahl ---------------------------------------------------------

    @slot_geschuetzt
    def _modelle_anbieten(self, eintraege: list) -> None:
        """Uebernimmt die Liste, die Claude Code selbst gemeldet hat - einzig
        fuer die Aufloesung von Namen in einer "#MODELL#"-Zeile
        (modellname_aufloesen) und fuer die Kopfzeilenanzeige. Kein
        Auswahlfeld mehr in der Oberflaeche (Block 662), darum keine
        Rueckwirkung mehr auf `self.modell`."""
        if not eintraege:
            return
        self.modelle = list(eintraege)

    @slot_geschuetzt
    def _modell_verbunden(self, modell_name: str) -> None:
        """Block 70, Teil B (Wiederholung des verlorenen Block 65): meldet
        sich bei jedem Verbindungsaufbau und jedem Modellwechsel mit dem
        tatsaechlich aufgeloesten Modellnamen (core/sitzung.py,
        Sitzung.modell_name, z.B. "claude-sonnet-5") - nicht nur beim
        allerersten Aufbau. Zeigt ihn dauerhaft in der Kopfzeile (core/
        kopfzeile.py, modell_zeigen) und sagt ihn an, wenn sich der Stand
        seit der letzten Ansage geaendert hat; eine reine Kontingent-
        Reconnect mit demselben Modell wiederholt die Ansage darum nicht.
        Weicht der aufgeloeste Name von der gespeicherten Wahl ab (z.B. weil
        das Abo das gewaehlte Modell nicht mehr hergibt), warnt die Ansage
        ausdruecklich statt nur den neuen Namen zu nennen."""
        lang, kurz = anzeige_name(modell_name)
        self.ausgabekopf.modell_zeigen(lang, kurz)
        if self._modell_eigenauftrag_rest > 0:
            # Block 77, Punkte 1/2: Hin- oder Rueckwechsel eines einmaligen
            # Modellwechsels fuer genau einen Auftrag (_auftrag_starten) -
            # die Kopfzeile zeigt das neue Modell, angesagt wird nichts
            # zusaetzlich: entweder hat _auftrag_starten den Satz schon
            # gesprochen (ausdruecklicher Wunsch), oder es war eine stille
            # Hochstufung.
            self._modell_eigenauftrag_rest -= 1
            return
        erwartet_voll = eintrag_suchen(self.modelle, self.modell).get("voll") or ""
        abweichend = bool(erwartet_voll) and erwartet_voll != modell_name
        erwartet_lang = anzeige_name(erwartet_voll)[0] if erwartet_voll else ""
        stand = (modell_name, abweichend, erwartet_lang)
        if stand == self._modell_angesagt:
            return
        self._modell_angesagt = stand
        if abweichend:
            log.warning("Modell abweichend: verbunden mit %s statt %s",
                        modell_name, erwartet_voll)
            self.sprecher.sprich(f"Achtung, verbunden mit {lang} statt {erwartet_lang}.",
                                  art="immer")
        else:
            self.sprecher.sprich(f"Modell {lang}.", art="immer")

    # -- Ereignisse aus der Sitzung ----------------------------------------

    def _bereit(self) -> None:
        # Modellwechsel, Neuverbinden und Code-Index melden "bereit", auch
        # waehrend ein Auftrag noch arbeitet - dann darf das Band nicht
        # umspringen und nichts angesagt werden.
        if self._laeuft():
            log.info("Bereit-Meldung uebergangen, es laeuft noch etwas")
            return
        self._zustand_zeigen("bereit")
        modell = self.faden.sitzung.modell_name if self.faden.sitzung else ""
        zusatz = f", Modell {modell}" if modell else ""
        self._status_zeigen(f"Bereit — Projekt {self.projekt.name}{zusatz}")
        self.sprecher.melde("bereit", "Claude bereit.", sprechen=True)

    @slot_geschuetzt
    def _ereignis(self, zustand: str, ansage: str, detail: str,
                  pfad: str = "", taetigkeit: str = "", ablehnung: bool = False,
                  hinweis: bool = False) -> None:
        """Waehrend der Arbeit bleibt die Statusmeldung leer: die laufende
        Taetigkeit steht ausschliesslich in der Plakette neben 'Ausgabe',
        farblich passend zum Balken, die betroffene Datei im Feld daneben.
        Die Statusmeldung zeigt nur Ergebnisse.

        Bei einer abgelehnten Aktion (ablehnung=True) ist ansage bewusst kurz
        und ohne Pfad - das ist alles, was gesprochen und in der Statuszeile
        angezeigt wird. Der volle Wortlaut mit Pfad steckt in detail und
        kommt, rot markiert wie ein Fehler, ins Ausgabefeld.

        Ein Hinweis (hinweis=True) ist eine erlaubte Aktion, von der der
        Nutzer trotzdem einmal erfahren soll - etwa der erste Zugriff
        ausserhalb des Projekts in einem Auftrag. Er wird gesprochen (Art
        'hinweis', siehe sprache.ERLAUBTE_ARTEN), steht in der Statuszeile
        und als Hinweiszeile im Ausgabefeld; Balken und Ton bleiben, wie sie
        sind, der Auftrag laeuft ohne Unterbrechung weiter."""
        if hinweis:
            self._status_zeigen(ansage)
            self._verlauf_anhaengen(detail or ansage, "hinweis")
            self.sprecher.sprich(kurzfassen(ansage), unterbrechen=False, art="hinweis")
            return
        if zustand in ("fertig", "bereit") and self._laeuft():
            # Waehrend des Auftrags (auch Nachtrag, Neuverbinden) setzt nur
            # `_fertig` das Band auf fertig, wenn Bericht und Upload stehen.
            log.info("Zustand %s waehrend des Laufs uebergangen", zustand)
            return
        if zustand in WERKZEUG_ZUSTAENDE and not self._laeuft():
            # Arbeitszustand ohne Auftrag: der Code-Index meldet beim
            # Verbinden "denkt" (Indizieren), bei "uebersprungen" folgt aber
            # kein "fertig" - das Band bliebe im Leerlauf blau. Auch
            # Nachzuegler nach dem Auftragsende landen hier. Das Band zeigt
            # nur, was wirklich laeuft.
            log.info("Zustand %s ohne laufenden Auftrag uebergangen", zustand)
            return
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
        elif zustand in WERKZEUG_ZUSTAENDE and taetigkeit:
            self._journal_werkzeuge = getattr(self, "_journal_werkzeuge", 0) + 1
            self._verlauf_anhaengen(
                self._werkzeug_zeile(taetigkeit, pfad, ansage), zustand
            )
        # Waehrend der Arbeit wird nichts gesprochen, nur der Ton wechselt.
        # Fehler und Ablehnungen werden gesprochen, aber auf zwei Saetze gekuerzt.
        gesprochen = kurzfassen(ansage) if (zustand == "fehler" or ablehnung) else ""
        self.sprecher.melde(zustand, gesprochen, sprechen=bool(gesprochen),
                            art="fehler")

    def _werkzeug_zeile(self, taetigkeit: str, pfad: str, ansage: str) -> str:
        """Baut die Zeile fuer einen Werkzeugaufruf im Ausgabefeld: bei einer
        betroffenen Datei Taetigkeit und Dateiname ('liest fenster.py'),
        sonst Taetigkeit und das Ziel aus der Ansage ('fuehrt aus: git
        status') - dieselbe Kurzform, die auch im Aktivitaetsbalken steht."""
        if pfad:
            return f"{taetigkeit} {Path(pfad).name}"
        ziel = ansage.split(": ", 1)[1] if ": " in ansage else ""
        return f"{taetigkeit}: {ziel}" if ziel else taetigkeit

    def _ausgabe_leeren(self, grund: str, feld=None) -> None:
        """Leert einen Ausgabebereich (Vorgabe: den Claude-Verlauf). Einzige
        Stelle, an der das geschieht - der Logeintrag macht hinterher
        nachweisbar, ob und wofuer geleert wurde."""
        feld = feld if feld is not None else self.verlauf
        try:
            feld.clear()
            log.info("Ausgabefeld geleert (%s): %s", feld.objectName(), grund)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Ausgabefeld nicht geleert (%s): %s", grund, fehler)

    def _verlauf_anhaengen(self, text: str, art: str = "antwort") -> None:
        """Haengt einen Absatz an den passenden Bereich: Terminaltext
        (Art 'terminal') in die Terminal-Ausgabe, alles andere in den
        Claude-Verlauf. Die Art bestimmt die Klasse (Farbe aus verlauf.css)
        und das Vorsatzzeichen; unbekannte Arten gelten als Antwort. Die
        beiden Bereiche beeinflussen sich nicht - es gibt nichts
        Zurueckzuhalten."""
        if art not in VERLAUF_ARTEN:
            art = "antwort"
        feld = self.terminal_verlauf if art == "terminal" else self.verlauf
        self._absatz_schreiben(text, art, feld)

    def _absatz_schreiben(self, text: str, art: str, feld=None) -> None:
        """Schreibt einen Absatz wirklich ins Feld."""
        feld = feld if feld is not None else self.verlauf
        inhalt = f"{VERLAUF_ARTEN[art]}{text}".strip()
        if not inhalt:
            return
        self._verlauf_waechst = True
        try:
            feld.append(
                f'<div class="{art}">'
                + html.escape(inhalt).replace(chr(10), "<br>")
                + "</div>"
            )
        except Exception as fehler:  # noqa: BLE001
            log.exception("Verlauf nicht ergänzt: %s", fehler)
            return
        finally:
            self._verlauf_waechst = False
        leiste = feld.verticalScrollBar()
        leiste.setValue(leiste.maximum())

    # -- Zustandsanzeige je Bereich ------------------------------------------

    def _terminal_aktiv(self) -> bool:
        return self._terminal_faden is not None and self._terminal_faden.isRunning()

    def _zustand_text(self, name: str, laeuft: bool, beginn) -> str:
        if not laeuft:
            return f"{name}: bereit"
        sekunden = max(0, int((datetime.now() - beginn).total_seconds())) if beginn else 0
        return f"{name}: läuft seit {self._dauer_wort(sekunden)}"

    def _bereiche_aktualisieren(self, terminal_fertig: bool = False) -> None:
        """Setzt die beiden Zustandsanzeigen ("Claude: ..." / "Terminal: ...")
        unabhaengig voneinander. Der sichtbare Text zaehlt jede Sekunde mit;
        die Beschreibung fuer den Screenreader wird nur bei einem Wechsel
        zwischen laeuft und bereit gesetzt, sonst spraeche er sekuendlich."""
        try:
            claude_an = self._code_laeuft()
            terminal_an = self._terminal_aktiv() and not terminal_fertig
            for label, name, an, beginn, merker in (
                (self.claude_zustand, "Claude", claude_an, self._auftrags_beginn,
                 "_claude_war_an"),
                (self.terminal_zustand, "Terminal", terminal_an, self._terminal_beginn,
                 "_terminal_war_an"),
            ):
                text = self._zustand_text(name, an, beginn)
                if label.text() != text:
                    label.setText(text)
                if getattr(self, merker, None) != an:
                    setattr(self, merker, an)
                    label.setAccessibleDescription(text)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Bereichsanzeige nicht aktualisiert: %s", fehler)

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
        # Gehoerte der gerade beendete Auftrag zur Bruecke (core/bruecke.py,
        # Vorhaben "Bruecke" Stufe B3), wird der Bericht weiter unten dorthin
        # hochgeladen - sofort geleert, damit der naechste Auftrag (ohne
        # Bruecke) nicht faelschlich mithochlaedt.
        bruecke_nummer, self._bruecke_code_nummer = self._bruecke_code_nummer, None
        block_nummer, self._aktueller_block_nummer = self._aktueller_block_nummer, None
        eingang_datei, self._eingang_code_datei = self._eingang_code_datei, None
        # Block 649: Hinweis zur Zeile "#MODELL# name" (unbekannter Name) -
        # ein spaeter async gemeldeter Fehlschlag des Wechsels selbst kommt
        # stattdessen ueber bilanz["modell_hinweis"] (core/faden.py), beide
        # schliessen sich gegenseitig aus (ein unbekannter Name versucht nie
        # einen Wechsel).
        modell_hinweis = self._laufender_modell_hinweis or bilanz.get("modell_hinweis") or ""
        self._laufender_modell_hinweis = ""
        # Der Platz beim Arbeitsfaden ist wieder frei; die Bilder wurden schon
        # beim Abschicken uebergeben.
        self._auftrag_laeuft = False
        self._auftrags_uhr.stop()
        # Block 70, Nachbesserung (07.10.2026): beide Aufrufe standen hier
        # ungeschuetzt vor abschliessen() weiter unten - eine Ausnahme darin
        # (z.B. eine kaputte Anzeige) wurde von @slot_geschuetzt abgefangen
        # und beendete _fertig() vorzeitig, OHNE dass abschliessen() je
        # lief. Der tatsaechlich fertige Auftrag blieb dadurch in laeuft/
        # liegen und wurde beim naechsten Neustart von wieder_aufnehmen()
        # erneut angestossen, obwohl Claude Code ihn schon erledigt hatte
        # ("schon erledigt" - Nutzer, 07.10.2026). Darum jetzt abgesichert:
        # ein Fehler hier darf den Abschluss nicht mehr verhindern.
        try:
            self.balken.animation_stoppen()
            # Das Auftragsprotokoll (core/sitzung.py, _protokoll_schreiben) hat
            # den Verlauf schon vor diesem Aufruf fortgeschrieben (Block C10).
            self.ausgabekopf.such_effizienz_zeigen(such_effizienz_prozent())
        except Exception as fehler:  # noqa: BLE001
            log.exception("Anzeige nach Auftragsende nicht aktualisiert: %s", fehler)
        # Block 77, Punkte 3/4: Kontingent-Zustand (Kopfzeile/F2) und
        # Sparmodus-Umschaltung - unabhaengig davon, ob der Auftrag gleich
        # als Kontingent-Pause zurueckkehrt oder normal fertig wird.
        self._kontingent_anzeige_aktualisieren()

        kontingent = bilanz.get("kontingent")
        if kontingent is not None:
            # Das Max-Kontingent ist erschoepft (core/sitzung.py, auftrag()) -
            # kein gescheiterter Auftrag, sondern eine Pause. Weder Bericht
            # noch Bruecken-Upload noch "naechsten_starten" noch abschliessen()
            # auf eingang_datei: das holt _kontingent_fortsetzen() nach,
            # sobald der Auftrag wirklich zu Ende ist - bis dahin bleibt die
            # Datei in laeuft/ liegen.
            self._kontingent_pause_behandeln(kontingent, bruecke_nummer, block_nummer,
                                              eingang_datei)
            return
        # Block 70, Teil A: der Auftrag ist jetzt wirklich fertig (Erfolg,
        # Fehler oder Abbruch) - erst jetzt gilt sein Eingangsordner-Auftrag
        # als erledigt.
        if eingang_datei is not None:
            abschliessen(eingang_datei)
            # Block 77, Punkt 2: Hochstufung bei Misserfolg - nur Auftraege
            # aus Eingang, Bruecke oder Leitstand zaehlen mit (erkennbar an
            # eingang_datei), ein manuell abgeschickter Auftrag weder zaehlt
            # noch setzt zurueck (siehe Docstring von
            # self._fehlschlaege_eingang_folge). "Abgebrochen" (Not-Aus) ist
            # keine Modell-Schwaeche und bleibt neutral - weder Zaehlung noch
            # Ruecksetzung.
            if bilanz.get("fehler"):
                self._fehlschlaege_eingang_folge += 1
            elif not bilanz.get("abgebrochen"):
                self._fehlschlaege_eingang_folge = 0

        # `satz` steht in der Statuszeile und muss in eine Zeile passen.
        # `hinweis` ergaenzt ihn im Ausgabefeld und wird nicht gesprochen.
        # `ansage` ist das Einzige, was durch die Stimme geht.
        hinweis = ""
        # `satzart` entscheidet, ob der Satz ueberhaupt gesprochen wird
        # (siehe sprache.ERLAUBTE_ARTEN): nur Abschluss und Fehler.
        satzart = "fertig"
        if bilanz.get("fehler"):
            zustand_ende = "fehler"
            satz = "Fehler."
            hinweis = f" {bilanz['fehler']}"
            ansage = kurzfassen(f"Claude Fehler. {bilanz['fehler']}")
            satzart = "fehler"
        elif bilanz.get("abgebrochen"):
            zustand_ende = "abgebrochen"
            satz = "Abgebrochen."
            ansage = "Claude abgebrochen."
        else:
            zustand_ende = "fertig"
            geaendert = bilanz.get("geaendert", [])
            anzahl = len(geaendert)
            if anzahl == 0:
                satz = "Fertig, keine Datei geändert."
            elif anzahl == 1:
                satz = f"Fertig, eine Datei geändert: {Path(geaendert[0]).name}."
            else:
                satz = f"Fertig, {anzahl} Dateien geändert."
            hinweis = " Antwort vorlesen mit F3, zurücknehmen mit Strg Z."
            # Gesprochen wird nur "Fertig" - die Bilanz (wie viele Dateien
            # geaendert) steht in Statuszeile und Ausgabefeld.
            ansage = "Claude fertig."

        try:
            self._letzter_bericht = self._bericht_bauen(bilanz, block_nummer, modell_hinweis)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Bericht nicht gebaut: %s", fehler)
            self._letzter_bericht = ""

        self._letzter_bericht_pfad = (
            self._bericht_datei_speichern() if self._letzter_bericht else None
        )
        if self._letzter_bericht_pfad:
            hinweis += f" Bericht auch gespeichert unter {self._letzter_bericht_pfad}."
        try:
            auftragsjournal.schreibe(
                "bericht_erstellt",
                f"zeichen={len(self._letzter_bericht or '')} "
                f"datei={'ja' if self._letzter_bericht_pfad else 'nein'}",
                nummer=bruecke_nummer, block=block_nummer, art="code", ohne_kontext=True)
            if bilanz.get("fehler"):
                auftragsjournal.schreibe("fehler", str(bilanz.get("fehler"))[:120],
                                         nummer=bruecke_nummer, block=block_nummer,
                                         art="code", ohne_kontext=True)
            elif bilanz.get("abgebrochen"):
                auftragsjournal.schreibe("abgebrochen", "Not-Aus oder Abbruch",
                                         nummer=bruecke_nummer, block=block_nummer,
                                         art="code", ohne_kontext=True)
            _journal_endet(self, bruecke_nummer, block_nummer, "code",
                                "fehler" if bilanz.get("fehler") else
                                "abgebrochen" if bilanz.get("abgebrochen") else "ok")
        except Exception as fehler:  # noqa: BLE001
            log.exception("Auftragsjournal (fertig): %s", fehler)

        bruecke_text = self._letzter_bericht or ansage
        orch = _orch_ist(self, eingang_datei)
        _orch_bericht(self, eingang_datei, bruecke_text, block_nummer,
                      "Fehler" if bilanz.get("fehler") else
                      "abgebrochen" if bilanz.get("abgebrochen") else "fertig", "CODE")
        if bruecke_nummer is not None:
            self._bruecke_bericht_hochladen(bruecke_nummer, bruecke_text, block_nummer)
            hinweis += " Bericht an Brücke hochgeladen."
        self._letzter_bericht_bruecke = bruecke_nummer
        # Erst jetzt, mit geschriebenem Bericht und angestossenem Upload, geht
        # das Band auf fertig (oder fehler/abgebrochen).
        self._zustand_zeigen(zustand_ende)
        if zustand_ende == "abgebrochen":
            self._abbruch_rueckfall_planen()

        self._status_zeigen(satz)
        self._verlauf_anhaengen(satz + hinweis,
                                "fehler" if bilanz.get("fehler") else "hinweis")
        # Die einzige Ansage nach einem Auftrag: "Fertig" (oder der Fehler),
        # bei Auftraegen ohne Bruecke samt Hinweis auf die Zwischenablage. Der
        # Inhalt des Ausgabefelds wird nie von allein vorgelesen - dafuer F3.
        # Bei Brueckenauftraegen kommt nichts mehr in die Zwischenablage: der
        # Volltext liegt im Ablagefach, im Chat steht nur die Kurzmeldung.
        ablage_satz = ("" if bruecke_nummer is not None or orch
                       else self._bericht_ablegen_nach_auftrag())
        nachsatz = getattr(self, "_notaus_nachsatz", "")
        self._notaus_nachsatz = ""
        if nachsatz and bilanz.get("abgebrochen"):
            ablage_satz += " " + nachsatz
        self.sprecher.sprich((ansage + ablage_satz).strip(), art=satzart)
        # Die Meldung zum Bruecken-Bericht geht zusaetzlich ins zuletzt aktive
        # Chatfenster, egal ob CWB gerade im Vordergrund ist.
        if bruecke_nummer is not None:
            self._bericht_zustellen(bruecke_nummer, bruecke_text, bilanz,
                                    block_nummer, self._code_ziel)
        self._code_ziel = None

        # Wartet noch ein Auftrag, laeuft er jetzt von allein los.
        self._naechsten_starten()
        # Block 82: "Läuft: ..." auf den neuen Stand bringen - entweder den
        # gerade gestarteten naechsten Auftrag (schon in _auftrag_starten
        # gesetzt, hier nur zur Sicherheit erneut gezeichnet) oder "–", wenn
        # die Warteschlange jetzt leer ist.
        self._statusleiste_aktualisieren()

        # Leitstand (core/leitstand.py, Block 72): reagiert nur, wenn der
        # Schalter an ist und das Projekt wissen/nachtplan.md hat - sonst
        # kehrt die Methode sofort zurueck.
        self._leitstand_nach_auftrag(bilanz, block_nummer, satz)

    def _kontingent_anzeige_aktualisieren(self) -> None:
        """Block 36 (vorher 77, Punkte 3 und 4): liest nach jedem beendeten
        Auftrag die zuletzt gemeldeten RateLimitEvent-Meldungen der Sitzung
        (core/sitzung.py, `kontingent_zustand`/`sparmodus_aktiv`) und zieht
        daraus drei Dinge: die Kontingent-Anzeige mit echten Prozentzahlen
        fuer die Statusleiste ueber dem Ausgabefeld (Block 82, `_kontingent_zeigen`;
        F2 nennt denselben Zustand ueber `Sitzung.stand()`), die einmalige Ansage
        beim Ueberschreiten von
        90 % bzw. 95 % Wochenauslastung sowie, sofern F12 -> Verhalten ->
        "Sparmodus bei knappem Wochenkontingent" an ist (Ab Werk an), die
        Sparmodus-Umschaltung anhand der dort einstellbaren Prozent-Schwelle
        (Ab Werk 95 %): beim Eintritt eine einmalige Ansage, beim Austritt
        laufen die zurueckgestellten Auftraege (`self._sparmodus_wartend`)
        wieder in die normale Warteschlange ein. Ohne Sitzung (ganz am
        Anfang, Verbindung steht noch nicht) geschieht nichts."""
        faden = getattr(self, "faden", None)
        sitzung = getattr(faden, "sitzung", None) if faden else None
        if sitzung is None:
            return
        try:
            zustand = sitzung.kontingent_zustand()
            ansicht = _orch_ansicht_von(self)
            if ansicht is not None:
                ansicht.kontingent_setzen(_orch_kontingent_von(self))
            self._kontingent_zeigen(
                zustand.get("stufe", "normal"), zustand.get("text", ""),
                zustand.get("woche_anzeige", ""), zustand.get("sitzung_anzeige"),
            )

            woche_prozent = zustand.get("woche_prozent")
            if woche_prozent is not None:
                if woche_prozent >= 90 and not self._kontingent_warnung_90_gegeben:
                    self._kontingent_warnung_90_gegeben = True
                    self.sprecher.sprich("Wochenkontingent 90 Prozent.", art="immer")
                if woche_prozent >= 95 and not self._kontingent_warnung_95_gegeben:
                    self._kontingent_warnung_95_gegeben = True
                    self.sprecher.sprich("Wochenkontingent 95 Prozent.", art="immer")
                if woche_prozent < 90:
                    self._kontingent_warnung_90_gegeben = False
                    self._kontingent_warnung_95_gegeben = False

            einstellungen = einstellungen_lesen()
            schalter_an = einstellungen.get("sparmodus_wochenkontingent", True)
            schwelle_prozent = int(einstellungen.get("sparmodus_schwelle_prozent", 95))
            soll_aktiv = schalter_an and sitzung.sparmodus_aktiv(schwelle_prozent)
            if soll_aktiv and not self._sparmodus_aktiv:
                self._sparmodus_aktiv = True
                log.info("Sparmodus eingeschaltet: Wochenkontingent wird knapp")
                self.sprecher.sprich(
                    "Wochenkontingent wird knapp, nur noch dringende Aufträge.",
                    art="immer")
            elif not soll_aktiv and self._sparmodus_aktiv:
                self._sparmodus_aktiv = False
                log.info("Sparmodus ausgeschaltet, %d zurückgestellte Aufträge laufen wieder an",
                          len(self._sparmodus_wartend))
                if self._sparmodus_wartend:
                    self._warteschlange.extend(self._sparmodus_wartend)
                    self._sparmodus_wartend = []
                    self._warteschlange_zeigen()
                    if not self._code_laeuft():
                        self._naechsten_starten()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kontingent-Anzeige/Sparmodus nicht aktualisiert: %s", fehler)

    def _kontingent_pause_behandeln(self, kontingent: dict, bruecke_nummer: int | None,
                                     block_nummer: int | None,
                                     eingang_datei: Path | None = None) -> None:
        """Haelt die Warteschlange an, statt den Auftrag als gescheitert zu
        werten: das Max-Kontingent ist erschoepft (core/sitzung.py,
        auftrag(), Rueckgabefeld "kontingent", RateLimitEvent des Agent-SDK
        mit status="rejected"). Beim ersten Aufruf einer Pause merkt
        `self._kontingent_info` Text, Bilder sowie Bruecken-/Blocknummer
        einmalig - jeder weitere Aufruf (ein Fortsetzungsversuch, der selbst
        wieder abgewiesen wurde) aktualisiert nur die Freigabezeit, damit
        der Fortsetzungs-Vorspann (KONTINGENT_VORSPANN) sich nicht mit jedem
        Versuch neu um den Auftragstext legt."""
        erster_versuch = self._kontingent_info is None
        if erster_versuch:
            self._kontingent_info = {
                "text": self.letzter_auftrag,
                "bilder": list(self._aktuelle_bilder),
                "bruecke_nummer": bruecke_nummer,
                "block_nummer": block_nummer,
                "eingang_datei": eingang_datei,
                # Block 77: ein einmaliger Modellwunsch fuer diesen Auftrag
                # (Punkt 1) bzw. eine Hochstufung (Punkt 2) gilt auch fuer
                # den Fortsetzungsversuch nach der Pause.
                "modell_wunsch": self._laufender_modell_wunsch,
                "modell_grund": self._laufender_modell_grund,
                # Block 82: Kennung fuer "Läuft: ..." waehrend der Pause
                # (core/fenster.py, _laeuft_kennung).
                "quelle": self._laufender_quelle,
                "zeit": self._laufender_zeit,
            }
        else:
            log.info("Kontingent weiterhin erschöpft, neue Freigabezeit übernommen")

        entscheidung = kontingent_entscheidung(kontingent.get("resets_at"), datetime.now())

        if entscheidung["wochenlimit"]:
            # Vermutlich das Wochenlimit, nicht das Fuenf-Stunden-Fenster:
            # kein automatischer Fortsetzungsversuch, die Warteschlange
            # bleibt angehalten, bis der Nutzer selbst eingreift.
            # Block 70, Nachbesserung: abschliessen() steht hier ganz vorn,
            # VOR Anzeige, Ansage und Berichtsbau - ein Fehler dort darf
            # nicht mehr verhindern, dass die Datei aus laeuft/ kommt.
            if eingang_datei is not None:
                abschliessen(eingang_datei)
            grund = entscheidung["grund"]
            log.warning("Kontingent-Pause abgebrochen (Wochenlimit): %s", grund)
            self._zustand_zeigen("fehler")
            self._status_zeigen(grund)
            self._verlauf_anhaengen(grund, "fehler")
            self.sprecher.sprich(grund, art="fehler")
            try:
                bilanz_fuer_bericht = {
                    "antwort": self.letzte_antwort, "geaendert": [], "fehler": grund,
                    "abgebrochen": False,
                }
                self._letzter_bericht = self._bericht_bauen(
                    bilanz_fuer_bericht, self._kontingent_info.get("block_nummer"))
            except Exception as fehler:  # noqa: BLE001
                log.exception("Bericht nicht gebaut (Kontingent-Wochenlimit): %s", fehler)
                self._letzter_bericht = ""
            self._letzter_bericht_pfad = (
                self._bericht_datei_speichern() if self._letzter_bericht else None
            )
            self._kontingent_info = None
            self._statusleiste_aktualisieren()
            return

        status, ansage = entscheidung["status"], entscheidung["ansage"]
        self._zustand_zeigen("wartet_kontingent")
        self._taetigkeit_zeigen("wartet auf Kontingent")
        self._status_zeigen(status)
        if erster_versuch:
            # Nur beim ersten Mal gesprochen - ein stiller Fortsetzungsversuch,
            # der selbst wieder abgewiesen wird, loest keine zweite Ansage aus.
            self._verlauf_anhaengen(status, "hinweis")
            self.sprecher.sprich(ansage, art="fehler")
        log.warning(
            "Kontingent erschöpft (Typ %s): %s - nächster Versuch in %d Sekunden",
            kontingent.get("rate_limit_type"), status, int(entscheidung["wartesekunden"]),
        )
        self._kontingent_uhr.start(int(entscheidung["wartesekunden"] * 1000))
        self._statusleiste_aktualisieren()

    @slot_geschuetzt
    def _kontingent_fortsetzen(self) -> None:
        """Vom Kontingent-Timer gerufen (_kontingent_pause_behandeln): setzt
        den pausierten Auftrag mit dem Fortsetzungs-Vorspann fort - in
        derselben Sitzung, wenn sie noch lebt, sonst verbindet
        core/sitzung.py (_neu_verbinden) von selbst neu, bevor der Auftrag
        gesendet wird.

        Block 80: vorher dieselbe Eingangsreihenfolge-Pruefung wie im
        Leerlauf (_naechstes_fremdes_projekt/_auto_projekt_pruefen) - sonst
        wuerde nach jeder Pause immer das zuletzt aktive Projekt fortgesetzt,
        auch wenn laut Eingangsordner ein anderes Projekt laenger wartet. Nur
        bei einem Auftrag aus dem Eingangsordner (eingang_datei gesetzt):
        seine Datei liegt bereits unveraendert in eingang/laeuft/ (Block 70,
        Teil A) und wird beim naechsten Oeffnen dieses Projekts von
        wieder_aufnehmen() erneut angestossen - ein von Hand eingegebener
        Auftrag ohne Eingangsdatei hat keine solche Ablage und wird deshalb
        immer fortgesetzt, sonst ginge er verloren."""
        info, self._kontingent_info = self._kontingent_info, None
        if info is None:
            # F8 (Not-Aus) hat die Pause inzwischen verworfen.
            return
        if info.get("eingang_datei") is not None:
            projekt = self._naechstes_fremdes_projekt()
            if projekt is not None:
                log.info(
                    "Kontingent-Pause vorbei, aber Projekt %s wartet laenger in der "
                    "Eingangsreihenfolge - wechsle, statt eigenen Auftrag fortzusetzen",
                    projekt.name,
                )
                self._statusleiste_aktualisieren()
                QTimer.singleShot(
                    0, lambda zielprojekt=projekt: self._auto_projekt_wechseln(zielprojekt))
                return
        log.info("Kontingent-Pause vorbei, setze Auftrag fort: %s", info["text"][:120])
        self._auftrag_starten(
            f"{KONTINGENT_VORSPANN}{info['text']}", info["bilder"], ansagen=False,
            bruecke_nummer=info["bruecke_nummer"], block_nummer=info["block_nummer"],
            eingang_datei=info.get("eingang_datei"),
            modell_wunsch=info.get("modell_wunsch"), modell_grund=info.get("modell_grund"),
            quelle=info.get("quelle") or "Eingabe", zeit=info.get("zeit"),
        )

    def _bericht_bauen(self, bilanz: dict, block_nummer: int | None = None,
                        modell_hinweis: str = "") -> str:
        """Baut den Bericht für die Zwischenablage: Auftrag, Antwort, geänderte
        Dateien und Tokenverbrauch des letzten Aufrufs. Trug der Auftrag eine
        Blocknummer (core/bloecke.py, "Block N" - die Zeile selbst wurde vor
        der Übergabe an Claude Code entfernt), steht sie hier im Kopf, sonst
        fehlte sie im Bericht ganz. `modell_hinweis` (Block 649) ist nur bei
        einer unbekannten oder gescheiterten "#MODELL#"-Zeile gesetzt."""
        teile = [f"Projekt: {self.projekt.name}",
                 f"Zeit: {datetime.now():%d.%m.%Y %H:%M}"]
        if block_nummer is not None:
            teile.append(f"Block: {block_nummer}")
        teile.append("")
        teile += ["Auftrag:", self.letzter_auftrag or "—", ""]
        teile += ["Antwort:", bilanz.get("antwort") or "—", ""]

        if bilanz.get("fehler"):
            teile += ["Fehler:", str(bilanz["fehler"]), ""]
        elif bilanz.get("abgebrochen"):
            teile += ["Abgebrochen.", ""]

        if bilanz.get("hintergrund_warnung"):
            teile += ["Warnung:", str(bilanz["hintergrund_warnung"]), ""]

        if modell_hinweis:
            teile += [modell_hinweis, ""]

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
        teile.append("")
        # Block 649/662, Punkt 9: nennt mit voller Versionsbezeichnung das
        # Modell, mit dem dieser Auftrag tatsaechlich lief - unabhaengig
        # davon, ob es die Voreinstellung (Sonnet), eine "#MODELL#"-Zeile
        # oder die Hochstufung nach Fehlschlaegen war.
        faden = getattr(self, "faden", None)
        sitzung = getattr(faden, "sitzung", None) if faden else None
        modell_name = sitzung.modell_name if sitzung else ""
        lang, _kurz = anzeige_name(modell_name) if modell_name else anzeige_name(self.modell)
        teile.append(f"Modell: {lang}")
        return "\n".join(teile).strip() + "\n"

    def _bericht_fuer_block_vorhanden(self, block_nummer: int) -> bool:
        """Block 70, Nachbesserung: True, wenn unter .cwb/bericht/ schon ein
        gespeicherter Bericht mit der Kopfzeile "Block: {block_nummer}"
        liegt (siehe _bericht_bauen) - Grundlage fuer die Sicherung in
        core/eingangsordner.py wieder_aufnehmen() gegen einen Auftrag, der in
        Wahrheit schon fertig war. Scheitert das Lesen eines einzelnen
        Berichts (beschaedigtes ZIP, Zugriffsfehler), gilt das als kein
        Treffer fuer diese Datei, sonst wird einfach weitergesucht."""
        ordner = self.projekt.pfad / BERICHT_UNTERORDNER
        if not ordner.is_dir():
            return False
        kennung = f"Block: {block_nummer}"
        try:
            dateien = [p for p in ordner.iterdir()
                       if p.is_file() and p.suffix.lower() in (".zip", ".txt")]
        except OSError:
            return False
        for pfad in dateien:
            try:
                if pfad.suffix.lower() == ".zip":
                    with zipfile.ZipFile(pfad) as archiv:
                        texte = [archiv.read(name).decode("utf-8", errors="ignore")
                                 for name in archiv.namelist()]
                else:
                    texte = [pfad.read_text(encoding="utf-8", errors="ignore")]
            except (OSError, zipfile.BadZipFile):
                continue
            if any(kennung in text for text in texte):
                return True
        return False

    def _bericht_datei_speichern(self) -> Path | None:
        """Speichert den zuletzt gebauten Bericht (self._letzter_bericht)
        zusaetzlich unter .cwb/bericht/, mit Datum und Uhrzeit im Dateinamen.
        Steht der Schalter "Bericht als ZIP-Datei" an (Standard), liegt der
        Text als ZIP darin - das kommt beim Hochladen in den Chat
        zuverlaessiger an als eine lose Textdatei. Steht er aus, wird die
        Textdatei direkt abgelegt. Raeumt danach alte Berichte weg."""
        ordner = self.projekt.pfad / BERICHT_UNTERORDNER
        try:
            ordner.mkdir(parents=True, exist_ok=True)
        except OSError as fehler:
            log.error("Berichtordner nicht anlegbar: %s", fehler)
            return None
        name = f"{datetime.now():%Y-%m-%d_%H-%M-%S}"
        als_zip = einstellungen_lesen().get("bericht_als_zip", True)
        ziel = ordner / (f"{name}.zip" if als_zip else f"{name}.txt")
        try:
            if als_zip:
                with zipfile.ZipFile(ziel, "w", compression=zipfile.ZIP_DEFLATED) as archiv:
                    archiv.writestr(f"{name}.txt", self._letzter_bericht)
            else:
                ziel.write_text(self._letzter_bericht, encoding="utf-8")
        except (OSError, zipfile.BadZipFile) as fehler:
            log.error("Berichtdatei nicht schreibbar: %s", fehler)
            return None
        log.info("Bericht als Datei gespeichert: %s", ziel)
        self._berichte_aufraeumen(ordner, behalten=ziel)
        return ziel

    @staticmethod
    def _berichte_aufraeumen(ordner: Path, behalten: Path) -> None:
        """Laesst die juengsten BERICHTE_BEHALTEN Berichtdateien liegen und
        loescht den Rest - Textdateien aus der Zeit vor dem ZIP eingeschlossen.
        Die Namen beginnen mit dem Zeitstempel, deshalb reicht Sortieren nach
        Namen. `behalten` bleibt in jedem Fall stehen."""
        try:
            dateien = sorted(
                p for p in ordner.iterdir()
                if p.is_file() and p.suffix.lower() in (".zip", ".txt")
            )
        except OSError as fehler:
            log.warning("Berichtordner nicht lesbar: %s", fehler)
            return
        alte = [p for p in dateien[:-BERICHTE_BEHALTEN] if p != behalten]
        for datei in alte:
            try:
                datei.unlink()
            except OSError as fehler:
                log.warning("Alter Bericht nicht loeschbar: %s (%s)", datei, fehler)
        if alte:
            log.info("Alte Berichte entfernt: %s, %s bleiben", len(alte), BERICHTE_BEHALTEN)

    def _berichtordner_oeffnen(self) -> None:
        """Oeffnet den Ordner mit den Berichtdateien im Explorer, damit die
        zuletzt gespeicherte Datei sofort hochgeladen werden kann."""
        ordner = self.projekt.pfad / BERICHT_UNTERORDNER
        if not ordner.is_dir():
            log.warning("Berichtordner fehlt: %s", ordner)
            self.sprecher.sprich("Es gibt noch keinen gespeicherten Bericht.",
                                 art="fehler")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(ordner))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(ordner)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except OSError as fehler:
            log.exception("Explorer nicht zu öffnen (%s): %s", ordner, fehler)
            self.sprecher.sprich("Der Ordner ließ sich nicht öffnen.", art="fehler")
            return
        log.info("Berichtordner geöffnet: %s", ordner)
        self.sprecher.sprich("Berichtordner geöffnet.", art="meldung")

    def _bericht_ablegen(self) -> str:
        """Legt den Bericht in die Zwischenablage: vorzugsweise als
        Dateiverweis auf die gespeicherte Berichtdatei (self.
        _letzter_bericht_pfad), sonst als Text. So laesst er sich mit Strg+V
        andernorts als echter Anhang einfuegen statt als leerer Text.

        Rückgabe nennt, welche der beiden Formen jetzt dort liegt - haengt
        sich an den Ergebnissatz an, damit Bilanz und Zwischenablage-Hinweis
        in einer einzigen Ansage zusammenkommen statt in zwei kurz
        hintereinander. Genannt wird nur, was nach dem Schreiben zurueckgelesen
        wurde (`zwischenablage_enthaelt_datei`/`_text`); sonst bleibt der Satz
        leer und eine WARNING-Zeile im Log nennt den Grund."""
        if self._letzter_bericht_pfad:
            if datei_in_zwischenablage(self._letzter_bericht_pfad):
                ok, grund = zwischenablage_enthaelt_datei(self._letzter_bericht_pfad)
                if ok:
                    auftragsjournal.schreibe("ablage_zwischenablage", "datei")
                    return " Bericht-Datei liegt in der Zwischenablage."
            else:
                grund = "Datei liess sich nicht ablegen"
            log.warning("Bericht-Datei nicht in der Zwischenablage (%s): %s",
                        self._letzter_bericht_pfad, grund)
            auftragsjournal.schreibe("ablage_zwischenablage", f"datei NICHT belegt: {grund}")
        if self._letzter_bericht:
            try:
                QGuiApplication.clipboard().setText(self._letzter_bericht)
            except Exception as fehler:  # noqa: BLE001
                log.exception("Bericht nicht in die Zwischenablage gelegt: %s", fehler)
                return " Bericht konnte nicht kopiert werden."
            ok, grund = zwischenablage_enthaelt_text(self._letzter_bericht)
            if ok:
                auftragsjournal.schreibe("ablage_zwischenablage", "text")
                return " Bericht-Text liegt in der Zwischenablage."
            log.warning("Bericht-Text nicht in der Zwischenablage: %s", grund)
            auftragsjournal.schreibe("ablage_zwischenablage", f"text NICHT belegt: {grund}")
            return ""
        return " Bericht konnte nicht erstellt werden."

    def _bericht_ablegen_nach_auftrag(self) -> str:
        """Legt den Bericht nach jedem Auftrag in die Zwischenablage (siehe
        _bericht_ablegen), sofern in den Einstellungen nicht abgeschaltet.

        Abgelegt wird nur, wenn das CWB-Fenster im Vordergrund ist. Sonst
        wuerde das ueberschreiben, was der Nutzer inzwischen anderswo kopiert
        hat; es wird dann gemerkt und beim naechsten Wechsel ins Fenster
        nachgelegt."""
        if not self._letzter_bericht:
            return " Bericht konnte nicht erstellt werden."
        if not einstellungen_lesen().get("bericht_kopieren", True):
            return ""
        if not self.isActiveWindow():
            self._bericht_wartet = True
            log.info("Bericht vorgemerkt, Fenster ist nicht im Vordergrund")
            return ""
        return self._bericht_ablegen()

    def _bericht_nachlegen(self) -> None:
        """Legt einen vorgemerkten Bericht in die Zwischenablage, sobald das
        Fenster wieder im Vordergrund ist, und sagt es an."""
        if not self._bericht_wartet or not self._letzter_bericht:
            return
        self._bericht_wartet = False
        if self._letzter_bericht_bruecke in self._bruecke_eingefuegt:
            # Ging schon in den Chat (_bruecke_bericht_einfuegen); ihn jetzt
            # noch einmal in die Zwischenablage zu legen lud zum zweiten
            # Einfuegen per Strg+V ein.
            log.info("Vorgemerkter Bericht nicht nachgelegt: Bruecken-Bericht %s "
                     "schon eingefuegt", self._letzter_bericht_bruecke)
            return
        zusatz = self._bericht_ablegen().strip()
        if not zusatz:
            return
        log.info("Vorgemerkter Bericht abgelegt: %s", zusatz)
        # Gehoert zur Abschlussmeldung: beim Fertigwerden war das Fenster nicht
        # im Vordergrund, der Hinweis auf die Zwischenablage kommt erst jetzt.
        # Ohne Unterbrechen: sonst bricht er eine noch laufende "Fertig."-
        # Ansage ab (ein Wechsel ins Fenster folgt oft kurz nach dem Ende).
        self.sprecher.sprich(zusatz, unterbrechen=False, art="fertig")

    @slot_geschuetzt
    def _bericht_erneut_kopieren(self) -> None:
        """F6: legt den Bericht des letzten Auftrags noch einmal als Text in
        die Zwischenablage, egal was inzwischen dort lag. Fuer die Datei gibt
        es die eigene Taste Strg+F7 (_berichtdatei_kopieren)."""
        if not self._letzter_bericht:
            self.sprecher.sprich("Es gibt noch keinen Bericht.", art="fehler")
            return
        self._bericht_wartet = False
        if not zielfenster._in_zwischenablage_legen(self._letzter_bericht):
            self.sprecher.sprich("Bericht konnte nicht kopiert werden.", art="fehler")
            return
        log.info("Bericht-Text erneut in die Zwischenablage gelegt (F6)")
        self.sprecher.sprich("Bericht-Text liegt jetzt in der Zwischenablage.",
                             art="meldung")

    @slot_geschuetzt
    def _berichtdatei_kopieren(self) -> None:
        """Strg+F7: legt die zuletzt gespeicherte Berichtdatei noch einmal als
        Dateiverweis in die Zwischenablage, egal was inzwischen dort lag - so
        laesst sie sich mit Strg+V direkt als Anhang einfuegen."""
        if not self._letzter_bericht_pfad or not self._letzter_bericht_pfad.exists():
            self.sprecher.sprich("Es gibt noch keine gespeicherte Berichtdatei.",
                                 art="fehler")
            return
        self._bericht_wartet = False
        if not datei_in_zwischenablage(self._letzter_bericht_pfad):
            self.sprecher.sprich("Bericht-Datei konnte nicht kopiert werden.",
                                 art="fehler")
            return
        log.info("Berichtdatei erneut in die Zwischenablage gelegt: %s",
                 self._letzter_bericht_pfad)
        self.sprecher.sprich("Bericht-Datei liegt jetzt in der Zwischenablage.",
                             art="meldung")

    # -- Bedienung ----------------------------------------------------------

    @slot_geschuetzt
    def _aus_zwischenablage(self) -> None:
        """F7: holt den Text aus der Zwischenablage, sagt die erkannte
        Auftragsart an und schickt ihn sofort ab.

        Notweg von Hand: gewoehnlich holt der Waechter markierte Auftraege von
        selbst, darum gibt es dafuer keine Kachel mehr. Die erste Zeile im Log
        ist der Beleg, dass die Taste ueberhaupt ankommt - vorher
        (Strg+Umschalt+V) verschluckten die Textfelder sie.

        Die Zwischenablage wird sofort nach dem Lesen geleert - sonst faende
        der Waechter zwei Sekunden spaeter denselben Text noch vor und hielte
        ihn faelschlich fuer einen neuen, zweiten Auftrag. Die Dublettensperre
        (`_dublette_abgewiesen`) prueft hier genauso wie beim Waechter - F7
        ist kein Weg an ihr vorbei."""
        log.info("Aus Zwischenablage aufgerufen (F7)")
        try:
            zwischenablage = QGuiApplication.clipboard()
            text = zwischenablage.text()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zwischenablage nicht lesbar: %s", fehler)
            self.sprecher.sprich("Zwischenablage konnte nicht gelesen werden.",
                                 art="fehler")
            return
        if not text.strip(RANDZEICHEN):
            log.info("Zwischenablage leer")
            self.sprecher.sprich("Zwischenablage ist leer.", art="fehler")
            return
        try:
            zwischenablage.clear()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zwischenablage nicht leerbar: %s", fehler)
        art, inhalt = markierung_erkennen(text)
        inhalt, modell_sticky, modell_hinweis = self._modell_zeile_verarbeiten(art, inhalt)
        log.info(
            "Zwischenablage: %d Zeichen, Art %r, Inhalt %d Zeichen",
            len(text), art or "ohne Markierung", len(inhalt),
        )
        block_angesagt = False
        block_nummer = None
        if art:
            inhalt, weiter, block_angesagt, block_nummer = self._block_verarbeiten(art, inhalt)
            if not weiter:
                return
        if art == "bild":
            # #BILD# fuellt nie das Eingabefeld: die Markierung allein loest
            # schon aus, kein Inhalt noetig. Keine Dublettenpruefung: ein
            # Bildschirmabzug ohne Inhalt ist zwangslaeufig jedes Mal
            # derselbe Text und laeuft immer sofort.
            if not block_angesagt:
                self.sprecher.sprich("Auftrag erhalten.", art="auftrag")
            self._bild_markierung(block_nummer=block_nummer, quelle="Zwischenablage")
            return
        if art in ("run", "admin"):
            # #run# und #admin# fuellen nie das Eingabefeld: sie laufen direkt
            # im Terminal, ohne Claude Code, und ohne Dublettenpruefung -
            # diese Befehle laufen immer sofort, auch wiederholt.
            if not block_angesagt:
                self.sprecher.sprich("Auftrag erhalten.", art="auftrag")
            self._terminal_markierung(art, inhalt, block_nummer=block_nummer,
                                       quelle="Zwischenablage")
            return
        if self._dublette_abgewiesen(art, inhalt):
            return
        if not inhalt:
            # Nur die Markierung, kein Auftrag darunter: dann gilt der ganze
            # Text als Auftrag, damit nichts stillschweigend verlorengeht.
            inhalt = text.strip(RANDZEICHEN)
            art = ""
        ansage = (
            "Code-Auftrag erkannt." if art == "code" else "Auftrag ohne Markierung."
        )
        self._absenden(vorspann=f"Aus Zwischenablage. {ansage}", art=art, inhalt=inhalt,
                        block_angesagt=block_angesagt, block_nummer=block_nummer,
                        modell_sticky=modell_sticky, modell_hinweis=modell_hinweis)

    @slot_geschuetzt
    def _ablage_auftrag(self, art: str, inhalt: str) -> None:
        """Der Wächter hat einen markierten Auftrag gefunden. #run# und
        #admin# laufen direkt im Terminal, #BILD# holt direkt den Screenshot -
        alle drei ohne Eingabefeld, ohne Claude Code und ohne
        Dublettenpruefung, sie laufen immer sofort. Nur #code# und Auftraege
        ohne Markierung gehen an Claude Code und werden vorher durch die
        Dublettensperre (`_dublette_abgewiesen`) geprueft, dann ueber
        _absenden, mit Art und Inhalt direkt uebergeben statt ueber das
        Eingabefeld neu geparst - sonst ginge die Markierung dabei verloren.
        Die Zwischenablage ist zu diesem Zeitpunkt schon geleert (siehe
        ablagewaechter.py)."""
        inhalt, modell_sticky, modell_hinweis = self._modell_zeile_verarbeiten(art, inhalt)
        inhalt, weiter, block_angesagt, block_nummer = self._block_verarbeiten(art, inhalt)
        if not weiter:
            return
        if art == "bild":
            # Keine Dublettenpruefung: siehe _aus_zwischenablage.
            if not block_angesagt:
                self.sprecher.sprich("Auftrag erhalten.", art="auftrag")
            self._bild_markierung(block_nummer=block_nummer, quelle="Zwischenablage")
            return
        if art in ("run", "admin"):
            # Keine Dublettenpruefung: siehe _aus_zwischenablage.
            if not block_angesagt:
                self.sprecher.sprich("Auftrag erhalten.", art="auftrag")
            self._terminal_markierung(art, inhalt, block_nummer=block_nummer,
                                       quelle="Zwischenablage")
            return
        if self._dublette_abgewiesen(art, inhalt):
            return
        self._absenden(vorspann="Auftrag angenommen.", art=art, inhalt=inhalt,
                        block_angesagt=block_angesagt, block_nummer=block_nummer,
                        modell_sticky=modell_sticky, modell_hinweis=modell_hinweis)

    def _eingang_auftrag(self, auftrag) -> None:
        """Duenner, ABSICHTLICH nicht mit @slot_geschuetzt versehener
        Vorspann vor `_eingang_auftrag_geschuetzt`: prueft, ob das Terminal
        (#run#/#admin#) oder der Screenshot-Weg (#BILD#) gerade belegt ist,
        und wirft dann AuftragSpaeter. @slot_geschuetzt faengt JEDE Ausnahme
        ab und verschluckt sie - stuende es hier, wuerde
        core.eingangsordner.verarbeiten() die Ausnahme nie zu sehen bekommen
        und die Datei faelschlich als erledigt gelten. Anders als
        `_ablage_auftrag` darf ein Auftrag aus dem Eingangsordner nie
        verloren gehen: `verarbeiten()` legt die Datei bei AuftragSpaeter
        unverarbeitet zurueck, der naechste Blick des Waechters versucht sie
        erneut, sobald die Ressource frei ist."""
        art = auftrag.art
        if art == "bild" and self._bild_faden is not None and self._bild_faden.isRunning():
            raise AuftragSpaeter("Screenshot-Weg belegt")
        if art in ("run", "admin") and self._terminal_faden is not None \
                and self._terminal_faden.isRunning():
            raise AuftragSpaeter("Terminal belegt")
        self._eingang_auftrag_geschuetzt(auftrag)

    @slot_geschuetzt
    def _eingang_auftrag_geschuetzt(self, auftrag) -> None:
        """Der eigentliche Eingangsordner-Auftrag, abgesichert durch
        @slot_geschuetzt wie jeder andere Qt-Slot - die Belegt-Pruefung dafuer
        steht in `_eingang_auftrag` davor (siehe dort). Sonst identisch zu
        `_ablage_auftrag`: gleiche Blocknummern-, Dubletten- und
        Projektpruefung; nur `vorspann` nennt zusaetzlich die Quelle.

        Kommt der Auftrag von der Bruecke (core/bruecke.py, Vorhaben
        "Bruecke" Stufe B3, `auftrag.quelle == "bruecke"`), wird zusaetzlich
        seine `auftrag_nummer` mitgefuehrt - sie kommt am Ende bei
        `_fertig`/`_terminal_fertig`/`_bild_fertig` wieder heraus und sorgt
        dort fuer den Bericht-Upload - und die Blockansage nennt "Claude" als
        Quelle, weil sie es dort tatsaechlich ist."""
        art, inhalt = auftrag.art, auftrag.inhalt
        if (auftrag.quelle == orchestrator.QUELLE and auftrag.auftrag_nummer is not None
                and auftrag.datei is not None):
            self._orch_nummern[auftrag.datei.name] = auftrag.auftrag_nummer
        von_bruecke = auftrag.quelle == QUELLE_BRUECKE
        bruecke_nummer = auftrag.auftrag_nummer if von_bruecke else None
        log.info(
            "Eingangsordner: Auftrag erhalten (Quelle %s, Projekt %r, Art %s, %d Zeichen)",
            auftrag.quelle, auftrag.projekt, art or "ohne Markierung", len(inhalt),
        )
        if von_bruecke:
            log.info("Brücke: Auftrag gestartet (Nummer %s, Art %s)",
                      bruecke_nummer, art or "ohne Markierung")
        inhalt, modell_sticky, modell_hinweis = self._modell_zeile_verarbeiten(art, inhalt)
        inhalt, weiter, block_angesagt, block_nummer = self._block_verarbeiten(
            art, inhalt, herkunft="von Claude" if von_bruecke else "")
        if not weiter:
            # Unvollstaendiger Block, vormerkt als self._pending_block - F5/
            # Escape braucht eine anwesende Person, die ein Eingangsordner-
            # oder Bruecken-Auftrag nicht hat. Die Datei bliebe sonst fuer
            # immer in laeuft/ liegen und wuerde bei jedem Neustart erneut
            # als unvollstaendig vorgemerkt.
            if auftrag.datei is not None:
                verwerfen(auftrag.datei, "Block kam unvollständig an, braucht Eingabe vor Ort")
            return
        quelle_anzeige = "Brücke" if von_bruecke else "Eingang"
        if art == "bild":
            if not block_angesagt:
                self.sprecher.sprich("Auftrag erhalten.", art="auftrag")
            self._bild_markierung(bruecke_nummer=bruecke_nummer, eingang_datei=auftrag.datei,
                                   block_nummer=block_nummer, quelle=quelle_anzeige)
            return
        if art in ("run", "admin"):
            if not block_angesagt:
                self.sprecher.sprich("Auftrag erhalten.", art="auftrag")
            self._terminal_markierung(art, inhalt, bruecke_nummer=bruecke_nummer,
                                       eingang_datei=auftrag.datei, block_nummer=block_nummer,
                                       quelle=quelle_anzeige)
            return
        if self._dublette_abgewiesen(art, inhalt):
            return
        self._absenden(vorspann=f"Auftrag aus dem Eingangsordner ({auftrag.quelle}).",
                        art=art, inhalt=inhalt, block_angesagt=block_angesagt,
                        bruecke_nummer=bruecke_nummer, block_nummer=block_nummer,
                        projekt_vorgegeben=auftrag.projekt, eingang_datei=auftrag.datei,
                        modell_sticky=modell_sticky, modell_hinweis=modell_hinweis)

    def _eingang_fremde_melden(self, projekte: dict) -> None:
        """Rueckruf des Eingangswaechters (core/eingangsordner.py, Block 63):
        `projekte` ist Projektname -> Anzahl der wartenden Auftragsdateien,
        die nicht zum hier offenen Projekt passen. Die Kopfzeilenanzeige wird
        bei jedem Blick aktualisiert; gesprochen wird nur einmal je neuer
        Wartestellung und nur, solange gerade kein eigener Auftrag laeuft -
        sonst wuerde die Ansage mitten in eine laufende Antwort platzen."""
        if not hasattr(self, "ausgabekopf"):
            # Eingangswaechter.starten() blickt sofort einmal nach (siehe
            # core/eingangsordner.py) - zu diesem Zeitpunkt in _aufbauen()
            # existiert die Kopfzeile noch nicht. Der naechste Blick
            # (PRUEF_ABSTAND_MS) holt die Anzeige nach.
            return
        self._unbekannte_verwerfen()
        try:
            self.ausgabekopf.eingang_fremde_zeigen(projekte)
            # Block 82: derselbe periodische Blick des Eingangswaechters
            # aktualisiert auch "Wartet: ..." - eigene (oder unspezifische)
            # und fremde liegen gebliebene Auftragsdateien aendern sich sonst
            # ohne eigenes Signal (siehe _wartet_kennungen).
            self._statusleiste_aktualisieren()
            namen = frozenset(projekte.keys())
            if not namen:
                self._eingang_fremde_angesagt = frozenset()
                ansagegedaechtnis.pruefen("fremde_projekte", "")
                return
            if namen == self._eingang_fremde_angesagt or self._laeuft():
                return
            self._eingang_fremde_angesagt = namen
            # Gemerkt ueber Neustarts: dieselbe Lage wird nie ein zweites Mal angesagt.
            if not ansagegedaechtnis.pruefen("fremde_projekte", ",".join(sorted(namen))):
                return
            geordnet = sorted(namen)
            ziel = geordnet[0] if len(geordnet) == 1 else \
                ", ".join(geordnet[:-1]) + " und " + geordnet[-1]
            self.sprecher.sprich(f"Es warten Aufträge für Projekt {ziel}.",
                                  unterbrechen=False, art="hinweis")
        except Exception as fehler:  # noqa: BLE001
            log.exception("Fremde Projekte im Eingang nicht gemeldet: %s", fehler)
        self._auto_projekt_pruefen()

    def _unbekannte_verwerfen(self) -> None:
        """Wirft Eingangsdateien fuer ein unbekanntes Projekt nach 15 Minuten
        weg (core/eingangsordner.py, unbekannte_verwerfen) und sagt es einmal
        an, damit sie nicht endlos in "Wartet" haengen."""
        try:
            namen = None

            def bekannt(name: str) -> bool:
                nonlocal namen
                if namen is None:
                    namen = [p.name for p in projekte_finden()]
                    if not namen:
                        log.warning("Projektliste leer: im Eingang wird nichts verworfen")
                return bekannt_unter(namen)(name)

            verworfen = unbekannte_verwerfen(bekannt)
            if not verworfen:
                return
            projekte = sorted({projekt for projekt, _datei in verworfen})
            if self._auto_projekt_unbekannt_angesagt in projekte:
                self._auto_projekt_unbekannt_angesagt = None
            ziel = ", ".join(projekte[:-1]) + " und " + projekte[-1] if len(projekte) > 1 \
                else projekte[0]
            anzahl = len(verworfen)
            satz = (f"Ein Auftrag für das unbekannte Projekt {ziel} wurde verworfen."
                    if anzahl == 1 else
                    f"{anzahl} Aufträge für das unbekannte Projekt {ziel} wurden verworfen.")
            log.warning("Eingang: %s", satz)
            self.sprecher.sprich(satz, unterbrechen=False, art="hinweis")
            self._statusleiste_aktualisieren()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Unbekannte Projekte im Eingang nicht verworfen: %s", fehler)

    def _naechstes_fremdes_projekt(self) -> Projekt | None:
        """Liefert das Projekt des aeltesten wartenden Eingangs-/Bruecken-
        Auftrags, der nicht zum hier offenen Projekt passt (core/
        eingangsordner.py, naechste_fremde_projekt_datei) - None, wenn keiner
        wartet, der Schalter "Automatisch Projekt wechseln" aus ist oder das
        genannte Projekt unbekannt ist (dann nur einmalig angesagt). Block
        80: gemeinsame Grundlage fuer den Leerlauf-Wechsel
        (_auto_projekt_pruefen) UND die Pruefung beim Ende einer Kontingent-
        Pause (_kontingent_fortsetzen) - beide muessen dieselbe
        Eingangsreihenfolge befolgen, nicht nur der Leerlauf."""
        if not einstellungen_lesen().get("auto_projektwechsel", True):
            return None
        ziel_roh = naechste_fremde_projekt_datei(self.projekt.name)
        if ziel_roh is None:
            self._auto_projekt_unbekannt_angesagt = None
            ansagegedaechtnis.pruefen("unbekanntes_projekt", "")
            return None
        projekt = next(
            (p for p in projekte_finden() if projekt_gleichwertig(p.name, ziel_roh)), None
        )
        if projekt is None:
            if self._auto_projekt_unbekannt_angesagt != ziel_roh:
                self._auto_projekt_unbekannt_angesagt = ziel_roh
                log.warning("Eingang: Auftrag fuer unbekanntes Projekt wartet: %s", ziel_roh)
                if not ansagegedaechtnis.pruefen("unbekanntes_projekt", ziel_roh):
                    return None
                self.sprecher.sprich(
                    f"Ein Auftrag für ein unbekanntes Projekt namens {ziel_roh} "
                    "wartet im Eingang.", unterbrechen=False, art="hinweis")
            return None
        self._auto_projekt_unbekannt_angesagt = None
        return projekt

    def _auto_projekt_pruefen(self) -> None:
        """Block 70, Teil C: wechselt im Leerlauf von selbst zu einem anderen
        bekannten Projekt, sobald dort der aelteste wartende Auftrag aus
        Eingang oder Bruecke wartet (_naechstes_fremdes_projekt) - wie F9,
        nur ohne Zutun des Nutzers. Aufgerufen nach jedem Blick des
        Eingangswaechters (_eingang_fremde_melden), auch dann, wenn gerade
        kein eigener Auftrag lief. Kein Wechsel, solange ein eigener Auftrag
        laeuft, die Warteschlange nicht leer ist, eine Kontingent-Pause
        laeuft, eine Rueckfrage offen ist oder ein Wechsel schon im Gang ist
        - sonst verschwaende das Fenster unter der Hand, waehrend noch etwas
        darauf wartet."""
        if (self._laeuft() or self._warteschlange or self._kontingent_info is not None
                or self.frage_offen or self.wechselt):
            return
        projekt = self._naechstes_fremdes_projekt()
        if projekt is None:
            return
        # Ueber den Ereignisumlauf entkoppelt, statt den Wechsel (der dieses
        # Fenster schliesst) noch innerhalb des Waechter-Rueckrufs
        # auszufuehren, aus dem diese Methode selbst aufgerufen wird.
        QTimer.singleShot(0, lambda zielprojekt=projekt: self._auto_projekt_wechseln(zielprojekt))

    def _auto_projekt_wechseln(self, projekt: Projekt) -> None:
        """Fuehrt den in `_auto_projekt_pruefen` entschiedenen Wechsel aus -
        derselbe Ablauf wie `_projekt_wechseln` (F9), nur ohne die
        Projektwahl zu zeigen: `Start._oeffnen` oeffnet das Zielprojekt
        direkt."""
        if self._laeuft():
            log.info("Automatischer Projektwechsel zu %s verschoben: es laeuft noch etwas",
                     projekt.name)
            return
        log.info("Automatischer Projektwechsel zu %s", projekt.name)
        auftragsjournal.schreibe("projektwechsel",
                                 f"von={self.projekt.name} nach={projekt.name} automatisch",
                                 ohne_kontext=True)
        self.sprecher.sprich(f"Wechsle zu Projekt {projekt.name}.", art="immer")
        self.wechselt = True
        if self in OFFENE_FENSTER:
            OFFENE_FENSTER.remove(self)
        _orch_beenden(self)
        try:
            self.faden.beenden()
            self.faden.wait(5000)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Faden beim automatischen Projektwechsel nicht beendet: %s", fehler)
        self.start_fenster = Start(self.sprecher, Werkbank, automatisch=False)
        self.start_fenster.projekt_oeffnen(projekt)
        self.close()

    # -- Bruecke (core/bruecke.py, Vorhaben "Bruecke" Stufe B3) ----------------

    def _bruecke_zustand_anwenden(self) -> None:
        """Bringt Thread, Kachel und Kopfzeile auf den Stand des Schalters
        "bruecke_aktiv" (einstellungen.json). Aufgerufen beim Start, nach
        jedem Schliessen der Einstellungen (F12) und von
        `_bruecke_umschalten` (Kachel/Umschalt+F8)."""
        schalter = bool(einstellungen_lesen().get("bruecke_aktiv", True))
        pausiert = schalter and notaus_pause.bruecke_pausiert()
        an = schalter and not pausiert
        self.ausgabekopf.bruecke_zeigen(an, pausiert)
        text = "Brücke pausiert" if pausiert else ("Brücke an" if an else "Brücke aus")
        symbol = BRUECKE_SYMBOL_AN if an else BRUECKE_SYMBOL_AUS
        self.kacheln.kachel_beschriften(BRUECKE_KENNUNG, text, text, symbol)
        self.kacheln.kachel_faerben(BRUECKE_KENNUNG,
                                    BRUECKE_FARBE_AN if an else BRUECKE_FARBE_AUS)
        if an:
            self._bruecke_starten()
        else:
            self._bruecke_stoppen()

    def _bruecke_starten(self) -> None:
        if self.bruecke_faden is not None and self.bruecke_faden.isRunning():
            return
        self.bruecke_faden = BrueckenFaden(markierung_erkennen, self)
        self.bruecke_faden.nicht_erreichbar.connect(self._bruecke_nicht_erreichbar)
        self.bruecke_faden.start()
        log.info("Brücke gestartet")

    def _bruecke_stoppen(self) -> None:
        if self.bruecke_faden is None:
            return
        self.bruecke_faden.anhalten()
        self.bruecke_faden.wait(2000)
        self.bruecke_faden = None
        log.info("Brücke angehalten")

    @slot_geschuetzt
    def _bruecke_umschalten(self) -> None:
        """Kachel "Brücke" / Umschalt+F8: schaltet den persistierten Schalter
        um - dieselbe Einstellung wie die Kachel in F12 → Verhalten, nur ohne
        den Umweg über das Einstellungsfenster. Waehrend der Not-Aus-Pause
        beendet sie die Pause, und die Brücke läuft wieder."""
        werte = einstellungen_lesen()
        if notaus_pause.bruecke_pausiert():
            self._notaus_pause_abbrechen()
            self._bruecke_zustand_anwenden()
            self._leitstand_zustand_anwenden()
            self.sprecher.sprich("Brücke an.", art="immer")
            return
        self._notaus_pause_abbrechen()
        an = not bool(werte.get("bruecke_aktiv", True))
        werte["bruecke_aktiv"] = an
        einstellungen_schreiben(werte)
        self._bruecke_zustand_anwenden()
        self.sprecher.sprich(f"Brücke {'an' if an else 'aus'}.", art="immer")

    @slot_geschuetzt
    def _bruecke_nicht_erreichbar(self) -> None:
        """Kommt vom BrueckenFaden, nachdem fünf Minuten lang kein
        Abholversuch gelang (wissen/plan_bruecke.md, Stufe B3) - genau einmal
        pro Ausfallphase, nicht bei jedem einzelnen Fehlschlag."""
        self._status_zeigen("Brücke nicht erreichbar.")
        self.sprecher.sprich("Brücke nicht erreichbar.", art="fehler")

    # -- Orchestrator (core/orchestrator.py, core/orchestrator_ansicht.py) ----

    def _orch_einrichten(self, mitte: QWidget) -> None:
        """Haengt die Orchestrator-Ansicht neben die normale Arbeitsflaeche
        (Seitenstapel). Nur gerufen, wenn der Schalter \"orchestrator\" an ist."""
        ansicht = OrchestratorAnsicht(self.projekt, self.sprecher, self)
        ansicht.frage_gestellt.connect(self._orch_frage)
        ansicht.zurueck_gewuenscht.connect(self._orch_umschalten)
        ansicht.neustart_gewuenscht.connect(self._neustart)
        ansicht.fenster_zustand_setzen(self._orch_fensterzustand)
        stapel = QStackedWidget()
        stapel.addWidget(mitte)
        stapel.addWidget(ansicht)
        self._orch_ansicht = ansicht
        self._orch_stapel = stapel
        self._huelle_layout.addWidget(stapel, 1)
        # Meldungen, die der letzte Lauf nicht mehr zustellen konnte, kommen
        # kurz nach dem Start in die Orchestrator-Sitzung.
        if ansicht.schlange.anzahl():
            QTimer.singleShot(3000, ansicht.nachholen)
        log.info("Orchestrator-Ansicht eingerichtet (Strg+O)")

    def _orch_fensterzustand(self) -> dict:
        """Stand fuer das Werkzeug `status`; gelesen aus dem Faden der
        Orchestrator-Sitzung, darum nur einfache Werte."""
        return {"projekt": self.projekt.name, "laeuft": bool(self._laeuft()),
                "wartet": len(self._warteschlange),
                "taetigkeit": self._letzte_taetigkeit}

    def _orch_sichtbar(self) -> bool:
        return (self._orch_stapel is not None
                and self._orch_stapel.currentWidget() is self._orch_ansicht)

    def _senden_taste(self) -> None:
        """Strg+Eingabe bei eingeschaltetem Orchestrator."""
        if self._orch_sichtbar():
            self._orch_ansicht.senden()
        else:
            self._absenden()

    @slot_geschuetzt
    def _orch_umschalten(self) -> None:
        """Strg+O: wechselt zwischen Claude-Code-Ansicht und Orchestrator."""
        if self._orch_stapel is None:
            return
        if self._orch_sichtbar():
            self._orch_stapel.setCurrentWidget(self._arbeitsflaeche)
            self._waechter_platzieren()
            self.eingabe.setFocus()
            self.sprecher.sprich("Claude Code.", art="immer")
        else:
            self._orch_stapel.setCurrentWidget(self._orch_ansicht)
            self._waechter_platzieren()
            self._orch_ansicht.fokus_setzen()
            self.sprecher.sprich("Orchestrator.", art="immer")

    def _waechter_platzieren(self) -> None:
        """Setzt den Waechter-Platzhalter fest links neben den grossen
        Statusbalken der gerade sichtbaren Ansicht."""
        try:
            ziel = (self._orch_ansicht.titel_zeile if self._orch_sichtbar()
                    else self._balken_quer)
            platz = self.waechter_platzhalter
            for zeile in (self._balken_quer, getattr(self._orch_ansicht, "titel_zeile", None)):
                if zeile is not None and zeile is not ziel:
                    zeile.removeWidget(platz)
            if ziel.indexOf(platz) < 0:
                ziel.insertWidget(0, platz, 0, Qt.AlignVCenter)
            platz.show()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Wächter nicht umgesetzt: %s", fehler)

    @slot_geschuetzt
    def _orch_frage(self, satz: str, kurz_satz: str) -> None:
        self.sprecher.melde("wartet", f"Orchestrator fragt. {kurz_satz}", sprechen=True,
                            art="frage")

    def _nach_unsauberem_ende_behandeln(self) -> None:
        """Folgte dieser Start auf einen harten Abbruch (Lauf-Marker, siehe
        core/absturzschutz.py), werden die damals angenommenen, nicht
        abgeschlossenen Auftraege dieses Projekts als "unterbrochen"
        markiert statt wieder aufgenommen: Journal, Verlauf, und bei
        Bruecken-Auftraegen ein Bericht, damit der Absender neu bestellt.
        Gesprochen wird nichts - der Nutzer hoert schon den Warnton."""
        if not absturzschutz.unsauber_abholen():
            return
        try:
            unterbrochen = unterbrochene_markieren(markierung_erkennen, self.projekt.name)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Unterbrochene Auftraege nicht markiert: %s", fehler)
            unterbrochen = []
        satz = "Der letzte Lauf von CWB endete unsauber (Absturz)."
        if unterbrochen:
            satz += (f" {len(unterbrochen)} Aufträge waren unterbrochen und werden NICHT "
                     "wiederholt, bitte neu bestellen."
                     if len(unterbrochen) > 1 else
                     " Ein Auftrag war unterbrochen und wird NICHT wiederholt, "
                     "bitte neu bestellen.")
        self._verlauf_anhaengen(satz, "hinweis")
        for auftrag in unterbrochen:
            if auftrag.quelle == QUELLE_BRUECKE and auftrag.auftrag_nummer is not None:
                block_nummer, _inhalt, _voll = block_erkennen(auftrag.art, auftrag.inhalt)
                self._bruecke_bericht_hochladen(
                    auftrag.auftrag_nummer,
                    "UNTERBROCHEN: CWB ist waehrend dieses Auftrags abgestuerzt. Der Auftrag "
                    "wurde nicht abgeschlossen und nicht wiederholt - bitte neu bestellen.",
                    block_nummer=block_nummer)

    def _bruecke_bericht_hochladen(self, auftrag_nummer, text: str,
                                   block_nummer=None) -> None:
        """Laedt den Bericht/die Ausgabe eines Bruecken-Auftrags hoch, ohne
        die Oberflaeche zu blockieren - eigener Thread pro Hochladung
        (core/bruecke.py.BerichtFaden), wie beim Terminal- oder
        Bild-Auftrag. Ein Fehlschlag bleibt still (nur Log), passend zu
        "Netzfehler still" aus wissen/plan_bruecke.md."""
        if block_nummer is None:
            block_nummer = getattr(self, "_laufender_block_nummer", None)
        faden = BerichtFaden(auftrag_nummer, text, self, block=block_nummer)
        faden.fertig_da.connect(functools.partial(self._bruecke_bericht_fertig, faden))
        self._bruecke_berichte.append(faden)
        faden.start()

    def _bruecke_protokoll_ablegen(self, text: str, art: str = "hinweis",
                                   auftrag_nummer=None, titel: str | None = None,
                                   danach=None) -> None:
        """Legt zusaetzlich zum Chat-Weg einen CWB-Hinweis oder Fehler ins
        Ablagefach der Bruecke (core/bruecke.py.ProtokollFaden), damit die KI
        ihn jederzeit nachlesen kann. Nie blockierend, Fehler nur im Log; ohne
        eingerichtete Bruecke passiert nichts. `danach(protokollnummer)` wird
        nach dem Ablegen gerufen, mit None, wenn nichts abgelegt werden
        konnte - auch ohne Bruecke und bei jedem Fehler."""
        try:
            if not text or zugangsdaten_lesen() is None:
                if danach is not None:
                    danach(None)
                return
            projekt = getattr(getattr(self, "projekt", None), "name", None)
            faden = ProtokollFaden(text, art, projekt, auftrag_nummer, titel, self)
            faden.danach = danach
            faden.fertig_da.connect(functools.partial(self._bruecke_protokoll_fertig, faden))
            self._bruecke_protokolle.append(faden)
            faden.start()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Protokoll nicht abgelegt: %s", fehler)
            if danach is not None:
                danach(None)

    @slot_geschuetzt
    def _bruecke_protokoll_fertig(self, faden, erfolg: bool) -> None:
        if faden in self._bruecke_protokolle:
            self._bruecke_protokolle.remove(faden)
        if faden.danach is not None:
            try:
                faden.danach(faden.nummer if erfolg else None)
            except Exception as fehler:  # noqa: BLE001
                log.exception("Meldung nach dem Ablegen nicht gesendet: %s", fehler)

    def _bericht_zustellen(self, nummer, text: str, bilanz: dict, block_nummer,
                           ziel) -> None:
        """Bruecken-Bericht (#CODE#): legt den Volltext ins Ablagefach und
        schickt nur eine Kurzmeldung in den Chat. Ist der Schalter
        "bericht_voll_im_chat" an, geht der Volltext wie frueher hinein."""
        if einstellungen_lesen().get("bericht_voll_im_chat", False):
            self._bruecke_bericht_einfuegen(nummer, text, ziel)
            return
        status = ("fehler" if bilanz.get("fehler")
                  else "abgebrochen" if bilanz.get("abgebrochen") else "fertig")
        projekt = getattr(getattr(self, "projekt", None), "name", None)
        zeichen = len(text)
        dateien = len(bilanz.get("geaendert") or [])

        def senden(protokoll) -> None:
            meldung = zustellwache.kurzmeldung_bericht(
                nummer, projekt, block_nummer, status, protokoll, zeichen, dateien)
            self._bruecke_bericht_einfuegen(nummer, meldung, ziel)

        self._bruecke_protokoll_ablegen(text, "bericht", nummer, f"Auftrag {nummer}",
                                        danach=senden)

    def _hinweis_ablegen(self, nummer, art: str, text: str) -> None:
        """Rueckruf der Zustellwache fuer jeden CWB-Hinweis (Zeitwache,
        Zustellwache, Screenshot-Hinweis)."""
        titel = "Zeitwache" if art.startswith("zeit") else "Zustellwache"
        if art == "hinweis_bild":
            titel = "Screenshot"
        self._bruecke_protokoll_ablegen(text, "hinweis", nummer, titel)

    def _bruecke_bericht_einfuegen(self, auftrag_nummer, text: str, ziel) -> bool:
        """Fuegt den Bericht eines Bruecken-Auftrags (#CODE#) ins zuletzt
        aktive Chatfenster ein - wie bei #RUN# (`_terminal_fertig`), also auch
        dann, wenn CWB nicht im Vordergrund ist. Hoechstens einmal je
        Bruecken-Nummer: `_bruecke_eingefuegt` verhindert, dass derselbe
        Bericht ein zweites Mal im Chat landet (auch das Nachlegen beim
        Aktivieren, `_bericht_nachlegen`, schaut dort nach). Rueckgabe: wurde
        eingefuegt bzw. eingereiht."""
        if auftrag_nummer in self._bruecke_eingefuegt:
            log.info("Bruecken-Bericht %s schon eingefuegt, nicht erneut", auftrag_nummer)
            return False
        if not text:
            return False
        self._bruecke_eingefuegt.add(auftrag_nummer)
        log.info("Bruecken-Bericht %s wird eingefuegt (Ziel: %s)", auftrag_nummer,
                 (ziel[1][:60] if ziel and len(ziel) > 1 else ziel))
        # Zustellwache: erster Versuch jetzt, bei Misserfolg Wiederholungen
        # und Hinweis (core/zustellwache.py).
        eingereiht = self._zustellen_versuchen(auftrag_nummer, "code", text, ziel)
        if eingereiht is not None:
            if zielfenster.UNTER_WINDOWS:
                return self._zustellwache_holen().ist_zugestellt(auftrag_nummer, "code")
            return eingereiht
        if zielfenster.UNTER_WINDOWS:
            erfolg = bool(zielfenster.einfuegen(ziel, text))
            if not erfolg:
                log.info("Bruecken-Bericht %s liegt in der Zwischenablage", auftrag_nummer)
            return erfolg
        _einfuegen_mit_kennung(self._einfueger_holen(), ziel, text,
                               auftragsjournal.kennung(auftrag_nummer, None, "code"))
        return True

    def _zustellwache_holen(self):
        """Legt die Zustellwache beim ersten Gebrauch an."""
        if getattr(self, "_zustellwache", None) is None:
            self._zustellwache = zustellwache.Zustellwache(
                self._zustell_einreihen,
                lambda ms, funktion: QTimer.singleShot(ms, funktion),
                (lambda: getattr(einfueger, "_letztes_ziel", None))
                if zielfenster.UNTER_WINDOWS else einfueger.ziel_finden,
                self._zustellung_ansagen,
                self._zustell_pruefen if not zielfenster.UNTER_WINDOWS else None,
                self._zustell_kachel_zeigen,
                self._hinweis_ablegen,
            )
        return self._zustellwache

    def _zustell_pruefen(self, ziel, manuell: bool = False) -> tuple[bool, str]:
        """Ist die Luft rein fuer eine Zustellung? (Chat erreichbar, seit 3
        Sekunden keine Eingabe; bei der Zustelltaste ohne Ruhezeit.)"""
        return self._einfueger_holen().zustellung_moeglich(ziel, manuell)

    def _zustellung_ansagen(self, zahl: int) -> None:
        """Die eine Ansage, wenn Ergebnisse laenger als 20 Sekunden warten;
        sie liegen schon auf der Bruecke. Wiederholt wird nur bei mehr."""
        log.info("%d Ergebnisse warten auf Zustellung", zahl)
        try:
            if not ansagegedaechtnis.pruefen("ergebnisse_warten", str(zahl)):
                return
            if not zielfenster.UNTER_WINDOWS and einfueger.suche_erfolglos():
                satz = ("Kein Chatfenster gefunden, Ergebnis liegt auf der Brücke."
                        if zahl == 1 else
                        f"Kein Chatfenster gefunden, {zahl} Ergebnisse liegen auf der Brücke.")
                self.sprecher.sprich(satz, unterbrechen=False, art="hinweis")
                return
            satz = ("Ein Ergebnis wartet." if zahl == 1 else f"{zahl} Ergebnisse warten.")
            self.sprecher.sprich(f"{satz} Mit Strg+F8 zustellen.",
                                 unterbrechen=False, art="hinweis")
        except Exception as fehler:  # noqa: BLE001
            log.exception("Wartemeldung nicht gesprochen: %s", fehler)

    def _zustell_kachel_zeigen(self, zahl: int) -> None:
        """Kachel "Ergebnisse zustellen": zeigt die Zahl der Wartenden, ist
        ausgeblendet, wenn nichts wartet."""
        try:
            if zahl == 0:
                ansagegedaechtnis.pruefen("ergebnisse_warten", "")
            if zahl > 0:
                text = f"Ergebnisse zustellen ({zahl})"
                self.kacheln.kachel_beschriften(
                    ZUSTELL_KENNUNG, text,
                    f"Ergebnisse zustellen, {zahl} warten", ZUSTELL_SYMBOL)
            self.kacheln.kachel_zeigen(ZUSTELL_KENNUNG, zahl > 0)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zustellkachel nicht umgeschaltet: %s", fehler)

    @slot_geschuetzt
    def _ergebnisse_zustellen(self) -> None:
        """Strg+F8 / Kachel: stellt alle wartenden Ergebnisse der Reihe nach
        zu (2 Sekunden Abstand), auch wenn Robert gerade erst getippt hat."""
        wache = self._zustellwache_holen()
        zahl, grund = wache.vorbereiten_manuell()
        if zahl == 0:
            self.sprecher.sprich("Keine Ergebnisse warten.", art="immer")
            return
        if grund:
            self.sprecher.sprich(
                f"{zahl} Ergebnisse warten, Zustellung jetzt nicht möglich: {grund}.",
                art="immer")
            return
        self.sprecher.sprich(f"Stelle {zahl} Ergebnisse zu.", art="immer")
        wache.manuell_starten()

    def _zustellen_versuchen(self, nummer, art: str, text: str, ziel,
                              bild_pfad: str | None = None):
        """Gibt das Ergebnis an die Zustellwache; None, wenn sie sich nicht
        anlegen liess (dann gilt der alte, direkte Weg). Ab hier ist das
        Einfuegen moeglich: das Journal zaehlt seine Frist erst jetzt."""
        if art in ("code", "run"):
            auftragsjournal.zustellbereit(nummer=nummer, art=art)
        try:
            wache = self._zustellwache_holen()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zustellwache nicht angelegt: %s", fehler)
            return None
        return wache.zustellen(nummer, art, text, ziel, bild_pfad)

    def _zustell_einreihen(self, ziel, text, bild_pfad, kennung, rueckruf) -> bool:
        """Einreihen fuer die Zustellwache: Linux ueber den Einfueger, Windows
        ueber zielfenster.einfuegen (kennt kein Bild)."""
        if zielfenster.UNTER_WINDOWS:
            if bild_pfad:
                return False
            rueckruf(bool(zielfenster.einfuegen(ziel, text)), "Windows-Einfuegen")
            return True
        einfueger_objekt = self._einfueger_holen()
        einfueger_objekt.naechste_kennung = kennung
        einfueger_objekt.naechster_rueckruf = rueckruf
        if bild_pfad:
            einfueger_objekt.hinzufuegen(ziel, text, bild_pfad)
        else:
            einfueger_objekt.hinzufuegen(ziel, text)
        return True

    def _bild_in_chat(self, bruecke_nummer, pfad: str) -> None:
        """Brueckenauftrag #BILD# (nur Linux): das Bild geht ins gemerkte
        Chatfenster (Strg+V, Enter), Zustellwache wiederholt einmal."""
        if zielfenster.UNTER_WINDOWS:
            return
        ziel, self._bild_ziel = self._bild_ziel, None
        ergebnis = self._zustellen_versuchen(
            bruecke_nummer, "bild", f"[Bild {Path(pfad).name}]", ziel, bild_pfad=pfad)
        log.info("Bild zu Bruecken-Auftrag %s %s", bruecke_nummer,
                 "eingereiht" if ergebnis else "nicht eingereiht")

    def _bild_hinweis(self, bruecke_nummer, grund: str) -> None:
        """Brueckenauftrag #BILD# ohne Bild: die KI erfaehrt es im Chat."""
        if zielfenster.UNTER_WINDOWS:
            return
        ziel, self._bild_ziel = self._bild_ziel, None
        self._zustellen_versuchen(
            bruecke_nummer, "hinweis_bild",
            f"CWB-Hinweis: Screenshot zu Auftrag {bruecke_nummer} fehlgeschlagen: {grund}",
            ziel)

    @slot_geschuetzt
    def _bruecke_bericht_fertig(self, faden, erfolg: bool) -> None:
        if faden in self._bruecke_berichte:
            self._bruecke_berichte.remove(faden)
        try:
            # Ab jetzt laeuft die Uhr der Zustellwache (erfolgreich oder nicht:
            # in den Chat soll der Bericht trotzdem).
            nummer_uhr = getattr(faden, "_auftrag_nummer", None)
            if nummer_uhr is not None:
                self._zustellwache_holen().hochgeladen(nummer_uhr)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zustellwache (hochgeladen): %s", fehler)
        if not erfolg:
            log.error("Bruecken-Bericht nicht hochgeladen (auch Wiederholung scheiterte)")
        else:
            nummer = getattr(faden, "_auftrag_nummer", None)
            try:
                if nummer is not None:
                    bericht_vermerken(int(nummer))
            except (TypeError, ValueError):
                log.warning("Berichtsvermerk: ungueltige Nummer %r", nummer)

    # -- Leitstand (core/leitstand.py, Block 72, wissen/plan_leitstand.md) ----

    def _leitstand_zustand_anwenden(self) -> None:
        """Bringt Kachel und Kopfzeile auf den Stand des Schalters
        "leitstand_aktiv" (einstellungen.json). Aufgerufen beim Start und
        nach jedem Schliessen der Einstellungen (F12), wie
        `_bruecke_zustand_anwenden`."""
        an = leitstand.aktiv()
        self.ausgabekopf.leitstand_zeigen(an)
        text = "Leitstand an" if an else "Leitstand aus"
        symbol = LEITSTAND_SYMBOL_AN if an else LEITSTAND_SYMBOL_AUS
        self.kacheln.kachel_beschriften(LEITSTAND_KENNUNG, text, text, symbol)
        self.kacheln.kachel_faerben(LEITSTAND_KENNUNG,
                                    LEITSTAND_FARBE_AN if an else LEITSTAND_FARBE_AUS)

    @slot_geschuetzt
    def _leitstand_umschalten(self) -> None:
        """Kachel "Leitstand" / Umschalt+F9: schaltet den persistierten
        Schalter um - dieselbe Einstellung wie F12 -> Leitstand, nur ohne den
        Umweg ueber das Einstellungsfenster. Waehrend der Not-Aus-Pause
        beendet sie die Pause, und der Leitstand laeuft wieder."""
        werte = einstellungen_lesen()
        if notaus_pause.leitstand_pausiert():
            self._notaus_pause_abbrechen()
            self._bruecke_zustand_anwenden()
            self._leitstand_zustand_anwenden()
            self.sprecher.sprich("Leitstand an.", art="immer")
            return
        self._notaus_pause_abbrechen()
        an = not bool(werte.get("leitstand_aktiv", True))
        werte["leitstand_aktiv"] = an
        einstellungen_schreiben(werte)
        self._leitstand_zustand_anwenden()
        if an and leitstand.wirksamer_anbieter().api_schluessel is None:
            self.sprecher.sprich("Leitstand an. Kein Gemini-Schlüssel hinterlegt.", art="fehler")
        else:
            self.sprecher.sprich(f"Leitstand {'an' if an else 'aus'}.", art="immer")

    def _leitstand_nach_auftrag(self, bilanz: dict, block_nummer: int | None,
                                 satz: str) -> None:
        """Block 72/73: nach jedem abgeschlossenen #CODE#-Auftrag (aufgerufen
        aus `_fertig`) eines Projekts mit wissen/nachtplan.md fragt Leitstand
        den gewaehlten Anbieter (Gemini oder Anthropic, F12 -> Leitstand), ob
        und wie es weitergeht. Prueft dafuer zuerst synchron die Grenzen
        (Fehlschlaege, Aufträge pro Nacht, Aenderung ausserhalb des Projekts)
        - erst danach laeuft der Anbieter-Aufruf selbst in
        core.leitstand.EntscheidungsFaden, damit ein langsamer oder
        haengender Netzaufruf das Fenster nie blockiert."""
        try:
            if not leitstand.aktiv():
                return
            plan_pfad = self.projekt.pfad / "wissen" / "nachtplan.md"
            if not plan_pfad.is_file():
                return
            plan_mtime = plan_pfad.stat().st_mtime
            zustand = leitstand.zustand_lesen()
            if leitstand.ist_angehalten(zustand, self.projekt.name, plan_mtime):
                return
            leitstand.verlauf_anhaengen(zustand, self.projekt.name, block_nummer, satz)
            if bilanz.get("abgebrochen"):
                self._leitstand_anhalten(zustand, plan_mtime,
                                          "Von Hand abgebrochen (Not-Aus).")
                return
            aussen = leitstand.aenderung_ausserhalb(
                self.projekt.pfad, bilanz.get("geaendert", []))
            if aussen:
                self._leitstand_anhalten(
                    zustand, plan_mtime,
                    f"Auftrag hat außerhalb des Projektordners geändert ({aussen}).")
                return
            if bilanz.get("fehler"):
                zustand.fehlschlaege_in_folge += 1
            else:
                zustand.fehlschlaege_in_folge = 0
            if zustand.fehlschlaege_in_folge >= leitstand.MAX_FEHLSCHLAEGE_IN_FOLGE:
                self._leitstand_anhalten(
                    zustand, plan_mtime,
                    f"{zustand.fehlschlaege_in_folge} Fehlschläge hintereinander.")
                return
            if zustand.anzahl_auftraege >= leitstand.max_auftraege_pro_nacht():
                self._leitstand_anhalten(
                    zustand, plan_mtime,
                    f"Höchstzahl von {leitstand.max_auftraege_pro_nacht()} "
                    "Aufträgen pro Nacht erreicht.")
                return
            aufloesung = leitstand.wirksamer_anbieter()
            if aufloesung.zurueckgefallen:
                self.sprecher.sprich("Kein Anthropic-Schlüssel hinterlegt.", art="fehler")
            if aufloesung.api_schluessel is None:
                self.sprecher.sprich("Kein Gemini-Schlüssel hinterlegt.", art="fehler")
                self._leitstand_anhalten(zustand, plan_mtime,
                                          "Kein Gemini-Schlüssel hinterlegt.")
                return
            try:
                plan_text = plan_pfad.read_text(encoding="utf-8")
            except OSError as fehler:
                log.error("Leitstand: nachtplan.md nicht lesbar: %s", fehler)
                self._leitstand_anhalten(zustand, plan_mtime, "nachtplan.md nicht lesbar.")
                return
            offen_pfad = self.projekt.pfad / "wissen" / "offen.md"
            try:
                offen_text = offen_pfad.read_text(encoding="utf-8") if offen_pfad.is_file() \
                    else ""
            except OSError:
                offen_text = ""
            leitstand.zustand_schreiben(zustand)
            self._leitstand_plan_mtime = plan_mtime
            self.leitstand_faden = leitstand.EntscheidungsFaden(
                aufloesung.anbieter, aufloesung.api_schluessel, plan_text, offen_text,
                self._letzter_bericht or satz, leitstand.zeitlimit_sekunden(), self)
            self.leitstand_faden.fertig.connect(self._leitstand_entschieden)
            self.leitstand_faden.start()
            log.info("Leitstand: %s-Anfrage gestartet (Projekt %s)",
                      aufloesung.anbieter, self.projekt.name)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Leitstand: Nachbearbeitung fehlgeschlagen: %s", fehler)

    @slot_geschuetzt
    def _leitstand_entschieden(self, ergebnis: dict) -> None:
        """Kommt von core.leitstand.EntscheidungsFaden. `self._leitstand_plan_mtime`
        wurde direkt vor dem Start des Fadens gesetzt (`_leitstand_nach_auftrag`)
        und gehoert zu genau dieser Anfrage."""
        plan_mtime = self._leitstand_plan_mtime
        if plan_mtime is None:
            return
        zustand = leitstand.zustand_lesen()
        if not ergebnis.get("ok"):
            self._leitstand_anhalten(
                zustand, plan_mtime, f"Anfrage gescheitert ({ergebnis.get('text', '')}).")
            return
        benutzter_anbieter = ergebnis.get("anbieter", leitstand.ANBIETER_GEMINI)
        leitstand.nutzung_erfassen(
            zustand, benutzter_anbieter,
            ergebnis.get("eingabe_token", 0), ergebnis.get("ausgabe_token", 0))
        entscheidung = ergebnis["entscheidung"]
        schritt = ergebnis.get("schritt")
        auftrag_text = ergebnis.get("auftrag", "")
        grund = ergebnis.get("grund", "")
        if entscheidung == "stopp":
            self._leitstand_anhalten(zustand, plan_mtime, grund or "Stopp.")
            return
        verboten = leitstand.markierung_verboten(auftrag_text)
        if verboten:
            self._leitstand_anhalten(
                zustand, plan_mtime,
                f"{leitstand.anbieter_anzeigename(benutzter_anbieter)} schlug eine "
                f"gesperrte Markierung vor ({verboten}).")
            return
        if entscheidung == "wiederholen":
            anzahl = leitstand.wiederholung_erhoehen(zustand, self.projekt.name, schritt)
            if anzahl > leitstand.max_wiederholungen_je_schritt():
                self._leitstand_anhalten(
                    zustand, plan_mtime, f"Schritt {schritt} zu oft wiederholt ({anzahl}).")
                return
            # Block 77, Punkt 2: "der Leitstand entscheidet wiederholen"
            # zaehlt wie ein Fehlschlag des Eingang-Auftrags fuer die
            # Modell-Hochstufung - der naechste von _fertig abgelegte Block
            # laeuft wieder ueber eingang_datei und liest den Zaehler.
            self._fehlschlaege_eingang_folge += 1
        zustand.anzahl_auftraege += 1
        leitstand.zustand_schreiben(zustand)
        nummer = naechste_block_nummer(self.projekt.name)
        block = leitstand.codeblock_bauen(self.projekt.name, nummer, auftrag_text)
        ablegen(leitstand.QUELLE_LEITSTAND, block, projekt=self.projekt.name)
        log.info("Leitstand: nächster Auftrag abgelegt (Projekt %s, Schritt %s, Block %d)",
                  self.projekt.name, schritt, nummer)

    def _leitstand_anhalten(self, zustand: "leitstand.Zustand", plan_mtime: float,
                             grund: str) -> None:
        """Haelt Leitstand fuer das aktuelle Projekt an: merkt den Zeitstempel
        des Plans (eine neue nachtplan.md hebt das wieder auf), schreibt
        wissen/nachtbericht.md aus dem bisherigen Verlauf und laedt ihn bei
        aktiver Brücke hoch."""
        leitstand.anhalten_merken(zustand, self.projekt.name, plan_mtime)
        verlauf = leitstand.verlauf_abholen(zustand, self.projekt.name)
        leitstand.verlauf_leeren(zustand, self.projekt.name)
        leitstand.zustand_schreiben(zustand)
        text = leitstand.nachtbericht_bauen(self.projekt.name, verlauf, grund, zustand.nutzung)
        try:
            (self.projekt.pfad / "wissen").mkdir(parents=True, exist_ok=True)
            (self.projekt.pfad / "wissen" / "nachtbericht.md").write_text(
                text, encoding="utf-8")
        except OSError as fehler:
            log.error("Leitstand: nachtbericht.md nicht schreibbar: %s", fehler)
        if bool(einstellungen_lesen().get("bruecke_aktiv", True)):
            faden = NachtberichtFaden(self.projekt.name, text, self)
            faden.fertig_da.connect(functools.partial(self._leitstand_nachtbericht_fertig, faden))
            self._nachtberichte.append(faden)
            faden.start()
        log.warning("Leitstand angehalten (Projekt %s): %s", self.projekt.name, grund)
        self.sprecher.sprich(f"Leitstand angehalten: {kurzfassen(grund)}", art="fehler")

    @slot_geschuetzt
    def _leitstand_nachtbericht_fertig(self, faden, erfolg: bool) -> None:
        if faden in self._nachtberichte:
            self._nachtberichte.remove(faden)
        if not erfolg:
            log.info("Nachtbericht nicht hochgeladen (Netzfehler, bleibt stumm)")

    # -- Dublettensperre ------------------------------------------------------
    # Zehn Minuten - lang genug fuer ein verspaetetes zweites Einfuegen aus
    # der Zwischenablage, kurz genug, dass ein am naechsten Tag bewusst
    # wiederholter Auftrag nicht angemeckert wird.
    DUBLETTE_FENSTER_SEKUNDEN = 600

    def _text_glaetten(self, text: str) -> str:
        return " ".join(text.split())

    def _dublette_abgewiesen(self, art: str, text: str) -> bool:
        """Die einzige Dublettensperre im ganzen Programm - aber nur fuer
        Auftraege, die an Claude Code gehen (Art "code" oder ohne
        Markierung). Waechter, F7 und das normale Absenden ueber das
        Eingabefeld rufen sie deshalb nur fuer diese beiden Arten auf, bevor
        irgendetwas ausgefuehrt oder in die Warteschlange gelegt wird. Bei
        "run", "admin" und "bild" wird gar nicht erst hierher verzweigt:
        diese Befehle laufen immer sofort, auch wenn derselbe Text kurz
        zuvor schon kam - ein Bildschirmabzug ohne Inhalt ist zwangslaeufig
        jedes Mal derselbe Text und darf nie blockieren.

        Wahr, wenn `art`/`text` innerhalb von DUBLETTE_FENSTER_SEKUNDEN schon
        einmal angenommen wurden - dann wird "Läuft bereits." (etwas
        arbeitet noch) oder "Schon erledigt." (nichts arbeitet mehr)
        gemeldet, gesprochen und im Ausgabefeld gezeigt, und der Aufrufer
        muss abbrechen. Sonst merkt sich diese Methode den Auftrag sofort
        selbst mit und gibt Falsch zurueck.

        Leerzeichen und Zeilenumbrueche werden vor dem Vergleich geglaettet,
        damit ein aus der Zwischenablage neu eingefuegter, inhaltlich
        identischer Text trotzdem erkannt wird. Nur wenn weder eine Art noch
        ein Text vorliegt, gibt es nichts zu vergleichen.

        Der Schalter "dubletten_pruefung" (Einstellungen, Verhalten) schaltet
        die ganze Sperre ab - fehlt er in einstellungen.json, gilt aus.

        Zusaetzlich zur Zehn-Minuten-Regel (die unveraendert bleibt) wird
        ohne jedes Zeitfenster auch gegen den Text des gerade laufenden
        Auftrags und gegen alle in der Warteschlange wartenden Auftraege
        verglichen: laeuft ein Auftrag laenger als zehn Minuten oder wartet
        er entsprechend lange in der Warteschlange, faellt er sonst aus dem
        Fenster der `_auftragsverlauf`-Pruefung und ein doppelt
        abgeschickter Text wuerde trotzdem angehaengt und ein zweites Mal
        abgearbeitet."""
        if not einstellungen_lesen().get("dubletten_pruefung", False):
            return False
        geglaettet = self._text_glaetten(text)
        if not art and not geglaettet:
            return False

        if geglaettet and self._code_laeuft() and self.letzter_auftrag and (
                self._text_glaetten(self.letzter_auftrag) == geglaettet):
            self._dublette_melden("Läuft bereits.", art, "laufender Auftrag")
            return True
        if geglaettet:
            for eintrag in self._warteschlange:
                wartender_text = eintrag[0]
                if self._text_glaetten(wartender_text) == geglaettet:
                    self._dublette_melden("Wartet schon.", art, "Warteschlange")
                    return True

        schluessel = (art, geglaettet)
        jetzt = datetime.now()
        for alte_art, alter_text, zeitpunkt in reversed(self._auftragsverlauf):
            if (alte_art, alter_text) == schluessel:
                if (jetzt - zeitpunkt).total_seconds() <= self.DUBLETTE_FENSTER_SEKUNDEN:
                    satz = "Läuft bereits." if self._auftrag_laeuft else "Schon erledigt."
                    self._dublette_melden(satz, art, "Verlauf")
                    return True
                break
        self._auftragsverlauf.append((art, geglaettet, jetzt))
        return False

    def _dublette_melden(self, satz: str, art: str, quelle: str) -> None:
        log.info("Dublette abgewiesen (%s, %s): %s", quelle, art or "ohne Markierung", satz)
        self._verlauf_anhaengen(satz, "hinweis")
        self._status_zeigen(satz)
        self.sprecher.sprich(satz, art="fehler")

    # -- Blocknummern ---------------------------------------------------------

    def _modell_zeile_verarbeiten(self, art: str, inhalt: str) -> tuple[str, str | None, str]:
        """Block 649/662: erkennt/entfernt die Zeile '#MODELL# name' direkt
        nach der Markierung (oder ganz ohne Markierung, siehe unten), fuer
        alle vier Wege (Waechter, F7, Eingabefeld, Eingangsordner) - vor
        `_block_verarbeiten` aufgerufen, damit eine darauf folgende
        "Block N"-Zeile (core/bloecke.py) trotzdem als erste Zeile erkannt
        wird.

        Rueckgabe: (Inhalt ohne die Zeile, CLI-Wert fuer einen Wechsel oder
        None, Hinweistext bei unbekanntem Namen, sonst leer).

        Ein Wechsel wird fuer '#CODE#' UND fuer einen Auftrag ganz ohne
        Markierung vorgeschlagen - beide gehen an Claude Code
        (markierung_erkennen: Art "" ist ein gewoehnlicher Auftrag, kein
        Sonderfall). Block 662, Ursache des Fehlschlags bei Bruecken-
        Auftraegen ohne "#CODE#": die fruehere Bedingung `if not art` gab den
        Text bei Art "" sofort unveraendert zurueck, die Zeile wurde nie
        erkannt. RUN und ADMIN laufen in CWB direkt im Terminal, BILD holt
        nur einen Screenshot - keines der drei ruft Claude Code auf, darum
        bleibt die Zeile dort nur entfernt (sie soll z.B. kein PowerShell-
        Kommando verfaelschen), ohne dass ein Wechsel versucht wird. Ist der
        aufgeloeste Name bereits das aktive Modell (`self.modell`), gilt das
        ebenfalls als kein Wechsel."""
        bereinigt, roh_name = modell_zeile_erkennen(inhalt)
        if roh_name is None:
            return bereinigt, None, ""
        if art not in ("", "code"):
            return bereinigt, None, ""
        aufgeloest = modellname_aufloesen(roh_name, self.modelle)
        if aufgeloest is None:
            hinweis = f"Modell '{roh_name}' unbekannt, aktives Modell beibehalten"
            log.warning(hinweis)
            return bereinigt, None, hinweis
        if aufgeloest == self.modell:
            return bereinigt, None, ""
        return bereinigt, aufgeloest, ""

    def _block_verarbeiten(self, art: str, inhalt: str,
                            bilder: list[Path] | None = None, *,
                            herkunft: str = "") -> tuple[str, bool, bool, int | None]:
        """Erkennt und entfernt eine Blocknummer am Anfang/Ende von `inhalt`
        (core/bloecke.py, Block 56) und sagt Annahme, Luecke oder
        Unvollstaendigkeit an. Wird fuer alle vier Wege (Waechter, F7,
        Eingabefeld, Eingangsordner) und alle vier Markierungen aufgerufen,
        jeweils bevor der Inhalt an Claude Code oder das Terminal geht.

        Rueckgabe: (bereinigter Inhalt, ausfuehren, schon_angesagt, nummer).
        `nummer` ist die erkannte Blocknummer (None ohne Blockzeile) - sie
        wandert bei einem #CODE#-Auftrag bis in den Bericht (_fertig).

        Ohne Blockzeile bleibt der Inhalt unveraendert, es wird nichts
        gesagt, `schon_angesagt` ist Falsch - der Aufrufer sagt wie bisher
        selbst "Auftrag erhalten." an.

        Fehlt die Zeile "Ende Block N" (bei #BILD# gibt es dafuer keine
        Pruefung), wird NICHT ausgefuehrt (`ausfuehren`=False), sondern als
        `self._pending_block` vorgemerkt - F5 fuehrt ihn aus, Escape
        verwirft ihn (siehe _f5, _escape).

        `herkunft` (z.B. "von Claude") haengt sich nur an die
        Annahme-Ansage - fuer Auftraege aus der Bruecke (core/bruecke.py,
        Vorhaben "Bruecke" Stufe B3, `_eingang_auftrag_geschuetzt`), sonst
        bleibt die Ansage wie bisher ohne Quellenangabe."""
        nummer, bereinigt, vollstaendig = block_erkennen(art, inhalt)
        if nummer is None:
            return inhalt, True, False, None
        luecke = block_zaehler_aktualisieren(self.projekt.name, nummer)
        if luecke:
            log.warning("Block-Luecke (Projekt %s, Block %d): %s",
                        self.projekt.name, nummer, luecke)
        if not vollstaendig:
            self._pending_block = {
                "art": art, "inhalt": bereinigt, "bilder": list(bilder or []),
                "nummer": nummer,
            }
            satz = f"Achtung, Block {nummer} ist unvollständig angekommen."
            if luecke:
                satz += f" {luecke}"
            log.warning("Block %d unvollstaendig angekommen (Art %s), vorgemerkt",
                        nummer, art or "code")
            self._verlauf_anhaengen(satz, "hinweis")
            self._status_zeigen(satz)
            self.sprecher.sprich(satz, art="fehler")
            return bereinigt, False, True, nummer
        mitte = f" {herkunft}" if herkunft else ""
        satz = f"Block {nummer}{mitte} erhalten."
        if luecke:
            satz += f" {luecke}"
        log.info("Block %d erkannt und angenommen (Art %s)", nummer, art or "code")
        self.sprecher.sprich(satz, art="auftrag")
        return bereinigt, True, True, nummer

    @slot_geschuetzt
    def _absenden(self, vorspann: str = "", *, art: str | None = None,
                  inhalt: str | None = None, block_angesagt: bool = False,
                  bruecke_nummer: int | None = None,
                  block_nummer: int | None = None,
                  projekt_vorgegeben: str = "",
                  eingang_datei: Path | None = None,
                  modell_sticky: str | None = None,
                  modell_hinweis: str = "") -> None:
        """`vorspann` ist der Anfang der Annahme-Ansage, wenn der Aufrufer
        schon einen eigenen Satz gebaut hat (Zwischenablage, Wächter,
        Vormerkung) - der Projekt-Hinweis haengt sich dann daran an, statt
        eine zweite Ansage kurz danach auszuloesen. Leer heisst: normaler
        Weg, die Ansage entsteht ganz in dieser Methode und in
        `_auftrag_starten`.

        `projekt_vorgegeben` kommt vom Eingangsordner (core/eingangsordner.py,
        `EingangsAuftrag.projekt`) - gesetzt, wenn die Datei ein Feld
        "projekt" trug und darueber schon VOR dem Beanspruchen gegen
        `passend_fuer_projekt()` geprueft wurde, also nur bei einem Fenster
        mit passendem offenem Projekt ankommt. Dann gilt diese Zuordnung ohne
        erneute Pruefung (Block 63): die Wort- und Dateiregel aus
        core/zuordnung.py wuerde sonst faelschlich auf eine "Projekt: X"-Zeile
        im Auftragstext selbst anspringen und ihn vormerken statt ausfuehren,
        obwohl die Zuordnung laengst feststeht.

        `art`/`inhalt` kommen vom Wächter und von F7 schon fertig zerlegt
        herein - beide haben die Dublettensperre (`_dublette_abgewiesen`)
        vorher selbst schon geprueft, deshalb wird hier nicht zweimal
        geprueft und nicht zweimal gemerkt. So bekommt derselbe Auftrag
        ueber jeden Weg dasselbe Paar aus Art und Text: fruehere Fassungen
        schrieben den markierungsfreien Text zurueck ins Eingabefeld und
        parsten ihn hier neu - dabei ging je nach Herkunft die Markierung
        verloren, und zwei Wege desselben Auftrags sahen fuer die
        Dublettensperre wie zwei verschiedene Auftraege aus. Bleiben beide
        Parameter leer, wird wie gewohnt aus dem Eingabefeld gelesen und
        dabei frisch auf Dubletten geprueft.

        `block_angesagt` kommt vom Aufrufer, wenn er `_block_verarbeiten`
        (core/bloecke.py, Block 56) schon selbst aufgerufen und dabei schon
        "Block N erhalten." gesagt hat - dann bleibt das spaetere generische
        "Auftrag erhalten." hier und in `_auftrag_starten` stumm. Ist `art`
        leer, ruft diese Methode `_block_verarbeiten` selbst auf.

        `modell_sticky`/`modell_hinweis` (Block 649) kommen vom Aufrufer,
        wenn er `_modell_zeile_verarbeiten` schon selbst aufgerufen hat -
        genau wie bei `block_angesagt` nur bei eigener Eingabe ins Feld
        (`art is None`) selbst ermittelt."""
        # Block 82: Kennung fuer "Läuft:"/"Wartet:" (core/fenster.py,
        # _laeuft_kennung/_wartet_kennungen) - VOR der Umdeutung von `art`
        # gleich unten berechnet, weil "art is None" nur in diesem Moment
        # noch zuverlaessig "eigene Eingabe ins Feld" bedeutet.
        if bruecke_nummer is not None:
            quelle = "Brücke"
        elif eingang_datei is not None:
            quelle = "Eingang"
        elif art is None:
            quelle = "Eingabe"
        else:
            quelle = "Zwischenablage"
        zeit = datetime.now()
        if art is None:
            roh = self.eingabe.toPlainText()
            art, text = markierung_erkennen(roh)
            text, modell_sticky, modell_hinweis = self._modell_zeile_verarbeiten(art, text)
            text, weiter, block_angesagt, block_nummer = self._block_verarbeiten(
                art, text, self.bilder)
            if not weiter:
                self.eingabe.clear()
                return
            if (text.strip() and not self._holt_vorgemerkten
                    and art not in ("run", "admin", "bild")
                    and self._dublette_abgewiesen(art, text)):
                self.eingabe.clear()
                return
        else:
            text = inhalt
            roh = f"{MARKIERUNG_CODE}\n{text}" if art == "code" else text

        if eingang_datei is None:
            # Bruecke und Eingangsordner schreiben ihr "angenommen" selbst
            # (core/bruecke.py, core/eingangsordner.py); hier nur die beiden
            # lokalen Wege.
            auftragsjournal.angenommen("eingabefeld" if quelle == "Eingabe" else "zwischenablage",
                                       block=block_nummer, art=art or "code")
        if art == "bild":
            # #BILD# braucht keinen Befehlstext: die Markierung allein loest
            # schon aus, direkt der Screenshot-Ausloeser, ohne Claude Code.
            self.eingabe.clear()
            self._bild_markierung(block_nummer=block_nummer, angenommen_vermerkt=True)
            return
        if art in ("run", "admin"):
            # #run# und #admin# laufen nie ueber Claude Code: kein
            # Modellaufruf, kein Tokenverbrauch, direkt im Terminal.
            self.eingabe.clear()
            self._terminal_markierung(art, text, block_nummer=block_nummer)
            return
        if not text:
            self.sprecher.sprich(
                "Nach der Markierung steht nichts." if art else "Nichts eingegeben.",
                art="fehler",
            )
            return

        # Block 77, Punkte 1 und 3: "Modell: …" und "Dringend: ja" gelten nur
        # fuer Auftraege, die tatsaechlich an Claude Code gehen (#RUN#/
        # #ADMIN#/#BILD# sind hier laengst per return verlassen, siehe oben).
        text, modell_wunsch, dringend = kopf_metadaten_entfernen(text)
        modell_grund: str | None = None
        # Punkt 2: Hochstufung nach Fehlschlaegen - nur fuer Auftraege aus
        # Eingang, Bruecke oder Leitstand (erkennbar an eingang_datei, siehe
        # core/eingangsordner.py) und nur ohne ausdruecklichen Modellwunsch,
        # der geht immer vor.
        if (modell_wunsch is None and eingang_datei is not None
                and self._fehlschlaege_eingang_folge >= HOCHSTUFUNG_AB_FEHLSCHLAEGEN
                and not _modell_ist_opus(self.modell)):
            modell_wunsch = "opus"
            modell_grund = (
                f"nach {self._fehlschlaege_eingang_folge} Fehlschlägen in Folge hochgestuft"
            )

        if not self._holt_vorgemerkten:
            # Zwei Regeln halten einen Auftrag hier auf: er nennt Dateien, die
            # es hier nicht gibt, wohl aber in einem anderen Projekt - oder er
            # nennt den Namen eines anderen Projekts aus der Projektliste. In
            # beiden Faellen wird er vorgemerkt und dort ausgefuehrt, sobald
            # das Projekt geoeffnet wird. Bei ausdruecklich vorgegebenem
            # Projekt (siehe Docstring) entfaellt das - sonst koennte eine
            # "Projekt: X"-Kopfzeile im eigenen Auftragstext ihn faelschlich
            # als fremd einstufen, obwohl er genau hier hingehoert.
            fremd = None if projekt_vorgegeben else (
                fremdes_projekt_erkennen(text, self.projekt)
                or genanntes_projekt(text, self.projekt)
            )
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
                # Gesprochen nur der Kern ohne Tastenhinweise - der volle
                # Wortlaut steht in Statuszeile und Ausgabefeld.
                self.sprecher.sprich(
                    f"Auftrag gehört vermutlich zu Projekt {fremd}, "
                    f"hier nicht ausgeführt.", art="fehler")
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

        if self._sparmodus_aktiv and not dringend:
            # Block 77, Punkt 3: Sparmodus bei knappem Wochenkontingent -
            # nur Auftraege mit "Dringend: ja" laufen, alle anderen sammeln
            # sich hier statt in self._warteschlange und werden erst
            # eingereiht, wenn die Warnung endet (siehe _sparmodus_setzen).
            self._sparmodus_wartend.append(
                (text, bilder, bruecke_nummer, block_nummer, eingang_datei,
                 modell_wunsch, modell_grund, quelle, zeit, modell_sticky, modell_hinweis))
            # Block 82: "Wartet: ..." zaehlt auch Sparmodus-Zurueckstellungen
            # mit - anders als die bestehende Kopfzeilen-Warteanzeige, die
            # bewusst nur self._warteschlange zeigt (siehe _warteschlange_zeigen).
            self._statusleiste_aktualisieren()
            satz = "Wochenkontingent knapp, Auftrag wartet, bis das nicht mehr gilt."
            if vorspann:
                satz = f"{vorspann} {satz}"
            log.info("Auftrag im Sparmodus zurueckgestellt: %s", text[:120])
            auftragsjournal.schreibe("in_warteschlange", "sparmodus",
                                     nummer=bruecke_nummer, block=block_nummer,
                                     art="code", ohne_kontext=True)
            self._verlauf_anhaengen(f"{satz} {text}", "hinweis")
            self._status_zeigen(satz)
            if block_angesagt:
                self.sprecher.sprich("Er wartet wegen des Sparmodus.", art="auftrag")
            else:
                self.sprecher.sprich(
                    "Auftrag erhalten, er wartet wegen des Sparmodus.", art="auftrag")
            return

        if not self._code_laeuft():
            # Kontingentsperre: nur wenn gerade nichts laeuft; sonst reiht der
            # Auftrag sich unten ein und das Tor sitzt in _naechsten_starten.
            eintrag = (text, bilder, bruecke_nummer, block_nummer, eingang_datei,
                       modell_wunsch, modell_grund, quelle, zeit, modell_sticky, modell_hinweis)
            urteil = self._kontingent_tor.pruefen(kontingentsperre.modell_von(eintrag))
            if urteil.aktion == kontingentsperre.HALTEN or self._warteschlange:
                # Auch bei offenem Tor hinten anstellen, solange noch gehaltene
                # Auftraege vor ihm warten - die Reihenfolge bleibt.
                if not kontingentsperre.schon_vorgemerkt(self._warteschlange, eingang_datei):
                    self._warteschlange.append(eintrag)
                    self._warteschlange_zeigen()
                    auftragsjournal.schreibe("in_warteschlange", "kontingent",
                                             nummer=bruecke_nummer, block=block_nummer,
                                             art="code", ohne_kontext=True)
                else:
                    log.info("Kontingentsperre: Auftrag steht schon in der Warteschlange: %s",
                             text[:120])
                self._naechsten_starten()
                return
            eintrag = kontingentsperre.eintrag_herabsetzen(eintrag, urteil)
            modell_wunsch, modell_sticky = eintrag[5], eintrag[9]
            self._kontingent_urteil_melden(urteil, bruecke_nummer, block_nummer, eingang_datei)

        if self._code_laeuft():
            # Es laeuft schon einer - oder die Sitzung wartet gerade auf ein
            # erschoepftes Kontingent (core/sitzung.py, auftrag(),
            # "kontingent"). Der neue geht nicht verloren und blockiert
            # nichts, sondern reiht sich ein und laeuft los, sobald der
            # vorherige fertig ist.
            self._warteschlange.append(
                (text, bilder, bruecke_nummer, block_nummer, eingang_datei,
                 modell_wunsch, modell_grund, quelle, zeit, modell_sticky, modell_hinweis))
            self._warteschlange_zeigen()
            satz = f"Auftrag vorgemerkt, Platz {platzwort(len(self._warteschlange) + 1)}."
            if vorspann:
                satz = f"{vorspann} {satz}"
            log.info("Auftrag in die Warteschlange auf Platz %d: %s",
                     len(self._warteschlange) + 1, text[:120])
            auftragsjournal.schreibe("in_warteschlange",
                                     f"platz={len(self._warteschlange) + 1}",
                                     nummer=bruecke_nummer, block=block_nummer,
                                     art="code", ohne_kontext=True)
            self._verlauf_anhaengen(f"{satz} {text}", "hinweis")
            self._status_zeigen(satz)
            # Auch ein wartender Auftrag wird einmal kurz bestaetigt, sonst
            # bliebe das Abschicken voellig ohne hoerbare Antwort. War schon
            # eine Blocknummer angesagt (_block_verarbeiten), wird die
            # Annahme nicht ein zweites Mal gesprochen, nur das Warten.
            if block_angesagt:
                self.sprecher.sprich("Er wartet noch.", art="auftrag")
            else:
                self.sprecher.sprich("Auftrag erhalten, er wartet noch.", art="auftrag")
            return

        self._auftrag_starten(text, bilder, vorspann=vorspann, block_angesagt=block_angesagt,
                               bruecke_nummer=bruecke_nummer, block_nummer=block_nummer,
                               eingang_datei=eingang_datei, modell_wunsch=modell_wunsch,
                               modell_grund=modell_grund, quelle=quelle, zeit=zeit,
                               modell_sticky=modell_sticky, modell_hinweis=modell_hinweis)

    def _auftrag_starten(self, text: str, bilder: list[Path], vorspann: str = "",
                          ansagen: bool = True, block_angesagt: bool = False,
                          bruecke_nummer: int | None = None,
                          block_nummer: int | None = None,
                          eingang_datei: Path | None = None,
                          modell_wunsch: str | None = None,
                          modell_grund: str | None = None,
                          quelle: str = "Eingabe",
                          zeit: datetime | None = None,
                          modell_sticky: str | None = None,
                          modell_hinweis: str = "") -> None:
        """Uebergibt genau einen Auftrag an den Arbeitsfaden und stellt die
        Anzeige darauf ein. Gerufen wird das von `_absenden` fuer den ersten
        Auftrag und von `_naechsten_starten` fuer jeden aus der Warteschlange.

        Gesprochen wird hier genau ein kurzer Satz: "Auftrag erhalten." Der
        `vorspann` und der Verbindungshinweis stehen nur noch im Ausgabefeld
        und in der Statuszeile - gesprochen wuerden sie sich mit der naechsten
        Ansage ueberlagern. `ansagen=False` schweigt hier ganz, weil
        `_naechsten_starten` den Auftrag aus der Warteschlange holt, dessen
        Annahme beim Abschicken schon bestaetigt wurde.

        `bruecke_nummer` ist nur bei einem #CODE#-Auftrag aus der Bruecke
        gesetzt (core/bruecke.py, Vorhaben "Bruecke" Stufe B3) - gemerkt, bis
        `_fertig()` den Bericht dorthin hochlaedt. `block_nummer` ist die
        Blocknummer (core/bloecke.py, "Block N", None ohne Nummer) - gemerkt,
        bis `_fertig()` sie in den Bericht schreibt.

        `modell_wunsch` (Block 77, Punkte 1/2) ist ein CLI-Kurzname ("opus",
        "sonnet", "haiku") - verbindet die Sitzung ueber den Arbeitsfaden fuer
        GENAU diesen Auftrag mit diesem Modell und direkt danach wieder mit
        der festen Voreinstellung (`self.modell`, seit Block 662 immer
        Sonnet): core/faden.py verarbeitet "modell"- und "auftrag"-Eintraege
        streng der Reihe nach, darum reicht es, Hin- und Rueckwechsel
        unmittelbar vor bzw. nach `auftrag_geben` einzureihen. `modell_grund`
        ist nur bei einer
        Hochstufung nach Fehlschlaegen gesetzt (Punkt 2) - dann bleibt die
        Ansage aus (der Nutzer ist in dieser Lage oft nicht am Platz), nur der
        Bericht bekommt den Vermerk; ohne Grund (ausdruecklicher Wunsch per
        "Modell: …"-Zeile) wird die Umstellung angesagt.

        `modell_sticky` (Block 649/662, "#MODELL# name" direkt nach der
        Markierung oder ganz ohne Markierung) wird GENAUSO wie `modell_wunsch`
        nur fuer diesen einen Auftrag gesetzt und danach zurueckgewechselt:
        `self.modell` ist seit Block 662 immer die feste Voreinstellung
        (core/modelle.py, VOREINSTELLUNG, Sonnet) und wird nirgends mehr
        dauerhaft veraendert - weder durch F12 (das Feld entfaellt) noch durch
        eine "#MODELL#"-Zeile. `modell_hinweis` (z.B. unbekannter Name) landet
        unveraendert im Bericht, ohne dass etwas unternommen wird."""
        self._auftrag_laeuft = True
        _journal_beginnt(self, "code", bruecke_nummer, block_nummer,
                              f"quelle={quelle} modell={modell_wunsch or modell_sticky or 'standard'}")
        self._bruecke_code_nummer = bruecke_nummer
        # Ein Bruecken-Bericht soll am Ende ins zuletzt aktive Chatfenster
        # (siehe _bruecke_bericht_einfuegen) - das Ziel wird jetzt gemerkt,
        # solange der Nutzer noch dort ist, nicht erst beim Auftragsende.
        self._code_ziel = None
        if bruecke_nummer is not None:
            self._code_ziel = (zielfenster.fenster_merken() if zielfenster.UNTER_WINDOWS
                               else einfueger.ziel_merken())
        self._aktueller_block_nummer = block_nummer
        self._eingang_code_datei = eingang_datei
        self._laufender_modell_wunsch = modell_wunsch
        self._laufender_modell_grund = modell_grund
        self._laufender_modell_hinweis = modell_hinweis
        # Block 82: Kennung fuer "Läuft: ..." - siehe Docstring von
        # self._laufender_block_nummer in __init__.
        self._laufender_block_nummer = block_nummer
        self._laufender_quelle = quelle
        self._laufender_zeit = zeit or datetime.now()
        self._statusleiste_aktualisieren()
        # Wie bei einem Terminalbefehl faengt jeder Auftrag mit einem leeren
        # Feld an - egal ob #code#, #run# oder #admin#, egal ob frisch
        # abgeschickt oder aus der Warteschlange geholt. Bliebe die alte
        # Ausgabe stehen, waere ueber die Sprachausgabe nicht zu
        # unterscheiden, was zum neuen Auftrag gehoert und was vom vorigen
        # uebrig ist.
        self._ausgabe_leeren("Auftrag an Claude Code")
        self._verlauf_anhaengen(text, "auftrag")
        self.letzter_auftrag = text
        self._aktuelle_bilder = list(bilder)
        self.letzter_verbrauch = {}
        # Die Statuszeile zeigt keine laufende Arbeit an, nur Ergebnisse.
        self._status_zeigen("")
        self._taetigkeit_zeigen("beginnt")
        self._auftrags_beginn = datetime.now()
        self.zeit_anzeige.setText("0 s")
        self._auftrags_uhr.start()
        self.balken.animation_starten()

        faden = getattr(self, "faden", None)
        # Block 77: ein Modellwunsch braucht den Arbeitsfaden, um die Sitzung
        # umzuschalten - ohne ihn (siehe "faden is None" unten) entfaellt er,
        # das ist der seltene Fall ganz am Anfang, bevor der erste Faden steht.
        einmal_modell = modell_wunsch if (faden is not None and modell_wunsch) else None
        if einmal_modell:
            lang, _kurz = anzeige_name(einmal_modell)
            if modell_grund:
                satz_modell = f"Modell {lang}, {modell_grund}"
            else:
                ziel = f"für Block {block_nummer}." if block_nummer is not None \
                    else "für diesen Auftrag."
                satz_modell = f"Modell {lang} {ziel}"
            # Die naechsten zwei Meldungen von _modell_verbunden (Hin- und
            # Rueckwechsel) bleiben stumm, siehe dort - die Ansage uebernimmt
            # hier direkt dieser eine Satz.
            self._modell_eigenauftrag_rest += 2
            faden.modell_setzen(einmal_modell)
            log.info("Einmaliger Modellwechsel fuer diesen Auftrag: %s (%s)",
                     einmal_modell, modell_grund or "ausdruecklicher Wunsch")
            if modell_grund:
                self._verlauf_anhaengen(satz_modell, "hinweis")
            else:
                self.sprecher.sprich(satz_modell, art="immer")
                self._verlauf_anhaengen(satz_modell, "hinweis")
        # Block 662: "#MODELL# name" direkt nach der Markierung oder ganz ohne
        # Markierung - wie `einmal_modell` oben NUR fuer diesen einen Auftrag,
        # mit Ruecksprung auf `self.modell` (Sonnet) danach, siehe Docstring.
        einmal_sticky = modell_sticky if (faden is not None and modell_sticky) else None
        if einmal_sticky:
            lang, kurz = anzeige_name(einmal_sticky)
            satz_sticky = f"Modell {kurz} für diesen Auftrag."
            # Wie bei einmal_modell: Hin- und Rueckwechsel bleiben stumm,
            # dieser Satz uebernimmt die Ansage.
            self._modell_eigenauftrag_rest += 2
            faden.modell_setzen(einmal_sticky)
            log.info("Modellwechsel fuer diesen Auftrag (#MODELL#-Zeile): %s", einmal_sticky)
            self.sprecher.sprich(satz_sticky, art="immer")
            self._verlauf_anhaengen(satz_sticky, "hinweis")
        if faden is None:
            # Der Arbeitsfaden steht noch nicht. Der Auftrag wird gemerkt und
            # in _wartende_absenden nachgereicht, sobald es ihn gibt.
            self._wartende_auftraege.append((text, bilder))
            self._taetigkeit_zeigen("wartet")
            log.info("Auftrag vorgemerkt, Arbeitsfaden fehlt noch: %s", text[:120])
            self._status_zeigen(
                f"{vorspann or 'Auftrag angenommen.'} Verbindung wird noch aufgebaut.")
            if ansagen and not block_angesagt:
                self.sprecher.sprich("Auftrag erhalten.", art="auftrag")
            return
        if faden.sitzung is None:
            self._taetigkeit_zeigen("verbindet")
            faden.auftrag_geben(text, bilder)
            if einmal_modell or einmal_sticky:
                faden.modell_setzen(self.modell)
            self._status_zeigen(
                f"{vorspann or 'Auftrag angenommen.'} Verbindung wird noch aufgebaut.")
            if ansagen and not block_angesagt:
                self.sprecher.sprich("Auftrag erhalten.", art="auftrag")
            return
        if ansagen and not block_angesagt:
            self.sprecher.sprich("Auftrag erhalten.", art="auftrag")
        faden.auftrag_geben(text, bilder)
        if einmal_modell or einmal_sticky:
            faden.modell_setzen(self.modell)

    def _warteschlange_zeigen(self) -> None:
        """Bringt die Zahl der wartenden Auftraege in die Kopfzeile."""
        try:
            self.ausgabekopf.warteschlange_zeigen(len(self._warteschlange))
        except Exception as fehler:  # noqa: BLE001
            log.exception("Warteschlange nicht angezeigt: %s", fehler)
        self._statusleiste_aktualisieren()

    # -- Block 82: Leiste "Läuft"/"Wartet" ueber dem Ausgabefeld -------------

    def _laeuft_kennung(self) -> str:
        """Kennung des GERADE LAUFENDEN Auftrags (CODE, RUN, ADMIN oder BILD)
        fuer "Läuft: ..." - "–", solange nichts laeuft. Eine Kontingent-Pause
        (self._kontingent_info) zaehlt als "läuft": der Auftrag ist nicht
        verloren, nur kurz angehalten (core/fenster.py, _kontingent_pause_behandeln)."""
        if self._kontingent_info is not None:
            info = self._kontingent_info
            return auftrags_kennung(
                info.get("block_nummer"), info.get("quelle") or "Eingabe",
                info.get("zeit") or datetime.now(),
            )
        if not self._laeuft():
            return "–"
        return auftrags_kennung(
            self._laufender_block_nummer, self._laufender_quelle or "Eingabe",
            self._laufender_zeit or datetime.now(),
        )

    def _wartet_kennungen(self) -> list[str]:
        """Kennungen aller wartenden Auftraege in Reihenfolge fuer
        "Wartet: ..." - aus drei Quellen, mit Beleg:

        1. self._warteschlange - CODE-Auftraege aus Eingabefeld, Zwischenablage
           (F7/Waechter), Eingangsordner oder Bruecke, aufgereiht in
           `_absenden`, sobald schon ein Auftrag laeuft (siehe dort).
        2. self._sparmodus_wartend - dieselben Quellen, aber vom Sparmodus
           zurueckgestellt (F12 -> Verhalten, siehe _absenden).
        3. core.eingangsordner.wartende_dateien() - #RUN#/#ADMIN#/#BILD#-
           Auftraege aus dem Eingangsordner, die wegen belegtem Terminal/
           Screenshot-Weg per AuftragSpaeter zurueckgestellt wurden (core/
           eingangsordner.py, `verarbeiten`/`zuruecklegen`) UND frisch
           angekommene, noch nicht beanspruchte Dateien - beide liegen
           ununterscheidbar direkt im Eingangsordner. Dateien fuer ein
           anderes als das hier offene Projekt bekommen den Projektnamen
           davor (core/grundlagen.py, auftrags_kennung)."""
        kennungen = []
        for eintrag in (*self._warteschlange, *self._sparmodus_wartend):
            _text, _bilder, _bruecke_nummer, block_nummer, _eingang_datei, \
                _modell_wunsch, _modell_grund, quelle, zeit, _modell_sticky, \
                _modell_hinweis = eintrag
            kennungen.append(auftrags_kennung(block_nummer, quelle, zeit))
        # Derselbe Block steht sonst als laufend UND wartend da (z.B. die
        # Eingangsdatei, solange sie noch nicht aus dem Ordner verschwunden ist).
        laeuft_jetzt = self._laeuft_kennung()
        if laeuft_jetzt != "–":
            kennungen = [k for k in kennungen if k != laeuft_jetzt]
        try:
            for pfad in wartende_dateien():
                try:
                    auftrag = auftrag_lesen(pfad, markierung_erkennen)
                except EingangsFehler:
                    continue
                block_nummer, _rest, _vollstaendig = block_erkennen(auftrag.art, auftrag.inhalt)
                zeit = datetime.fromtimestamp(pfad.stat().st_mtime)
                quelle = "Brücke" if auftrag.quelle == QUELLE_BRUECKE else "Eingang"
                projekt = auftrag.projekt if (
                    auftrag.projekt and not projekt_gleichwertig(auftrag.projekt, self.projekt.name)
                ) else None
                kennung = auftrags_kennung(block_nummer, quelle, zeit, projekt)
                if kennung != laeuft_jetzt:
                    kennungen.append(kennung)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Eingangsordner-Dateien nicht in 'Wartet' uebernommen: %s", fehler)
        return kennungen

    def _statusleiste_satz(self) -> str:
        """Der gesprochene Satz fuer F2 ('Wo stehen wir') - derselbe Inhalt
        wie die Leiste, nur als Satz."""
        wartet = self._wartet_kennungen()
        wartet_satz = ", ".join(wartet) if wartet else "keiner"
        return f"Läuft: {self._laeuft_kennung()}. Wartet: {wartet_satz}."

    def _statusleiste_aktualisieren(self) -> None:
        """Zeichnet die Leiste ueber dem Ausgabefeld neu - aufgerufen bei
        jeder Aenderung: Auftragsstart/-ende (CODE/RUN/ADMIN/BILD),
        Warteschlangen-Aenderung (_warteschlange_zeigen) und beim
        periodischen Blick des Eingangswaechters (_eingang_fremde_melden)."""
        try:
            self.laeuft_anzeige.setText(f"Läuft: {self._laeuft_kennung()}")
            wartet = self._wartet_kennungen()
            wartet_text = ", ".join(wartet) if wartet else "–"
            self.wartet_anzeige.setText(f"Wartet: {wartet_text}")
            satz = self._statusleiste_satz()
            self.laeuft_anzeige.setToolTip(satz)
            self.wartet_anzeige.setToolTip(satz)
            self.laeuft_anzeige.setAccessibleDescription(satz)
            self.wartet_anzeige.setAccessibleDescription(satz)
            warte_kachel = getattr(self, "_warte_kachel_zeigen", None)
            if warte_kachel is not None:
                warte_kachel(len(wartet))
        except Exception as fehler:  # noqa: BLE001
            log.exception("Statusleiste nicht aktualisiert: %s", fehler)

    def _kontingent_stufe_setzen(self, feld: QLabel, stufe: str) -> None:
        if str(feld.property("kontingentstufe") or "") != stufe:
            feld.setProperty("kontingentstufe", stufe)
            feld.style().unpolish(feld)
            feld.style().polish(feld)

    def _kontingent_zeigen(self, stufe: str, text: str, woche_anzeige: str,
                            sitzung_anzeige: str | None) -> None:
        """Zeichnet die beiden Kontingent-Felder in der Statusleiste neu -
        hierher aus core/kopfzeile.py verlegt (Block 36/37 -> 82). Gerufen von
        _kontingent_anzeige_aktualisieren() mit dem Ergebnis von
        Sitzung.kontingent_zustand(). Ohne bekannte Prozentzahl steht ein
        ruhiger Platzhalter ("Sitzung: –") statt einer erfundenen Zahl oder
        eines verborgenen Feldes - so springt die Leiste nicht, wenn die erste
        RateLimitEvent-Meldung eintrifft."""
        try:
            stufe = stufe or "normal"
            satz = text or "Woche: unter Warnschwelle."

            self.kontingent_anzeige.setText(woche_anzeige or "Woche: unter Warnschwelle")
            self.kontingent_anzeige.setToolTip(satz)
            self.kontingent_anzeige.setAccessibleDescription(satz)
            self._kontingent_stufe_setzen(self.kontingent_anzeige, stufe)

            self.kontingent_sitzung_anzeige.setText(sitzung_anzeige or "Sitzung: –")
            self.kontingent_sitzung_anzeige.setToolTip(satz)
            self.kontingent_sitzung_anzeige.setAccessibleDescription(satz)
            self._kontingent_stufe_setzen(
                self.kontingent_sitzung_anzeige, stufe if sitzung_anzeige else "normal"
            )
        except Exception as fehler:  # noqa: BLE001
            log.exception("Kontingent-Anzeige nicht gesetzt: %s", fehler)

    # -- Block 82 (Punkt 3): Platzhalter fuer den Waechter-Farbknopf ---------

    def _waechter_platzhalter_geometrie(self) -> dict | None:
        """Globale Bildschirmkoordinaten und Groesse des Platzhalters ganz
        links in der Statusleiste - die Grundlage, auf die sich der
        eigenstaendige Waechter-Prozess (core/waechter_anzeige.py) per
        Fenstergeometrie legt. None, solange dieses Fenster minimiert, nicht
        sichtbar oder der Platzhalter noch nicht ausgemessen ist (vor dem
        ersten Layout) - der Waechter blendet sich dann aus (ausser bei
        Haengt/Abgestuerzt, siehe dort)."""
        platzhalter = getattr(self, "waechter_platzhalter", None)
        if platzhalter is None or self.isMinimized() or not self.isVisible():
            return None
        if platzhalter.width() <= 0 or platzhalter.height() <= 0:
            return None
        ecke = platzhalter.mapToGlobal(QPoint(0, 0))
        return {
            "x": ecke.x(), "y": ecke.y(),
            "breite": platzhalter.width(), "hoehe": platzhalter.height(),
        }

    def _kontingent_urteil_melden(self, urteil, bruecke_nummer, block_nummer,
                                   eingang_datei) -> None:
        """Ein Start ist freigegeben: Hinweis (veraltet, herabgesetzt, von Hand
        freigegeben) in Verlauf und Protokoll, bei Ende der Sperre der Ton."""
        if self._kontingent_tor.zustand_melden(False) == "weiter":
            self._kontingent_sperre_uhr.stop()
            log.info("Kontingentsperre aufgehoben, gehaltene Aufträge laufen weiter")
            self.sprecher.ton("wartet")
        for nummer in self._kontingent_nummern(bruecke_nummer, eingang_datei):
            kontingentsperre.gehalten_loeschen(nummer)
        if urteil is not None and urteil.hinweis:
            log.info("Kontingentsperre: %s", urteil.hinweis)
            self._verlauf_anhaengen(urteil.hinweis, "hinweis")

    def _kontingent_nummern(self, bruecke_nummer, eingang_datei) -> list:
        nummern = [bruecke_nummer] if bruecke_nummer is not None else []
        if eingang_datei is not None:
            nummer = _orch_nummern_von(self).get(eingang_datei.name)
            if nummer is not None:
                nummern.append(nummer)
        return nummern

    def _kontingent_gehalten_zeigen(self, urteil) -> None:
        """Das Tor ist zu: Zustand, Statuszeile und Ton (nur beim Beginn),
        Anzeigevermerk fuer bericht_holen, Zeitgeber laeuft weiter."""
        if urteil is None:
            self._kontingent_sperre_uhr.stop()
            return
        text = f"wartet auf Kontingent bis {kontingentsperre.uhrzeit_text(urteil.bis)}"
        self._zustand_zeigen("wartet_kontingent")
        self._taetigkeit_zeigen(text)
        self._status_zeigen(text)
        for eintrag in self._warteschlange:
            for nummer in self._kontingent_nummern(eintrag[2], eintrag[4]):
                kontingentsperre.gehalten_vermerken(nummer, urteil.bis)
        if self._kontingent_tor.zustand_melden(True) == "beginn":
            log.warning("Kontingentsperre: %d Auftrag/Aufträge gehalten, %s",
                        len(self._warteschlange), text)
            self._verlauf_anhaengen(f"Kontingent knapp: {text}.", "hinweis")
            self.sprecher.ton("wartet")
        if not self._kontingent_sperre_uhr.isActive():
            self._kontingent_sperre_uhr.start()
        self._statusleiste_aktualisieren()

    @slot_geschuetzt
    def _kontingent_sperre_pruefen(self) -> None:
        """Zeitgeber (60 s): ist die Sperre gefallen, laeuft der naechste los.
        Ein laufender Auftrag wird nie angefasst; sein Ende ruft ohnehin
        _naechsten_starten."""
        if not self._warteschlange:
            self._kontingent_sperre_uhr.stop()
            self._kontingent_tor.zustand_melden(False)
            return
        if self._code_laeuft() or self.wechselt:
            return
        urteil = self._kontingent_tor.pruefen(
            kontingentsperre.modell_von(self._warteschlange[0]), verbrauchen=False)
        if urteil.aktion != kontingentsperre.HALTEN:
            self._naechsten_starten()
        else:
            self._kontingent_gehalten_zeigen(urteil)

    @slot_geschuetzt
    def _kontingent_freigeben(self) -> None:
        """Strg+Umschalt+K: die Sperre gilt fuer den naechsten Start nicht, einmal."""
        kontingentsperre.freigabe_geben()
        text = "Kontingentsperre einmal aufgehoben, der nächste Auftrag startet."
        log.info("Kontingentsperre per Taste einmal aufgehoben")
        self._verlauf_anhaengen(text, "hinweis")
        self._status_zeigen(text)
        if self._warteschlange and not self._code_laeuft():
            self._naechsten_starten()

    def _naechsten_starten(self) -> None:
        """Holt den naechsten Auftrag aus der Warteschlange, sobald der
        vorherige beendet ist. Ist sie leer, geschieht nichts. Waehrend eines
        Projektwechsels/Neustarts startet nichts mehr."""
        if self.wechselt:
            return
        self._warteschlange_zeigen()
        if not self._warteschlange:
            return
        eintrag, urteil = kontingentsperre.naechsten_holen(
            self._warteschlange, self._kontingent_tor)
        if eintrag is None:
            self._kontingent_gehalten_zeigen(urteil)
            return
        eintrag = kontingentsperre.eintrag_herabsetzen(eintrag, urteil)
        self._kontingent_urteil_melden(urteil, eintrag[2], eintrag[3], eintrag[4])
        text, bilder, bruecke_nummer, block_nummer, eingang_datei, modell_wunsch, \
            modell_grund, quelle, zeit, modell_sticky, modell_hinweis = eintrag
        self._warteschlange_zeigen()
        log.info("Nächster Auftrag aus der Warteschlange: %s", text[:120])
        rest = len(self._warteschlange)
        satz = "Nächster Auftrag aus der Warteschlange."
        if rest:
            satz += f" Danach warten noch {rest}." if rest > 1 else " Danach wartet noch einer."
        # Ohne Unterbrechen: der Ergebnissatz des vorherigen Auftrags darf
        # nicht abgeschnitten werden.
        self.sprecher.sprich(satz, unterbrechen=False, art="meldung")
        self._auftrag_starten(text, bilder, ansagen=False, bruecke_nummer=bruecke_nummer,
                               block_nummer=block_nummer, eingang_datei=eingang_datei,
                               modell_wunsch=modell_wunsch, modell_grund=modell_grund,
                               quelle=quelle, zeit=zeit,
                               modell_sticky=modell_sticky, modell_hinweis=modell_hinweis)

    @slot_geschuetzt
    def _warteschlange_leeren(self) -> None:
        """F4: verwirft alle wartenden Auftraege. Der gerade laufende bleibt -
        den beendet der Not-Aus (F8)."""
        anzahl = len(self._warteschlange)
        for _text, _bilder, _bruecke_nummer, _block_nummer, eingang_datei, _modell_wunsch, \
                _modell_grund, _quelle, _zeit, _modell_sticky, _modell_hinweis \
                in self._warteschlange:
            if eingang_datei is not None:
                verwerfen(eingang_datei, "Warteschlange geleert")
        self._warteschlange.clear()
        self._kontingent_sperre_uhr.stop()
        self._kontingent_tor.zustand_melden(False)
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

    def _warteliste_sammeln(self) -> list:
        """Die Posten der Warteschlangenliste: der laufende Auftrag zuerst
        (nicht loeschbar), dann Warteschlange, Sparmodus-Rueckstellung und
        die im Eingangsordner liegen gebliebenen Dateien (#RUN#/#ADMIN#/#BILD#)."""
        posten = []
        if self._laeuft():
            art = self._laeuft_art().lower()
            nummer = (self._bruecke_code_nummer if art == "code" else
                      self._terminal_bruecke_nummer if art in ("run", "admin") else
                      self._bild_bruecke_nummer if art == "bild" else None)
            posten.append(warteliste.Posten(
                quelle=warteliste.QUELLE_LAUFEND, projekt=self.projekt.name,
                art=art or "code", nummer=nummer, block=self._laufender_block_nummer,
                kennung=self._laeuft_kennung()))
        for quelle, liste in ((warteliste.QUELLE_SCHLANGE, self._warteschlange),
                              (warteliste.QUELLE_SPARMODUS, self._sparmodus_wartend)):
            for eintrag in liste:
                _text, _bilder, bruecke_nummer, block_nummer, eingang_datei, \
                    _wunsch, _grund, eintrag_quelle, zeit, _sticky, _hinweis = eintrag
                posten.append(warteliste.Posten(
                    quelle=quelle, projekt=self.projekt.name, art="code",
                    nummer=bruecke_nummer, block=block_nummer,
                    kennung=auftrags_kennung(block_nummer, eintrag_quelle, zeit),
                    datei=eingang_datei, ref=eintrag))
        bekannt = {p.datei for p in posten if p.datei is not None}
        try:
            for pfad in wartende_dateien():
                if pfad in bekannt:
                    continue
                try:
                    auftrag = auftrag_lesen(pfad, markierung_erkennen)
                except EingangsFehler:
                    continue
                block_nummer, _rest, _vollstaendig = block_erkennen(auftrag.art, auftrag.inhalt)
                zeit = datetime.fromtimestamp(pfad.stat().st_mtime)
                posten.append(warteliste.Posten(
                    quelle=warteliste.QUELLE_EINGANG,
                    projekt=auftrag.projekt or self.projekt.name,
                    art=auftrag.art or "code", nummer=auftrag.auftrag_nummer,
                    block=block_nummer, kennung=auftrags_kennung(block_nummer, "Eingang", zeit),
                    datei=pfad))
        except Exception as fehler:  # noqa: BLE001
            log.exception("Eingangsdateien nicht in die Warteliste uebernommen: %s", fehler)
        return warteliste.nummerieren(posten)

    def _warteliste_loeschen(self, posten) -> str:
        """Nimmt einen wartenden Auftrag heraus (Datei nach verworfen/, Zeile
        im Journal) und liefert die Ansage danach."""
        try:
            if posten.quelle == warteliste.QUELLE_SCHLANGE:
                liste = self._warteschlange
            elif posten.quelle == warteliste.QUELLE_SPARMODUS:
                liste = self._sparmodus_wartend
            else:
                liste = None
            if liste is not None:
                for index, eintrag in enumerate(liste):
                    if eintrag is posten.ref:
                        del liste[index]
                        break
                else:
                    return "Dieser Auftrag wartet nicht mehr."
            warteliste.verwerfen_datei(posten)
            self._warteschlange_zeigen()
            satz = f"{warteliste.kurzname(posten)} gelöscht, nach verworfen verschoben."
            self._verlauf_anhaengen(satz, "hinweis")
            self._status_zeigen(satz)
            return satz
        except Exception as fehler:  # noqa: BLE001
            log.exception("Wartender Auftrag nicht geloescht: %s", fehler)
            return "Löschen fehlgeschlagen."

    def _warteliste_fragen(self, frage: str) -> bool:
        try:
            self.sprecher.sprich(frage, art="frage")
            antwort = QMessageBox.question(
                self, "CWB", frage, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            return antwort == QMessageBox.Yes
        except Exception as fehler:  # noqa: BLE001
            log.exception("Rueckfrage zum Loeschen fehlgeschlagen: %s", fehler)
            return False

    def _warte_kachel_zeigen(self, zahl: int) -> None:
        """Kachel "Warteschlange" mit der Zahl; ausgeblendet, wenn nichts wartet."""
        try:
            if zahl > 0:
                self.kacheln.kachel_beschriften(
                    WARTE_KENNUNG, f"Warteschlange ({zahl})",
                    f"Warteschlange öffnen, {zahl} warten", WARTE_SYMBOL)
            self.kacheln.kachel_zeigen(WARTE_KENNUNG, zahl > 0)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Warteschlangen-Kachel nicht umgeschaltet: %s", fehler)

    @slot_geschuetzt
    def _warteschlange_verwalten(self) -> None:
        """Umschalt+F4 / Kachel "Warteschlange": oeffnet die Liste aller
        wartenden Auftraege (laufender zuerst), aus der einzelne geloescht
        werden koennen - anders als F4, das alle verwirft."""
        if not self._warteliste_sammeln():
            satz = "Keine wartenden Aufträge."
            self._status_zeigen(satz)
            self.sprecher.sprich(satz, art="fehler")
            return
        dialog = WarteschlangenFenster(
            self._warteliste_sammeln, self._warteliste_loeschen, self._warteliste_fragen,
            lambda satz: self.sprecher.sprich(satz, art="immer"), self)
        dialog.exec()
        self._warteschlange_zeigen()

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
        """F5 hat drei Bedeutungen, je nach Lage: liegt ein unvollstaendig
        angekommener Block vor (core/bloecke.py), fuehrt F5 ihn trotzdem
        aus. Sonst, haelt die Projektwarnung gerade einen Auftrag zurueck,
        fuehrt F5 ihn hier aus. Sonst springt sie wie gewohnt ins
        Eingabefeld."""
        if self._pending_block is not None:
            self._block_trotzdem_ausfuehren()
            return
        if vormerkung_offen():
            self._trotzdem_hier()
            return
        self._springe(self.eingabe, "Eingabefeld")

    @slot_geschuetzt
    def _block_trotzdem_ausfuehren(self) -> None:
        """F5 bei einem unvollstaendig angekommenen Block: er laeuft doch,
        obwohl die Zeile "Ende Block N" fehlte."""
        info, self._pending_block = self._pending_block, None
        if info is None:
            return
        satz = f"Block {info['nummer']} läuft trotzdem."
        log.info("Unvollstaendiger Block %d wird trotzdem ausgefuehrt (Art %s)",
                 info["nummer"], info["art"] or "code")
        self._verlauf_anhaengen(satz, "hinweis")
        self._status_zeigen(satz)
        self.sprecher.sprich(satz, art="auftrag")
        art, inhalt = info["art"], info["inhalt"]
        if art == "bild":
            self._bild_markierung(block_nummer=info["nummer"])
        elif art in ("run", "admin"):
            self._terminal_markierung(art, inhalt, block_nummer=info["nummer"])
        else:
            self.bilder = list(info["bilder"])
            self._absenden(vorspann="Auftrag angenommen.", art=art, inhalt=inhalt,
                            block_angesagt=True)

    @slot_geschuetzt
    def _block_verwerfen(self) -> None:
        """Escape bei einem unvollstaendig angekommenen Block: verwerfen,
        statt ihn auszufuehren."""
        info, self._pending_block = self._pending_block, None
        if info is None:
            return
        satz = f"Block {info['nummer']} verworfen."
        log.info("Unvollstaendiger Block %d verworfen (Art %s)",
                 info["nummer"], info["art"] or "code")
        self._verlauf_anhaengen(satz, "hinweis")
        self._status_zeigen(satz)
        self.sprecher.sprich(satz, art="hinweis")

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
        allein los, was niemand erwartet, der eben alles gestoppt hat.
        Schaltet zusaetzlich die Bruecke aus, falls sie an war
        (wissen/plan_bruecke.md, Stufe B3). Bricht ausserdem einen laufenden
        #run#/#admin#-Terminalbefehl hart ab (Block 106) - frueher rief diese
        Methode nur self.faden.not_aus() (die Claude-Code-Sitzung), ein
        haengender Terminalbefehl lief dabei unbeeinflusst weiter."""
        if _orch_im_vordergrund(self):
            # F8 gilt nur der Sitzung, die gerade vorn ist: hier der
            # Orchestrator. Claude Code, Terminal und Warteschlange bleiben.
            auftragsjournal.schreibe("abgebrochen", "grund=Not-Aus F8 (Orchestrator)")
            _orch_stopp(self)
            self.sprecher.sprich("Orchestrator gestoppt.")
            return
        auftragsjournal.schreibe("abgebrochen", "grund=Not-Aus F8")
        if self._terminal_faden is not None and self._terminal_faden.isRunning():
            self._terminal_faden.not_aus()
            log.info("Not-Aus: laufender Terminalbefehl abgebrochen")
        verworfen = len(self._warteschlange)
        for _text, _bilder, _bruecke_nummer, _block_nummer, eingang_datei, _modell_wunsch, \
                _modell_grund, _quelle, _zeit, _modell_sticky, _modell_hinweis \
                in self._warteschlange:
            if eingang_datei is not None:
                verwerfen(eingang_datei, "Not-Aus")
        self._warteschlange.clear()
        self._warteschlange_zeigen()
        kontingent_verworfen = self._kontingent_info is not None
        if kontingent_verworfen and self._kontingent_info.get("eingang_datei") is not None:
            verwerfen(self._kontingent_info["eingang_datei"], "Not-Aus")
        self._kontingent_uhr.stop()
        self._kontingent_info = None
        teile = []
        if verworfen == 1:
            teile.append("Ein wartender Auftrag verworfen.")
        elif verworfen > 1:
            teile.append(f"{verworfen} wartende Aufträge verworfen.")
        if kontingent_verworfen:
            teile.append("Kontingent-Pause beendet, wartender Auftrag verworfen.")
        pause = self._notaus_pause_beginnen().strip()
        if pause:
            teile.append(pause)
        zusatz = " ".join(teile)
        log.info("Not-Aus, wartende Auftraege verworfen: %d", verworfen)
        # Art "hinweis": ohne Art galt der Satz als "beruehrt" und blieb
        # stumm (ERLAUBTE_ARTEN). Laeuft ein Auftrag, sagt _fertig gleich
        # "Abgebrochen." (mit Unterbrechen) und wuerde diesen Satz abschneiden:
        # dann entfaellt "Not-Aus." und _fertig haengt den Zusatz an.
        if getattr(self, "_auftrag_laeuft", False):
            self._notaus_nachsatz = zusatz
        else:
            self._notaus_nachsatz = ""
            self.sprecher.sprich(("Not-Aus. " + zusatz).strip(), art="hinweis")
        self.faden.not_aus()

    def _notaus_pause_beginnen(self) -> str:
        """Pausiert Bruecke und Leitstand fuer die eingestellte Zeit (nur im
        Speicher, die Schalter in einstellungen.json bleiben unberuehrt).
        Gibt den Zusatz fuer die Ansage zurueck, bei Dauer 0 oder wenn beide
        ohnehin aus sind: leer."""
        dauer = notaus_pause.minuten()
        bruecke_an = bool(einstellungen_lesen().get("bruecke_aktiv", True))
        leitstand_an = leitstand.aktiv()
        self._notaus_uhr.stop()
        notaus_pause.beenden()
        ende = notaus_pause.starten(bruecke_an, leitstand_an, dauer)
        if ende is None:
            log.info("Not-Aus: keine Pause (Dauer %d, Brücke=%s, Leitstand=%s)",
                     dauer, bruecke_an, leitstand_an)
            return ""
        self._notaus_uhr.start(max(1, int(dauer * 60_000)))
        self._bruecke_zustand_anwenden()
        self._leitstand_zustand_anwenden()
        uhrzeit = ende.strftime("%H:%M")
        was = "Brücke" if bruecke_an else "Leitstand"
        if bruecke_an:
            self._status_zeigen(f"Brücke pausiert bis {uhrzeit}")
        else:
            self._status_zeigen(f"Leitstand pausiert bis {uhrzeit}")
        auftragsjournal.schreibe(
            "notaus_pause", f"{was} pausiert {dauer} Min bis {uhrzeit}"
            + (", Leitstand ebenso" if bruecke_an and leitstand_an else ""))
        log.info("Not-Aus: %s pausiert bis %s", was, uhrzeit)
        zahl = {1: "eine", 2: "zwei", 3: "drei", 4: "vier", 5: "fünf", 6: "sechs",
                7: "sieben", 8: "acht", 9: "neun", 10: "zehn"}.get(dauer, str(dauer))
        einheit = "Minute" if dauer == 1 else "Minuten"
        return f" {was} pausiert {zahl} {einheit}."

    def _notaus_pause_abbrechen(self) -> None:
        """Beendet eine laufende Not-Aus-Pause still (Nutzer schaltet selbst)."""
        self._notaus_uhr.stop()
        notaus_pause.beenden()

    def _abbruch_rueckfall_planen(self) -> None:
        """Ohne Not-Aus-Pause faellt der graue Balken nach kurzer Zeit zurueck;
        mit Pause tut das erst deren Ende (`_notaus_pause_ende`)."""
        if not notaus_pause.aktiv():
            self._abbruch_uhr.start(ABBRUCH_RUECKFALL_MS)

    @slot_geschuetzt
    def _abbruch_ruhe(self) -> None:
        """Setzt den grauen Balken "abgebrochen" auf den Ruhezustand "bereit"
        zurueck, aber nur wenn nichts laeuft und er noch grau steht; jeder
        andere Zustand (laeuft, fertig, Fehler) bleibt unberuehrt."""
        if self._letzter_zustand != "abgebrochen" or self._laeuft():
            return
        self._zustand_zeigen("bereit")
        self._taetigkeit_zeigen("")
        log.info("Balken von abgebrochen auf bereit zurueckgefallen")

    @slot_geschuetzt
    def _notaus_pause_ende(self) -> None:
        """Zeit um: Bruecke und Leitstand laufen wieder, soweit ihre Schalter
        an sind. Nur Statusmeldung, Verlauf und Abschlusston, kein Satz."""
        if not notaus_pause.abgelaufen():
            return
        war_bruecke = notaus_pause.bruecke_eingetragen()
        notaus_pause.beenden()
        self._bruecke_zustand_anwenden()
        self._leitstand_zustand_anwenden()
        self._abbruch_ruhe()
        if war_bruecke and bool(einstellungen_lesen().get("bruecke_aktiv", True)):
            text = "Brücke ist wieder an"
        else:
            text = "Leitstand ist wieder an"
        self._status_zeigen(text)
        self._verlauf_anhaengen(text, "hinweis")
        self.sprecher.ton("fertig")
        self.sprecher.sprich(text + ".", unterbrechen=False, art="hinweis")
        auftragsjournal.schreibe("notaus_pause", "Pause beendet")
        log.info("Not-Aus-Pause abgelaufen: %s", text)

    def _zuruecknehmen(self) -> None:
        if not self.faden.sitzung:
            return
        urteil = self.faden.sitzung.rueckgaengig()
        self._status_zeigen(urteil.ansage())
        self.sprecher.sprich(urteil.ansage())

    def _bild_waehlen(self) -> None:
        if self._orch_sichtbar():
            self._orch_ansicht.bild_waehlen()
            return
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
        """Faden sauber beenden, Projektwahl öffnen, dieses Fenster schließen.
        Laeuft noch ein Auftrag, wird nicht still gewechselt (`_laeuft_beenden`)."""
        if not self._laeuft_beenden("das Projekt wechseln"):
            return
        self.wechselt = True
        if self in OFFENE_FENSTER:
            OFFENE_FENSTER.remove(self)
        auftragsjournal.schreibe("projektwechsel", f"von={self.projekt.name} per=F9",
                                 ohne_kontext=True)
        self.sprecher.sprich("Projekt wechseln.")
        _orch_beenden(self)
        try:
            self.faden.beenden()
            self.faden.wait(5000)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Faden beim Projektwechsel nicht beendet: %s", fehler)
        self.start_fenster = Start(self.sprecher, Werkbank, automatisch=False)
        self.start_fenster.resize(*darstellung.FENSTER_START)
        self.start_fenster.show()
        self.close()

    def _neustart(self) -> None:
        """Beendet den laufenden Python-Prozess und startet ihn neu - wie ein
        Neuladen einer Seite. Anders als der Projektwechsel (F9) verwirft das
        auch jeden internen Zustand, der nicht in Dateien gesichert ist."""
        # Laeuft nur der Orchestrator (oder wartet ein von ihm vergebener
        # Auftrag), fragt _laeuft_beenden nicht - darum hier ja/nein. Laeuft
        # Claude Code, fragt _laeuft_beenden schon, nicht doppelt.
        if (_orch_beschaeftigt(self) and not self._arbeit_laeuft()
                and not self._abbruch_bestaetigen(
                    "Der Orchestrator oder ein von ihm vergebener Auftrag läuft noch. "
                    "Trotzdem neu starten?")):
            log.info("Neustart abgelehnt: Orchestrator laeuft noch")
            return
        if not self._laeuft_beenden("neu starten"):
            return
        self.sprecher.sprich("Kompletter Neustart.")
        self.wechselt = True
        if self in OFFENE_FENSTER:
            OFFENE_FENSTER.remove(self)
        _orch_beenden(self)
        try:
            self.faden.beenden()
            self.faden.wait(5000)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Faden beim Neustart nicht beendet: %s", fehler)
        if os.environ.get(absturzschutz.ENV_AUFPASSER):
            # Der Aufpasser (core/aufpasser.py) beobachtet diesen Prozess:
            # Exitcode 75 heisst "bitte neu starten". Ein eigener Kindprozess
            # waere ihm entzogen und liefe ohne Schutz weiter.
            global _NEUSTART_ANGEFORDERT
            _NEUSTART_ANGEFORDERT = True
            self.close()
            QApplication.instance().quit()
            return
        try:
            # os.execv wartet unter Windows intern auf das Prozessende des
            # neuen Prozesses, bevor der alte sich beendet - das alte Fenster
            # friert dabei ein, statt zu verschwinden. Daher ein eigener,
            # entkoppelter Prozess statt eines echten Prozess-Austauschs.
            subprocess.Popen(self._neustart_befehl(), cwd=str(CWB_WURZEL))
        except OSError as fehler:
            log.error("Neustart gescheitert: %s", fehler)
            self.sprecher.sprich("Neustart gescheitert.", art="fehler")
            return
        self.close()
        QApplication.instance().quit()

    def _neustart_befehl(self) -> list[str]:
        """Baut die Kommandozeile fuer den Neustart-Unterprozess.

        Im gepackten Zustand (starter.py, setzt `sys.frozen`) hat starter.py
        beim eigenen Start `sys.argv[0]` auf `core/fenster.py` umgeschrieben,
        damit runpy die Datei als __main__ ausfuehrt. Ein Neustart ueber
        `sys.argv` wuerde deshalb core/fenster.py direkt aufrufen und ohne
        den von starter.py gesetzten Suchpfad zum Ordner `pakete` sofort an
        einem fehlenden PySide6-Import scheitern - das Fenster verschwindet,
        ohne dass je ein neues erscheint. Deshalb im gepackten Zustand immer
        ueber starter.py neu starten, im Skript-Start (kein sys.frozen)
        bleibt der bisherige Weg ueber sys.argv unveraendert."""
        if getattr(sys, "frozen", False):
            einstieg = CWB_WURZEL / "starter.py"
            return [sys.executable, str(einstieg)] + sys.argv[1:]
        return [sys.executable] + sys.argv

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
        # Zeile wird dann neu ausgemessen und der Text passend gekuerzt. Neu
        # gemessen wird nur bei echtem Schriftwechsel - sonst wuerde jede
        # Groessenaenderung des Fensters (ueber stil_verzoegert) hier immer
        # wieder unnoetig die Kopfzeilen-Maße anfassen.
        if ereignis.type() in (QEvent.StyleChange, QEvent.FontChange) and hasattr(
            self, "ausgabekopf"
        ):
            schrift = self.font()
            schluessel = (schrift.family(), round(schrift.pointSizeF(), 1))
            if schluessel != self._kopf_schrift_merker:
                self._kopf_schrift_merker = schluessel
                # Setzt nur feste Masse an den Kopfzeilen-Widgets selbst
                # (core/kopfzeile.py, masse_festlegen). Ruehrt die
                # Fenstergroesse nicht mehr an - das war die Quelle der
                # resizeEvent-Kaskaden (Korrektur loeste selbst ein neues
                # resizeEvent aus, das die Skalierung erneut anstiess).
                self.ausgabekopf.masse_festlegen()
            self.ausgabekopf.status_zeichnen()

    def showEvent(self, ereignis) -> None:
        super().showEvent(ereignis)
        # Beim ersten Anzeigen ist das Stilblatt noch unskaliert, und die
        # gemerkte Geometrie (fenster_geometrie_anwenden) wurde vor dem Anzeigen
        # gesetzt: Kachelhoehen, Umbruch und Kopfzeilenmasse stammen dann aus
        # der falschen Schrift. Einmal vollstaendig neu rechnen, sobald das
        # Fenster seine endgueltige Groesse hat.
        if not self._erste_anzeige_erledigt:
            self._erste_anzeige_erledigt = True
            QTimer.singleShot(0, self._layout_neu_berechnen)

    def _layout_neu_berechnen(self) -> None:
        """Stilblatt sofort fuer die tatsaechliche Fenstergroesse skalieren,
        Kopfzeile neu ausmessen, Kachelreihe neu umbrechen, Layout neu setzen."""
        try:
            stil_erneuern(self.width(), self.height())
            self.ausgabekopf.masse_festlegen()
            self.ausgabekopf.status_zeichnen()
            self.kacheln.neu_berechnen()
            flaeche = self.centralWidget()
            flaeche.layout().invalidate()
            flaeche.layout().activate()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Layout nicht neu berechnet: %s", fehler)

    def resizeEvent(self, ereignis) -> None:
        super().resizeEvent(ereignis)
        # Wiedereintritts-Sperre: setStyleSheet() (in stil_anwenden) loest an
        # jedem Widget - auch hier - ein StyleChange-Ereignis aus, das ueber
        # Qt auch ein resizeEvent nach sich ziehen kann. Das ist keine echte
        # Groessenaenderung durch den Nutzer, sondern ein Nachbeben der
        # eigenen Skalierung - hier wird es nicht weiterverarbeitet, sonst
        # startete stil_verzoegert seinen Zeitgeber immer wieder neu.
        if stil_wird_angewandt():
            return
        log.info(
            "resizeEvent %s: %dx%d (vorher %dx%d)",
            datetime.now().strftime("%H:%M:%S.%f")[:-3],
            self.width(),
            self.height(),
            ereignis.oldSize().width(),
            ereignis.oldSize().height(),
        )
        stil_verzoegert(self.width(), self.height())
        # Die Meldung in der Kopfzeile bleibt einzeilig, also muss die Kuerzung
        # zur neuen Breite passen. Beim allerersten Ereignis steht sie noch nicht.
        if hasattr(self, "ausgabekopf"):
            self.ausgabekopf.status_zeichnen()

    def _hintergrundfaeden_beenden(self) -> None:
        """Block 424: stoppt BildFaden, TerminalFaden und den Leitstand-Faden,
        bevor das Fenster selbst zerstoert wird.

        Alle drei haengen per Qt-Elternschaft an `self` (siehe `eltern`-
        Parameter bei ihrer Erzeugung) und wurden bislang beim Schliessen
        nicht beruecksichtigt: lief einer noch (z.B. ein #RUN#-Gradle-Build
        waehrend Strg+F4), zerstoerte Qt ihn zusammen mit dem Fenster, obwohl
        `isRunning()` noch wahr war - Qt beantwortet das nicht mit einer
        Ausnahme, sondern mit qFatal() und einem harten Prozessabbruch
        (Absturz vom 08.10.2026, 16:58 Uhr: Gradle lief noch, Strg+F4 kam
        dazwischen). `not_aus()` nutzt denselben Abbruchweg wie F8, der den
        Prozessbaum sofort beendet, darum reicht hier ein kurzes Zeitlimit."""
        faden = self._terminal_faden
        if faden is not None and faden.isRunning():
            faden.not_aus()
            if not faden.wait(8000):
                log.error(
                    "Terminalbefehl liess sich beim Beenden nicht rechtzeitig abbrechen"
                )

        bild = self._bild_faden
        if bild is not None and bild.isRunning():
            if not bild.wait(BILD_ZEITLIMIT_S * 1000 + 5000):
                log.error(
                    "Bild-Auftrag liess sich beim Beenden nicht rechtzeitig abwarten"
                )

        entscheidung = self.leitstand_faden
        if entscheidung is not None and entscheidung.isRunning():
            if not entscheidung.wait(leitstand.zeitlimit_sekunden() * 1000 + 5000):
                log.error(
                    "Leitstand-Entscheidung liess sich beim Beenden nicht rechtzeitig "
                    "abwarten"
                )

        # BerichtFaden/NachtberichtFaden (core/bruecke.py) stehen schon in
        # einer eigenen Liste statt nur an einer lokalen Variable - trotzdem
        # haengen sie per Qt-Elternschaft an `self` und muessen vor dem
        # Zerstoeren fertig sein. Jeder Hochladeversuch ist durch
        # bruecke.ZEITLIMIT_SEKUNDEN auf zwei kurze Anfragen begrenzt.
        for faden in list(self._bruecke_berichte) + list(self._nachtberichte):
            if faden.isRunning() and not faden.wait(20000):
                log.error("Bruecken-Hochladung liess sich beim Beenden nicht abwarten")

    def closeEvent(self, ereignis) -> None:
        if not (self.wechselt or self._schliessen_erzwingen
                or self._laeuft_beenden("schließen")):
            ereignis.ignore()
            return
        if self in OFFENE_FENSTER:
            OFFENE_FENSTER.remove(self)
        # Nicht die Maximiert-Geometrie merken, sondern die normale - sonst
        # ließe sich nach dem nächsten Start keine kleinere Größe mehr sehen.
        fenster_geometrie_merken(self.normalGeometry())
        try:
            waechter = getattr(self, "ablage_waechter", None)
            if waechter is not None:
                waechter.anhalten()
            eingang_waechter = getattr(self, "eingang_waechter", None)
            if eingang_waechter is not None:
                eingang_waechter.anhalten()
            self._bruecke_stoppen()
            pausetaste = getattr(self, "_pausetaste", None)
            if pausetaste is not None:
                pausetaste.abmelden()
            self._hintergrundfaeden_beenden()
            _orch_beenden(self)
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

# ---------------------------------------------------------------------------
# Herzschlag fuer den Waechter-Prozess (core/waechter_anzeige.py)
# ---------------------------------------------------------------------------
# Der Waechter kennt CWB nur ueber STATUS_DATEI - ein eigener, unabhaengiger
# Prozess, der genau deshalb auch anzeigt, wenn dieser Prozess haengt oder
# abstuerzt. Der QTimer unten (main()) laeuft im GUI-Faden und schreibt die
# Datei jede Sekunde neu; haengt der GUI-Faden, bleibt sie automatisch stehen
# - das ist das Signal fuer den Waechter. "Arbeitet" gilt, sobald IRGENDEIN
# offenes Fenster (OFFENE_FENSTER, mehrere Projekte moeglich) einen Auftrag
# laufen hat (Werkbank._auftrag_aktiv, oben). Block 82 (Punkt 3): zusaetzlich
# die globalen Bildschirmkoordinaten/Groesse des Waechter-Platzhalters in der
# Statusleiste (Werkbank._waechter_platzhalter_geometrie) sowie "minimiert" -
# der Waechter legt sich darauf und blendet sich bei minimiertem CWB aus
# (ausser bei Haengt/Abgestuerzt). Bevorzugt die Geometrie desselben Fensters,
# das gerade arbeitet; sonst das erste sichtbare, nicht minimierte Fenster.

def _herzschlag_schreiben() -> None:
    zustand = "bereit"
    auftrag = ""
    aktives_fenster = None
    for fenster in list(OFFENE_FENSTER):
        try:
            if fenster._auftrag_aktiv():
                zustand = "arbeitet"
                auftrag = fenster._auftrag_kurz()
                aktives_fenster = fenster
                break
        except Exception as fehler:  # noqa: BLE001
            log.exception("Herzschlag: Fensterabfrage gescheitert: %s", fehler)

    geometrie = None
    minimiert = True
    kandidaten = [aktives_fenster] if aktives_fenster is not None else list(OFFENE_FENSTER)
    for fenster in kandidaten:
        if fenster is None:
            continue
        try:
            platz = fenster._waechter_platzhalter_geometrie()
        except Exception as fehler:  # noqa: BLE001
            log.exception("Herzschlag: Platzhaltergeometrie gescheitert: %s", fehler)
            continue
        if platz is not None:
            geometrie = platz
            minimiert = False
            break
        if not fenster.isMinimized():
            minimiert = False

    try:
        STATUS_DATEI.parent.mkdir(parents=True, exist_ok=True)
        daten = {
            "zeit": time.time(), "pid": os.getpid(), "zustand": zustand, "auftrag": auftrag,
            "minimiert": minimiert,
        }
        if geometrie is not None:
            daten.update(geometrie)
        inhalt = json.dumps(daten, ensure_ascii=False)
        temp = STATUS_DATEI.with_suffix(".tmp")
        temp.write_text(inhalt, encoding="utf-8")
        os.replace(temp, STATUS_DATEI)
    except OSError as fehler:
        log.error("Herzschlag nicht schreibbar: %s", fehler)


def _herzschlag_beenden() -> None:
    """An atexit gehaengt: haelt ein regulaeres Programmende fest, damit
    core/waechter_anzeige.py es nicht faelschlich als Absturz meldet. atexit
    laeuft bei einem echten Absturz/Kill nicht - genau der Unterschied, den
    der Waechter braucht."""
    try:
        STATUS_DATEI.write_text(
            json.dumps({"zeit": time.time(), "pid": os.getpid(), "zustand": "beendet"}),
            encoding="utf-8",
        )
    except OSError as fehler:
        log.error("Herzschlag (Ende) nicht schreibbar: %s", fehler)


def _waechter_befehl() -> list[str]:
    """Wie Werkbank._neustart_befehl: im gepackten Zustand (sys.frozen) ueber
    starter.py, sonst fehlt der von starter.py gesetzte Suchpfad zum Ordner
    'pakete' (PySide6 usw.) und der Waechter stuerzte sofort beim Import ab."""
    if getattr(sys, "frozen", False):
        einstieg = CWB_WURZEL / "starter.py"
        return [sys.executable, str(einstieg), "--waechter-anzeige"]
    return [sys.executable, str(Path(sys.argv[0]).resolve()), "--waechter-anzeige"]


def _waechter_starten() -> None:
    """Stoesst core/waechter_anzeige.py als eigenen, konsolenlosen Prozess an
    - ueber denselben Startweg wie CWB selbst (_waechter_befehl). Scheitert
    das, laeuft CWB trotzdem normal weiter, nur ohne Zustandsanzeige."""
    try:
        subprocess.Popen(
            _waechter_befehl(),
            cwd=str(CWB_WURZEL),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log.info("Waechter-Anzeige gestartet")
    except OSError as fehler:
        log.error("Waechter-Anzeige nicht startbar: %s", fehler)


def _waechter_anzeige_starten_und_beenden() -> None:
    """Zweig fuer den Schalter --waechter-anzeige (siehe main()): dieser
    Prozess wird zum Waechter selbst statt ein Hauptfenster aufzubauen - wie
    _admin_worker_starten_und_beenden fuer --admin-worker."""
    try:
        from . import waechter_anzeige
    except ImportError:
        import waechter_anzeige
    waechter_anzeige.main()


def _admin_worker_starten_und_beenden() -> None:
    """Nimmt CWB als erhoehten Worker-Prozess: gestartet mit --admin-worker
    und --admin-schluessel, ohne jede Oberflaeche. Kehrt erst zurueck, wenn
    sich der Worker von selbst beendet (siehe admin_worker_schleife)."""
    schluessel = ""
    if "--admin-schluessel" in sys.argv:
        index = sys.argv.index("--admin-schluessel")
        if index + 1 < len(sys.argv):
            schluessel = sys.argv[index + 1]
    admin_worker_schleife(schluessel)


_ABSTURZ_HANDHABUNG = None
_EINZELINSTANZ_MUTEX = None
_NEUSTART_ANGEFORDERT = False


def _faulthandler_einrichten() -> None:
    """Block 424: haelt crash.log (Datenordner) offen und schaltet Pythons eigenen
    Absturz-Melder ein. logging erreicht einen harten Abbruch (Segfault,
    qFatal(), abort()) nie - dafuer braucht es den C-Stapel, den nur
    faulthandler mitschreibt. Die Datei muss fuer die gesamte Laufzeit offen
    bleiben, darum das globale `_ABSTURZ_HANDHABUNG` statt einer lokalen
    Variable, die der Speicherbereiniger sonst wieder schliessen wuerde."""
    global _ABSTURZ_HANDHABUNG
    try:
        _ABSTURZ_HANDHABUNG = absturzschutz.crash_datei_oeffnen()
        faulthandler.enable(file=_ABSTURZ_HANDHABUNG, all_threads=True)
    except OSError as fehler:
        log.error("faulthandler nicht einrichtbar: %s", fehler)


def _einzelinstanz_sperre_linux() -> bool:
    """Linux-Gegenstueck zum Named Mutex: eine flock-Sperre auf einer Datei
    im Laufzeitordner. Auch sie gibt das Betriebssystem frei, sobald der
    Prozess endet. Beim Neustart (Werkbank._neustart) laeuft die alte
    Instanz noch kurz weiter - darum bis zu fuenf Sekunden Geduld."""
    global _EINZELINSTANZ_MUTEX
    import fcntl
    import tempfile
    ordner = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    try:
        datei = open(ordner / f"cwb_hauptfenster_{os.getuid()}.lock", "a+")
    except OSError as fehler:
        log.error("Einzelinstanz-Sperrdatei nicht anlegbar: %s", fehler)
        return True
    ablauf = time.monotonic() + 5.0
    while True:
        try:
            fcntl.flock(datei, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() > ablauf:
                datei.close()
                return False
            time.sleep(0.1)
    _EINZELINSTANZ_MUTEX = datei
    return True


def _einzelinstanz_sicherstellen() -> bool:
    """Block 424: legt einen systemweiten Named Mutex an, einmal pro
    Windows-Anmeldesitzung.

    Verhindert ein zweites Hauptfenster: am 08.10.2026 blockierte eine
    bereits laufende CWB-Instanz mit ihrem systemweiten Pause-Hotkey
    (core/pausetaste.py) jede weitere - Windows vergibt einen Hotkey nur
    einmal, jeder weitere Versuch scheitert mit Fehlercode 1409 - und am
    Ende liefen acht pythonw.exe-Prozesse gleichzeitig, weil nichts das
    verhinderte. Ein Mutex statt einer Sperrdatei, weil Windows ihn
    automatisch freigibt, sobald der haltende Prozess endet oder abstuerzt;
    eine Sperrdatei bliebe nach einem Absturz liegen und muesste erst als
    veraltet erkannt werden.

    Gilt nur fuer das Hauptfenster, nicht fuer den Admin-Worker oder die
    Waechter-Anzeige - die sind als Begleitprozesse gedacht und haben
    eigene, einfachere Abstimmungen (ADMIN_SPERR_DATEI, STATUS_DATEI).

    Gibt True zurueck, wenn dies die einzige Instanz ist (und haelt den
    Mutex fuer die Lebenszeit des Prozesses offen); False, wenn schon eine
    andere laeuft."""
    global _EINZELINSTANZ_MUTEX
    if sys.platform != "win32":
        return _einzelinstanz_sperre_linux()
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    kernel32.SetLastError(0)
    griff = kernel32.CreateMutexW(None, False, "CWB_Hauptfenster_Einzelinstanz")
    if not griff:
        log.error("Einzelinstanz-Mutex nicht anlegbar (Fehler %s)", kernel32.GetLastError())
        return True  # lieber ein zweites Fenster als eines, das nie startet
    _EINZELINSTANZ_MUTEX = griff
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def _laeuft_bereits_ansagen() -> None:
    """Kurzer gesprochener Hinweis ohne QApplication/Sprecher - die zweite
    Instanz beendet sich, bevor sie Qt oder den vollen Sprachweg aufbaut.
    Direkt ueber SAPI (wie core/sprache.py im Netzausfall), weil das ohne
    Ereignisschleife funktioniert."""
    log.warning("Zweite CWB-Instanz erkannt, beendet sich ohne eigenes Fenster")
    text = "CWB läuft schon. Dieses Fenster beendet sich wieder."
    try:
        if sys.platform != "win32":
            import shutil
            for programm in (["espeak-ng", "-v", "de", "--"], ["espeak", "-v", "de", "--"],
                             ["spd-say", "-l", "de", "-w"]):
                if shutil.which(programm[0]):
                    subprocess.run([*programm, text], timeout=15)
                    break
            return
        import win32com.client
        stimme = win32com.client.Dispatch("SAPI.SpVoice")
        stimme.Speak(text)
    except Exception as fehler:  # noqa: BLE001
        log.error("Ansage der zweiten Instanz fehlgeschlagen: %s", fehler)


def main() -> None:
    # Muss vor allem anderen stehen: ab hier landet jeder Absturz im Log
    # statt auf dem unsichtbaren stderr von pythonw. sys.excepthook faengt
    # nur den Hauptfaden - threading.excepthook ist der eigene Zustaendige
    # fuer alle ueber threading.Thread gestarteten Hintergrundfaeden und war
    # bisher nicht gesetzt, Python schrieb dort mit seiner eigenen Vorgabe
    # weiterhin auf das unsichtbare stderr.
    _faulthandler_einrichten()
    sys.excepthook = unbehandelte_ausnahme
    threading.excepthook = unbehandelte_ausnahme_im_faden
    # Meldungen, die Qt selbst erzeugt (qWarning/qCritical/qFatal aus der
    # C++-Seite, z.B. bei einem Zugriff auf ein Widget aus dem falschen
    # Faden) gingen bisher nach stderr - unter pythonw.exe ins Nichts. Ein
    # qFatal() ruft diesen Handler noch vor dem harten Abbruch auf, darum
    # bekommt auch ein sonst spurloser Absturz jetzt eine Zeile im Log.
    qInstallMessageHandler(qt_meldung_behandeln)

    # Steht bei jedem Start im Log, damit bei einem Fehlerbericht klar ist,
    # welche Fassung lief.
    log.info("CWB startet, Version %s", VERSION)

    # Der erhoehte Admin-Worker ist derselbe Prozess, nur mit anderem
    # Kommandozeilenschalter neu gestartet (siehe
    # AdminWorkerVerwaltung._sicherstellen in core/terminal.py) - er braucht
    # keine Oberflaeche und darf gar nicht erst ein QApplication aufbauen.
    if "--admin-worker" in sys.argv:
        _admin_worker_starten_und_beenden()
        return

    # Der Waechter (core/waechter_anzeige.py) ist derselbe Einstiegspunkt,
    # nur mit anderem Kommandozeilenschalter neu gestartet (_waechter_befehl
    # unten) - genau wie der Admin-Worker braucht er keine Werkbank-
    # Oberflaeche und darf gar nicht erst eine aufbauen.
    if "--waechter-anzeige" in sys.argv:
        _waechter_anzeige_starten_und_beenden()
        return

    # Block 424: ein zweites Hauptfenster blockierte bisher stillschweigend
    # die systemweiten Hotkeys (Pause, Strg+Umschalt+B) der ersten Instanz,
    # statt sich zu erkennen zu geben.
    if not _einzelinstanz_sicherstellen():
        _laeuft_bereits_ansagen()
        return

    # Lauf-Marker (core/absturzschutz.py): erst hier, nach den Begleitprozessen
    # und der Einzelinstanz-Pruefung, damit nur das echte Hauptfenster ihn
    # setzt und loescht. atexit laeuft bei sauberem Ende und beim gewollten
    # Neustart, nicht bei Segfault oder SIGKILL.
    absturzschutz.lauf_beginnen()
    atexit.register(absturzschutz.lauf_beenden_sauber)

    ADMIN_WORKER.sperre_schreiben()
    atexit.register(ADMIN_WORKER.sperre_entfernen)

    anwendung = QApplication(sys.argv)
    stil_laden(anwendung)

    sprecher = Sprecher()

    # Frisch installierte Fassung mit leerem Datenordner: gibt es auf diesem
    # Rechner eine aeltere Datenhaltung, wird sie genau einmal kopiert - vor
    # der Ersteinrichtung, damit uebernommene Einstellungen sie ersparen.
    uebernahme = erstuebernahme(EINSTELLUNGEN_DATEI)
    if uebernahme is not None:
        sprecher.sprich(uebernahme.ansage(), art="immer")

    # Beim allerersten Start ist noch kein Projektordner gemerkt. Ohne ihn
    # bliebe die Projektwahl leer, deshalb wird vorher gefragt.
    if not pfade_vollstaendig():
        log.info("Kein Projektordner eingestellt, Ersteinrichtung wird gezeigt")
        Ersteinrichtung(sprecher).exec()

    fenster = Start(sprecher, Werkbank)
    fenster.resize(*darstellung.FENSTER_START)
    fenster.show()

    # Nach einem Absturz-Neustart durch den Aufpasser: Warnton aus der Gruppe
    # "warnung" (kein gesprochener Satz). Der Hinweis im Verlauf kommt, sobald
    # die Werkbank offen ist (Werkbank.__init__, unterbrochene Auftraege).
    if os.environ.get(absturzschutz.ENV_NACH_ABSTURZ):
        log.warning("CWB wurde nach einem Absturz vom Aufpasser neu gestartet")
        try:
            sprecher.ton("fehler")
        except Exception as fehler:  # noqa: BLE001
            log.error("Warnton nach Absturz nicht spielbar: %s", fehler)

    threading.Thread(
        target=sprecher.vorwaermen,
        args=(FESTE_SAETZE,),
        daemon=True,
    ).start()

    # Diktat-Modell im Hintergrund laden, damit der erste Druck auf den
    # Diktat-Knopf nicht auf das Laden wartet (eigener Faden, blockiert nie).
    try:
        try:
            from . import diktat
        except ImportError:
            import diktat
        diktat.beim_start_vorladen()
    except Exception as fehler:  # noqa: BLE001
        log.error("Diktat-Vorladen nicht gestartet: %s", type(fehler).__name__)

    # Herzschlag fuer den Waechter: ab sofort jede Sekunde, damit die Datei
    # von Anfang an frisch ist, statt die ersten Sekunden als "kein
    # Herzschlag" zu zeigen. atexit sorgt beim regulaeren Ende dafuer, dass
    # der Waechter das von einem Absturz unterscheiden kann (siehe
    # _herzschlag_beenden) - bei einem echten Absturz laeuft atexit nicht.
    _herzschlag_schreiben()
    herzschlag_uhr = QTimer(anwendung)
    herzschlag_uhr.setInterval(1000)
    herzschlag_uhr.timeout.connect(_herzschlag_schreiben)
    herzschlag_uhr.start()
    atexit.register(_herzschlag_beenden)
    _waechter_starten()

    ergebnis = anwendung.exec()
    sys.exit(absturzschutz.EXIT_NEUSTART if _NEUSTART_ANGEFORDERT else ergebnis)


if __name__ == "__main__":
    try:
        main()
    except Exception as fehler:  # noqa: BLE001
        log.exception("CWB abgestürzt: %s", fehler)
        print(f"CWB abgestürzt: {fehler}")
