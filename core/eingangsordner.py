"""
CWB - Code Workbench
Eingangsordner: Aufträge, die nicht über die Zwischenablage hereinkommen,
sondern als Datei abgelegt werden - von einer Zeitschaltung nachts, von Hand
über werkzeuge/in_eingang.ps1, später von der Brücke zu claude.ai im Browser
(Vorhaben "Brücke", siehe wissen/plan_bruecke.md).

Liegt eine Datei *.json mit den Feldern "quelle", "projekt" (optional) und
"text" in %LOCALAPPDATA%\\CWB\\eingang\\ (core/pfade.py, EINGANG_ORDNER),
wird sie genauso behandelt wie ein markierter Block aus der Zwischenablage
(core/ablagewaechter.py): gleiche Markierungserkennung, gleiche Blocknummern-
Prüfung (core/bloecke.py), gleiche Dublettensperre. #ADMIN# ist über den
Eingangsordner gesperrt, außer die Quelle ist ausdrücklich "lokal" - eine
Datei von außen (Zeitschaltung, Brücke) darf nie mit erhöhten Rechten laufen.

Dieses Modul kennt nur Dateien und Text, kein fenster.py: `markierung_erkennen`
und die eigentliche Ausführung kommen als Funktionen von außen herein
(core/fenster.py, Eingangswaechter). So lassen sich Lesen, Prüfen und
Verschieben ohne laufendes Fenster testen (core/test_eingangsordner.py).

Eine Datei wird vor der Verarbeitung per Path.replace() in den Unterordner
".in_bearbeitung" verschoben - unter Windows wie unter Linux ein atomarer
Vorgang. Schlägt er fehl (ein anderer Blick hat die Datei schon geholt, oder
sie ist inzwischen weg), wird sie einfach übersprungen. So kann dieselbe
Datei nie zweimal verarbeitet werden, auch wenn das Dateisystem-Ereignis und
der Zwei-Sekunden-Rückfall fast gleichzeitig anschlagen - und auch wenn
mehrere Projektfenster gleichzeitig offen sind und denselben Ordner
beobachten.

Trägt eine Datei ein Feld "projekt", wird sie nur von dem Fenster
beansprucht, dessen offenes Projekt dazu passt (`passend_fuer_projekt`) -
dieser Blick geschieht VOR dem Beanspruchen, ohne die Datei zu verschieben,
damit sie für das richtige Fenster liegen bleibt. Ohne dieses Feld darf sie
jedes offene Fenster holen.
"""

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer

try:
    from . import auftragsjournal
    from .bloecke import block_erkennen
    from .pfade import EINGANG_ORDNER, log_einrichten, zusatzprojekte_lesen
except ImportError:
    import auftragsjournal
    from bloecke import block_erkennen
    from pfade import EINGANG_ORDNER, log_einrichten, zusatzprojekte_lesen

log_einrichten()
log = logging.getLogger("cwb.eingangsordner")

# Abstand zwischen zwei Rückfall-Blicken, wenn das Dateisystem-Ereignis
# ausbleibt (siehe core/ablagewaechter.py, dieselbe Schranke dort).
PRUEF_ABSTAND_MS = 2000

ERLEDIGT_UNTERORDNER = "erledigt"
ABGELEHNT_UNTERORDNER = "abgelehnt"
VERWORFEN_UNTERORDNER = "verworfen"
# Auftraege, die ein harter Abbruch von CWB mitten im Lauf erwischt hat. Sie
# werden NIE automatisch wiederholt (unterbrochene_markieren); wer sie
# bestellt hat, sieht den Status und bestellt neu.
UNTERBROCHEN_UNTERORDNER = "unterbrochen"
IN_BEARBEITUNG_UNTERORDNER = ".in_bearbeitung"
# Block 70, Teil A: ein angenommener Auftrag steht hier, solange er
# tatsaechlich noch laeuft oder in core/fenster.py wartet - verarbeiten()
# selbst verschiebt NIE nach erledigt/, das tut erst abschliessen(), von
# fenster.py aus aufgerufen, wenn ein Bericht wirklich geschrieben oder
# hochgeladen wurde. Ueberlebt ein Absturz oder ein Projektwechsel, bleibt
# die Datei hier liegen - wieder_aufnehmen() holt sie beim naechsten Start
# dieses Projekts zurueck.
LAEUFT_UNTERORDNER = "laeuft"

QUELLE_LOKAL = "lokal"

# Bleibt eine Datei dauerhaft zurueckgestellt (z.B. weil das Terminal durch
# einen langen Fremdbefehl belegt bleibt), wuerde jeder Blick des Waechters
# (alle PRUEF_ABSTAND_MS) eine neue Logzeile erzeugen - das flutet die
# rotierenden Logdateien binnen einer Stunde und verdraengt die eigentliche
# Fehlerursache, bevor sie gelesen werden kann. Darum wird dieselbe Meldung
# je Datei hoechstens alle MELDUNG_ABSTAND_S erneut geschrieben; der
# eigentliche Versuch (verarbeiten/wieder_aufnehmen) laeuft unveraendert im
# alten Takt weiter.
MELDUNG_ABSTAND_S = 60.0
_letzte_meldung: dict[str, float] = {}

# Haenger vom 07.10.2026 (py-spy-Beleg: haenger/haenger_2026-10-07_10-05-48.txt):
# _beanspruchen (verschiebt aus EINGANG_ORDNER heraus) und _zurueckstellen
# (verschiebt wieder hinein) aendern den von Eingangswaechter beobachteten
# Ordner selbst - jede der beiden Bewegungen loest sofort ein neues
# directoryChanged aus. Bleibt eine Datei dauerhaft zurueckgestellt (Terminal
# belegt durch einen laengeren Fremdbefehl), fuettert das eine Schleife im
# GUI-Faden: Blick -> beanspruchen -> AuftragSpaeter -> zurueckstellen ->
# neues directoryChanged -> naechster Blick, ohne dass die Qt-Ereignis-
# schleife dazwischen zum Zeichnen kommt. Zwei Gegenmassnahmen:
# RUECKSTELL_WARTEZEIT_S laesst eine gerade zurueckgestellte Datei fuer
# diese Zeit unangetastet (kein erneutes Beanspruchen, also auch kein
# weiteres directoryChanged durch diese Datei), NACHSEHEN_ENTPRELL_MS
# fasst mehrere directoryChanged kurz hintereinander zu einem einzigen
# Blick zusammen, statt auf jedes einzelne sofort zu reagieren.
RUECKSTELL_WARTEZEIT_S = 3.0
NACHSEHEN_ENTPRELL_MS = 500
_naechster_versuch: dict[str, float] = {}

# Block 70, Nachbesserung (07.10.2026): zweite Sicherung in wieder_aufnehmen(),
# zusaetzlich dazu, dass core/fenster.py jeden erreichten Auftragsabschluss
# jetzt zuverlaessiger meldet (siehe abschliessen()). Eine Datei in laeuft/,
# die laenger als diese Schwelle dort liegt, gilt als vermutlich schon
# erledigt - ein echter Auftrag braucht dafuer nie so lange, selbst eine
# Kontingent-Pause ueber das Wochenende hinaus meldet sich ueber
# _kontingent_pause_behandeln() in core/fenster.py selbst ab.
WIEDERAUFNAHME_MAX_ALTER_STUNDEN = 12.0


# Ein Auftrag fuer ein Projekt, das es hier nicht gibt, kann nie laufen. Nach
# dieser Zeit im Eingang wird er verworfen (unbekannte_verwerfen).
UNBEKANNT_MAX_ALTER_S = 15 * 60.0


def _zurueckstellung_melden(name: str, grund) -> None:
    jetzt = time.monotonic()
    if jetzt - _letzte_meldung.get(name, 0.0) < MELDUNG_ABSTAND_S:
        return
    _letzte_meldung[name] = jetzt
    log.info("Eingangsdatei zurückgestellt (%s): %s", name, grund)


def _wartezeit_setzen(name: str) -> None:
    _naechster_versuch[name] = time.monotonic() + RUECKSTELL_WARTEZEIT_S


def _wartet_noch(name: str) -> bool:
    return time.monotonic() < _naechster_versuch.get(name, 0.0)


def erledigt_ordner() -> Path:
    return EINGANG_ORDNER / ERLEDIGT_UNTERORDNER


def abgelehnt_ordner() -> Path:
    return EINGANG_ORDNER / ABGELEHNT_UNTERORDNER


def verworfen_ordner() -> Path:
    """Hierher kommen einzeln geloeschte wartende Auftraege (Warteschlangenliste)."""
    return EINGANG_ORDNER / VERWORFEN_UNTERORDNER


def unterbrochen_ordner() -> Path:
    return EINGANG_ORDNER / UNTERBROCHEN_UNTERORDNER


def in_bearbeitung_ordner() -> Path:
    return EINGANG_ORDNER / IN_BEARBEITUNG_UNTERORDNER


def laeuft_ordner() -> Path:
    return EINGANG_ORDNER / LAEUFT_UNTERORDNER


# Block 73: Dublettenschutz fuer Bruecken-Auftraege ueber auftrag_nummer,
# auf der Platte statt im Arbeitsspeicher (core/bruecke.py._abgelegt war rein
# im Speicher und verlor seinen Schutz bei jedem CWB-Neustart). Zu jeder
# auftrag_nummer, die je in den Eingangsordner wollte, liegt hier hoechstens
# eine Markierungsdatei mit dem Namen der Auftragsdatei, die sie zuerst
# beansprucht hat - unabhaengig davon, in welchem der vier Ordner
# (eingang/, .in_bearbeitung/, laeuft/, erledigt/) diese Datei inzwischen
# liegt, denn ihr Name aendert sich beim Verschieben zwischen ihnen nicht
# (siehe _beanspruchen/_verschieben). Das macht die Pruefung einen einzelnen
# Dateizugriff (os.stat/open) statt eine Suche durch womoeglich viele alte
# erledigt/-Dateien, und ueberlebt Neustarts, weil nichts davon im
# Arbeitsspeicher steht. Das exklusive Anlegen (Modus "x") ist unter Windows
# wie unter Linux atomar - legen zwei Fenster gleichzeitig dieselbe Nummer
# an, gewinnt nur eines.
NUMMERN_UNTERORDNER = ".nummern"


def nummern_ordner() -> Path:
    return EINGANG_ORDNER / NUMMERN_UNTERORDNER


def _nummer_datei(auftrag_nummer: int) -> Path:
    return nummern_ordner() / f"{auftrag_nummer}.json"


def _nummer_beanspruchen(auftrag_nummer: int, dateiname: str) -> str | None:
    """Versucht, `auftrag_nummer` exklusiv fuer die Datei `dateiname` zu
    reservieren. War die Nummer noch frei, wird das vermerkt und `None`
    zurückgegeben - der Aufrufer darf fortfahren. War sie schon vergeben,
    kommt der Name der Datei zurück, die sie zuerst bekommen hat; ist das
    `dateiname` selbst, gilt das NICHT als Dublette (derselbe Auftrag wird
    hier nur ein zweites Mal geprüft, z.B. beim Verarbeiten nach dem
    Ablegen)."""
    try:
        nummern_ordner().mkdir(parents=True, exist_ok=True)
    except OSError as fehler:
        log.error("Nummernordner nicht anlegbar: %s", fehler)
        return None
    pfad = _nummer_datei(auftrag_nummer)
    try:
        with pfad.open("x", encoding="utf-8") as datei:
            json.dump({"datei": dateiname}, datei)
        return None
    except FileExistsError:
        pass
    except OSError as fehler:
        log.error("Nummernmarkierung nicht anlegbar (%s): %s", auftrag_nummer, fehler)
        return None
    try:
        vorhanden = json.loads(pfad.read_text(encoding="utf-8"))
        bisheriger_name = str(vorhanden.get("datei", ""))
    except (OSError, ValueError) as fehler:
        log.error("Nummernmarkierung nicht lesbar (%s): %s - wird als Dublette behandelt",
                   auftrag_nummer, fehler)
        return dateiname if dateiname else "unbekannt"
    if bisheriger_name == dateiname:
        return None
    return bisheriger_name


def bericht_vermerken(auftrag_nummer: int) -> None:
    """Merkt auf der Platte, dass zu dieser Bruecken-Nummer ein Bericht
    hochgeladen wurde (core/fenster.py, _bruecke_bericht_fertig). Eine Datei
    in laeuft/ mit so einer Nummer ist danach fertig, auch wenn der Abschluss
    (abschliessen) nie ankam - wieder_aufnehmen() nimmt sie nicht erneut auf."""
    pfad = _nummer_datei(auftrag_nummer)
    try:
        nummern_ordner().mkdir(parents=True, exist_ok=True)
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
            if not isinstance(daten, dict):
                daten = {}
        except (OSError, ValueError):
            daten = {}
        daten["hochgeladen"] = True
        teil = pfad.with_suffix(".teil")
        teil.write_text(json.dumps(daten), encoding="utf-8")
        teil.replace(pfad)
    except OSError as fehler:
        log.warning("Berichtsvermerk nicht schreibbar (%s): %s", auftrag_nummer, fehler)


def bericht_hochgeladen(auftrag_nummer: int) -> bool:
    try:
        daten = json.loads(_nummer_datei(auftrag_nummer).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(daten, dict) and bool(daten.get("hochgeladen"))


# Aufträge, die DIESES Fenster gerade angenommen hat (laufend oder wartend).
# Der Wächter nimmt beim Start schon eine Datei an, bevor wieder_aufnehmen()
# durch laeuft/ geht - ohne diese Liste fände es dieselbe Datei und nähme sie
# ein zweites Mal an. Ein neues Fenster (Projektwechsel, Neustart) beginnt
# mit leerer Liste: was das alte Fenster hielt, ist dort verloren und soll
# gerade wieder aufgenommen werden.
_angenommene_dateien: set[str] = set()
_angenommene_nummern: set[int] = set()


def annahmen_zuruecksetzen() -> None:
    _angenommene_dateien.clear()
    _angenommene_nummern.clear()


def _annahme_merken(auftrag: "EingangsAuftrag") -> None:
    _angenommene_dateien.add(auftrag.datei.name)
    if auftrag.auftrag_nummer is not None:
        _angenommene_nummern.add(auftrag.auftrag_nummer)


def _schon_angenommen(auftrag: "EingangsAuftrag") -> bool:
    return (auftrag.datei.name in _angenommene_dateien
            or (auftrag.auftrag_nummer is not None
                and auftrag.auftrag_nummer in _angenommene_nummern))


def sicherstellen() -> None:
    """Legt den Eingangsordner und seine Unterordner an, falls sie fehlen.
    Schlägt das fehl, läuft CWB ohne Eingangsordner weiter - wie bei jedem
    anderen Schreibfehler in diesem Projekt."""
    for ordner in (EINGANG_ORDNER, erledigt_ordner(), abgelehnt_ordner(), verworfen_ordner(),
                   unterbrochen_ordner(), in_bearbeitung_ordner(), laeuft_ordner(), nummern_ordner()):
        try:
            ordner.mkdir(parents=True, exist_ok=True)
        except OSError as fehler:
            log.error("Eingangsordner nicht anlegbar: %s (%s)", ordner, fehler)


class EingangsFehler(Exception):
    """Eine Datei im Eingangsordner ist kein gültiger Auftrag."""


class AuftragSpaeter(Exception):
    """`ausfuehren` wirft das, wenn eine belegte Ressource (Terminal oder
    Screenshot-Weg) den Auftrag gerade nicht annehmen kann. Die Datei geht
    dadurch nicht verloren: `verarbeiten()` legt sie unverändert in den
    Eingangsordner zurück, statt sie nach erledigt/ zu verschieben - der
    nächste Blick des Wächters (Dateisystem-Ereignis oder spätestens nach
    PRUEF_ABSTAND_MS) versucht sie erneut, in derselben Reihenfolge wie beim
    ersten Mal."""


@dataclass
class EingangsAuftrag:
    quelle: str
    projekt: str
    art: str
    inhalt: str
    datei: Path
    # Nur bei quelle == "bruecke" gesetzt (core/bruecke.py, Vorhaben
    # "Bruecke" Stufe B3): die Nummer, unter der der Connector-Dienst diesen
    # Auftrag fuehrt - nicht zu verwechseln mit der Blocknummer aus dem Text
    # (core/bloecke.py). Wird bis zum Abschluss mitgefuehrt, damit core/
    # fenster.py den Bericht an die richtige Nummer hochladen kann.
    auftrag_nummer: int | None = None


def _daten_lesen(pfad: Path) -> dict:
    # utf-8-sig statt utf-8: PowerShell 5.1 (Set-Content -Encoding UTF8, siehe
    # werkzeuge/in_eingang.ps1) schreibt eine UTF-8-BOM. json.loads lehnt eine
    # BOM als "Unexpected UTF-8 BOM" ab - utf-8-sig liest mit und ohne BOM.
    rohtext = pfad.read_text(encoding="utf-8-sig")
    daten = json.loads(rohtext)
    if not isinstance(daten, dict):
        raise EingangsFehler("JSON ist kein Objekt")
    return daten


def auftrag_lesen(pfad: Path, markierung_erkennen) -> EingangsAuftrag:
    """Liest und zerlegt eine Auftragsdatei. Wirft EingangsFehler bei
    kaputtem JSON oder fehlenden Pflichtfeldern ("quelle", "text")."""
    try:
        daten = _daten_lesen(pfad)
    except OSError as fehler:
        raise EingangsFehler(f"nicht lesbar: {fehler}") from fehler
    except ValueError as fehler:
        raise EingangsFehler(f"kein gültiges JSON: {fehler}") from fehler
    quelle = str(daten.get("quelle", "")).strip()
    text = daten.get("text", "")
    if not quelle:
        raise EingangsFehler("Feld 'quelle' fehlt oder ist leer")
    if not isinstance(text, str) or not text.strip():
        raise EingangsFehler("Feld 'text' fehlt oder ist leer")
    projekt = str(daten.get("projekt", "")).strip()
    art, inhalt = markierung_erkennen(text)
    try:
        auftrag_nummer = int(daten["auftrag_nummer"]) if "auftrag_nummer" in daten else None
    except (TypeError, ValueError):
        auftrag_nummer = None
    return EingangsAuftrag(quelle=quelle, projekt=projekt, art=art, inhalt=inhalt, datei=pfad,
                            auftrag_nummer=auftrag_nummer)


def ablegen(quelle: str, text: str, projekt: str = "",
            auftrag_nummer: int | None = None) -> Path | None:
    """Legt einen Auftrag als Datei in den Eingangsordner, genau wie
    werkzeuge/in_eingang.ps1: erst unter ".json.teil" geschrieben, dann per
    Path.replace() umbenannt - auf demselben Laufwerk atomar, damit der
    Waechter nie eine halb geschriebene Datei zu sehen bekommt. Gedacht fuer
    core/bruecke.py (Vorhaben "Bruecke" Stufe B3): jeder vom Connector-Dienst
    abgeholte Auftrag landet so im selben Eingangsordner wie eine
    Zeitschaltung und durchlaeuft dieselbe Pruefung.

    Ist `auftrag_nummer` gesetzt und schon einmal abgelegt worden (Block 73,
    `_nummer_beanspruchen`) - auch in einem frueheren CWB-Lauf oder aus einem
    anderen Fenster -, wird NICHT erneut abgelegt, sondern `None`
    zurückgegeben. Der Aufrufer (core/bruecke.py) quittiert trotzdem beim
    Server, damit der aufhört, denselben Auftrag erneut auszuliefern."""
    sicherstellen()
    name = f"eingang_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    if auftrag_nummer is not None:
        bisheriger_name = _nummer_beanspruchen(auftrag_nummer, name)
        if bisheriger_name is not None:
            log.info("Auftrag %s war schon da (%s), übersprungen",
                      auftrag_nummer, bisheriger_name)
            return None
    daten: dict = {"quelle": quelle, "projekt": projekt, "text": text}
    if auftrag_nummer is not None:
        daten["auftrag_nummer"] = auftrag_nummer
    teil = EINGANG_ORDNER / f"{name}.teil"
    ziel = EINGANG_ORDNER / name
    teil.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    teil.replace(ziel)
    return ziel


def admin_gesperrt(art: str, quelle: str) -> bool:
    """#ADMIN# ist über den Eingangsordner immer gesperrt, außer die Quelle
    ist ausdrücklich "lokal" - alles andere (Zeitschaltung, Brücke) könnte
    ohne unmittelbare Gegenwart des Nutzers auslösen."""
    return art == "admin" and quelle != QUELLE_LOKAL


def _projekt_normalisiert(name: str) -> str:
    """Vergleichsform eines Projektnamens fuer den unscharfen Abgleich
    (Block 70, Teil C): klein geschrieben, ohne Leerzeichen, Bindestrich,
    Unterstrich oder Et-Zeichen - "mein-projekt" und "Mein & Projekt" werden
    so gleich."""
    return re.sub(r"[\s\-_&]+", "", (name or "").lower())


def _alias_klassen() -> dict[str, str]:
    """Normalisierter Alias/Name -> normalisierter kanonischer Projektname,
    aus dem Feld "aliase" der Zusatzprojekte (core/pfade.py,
    zusatzprojekte_lesen). Ohne Zusatzprojekte oder ohne "aliase" bleibt die
    Abbildung leer - dann zaehlt nur `_projekt_normalisiert` allein. Scheitert
    das Lesen, gilt dasselbe, statt den Abgleich ganz abzubrechen."""
    abbildung: dict[str, str] = {}
    try:
        for zusatz in zusatzprojekte_lesen():
            kanon = _projekt_normalisiert(zusatz.get("name", ""))
            if not kanon:
                continue
            abbildung[kanon] = kanon
            for alias in zusatz.get("aliase", None) or []:
                norm = _projekt_normalisiert(str(alias))
                if norm:
                    abbildung[norm] = kanon
    except Exception as fehler:  # noqa: BLE001
        log.exception("Aliase der Zusatzprojekte nicht lesbar: %s", fehler)
    return abbildung


def projekt_gleichwertig(a: str, b: str) -> bool:
    """Block 70, Teil C: wahr, wenn `a` und `b` denselben Projektnamen
    meinen - ohne Ruecksicht auf Gross-/Kleinschreibung, Bindestrich und
    Leerzeichen, und zusaetzlich ueber die Aliase der Zusatzprojekte (z.B.
    "mein-projekt" fuer "Mein und Projekt", wenn dort als Alias eingetragen).
    Zwei leere Namen gelten NICHT als gleich - das waere kein Treffer,
    sondern schlicht nichts zu vergleichen."""
    na, nb = _projekt_normalisiert(a), _projekt_normalisiert(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    klassen = _alias_klassen()
    return klassen.get(na, na) == klassen.get(nb, nb)


def passend_fuer_projekt(pfad: Path, projekt_name: str) -> bool:
    """Wahr, wenn diese Datei zu einem Fenster mit offenem Projekt
    `projekt_name` gehört: ihr Feld "projekt" ist leer (dann darf jedes
    Fenster sie holen) oder ist zu `projekt_name` gleichwertig
    (`projekt_gleichwertig`, Block 70 Teil C). Ein Lesefehler zählt als
    Treffer - die eigentliche Fehlermeldung entsteht erst in `verarbeiten()`,
    nach dem Beanspruchen, wo sie auch protokolliert und als abgelehnte
    Datei sichtbar wird."""
    try:
        daten = _daten_lesen(pfad)
    except (OSError, ValueError, EingangsFehler):
        return True
    ziel = str(daten.get("projekt", "")).strip()
    return not ziel or projekt_gleichwertig(ziel, projekt_name)


def fremde_projekte(projekt_name: str) -> dict[str, int]:
    """Zaehlt die wartenden Auftragsdateien, deren Feld "projekt" gesetzt ist
    und nicht zu `projekt_name` passt - je genanntem Projekt eine Anzahl, in
    der Reihenfolge ihres ersten Auftretens unter den wartenden Dateien.
    Dateien ohne Feld "projekt" zaehlen nicht mit: sie passen zu jedem
    offenen Fenster (siehe `passend_fuer_projekt`) und warten nicht auf ein
    bestimmtes Projekt. Block 63: Grundlage fuer den Hinweis "Es warten
    Aufträge für Projekt X" und die Kopfzeilen-Anzeige in core/fenster.py."""
    ergebnis: dict[str, int] = {}
    for pfad in wartende_dateien():
        try:
            daten = _daten_lesen(pfad)
        except (OSError, ValueError, EingangsFehler):
            continue
        ziel = str(daten.get("projekt", "")).strip()
        if not ziel or projekt_gleichwertig(ziel, projekt_name):
            continue
        schluessel = next((k for k in ergebnis if projekt_gleichwertig(k, ziel)), ziel)
        ergebnis[schluessel] = ergebnis.get(schluessel, 0) + 1
    return ergebnis


def naechste_fremde_projekt_datei(projekt_name: str) -> str | None:
    """Block 70, Teil C: das Feld "projekt" der aeltesten wartenden Datei,
    die nicht zu `projekt_name` gleichwertig ist (`projekt_gleichwertig`) -
    Grundlage fuer den automatischen Projektwechsel im Leerlauf (core/
    fenster.py, `_auto_projekt_pruefen`). Dateien ohne Feld "projekt" zaehlen
    nicht, sie passen zu jedem offenen Fenster. `None`, wenn keine solche
    Datei wartet."""
    for pfad in wartende_dateien():
        try:
            daten = _daten_lesen(pfad)
        except (OSError, ValueError, EingangsFehler):
            continue
        ziel = str(daten.get("projekt", "")).strip()
        if ziel and not projekt_gleichwertig(ziel, projekt_name):
            return ziel
    return None


def bekannt_unter(namen: list[str]):
    """Baut das `ist_bekannt` fuer unbekannte_verwerfen aus der Liste der
    vorhandenen Projektnamen. Ist die Liste leer (Einstellungen oder Ordner
    gerade nicht lesbar), gilt JEDES Projekt als bekannt: verworfen wird nur,
    was nachweislich zu keinem vorhandenen Projekt gehoert."""
    def ist_bekannt(name: str) -> bool:
        if not namen:
            return True
        return any(projekt_gleichwertig(p, name) for p in namen)
    return ist_bekannt


def unbekannte_verwerfen(ist_bekannt, max_alter_s: float = UNBEKANNT_MAX_ALTER_S,
                         jetzt: float | None = None) -> list[tuple[str, str]]:
    """Verschiebt wartende Dateien, deren Feld "projekt" ein Projekt nennt,
    das `ist_bekannt(name)` nicht kennt und die laenger als `max_alter_s`
    (Aenderungszeit der Datei, bleibt ueber Zurueckstellungen gleich) im
    Eingang liegen, nach abgelehnt/ - mit Grund in der .txt daneben und einer
    Zeile im Auftragsjournal. Dateien ohne Feld "projekt" und solche fuer
    bekannte Projekte bleiben unberuehrt. Gibt (Projektname, Dateiname) je
    verworfener Datei zurueck, damit core/fenster.py es ansagen kann."""
    verworfen: list[tuple[str, str]] = []
    jetzt = time.time() if jetzt is None else jetzt
    for pfad in wartende_dateien():
        try:
            alter = jetzt - pfad.stat().st_mtime
            if alter < max_alter_s:
                continue
            daten = _daten_lesen(pfad)
        except (OSError, ValueError, EingangsFehler):
            continue
        ziel = str(daten.get("projekt", "")).strip()
        if not ziel or ist_bekannt(ziel):
            continue
        sicherstellen()
        beansprucht = _beanspruchen(pfad)
        if beansprucht is None:
            continue
        minuten = int(alter // 60)
        grund = (f"Projekt {ziel} ist unbekannt, Auftrag wartete {minuten} Minuten "
                 "im Eingang und wurde verworfen")
        ziel_pfad = _verschieben(beansprucht, abgelehnt_ordner(), grund)
        if ziel_pfad is None:
            continue
        log.warning("Eingangsdatei verworfen (%s): %s", pfad.name, grund)
        auftragsjournal.schreibe("verworfen", f"datei={pfad.name} {grund}",
                                 nummer=daten.get("auftrag_nummer") or None,
                                 art="eingang", ohne_kontext=True)
        verworfen.append((ziel, pfad.name))
    return verworfen


def wartende_dateien() -> list[Path]:
    """Alle *.json direkt im Eingangsordner, älteste zuerst - so holt ein
    nachts liegen gebliebener Stapel seine Reihenfolge nicht durcheinander."""
    if not EINGANG_ORDNER.is_dir():
        return []
    dateien = [p for p in EINGANG_ORDNER.glob("*.json") if p.is_file()]
    return sorted(dateien, key=lambda p: p.stat().st_mtime)


def _beanspruchen(pfad: Path) -> Path | None:
    """Verschiebt `pfad` atomar nach .in_bearbeitung. `None`, wenn das nicht
    mehr möglich ist (Datei schon von einem anderen Blick geholt oder
    inzwischen gelöscht)."""
    ziel = in_bearbeitung_ordner() / pfad.name
    try:
        pfad.replace(ziel)
        return ziel
    except OSError:
        return None


def _verschieben(pfad: Path, ziel_ordner: Path, grund: str = "") -> Path | None:
    """Verschiebt die beanspruchte Datei nach laeuft/, erledigt/ oder
    abgelehnt/. Ein Namenskonflikt (zwei Dateien gleichen Namens) bekommt
    einen Zeitstempel angehängt, statt die ältere zu überschreiben. Bei
    Ablehnung wird der Grund in eine gleichnamige .txt-Datei daneben
    geschrieben. Gibt den tatsächlichen Zielpfad zurück, `None` bei einem
    Schreibfehler."""
    ziel = ziel_ordner / pfad.name
    if ziel.exists():
        zeitstempel = datetime.now().strftime("%Y%m%d_%H%M%S")
        ziel = ziel_ordner / f"{pfad.stem}_{zeitstempel}{pfad.suffix}"
    try:
        pfad.replace(ziel)
    except OSError as fehler:
        log.error("Eingangsdatei nicht verschiebbar: %s -> %s (%s)", pfad, ziel, fehler)
        return None
    if grund:
        try:
            ziel.with_suffix(".txt").write_text(grund, encoding="utf-8")
        except OSError as fehler:
            log.warning("Ablehnungsgrund nicht schreibbar für %s: %s", ziel, fehler)
    return ziel


def _zurueckstellen(pfad: Path) -> None:
    """Legt eine beanspruchte Datei unverändert in den Eingangsordner
    zurück (AuftragSpaeter). `Path.replace()` ändert den Zeitstempel nicht,
    `wartende_dateien()` sortiert danach - die Ankunftsreihenfolge bleibt
    also über beliebig viele Rückstellungen hinweg erhalten."""
    ziel = EINGANG_ORDNER / pfad.name
    try:
        pfad.replace(ziel)
    except OSError as fehler:
        log.error("Eingangsdatei nicht zurückstellbar: %s -> %s (%s)", pfad, ziel, fehler)


def verarbeiten(pfad: Path, markierung_erkennen, ausfuehren) -> None:
    """Ein Durchlauf für genau eine Datei: beanspruchen, lesen, bei #ADMIN#
    ohne Quelle "lokal" ablehnen, sonst nach laeuft/ verschieben und an
    `ausfuehren(auftrag)` (core/fenster.py, _eingang_auftrag) übergeben.

    Kehrt `ausfuehren` ohne Ausnahme zurück, heißt das nur "angenommen", NICHT
    "fertig" - core/sitzung.py arbeitet den Auftrag meist noch asynchron ab
    (Warteschlange, Arbeitsfaden). Die Datei bleibt darum in laeuft/ liegen;
    erst core/fenster.py ruft nach einem echten Abschluss (Bericht
    geschrieben oder hochgeladen) `abschliessen()` auf. Nur wenn `ausfuehren`
    selbst eine andere Ausnahme als AuftragSpaeter wirft - der Auftrag kam
    also nie bis zur Warteschlange -, landet die Datei sofort in erledigt/,
    damit sie nicht bei jedem Blick erneut versucht wird; der Fehler steht
    im Log. AuftragSpaeter legt die Datei unverändert in den Eingangsordner
    zurück (siehe `_zurueckstellen`)."""
    sicherstellen()
    beansprucht = _beanspruchen(pfad)
    if beansprucht is None:
        return
    try:
        auftrag = auftrag_lesen(beansprucht, markierung_erkennen)
    except EingangsFehler as fehler:
        log.warning("Eingangsdatei abgelehnt (%s): %s", pfad.name, fehler)
        _verschieben(beansprucht, abgelehnt_ordner(), str(fehler))
        return
    if auftrag.auftrag_nummer is not None:
        bisheriger_name = _nummer_beanspruchen(auftrag.auftrag_nummer, beansprucht.name)
        if bisheriger_name is not None:
            grund = f"Auftrag {auftrag.auftrag_nummer} war schon da ({bisheriger_name}), übersprungen"
            log.info("Eingangsdatei abgelehnt (%s): %s", pfad.name, grund)
            auftragsjournal.angenommen("eingang", nummer=auftrag.auftrag_nummer,
                                       art=auftrag.art or "code",
                                       detail="abgelehnt, Nummer schon da")
            _verschieben(beansprucht, abgelehnt_ordner(), grund)
            return
    if admin_gesperrt(auftrag.art, auftrag.quelle):
        grund = f"#ADMIN# über den Eingangsordner gesperrt (Quelle: {auftrag.quelle})"
        log.warning("Eingangsdatei abgelehnt (%s): %s", pfad.name, grund)
        _verschieben(beansprucht, abgelehnt_ordner(), grund)
        return
    laeuft = _verschieben(beansprucht, laeuft_ordner())
    if laeuft is None:
        return
    auftrag.datei = laeuft
    auftragsjournal.angenommen("eingang", nummer=auftrag.auftrag_nummer,
                               art=auftrag.art or "code",
                               detail=f"quelle_datei={auftrag.quelle}")
    try:
        ausfuehren(auftrag)
        _annahme_merken(auftrag)
    except AuftragSpaeter as grund:
        _zurueckstellung_melden(pfad.name, grund)
        _wartezeit_setzen(pfad.name)
        _zurueckstellen(laeuft)
    except Exception as fehler:  # noqa: BLE001
        log.exception("Auftrag aus dem Eingangsordner gescheitert (%s): %s", pfad.name, fehler)
        _verschieben(laeuft, erledigt_ordner())


def abschliessen(datei: Path) -> None:
    """Verschiebt eine Datei aus laeuft/ nach erledigt/ - aufgerufen von
    core/fenster.py (_fertig, _terminal_fertig, _bild_fertig), sobald der
    zugehörige Auftrag tatsächlich abgeschlossen ist (Bericht geschrieben
    oder an die Brücke hochgeladen), egal ob mit Erfolg, Fehler oder nach
    einem Abbruch (F8). Existiert die Datei nicht mehr (schon abgeschlossen,
    oder zwischenzeitlich zurückgestellt), passiert nichts."""
    if not datei.exists():
        return
    _verschieben(datei, erledigt_ordner())


def verwerfen(datei: Path, grund: str) -> None:
    """Verschiebt eine Datei aus laeuft/ nach abgelehnt/, mit `grund` in der
    gleichnamigen .txt-Datei - core/fenster.py ruft das auf, wenn ein
    wartender oder laufender Eingangsordner-Auftrag ausdrücklich verworfen
    wird (F4 Warteschlange leeren, F8 Not-Aus, einzelnes Entfernen in der
    Warteschlangenverwaltung), statt ihn als erledigt zu melden. Ohne diesen
    Aufruf würde `wieder_aufnehmen()` die Datei beim nächsten Start erneut
    anstoßen, obwohl der Nutzer sie gerade bewusst verworfen hat."""
    if not datei.exists():
        return
    nummer = None
    try:
        nummer = _daten_lesen(datei).get("auftrag_nummer") or None
    except (OSError, ValueError, EingangsFehler):
        pass
    ziel = _verschieben(datei, abgelehnt_ordner(), grund)
    # Ein verworfener Auftrag ohne Grund waere ein stiller Datenverlust.
    auftragsjournal.schreibe("verworfen", f"datei={datei.name} {grund}", nummer=nummer,
                             art="eingang", ohne_kontext=True)
    log.warning("Eingangsdatei verworfen (%s): %s -> %s", datei.name, grund,
                ziel if ziel is not None else "NICHT verschoben")


def einzeln_verwerfen(datei: Path, grund: str) -> Path | None:
    """Legt eine einzeln geloeschte Auftragsdatei nach verworfen/ (mit Grund in
    der gleichnamigen .txt). Gibt den Zielpfad zurueck, None ohne Datei/Fehler."""
    if not datei.exists():
        return None
    try:
        verworfen_ordner().mkdir(parents=True, exist_ok=True)
    except OSError as fehler:
        log.error("verworfen/ nicht anlegbar: %s", fehler)
        return None
    return _verschieben(datei, verworfen_ordner(), grund)


def wieder_aufnehmen(markierung_erkennen, projekt_name: str, ausfuehren,
                      bereits_erledigt=None) -> tuple[int, int, int]:
    """Block 70, Teil A: nimmt beim Öffnen eines Projekts alle Aufträge
    wieder auf, die beim letzten Mal nicht fertig wurden - ihre Datei liegt
    noch in laeuft/, weil `verarbeiten()` sie dort erst durch `abschliessen()`
    wegnimmt (core/fenster.py), nicht schon bei der Annahme. Das deckt sowohl
    einen abgestürzten/neu gestarteten Prozess als auch einen Projektwechsel
    (F9) ab: in beiden Fällen geht der im Fenster gemerkte Zustand (Faden,
    Warteschlange) verloren, die Datei in laeuft/ aber nicht.

    #RUN#/#ADMIN# werden hier NICHT erneut angestoßen: anders als ein
    #CODE#-Auftrag (der ohne Wirkung ist, solange er nicht erneut an Claude
    geschickt wird) kann ein Shell-Befehl beim ersten Mal schon gewirkt haben
    oder ein eigenes Programm gestartet haben, das noch läuft - ein
    automatischer zweiter Lauf beim nächsten CWB-Start wäre blind gegenüber
    beidem. Solche Dateien landen stattdessen in abgelehnt/, mit Begründung,
    und müssen von Hand erneut gesendet werden.

    Block 70, Nachbesserung (07.10.2026): zweite Sicherung gegen einen
    Auftrag, der in Wahrheit schon fertig war, aber durch einen Fehler nach
    dem eigentlichen Abschluss nie bei `abschliessen()` ankam (core/fenster.py
    hat dieses Risiko mittlerweile selbst entschärft, hier bleibt die
    Sicherung zusätzlich bestehen). Eine Datei wird NICHT erneut angestoßen,
    sondern mit Begründung verschoben, wenn entweder sie älter als
    `WIEDERAUFNAHME_MAX_ALTER_STUNDEN` ist (landet in abgelehnt/, da unklar)
    oder `bereits_erledigt` (vom Aufrufer übergeben, prüft z.B. einen schon
    gespeicherten Bericht zur Blocknummer) für ihre Blocknummer wahr ist
    (landet in erledigt/, da belegt). Beides steht geloggt, nie stillschweigend.

    Älteste zuerst, wie `wartende_dateien()`. Nur Dateien, die zu
    `projekt_name` passen (`passend_fuer_projekt`), werden hier angefasst -
    andere bleiben liegen, bis das richtige Fenster sie holt. Gibt ein Tripel
    zurück: Zahl der tatsächlich wieder angenommenen Aufträge, Zahl der
    deswegen verworfenen #RUN#/#ADMIN#-Aufträge, Zahl der wegen Alter oder
    vorhandenem Bericht übersprungenen Aufträge."""
    sicherstellen()
    ordner = laeuft_ordner()
    if not ordner.is_dir():
        return 0, 0, 0
    dateien = sorted((p for p in ordner.glob("*.json") if p.is_file()),
                      key=lambda p: p.stat().st_mtime)
    anzahl = 0
    verworfen = 0
    uebersprungen = 0
    for pfad in dateien:
        if not passend_fuer_projekt(pfad, projekt_name):
            continue
        try:
            auftrag = auftrag_lesen(pfad, markierung_erkennen)
        except EingangsFehler as fehler:
            log.warning("Wieder aufgenommene Datei kaputt (%s): %s", pfad.name, fehler)
            _verschieben(pfad, abgelehnt_ordner(), str(fehler))
            continue
        if _schon_angenommen(auftrag):
            log.info("Wieder aufnehmen übersprungen, in diesem Fenster schon angenommen: %s",
                     pfad.name)
            continue
        if auftrag.auftrag_nummer is not None and bericht_hochgeladen(auftrag.auftrag_nummer):
            grund = (f"Zu Auftrag {auftrag.auftrag_nummer} wurde schon ein Bericht "
                      "hochgeladen - kein erneuter Lauf")
            log.warning("Wieder aufgenommene Datei übersprungen (%s): %s", pfad.name, grund)
            _verschieben(pfad, erledigt_ordner(), grund)
            uebersprungen += 1
            continue
        if auftrag.art in ("run", "admin"):
            grund = (f"#{auftrag.art.upper()}# wird nach einem Neustart nicht automatisch "
                     "wiederholt, da er bereits gewirkt oder ein eigenes Programm gestartet "
                     "haben könnte")
            log.warning("Wieder aufgenommener Befehl verworfen (%s): %s", pfad.name, grund)
            _verschieben(pfad, abgelehnt_ordner(), grund)
            verworfen += 1
            continue
        try:
            alter_stunden = (time.time() - pfad.stat().st_mtime) / 3600.0
        except OSError:
            alter_stunden = 0.0
        zu_alt = alter_stunden > WIEDERAUFNAHME_MAX_ALTER_STUNDEN
        block_nummer, _inhalt, _vollstaendig = block_erkennen(auftrag.art, auftrag.inhalt)
        hat_bericht = (
            not zu_alt and block_nummer is not None and bereits_erledigt is not None
            and bool(bereits_erledigt(block_nummer))
        )
        if zu_alt or hat_bericht:
            if hat_bericht:
                grund = (f"Block {block_nummer} hat schon einen gespeicherten Bericht - "
                          "vermutlich schon erledigt, kein erneuter Lauf")
                ziel_ordner = erledigt_ordner()
            else:
                grund = (f"Liegt seit {alter_stunden:.1f} Stunden in laeuft/ (Grenze "
                          f"{WIEDERAUFNAHME_MAX_ALTER_STUNDEN:.0f}) - vermutlich schon erledigt, "
                          "bitte von Hand prüfen und bei Bedarf erneut senden")
                ziel_ordner = abgelehnt_ordner()
            log.warning("Wieder aufgenommene Datei übersprungen (%s): %s", pfad.name, grund)
            _verschieben(pfad, ziel_ordner, grund)
            uebersprungen += 1
            continue
        auftragsjournal.schreibe("wieder_aufgenommen", f"datei={pfad.name}",
                                 nummer=auftrag.auftrag_nummer, art=auftrag.art or "code",
                                 ohne_kontext=True)
        try:
            ausfuehren(auftrag)
        except AuftragSpaeter as grund:
            _zurueckstellung_melden(pfad.name, grund)
            _zurueckstellen(pfad)
            continue
        except Exception as fehler:  # noqa: BLE001
            log.exception("Wieder aufgenommener Auftrag gescheitert (%s): %s",
                           pfad.name, fehler)
            _verschieben(pfad, erledigt_ordner())
            continue
        _annahme_merken(auftrag)
        anzahl += 1
    return anzahl, verworfen, uebersprungen


UNTERBROCHEN_GRUND = ("CWB wurde waehrend dieses Auftrags hart beendet (Absturz). Er wurde "
                      "nicht abgeschlossen und nicht automatisch wiederholt - bitte neu "
                      "bestellen.")


def unterbrochene_markieren(markierung_erkennen, projekt_name: str) -> list[EingangsAuftrag]:
    """Nach einem unsauberen Ende: jede Datei in laeuft/, die zu `projekt_name`
    passt, war beim Absturz angenommen und nicht fertig. Sie wird NICHT
    erneut ausgefuehrt (bekannter Fehler mit doppelt gestarteten Auftraegen),
    sondern nach unterbrochen/ verschoben, mit Grund in einer .txt daneben und
    einer Zeile im Auftragsjournal. Hatte die Bruecken-Nummer schon einen
    hochgeladenen Bericht, ist der Auftrag fertig: er geht nach erledigt/ und
    wird nicht gemeldet, sein Bericht wird nie erneut abgelegt. Gibt die
    wirklich unterbrochenen Auftraege zurueck (Datei zeigt auf den neuen Ort)."""
    sicherstellen()
    ordner = laeuft_ordner()
    if not ordner.is_dir():
        return []
    unterbrochen: list[EingangsAuftrag] = []
    for pfad in sorted((p for p in ordner.glob("*.json") if p.is_file()),
                       key=lambda p: p.stat().st_mtime):
        if not passend_fuer_projekt(pfad, projekt_name):
            continue
        try:
            auftrag = auftrag_lesen(pfad, markierung_erkennen)
        except EingangsFehler as fehler:
            log.warning("Unterbrochene Datei kaputt (%s): %s", pfad.name, fehler)
            _verschieben(pfad, abgelehnt_ordner(), str(fehler))
            continue
        if auftrag.auftrag_nummer is not None and bericht_hochgeladen(auftrag.auftrag_nummer):
            _verschieben(pfad, erledigt_ordner(),
                         "Bericht war schon hochgeladen - kein erneuter Lauf")
            log.info("Nach Absturz: Auftrag %s war fertig (Bericht hochgeladen)",
                     auftrag.auftrag_nummer)
            continue
        ziel = _verschieben(pfad, unterbrochen_ordner(), UNTERBROCHEN_GRUND)
        if ziel is None:
            continue
        auftrag.datei = ziel
        unterbrochen.append(auftrag)
        log.warning("Auftrag als unterbrochen markiert: %s (Nummer %s, Quelle %s)",
                    pfad.name, auftrag.auftrag_nummer, auftrag.quelle)
        auftragsjournal.schreibe("unterbrochen", f"datei={pfad.name} quelle={auftrag.quelle}",
                                 nummer=auftrag.auftrag_nummer, art=auftrag.art or "code",
                                 ohne_kontext=True)
    return unterbrochen


class Eingangswaechter(QObject):
    """Beobachtet den Eingangsordner: Dateisystem-Ereignis sofort, zusätzlich
    ein Blick alle zwei Sekunden als Rückfall (manche Zeitschaltungen und
    Netzlaufwerke lösen kein verlässliches Ereignis aus).

    `markierung_erkennen` zerlegt den Auftragstext (core/fenster.py), `aktiv`
    sagt vor jedem Blick, ob der Wächter eingeschaltet ist, `projekt_name`
    liefert den Namen des in diesem Fenster offenen Projekts (für
    `passend_fuer_projekt`), `ausfuehren` bekommt den fertigen
    `EingangsAuftrag` - wie beim Zwischenablage-Wächter liegt die
    Dublettenprüfung beim Aufrufer. `fremde_melden` (Block 63, optional) wird
    nach jedem Blick mit `fremde_projekte(projekt_name)` aufgerufen - auch mit
    einem leeren dict, damit der Aufrufer eine verschwundene Wartestellung
    ebenso bemerkt wie eine neue."""

    def __init__(self, markierung_erkennen, aktiv, projekt_name, ausfuehren, eltern=None,
                 fremde_melden=None):
        super().__init__(eltern)
        annahmen_zuruecksetzen()
        self._markierung_erkennen = markierung_erkennen
        self._aktiv = aktiv
        self._projekt_name = projekt_name
        self._ausfuehren = ausfuehren
        self._fremde_melden = fremde_melden
        self._laeuft_gerade = False
        self._beobachter = QFileSystemWatcher(self)
        # Entprellung (Haenger vom 07.10.2026): directoryChanged startet nur
        # einen einmaligen Timer neu, statt _nachsehen direkt aufzurufen -
        # mehrere Ereignisse kurz hintereinander (z.B. durch _beanspruchen
        # und _zurueckstellen innerhalb desselben Blicks) ergeben so einen
        # einzigen Blick statt vielen.
        self._entprell_uhr = QTimer(self)
        self._entprell_uhr.setSingleShot(True)
        self._entprell_uhr.setInterval(NACHSEHEN_ENTPRELL_MS)
        self._entprell_uhr.timeout.connect(self._nachsehen)
        self._beobachter.directoryChanged.connect(self._entprell_uhr.start)
        self._uhr = QTimer(self)
        self._uhr.setInterval(PRUEF_ABSTAND_MS)
        self._uhr.timeout.connect(self._nachsehen)

    def starten(self) -> None:
        sicherstellen()
        if str(EINGANG_ORDNER) not in self._beobachter.directories():
            if not self._beobachter.addPath(str(EINGANG_ORDNER)):
                log.warning("Eingangsordner nicht per Dateisystem-Ereignis beobachtbar: %s",
                            EINGANG_ORDNER)
        if not self._uhr.isActive():
            self._uhr.start()
            log.info("Eingangsordner-Wächter läuft: %s, Rückfall alle %d ms",
                      EINGANG_ORDNER, PRUEF_ABSTAND_MS)
        self._nachsehen()

    def anhalten(self) -> None:
        self._uhr.stop()
        self._entprell_uhr.stop()
        if self._beobachter.directories():
            self._beobachter.removePaths(self._beobachter.directories())
        log.info("Eingangsordner-Wächter angehalten")

    def _eingeschaltet(self) -> bool:
        try:
            return bool(self._aktiv())
        except Exception as fehler:  # noqa: BLE001
            log.exception("Einstellung des Eingangsordner-Wächters nicht lesbar: %s", fehler)
            return False

    def _nachsehen(self, *_ignoriert) -> None:
        """Ein Blick in den Eingangsordner. `*_ignoriert` fängt den Pfad auf,
        den QFileSystemWatcher.directoryChanged mitgibt - er wird nicht
        gebraucht, es wird ohnehin der ganze Ordner neu durchsucht.

        Wiedereintrittssperre und die Wartezeit je Datei (`_wartet_noch`)
        gehören zusammen: läuft dieser Blick schon (sollte bei Qt im
        GUI-Faden nicht vorkommen, ist aber billig abzusichern), wird nichts
        doppelt angefasst; eine Datei, die gerade erst zurückgestellt wurde,
        wird nicht sofort wieder beansprucht - genau das fütterte den
        Hänger vom 07.10.2026, da jedes Beanspruchen/Zurückstellen selbst
        ein neues directoryChanged auslöst."""
        if self._laeuft_gerade or not self._eingeschaltet():
            return
        self._laeuft_gerade = True
        try:
            try:
                projekt_name = str(self._projekt_name())
            except Exception as fehler:  # noqa: BLE001
                log.exception("Projektname für den Eingangsordner nicht lesbar: %s", fehler)
                return
            for pfad in wartende_dateien():
                if _wartet_noch(pfad.name):
                    continue
                if not passend_fuer_projekt(pfad, projekt_name):
                    continue
                verarbeiten(pfad, self._markierung_erkennen, self._ausfuehren)

            if self._fremde_melden is not None:
                try:
                    self._fremde_melden(fremde_projekte(projekt_name))
                except Exception as fehler:  # noqa: BLE001
                    log.exception("Fremde Projekte im Eingang nicht gemeldet: %s", fehler)
        finally:
            self._laeuft_gerade = False
