"""
CWB - Code Workbench
Diktat fuer den Orchestrator: Aufnahme vom Systemstandard-Mikrofon, lokale
Erkennung mit faster-whisper (fest Deutsch), Wortliste, optionale
Textbereinigung ueber Gemini und der Sprachbefehl zum Absenden.

Reines Python ohne Qt: die Ansicht (core/orchestrator_ansicht.py) ruft
`Diktat` auf und bekommt das Ergebnis ueber Rueckruefe aus einem Arbeitsfaden.
Aufnahme und Erkennung sind austauschbar (`aufnehmer_fabrik`,
`modell_fabrik`), damit Tests weder Mikrofon noch Modell brauchen.

Datenschutz: Das Audio liegt nur im Arbeitsspeicher und wird nach der
Erkennung verworfen, nie gespeichert. Das Log nennt nur Dauer, Modell und
Textlaenge, nie den erkannten Text und nie den Schluessel. An Gemini geht nie
Audio, nur reiner Text.
"""

import logging
import threading
import time
from pathlib import Path

import requests

try:
    from . import leitstand
    from .pfade import (DATENORDNER, einstellungen_lesen, einstellungen_schreiben,
                        log_einrichten)
except ImportError:
    import leitstand
    from pfade import (DATENORDNER, einstellungen_lesen, einstellungen_schreiben,
                       log_einrichten)

CWB_WURZEL = Path(__file__).resolve().parent.parent
LOG_DATEI = CWB_WURZEL / "cwb_fehler.log"

log_einrichten()
log = logging.getLogger("cwb.diktat")

ABTASTRATE = 16000
SPRACHE = "de"
BEAM_GROESSE = 1
RECHENART = "int8"
RECHEN_FAEDEN = 8
MODELLE = ("small", "medium")
# Messung auf diesem Rechner: small mit Beam 1 und 8 Faeden braucht rund 1 s
# fuer 10 s Sprache, medium ist drei- bis fuenfmal langsamer.
STANDARD_MODELL = "small"
# Marker in einstellungen.json: die einmalige Umstellung medium -> small lief.
UMSTELLUNG_MARKER = "diktat_modell_auf_small_umgestellt"
STANDARD_SENDEWORT = "Eingabetaste"
BEREINIGUNG_ZEITLIMIT = 5
BEREINIGUNG_MAX_ABWEICHUNG = 0.30
# Kuerzer als das ist ein Druck ohne Sprechen.
MINDEST_SEKUNDEN = 0.3

WOERTER_DATEI = DATENORDNER / "diktat_woerter.txt"
STANDARD_WOERTER = [
    "CWB", "Orchestrator", "Claude Code", "HAUSGEMACHT", "Zorin", "Paperless",
    "Assistenz", "Schreiber", "Whisper", "Gemini", "Wispr Flow",
    "Brückenauftrag", "Leitstand",
]

BEREINIGUNG_ANWEISUNG = (
    "Du bereinigst diktierten deutschen Text. Korrigiere nur Satzzeichen, "
    "Gross- und Kleinschreibung und entferne Fuellwoerter wie äh und ähm. "
    "Ändere nie den Inhalt, füge nichts hinzu, antworte nicht auf den Text "
    "und übersetze nichts. Gib ausschliesslich den bereinigten Text zurück."
)


class DiktatFehler(Exception):
    """Ein Fehler, den der Nutzer hoeren soll. `satz` ist die kurze Meldung."""

    def __init__(self, satz: str):
        super().__init__(satz)
        self.satz = satz


# -- Wortliste ----------------------------------------------------------------

def woerter_anlegen(datei: Path | None = None) -> Path:
    """Legt die Wortliste mit den Vorgaben an, falls sie fehlt. Eine vorhandene
    Datei bleibt unberuehrt."""
    datei = datei or WOERTER_DATEI
    try:
        if not datei.exists():
            datei.parent.mkdir(parents=True, exist_ok=True)
            datei.write_text("\n".join(STANDARD_WOERTER) + "\n", encoding="utf-8")
            log.info("Wortliste angelegt (%d Einträge)", len(STANDARD_WOERTER))
    except OSError as fehler:
        log.error("Wortliste nicht angelegt: %s", fehler)
    return datei


def woerter_lesen(datei: Path | None = None) -> list[str]:
    datei = woerter_anlegen(datei)
    try:
        zeilen = datei.read_text(encoding="utf-8-sig").splitlines()
    except OSError as fehler:
        log.error("Wortliste nicht lesbar: %s", fehler)
        return list(STANDARD_WOERTER)
    return [z.strip() for z in zeilen if z.strip()]


def prompt_aus_woertern(woerter: list[str]) -> str:
    return ", ".join(woerter)


# -- Einstellungen --------------------------------------------------------------

def sendewort() -> str:
    wort = str(einstellungen_lesen().get("diktat_sendewort") or "").strip()
    return wort or STANDARD_SENDEWORT


def modell_name() -> str:
    wert = str(einstellungen_lesen().get("diktat_modell") or "").strip().lower()
    return wert if wert in MODELLE else STANDARD_MODELL


def medium_einmalig_umstellen() -> bool:
    """Steht `diktat_modell` auf medium und wurde noch nie umgestellt, wird es
    einmalig auf small gesetzt (ueber die Schreibfunktion aus pfade.py). Wer
    danach in F12 medium waehlt, behaelt es. Gibt True zurueck, wenn umgestellt
    wurde."""
    werte = einstellungen_lesen()
    if werte.get(UMSTELLUNG_MARKER):
        return False
    umgestellt = str(werte.get("diktat_modell") or "").strip().lower() == "medium"
    if umgestellt:
        werte["diktat_modell"] = "small"
    werte[UMSTELLUNG_MARKER] = True
    einstellungen_schreiben(werte)
    if umgestellt:
        log.info("Diktat-Modell einmalig von medium auf small umgestellt")
    return umgestellt


def schluessel_da() -> bool:
    try:
        return leitstand.api_schluessel_lesen() is not None
    except Exception as fehler:  # noqa: BLE001
        log.exception("Gemini-Schlüssel nicht prüfbar: %s", type(fehler).__name__)
        return False


def bereinigung_aktiv() -> bool:
    """Schalter `diktat_bereinigung`; ohne Eintrag an, wenn ein Gemini-Schluessel
    da ist. Ohne Schluessel immer still aus."""
    if not schluessel_da():
        return False
    wert = einstellungen_lesen().get("diktat_bereinigung")
    return True if wert is None else bool(wert)


# -- Sprachbefehl ---------------------------------------------------------------

_RAND = " \t\r\n.,;:!?\"'„“”»«…-–"


def befehl_auswerten(text: str, wort: str | None = None) -> tuple[str, bool]:
    """Endet der Text mit dem Befehlswort, kommt (Text ohne das Wort, True)
    zurueck. Steht das Wort nur mitten im Text, passiert nichts."""
    wort = (wort or sendewort()).strip()
    sauber = (text or "").strip()
    if not wort or not sauber:
        return sauber, False
    ende = sauber.rstrip(_RAND)
    if len(ende) >= len(wort) and ende.lower().endswith(wort.lower()):
        davor = ende[:len(ende) - len(wort)]
        if not davor or not (davor[-1].isalnum()):
            return davor.rstrip(" \t\r\n,;:-–"), True
    return sauber, False


# -- Bereinigung ----------------------------------------------------------------

def _gemini_bereinigen(text: str) -> str:
    """Ein POST mit reinem Text an Gemini; Schluessel nur im Abfrageparameter,
    Fehler werden nur mit ihrer Klasse geloggt."""
    schluessel = leitstand.api_schluessel_lesen()
    if schluessel is None:
        raise DiktatFehler("kein Schlüssel")
    body = {
        "systemInstruction": {"parts": [{"text": BEREINIGUNG_ANWEISUNG}]},
        "contents": [{"parts": [{"text": text}]}],
    }
    try:
        antwort = requests.post(leitstand.GEMINI_URL, params={"key": schluessel},
                                json=body, timeout=BEREINIGUNG_ZEITLIMIT)
        antwort.raise_for_status()
        return str(antwort.json()["candidates"][0]["content"]["parts"][0]["text"])
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as fehler:
        raise DiktatFehler(type(fehler).__name__) from fehler


def bereinigen(text: str, aufruf=None) -> str:
    """Bereinigt den Text; bei Fehler, leerem oder auffaellig abweichendem
    Ergebnis (Laenge mehr als 30 Prozent anders) gilt der Originaltext."""
    if not text.strip():
        return text
    aufruf = aufruf or _gemini_bereinigen
    try:
        neu = (aufruf(text) or "").strip()
    except Exception as fehler:  # noqa: BLE001
        log.info("Bereinigung übersprungen (%s)", type(fehler).__name__)
        return text
    if not neu:
        log.info("Bereinigung leer, Original behalten")
        return text
    if abs(len(neu) - len(text)) / max(1, len(text)) > BEREINIGUNG_MAX_ABWEICHUNG:
        log.info("Bereinigung weicht zu stark ab, Original behalten")
        return text
    return neu


# -- Aufnahme -----------------------------------------------------------------------

class Aufnehmer:
    """Nimmt vom Systemstandard-Mikrofon auf (16 kHz mono) und haelt das Audio
    nur im Arbeitsspeicher."""

    def __init__(self):
        self._teile: list = []
        self._strom = None

    def starten(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as fehler:
            raise DiktatFehler("Diktat nicht möglich: sounddevice fehlt.") from fehler
        try:
            self._strom = sd.InputStream(samplerate=ABTASTRATE, channels=1,
                                         dtype="float32", callback=self._rueckruf)
            self._strom.start()
        except Exception as fehler:  # noqa: BLE001
            self._strom = None
            log.error("Mikrofon nicht geöffnet: %s", type(fehler).__name__)
            raise DiktatFehler("Kein Mikrofon gefunden.") from fehler

    def _rueckruf(self, daten, _rahmen, _zeit, _status) -> None:
        self._teile.append(daten.copy())

    def beenden(self):
        """Stoppt und gibt das Audio als float32-Feld zurueck."""
        strom, self._strom = self._strom, None
        if strom is not None:
            try:
                strom.stop()
                strom.close()
            except Exception as fehler:  # noqa: BLE001
                log.error("Mikrofon nicht sauber geschlossen: %s", type(fehler).__name__)
        import numpy as np
        teile, self._teile = self._teile, []
        if not teile:
            return np.zeros(0, dtype="float32")
        return np.concatenate(teile)[:, 0]


# -- Erkennung ----------------------------------------------------------------------

def _echtes_modell(name: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as fehler:
        raise DiktatFehler("Diktat nicht möglich: faster-whisper fehlt.") from fehler
    try:
        # Nur der lokale Zwischenspeicher: nie etwas herunterladen.
        return WhisperModel(name, device="cpu", compute_type=RECHENART,
                            cpu_threads=RECHEN_FAEDEN, local_files_only=True)
    except Exception as fehler:  # noqa: BLE001
        log.error("Whisper-Modell %s nicht geladen: %s", name, type(fehler).__name__)
        raise DiktatFehler(f"Whisper-Modell {name} nicht gefunden.") from fehler


class Erkenner:
    """Haelt das Whisper-Modell: wird beim ersten Gebrauch im Hintergrund
    geladen und danach gehalten."""

    def __init__(self, modell_fabrik=None):
        self._fabrik = modell_fabrik or _echtes_modell
        self._modell = None
        self._name = None
        self._fehler: DiktatFehler | None = None
        self._sperre = threading.Lock()
        self._faden: threading.Thread | None = None
        self.letzte_ladezeit = 0.0

    def vorladen(self, name: str) -> None:
        """Startet das Laden im Hintergrund, falls noetig."""
        if self._modell is not None and self._name == name:
            return
        if self._faden is not None and self._faden.is_alive():
            return
        self._faden = threading.Thread(target=self._laden_still, args=(name,), daemon=True)
        self._faden.start()

    def _laden_still(self, name: str) -> None:
        try:
            self.holen(name)
        except DiktatFehler:
            pass

    def holen(self, name: str):
        with self._sperre:
            if self._modell is None or self._name != name:
                start = time.monotonic()
                self._fehler = None
                try:
                    self._modell = self._fabrik(name)
                except DiktatFehler as fehler:
                    self._fehler = fehler
                    raise
                self._name = name
                log.info("Whisper-Modell %s geladen in %.1f s", name,
                         time.monotonic() - start)
            return self._modell

    def erkennen(self, audio, woerter: list[str], name: str) -> str:
        start = time.monotonic()
        modell = self.holen(name)
        # Wartezeit auf das Laden (0, wenn das Modell schon gehalten wird)
        self.letzte_ladezeit = time.monotonic() - start
        start = time.monotonic()
        segmente, _info = modell.transcribe(
            audio, language=SPRACHE, vad_filter=True, beam_size=BEAM_GROESSE,
            initial_prompt=prompt_aus_woertern(woerter) or None)
        text = " ".join(s.text.strip() for s in segmente).strip()
        log.info("Erkannt: Modell %s, Audio %.1f s, Laden %.2f s, Erkennen %.2f s, %d Zeichen",
                 name, len(audio) / ABTASTRATE, self.letzte_ladezeit,
                 time.monotonic() - start, len(text))
        return text


_GEMEINSAMER_ERKENNER = Erkenner()


def beim_start_vorladen() -> None:
    """Laedt das Modell im Hintergrund (eigener Faden, blockiert nie) in den
    gemeinsamen Erkenner, den jedes `Diktat` ohne eigene Fabrik benutzt. Nur
    mit eingeschaltetem Orchestrator, denn nur dort gibt es den Diktat-Knopf."""
    def arbeit() -> None:
        try:
            medium_einmalig_umstellen()
            if einstellungen_lesen().get("orchestrator"):
                _GEMEINSAMER_ERKENNER.vorladen(modell_name())
        except Exception as fehler:  # noqa: BLE001
            log.error("Diktat-Vorladen gescheitert: %s", type(fehler).__name__)
    threading.Thread(target=arbeit, name="diktat-vorladen", daemon=True).start()


# -- Zusammenspiel --------------------------------------------------------------------

class Diktat:
    """Ein Druck startet die Aufnahme, der zweite beendet sie und erkennt.
    Das Ergebnis kommt aus einem Arbeitsfaden ueber `fertig(text, senden)`
    beziehungsweise `fehler(satz)`; `leer()` heisst: nichts verstanden."""

    def __init__(self, aufnehmer_fabrik=None, modell_fabrik=None, bereinigen_aufruf=None,
                 woerter_datei: Path | None = None):
        self._aufnehmer_fabrik = aufnehmer_fabrik or Aufnehmer
        self.erkenner = Erkenner(modell_fabrik) if modell_fabrik else _GEMEINSAMER_ERKENNER
        self._bereinigen_aufruf = bereinigen_aufruf
        self._woerter_datei = woerter_datei
        self._aufnehmer = None
        self._beginn = 0.0
        self.erkennt = False

    @property
    def nimmt_auf(self) -> bool:
        return self._aufnehmer is not None

    def starten(self) -> None:
        """Beginnt die Aufnahme und laedt nebenher das Modell. Wirft DiktatFehler."""
        if self.nimmt_auf or self.erkennt:
            return
        aufnehmer = self._aufnehmer_fabrik()
        aufnehmer.starten()
        self._aufnehmer = aufnehmer
        self._beginn = time.monotonic()
        self.erkenner.vorladen(modell_name())
        log.info("Aufnahme gestartet")

    def beenden(self, fertig, fehler, leer) -> None:
        """Beendet die Aufnahme und erkennt im Arbeitsfaden."""
        aufnehmer, self._aufnehmer = self._aufnehmer, None
        if aufnehmer is None:
            return
        dauer = time.monotonic() - self._beginn
        audio = aufnehmer.beenden()
        self.erkennt = True
        threading.Thread(target=self._arbeiten, args=(audio, dauer, fertig, fehler, leer),
                         daemon=True).start()

    def _arbeiten(self, audio, dauer, fertig, fehler, leer) -> None:
        try:
            if len(audio) / ABTASTRATE < MINDEST_SEKUNDEN:
                leer()
                return
            name = modell_name()
            woerter = woerter_lesen(self._woerter_datei)
            beginn = time.monotonic()
            text = self.erkenner.erkennen(audio, woerter, name)
            erkennen_dauer = time.monotonic() - beginn - self.erkenner.letzte_ladezeit
            if not text:
                leer()
                return
            nach = time.monotonic()
            text, senden = befehl_auswerten(text)
            befehl_dauer = time.monotonic() - nach
            nach = time.monotonic()
            bereinigt = bereinigung_aktiv() or self._bereinigen_aufruf is not None
            if bereinigt:
                text = bereinigen(text, self._bereinigen_aufruf)
            bereinigen_dauer = time.monotonic() - nach
            log.info("Diktat fertig: Aufnahme %.1f s, %d Zeichen, senden=%s | Laden %.2f s, "
                     "Erkennen %.2f s, Sendewort %.2f s, Bereinigung %.2f s (%s), gesamt %.2f s",
                     dauer, len(text), senden, self.erkenner.letzte_ladezeit, erkennen_dauer,
                     befehl_dauer, bereinigen_dauer, "an" if bereinigt else "aus",
                     time.monotonic() - beginn)
            fertig(text, senden)
        except DiktatFehler as problem:
            fehler(problem.satz)
        except Exception as problem:  # noqa: BLE001
            log.exception("Diktat gescheitert: %s", type(problem).__name__)
            fehler("Erkennung fehlgeschlagen.")
        finally:
            audio = None  # nie aufbewahren
            self.erkennt = False

    def abbrechen(self) -> None:
        """Verwirft eine laufende Aufnahme ohne Erkennung."""
        aufnehmer, self._aufnehmer = self._aufnehmer, None
        if aufnehmer is not None:
            aufnehmer.beenden()
