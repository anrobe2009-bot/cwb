"""
CWB - Code Workbench
Brücke zu claude.ai im Browser (Vorhaben "Brücke", Stufe B3, siehe
wissen/plan_bruecke.md). B1 (Eingangsordner, core/eingangsordner.py) und B2
(Server-Dienst im Projekt mein-projekt, Ordner bruecke/) sind fertig.

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

import datetime
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from PySide6.QtCore import QThread, Signal

try:
    from . import auftragsjournal, eingangsordner
    from .pfade import BRUECKE_ZUGANG_DATEI, log_einrichten
except ImportError:
    import auftragsjournal
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

# Muss zum Server passen (bruecke\server.py im Projekt mein-projekt,
# QUITTUNG_SCHWELLE_SEKUNDEN): liefert er einen Auftrag erneut aus, wenn
# innerhalb dieser Zeit keine Quittung ankam - nur zur Begruendung der
# Logzeilen hier, keine eigene Fristpruefung auf dieser Seite.
QUITTUNG_SCHWELLE_SEKUNDEN = 60

# Berichts-Upload: ein Versuch plus eine Wiederholung nach einigen Sekunden.
BERICHT_VERSUCHE = 2
WIEDERHOLUNG_PAUSE_SEKUNDEN = 5

# Kennzeile als allererste Zeile jedes hochgeladenen Berichts. Muss zum Muster
# in bruecke/server.py (_KENN_MUSTER) passen: dort wird nichts davorgesetzt,
# wenn die erste Zeile schon so aussieht.
KENNZEILE_MUSTER = re.compile(r"^Auftrag \d+ \| Block (?:\d+|-) \| Zeit \S.*$")


def mit_kennzeile(auftrag_nummer, block, text: str, zeit: str | None = None) -> str:
    """Setzt "Auftrag N | Block B | Zeit T" als erste Zeile vor den Bericht.
    Steht dort schon eine passende Kennzeile, bleibt der Text unveraendert.
    B ist "-", wenn die Blocknummer unbekannt ist."""
    erste = (text or "").split("\n", 1)[0].rstrip("\r")
    if KENNZEILE_MUSTER.match(erste):
        return text
    if zeit is None:
        zeit = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    return f"Auftrag {auftrag_nummer} | Block {block if block else '-'} | Zeit {zeit}\n{text}"


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
    """Ein Abholversuch gegen GET .../abholen. Der Server (server.py,
    cwb_abholen) antwortet immer mit {"auftrag": {...}} oder {"auftrag":
    None} - nie mit den Feldern direkt auf oberster Ebene. `None` kommt
    zurueck, wenn gerade kein Auftrag wartet (leere Antwort, "auftrag" fehlt
    oder ist None, oder das verschachtelte Objekt hat kein Feld "text").
    Wirft BrueckenFehler, wenn der Dienst weder lokal noch öffentlich
    erreichbar war."""
    antwort = _anfrage("GET", "/abholen", zugang)
    if antwort.status_code == 204 or not antwort.content:
        return None
    try:
        daten = antwort.json()
    except ValueError:
        log.warning("Antwort von /abholen ist kein gültiges JSON")
        return None
    if not isinstance(daten, dict):
        return None
    auftrag = daten.get("auftrag")
    if not isinstance(auftrag, dict) or not str(auftrag.get("text", "")).strip():
        return None
    return auftrag


def bericht_hochladen(zugang: Zugangsdaten, auftrag_nummer, text: str) -> None:
    """POST .../bericht mit {auftrag_nummer, text}. Wirft BrueckenFehler bei
    Netzfehlern - der Aufrufer entscheidet, ob er das nur loggt oder erneut
    versucht."""
    _anfrage("POST", "/bericht", zugang,
             json={"auftrag_nummer": auftrag_nummer, "text": text})


def nachtbericht_hochladen(zugang: Zugangsdaten, projekt: str, text: str) -> None:
    """POST .../nachtbericht mit {projekt, text} - fuer Leitstand (Block 72,
    core/leitstand.py, wissen/plan_leitstand.md), wenn er anhaelt und
    wissen/nachtbericht.md geschrieben hat, damit die KI im Chat ihn morgens
    holen kann, ohne CWB dafuer erst zu oeffnen. Anders als
    `bericht_hochladen` haengt dieser Bericht an keinem Brücken-Auftrag,
    darum ein eigener Endpunkt. Der Connector-Dienst (Projekt mein-projekt)
    muss ihn dafuer kennen - wirft BrueckenFehler wie jede andere Anfrage,
    wenn er es (noch) nicht tut; der Aufrufer behandelt das als
    best-effort und loggt nur."""
    _anfrage("POST", "/nachtbericht", zugang, json={"projekt": projekt, "text": text})


def protokoll_ablegen(zugang: Zugangsdaten, text: str, art: str = "hinweis",
                      projekt: str | None = None, auftrag_nummer=None,
                      titel: str | None = None) -> int | None:
    """POST .../protokoll: legt einen Eintrag ins Ablagefach der Bruecke
    (bruecke/server.py, protokoll_hochladen). Dort wird nie ueberschrieben, die
    KI im Chat liest ihn ueber protokolle_liste/protokoll_lesen nach. Gibt die
    Protokollnummer zurueck, die der Server vergibt (None, wenn die Antwort
    keine nennt). Wirft BrueckenFehler bei Netzfehlern; der Aufrufer loggt nur."""
    antwort = _anfrage("POST", "/protokoll", zugang, json={
        "text": text, "art": art, "projekt": projekt,
        "auftrag_nummer": auftrag_nummer, "titel": titel})
    try:
        nummer = antwort.json().get("nummer")
    except (ValueError, AttributeError):
        return None
    return nummer if isinstance(nummer, int) else None


def quittieren(zugang: Zugangsdaten, auftrag_nummer) -> None:
    """POST .../quittung mit {auftrag_nummer}. Erst danach gilt ein Auftrag
    beim Server endgueltig als abgeholt (server.py, cwb_quittung) - ohne
    Quittung liefert er ihn nach QUITTUNG_SCHWELLE_SEKUNDEN erneut aus.
    Wirft BrueckenFehler bei Netzfehlern; der Aufrufer entscheidet, ob er das
    nur loggt (die naechste Auslieferung desselben Auftrags wird dann anhand
    seiner auftrag_nummer erkannt und nicht doppelt abgelegt, siehe
    BrueckenFaden._abgelegt)."""
    _anfrage("POST", "/quittung", zugang, json={"auftrag_nummer": auftrag_nummer})


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
        # auftrag_nummern, die in diesem Lauf schon im Eingangsordner liegen
        # (abgelegt oder als #ADMIN# abgelehnt) - schuetzt vor doppelter
        # Ablage, wenn der Server denselben Auftrag erneut ausliefert, weil
        # die Quittung nicht ankam (Netzfehler zwischen Ablage und Quittung).
        self._abgelegt: set[int] = set()

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
        werden.

        Das Feld heisst beim Server "nummer" (server.py, cwb_abholen), nicht
        "auftrag_nummer" - das ist nur der interne Name in core/
        eingangsordner.py."""
        zugang = zugangsdaten_lesen()
        if zugang is None:
            raise BrueckenFehler("keine Zugangsdaten")
        auftrag = abholen(zugang)
        if auftrag is None:
            return
        nummer = auftrag.get("nummer")
        text = str(auftrag.get("text", ""))
        projekt = str(auftrag.get("projekt", ""))
        log.info("Brücke: Auftrag abgeholt (Nummer %s)", nummer)
        if nummer in self._abgelegt:
            auftragsjournal.angenommen("bruecke", nummer=nummer,
                                       detail="erneut zugestellt, nicht erneut abgelegt")
            log.info("Brücke: Auftrag %s erneut zugestellt (Quittung wohl verloren) - "
                      "nicht erneut abgelegt, nur erneut quittiert", nummer)
            self._quittieren_versuchen(zugang, nummer)
            return
        art, _ = self._markierung_erkennen(text)
        auftragsjournal.angenommen("bruecke", nummer=nummer, art=art or "code",
                                   detail=f"projekt={projekt or 'egal'}")
        if art == "admin":
            log.warning("Brücke: #ADMIN#-Auftrag abgelehnt (Auftrag %s)", nummer)
            try:
                bericht_hochladen(
                    zugang, nummer, "Abgelehnt: #ADMIN# ist über die Brücke gesperrt.",
                )
            except BrueckenFehler:
                log.info("Brücke: Ablehnungsbericht nicht hochgeladen (Netzfehler)")
            self._abgelegt.add(nummer)
            self._quittieren_versuchen(zugang, nummer)
            return
        # Block 73: eingangsordner.ablegen() prueft selbst, auf der Platte
        # statt im Speicher, ob diese auftrag_nummer schon einmal abgelegt
        # wurde - auch aus einem frueheren CWB-Lauf oder einem anderen
        # Fenster. `self._abgelegt` bleibt als schnelle Abkuerzung innerhalb
        # dieses Laufs bestehen, ist fuer die eigentliche Dublettensperre
        # aber nicht mehr nötig.
        ziel = eingangsordner.ablegen(QUELLE_BRUECKE, text, projekt=projekt, auftrag_nummer=nummer)
        self._abgelegt.add(nummer)
        if ziel is None:
            log.info("Brücke: Auftrag %s war schon da, übersprungen", nummer)
        else:
            log.info("Brücke: Auftrag abgelegt (Nummer %s, Projekt %r)", nummer, projekt or "egal")
        # Quittung sofort, sobald die Datei sicher im Eingangsordner liegt
        # (oder feststeht, dass sie schon dort liegt) - VOR jeder Ausführung,
        # die asynchron im GUI-Faden passiert. Damit hoert der Server auf,
        # denselben Auftrag erneut auszuliefern, bevor er ueberhaupt
        # begonnen hat.
        self._quittieren_versuchen(zugang, nummer)

    def _quittieren_versuchen(self, zugang: Zugangsdaten, nummer) -> None:
        """Best-effort: scheitert die Quittung an einem Netzfehler, liefert
        der Server denselben Auftrag nach QUITTUNG_SCHWELLE_SEKUNDEN erneut
        aus - `_einen_durchlauf` erkennt ihn dann ueber `self._abgelegt` und
        versucht nur die Quittung erneut, ohne ihn ein zweites Mal
        abzulegen."""
        try:
            quittieren(zugang, nummer)
        except BrueckenFehler:
            log.info("Brücke: Quittung nicht gesendet (Auftrag %s), Server liefert nach "
                      "%d s erneut aus", nummer, QUITTUNG_SCHWELLE_SEKUNDEN)
            return
        log.info("Brücke: Auftrag quittiert (Nummer %s)", nummer)


class ProtokollFaden(QThread):
    """Legt einen CWB-Hinweis, Fehler oder ein Buildergebnis ins Ablagefach
    (protokoll_ablegen) - eigener Thread, ein Netzfehler blockiert die
    Oberflaeche nie. Ein Versuch plus eine Wiederholung; scheitert auch die,
    bleibt es bei einer Logzeile (der Chat-Weg laeuft unabhaengig davon)."""

    fertig_da = Signal(bool)

    def __init__(self, text: str, art: str = "hinweis", projekt: str | None = None,
                 auftrag_nummer=None, titel: str | None = None, eltern=None):
        super().__init__(eltern)
        self._eintrag = dict(text=text, art=art, projekt=projekt,
                             auftrag_nummer=auftrag_nummer, titel=titel)
        self.nummer: int | None = None   # Protokollnummer nach dem Ablegen
        self.danach = None               # Rueckruf(nummer oder None), siehe fenster.py

    def run(self) -> None:
        zugang = zugangsdaten_lesen()
        if zugang is None:
            log.info("Protokoll nicht abgelegt (%s): keine Zugangsdaten", self._eintrag["art"])
            self.fertig_da.emit(False)
            return
        for versuch in range(1, BERICHT_VERSUCHE + 1):
            try:
                self.nummer = protokoll_ablegen(zugang, **self._eintrag)
            except BrueckenFehler:
                log.info("Protokoll nicht abgelegt (%s, Versuch %d): Brücke nicht erreichbar",
                         self._eintrag["art"], versuch)
            except Exception:  # noqa: BLE001
                log.exception("Protokoll nicht abgelegt (%s, Versuch %d)",
                              self._eintrag["art"], versuch)
            else:
                log.info("Protokoll abgelegt (%s, Auftrag %s)", self._eintrag["art"],
                         self._eintrag["auftrag_nummer"])
                self.fertig_da.emit(True)
                return
            if versuch < BERICHT_VERSUCHE:
                self.msleep(WIEDERHOLUNG_PAUSE_SEKUNDEN * 1000)
        self.fertig_da.emit(False)


class NachtberichtFaden(QThread):
    """Laedt einen Nachtbericht hoch (core/leitstand.py, Block 72,
    wissen/plan_leitstand.md) - eigener Thread wie BerichtFaden, ein
    Netzfehler beim Hochladen darf die Oberflaeche nie blockieren. Anders als
    BerichtFaden haengt dieser Bericht an keinem Brücken-Auftrag, sondern am
    Projektnamen (core.bruecke.nachtbericht_hochladen)."""

    fertig_da = Signal(bool)

    def __init__(self, projekt: str, text: str, eltern=None):
        super().__init__(eltern)
        self._projekt = projekt
        self._text = text

    def run(self) -> None:
        zugang = zugangsdaten_lesen()
        if zugang is None:
            log.info("Nachtbericht nicht hochgeladen (Projekt %s): keine Zugangsdaten",
                      self._projekt)
            self.fertig_da.emit(False)
            return
        try:
            nachtbericht_hochladen(zugang, self._projekt, self._text)
        except BrueckenFehler:
            log.info("Nachtbericht nicht hochgeladen (Projekt %s): Brücke nicht erreichbar",
                      self._projekt)
            self.fertig_da.emit(False)
            return
        except Exception:  # noqa: BLE001
            log.exception("Nachtbericht nicht hochgeladen (Projekt %s)", self._projekt)
            self.fertig_da.emit(False)
            return
        log.info("Nachtbericht hochgeladen (Projekt %s)", self._projekt)
        self.fertig_da.emit(True)


class BerichtFaden(QThread):
    """Lädt genau einen Bericht-Text zu einem bereits abgeschlossenen
    Brücken-Auftrag hoch (core/fenster.py, _fertig/_terminal_fertig/
    _bild_fertig). Eigener Thread pro Hochladung, wie BildFaden/TerminalFaden
    - ein Netzfehler beim Hochladen darf die Oberfläche nie blockieren."""

    fertig_da = Signal(bool)

    def __init__(self, auftrag_nummer, text: str, eltern=None, block=None):
        super().__init__(eltern)
        self._auftrag_nummer = auftrag_nummer
        # Kennzeile einmal hier setzen: eine Wiederholung schickt denselben
        # Text mit derselben Zeit.
        self._text = (mit_kennzeile(auftrag_nummer, block, text)
                      if auftrag_nummer is not None else text)

    def run(self) -> None:
        if self._auftrag_nummer is None:
            # Ohne Nummer wuerde der Bericht auf der Bruecke keinem Auftrag
            # zugeordnet und von bericht_holen nie geliefert.
            log.error("Bericht ohne Auftragsnummer nicht hochgeladen")
            auftragsjournal.schreibe("bericht_upload_fehler", "keine Auftragsnummer",
                                     nummer=None, art="code")
            self.fertig_da.emit(False)
            return
        zugang = zugangsdaten_lesen()
        if zugang is None:
            auftragsjournal.schreibe("bericht_upload_fehler", "keine Zugangsdaten",
                                     nummer=self._auftrag_nummer, art="code")
            log.warning("Bericht nicht hochgeladen (Auftrag %s): keine Zugangsdaten",
                        self._auftrag_nummer)
            self.fertig_da.emit(False)
            return
        # Ein Versuch plus eine Wiederholung nach WIEDERHOLUNG_PAUSE_SEKUNDEN:
        # ein kurzer Netzaussetzer soll den Bericht nicht endgueltig verlieren
        # (die KI fragt sonst dauerhaft "noch nicht fertig" ab). Erst der
        # zweite Fehlschlag ist ein ERROR.
        for versuch in range(1, BERICHT_VERSUCHE + 1):
            letzter = versuch == BERICHT_VERSUCHE
            try:
                bericht_hochladen(zugang, self._auftrag_nummer, self._text)
            except BrueckenFehler:
                auftragsjournal.schreibe("bericht_upload_fehler",
                                         f"versuch={versuch} bruecke nicht erreichbar",
                                         nummer=self._auftrag_nummer, art="code")
                if letzter:
                    log.error("Bericht nicht hochgeladen (Auftrag %s): Brücke nicht "
                              "erreichbar, %d Versuche", self._auftrag_nummer, versuch)
                    self.fertig_da.emit(False)
                    return
                log.warning("Bericht nicht hochgeladen (Auftrag %s, Versuch %d): "
                            "Brücke nicht erreichbar, neuer Versuch in %d s",
                            self._auftrag_nummer, versuch, WIEDERHOLUNG_PAUSE_SEKUNDEN)
                self._pausieren()
                continue
            except Exception:  # noqa: BLE001
                auftragsjournal.schreibe("bericht_upload_fehler",
                                         f"versuch={versuch} unerwarteter fehler",
                                         nummer=self._auftrag_nummer, art="code")
                log.exception("Bericht nicht hochgeladen (Auftrag %s, Versuch %d)",
                              self._auftrag_nummer, versuch)
                if letzter:
                    self.fertig_da.emit(False)
                    return
                self._pausieren()
                continue
            auftragsjournal.bericht_hochgeladen(versuch, nummer=self._auftrag_nummer,
                                                art="code")
            log.info("Bericht hochgeladen (Auftrag %s, Versuch %d)",
                     self._auftrag_nummer, versuch)
            self.fertig_da.emit(True)
            return

    def _pausieren(self) -> None:
        self.msleep(WIEDERHOLUNG_PAUSE_SEKUNDEN * 1000)
