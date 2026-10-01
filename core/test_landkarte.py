"""
CWB - Code Workbench
Unit-Tests fuer core/landkarte.py: Zweck-Erkennung je Sprache, Ausschluesse,
Aenderungserkennung und der CLAUDE.md-Hinweis.

Laufen ohne Qt und ohne den echten Datenordner anzufassen:
`landkarte.LANDKARTE_DATEN` wird je Test durch einen temporaeren Ordner
ersetzt.

Aufruf: python -m unittest core.test_landkarte -v
        (oder, aus dem Ordner core/: python test_landkarte.py -v)
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import landkarte
except ImportError:
    import landkarte


class PythonZweckTest(unittest.TestCase):

    def test_text_auf_der_oeffnenden_zeile(self):
        text = '"""Memory Hub - Kernmodul.\n\nWeiterer Text.\n"""\nimport os\n'
        self.assertEqual(landkarte.zweck_ermitteln(text, ".py"), "Memory Hub - Kernmodul.")

    def test_leere_erste_zeile_bleibt_leer(self):
        text = '"""\nCWB - Code Workbench\nPfade: wo die Projekte liegen.\n"""\nimport os\n'
        self.assertEqual(landkarte.zweck_ermitteln(text, ".py"), "")

    def test_ohne_docstring_bleibt_leer(self):
        text = "import os\n\ndef f():\n    pass\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".py"), "")

    def test_syntaxfehler_bleibt_leer(self):
        text = "def f(:\n    pass\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".py"), "")


class KommentarZweckTest(unittest.TestCase):

    def test_kotlin_javadoc_inline(self):
        text = "/** Beschreibung der Datei. */\nclass Foo\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".kt"), "Beschreibung der Datei.")

    def test_java_javadoc_leere_oeffnende_zeile_bleibt_leer(self):
        text = "/**\n * Beschreibung der Datei.\n */\nclass Foo {}\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".java"), "")

    def test_kotlin_zeilenkommentar(self):
        text = "// Kurze Beschreibung\nclass Foo\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".kt"), "Kurze Beschreibung")

    def test_js_block_kommentar(self):
        text = "/* Hilfsfunktionen fuer das Formular. */\nfunction f() {}\n"
        self.assertEqual(
            landkarte.zweck_ermitteln(text, ".js"), "Hilfsfunktionen fuer das Formular."
        )

    def test_ts_ohne_kommentar_bleibt_leer(self):
        text = "export function f() {}\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".ts"), "")

    def test_css_block_kommentar(self):
        text = "/* Globale Abstaende. */\nbody { margin: 0; }\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".css"), "Globale Abstaende.")

    def test_html_kommentar(self):
        text = "<!-- Startseite -->\n<html></html>\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".html"), "Startseite")

    def test_html_mehrzeiliger_kommentar_leere_oeffnende_zeile_bleibt_leer(self):
        text = "<!--\nStartseite\n-->\n<html></html>\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".html"), "")

    def test_ps1_blockkommentar(self):
        text = "<# Legt einen Auftrag ab. #>\nparam()\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".ps1"), "Legt einen Auftrag ab.")

    def test_ps1_zeilenkommentar(self):
        text = "# Kurzbeschreibung\nparam()\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".ps1"), "Kurzbeschreibung")

    def test_bat_rem(self):
        text = "REM Startet den Dienst neu\n@echo off\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".bat"), "Startet den Dienst neu")

    def test_bat_doppelpunkt_kommentar(self):
        text = ":: Startet den Dienst neu\n@echo off\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".bat"), "Startet den Dienst neu")

    def test_bat_bare_rem_ohne_text(self):
        text = "REM\n@echo off\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".bat"), "")

    def test_fuehrende_leerzeilen_werden_uebersprungen(self):
        text = "\n\n// Kommentar nach Leerzeilen\nclass Foo\n"
        self.assertEqual(
            landkarte.zweck_ermitteln(text, ".kt"), "Kommentar nach Leerzeilen"
        )

    def test_erste_inhaltszeile_ohne_kommentar_bleibt_leer(self):
        text = "class Foo\n// Kommentar erst danach\n"
        self.assertEqual(landkarte.zweck_ermitteln(text, ".kt"), "")


class AusgeschlosseneNamenTest(unittest.TestCase):

    def test_python_testdatei(self):
        self.assertTrue(landkarte._ausgeschlossener_name("test_bloecke.py"))
        self.assertTrue(landkarte._ausgeschlossener_name("bloecke_test.py"))
        self.assertFalse(landkarte._ausgeschlossener_name("bloecke.py"))

    def test_js_testdatei(self):
        self.assertTrue(landkarte._ausgeschlossener_name("formular.test.js"))
        self.assertTrue(landkarte._ausgeschlossener_name("formular.spec.tsx"))
        self.assertFalse(landkarte._ausgeschlossener_name("formular.js"))

    def test_java_kotlin_testdatei(self):
        self.assertTrue(landkarte._ausgeschlossener_name("TestFoo.java"))
        self.assertTrue(landkarte._ausgeschlossener_name("FooTest.kt"))
        self.assertTrue(landkarte._ausgeschlossener_name("FooTests.java"))
        self.assertFalse(landkarte._ausgeschlossener_name("Foo.java"))

    def test_bak_vor_und_patch_im_namen(self):
        self.assertTrue(landkarte._ausgeschlossener_name("fenster.py.bak"))
        self.assertTrue(landkarte._ausgeschlossener_name("fenster_vor_block61.py"))
        self.assertTrue(landkarte._ausgeschlossener_name("patch_fenster.py"))

    def test_generierte_dateien(self):
        self.assertTrue(landkarte._ausgeschlossener_name("package-lock.json"))
        self.assertTrue(landkarte._ausgeschlossener_name("bundle.min.js"))
        self.assertTrue(landkarte._ausgeschlossener_name("style.min.css"))

    def test_unauffaelliger_name_bleibt_drin(self):
        self.assertFalse(landkarte._ausgeschlossener_name("fenster.py"))


class ProjektDateienTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.projekt = Path(self._tmp.name)

    def _anlegen(self, relpfad: str, inhalt: str = "x") -> Path:
        pfad = self.projekt / relpfad
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(inhalt, encoding="utf-8")
        return pfad

    def test_ausgeschlossene_ordner_werden_uebersprungen(self):
        self._anlegen("core/fenster.py")
        self._anlegen(".git/hooks/pre-commit.py")
        self._anlegen("node_modules/paket/index.js")
        self._anlegen("build/out.js")
        self._anlegen("__pycache__/fenster.cpython-312.pyc")  # falsche Endung, zaehlt ohnehin nicht
        self._anlegen(".gradle/caches/foo.java")
        self._anlegen(".cwb/protokoll/eins.py")
        gefunden = {
            p.relative_to(self.projekt).as_posix() for p in landkarte.projekt_dateien(self.projekt)
        }
        self.assertEqual(gefunden, {"core/fenster.py"})

    def test_fremde_endung_wird_nicht_aufgenommen(self):
        self._anlegen("daten.json")
        self._anlegen("README.md")
        self.assertEqual(landkarte.projekt_dateien(self.projekt), [])

    def test_testdatei_wird_nicht_aufgenommen(self):
        self._anlegen("core/test_bloecke.py")
        self._anlegen("core/bloecke.py")
        gefunden = [p.name for p in landkarte.projekt_dateien(self.projekt)]
        self.assertEqual(gefunden, ["bloecke.py"])


class LandkarteErzeugenTest(unittest.TestCase):

    def setUp(self):
        self._tmp_daten = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_daten.cleanup)
        self._patch = mock.patch.object(landkarte, "LANDKARTE_DATEN", Path(self._tmp_daten.name))
        self._patch.start()
        self.addCleanup(self._patch.stop)

        self._tmp_projekt = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_projekt.cleanup)
        self.projekt = Path(self._tmp_projekt.name)

    def _anlegen(self, relpfad: str, inhalt: str) -> Path:
        pfad = self.projekt / relpfad
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(inhalt, encoding="utf-8")
        return pfad

    def test_schreibt_landkarte_sortiert_nach_zeilen(self):
        self._anlegen("klein.py", '"""Kurz."""\n')
        self._anlegen("gross.py", '"""Lang."""\n' + "x = 1\n" * 20)
        geschrieben = landkarte.landkarte_erzeugen(self.projekt, "TestProjekt")
        self.assertTrue(geschrieben)
        inhalt = (self.projekt / "wissen" / "landkarte.md").read_text(encoding="utf-8")
        self.assertIn("# Landkarte von TestProjekt", inhalt)
        pos_gross = inhalt.index("gross.py")
        pos_klein = inhalt.index("klein.py")
        self.assertLess(pos_gross, pos_klein)
        self.assertIn("Lang.", inhalt)
        self.assertIn("Kurz.", inhalt)

    def test_zweiter_lauf_ohne_aenderung_schreibt_nicht_neu(self):
        self._anlegen("a.py", '"""Zweck A."""\n')
        self.assertTrue(landkarte.landkarte_erzeugen(self.projekt, "TestProjekt"))
        pfad = self.projekt / "wissen" / "landkarte.md"
        erster_stand = pfad.read_text(encoding="utf-8")
        self.assertFalse(landkarte.landkarte_erzeugen(self.projekt, "TestProjekt"))
        self.assertEqual(pfad.read_text(encoding="utf-8"), erster_stand)

    def test_geaenderte_datei_loest_neuschreiben_aus(self):
        pfad = self._anlegen("a.py", '"""Zweck A."""\n')
        self.assertTrue(landkarte.landkarte_erzeugen(self.projekt, "TestProjekt"))
        pfad.write_text('"""Zweck A geaendert."""\n', encoding="utf-8")
        self.assertTrue(landkarte.landkarte_erzeugen(self.projekt, "TestProjekt"))
        inhalt = (self.projekt / "wissen" / "landkarte.md").read_text(encoding="utf-8")
        self.assertIn("Zweck A geaendert.", inhalt)

    def test_ohne_passende_dateien_entsteht_leere_tabelle_ohne_fehler(self):
        self._anlegen("daten.json", "{}")
        geschrieben = landkarte.landkarte_erzeugen(self.projekt, "TestProjekt")
        self.assertTrue(geschrieben)
        inhalt = (self.projekt / "wissen" / "landkarte.md").read_text(encoding="utf-8")
        self.assertIn("| Datei | Zeilen | Zweck |", inhalt)


class ClaudeMdHinweisTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.projekt = Path(self._tmp.name)

    def test_fehlende_datei_bleibt_unangetastet(self):
        self.assertFalse(landkarte.claude_md_hinweis_sicherstellen(self.projekt))
        self.assertFalse((self.projekt / "CLAUDE.md").exists())

    def test_hinweis_wird_ergaenzt_wenn_er_fehlt(self):
        pfad = self.projekt / "CLAUDE.md"
        pfad.write_text("# Mein Projekt\n\nEtwas Text.\n", encoding="utf-8")
        self.assertTrue(landkarte.claude_md_hinweis_sicherstellen(self.projekt))
        inhalt = pfad.read_text(encoding="utf-8")
        self.assertIn(landkarte.LANDKARTE_HINWEIS, inhalt)
        self.assertIn("Etwas Text.", inhalt)

    def test_vorhandener_hinweis_wird_nicht_verdoppelt(self):
        pfad = self.projekt / "CLAUDE.md"
        pfad.write_text(f"# Mein Projekt\n\n{landkarte.LANDKARTE_HINWEIS}\n", encoding="utf-8")
        self.assertFalse(landkarte.claude_md_hinweis_sicherstellen(self.projekt))
        inhalt = pfad.read_text(encoding="utf-8")
        self.assertEqual(inhalt.count(landkarte.LANDKARTE_HINWEIS), 1)


if __name__ == "__main__":
    unittest.main()
