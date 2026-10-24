"""
CWB - Code Workbench
Waechtertest: Kein Test darf den echten Datenordner veraendern.

Der Stand des Datenordners (Dateiliste und Groessen, nur lesend) wird beim
Import dieses Moduls festgehalten. Beim Sammeln aller Tests (`discover`) werden
alle Module vor dem ersten Lauf importiert, und dieses Modul laeuft dank des
Namens `test_zz_...` als letztes: so liegt der Vergleich vor allen Tests und
nach allen Tests. Bei Einzelaufrufen eines Moduls prueft der Test nur sich selbst.

Dateien, die eine nebenher laufende CWB-Fassung selbst schreibt (Status, Pid,
Ansagen, Gedaechtnis, Landkarte, Logs), sind ausgenommen; sie ersetzen keinen
Testbefund. Alles unter `orchestrator/` wird dagegen ohne Ausnahme verglichen.

Aufruf: python -m unittest discover -s core -p "test_*.py"
"""

import logging
import unittest
from pathlib import Path

try:
    from .pfade import DATENORDNER, log_einrichten
except ImportError:
    from pfade import DATENORDNER, log_einrichten

log_einrichten()
log = logging.getLogger("cwb.test_datenordner_wache")

# Laufende CWB-Fassung schreibt diese selbst - kein Hinweis auf ein Testleck.
AUSNAHMEN_NAMEN = {"status.json", "ansagen.json", "waechter.pid"}
AUSNAHMEN_ORDNER = {"memory_hub", "landkarte", "index"}


def stand_lesen(wurzel: Path = DATENORDNER) -> dict[str, int]:
    """Relativer Pfad -> Groesse. Nur lesend; fehlender Ordner = leerer Stand."""
    stand: dict[str, int] = {}
    try:
        for datei in wurzel.rglob("*"):
            try:
                if not datei.is_file():
                    continue
                relativ = datei.relative_to(wurzel)
                if relativ.parts[0] in AUSNAHMEN_ORDNER or relativ.name in AUSNAHMEN_NAMEN:
                    continue
                if relativ.suffix == ".log" or ".log." in relativ.name:
                    continue
                stand[relativ.as_posix()] = datei.stat().st_size
            except OSError as fehler:
                log.error("Datei im Datenordner nicht lesbar: %s (%s)", datei, fehler)
    except OSError as fehler:
        log.error("Datenordner nicht lesbar: %s (%s)", wurzel, fehler)
    return stand


STAND_VORHER = stand_lesen()


def unterschiede(vorher: dict[str, int], nachher: dict[str, int]) -> list[str]:
    meldungen = []
    for pfad in sorted(set(vorher) | set(nachher)):
        if pfad not in vorher:
            meldungen.append(f"neu: {pfad} ({nachher[pfad]} Byte)")
        elif pfad not in nachher:
            meldungen.append(f"verschwunden: {pfad}")
        elif vorher[pfad] != nachher[pfad]:
            meldungen.append(f"geaendert: {pfad} ({vorher[pfad]} -> {nachher[pfad]} Byte)")
    return meldungen


class DatenordnerWacheTest(unittest.TestCase):
    def test_datenordner_ist_unveraendert(self):
        diff = unterschiede(STAND_VORHER, stand_lesen())
        if diff:
            log.error("Tests haben den echten Datenordner veraendert: %s", diff)
        self.assertEqual(diff, [], "Tests haben den echten Datenordner veraendert")

    def test_unterschiede_erkennt_neu_geaendert_verschwunden(self):
        diff = unterschiede({"a": 1, "b": 2}, {"b": 3, "c": 4})
        self.assertEqual(len(diff), 3)
        self.assertTrue(diff[0].startswith("verschwunden: a"))
        self.assertTrue(diff[1].startswith("geaendert: b"))
        self.assertTrue(diff[2].startswith("neu: c"))


if __name__ == "__main__":
    unittest.main()
