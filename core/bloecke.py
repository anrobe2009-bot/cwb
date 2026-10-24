"""
CWB - Code Workbench
Blocknummern in Auftraegen aus dem Chat (Block 56).

Ab sofort traegt jeder aus dem Chat kopierte Block eine Nummer: die erste
Inhaltszeile nach der Markierung ist "Block N" (bei #RUN#/#ADMIN# als
PowerShell-Kommentar "# Block N", damit die Zeile - bliebe sie einmal
stehen - gueltiges PowerShell waere), die letzte Zeile ist "Ende Block N"
(bzw. "# Ende Block N"). Bei #BILD# steht nur die Kopfzeile "Block N", ohne
Ende-Zeile - dort gehoert ueblich kein Inhalt dahinter. Fehlt die erste Zeile,
gilt der Block wie bisher ohne jede Pruefung.

Dieses Modul kennt nur Text: Erkennen und Entfernen der Block-Zeilen
(`block_erkennen`) sowie das Merken der zuletzt angenommenen Nummer je
Projekt und Kalendertag fuer die Luecken-Erkennung (`block_zaehler_aktualisieren`).
Ansagen, Vormerken bei Unvollstaendigkeit und die Tastenbelegung (F5/Escape)
liegen in core/fenster.py.
"""

import logging
import re
from datetime import date

try:
    from .pfade import einstellungen_lesen, einstellungen_schreiben, log_einrichten
except ImportError:
    from pfade import einstellungen_lesen, einstellungen_schreiben, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.bloecke")

# Das "#" davor ist optional und wird in beiden Formen erkannt (plain fuer
# #CODE#/#BILD#, PowerShell-Kommentar fuer #RUN#/#ADMIN#) - so muss dieses
# Modul die vier Markierungen nicht einzeln unterscheiden.
_BLOCK_MUSTER = re.compile(r"^#?\s*Block\s+(\d+)\s*$", re.IGNORECASE)
_ENDE_MUSTER = re.compile(r"^#?\s*Ende\s+Block\s+(\d+)\s*$", re.IGNORECASE)

BLOCK_ZAEHLER_SCHLUESSEL = "block_zaehler"

# Block 77, Punkt 1 und 3: "Modell: Opus/Sonnet/Haiku" und "Dringend: ja" -
# eigene Zeilen direkt unter "Block N" bzw. "Projekt: X" (core/zuordnung.py,
# bleibt unberuehrt). Gross-/Kleinschreibung egal, wie bei den Block-Zeilen.
_MODELL_MUSTER = re.compile(r"^Modell:\s*(Opus|Sonnet|Haiku)\s*$", re.IGNORECASE)
_DRINGEND_MUSTER = re.compile(r"^Dringend:\s*ja\s*$", re.IGNORECASE)

# Nur innerhalb der ersten KOPF_ZEILEN_MAX Zeilen (nach block_erkennen, die
# Block-Zeile ist dann schon weg) wird nach "Modell:"/"Dringend:" gesucht -
# weiter unten im eigentlichen Auftragstext koennte ein aehnlicher Satz
# faelschlich als Metadatenzeile gelesen werden.
KOPF_ZEILEN_MAX = 6


def block_erkennen(art: str, inhalt: str) -> tuple[int | None, str, bool]:
    """Zerlegt `inhalt` (bereits ohne die #CODE#/#RUN#/#ADMIN#/#BILD#-Zeile,
    siehe fenster.markierung_erkennen) in (Nummer, Inhalt ohne Block-Zeilen,
    vollstaendig).

    Ist die erste nicht-leere Zeile keine Blockzeile, gilt der Block wie
    bisher ohne Pruefung: Rueckgabe (None, inhalt unveraendert, True).

    Bei "bild" reicht die Kopfzeile allein - es gibt keine Ende-Zeile zu
    suchen, `vollstaendig` ist dann immer True. Sonst gilt der Block nur als
    vollstaendig, wenn die letzte nicht-leere Zeile "Ende Block N" mit
    derselben Nummer ist; andernfalls kommt der (bestmoeglich bereinigte)
    Inhalt mit `vollstaendig=False` zurueck."""
    zeilen = inhalt.split("\n")
    kopf_index = 0
    while kopf_index < len(zeilen) and not zeilen[kopf_index].strip():
        kopf_index += 1
    if kopf_index >= len(zeilen):
        return None, inhalt, True
    treffer = _BLOCK_MUSTER.match(zeilen[kopf_index].strip())
    if not treffer:
        return None, inhalt, True
    nummer = int(treffer.group(1))
    rest = zeilen[kopf_index + 1:]

    if art == "bild":
        return nummer, "\n".join(rest).strip("\n"), True

    ende_index = len(rest) - 1
    while ende_index >= 0 and not rest[ende_index].strip():
        ende_index -= 1
    if ende_index < 0:
        return nummer, "", False
    ende_treffer = _ENDE_MUSTER.match(rest[ende_index].strip())
    if not ende_treffer or int(ende_treffer.group(1)) != nummer:
        return nummer, "\n".join(rest).strip("\n"), False
    bereinigt = rest[:ende_index] + rest[ende_index + 1:]
    return nummer, "\n".join(bereinigt).strip("\n"), True


def kopf_metadaten_entfernen(inhalt: str) -> tuple[str, str | None, bool]:
    """Erkennt und entfernt die Zeilen 'Modell: Opus/Sonnet/Haiku' und
    'Dringend: ja' aus den ersten KOPF_ZEILEN_MAX Zeilen von `inhalt` (Block
    77, Punkte 1 und 3) - unabhaengig von ihrer Reihenfolge und ob
    "Projekt: X" (core/zuordnung.py) dazwischensteht; diese Zeile bleibt
    unangetastet, sie wird fuer Claude Code gebraucht.

    Rueckgabe: (Inhalt ohne die beiden Zeilen, Modellwunsch als CLI-Kurzname
    "opus"/"sonnet"/"haiku" oder None ohne Zeile, Dringend ja/nein)."""
    zeilen = inhalt.split("\n")
    modell_wunsch: str | None = None
    dringend = False
    behalten: list[str] = []
    for index, zeile in enumerate(zeilen):
        if index < KOPF_ZEILEN_MAX:
            treffer = _MODELL_MUSTER.match(zeile.strip())
            if treffer:
                modell_wunsch = treffer.group(1).lower()
                continue
            if _DRINGEND_MUSTER.match(zeile.strip()):
                dringend = True
                continue
        behalten.append(zeile)
    return "\n".join(behalten), modell_wunsch, dringend


def naechste_block_nummer(projekt: str) -> int:
    """Die Nummer, die ein selbst erzeugter Block (core/leitstand.py, Block 72)
    heute fuer `projekt` tragen sollte, ohne den Zaehler zu veraendern - das
    tut erst `block_zaehler_aktualisieren`, wenn der Block tatsaechlich bei
    `core.fenster._block_verarbeiten` ankommt. Ohne gemerkten Eintrag von
    heute: 1."""
    try:
        werte = einstellungen_lesen()
        alle = werte.get(BLOCK_ZAEHLER_SCHLUESSEL)
        eintrag = alle.get(projekt) if isinstance(alle, dict) else None
        if isinstance(eintrag, dict) and eintrag.get("datum") == date.today().isoformat():
            return int(eintrag.get("letzte", 0)) + 1
    except Exception as fehler:  # noqa: BLE001
        log.exception("Naechste Blocknummer nicht ermittelbar (Projekt %s): %s", projekt, fehler)
    return 1


def block_zaehler_aktualisieren(projekt: str, nummer: int) -> str:
    """Merkt `nummer` als zuletzt angenommenen Block fuer `projekt` am
    heutigen Kalendertag in einstellungen.json und gibt den
    Luecken-Ansagesatz zurueck ("" ohne Luecke).

    Eine Nummer groesser als die gemerkte plus eins meldet die Luecke
    ("Achtung, Block 11 fehlt." bzw. "Achtung, Blöcke 9 bis 11 fehlen.").
    Eine kleinere oder gleiche Nummer gilt als Neubeginn der Zaehlung, ohne
    Warnung - ebenso, wenn der letzte Eintrag von einem frueheren
    Kalendertag stammt. Scheitert das Schreiben, laeuft CWB ohne
    Luecken-Erkennung fuer diesen Block weiter."""
    try:
        werte = einstellungen_lesen()
        alle = werte.get(BLOCK_ZAEHLER_SCHLUESSEL)
        if not isinstance(alle, dict):
            alle = {}
        eintrag = alle.get(projekt)
        heute = date.today().isoformat()
        luecke_satz = ""
        if isinstance(eintrag, dict) and eintrag.get("datum") == heute:
            try:
                letzte = int(eintrag.get("letzte"))
            except (TypeError, ValueError):
                letzte = None
            if letzte is not None and nummer > letzte + 1:
                fehlend_von, fehlend_bis = letzte + 1, nummer - 1
                if fehlend_von == fehlend_bis:
                    luecke_satz = f"Achtung, Block {fehlend_von} fehlt."
                else:
                    luecke_satz = f"Achtung, Blöcke {fehlend_von} bis {fehlend_bis} fehlen."
        alle[projekt] = {"datum": heute, "letzte": nummer}
        werte[BLOCK_ZAEHLER_SCHLUESSEL] = alle
        einstellungen_schreiben(werte)
        return luecke_satz
    except Exception as fehler:  # noqa: BLE001
        log.exception(
            "Blockzaehler nicht aktualisiert (Projekt %s, Block %d): %s",
            projekt, nummer, fehler,
        )
        return ""
