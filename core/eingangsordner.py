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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer

try:
    from .pfade import EINGANG_ORDNER, log_einrichten
except ImportError:
    from pfade import EINGANG_ORDNER, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.eingangsordner")

# Abstand zwischen zwei Rückfall-Blicken, wenn das Dateisystem-Ereignis
# ausbleibt (siehe core/ablagewaechter.py, dieselbe Schranke dort).
PRUEF_ABSTAND_MS = 2000

ERLEDIGT_UNTERORDNER = "erledigt"
ABGELEHNT_UNTERORDNER = "abgelehnt"
IN_BEARBEITUNG_UNTERORDNER = ".in_bearbeitung"

QUELLE_LOKAL = "lokal"


def erledigt_ordner() -> Path:
    return EINGANG_ORDNER / ERLEDIGT_UNTERORDNER


def abgelehnt_ordner() -> Path:
    return EINGANG_ORDNER / ABGELEHNT_UNTERORDNER


def in_bearbeitung_ordner() -> Path:
    return EINGANG_ORDNER / IN_BEARBEITUNG_UNTERORDNER


def sicherstellen() -> None:
    """Legt den Eingangsordner und seine drei Unterordner an, falls sie
    fehlen. Schlägt das fehl, läuft CWB ohne Eingangsordner weiter - wie bei
    jedem anderen Schreibfehler in diesem Projekt."""
    for ordner in (EINGANG_ORDNER, erledigt_ordner(), abgelehnt_ordner(), in_bearbeitung_ordner()):
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
    return EingangsAuftrag(quelle=quelle, projekt=projekt, art=art, inhalt=inhalt, datei=pfad)


def admin_gesperrt(art: str, quelle: str) -> bool:
    """#ADMIN# ist über den Eingangsordner immer gesperrt, außer die Quelle
    ist ausdrücklich "lokal" - alles andere (Zeitschaltung, Brücke) könnte
    ohne Roberts unmittelbare Gegenwart auslösen."""
    return art == "admin" and quelle != QUELLE_LOKAL


def passend_fuer_projekt(pfad: Path, projekt_name: str) -> bool:
    """Wahr, wenn diese Datei zu einem Fenster mit offenem Projekt
    `projekt_name` gehört: ihr Feld "projekt" ist leer (dann darf jedes
    Fenster sie holen) oder stimmt ohne Rücksicht auf Gross-/Kleinschreibung
    überein. Ein Lesefehler zählt als Treffer - die eigentliche Fehlermeldung
    entsteht erst in `verarbeiten()`, nach dem Beanspruchen, wo sie auch
    protokolliert und als abgelehnte Datei sichtbar wird."""
    try:
        daten = _daten_lesen(pfad)
    except (OSError, ValueError, EingangsFehler):
        return True
    ziel = str(daten.get("projekt", "")).strip()
    return not ziel or ziel.lower() == projekt_name.strip().lower()


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


def _verschieben(pfad: Path, ziel_ordner: Path, grund: str = "") -> None:
    """Verschiebt die beanspruchte Datei nach erledigt/ oder abgelehnt/. Ein
    Namenskonflikt (zwei Dateien gleichen Namens) bekommt einen Zeitstempel
    angehängt, statt die ältere zu überschreiben. Bei Ablehnung wird der
    Grund in eine gleichnamige .txt-Datei daneben geschrieben."""
    ziel = ziel_ordner / pfad.name
    if ziel.exists():
        zeitstempel = datetime.now().strftime("%Y%m%d_%H%M%S")
        ziel = ziel_ordner / f"{pfad.stem}_{zeitstempel}{pfad.suffix}"
    try:
        pfad.replace(ziel)
    except OSError as fehler:
        log.error("Eingangsdatei nicht verschiebbar: %s -> %s (%s)", pfad, ziel, fehler)
        return
    if grund:
        try:
            ziel.with_suffix(".txt").write_text(grund, encoding="utf-8")
        except OSError as fehler:
            log.warning("Ablehnungsgrund nicht schreibbar für %s: %s", ziel, fehler)


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
    ohne Quelle "lokal" ablehnen, sonst an `ausfuehren(auftrag)` (core/
    fenster.py, _eingang_auftrag) übergeben und danach nach erledigt/
    verschieben.

    `ausfuehren` darf selbst eine Ausnahme werfen - die Datei landet dann
    trotzdem in erledigt/, damit sie nicht bei jedem Blick erneut versucht
    wird; der Fehler steht im Log."""
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
    try:
        ausfuehren(auftrag)
    except AuftragSpaeter as grund:
        log.info("Eingangsdatei zurückgestellt (%s): %s", pfad.name, grund)
        _zurueckstellen(beansprucht)
        return
    except Exception as fehler:  # noqa: BLE001
        log.exception("Auftrag aus dem Eingangsordner gescheitert (%s): %s", pfad.name, fehler)
    _verschieben(beansprucht, erledigt_ordner())


class Eingangswaechter(QObject):
    """Beobachtet den Eingangsordner: Dateisystem-Ereignis sofort, zusätzlich
    ein Blick alle zwei Sekunden als Rückfall (manche Zeitschaltungen und
    Netzlaufwerke lösen kein verlässliches Ereignis aus).

    `markierung_erkennen` zerlegt den Auftragstext (core/fenster.py), `aktiv`
    sagt vor jedem Blick, ob der Wächter eingeschaltet ist, `projekt_name`
    liefert den Namen des in diesem Fenster offenen Projekts (für
    `passend_fuer_projekt`), `ausfuehren` bekommt den fertigen
    `EingangsAuftrag` - wie beim Zwischenablage-Wächter liegt die
    Dublettenprüfung beim Aufrufer."""

    def __init__(self, markierung_erkennen, aktiv, projekt_name, ausfuehren, eltern=None):
        super().__init__(eltern)
        self._markierung_erkennen = markierung_erkennen
        self._aktiv = aktiv
        self._projekt_name = projekt_name
        self._ausfuehren = ausfuehren
        self._beobachter = QFileSystemWatcher(self)
        self._beobachter.directoryChanged.connect(self._nachsehen)
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
        gebraucht, es wird ohnehin der ganze Ordner neu durchsucht."""
        if not self._eingeschaltet():
            return
        try:
            projekt_name = str(self._projekt_name())
        except Exception as fehler:  # noqa: BLE001
            log.exception("Projektname für den Eingangsordner nicht lesbar: %s", fehler)
            return
        for pfad in wartende_dateien():
            if not passend_fuer_projekt(pfad, projekt_name):
                continue
            verarbeiten(pfad, self._markierung_erkennen, self._ausfuehren)
