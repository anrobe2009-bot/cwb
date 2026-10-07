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
    from .pfade import EINGANG_ORDNER, log_einrichten, zusatzprojekte_lesen
except ImportError:
    from pfade import EINGANG_ORDNER, log_einrichten, zusatzprojekte_lesen

log_einrichten()
log = logging.getLogger("cwb.eingangsordner")

# Abstand zwischen zwei Rückfall-Blicken, wenn das Dateisystem-Ereignis
# ausbleibt (siehe core/ablagewaechter.py, dieselbe Schranke dort).
PRUEF_ABSTAND_MS = 2000

ERLEDIGT_UNTERORDNER = "erledigt"
ABGELEHNT_UNTERORDNER = "abgelehnt"
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


def in_bearbeitung_ordner() -> Path:
    return EINGANG_ORDNER / IN_BEARBEITUNG_UNTERORDNER


def laeuft_ordner() -> Path:
    return EINGANG_ORDNER / LAEUFT_UNTERORDNER


def sicherstellen() -> None:
    """Legt den Eingangsordner und seine vier Unterordner an, falls sie
    fehlen. Schlägt das fehl, läuft CWB ohne Eingangsordner weiter - wie bei
    jedem anderen Schreibfehler in diesem Projekt."""
    for ordner in (EINGANG_ORDNER, erledigt_ordner(), abgelehnt_ordner(),
                   in_bearbeitung_ordner(), laeuft_ordner()):
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
            auftrag_nummer: int | None = None) -> Path:
    """Legt einen Auftrag als Datei in den Eingangsordner, genau wie
    werkzeuge/in_eingang.ps1: erst unter ".json.teil" geschrieben, dann per
    Path.replace() umbenannt - auf demselben Laufwerk atomar, damit der
    Waechter nie eine halb geschriebene Datei zu sehen bekommt. Gedacht fuer
    core/bruecke.py (Vorhaben "Bruecke" Stufe B3): jeder vom Connector-Dienst
    abgeholte Auftrag landet so im selben Eingangsordner wie eine
    Zeitschaltung und durchlaeuft dieselbe Pruefung."""
    sicherstellen()
    daten: dict = {"quelle": quelle, "projekt": projekt, "text": text}
    if auftrag_nummer is not None:
        daten["auftrag_nummer"] = auftrag_nummer
    name = f"eingang_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    teil = EINGANG_ORDNER / f"{name}.teil"
    ziel = EINGANG_ORDNER / name
    teil.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    teil.replace(ziel)
    return ziel


def admin_gesperrt(art: str, quelle: str) -> bool:
    """#ADMIN# ist über den Eingangsordner immer gesperrt, außer die Quelle
    ist ausdrücklich "lokal" - alles andere (Zeitschaltung, Brücke) könnte
    ohne Roberts unmittelbare Gegenwart auslösen."""
    return art == "admin" and quelle != QUELLE_LOKAL


def _projekt_normalisiert(name: str) -> str:
    """Vergleichsform eines Projektnamens fuer den unscharfen Abgleich
    (Block 70, Teil C): klein geschrieben, ohne Leerzeichen, Bindestrich,
    Unterstrich oder Et-Zeichen - "max-friends" und "Max & Friends" werden
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
    "max-friends" fuer "Max und frriends", wenn dort als Alias eingetragen).
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
    if admin_gesperrt(auftrag.art, auftrag.quelle):
        grund = f"#ADMIN# über den Eingangsordner gesperrt (Quelle: {auftrag.quelle})"
        log.warning("Eingangsdatei abgelehnt (%s): %s", pfad.name, grund)
        _verschieben(beansprucht, abgelehnt_ordner(), grund)
        return
    laeuft = _verschieben(beansprucht, laeuft_ordner())
    if laeuft is None:
        return
    auftrag.datei = laeuft
    try:
        ausfuehren(auftrag)
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
    anstoßen, obwohl Robert sie gerade bewusst verworfen hat."""
    if not datei.exists():
        return
    _verschieben(datei, abgelehnt_ordner(), grund)


def wieder_aufnehmen(markierung_erkennen, projekt_name: str, ausfuehren) -> tuple[int, int]:
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

    Älteste zuerst, wie `wartende_dateien()`. Nur Dateien, die zu
    `projekt_name` passen (`passend_fuer_projekt`), werden hier angefasst -
    andere bleiben liegen, bis das richtige Fenster sie holt. Gibt ein Paar
    zurück: Zahl der tatsächlich wieder angenommenen Aufträge, Zahl der
    deswegen verworfenen #RUN#/#ADMIN#-Aufträge."""
    sicherstellen()
    ordner = laeuft_ordner()
    if not ordner.is_dir():
        return 0, 0
    dateien = sorted((p for p in ordner.glob("*.json") if p.is_file()),
                      key=lambda p: p.stat().st_mtime)
    anzahl = 0
    verworfen = 0
    for pfad in dateien:
        if not passend_fuer_projekt(pfad, projekt_name):
            continue
        try:
            auftrag = auftrag_lesen(pfad, markierung_erkennen)
        except EingangsFehler as fehler:
            log.warning("Wieder aufgenommene Datei kaputt (%s): %s", pfad.name, fehler)
            _verschieben(pfad, abgelehnt_ordner(), str(fehler))
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
        anzahl += 1
    return anzahl, verworfen


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
