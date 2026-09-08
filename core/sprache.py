"""
CWB - Code Workbench
Sprachausgabe und Signaltöne.

Ausgabewege:
- "edge"  Edge-TTS, natürliche Stimmen, freie Sprecherwahl, braucht Internet
- "sapi"  Windows-Bordstimme, sofort da, keine Verzögerung
- "nvda"  spricht durch NVDA, gleiche Stimme wie der Screenreader
- "stumm" nur Töne

Wiederkehrende Sätze werden zwischengespeichert und beim zweiten Mal
ohne Verzögerung abgespielt. Fällt das Internet aus, springt SAPI ein.

Wie viel gesprochen wird, regelt die Stufe (Einstellungen, Reiter "Sprache"):
1 nur Meldungen, 2 zusätzlich Berührtes. Der Inhalt des Ausgabefelds wird nie
von allein vorgelesen, dafür gibt es F3 (letzte Antwort) und Strg+L (Markiertes).
Jeder Aufruf von `sprich` nennt dazu die Art seines Satzes.
"""

import asyncio
import hashlib
import json
import logging
import math
import queue
import struct
import threading
import time
import wave
from ctypes import WinDLL, create_unicode_buffer
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("cwb.sprache")

CWB_WURZEL = Path(__file__).resolve().parent.parent
STIMMEN_ORDNER = CWB_WURZEL / ".stimmen"
EINSTELLUNGEN = CWB_WURZEL / "einstellungen.json"

TOENE_ORDNER = CWB_WURZEL / ".toene"
TOENE_ABTASTRATE = 22050
TOENE_EINAUSBLENDEN_MS = 8

NVDA_DLL_ORTE = [
    CWB_WURZEL / "nvdaControllerClient64.dll",
    CWB_WURZEL / "core" / "nvdaControllerClient64.dll",
    Path(r"C:\Program Files (x86)\NVDA\nvdaControllerClient64.dll"),
    Path(r"C:\Program Files\NVDA\nvdaControllerClient64.dll"),
]

# Rückfall, falls die Stimmenliste nicht abrufbar ist
STIMMEN_NOTNAGEL = [
    ("de-DE-KatjaNeural", "weiblich", "Deutschland"),
    ("de-DE-ConradNeural", "männlich", "Deutschland"),
    ("de-DE-AmalaNeural", "weiblich", "Deutschland"),
    ("de-DE-KillianNeural", "männlich", "Deutschland"),
    ("de-AT-IngridNeural", "weiblich", "Österreich"),
    ("de-CH-JanNeural", "männlich", "Schweiz"),
]

STANDARD_STIMME = "de-DE-KatjaNeural"

# ---------------------------------------------------------------------------
# Stufen der Sprachausgabe (Einstellungen, Reiter "Sprache")
# ---------------------------------------------------------------------------
# Jede Stufe enthaelt alles, was die kleinere schon spricht. Stufe eins ist
# die Voreinstellung: laeuft ein Screenreader, liest der ohnehin vor, worauf
# der Fokus steht - CWB wuerde das nur doppeln.
STUFE_MELDUNGEN = 1
STUFE_BERUEHRT = 2
STUFE_STANDARD = STUFE_MELDUNGEN

# Stufe eins ist bewusst eng: automatisch spricht CWB nur noch, wenn ein
# Auftrag angenommen wird, wenn er fertig ist samt Bilanz, beim Hinweis auf
# den Bericht in der Zwischenablage, sowie kurz bei Rueckfragen und Fehlern.
# Der Inhalt des Ausgabefelds wird nie von allein vorgelesen - dafuer gibt es
# F3 (letzte Antwort) und Strg+L (Markiertes), unabhaengig von der Stufe.
STUFEN = [
    (STUFE_MELDUNGEN, "Nur Meldungen",
     "Auftrag angenommen, Ergebnissatz mit Bilanz nach dem Auftrag, Hinweis "
     "auf den Bericht in der Zwischenablage, Rückfragen und Fehler"),
    (STUFE_BERUEHRT, "Meldungen und Berührtes",
     "zusätzlich, worauf der Mauszeiger ruht und wohin der Tastaturfokus springt"),
]

# Art eines Satzes -> ab welcher Stufe er zu hoeren ist.
# "immer" gilt fuer Saetze, die der Nutzer ausdruecklich abruft (Vorlesetasten,
# Probehoeren, Ersteinrichtung); sie stumm zu schalten hiesse, die Taste
# abzuschalten. Nicht eingeordnete Saetze gelten als "beruehrt" und schweigen
# damit in Stufe eins.
SATZARTEN = {
    "immer": 0,
    "meldung": STUFE_MELDUNGEN,
    "beruehrt": STUFE_BERUEHRT,
}
SATZART_STANDARD = "beruehrt"


def stufe_pruefen(wert) -> int:
    """Macht aus einem gespeicherten Wert eine gueltige Stufe."""
    try:
        zahl = int(wert)
    except (TypeError, ValueError):
        return STUFE_STANDARD
    return zahl if STUFE_MELDUNGEN <= zahl <= STUFE_BERUEHRT else STUFE_STANDARD


@dataclass(frozen=True)
class Signal:
    """Ein kurzer Ton. Höhe in Hertz, Dauer in Millisekunden."""
    hoehe: int
    dauer: int


# Zustandsname aus sitzung.Zustand -> Ton.
# Tief für Ruhe, mittel für Arbeit, hoch für Aufmerksamkeit.
SIGNALE: dict[str, Signal] = {
    "bereit": Signal(520, 90),
    "schaerft": Signal(600, 60),
    "denkt": Signal(440, 60),
    "liest": Signal(660, 50),
    "sucht": Signal(700, 50),
    "schreibt": Signal(780, 70),
    "fuehrt_aus": Signal(340, 70),
    "netz": Signal(900, 60),
    "wartet": Signal(1050, 160),
    "fertig": Signal(880, 140),
    "abgebrochen": Signal(300, 200),
    "fehler": Signal(220, 300),
}


# ---------------------------------------------------------------------------
# Tongruppen: geschaltet wird in dreien, nicht Ton fuer Ton.
# "bereit" zaehlt zum Abschluss, weil es das Ende des Verbindens meldet;
# "schaerft" und "netz" zur Arbeit, weil sie waehrend eines Auftrags klingen.
# ---------------------------------------------------------------------------

TON_GRUPPEN: dict[str, tuple[str, ...]] = {
    "abschluss": ("fertig", "abgebrochen", "bereit"),
    "warnung": ("fehler", "wartet"),
    "arbeit": ("liest", "schreibt", "fuehrt_aus", "sucht", "denkt", "schaerft", "netz"),
}

TON_GRUPPEN_TITEL = {
    "abschluss": "Abschlusstöne, fertig und abgebrochen",
    "warnung": "Warntöne, Fehler und Rückfragen",
    "arbeit": "Arbeitstöne, liest, schreibt, führt aus, sucht, denkt",
}

# Alle drei Gruppen sind ab Werk an. Frueher stand "arbeit" auf False - damit
# fielen sieben der zwoelf Toene weg, naemlich genau die, die waehrend eines
# Auftrags klingen. Uebrig blieben nur Start und Abschluss, und es wirkte, als
# gaebe es ueberhaupt keine Toene mehr. Wer sie nicht will, schaltet sie in
# den Einstellungen (F12) selbst ab.
TON_GRUPPEN_STANDARD = {"abschluss": True, "warnung": True, "arbeit": True}

# Welcher Ton beim Probehoeren einer Gruppe erklingt.
TON_GRUPPEN_PROBE = {"abschluss": "fertig", "warnung": "wartet", "arbeit": "schreibt"}

GRUPPE_JE_ZUSTAND = {
    zustand: gruppe
    for gruppe, zustaende in TON_GRUPPEN.items()
    for zustand in zustaende
}


# ---------------------------------------------------------------------------
# Tondateien: einmalig erzeugte Sinustoene mit weichem Ein- und Ausblenden
# ---------------------------------------------------------------------------

def _ton_erzeugen(hoehe: int, dauer_ms: int, ziel: Path) -> None:
    """Schreibt einen Sinuston mit weichem Ein- und Ausblenden als WAV-Datei."""
    anzahl = int(TOENE_ABTASTRATE * dauer_ms / 1000)
    einausblenden = max(1, min(anzahl // 4, int(TOENE_ABTASTRATE * TOENE_EINAUSBLENDEN_MS / 1000)))
    rahmen = bytearray()
    for i in range(anzahl):
        lautstaerke = 1.0
        if i < einausblenden:
            lautstaerke = i / einausblenden
        elif i > anzahl - einausblenden:
            lautstaerke = (anzahl - i) / einausblenden
        wert = math.sin(2 * math.pi * hoehe * i / TOENE_ABTASTRATE) * lautstaerke
        rahmen += struct.pack("<h", int(wert * 32767 * 0.8))
    with wave.open(str(ziel), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(TOENE_ABTASTRATE)
        datei.writeframes(bytes(rahmen))


def _toene_bereitstellen() -> dict[str, Path]:
    """Erzeugt fehlende Tondateien einmalig unter .toene/ und liefert Zustand -> Pfad."""
    pfade: dict[str, Path] = {}
    try:
        TOENE_ORDNER.mkdir(parents=True, exist_ok=True)
    except OSError as fehler:
        log.error("Toeneordner nicht anlegbar: %s", fehler)
        return pfade
    for zustand, signal in SIGNALE.items():
        ziel = TOENE_ORDNER / f"{zustand}.wav"
        if not ziel.exists():
            try:
                _ton_erzeugen(signal.hoehe, signal.dauer, ziel)
            except OSError as fehler:
                log.error("Ton nicht erzeugbar (%s): %s", zustand, fehler)
                continue
        pfade[zustand] = ziel
    return pfade


# ---------------------------------------------------------------------------
# Abspielen über die Windows-Multimediaschnittstelle, ohne Zusatzpaket
# ---------------------------------------------------------------------------

class Abspieler:
    """Spielt MP3-Dateien über winmm ab. Ein Stück zur Zeit, abbrechbar.

    `play alias wait` blockierte frueher den Sprech-Faden bis zum Ende des
    Stuecks. Ein "close" von einem anderen Faden - etwa Escape ueber
    `schweig()` - reihte sich dann hinter diesem blockierenden Befehl ein und
    kam faktisch nie rechtzeitig an, die Ansage liess sich nicht abbrechen.
    Jetzt startet `play` ohne `wait`, ein eigener Wartelauf fragt den Stand
    ab - `stopp()` bleibt so aus jedem Faden jederzeit sofort wirksam."""

    _ABFRAGE_SEKUNDEN = 0.05

    def __init__(self):
        self._zaehler = 0
        self._laufend: str | None = None
        self._sperre = threading.Lock()
        try:
            self._winmm = WinDLL("winmm.dll")
        except OSError as fehler:
            log.error("winmm nicht ladbar: %s", fehler)
            self._winmm = None

    def _befehl(self, text: str) -> bool:
        if self._winmm is None:
            return False
        fehlercode = self._winmm.mciSendStringW(text, None, 0, None)
        if fehlercode:
            puffer = create_unicode_buffer(256)
            self._winmm.mciGetErrorStringW(fehlercode, puffer, 256)
            log.warning("MCI-Fehler bei '%s': %s", text, puffer.value)
            return False
        return True

    def _status(self, alias: str) -> str:
        if self._winmm is None:
            return ""
        puffer = create_unicode_buffer(32)
        if self._winmm.mciSendStringW(f"status {alias} mode", puffer, 32, None):
            return ""
        return puffer.value.strip().lower()

    def stopp(self) -> None:
        with self._sperre:
            alias, self._laufend = self._laufend, None
        if not alias:
            return
        self._befehl(f"stop {alias}")
        # Auf die Bestaetigung warten, statt sofort zu schliessen: "stop"
        # kehrt bei komprimiertem Ton (mp3) manchmal zurueck, bevor die
        # Hardware wirklich still ist. Wird direkt danach ein neues Stueck
        # geoeffnet und gespielt, ueberlagern sich beide kurz - zwei Stimmen
        # gleichzeitig. Die Wartezeit ist eng begrenzt, damit eine haengende
        # Abfrage nicht die naechste Ansage blockiert.
        ende = time.monotonic() + 0.5
        while self._status(alias) == "playing" and time.monotonic() < ende:
            time.sleep(0.01)
        self._befehl(f"close {alias}")

    def spiele(self, datei: Path, warten: bool = True) -> None:
        self.stopp()
        with self._sperre:
            self._zaehler += 1
            alias = f"cwb{self._zaehler}"
            if not self._befehl(f'open "{datei}" type mpegvideo alias {alias}'):
                return
            self._laufend = alias
        if not self._befehl(f"play {alias}"):
            return
        if warten:
            self._bis_fertig_warten(alias)

    def _bis_fertig_warten(self, alias: str) -> None:
        """Fragt den Wiedergabestatus ab, statt mit `play ... wait` zu
        blockieren. So merkt diese Methode sofort, wenn `stopp()` aus einem
        anderen Faden den Alias schon entfernt hat, statt bis zum natuerlichen
        Ende des Stuecks zu warten."""
        while True:
            with self._sperre:
                if self._laufend != alias:
                    return
            if self._status(alias) != "playing":
                break
            time.sleep(self._ABFRAGE_SEKUNDEN)
        self.stopp()


# ---------------------------------------------------------------------------
# Sprecher
# ---------------------------------------------------------------------------

class Sprecher:
    """Spricht Texte und spielt Signaltöne. Blockiert die Oberfläche nie."""

    def __init__(
        self,
        weg: str | None = None,
        stimme: str | None = None,
        tempo: int | None = None,
        sprechen_an: bool = True,
        toene_an: bool = True,
        stufe: int | None = None,
    ):
        gespeichert = self._einstellungen_lesen()
        self.weg = weg or gespeichert.get("weg", "edge")
        self.stimme = stimme or gespeichert.get("stimme", STANDARD_STIMME)
        self.tempo = tempo if tempo is not None else int(gespeichert.get("tempo", 0))
        self.stufe = stufe_pruefen(
            stufe if stufe is not None else gespeichert.get("stufe", STUFE_STANDARD)
        )
        self.sprechen_an = sprechen_an
        self.toene_an = toene_an

        # Hauptschalter und die drei Gruppen aus den Einstellungen (F12).
        self.toene_alle_aus = False
        self.ton_gruppen = dict(TON_GRUPPEN_STANDARD)
        # Zuletzt geklungener Arbeitszustand. Zehn gelesene Dateien
        # hintereinander ergeben so einen Leseton, nicht zehn.
        self._letzter_arbeitston: str | None = None
        self.toene_uebernehmen(self._toene_lesen())

        self._nvda = self._nvda_laden() if self.weg == "nvda" else None
        self._sapi = self._sapi_laden()
        self._abspieler = Abspieler()
        # Fuer schweig() und spricht(): welcher Weg zuletzt tatsaechlich
        # gesprochen hat (self.weg kann "edge" sagen, waehrend ein einzelner
        # Satz mangels Netz doch ueber SAPI ausweicht), und ob gerade ein Satz
        # laeuft.
        self._letzter_weg = ""
        self._aktuell_sprechend = False
        # Zaehlt hoch, sobald schweig() eine neue Ansage gegen die laufende
        # durchsetzt. Ein Satz, dessen Erzeugung (Netzabruf bei Edge-TTS)
        # noch laeuft, wenn schweig() schon einmal weiterzaehlt, wird beim
        # Fertigwerden verworfen statt verspaetet und ueberlappend zu klingen.
        self._sprech_generation = 0
        self._generation_sperre = threading.Lock()

        if self.weg == "edge" and not self._edge_vorhanden():
            log.warning("Edge-TTS nicht vorhanden, weiche auf SAPI aus")
            self.weg = "sapi"
        if self.weg == "nvda" and self._nvda is None:
            log.warning("NVDA nicht erreichbar, weiche auf SAPI aus")
            self.weg = "sapi"

        try:
            STIMMEN_ORDNER.mkdir(parents=True, exist_ok=True)
        except OSError as fehler:
            log.error("Stimmenordner nicht anlegbar: %s", fehler)

        self._sprech_schlange: queue.Queue[tuple[int, str] | None] = queue.Queue()
        self._sprech_faden = threading.Thread(target=self._sprech_schleife, daemon=True)
        self._sprech_faden.start()

        self._ton_pfade = _toene_bereitstellen()
        self._ton_schlange: queue.Queue[str | None] = queue.Queue()
        self._ton_faden = threading.Thread(target=self._ton_schleife, daemon=True)
        self._ton_faden.start()

        log.info("Sprachausgabe über %s, Stimme %s, Tempo %+d%%, Stufe %d",
                 self.weg, self.stimme, self.tempo, self.stufe)

    # -- Einstellungen ------------------------------------------------------

    def _einstellungen_lesen(self) -> dict:
        try:
            if EINSTELLUNGEN.exists():
                inhalt = json.loads(EINSTELLUNGEN.read_text(encoding="utf-8"))
                return inhalt.get("sprache", {})
        except (OSError, ValueError) as fehler:
            log.error("Einstellungen nicht lesbar: %s", fehler)
        return {}

    def _toene_lesen(self) -> dict:
        """Die Toneinstellungen stehen neben dem Abschnitt "sprache" unter
        "toene", damit das Einstellungsfenster sie schreiben kann, ohne die
        Stimmenwahl anzufassen."""
        try:
            if EINSTELLUNGEN.exists():
                inhalt = json.loads(EINSTELLUNGEN.read_text(encoding="utf-8"))
                werte = inhalt.get("toene", {})
                return werte if isinstance(werte, dict) else {}
        except (OSError, ValueError) as fehler:
            log.error("Toneinstellungen nicht lesbar: %s", fehler)
        return {}

    def toene_uebernehmen(self, werte: dict) -> None:
        """Nimmt Hauptschalter und Gruppen an. Wirkt sofort, ohne Neustart."""
        if not isinstance(werte, dict):
            return
        self.toene_alle_aus = bool(werte.get("alle_aus", False))
        for gruppe, standard in TON_GRUPPEN_STANDARD.items():
            self.ton_gruppen[gruppe] = bool(werte.get(gruppe, standard))
        log.info("Töne: alle aus %s, Gruppen %s", self.toene_alle_aus, self.ton_gruppen)

    def einstellungen_sichern(self) -> None:
        daten = {}
        try:
            if EINSTELLUNGEN.exists():
                daten = json.loads(EINSTELLUNGEN.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            daten = {}
        daten["sprache"] = {
            "weg": self.weg,
            "stimme": self.stimme,
            "tempo": self.tempo,
            "stufe": self.stufe,
        }
        try:
            EINSTELLUNGEN.write_text(
                json.dumps(daten, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as fehler:
            log.error("Einstellungen nicht schreibbar: %s", fehler)

    # -- Ausgabewege --------------------------------------------------------

    @staticmethod
    def _edge_vorhanden() -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    def _nvda_laden(self):
        for ort in NVDA_DLL_ORTE:
            if not ort.exists():
                continue
            try:
                dll = WinDLL(str(ort))
                if dll.nvdaController_testIfRunning() == 0:
                    return dll
            except OSError as fehler:
                log.warning("NVDA-DLL nicht ladbar %s: %s", ort, fehler)
        return None

    def _sapi_laden(self):
        try:
            import win32com.client
            return win32com.client.Dispatch("SAPI.SpVoice")
        except Exception as fehler:  # noqa: BLE001
            log.error("SAPI nicht verfügbar: %s", fehler)
            return None

    # -- Stimmenwahl --------------------------------------------------------

    @staticmethod
    def stimmen_auflisten() -> list[tuple[str, str, str]]:
        """Deutschsprachige Edge-Stimmen. Fällt auf eine feste Liste zurück."""
        try:
            import edge_tts
        except ImportError:
            return list(STIMMEN_NOTNAGEL)

        geschlecht = {"Female": "weiblich", "Male": "männlich"}
        land = {"de-DE": "Deutschland", "de-AT": "Österreich", "de-CH": "Schweiz"}

        try:
            alle = asyncio.run(edge_tts.list_voices())
        except Exception as fehler:  # noqa: BLE001
            log.error("Stimmenliste nicht abrufbar: %s", fehler)
            return list(STIMMEN_NOTNAGEL)

        gefunden = [
            (
                eintrag.get("ShortName", ""),
                geschlecht.get(eintrag.get("Gender", ""), eintrag.get("Gender", "")),
                land.get(eintrag.get("Locale", ""), eintrag.get("Locale", "")),
            )
            for eintrag in alle
            if str(eintrag.get("Locale", "")).startswith("de")
        ]
        return sorted(gefunden) or list(STIMMEN_NOTNAGEL)

    def weg_setzen(self, weg: str, sichern: bool = True) -> None:
        """Wechselt den Ausgabeweg im laufenden Betrieb. Ist der gewaehlte Weg
        nicht erreichbar, bleibt es bei SAPI - lieber eine schlichtere Stimme
        als gar keine Ansage."""
        if weg == "edge" and not self._edge_vorhanden():
            log.warning("Edge-TTS nicht vorhanden, bleibe bei SAPI")
            weg = "sapi"
        if weg == "nvda":
            self._nvda = self._nvda or self._nvda_laden()
            if self._nvda is None:
                log.warning("NVDA nicht erreichbar, bleibe bei SAPI")
                weg = "sapi"
        self.schweig()
        self.weg = weg
        if sichern:
            self.einstellungen_sichern()
        log.info("Ausgabeweg jetzt %s", self.weg)

    def stimme_setzen(self, stimme: str, tempo: int | None = None, sichern: bool = True) -> None:
        self.stimme = stimme
        if tempo is not None:
            self.tempo = tempo
        if sichern:
            self.einstellungen_sichern()

    # -- Erzeugen und Zwischenspeichern -------------------------------------

    def _pfad_fuer(self, text: str) -> Path:
        schluessel = f"{self.stimme}|{self.tempo}|{text}"
        name = hashlib.sha1(schluessel.encode("utf-8")).hexdigest()[:20]
        return STIMMEN_ORDNER / f"{name}.mp3"

    def _erzeugen(self, text: str, ziel: Path) -> bool:
        try:
            import edge_tts
        except ImportError:
            return False

        async def lauf():
            ansage = edge_tts.Communicate(text, self.stimme, rate=f"{self.tempo:+d}%")
            await ansage.save(str(ziel))

        try:
            asyncio.run(lauf())
            return ziel.exists() and ziel.stat().st_size > 0
        except Exception as fehler:  # noqa: BLE001
            log.error("Edge-TTS gescheitert: %s", fehler)
            try:
                if ziel.exists():
                    ziel.unlink()
            except OSError:
                pass
            return False

    # -- Sprechen -----------------------------------------------------------

    def _sprech_schleife(self) -> None:
        while True:
            eintrag = self._sprech_schlange.get()
            if eintrag is None:
                return
            generation, text = eintrag
            if generation != self._sprech_generation:
                # Schon vor dem Start durch eine neuere Ansage ueberholt.
                continue
            try:
                self._sprich_jetzt(generation, text)
            except Exception as fehler:  # noqa: BLE001
                log.exception("Sprechen gescheitert: %s", fehler)

    def _sprich_jetzt(self, generation: int, text: str) -> None:
        self._aktuell_sprechend = True
        try:
            if self.weg == "nvda" and self._nvda:
                self._letzter_weg = "nvda"
                self._nvda.nvdaController_cancelSpeech()
                self._nvda.nvdaController_speakText(text)
                return

            if self.weg == "edge":
                datei = self._pfad_fuer(text)
                erzeugt = datei.exists() or self._erzeugen(text, datei)
                if generation != self._sprech_generation:
                    # Waehrend der Erzeugung (Netzabruf) kam eine neuere
                    # Ansage dazwischen - jetzt noch abzuspielen wuerde sich
                    # mit ihr ueberlagern, darum lieber schweigen.
                    return
                if erzeugt:
                    self._letzter_weg = "edge (mp3)"
                    self._abspieler.spiele(datei, warten=True)
                    return
                log.warning("Für diesen Satz weiche ich auf SAPI aus")

            if generation != self._sprech_generation:
                return
            if self._sapi:
                self._letzter_weg = "sapi"
                self._sapi.Speak(text, 0)
        finally:
            self._aktuell_sprechend = False

    def stufe_setzen(self, stufe: int, sichern: bool = True) -> None:
        """Wechselt die Redseligkeit im laufenden Betrieb."""
        self.stufe = stufe_pruefen(stufe)
        if sichern:
            self.einstellungen_sichern()
        log.info("Sprachstufe jetzt %d", self.stufe)

    def art_erlaubt(self, art: str) -> bool:
        """Passt ein Satz dieser Art zur eingestellten Stufe?"""
        return SATZARTEN.get(art, SATZARTEN[SATZART_STANDARD]) <= self.stufe

    def sprich(self, text: str, unterbrechen: bool = True,
               art: str = SATZART_STANDARD) -> None:
        """Reiht Text zum Sprechen ein. Kehrt sofort zurück.

        `art` ordnet den Satz einer Stufe zu (siehe SATZARTEN). Was ueber der
        eingestellten Stufe liegt, wird gar nicht erst eingereiht."""
        if not self.sprechen_an or not text:
            return
        if not self.art_erlaubt(art):
            return
        text = " ".join(text.split())
        if unterbrechen:
            self.schweig()
        with self._generation_sperre:
            generation = self._sprech_generation
        self._sprech_schlange.put((generation, text))

    def schweig(self) -> None:
        """Bricht laufende Sprachausgabe ab und leert die Warteschlange."""
        # Erst hochzaehlen: jeder Satz, der schon in der Erzeugung steckt
        # (Netzabruf bei Edge-TTS) oder noch in der Schlange wartet, traegt
        # eine aeltere Generation und wird beim Fertigwerden verworfen statt
        # sich mit der neuen Ansage zu ueberlagern.
        with self._generation_sperre:
            self._sprech_generation += 1
        # Damit sich am Log ablesen laesst, ob schweig() ueberhaupt ankommt
        # und ob die Ansage gerade wirklich ueber die MP3-Datei lief oder
        # mangels Netz stillschweigend auf SAPI auswich.
        log.info(
            "schweig() aufgerufen: Ausgabeweg=%s, zuletzt gesprochen ueber=%s, "
            "spricht gerade=%s, wartend in der Schlange=%d",
            self.weg, self._letzter_weg or "-", self._aktuell_sprechend,
            self._sprech_schlange.qsize(),
        )
        while not self._sprech_schlange.empty():
            try:
                self._sprech_schlange.get_nowait()
            except queue.Empty:
                break
        try:
            self._abspieler.stopp()
            if self._nvda:
                self._nvda.nvdaController_cancelSpeech()
            if self._sapi:
                self._sapi.Speak("", 1 | 2)
        except Exception as fehler:  # noqa: BLE001
            log.exception("Abbrechen gescheitert: %s", fehler)

    def spricht(self) -> bool:
        """Ist gerade eine Ansage unterwegs oder wartet noch eine in der
        Schlange? Fuer Escape: der erste Druck soll nur die Ansage abbrechen,
        nicht zugleich eine offene Rueckfrage mit Nein beantworten."""
        return self._aktuell_sprechend or not self._sprech_schlange.empty()

    # -- Töne ---------------------------------------------------------------

    def _ton_schleife(self) -> None:
        try:
            import winsound
        except ImportError:
            log.warning("winsound nicht verfügbar, keine Töne")
            return
        # Ohne SND_ASYNC: dieser Faden gehoert allein den Toenen, er darf die
        # 50 bis 300 Millisekunden warten. Asynchron schnitt der naechste Ton
        # den vorigen ab, sodass bei dichter Folge kaum etwas zu hoeren war.
        flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
        while True:
            zustand = self._ton_schlange.get()
            if zustand is None:
                return
            pfad = self._ton_pfade.get(zustand)
            if pfad is None:
                log.warning("Keine Tondatei für Zustand %s", zustand)
                continue
            try:
                winsound.PlaySound(str(pfad), flags)
            except Exception as fehler:  # noqa: BLE001
                log.warning("Ton gescheitert (%s): %s", pfad, fehler)

    def _einreihen(self, zustand: str) -> None:
        if zustand in self._ton_pfade and self._ton_schlange.qsize() < 3:
            self._ton_schlange.put(zustand)

    def ton(self, zustand: str) -> None:
        """Spielt den Ton eines Zustands, sofern seine Gruppe eingeschaltet
        ist. Der Hauptschalter geht allen Gruppen vor.

        Arbeitstoene klingen nur beim Zustandswechsel: liest er zehn Dateien
        nacheinander, kommt der Leseton einmal. Erst der Wechsel zum Schreiben
        bringt den Schreibton. Abschluss- und Warntoene (fertig, abgebrochen,
        Fehler, Rueckfrage) klingen dagegen immer und setzen das Gedaechtnis
        zurueck, damit der naechste Auftrag wieder von vorn beginnt."""
        if not self.toene_an or self.toene_alle_aus:
            return
        gruppe = GRUPPE_JE_ZUSTAND.get(zustand)
        if gruppe == "arbeit":
            if zustand == self._letzter_arbeitston:
                return
            self._letzter_arbeitston = zustand
        else:
            self._letzter_arbeitston = None
        if gruppe is not None and not self.ton_gruppen.get(gruppe, True):
            return
        self._einreihen(zustand)

    def ton_probe(self, zustand: str) -> None:
        """Probehoeren aus den Einstellungen: klingt auch, wenn die Gruppe
        gerade aus ist - sonst bliebe die Schaltflaeche unerklaerlich stumm."""
        self._einreihen(zustand)

    # -- Verbund ------------------------------------------------------------

    def melde(self, zustand: str, ansage: str = "", sprechen: bool = False,
              art: str = SATZART_STANDARD) -> None:
        """Ton immer, Sprache nur wenn ausdrücklich gewünscht und die Stufe
        sie zulässt. Der Ton bleibt von der Stufe unberührt."""
        self.ton(zustand)
        if sprechen and ansage:
            self.sprich(ansage, art=art)

    def vorwaermen(self, saetze: list[str]) -> int:
        """Erzeugt feste Sätze im Voraus, damit sie später sofort da sind."""
        if self.weg != "edge":
            return 0
        anzahl = 0
        for satz in saetze:
            ziel = self._pfad_fuer(satz)
            if not ziel.exists() and self._erzeugen(satz, ziel):
                anzahl += 1
        return anzahl

    def beenden(self) -> None:
        self._sprech_schlange.put(None)
        self._ton_schlange.put(None)
        self._abspieler.stopp()


# Sätze, die immer wieder vorkommen - lohnen sich zum Vorwärmen
FESTE_SAETZE = [
    "Bereit.",
    "Auftrag läuft.",
    "Fertig, keine Datei geändert.",
    "Fertig, eine Datei geändert.",
    "Abgebrochen.",
    "Fehler aufgetreten.",
    "Fortfahren?",
    "Nur lesen.",
    "Lesen und Schreiben erlaubt.",
]


# ---------------------------------------------------------------------------
# Selbsttest
# ---------------------------------------------------------------------------

def _selbsttest() -> None:
    import time

    print("Deutsche Stimmen werden abgerufen …\n")
    stimmen = Sprecher.stimmen_auflisten()
    for nummer, (name, geschlecht, land) in enumerate(stimmen, 1):
        print(f"  {nummer:2}. {name:36} {geschlecht:9} {land}")

    wahl = input("\nNummer wählen (leer = Katja): ").strip()
    stimme = STANDARD_STIMME
    if wahl.isdigit() and 1 <= int(wahl) <= len(stimmen):
        stimme = stimmen[int(wahl) - 1][0]

    eingabe = input("Tempo in Prozent, z. B. 0, 20 oder -10 (leer = 0): ").strip()
    tempo = int(eingabe) if eingabe.lstrip("+-").isdigit() else 0

    sprecher = Sprecher(weg="edge", stimme=stimme, tempo=tempo)
    print(f"\nAusgabeweg: {sprecher.weg}   Stimme: {sprecher.stimme}   Tempo: {sprecher.tempo:+d}%")

    probe = (
        "Größe, Prüfung, Änderung, Öffnen, Übersicht und Straße. "
        "Fertig, drei Dateien geändert."
    )
    print("\nProbesatz wird gesprochen …")
    sprecher.sprich(probe, art="immer")
    time.sleep(10)

    print("\nTöne der Reihe nach:")
    for zustand in SIGNALE:
        print("  ", zustand)
        sprecher.ton(zustand)
        time.sleep(0.6)

    antwort = input("\nDiese Stimme dauerhaft übernehmen? [j/n] ").strip().lower()
    if antwort.startswith("j"):
        sprecher.einstellungen_sichern()
        print(f"Gesichert in {EINSTELLUNGEN}")
        print("Feste Sätze werden vorgewärmt …")
        print(f"{sprecher.vorwaermen(FESTE_SAETZE)} Sätze erzeugt.")

    sprecher.beenden()
    print("\nSelbsttest beendet.")


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    try:
        _selbsttest()
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
    except Exception as fehler:  # noqa: BLE001
        log.exception("Selbsttest abgebrochen: %s", fehler)
        print(f"Selbsttest abgebrochen: {fehler}")
