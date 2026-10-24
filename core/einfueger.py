"""
CWB - Code Workbench
Einfueger (Linux): bringt #RUN#-/#ADMIN#-Ergebnisse nacheinander ins
Zielfenster. Unter Windows bleibt core/zielfenster.py zustaendig.

Eine Warteschlange arbeitet immer nur ein Ergebnis ab: in die Zwischenablage
legen, Zielfenster nach vorn, Strg+V, optional Enter, Zwischenablage leeren -
erst dann kommt das naechste. So ueberschreibt kein Ergebnis ein anderes. Die
Wartezeiten laufen ueber Qt-Zeitgeber statt time.sleep, damit der Qt-Faden
waehrenddessen die Zwischenablage an das Zielfenster ausliefern kann.

Enter wird nur gesendet, wenn das Zielfenster ein Browserfenster mit
"Claude" im Titel ist; bei Terminals und im Zweifel nur eingefuegt.
Schlaegt das Einfuegen fehl, bleibt der Text in der Zwischenablage; am Ende
des Laufs liegen alle gescheiterten Ergebnisse zusammen dort, keines geht
verloren.

Bruecken-Eintraege (mit Rueckruf der Zustellwache) sind strenger: Der Bericht
liegt dann schon auf der Bruecke, der Chat ist nur der Zustellweg. Darum wird
VOR dem Anfassen der Zwischenablage geprueft, ob das Ziel wirklich ein
Browserfenster mit "Claude" im Titel ist und ob Robert gerade nicht tippt
(Leerlaufzeit der Eingabegeraete, `XdotoolWerkzeug.leerlauf_ms`). Fehlt etwas,
wird weder eingefuegt noch Enter gesendet, und nichts bleibt in der
Zwischenablage liegen: der Eintrag meldet Misserfolg und bleibt bei der
Zustellwache in der Warteschlange. Die Zwischenablage wird nur waehrend des
Einfuegens belegt; was vorher darin stand, kommt am Ende des Laufs zurueck.

Die Fensterschnittstelle (xdotool), die Zwischenablage und der Zeitgeber sind
austauschbar, damit die Tests ohne Fenster, Netz und Ton laufen.
"""

import ctypes
import logging
import os
import re
import subprocess
import time
from collections import deque

try:
    from .pfade import log_einrichten
except ImportError:
    from pfade import log_einrichten

log_einrichten()
try:
    from . import auftragsjournal
except ImportError:
    import auftragsjournal

log = logging.getLogger("cwb.einfueger")

# Wartezeiten in Millisekunden: Fokus setzen lassen, Einfuegen abwarten
# (das Zielfenster holt den Text erst jetzt aus unserer Zwischenablage),
# Enter abwarten.
RUHE_VOR_EINFUEGEN_MS = 200
RUHE_NACH_EINFUEGEN_MS = 400
RUHE_NACH_ENTER_MS = 300
XDOTOOL_ZEITLIMIT_S = 3
XPROP_ZEITLIMIT_S = 3

# Bruecken-Eintraege: Mindestruhe der Eingabegeraete vor dem Einfuegen. Steht
# der Chat gerade vorn, kann dort etwas halb getippt sein - dann laenger warten.
# Drei Sekunden ohne Tastatureingabe, bevor CWB von selbst zustellt.
RUHE_FREMD_MS = 3000
RUHE_IM_CHAT_MS = 3000
# Zwischen zwei Bruecken-Einfuegungen derselben Lieferung.
ABSTAND_ZWISCHEN_EINFUEGUNGEN_MS = 2000
# So viele selbst belegte Zwischenablage-Texte werden fuer den Vergleich gemerkt.
EIGENE_TEXTE_MAX = 50

BROWSER_KLASSEN = (
    "firefox", "chrome", "chromium", "brave", "vivaldi", "opera", "edge",
    "librewolf", "zen", "waterfox", "epiphany", "falkon",
)
TERMINAL_KLASSEN = (
    "terminal", "term", "konsole", "alacritty", "kitty", "tilix", "wezterm",
    "ptyxis", "foot", "terminator", "guake", "tmux", "console",
)


def enter_passt(titel: str, klasse: str) -> bool:
    """Nur ein Browserfenster mit "Claude" im Titel bekommt Enter. Ein
    Terminal, in dem Claude Code laeuft, hat ebenfalls "Claude" im Titel -
    darum zaehlt zusaetzlich die Fensterklasse, und im Zweifel gilt: kein
    Enter."""
    klasse = (klasse or "").lower()
    if "claude" not in (titel or "").lower():
        return False
    if any(t in klasse for t in TERMINAL_KLASSEN):
        return False
    return any(b in klasse for b in BROWSER_KLASSEN)


def klasse_aus_xprop(ausgabe: str) -> str:
    """Zieht die Fensterklasse aus der Ausgabe von `xprop WM_CLASS`, z. B.
    WM_CLASS(STRING) = "google-chrome", "Google-chrome". Gibt beide Namen
    durch Leerzeichen getrennt zurueck, leer wenn nichts zu lesen ist."""
    return " ".join(re.findall(r'"([^"]*)"', ausgabe or "")).strip()


class XdotoolWerkzeug:
    """Fensterzugriff ueber xdotool. Jede Methode meldet Misserfolg als
    None/False, nie als Ausnahme."""

    def _lauf(self, *argumente: str) -> str | None:
        try:
            ergebnis = subprocess.run(
                ["xdotool", *argumente], capture_output=True, text=True,
                timeout=XDOTOOL_ZEITLIMIT_S,
            )
        except (OSError, subprocess.SubprocessError) as fehler:
            log.warning("xdotool %s nicht ausfuehrbar: %s", " ".join(argumente), fehler)
            return None
        if ergebnis.returncode != 0:
            log.info("xdotool %s: Code %s %s", " ".join(argumente),
                     ergebnis.returncode, ergebnis.stderr.strip()[:120])
            return None
        return ergebnis.stdout.strip()

    def fenster_lesen(self, kennung: str | None = None) -> tuple | None:
        """(Kennung, Titel, Klasse) des aktiven oder des genannten Fensters."""
        if kennung is None:
            kennung = self._lauf("getactivewindow")
            if not kennung:
                return None
        titel = self._lauf("getwindowname", kennung)
        if titel is None:
            return None
        return (kennung, titel, self._klasse_lesen(kennung))

    def _klasse_lesen(self, kennung: str) -> str:
        """Fensterklasse ueber xprop: `xdotool getwindowclassname` gibt es in
        aelteren xdotool-Fassungen (z. B. 3.20160805) nicht. Misserfolg
        liefert eine leere Klasse - dann sendet enter_passt() kein Enter."""
        try:
            ergebnis = subprocess.run(
                ["xprop", "-id", kennung, "WM_CLASS"], capture_output=True, text=True,
                timeout=XPROP_ZEITLIMIT_S,
            )
        except (OSError, subprocess.SubprocessError) as fehler:
            log.warning("xprop WM_CLASS %s nicht ausfuehrbar: %s", kennung, fehler)
            return ""
        if ergebnis.returncode != 0:
            log.info("xprop WM_CLASS %s: Code %s %s", kennung, ergebnis.returncode,
                     ergebnis.stderr.strip()[:120])
            return ""
        return klasse_aus_xprop(ergebnis.stdout)

    def chat_kandidaten(self) -> list:
        """Kennungen aller Fenster mit "Claude" im Titel, das oberste in der
        Fensterreihenfolge (zuletzt aktive) zuerst."""
        treffer = self._lauf("search", "--name", "Claude") or ""
        gefunden = [z for z in treffer.split() if z.isdigit()]
        if len(gefunden) < 2:
            return gefunden
        reihenfolge: list[int] = []
        try:
            ergebnis = subprocess.run(
                ["xprop", "-root", "_NET_CLIENT_LIST_STACKING"], capture_output=True,
                text=True, timeout=XPROP_ZEITLIMIT_S)
            if ergebnis.returncode == 0:
                reihenfolge = [int(h, 16) for h in re.findall(r"0x[0-9a-fA-F]+", ergebnis.stdout)]
        except (OSError, subprocess.SubprocessError, ValueError) as fehler:
            log.info("Fensterreihenfolge nicht lesbar: %s", fehler)
        rang = {kennung: nr for nr, kennung in enumerate(reihenfolge)}
        return sorted(gefunden, key=lambda k: rang.get(int(k), -1), reverse=True)

    def eigene_pid(self, kennung: str) -> bool:
        pid = self._lauf("getwindowpid", kennung)
        return pid is not None and pid == str(os.getpid())

    def aktivieren(self, kennung: str) -> bool:
        if self._lauf("windowactivate", "--sync", kennung) is None:
            return False
        aktiv = self._lauf("getactivewindow")
        return aktiv == kennung

    def taste(self, name: str) -> bool:
        return self._lauf("key", "--clearmodifiers", name) is not None

    def leerlauf_ms(self) -> int | None:
        """Millisekunden seit der letzten Tastatur-/Mauseingabe (X11,
        Bildschirmschoner-Erweiterung); None, wenn das nicht lesbar ist."""
        try:
            class _Info(ctypes.Structure):
                _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int),
                            ("kind", ctypes.c_int), ("til_or_since", ctypes.c_ulong),
                            ("idle", ctypes.c_ulong), ("event_mask", ctypes.c_ulong)]

            x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            xss = ctypes.cdll.LoadLibrary("libXss.so.1")
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XDefaultRootWindow.restype = ctypes.c_ulong
            x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(_Info)
            xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                   ctypes.POINTER(_Info)]
            anzeige = x11.XOpenDisplay(None)
            if not anzeige:
                return None
            try:
                info = xss.XScreenSaverAllocInfo()
                if not xss.XScreenSaverQueryInfo(
                        anzeige, x11.XDefaultRootWindow(anzeige), info):
                    return None
                return int(info.contents.idle)
            finally:
                x11.XCloseDisplay(anzeige)
        except Exception as fehler:  # noqa: BLE001
            log.info("Leerlaufzeit nicht lesbar: %s", fehler)
            return None


_letztes_ziel: tuple | None = None
# Hat die letzte Suche kein Chatfenster gefunden? (Fuer die Ansage.)
_suche_erfolglos = False
EINSTELLUNG_CHAT_ZIEL = "chat_ziel"


def _ziel_laden() -> tuple | None:
    """Das beim letzten Lauf gemerkte Chatfenster aus einstellungen.json
    (Kennung und Titel; die Klasse wird frisch gelesen). Tests ersetzen das."""
    try:
        try:
            from .pfade import einstellungen_lesen
        except ImportError:
            from pfade import einstellungen_lesen
        wert = einstellungen_lesen().get(EINSTELLUNG_CHAT_ZIEL)
        if isinstance(wert, dict) and wert.get("kennung"):
            return (str(wert["kennung"]), str(wert.get("titel", "")), "")
    except Exception:  # noqa: BLE001
        log.exception("Gemerktes Chatfenster nicht gelesen")
    return None


def _ziel_speichern(ziel: tuple) -> None:
    """Schreibt das Chatfenster in einstellungen.json, nur bei Aenderung der
    Kennung (Titel wechseln mit jedem Gespraech). Tests ersetzen das."""
    try:
        try:
            from .pfade import einstellungen_lesen, einstellungen_schreiben
        except ImportError:
            from pfade import einstellungen_lesen, einstellungen_schreiben
        werte = einstellungen_lesen()
        alt = werte.get(EINSTELLUNG_CHAT_ZIEL)
        if isinstance(alt, dict) and alt.get("kennung") == ziel[0]:
            return
        werte[EINSTELLUNG_CHAT_ZIEL] = {"kennung": ziel[0], "titel": ziel[1][:80]}
        einstellungen_schreiben(werte)
    except Exception:  # noqa: BLE001
        log.exception("Chatfenster nicht gespeichert")


def _ist_chat(werkzeug, ziel: tuple | None) -> tuple | None:
    """Frisch gelesenes Fenster, wenn es noch existiert und ein Chat ist
    (Titel "Claude", Browserklasse, nicht CWB selbst); sonst None."""
    if not ziel:
        return None
    try:
        info = werkzeug.fenster_lesen(ziel[0])
        eigene = getattr(werkzeug, "eigene_pid", None)
        if info and enter_passt(info[1], info[2]) and not (eigene and eigene(info[0])):
            return info
    except Exception:  # noqa: BLE001
        log.exception("Chatfenster nicht geprueft")
    return None


def chat_suchen(werkzeug=None) -> tuple | None:
    """Sucht das Chatfenster selbst: Titel enthaelt "Claude" und die
    Fensterklasse ist ein Browser. Mehrere: das zuletzt aktive (oberstes in
    der Fensterreihenfolge des Fenstermanagers)."""
    werkzeug = werkzeug or XdotoolWerkzeug()
    try:
        kennungen = werkzeug.chat_kandidaten()
    except Exception:  # noqa: BLE001
        log.exception("Chatfenster-Suche fehlgeschlagen")
        return None
    for kennung in kennungen or []:
        info = _ist_chat(werkzeug, (kennung, "", ""))
        if info:
            return info
    return None


def ziel_finden(werkzeug=None) -> tuple | None:
    """Ein Chatfenster fuer die Zustellung: das gemerkte, wenn es noch ein
    Chat ist, sonst das aus einstellungen.json, sonst eine Suche. Ein Fund wird
    gemerkt und gespeichert. Nichts gefunden: None."""
    global _letztes_ziel, _suche_erfolglos
    werkzeug = werkzeug or XdotoolWerkzeug()
    try:
        fund = _ist_chat(werkzeug, _letztes_ziel)
        if fund is None:
            fund = _ist_chat(werkzeug, _ziel_laden())
            if fund is not None:
                log.info("Chatfenster aus den Einstellungen: %s", fund[1][:60])
        if fund is None:
            fund = chat_suchen(werkzeug)
            if fund is not None:
                log.info("Chatfenster selbst gefunden: %s", fund[1][:60])
        if fund is None:
            if not _suche_erfolglos:
                log.warning("Kein Chatfenster gefunden")
            _suche_erfolglos = True
            return None
        _suche_erfolglos = False
        _letztes_ziel = fund
        _ziel_speichern(fund)
        return fund
    except Exception:  # noqa: BLE001
        log.exception("Chatfenster konnte nicht ermittelt werden")
        return None


def suche_erfolglos() -> bool:
    return _suche_erfolglos


def ziel_merken(werkzeug=None) -> tuple | None:
    """Merkt das aktive fremde Fenster (nicht CWB selbst). Ist gerade CWB
    vorn oder nichts lesbar, bleibt das zuletzt bekannte Ziel; gibt es auch
    das nicht (z. B. nach einem Neustart), wird das Chatfenster gesucht."""
    global _letztes_ziel
    werkzeug = werkzeug or XdotoolWerkzeug()
    try:
        aktuell = werkzeug.fenster_lesen()
        if aktuell and not werkzeug.eigene_pid(aktuell[0]):
            _letztes_ziel = aktuell
            log.info("Zielfenster gemerkt: %s", aktuell[1][:60])
            if enter_passt(aktuell[1], aktuell[2]):
                _ziel_speichern(aktuell)
        elif _letztes_ziel is not None:
            log.info("Kein frisches Zielfenster - bleibe bei: %s", _letztes_ziel[1][:60])
        else:
            ziel_finden(werkzeug)
    except Exception:  # noqa: BLE001
        log.exception("Zielfenster konnte nicht gemerkt werden")
    return _letztes_ziel


class Einfueger:
    """Warteschlange mit genau einem Ergebnis in Arbeit.

    werkzeug:       fenster_lesen/aktivieren/taste (siehe XdotoolWerkzeug)
    zwischenablage: Objekt mit setzen(text) -> bool, lesen() und leeren()
    planen:         planen(ms, funktion), ruft die Funktion spaeter auf
    enter_erlaubt:  Aufruf ohne Argumente, liest den Schalter bei jedem Lauf
    fertig:         fertig(erfolge: int, gescheitert: list[str]) am Ende
                    eines Laufs (Warteschlange leer)."""

    def __init__(self, werkzeug, zwischenablage, planen, enter_erlaubt, fertig,
                 bild_setzen=None):
        self._werkzeug = werkzeug
        self._ablage = zwischenablage
        self._planen = planen
        self._enter_erlaubt = enter_erlaubt
        self._fertig = fertig
        # bild_setzen(pfad) -> bool legt ein Bild in die Zwischenablage; nur
        # fuer Eintraege mit Bild (Brueckenauftrag #BILD#).
        self._bild_setzen = bild_setzen
        self._warteschlange: deque = deque()
        self._laeuft = False
        self._erfolge = 0
        self._gescheitert: list[str] = []
        # Was zuletzt als "gescheitert" in der Zwischenablage liegen blieb.
        self._liegengeblieben: list[str] = []
        # Parallel zur Warteschlange: zu welchem Auftrag jedes Ergebnis gehoert.
        self._kennungen: deque = deque()
        self.naechste_kennung: dict | None = None
        self._kennung_aktuell: dict | None = None
        # Rueckruf(erfolg, grund) je Ergebnis, den der Aufrufer unmittelbar
        # vorher in `naechster_rueckruf` ablegt (Zustellwache).
        self._rueckrufe: deque = deque()
        self.naechster_rueckruf = None
        self._rueckruf_aktuell = None
        self._text_aktuell: str = ""
        self._bild_aktuell: str | None = None
        self._bild_gescheitert: str | None = None
        # Bruecken-Eintrag (Rueckruf vorhanden) in Arbeit? Dann gelten die
        # strengen Regeln aus dem Modulkopf.
        self._aktuell_verwaltet = False
        # Was vor dem Lauf in der Zwischenablage stand (nur Text, nur Fremdes),
        # und welche Texte wir selbst hineingelegt haben.
        self._gesichert: str | None = None
        self._eigene: deque = deque(maxlen=EIGENE_TEXTE_MAX)
        self._ablage_belegt = False
        self._abstand_noetig = False
        self._chat_vorn_zeit = float("-inf")

    def hinzufuegen(self, ziel: tuple | None, text: str, bild_pfad: str | None = None) -> None:
        """Reiht ein Ergebnis ein. Mit `bild_pfad` geht ein Bild statt des
        Textes ins Zielfenster (`text` ist dann nur eine Beschriftung)."""
        if not text:
            return
        # `naechste_kennung` (nur fuers Auftragsjournal) setzt der Aufrufer
        # unmittelbar vorher; sie aendert nichts am Ablauf.
        self._kennungen.append(self.naechste_kennung)
        self.naechste_kennung = None
        verwaltet = self.naechster_rueckruf is not None
        self._rueckrufe.append(self.naechster_rueckruf)
        self.naechster_rueckruf = None
        self._warteschlange.append((ziel, text, bild_pfad, verwaltet))
        if not self._laeuft:
            self._laeuft = True
            self._gesichert = self._ablage_sichern()
            # Liegt das Gescheiterte des letzten Laufs noch unveraendert in der
            # Zwischenablage, zaehlt es weiter - sonst hat der Nutzer es
            # schon selbst ersetzt oder abgeholt.
            if self._liegengeblieben and self._ablage.lesen() == "\n\n".join(self._liegengeblieben):
                self._gescheitert = list(self._liegengeblieben)
            self._liegengeblieben = []
            self._naechstes()

    def _ablage_sichern(self) -> str | None:
        """Merkt den fremden Text, der vor dem Lauf in der Zwischenablage stand.
        Eigene Reste (von uns hineingelegt) werden nicht zurueckgeschrieben."""
        try:
            alt = self._ablage.lesen()
        except Exception:  # noqa: BLE001
            log.exception("Zwischenablage nicht gelesen")
            return None
        if not alt or alt in self._eigene or alt == "\n\n".join(self._liegengeblieben):
            return None
        return alt

    def _ablage_setzen(self, text: str) -> bool:
        self._eigene.append(text)
        self._ablage_belegt = True
        return bool(self._ablage.setzen(text))

    def wartend(self) -> int:
        return len(self._warteschlange) + (1 if self._laeuft else 0)

    def _naechstes(self) -> None:
        if not self._warteschlange:
            self._laeuft = False
            erfolge, gescheitert = self._erfolge, self._gescheitert
            self._erfolge, self._gescheitert = 0, []
            self._liegengeblieben = list(gescheitert)
            if gescheitert:
                # Alle gescheiterten Ergebnisse zusammen in die Zwischenablage,
                # damit das spaetere nicht das fruehere verdraengt.
                self._ablage.setzen("\n\n".join(gescheitert))
            elif self._bild_gescheitert and self._bild_setzen:
                # Ein Bild blieb liegen: wieder in die Zwischenablage.
                try:
                    self._bild_setzen(self._bild_gescheitert)
                except Exception:  # noqa: BLE001
                    log.exception("Bild nicht zurueck in die Zwischenablage gelegt")
            elif self._gesichert:
                # Nichts bleibt liegen: der alte Inhalt kommt zurueck.
                try:
                    self._ablage.setzen(self._gesichert)
                    auftragsjournal.schreibe("ablage_zurueck", "alter Inhalt wiederhergestellt")
                except Exception:  # noqa: BLE001
                    log.exception("Alte Zwischenablage nicht zurueckgeschrieben")
            self._gesichert = None
            self._ablage_belegt = False
            self._abstand_noetig = False
            self._bild_gescheitert = None
            try:
                self._fertig(erfolge, gescheitert)
            except Exception:  # noqa: BLE001
                log.exception("Abschlussmeldung des Einfuegers fehlgeschlagen")
            return
        ziel, text, bild, verwaltet = self._warteschlange.popleft()
        try:
            self._kennung_aktuell = self._kennungen.popleft() if self._kennungen else None
        except Exception:  # noqa: BLE001
            self._kennung_aktuell = None
        try:
            self._rueckruf_aktuell = self._rueckrufe.popleft() if self._rueckrufe else None
        except Exception:  # noqa: BLE001
            self._rueckruf_aktuell = None
        self._text_aktuell, self._bild_aktuell = text, bild
        self._aktuell_verwaltet = verwaltet

        def los() -> None:
            try:
                self._bearbeiten(ziel, text)
            except Exception:  # noqa: BLE001
                log.exception("Einfuegen unerwartet fehlgeschlagen")
                self._scheitern(text, "unerwarteter Fehler")

        if verwaltet and self._abstand_noetig:
            # Zwischen zwei Bruecken-Einfuegungen Luft lassen, damit nichts
            # verschluckt wird.
            self._abstand_noetig = False
            self._planen(ABSTAND_ZWISCHEN_EINFUEGUNGEN_MS, los)
        else:
            los()

    def _scheitern(self, text: str, grund: str = "") -> None:
        # Der Text bleibt in der Zwischenablage liegen (siehe _naechstes).
        auftragsjournal.schreibe("ablage_zwischenablage",
                                 f"{'bild' if self._bild_aktuell else 'text'} "
                                 f"grund={grund or 'unbekannt'}",
                                 **self._journal_ziel())
        if self._aktuell_verwaltet:
            # Der Bericht liegt auf der Bruecke und bei der Zustellwache:
            # nichts in der Zwischenablage liegen lassen.
            self._ablage_aufraeumen()
        elif self._bild_aktuell:
            self._bild_gescheitert = self._bild_aktuell
        else:
            self._gescheitert.append(text)
        self._rueckruf_melden(False, grund or "unbekannt")
        self._naechstes()

    def _ablage_aufraeumen(self) -> None:
        """Nimmt zurueck, was dieser Eintrag in die Zwischenablage gelegt hat."""
        if not self._ablage_belegt:
            return
        self._ablage_belegt = False
        try:
            self._ablage.leeren()
        except Exception:  # noqa: BLE001
            log.exception("Zwischenablage nicht geleert")

    def zustellung_moeglich(self, ziel: tuple, manuell: bool = False) -> tuple[bool, str]:
        """Oeffentlich fuer die Zustellwache: darf jetzt zugestellt werden?
        Mit `manuell` (Robert hat die Zustelltaste gedrueckt) entfaellt die
        Ruhezeit, das Ziel muss aber ein echtes Chatfenster sein."""
        try:
            return self._zustellung_erlaubt(ziel, manuell)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Zustellpruefung fehlgeschlagen")
            return False, f"Pruefung fehlgeschlagen: {fehler}"

    def _zustellung_erlaubt(self, ziel: tuple, manuell: bool = False) -> tuple[bool, str]:
        """Strenge Pruefung fuer Bruecken-Eintraege, bevor irgendetwas
        geschieht: ist das Ziel wirklich der Chat (Titel "Claude" und
        Browserklasse), und tippt Robert gerade nicht?

        Ob im Eingabefeld des Chats schon etwas steht, laesst sich von aussen
        nicht sicher lesen (der Browser gibt den Feldinhalt unter X11 nicht
        preis; Markieren und Kopieren wuerde seinen Text anfassen). Ersatz:
        Ruhe der Eingabegeraete - 3 Sekunden (RUHE_FREMD_MS, RUHE_IM_CHAT_MS)."""
        kennung = ziel[0]
        info = self._werkzeug.fenster_lesen(kennung)
        if not info:
            return False, "Zielfenster nicht lesbar"
        if not enter_passt(info[1], info[2]):
            return False, "kein Chatfenster"
        if manuell:
            return True, ""
        leerlauf = getattr(self._werkzeug, "leerlauf_ms", None)
        if leerlauf is None:
            return True, ""
        aktiv = self._werkzeug.fenster_lesen()
        vorn = bool(aktiv and aktiv[0] == kennung)
        ruhe = leerlauf()
        if ruhe is None:
            # Ohne Leerlaufzeit: nur einfuegen, wenn der Chat seit mindestens
            # 3 Sekunden nicht mehr vorn war.
            jetzt = time.monotonic()
            if vorn:
                self._chat_vorn_zeit = jetzt
                return False, "Chat im Vordergrund, Eingabe nicht pruefbar"
            if jetzt - self._chat_vorn_zeit < RUHE_FREMD_MS / 1000:
                return False, "Chat war gerade erst vorn"
            return True, ""
        noetig = RUHE_IM_CHAT_MS if vorn else RUHE_FREMD_MS
        if ruhe < noetig:
            return False, f"Eingabe laeuft (Ruhe {ruhe} ms, noetig {noetig})"
        return True, ""

    def _rueckruf_melden(self, erfolg: bool, grund: str = "") -> None:
        """Meldet dem Aufrufer das Ergebnis dieses einen Eintrags; ein Fehler
        im Rueckruf stoert den Ablauf nie."""
        rueckruf, self._rueckruf_aktuell = self._rueckruf_aktuell, None
        if rueckruf is None:
            return
        try:
            rueckruf(erfolg, grund)
        except Exception:  # noqa: BLE001
            log.exception("Rueckruf des Einfuegers fehlgeschlagen")

    def _journal_ziel(self) -> dict:
        k = self._kennung_aktuell or {}
        return {"nummer": k.get("nummer"), "block": k.get("block"), "art": k.get("art")}

    def _chat_sicherstellen(self, ziel: tuple | None) -> tuple | None:
        """Bruecken-Eintrag: fehlt das Ziel oder ist es kein Chat mehr (z. B.
        nach einem Neustart oder geschlossenem Browser), das Chatfenster
        selbst suchen, bevor aufgegeben wird."""
        if ziel and _ist_chat(self._werkzeug, ziel):
            return ziel
        return ziel_finden(self._werkzeug) or ziel

    def _bearbeiten(self, ziel: tuple | None, text: str) -> None:
        if self._aktuell_verwaltet:
            ziel = self._chat_sicherstellen(ziel)
        if not ziel:
            log.info("Kein Zielfenster - Ergebnis bleibt in der Zwischenablage")
            return self._scheitern(text, "kein Zielfenster")
        if self._aktuell_verwaltet:
            manuell = bool((self._kennung_aktuell or {}).get("manuell"))
            erlaubt, grund = self._zustellung_erlaubt(ziel, manuell)
            if not erlaubt:
                log.info("Zustellung zurueckgestellt: %s", grund)
                return self._scheitern(text, grund)
        if self._bild_aktuell:
            # Das Bild frisch hineinlegen: ein Ergebnis davor hat die
            # Zwischenablage geleert.
            self._ablage_belegt = True
            if not (self._bild_setzen and self._bild_setzen(self._bild_aktuell)):
                log.warning("Zwischenablage nahm das Bild nicht an")
                return self._scheitern(text, "Zwischenablage nahm Bild nicht an")
        elif not self._ablage_setzen(text):
            log.warning("Zwischenablage nahm den Text nicht an")
            return self._scheitern(text, "Zwischenablage nahm Text nicht an")
        kennung, titel, klasse = ziel
        if not self._werkzeug.aktivieren(kennung):
            log.warning("Zielfenster liess sich nicht nach vorn holen: %s", titel[:60])
            return self._scheitern(text, "Zielfenster nicht nach vorn")
        self._planen(RUHE_VOR_EINFUEGEN_MS, lambda: self._einfuegen(ziel, text))

    def _einfuegen(self, ziel: tuple, text: str) -> None:
        try:
            kennung, titel, klasse = ziel
            aktiv = self._werkzeug.fenster_lesen()
            if not aktiv or aktiv[0] != kennung:
                log.warning("Fokus vor dem Einfuegen verloren: %s", titel[:60])
                return self._scheitern(text, "Fokus verloren")
            if self._aktuell_verwaltet and not enter_passt(aktiv[1], aktiv[2]):
                log.warning("Vorn steht kein Chatfenster: %s", aktiv[1][:60])
                return self._scheitern(text, "kein Chatfenster")
            if not self._werkzeug.taste("ctrl+v"):
                log.warning("Strg+V wurde nicht angenommen: %s", titel[:60])
                return self._scheitern(text, "Strg+V nicht angenommen")
            log.info("%s eingefuegt in: %s", "Bild" if self._bild_aktuell else "Ergebnis",
                     titel[:60])
            # Titel frisch lesen: Chatfenster benennen sich um.
            neu = self._werkzeug.fenster_lesen(kennung)
            senden = bool(self._enter_erlaubt()) and enter_passt(
                neu[1] if neu else titel, neu[2] if neu else klasse)
            auftragsjournal.eingefuegt(neu[1] if neu else titel, senden,
                                       self._kennung_aktuell)
            self._planen(RUHE_NACH_EINFUEGEN_MS, lambda: self._abschicken(senden))
        except Exception:  # noqa: BLE001
            log.exception("Einfuegen fehlgeschlagen")
            self._scheitern(text, "Fehler beim Einfuegen")

    def _abschicken(self, enter: bool) -> None:
        try:
            if enter:
                if not self._werkzeug.taste("Return"):
                    log.warning("Enter wurde nicht angenommen")
                else:
                    log.info("Enter gesendet")
            self._planen(RUHE_NACH_ENTER_MS if enter else 0, self._abschliessen)
        except Exception:  # noqa: BLE001
            log.exception("Abschicken fehlgeschlagen")
            self._abschliessen()

    def _abschliessen(self) -> None:
        # Eingefuegt: Zwischenablage leeren, sonst fuegt der Nutzer es per
        # eigenem Strg+V ein zweites Mal ein.
        self._ablage.leeren()
        self._ablage_belegt = False
        self._abstand_noetig = self._aktuell_verwaltet
        self._erfolge += 1
        # Ein Text, der frueher gescheitert war und jetzt angekommen ist, soll
        # nicht am Ende erneut in die Zwischenablage gelegt werden.
        if self._text_aktuell in self._gescheitert:
            self._gescheitert.remove(self._text_aktuell)
        self._rueckruf_melden(True)
        self._naechstes()
