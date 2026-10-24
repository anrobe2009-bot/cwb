"""
CWB - Code Workbench
Tests fuer die Suchpflicht (core/sitzung.py, Block C6 Teil B) und die
Erkennung schreibender Befehle (core/sicherheit.py, befehl_schreibt).
Nur Attrappen, keine Fenster, keine echte Sitzung.
"""

import logging
import unittest
from unittest import mock

try:
    from . import sitzung as sitzung_modul
    from .sicherheit import befehl_schreibt
    from .sitzung import MELDUNG_SUCHPFLICHT, NACHSCHLAGE_WERKZEUGE, Sitzung
except ImportError:
    import sitzung as sitzung_modul
    from sicherheit import befehl_schreibt
    from sitzung import MELDUNG_SUCHPFLICHT, NACHSCHLAGE_WERKZEUGE, Sitzung

log = logging.getLogger(__name__)

LESEND = [
    "ls -d core/* 2>/dev/null | grep -i x",
    "head -c3 core/fenster.py | xxd; grep -n foo core/fenster.py",
    "git status --short",
    "find . -name '*.py' -not -path './.git/*' 2>/dev/null",
    "grep -n abc core/sitzung.py 2>&1 | head",
    "cat a.txt >/dev/null",
    "make &>/dev/null",
    "ls > /dev/null 2>&1",
    "ls 1>&2",
    "cd /home/robert; ls bin 2>&1 | head -50; wc -l bin/x.py",
]

SCHREIBEND = [
    "echo hallo > datei.txt",
    "ls 2>/dev/null > liste.txt",
    "grep x a 2>/dev/null >> log.txt",
    "ls > /dev/nullx",
    "cat a > /dev/null/b",
    "cat a 2>&1 | tee ausgabe.txt",
    "sed -i 's/a/b/' x.py",
    "mv a b",
    "cp a b",
    "rm -f a",
    "mkdir neu",
    "touch x",
    "git commit -m x",
    "git add .",
    "git push",
    "git reset --hard",
    "python3 - <<'E'\nopen('x','w').write('y')\nE\ncat a > b",
    "cat > neu.txt <<'E'\ntext\nE",
    "ls 2>/dev/null; rm -f a",
]


class BefehlSchreibtTest(unittest.TestCase):
    def test_lesende_befehle_gelten_nicht_als_schreibend(self):
        for befehl in LESEND:
            with self.subTest(befehl=befehl):
                self.assertIsNone(befehl_schreibt(befehl))

    def test_echte_schreibbefehle_bleiben_schreibend(self):
        for befehl in SCHREIBEND:
            with self.subTest(befehl=befehl):
                self.assertTrue(befehl_schreibt(befehl))


class SuchpflichtTest(unittest.TestCase):
    def _sitzung(self, schlank: bool) -> Sitzung:
        s = Sitzung(mock.MagicMock(), schlank=schlank)
        s._nachschlage_verfuegbar = set(NACHSCHLAGE_WERKZEUGE)
        s._nachschlage_erfuellt = schlank
        return s

    def _verletzt(self, s: Sitzung, name: str, eingabe: dict) -> bool:
        with mock.patch.object(
            sitzung_modul, "einstellungen_lesen",
            return_value={"suchpflicht_vor_aenderungen": True},
        ):
            return s._suchpflicht_verletzt(name, eingabe)

    def test_orchestrator_wird_bei_bash_nie_abgewiesen(self):
        s = self._sitzung(schlank=True)
        for befehl in LESEND + SCHREIBEND:
            with self.subTest(befehl=befehl):
                self.assertFalse(self._verletzt(s, "Bash", {"command": befehl}))
        # auch wenn das Flag verloren ginge, entscheidet die schlanke Sitzung
        s._nachschlage_erfuellt = False
        self.assertFalse(self._verletzt(s, "Bash", {"command": "rm -f a"}))
        self.assertFalse(self._verletzt(s, "Edit", {"file_path": "/x"}))

    def test_claude_code_schreibbefehl_vor_suche_wird_abgewiesen(self):
        s = self._sitzung(schlank=False)
        self.assertTrue(self._verletzt(s, "Bash", {"command": "echo a > b.txt"}))
        self.assertTrue(self._verletzt(s, "Edit", {"file_path": "/x"}))
        antwort = s._suchpflicht_ablehnen("Bash", {"command": "echo a > b.txt"})
        self.assertEqual(antwort.message, MELDUNG_SUCHPFLICHT)

    def test_claude_code_lesebefehl_mit_dev_null_wird_nicht_abgewiesen(self):
        s = self._sitzung(schlank=False)
        for befehl in LESEND:
            with self.subTest(befehl=befehl):
                self.assertFalse(self._verletzt(s, "Bash", {"command": befehl}))

    def test_claude_code_nach_suche_nicht_mehr_abgewiesen(self):
        s = self._sitzung(schlank=False)
        s._nachschlage_erfuellt = True
        self.assertFalse(self._verletzt(s, "Bash", {"command": "rm -f a"}))

    def test_schalter_aus_aendert_nichts(self):
        s = self._sitzung(schlank=False)
        with mock.patch.object(
            sitzung_modul, "einstellungen_lesen",
            return_value={"suchpflicht_vor_aenderungen": False},
        ):
            self.assertFalse(s._suchpflicht_verletzt("Bash", {"command": "rm -f a"}))


if __name__ == "__main__":
    unittest.main()
