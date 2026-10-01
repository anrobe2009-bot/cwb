"""
CWB - Code Workbench
Brücke zu claude.ai im Browser (Vorhaben "Brücke", Stufe B3, siehe
wissen/plan_bruecke.md). B1 (Eingangsordner, core/eingangsordner.py) und B2
(Server-Dienst im Projekt max-friends, Ordner bruecke/) sind fertig.

Dieses Modul fragt den Connector-Dienst ausgehend ab (GET .../abholen) und
legt jeden abgeholten Auftrag über core.eingangsordner.ablegen() in denselben
Eingangsordner wie eine Zeitschaltung - die vorhandene Verarbeitung
(core/eingangsordner.py, core/fenster.py) greift danach unverändert,
inklusive Blocknummern-Prüfung, Dublettensperre und #ADMIN#-Sperre.

Zusätzlich zur Sperre in core.eingangsordner.admin_gesperrt() wird ein
#ADMIN#-Auftrag schon hier erkannt und abgelehnt, bevor er überhaupt in den
Eingangsordner gelangt: nur hier lässt sich sofort ein Ablehnungsbericht an
den Connector zurückschicken - die spätere Ablehnung im Eingangsordner
schreibt nur eine Logzeile und verschiebt die Datei, sie lädt nichts hoch.

Die Zugangsdaten (Connector-Adresse, PC-Token) liegen in
core.pfade.BRUECKE_ZUGANG_DATEI und werden nie geloggt oder angezeigt - im
Log steht höchstens, dass die Datei fehlt oder unvollständig ist, nie ihr
Inhalt. Auch eine Netzfehlermeldung wird nie geloggt, weil requests sie mit
der vollen Adresse (samt geheimem Pfadteil) füllt - geloggt wird nur die
Fehlerklasse (z.B. "ConnectTimeout").

Abgeholt und hochgeladen wird bevorzugt über http://localhost:55557 (nginx
auf diesem PC, siehe B2), erst bei einem Fehler über die öffentliche Adresse
aus der Zugangsdatei - beide mit demselben Pfad, denn der geheime Pfadteil
steckt in der Connector-Adresse selbst, nicht im Hostnamen.
"""

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from PySide6.QtCore import QThread, Signal

try:
    from . import eingangsordner
    from .pfade import BRUECKE_ZUGANG_DATEI, log_einrichten
except ImportError:
    import eingangsordner
    from pfade import BRUECKE_ZUGANG_DATEI, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.bruecke")

QUELLE_BRUECKE = "bruecke"

# nginx auf diesem PC (B2) - derselbe Pfad wie die oeffentliche Adresse,
# nur ueber localhost statt ueber den Cloudflare Tunnel.
LOKALE_BASIS = "http://localhost:55557"

ZEITLIMIT_SEKUNDEN = 8
ABFRAGE_ABSTAND_MS = 5000
# Fuenf Minuten ohne jeden Erfolg, bevor die einmalige Ansage kommt
# (wissen/plan_bruecke.md, Stufe B3).
AUSFALL_SCHWELLE_SEKUNDEN = 300


class BrueckenFehler(Exception):
    """Weder lokal noch öffentlich erreichbar."""


@dataclass
class Zugangsdaten:
    connector_url: str
    pc_token: str


def zugangsdaten_lesen() -> Zugangsdaten | None:
    """Liest Connector-Adresse und PC-Token aus BRUECKE_ZUGANG_DATEI. `None`,
    wenn die Datei fehlt oder eines der beiden Felder leer ist - der Inhalt
    wird dabei nie geloggt, nur dass das Lesen gelang oder nicht."""
    try:
        zeilen = BRUECKE_ZUGANG_DATEI.read_text(encoding="utf-8-sig").splitlines()
    except OSError as fehler:
        log.info("Brücken-Zugangsdatei nicht lesbar: %s", type(fehler).__name__)
        return None
    werte: dict[str, str] = {}
    for zeile in zeilen:
        schluessel, trenner, wert = zeile.partition("=")
        if trenner:
            werte[schluessel.strip()] = wert.strip()
    connector_url = werte.get("connector_url", "")
    pc_token = werte.get("pc_token", "")
    if not connector_url or not pc_token:
        log.warning("Brücken-Zugangsdatei unvollständig (vorhandene Felder: %s)",
                    sorted(werte.keys()))
        return None
    return Zugangsdaten(connector_url=connector_url, pc_token=pc_token)


def _pfad_ohne_mcp(pfad: str) -> str:
    pfad = pfad.rstrip("/")
    if pfad.lower().endswith("/mcp"):
        pfad = pfad[: -len("/mcp")]
    return pfad


def _basis_urls(connector_url: str) -> tuple[str, str]:
    """(lokale Basis, öffentliche Basis), beide ohne "/mcp" und ohne
    abschließenden Schrägstrich."""
    teile = urlsplit(connector_url)
    pfad = _pfad_ohne_mcp(teile.path)
    oeffentlich = f"{teile.scheme}://{teile.netloc}{pfad}"
    lokal = f"{LOKALE_BASIS}{pfad}"
    return lokal, oeffentlich


def _anfrage(methode: str, endpunkt: str, zugang: Zugangsdaten, **kwargs) -> requests.Response:
    """Versucht `methode` auf `endpunkt` zuerst lokal, bei jedem Fehler
    (Zeitüberschreitung, Verbindungsfehler, Fehlerstatus) danach öffentlich.
    Scheitern beide, steht BrueckenFehler - ihre Meldung ist nur die
    Fehlerklasse, nie der volle requests-Fehlertext (der die Adresse samt
    geheimem Pfadteil enthielte)."""
    lokal, oeffentlich = _basis_urls(zugang.connector_url)
    headers = {"X-PC-Token": zugang.pc_token}
    letzter_fehlertyp = "unbekannt"
    for name, basis in (("lokal", lokal), ("öffentlich", oeffentlich)):
        try:
            antwort = requests.request(
                methode, basis + endpunkt, headers=headers,
                timeout=ZEITLIMIT_SEKUNDEN, **kwargs,
            )
            antwort.raise_for_status()
            return antwort
        except requests.RequestException as fehler:
            letzter_fehlertyp = type(fehler).__name__
            log.info("Brücke %s nicht erreichbar (%s)", name, letzter_fehlertyp)
    raise BrueckenFehler(letzter_fehlertyp)


def abholen(zugang: Zugangsdaten) -> dict | None:
    """Ein Abholversuch gegen GET .../abholen. `None`, wenn gerade kein
    Auftrag wartet (leere Antwort oder kein Feld "text"). Wirft
    BrueckenFehler, wenn der Dienst weder lokal noch öffentlich erreichbar
    war."""
    antwort = _anfrage("GET", "/abholen", zugang)
    if antwort.status_code == 204 or not antwort.content:
        return None
    try:
        daten = antwort.json()
    except ValueError:
        log.warning("Antwort von /abholen ist kein gültiges JSON")
        return None
    if not isinstance(daten, dict) or not str(daten.get("text", "")).strip():
        return None
    return daten


def bericht_hochladen(zugang: Zugangsdaten, auftrag_nummer, text: str) -> None:
    """POST .../bericht mit {auftrag_nummer, text}. Wirft BrueckenFehler bei
    Netzfehlern - der Aufrufer entscheidet, ob er das nur loggt oder erneut
    versucht."""
    _anfrage("POST", "/bericht", zugang,
             json={"auftrag_nummer": auftrag_nummer, "text": text})


class BrueckenFaden(QThread):
    """Fragt den Connector-Dienst alle fünf Sekunden ab, solange der Schalter
    "Brücke" an ist (core/fenster.py, F12 → Verhalten, Umschalt+F8). Läuft in
    einem eigenen Thread und blockiert die Oberfläche nie: jeder
    Abholversuch hat ein kurzes Zeitlimit, `anhalten()` wirkt spätestens nach
    100 ms.

    `markierung_erkennen` kommt wie beim Eingangsordner von außen herein
    (core/fenster.py) - dieses Modul kennt sonst kein fenster.py."""

    nicht_erreichbar = Signal()

    def __init__(self, markierung_erkennen, eltern=None):
        super().__init__(eltern)
        self._markierung_erkennen = markierung_erkennen
        self._laeuft = True
        self._letzter_erfolg = time.monotonic()
        self._ausfall_gemeldet = False

    def anhalten(self) -> None:
        self._laeuft = False

    def _warten(self) -> None:
        """Wartet bis zu ABFRAGE_ABSTAND_MS, bricht aber in 100-ms-Schritten
        sofort ab, sobald `anhalten()` aufgerufen wurde - sonst dauerte ein
        Stopp bis zu fünf Sekunden."""
        for _ in range(max(1, ABFRAGE_ABSTAND_MS // 100)):
            if not self._laeuft:
                return
            self.msleep(100)

    def run(self) -> None:
        log.info("Brücke gestartet")
        while self._laeuft:
            try:
                self._einen_durchlauf()
                self._letzter_erfolg = time.monotonic()
                self._ausfall_gemeldet = False
            except BrueckenFehler:
                self._fehler_merken()
            except Exception:  # noqa: BLE001
                log.exception("Brücke: unerwarteter Fehler beim Abholen")
            self._warten()
        log.info("Brücke angehalten")

    def _fehler_merken(self) -> None:
        if not self._ausfall_gemeldet and (
                time.monotonic() - self._letzter_erfolg > AUSFALL_SCHWELLE_SEKUNDEN):
            self._ausfall_gemeldet = True
            self.nicht_erreichbar.emit()

    def _einen_durchlauf(self) -> None:
        """Eine Abfrage. Fehlt die Zugangsdatei, zählt das wie ein
        Netzfehler (BrueckenFehler) - ohne sie ist die Brücke ohnehin nicht
        erreichbar, und auch das soll nach fünf Minuten einmal angesagt
        werden."""
        zugang = zugangsdaten_lesen()
        if zugang is None:
            raise BrueckenFehler("keine Zugangsdaten")
        auftrag = abholen(zugang)
        if auftrag is None:
            return
        nummer = auftrag.get("auftrag_nummer")
        text = str(auftrag.get("text", ""))
        projekt = str(auftrag.get("projekt", ""))
        art, _ = self._markierung_erkennen(text)
        if art == "admin":
            log.warning("Brücke: #ADMIN#-Auftrag abgelehnt (Auftrag %s)", nummer)
            try:
                bericht_hochladen(
                    zugang, nummer, "Abgelehnt: #ADMIN# ist über die Brücke gesperrt.",
                )
            except BrueckenFehler:
                log.info("Brücke: Ablehnungsbericht nicht hochgeladen (Netzfehler)")
            return
        eingangsordner.ablegen(QUELLE_BRUECKE, text, projekt=projekt, auftrag_nummer=nummer)
        log.info("Brücke: Auftrag abgelegt (Nummer %s, Projekt %r)", nummer, projekt or "egal")


class BerichtFaden(QThread):
    """Lädt genau einen Bericht-Text zu einem bereits abgeschlossenen
    Brücken-Auftrag hoch (core/fenster.py, _fertig/_terminal_fertig/
    _bild_fertig). Eigener Thread pro Hochladung, wie BildFaden/TerminalFaden
    - ein Netzfehler beim Hochladen darf die Oberfläche nie blockieren."""

    fertig_da = Signal(bool)

    def __init__(self, auftrag_nummer, text: str, eltern=None):
        super().__init__(eltern)
        self._auftrag_nummer = auftrag_nummer
        self._text = text

    def run(self) -> None:
        zugang = zugangsdaten_lesen()
        if zugang is None:
            log.warning("Bericht nicht hochgeladen (Auftrag %s): keine Zugangsdaten",
                        self._auftrag_nummer)
            self.fertig_da.emit(False)
            return
        try:
            bericht_hochladen(zugang, self._auftrag_nummer, self._text)
        except BrueckenFehler:
            log.info("Bericht nicht hochgeladen (Auftrag %s): Brücke nicht erreichbar",
                      self._auftrag_nummer)
            self.fertig_da.emit(False)
            return
        except Exception:  # noqa: BLE001
            log.exception("Bericht nicht hochgeladen (Auftrag %s)", self._auftrag_nummer)
            self.fertig_da.emit(False)
            return
        log.info("Bericht hochgeladen (Auftrag %s)", self._auftrag_nummer)
        self.fertig_da.emit(True)
