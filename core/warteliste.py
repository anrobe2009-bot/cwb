"""
CWB - Code Workbench
Warteliste: die Posten der Warteschlangenliste (Umschalt+F4, Kachel
"Warteschlange") samt Vorlesetext. Reines Python, keine Oberflaeche: das
Hauptfenster sammelt die Posten aus seinen Quellen (laufender Auftrag,
Warteschlange, Sparmodus-Rueckstellung, Eingangsordner) und reicht sie hierher.

Jeder Posten hat einen Satz wie "Platz 2, Auftrag 894, Projekt CWB, Code,
Block 870" - derselbe Text steht in der Liste und wird vom Bildschirmleser
gelesen.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

try:
    from . import auftragsjournal
    from . import eingangsordner
except ImportError:
    import auftragsjournal
    import eingangsordner

log = logging.getLogger("cwb.warteliste")

QUELLE_LAUFEND = "laufend"
QUELLE_SCHLANGE = "schlange"
QUELLE_SPARMODUS = "sparmodus"
QUELLE_EINGANG = "eingang"

ARTEN = {"code": "Code", "run": "Run", "admin": "Admin", "bild": "Bild"}


@dataclass
class Posten:
    quelle: str
    projekt: str
    art: str = "Code"
    nummer: int | None = None          # Bruecken-Auftragsnummer
    block: int | None = None
    kennung: str = ""                  # Ersatz, wenn es keine Nummer gibt
    datei: Path | None = None          # Datei in laeuft/ oder eingang/
    ref: object = field(default=None, repr=False)   # Eintrag der Warteschlange
    platz: int = 0

    @property
    def loeschbar(self) -> bool:
        return self.quelle != QUELLE_LAUFEND


def art_name(art: str) -> str:
    return ARTEN.get(str(art).lower(), str(art).capitalize() or "Code")


def vorlesetext(posten: Posten) -> str:
    """z.B. "Platz 2, Auftrag 894, Projekt CWB, Code, Block 870"."""
    teile = [f"Platz {posten.platz}"]
    if posten.quelle == QUELLE_LAUFEND:
        teile.append("läuft gerade")
    if posten.nummer is not None:
        teile.append(f"Auftrag {posten.nummer}")
    elif posten.kennung:
        teile.append(f"Auftrag {posten.kennung}")
    teile.append(f"Projekt {posten.projekt}")
    teile.append(art_name(posten.art))
    if posten.block is not None:
        teile.append(f"Block {posten.block}")
    if posten.quelle == QUELLE_LAUFEND:
        teile.append("nicht löschbar, zum Abbrechen F8")
    return ", ".join(teile)


def nummerieren(posten: list[Posten]) -> list[Posten]:
    for platz, eintrag in enumerate(posten, start=1):
        eintrag.platz = platz
    return posten


def kurzname(posten: Posten) -> str:
    """Fuer die Ansage nach dem Loeschen: "Auftrag 894" bzw. die Kennung."""
    if posten.nummer is not None:
        return f"Auftrag {posten.nummer}"
    if posten.block is not None:
        return f"Block {posten.block}"
    return f"Auftrag {posten.kennung}" if posten.kennung else "Auftrag"


def verwerfen_datei(posten: Posten, grund: str = "Einzeln aus der Warteschlange gelöscht"):
    """Legt die Datei des Postens nach verworfen/ (nie ins Nichts) und schreibt
    eine Zeile ins Auftragsjournal. Ohne Datei (Eintrag aus Eingabefeld oder
    Zwischenablage) steht nur die Journalzeile."""
    ziel = None
    if posten.datei is not None:
        ziel = eingangsordner.einzeln_verwerfen(posten.datei, grund)
    auftragsjournal.schreibe(
        "verworfen",
        f"einzeln geloescht, Platz {posten.platz}"
        + (f", Datei {ziel.name}" if ziel is not None else ""),
        nummer=posten.nummer, block=posten.block, art=str(posten.art).lower(),
        ohne_kontext=True)
    log.info("Wartender Auftrag gelöscht: %s", vorlesetext(posten))
    return ziel
