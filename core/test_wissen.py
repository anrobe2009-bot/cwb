"""
CWB - Code Workbench
Unit-Tests fuer core/wissen.py::_code_index_suchen (Block 83, 07.10.2026):
die Suche laeuft seitdem in einem eigenen Unterprozess (index/cli.py --suche)
statt chromadb/pyarrow/torch per `import indexer` in den CWB-Prozess zu
holen - ein nativer Absturz dort hatte CWB zuvor komplett beendet. Hier wird
subprocess.Popen nachgebildet, kein echter Unterprozess gestartet.

Aufruf: python -m unittest core.test_wissen -v
        (oder, aus dem Ordner core/: python test_wissen.py -v)
"""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from . import wissen
except ImportError:
    import wissen


class CodeIndexSuchenTest(unittest.TestCase):
    def setUp(self):
        # cli.py existiert im echten Projekt - fuer die Tests reicht die
        # Pruefung "Datei vorhanden" auf die echte Datei, der eigentliche
        # Aufruf wird unten mit subprocess.Popen gemockt.
        self.projekt = Path(wissen.INDEX_ORDNER).parent

    def test_erfolg_liefert_formatierte_zeilen(self):
        treffer_json = (
            '[{"source": "%s", "zeile_von": 10, "zeile_bis": 12, '
            '"text": "def foo():  pass", "distanz": 0.1}]'
        ) % str(self.projekt / "core" / "beispiel.py").replace("\\", "\\\\")
        prozess = MagicMock()
        prozess.communicate.return_value = (treffer_json, "")
        prozess.returncode = 0
        with patch.object(subprocess, "Popen", return_value=prozess) as popen:
            zeilen, verfuegbar = wissen._code_index_suchen(self.projekt, "foo", 5)
        self.assertTrue(verfuegbar)
        self.assertEqual(len(zeilen), 1)
        self.assertIn("core", zeilen[0])
        self.assertIn("beispiel.py:10-12", zeilen[0])
        # Kein Import von indexer/chromadb im Testprozess - nur ein
        # (gemockter) Unterprozessaufruf.
        befehl = popen.call_args.args[0]
        self.assertIn("--suche", befehl)
        self.assertIn("foo", befehl)

    def test_leeres_ergebnis_bleibt_leer(self):
        prozess = MagicMock()
        prozess.communicate.return_value = ("[]", "")
        prozess.returncode = 0
        with patch.object(subprocess, "Popen", return_value=prozess):
            zeilen, verfuegbar = wissen._code_index_suchen(self.projekt, "nichts", 5)
        self.assertEqual(zeilen, [])
        self.assertTrue(verfuegbar)

    def test_zeitueberschreitung_bricht_ab_ohne_treffer(self):
        prozess = MagicMock()
        prozess.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="cli.py", timeout=15.0),
            ("", ""),
        ]
        with patch.object(subprocess, "Popen", return_value=prozess):
            zeilen, verfuegbar = wissen._code_index_suchen(self.projekt, "frage", 5)
        self.assertEqual(zeilen, [])
        self.assertFalse(verfuegbar)
        prozess.kill.assert_called_once()

    def test_fehlschlag_des_unterprozesses_bleibt_ohne_treffer(self):
        prozess = MagicMock()
        prozess.communicate.return_value = ("", "Traceback: irgendein nativer Fehler")
        prozess.returncode = 1
        with patch.object(subprocess, "Popen", return_value=prozess):
            zeilen, verfuegbar = wissen._code_index_suchen(self.projekt, "frage", 5)
        self.assertEqual(zeilen, [])
        self.assertFalse(verfuegbar)

    def test_kaputtes_json_bleibt_ohne_treffer(self):
        prozess = MagicMock()
        prozess.communicate.return_value = ("nicht-json{{{", "")
        prozess.returncode = 0
        with patch.object(subprocess, "Popen", return_value=prozess):
            zeilen, verfuegbar = wissen._code_index_suchen(self.projekt, "frage", 5)
        self.assertEqual(zeilen, [])
        self.assertFalse(verfuegbar)

    def test_start_schlaegt_fehl_bleibt_ohne_treffer(self):
        with patch.object(subprocess, "Popen", side_effect=OSError("kein Interpreter")):
            zeilen, verfuegbar = wissen._code_index_suchen(self.projekt, "frage", 5)
        self.assertEqual(zeilen, [])
        self.assertFalse(verfuegbar)

    def test_fehlendes_cli_bleibt_ohne_treffer_und_startet_nichts(self):
        with patch.object(Path, "is_file", return_value=False), \
             patch.object(subprocess, "Popen") as popen:
            zeilen, verfuegbar = wissen._code_index_suchen(self.projekt, "frage", 5)
        self.assertEqual(zeilen, [])
        self.assertFalse(verfuegbar)
        popen.assert_not_called()

    def test_keine_vorladefunktionen_mehr_vorhanden(self):
        """Block 83: der In-Prozess-Weg (chromadb/pyarrow/torch im CWB-Prozess)
        ist ersatzlos entfernt, nicht nur umbenannt."""
        self.assertFalse(hasattr(wissen, "_code_index_laden"))
        self.assertFalse(hasattr(wissen, "code_index_vorladen"))
        self.assertFalse(hasattr(wissen, "_code_index_modul"))


if __name__ == "__main__":
    unittest.main()
