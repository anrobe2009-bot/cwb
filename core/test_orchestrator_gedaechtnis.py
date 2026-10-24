"""
CWB - Code Workbench
Tests fuer das Gedaechtnis des Orchestrators (core/orchestrator.py):
Startblock aus offen.md, tagebuch.md und Memory Hub, Laengenbegrenzung,
Schluesselmuster, Verweis auf die neueste Uebergabe, Verlaufskuerzung.

Nur Attrappen in Temp-Ordnern, keine Fenster.
Aufruf: python -m unittest core.test_orchestrator_gedaechtnis -v
"""

import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import orchestrator
except ImportError:
    import orchestrator

log = logging.getLogger("cwb.test_orchestrator_gedaechtnis")


def _hub(pfad: Path, zeilen) -> Path:
    db = pfad / "memory.db"
    with sqlite3.connect(db) as v:
        v.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY, project TEXT, category TEXT, "
                  "content TEXT, source TEXT DEFAULT 'x', pinned INTEGER DEFAULT 0, "
                  "created TEXT DEFAULT '2026-01-01', updated TEXT DEFAULT '2026-01-01')")
        for projekt, kategorie, inhalt in zeilen:
            v.execute("INSERT INTO memories(project, category, content) VALUES (?,?,?)",
                      (projekt, kategorie, inhalt))
    return db


class _Basis(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.ordner = Path(self._t.name)
        (self.ordner / "wissen").mkdir()

    def block(self, hub=None, **kw):
        return orchestrator.startblock_bauen(self.ordner, "CWB", hub or self.ordner / "fehlt.db", **kw)


class StartblockTest(_Basis):
    def test_mehrere_quellen(self):
        (self.ordner / "wissen" / "offen.md").write_text("- Alter Punkt A\n- Punkt B\n", encoding="utf-8")
        (self.ordner / "wissen" / "tagebuch.md").write_text(
            "- 2026-10-01  Erster Eintrag\n- 2026-10-02  Zweiter Eintrag\n", encoding="utf-8")
        (self.ordner / "wissen" / "uebergaben").mkdir()
        (self.ordner / "wissen" / "uebergaben" / "uebergabe_2026-10-20_0900.md").write_text("x")
        (self.ordner / "wissen" / "uebergaben" / "uebergabe_2026-10-22_1530.md").write_text("x")
        hub = _hub(self.ordner, [("CWB", "Notiz", "Eine Notiz"),
                                 ("global", "Regel", "Immer duzen"),
                                 ("andere", "Regel", "Fremdes Projekt")])
        text = self.block(hub)
        for stueck in ("Gedächtnis (keine Aufgabe", "Punkt B", "Zweiter Eintrag",
                       "uebergabe_2026-10-22_1530.md", "15:30 Uhr", "Immer duzen", "Eine Notiz"):
            self.assertIn(stueck, text)
        self.assertNotIn("2026-10-20_0900", text)
        self.assertNotIn("Fremdes Projekt", text)
        self.assertLess(text.index("Immer duzen"), text.index("Eine Notiz"))

    def test_leere_quellen(self):
        self.assertEqual(self.block(), "")
        hub = _hub(self.ordner, [])
        self.assertEqual(self.block(hub), "")

    def test_laengenbegrenzung(self):
        (self.ordner / "wissen" / "offen.md").write_text(
            "".join(f"- Punkt {i} " + "x" * 600 + "\n" for i in range(50)), encoding="utf-8")
        hub = _hub(self.ordner, [("CWB", "Regel", "R" * 900) for _ in range(40)])
        text = self.block(hub)
        self.assertLessEqual(len(text), orchestrator.STARTBLOCK_MAX_ZEICHEN)
        for zeile in text.splitlines():
            self.assertLessEqual(len(zeile), orchestrator.STARTBLOCK_ZEILE_MAX + 20)

    def test_keine_schluesselmuster(self):
        boese = ["Nutze sk-abcdef123456 hier", "AIzaSyABCDEFG123 im Code", "Header Bearer abc.def",
                 "API_KEY=geheim", "GITHUB_TOKEN=xyz", "PASSWORD=hunter2"]
        (self.ordner / "wissen" / "offen.md").write_text(
            "".join(f"- {b}\n" for b in boese) + "- Harmloser Punkt\n", encoding="utf-8")
        hub = _hub(self.ordner, [("CWB", "Notiz", b) for b in boese] + [("CWB", "Regel", "Gut")])
        text = self.block(hub)
        for b in boese:
            self.assertNotIn(b, text)
        for muster in ("sk-", "AIza", "Bearer", "KEY=", "TOKEN=", "PASSWORD="):
            self.assertNotIn(muster, text)
        self.assertIn("Harmloser Punkt", text)
        self.assertIn("Gut", text)

    def test_fehlendes_uebergabenverzeichnis(self):
        (self.ordner / "wissen" / "offen.md").write_text("- Nur ein Punkt\n", encoding="utf-8")
        text = self.block()
        self.assertIn("Nur ein Punkt", text)
        self.assertNotIn("Letzte Übergabe", text)
        self.assertIsNone(orchestrator.neueste_uebergabe(self.ordner / "gibt_es_nicht"))

    def test_kaputter_hub_wirft_nicht(self):
        kaputt = self.ordner / "memory.db"
        kaputt.write_text("kein sqlite")
        (self.ordner / "wissen" / "offen.md").write_text("- Punkt\n", encoding="utf-8")
        self.assertIn("Punkt", self.block(kaputt))


class VerlaufTest(_Basis):
    def test_ueber_1_mb_bleiben_nur_die_letzten_eintraege(self):
        with mock.patch.object(orchestrator, "ORCH_ORDNER", self.ordner):
            datei = orchestrator.verlauf_datei()
            zeile = "[2026-01-01 00:00:00] antwort: " + "x" * 1000 + "\n"
            datei.write_text(zeile * 1100, encoding="utf-8")
            self.assertGreater(datei.stat().st_size, orchestrator.VERLAUF_MAX_BYTES)
            self.assertTrue(orchestrator.verlauf_anhaengen("antwort", "NEUESTE"))
            neu = datei.read_text(encoding="utf-8")
            self.assertLessEqual(len(neu.splitlines()), orchestrator.VERLAUF_BEHALTEN)
            self.assertIn("NEUESTE", neu)
            self.assertFalse(datei.with_name("verlauf_alt.txt").exists())

    def test_mehrzeiliger_eintrag_bleibt_ganz(self):
        with mock.patch.object(orchestrator, "ORCH_ORDNER", self.ordner):
            datei = orchestrator.verlauf_datei()
            kopf = "[2026-01-01 00:00:00] antwort: "
            datei.write_text((kopf + "x" * 5000 + "\n") * 300
                             + kopf + "zeile eins\nzeile zwei\n", encoding="utf-8")
            orchestrator._verlauf_kuerzen(datei)
            neu = datei.read_text(encoding="utf-8")
            self.assertTrue(neu.startswith("[2026"))
            self.assertTrue(neu.endswith("zeile eins\nzeile zwei\n"))
            self.assertEqual(sum(1 for z in neu.splitlines() if z.startswith("[2026")),
                             orchestrator.VERLAUF_BEHALTEN)

    def test_laden_zeigt_hoechstens_60(self):
        with mock.patch.object(orchestrator, "ORCH_ORDNER", self.ordner):
            orchestrator.verlauf_datei().write_text(
                "".join(f"[2026-01-01 00:00:{i % 60:02d}] antwort: {i}\n" for i in range(100)),
                encoding="utf-8")
            self.assertEqual(len(orchestrator.verlauf_laden()), 60)


if __name__ == "__main__":
    unittest.main()
