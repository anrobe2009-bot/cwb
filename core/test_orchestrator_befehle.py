"""
CWB - Code Workbench
Tests fuer die Befehlsanzeige des Orchestrators (core/orchestrator.py,
core/orchestrator_ansicht.py und die Rueckrufe in core/sitzung.py):

- ein Werkzeugaufruf erzeugt eine Zeile, lange Befehle werden auf 120 Zeichen
  mit Auslassungspunkten gekuerzt,
- Ergebniszeilen fuer Erfolg, Fehler und Ablehnung,
- Schluessel, Tokens und Kennwoerter erscheinen nie (Anzeige und Verlauf),
- Schalter aus unterdrueckt die Zeilen, nichts wird gesprochen,
- das Vorlesen der Antwort enthaelt die Zeilen nicht,
- verlauf.txt wird beim Oeffnen wieder angezeigt, auch alte Verlaeufe ohne Zeilen.

Nur offscreen, kein sichtbares Fenster.
Aufruf: python -m unittest core.test_orchestrator_befehle -v
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

try:
    from . import eingangsordner, orchestrator, orchestrator_ansicht
    from .sicherheit import Projekt
    from .sitzung import Sitzung, Zustand
except ImportError:
    import eingangsordner
    import orchestrator
    import orchestrator_ansicht
    from sicherheit import Projekt
    from sitzung import Sitzung, Zustand

from claude_agent_sdk import ToolResultBlock, ToolUseBlock, UserMessage

SERVER = "mcp__cwb-orchestrator__"


class ZeilenTest(unittest.TestCase):
    def test_auftrag_senden_run(self):
        zeile = orchestrator.befehl_zeile(
            SERVER + "auftrag_senden",
            {"art": "RUN", "projekt": "hausgemacht", "text": "git status"})
        self.assertEqual(zeile, "→ RUN an hausgemacht: git status")

    def test_auftrag_senden_code(self):
        zeile = orchestrator.befehl_zeile(
            SERVER + "auftrag_senden", {"art": "CODE", "projekt": "cwb", "text": "Block 48"})
        self.assertTrue(zeile.startswith("→ CODE an cwb"))

    def test_weitere_werkzeuge(self):
        self.assertEqual(orchestrator.befehl_zeile(SERVER + "bericht_holen",
                                                   {"auftrag_nummer": 1031}),
                         "→ holt Bericht Auftrag 1031")
        self.assertEqual(orchestrator.befehl_zeile("Read", {"file_path": "/a/b/build.gradle.kts"}),
                         "→ liest build.gradle.kts")
        self.assertEqual(orchestrator.befehl_zeile("Grep", {"pattern": "Wache"}), "→ sucht Wache")
        self.assertEqual(orchestrator.befehl_zeile("Bash", {"command": "ls"}), "→ führt aus: ls")

    def test_kuerzung_ueber_120_zeichen(self):
        lang = "x" * 300
        zeile = orchestrator.befehl_zeile("Bash", {"command": lang})
        angabe = zeile.split(": ", 1)[1]
        self.assertEqual(len(angabe), orchestrator.BEFEHL_MAX_ZEICHEN + 1)
        self.assertTrue(angabe.endswith("…"))

    def test_kein_auslassungszeichen_bei_genau_120(self):
        angabe = orchestrator.befehl_zeile("Bash", {"command": "y" * 120}).split(": ", 1)[1]
        self.assertEqual(angabe, "y" * 120)

    def test_ergebniszeilen(self):
        self.assertEqual(orchestrator.ergebnis_zeile("Bash", {}, "fertig"), "← fertig")
        self.assertEqual(orchestrator.ergebnis_zeile("Bash", {}, "abgelehnt"), "← abgelehnt")
        self.assertEqual(orchestrator.ergebnis_zeile("Bash", {}, "fehler", "kein Zugriff"),
                         "← Fehler: kein Zugriff")
        self.assertEqual(orchestrator.ergebnis_zeile(SERVER + "bericht_holen",
                                                     {"auftrag_nummer": 1031}, "fertig"),
                         "← Bericht Auftrag 1031 gelesen")

    def test_fehlergrund_wird_gekuerzt(self):
        zeile = orchestrator.ergebnis_zeile("Bash", {}, "fehler", "z " * 200)
        self.assertLessEqual(len(zeile), len("← Fehler: ") + orchestrator.FEHLER_MAX_ZEICHEN + 1)


class VerbergenTest(unittest.TestCase):
    MUSTER = (
        "curl -H 'Authorization: Bearer abc123def'",
        "export ANTHROPIC_API_KEY=abc",
        "echo sk-ant-api03-abcdefghij",
        "curl https://x/?key=AIzaSyA1234567890",
        "TOKEN=xyz run.sh",
        "PASSWORD=geheim",
        "password = geheim",
    )

    def test_muster_werden_verborgen(self):
        for befehl in self.MUSTER:
            zeile = orchestrator.befehl_zeile("Bash", {"command": befehl})
            self.assertEqual(zeile, f"→ führt aus: {orchestrator.VERBORGEN}", befehl)

    def test_auch_in_auftraegen_und_fehlern(self):
        zeile = orchestrator.befehl_zeile(
            SERVER + "auftrag_senden", {"art": "RUN", "projekt": "p", "text": "KEY=abc go"})
        self.assertNotIn("abc", zeile)
        self.assertIn(orchestrator.VERBORGEN, zeile)
        fehler = orchestrator.ergebnis_zeile("Bash", {}, "fehler", "Bearer abc123def abgelehnt")
        self.assertEqual(fehler, f"← Fehler: {orchestrator.VERBORGEN}")

    def test_sperrdatei_name_wird_verborgen(self):
        self.assertEqual(orchestrator.befehl_zeile("Read", {"file_path": "/p/.env"}),
                         f"→ liest {orchestrator.VERBORGEN}")

    def test_harmloses_bleibt(self):
        self.assertEqual(orchestrator.verbergen("git status"), "git status")
        self.assertEqual(orchestrator.verbergen("monkey business"), "monkey business")


class SitzungRueckrufTest(unittest.TestCase):
    def setUp(self):
        self.aufrufe = []
        self.ergebnisse = []
        self.sitzung = Sitzung(
            mock.MagicMock(),
            bei_werkzeug=lambda n, e: self.aufrufe.append((n, e)),
            bei_werkzeug_ergebnis=lambda n, e, s, t: self.ergebnisse.append((n, e, s, t)),
        )

    def _aufruf(self, kennung="t1", name="Bash", eingabe=None):
        self.sitzung._werkzeug_gemeldet(ToolUseBlock(
            id=kennung, name=name, input=eingabe or {"command": "ls"}))

    def _ergebnis(self, kennung="t1", fehler=False, text="ok"):
        self.sitzung._werkzeug_ergebnisse_melden(UserMessage(content=[
            ToolResultBlock(tool_use_id=kennung, content=text, is_error=fehler)]))

    def test_aufruf_wird_gemeldet(self):
        self._aufruf()
        self.assertEqual(self.aufrufe, [("Bash", {"command": "ls"})])

    def test_erfolg_fehler_ablehnung(self):
        self._aufruf("a")
        self._ergebnis("a")
        self._aufruf("b")
        self._ergebnis("b", fehler=True, text="kaputt")
        self._aufruf("c")
        self.sitzung._melde(Zustand.FEHLER, "abgelehnt", ablehnung=True)
        self._ergebnis("c", fehler=True, text="verweigert")
        self.assertEqual([e[2] for e in self.ergebnisse], ["fertig", "fehler", "abgelehnt"])
        self.assertEqual(self.ergebnisse[1][3], "kaputt")

    def test_ohne_rueckruf_aendert_sich_nichts(self):
        sitzung = Sitzung(mock.MagicMock())
        sitzung._werkzeug_gemeldet(ToolUseBlock(id="x", name="Bash", input={}))
        sitzung._werkzeug_ergebnisse_melden(UserMessage(content=[
            ToolResultBlock(tool_use_id="x", content="ok", is_error=False)]))
        self.assertEqual(sitzung._werkzeug_offen, {})


class AnsichtBefehleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.wurzel = Path(temp.name)
        self.einstellungen = {}
        for p in (mock.patch.object(orchestrator, "ORCH_ORDNER", self.wurzel / "orchestrator"),
                  mock.patch.object(eingangsordner, "EINGANG_ORDNER", self.wurzel / "eingang"),
                  mock.patch.object(orchestrator, "einstellungen_lesen",
                                    side_effect=lambda: dict(self.einstellungen))):
            p.start()
            self.addCleanup(p.stop)
        self.sprecher = mock.MagicMock()
        self.ansicht = self._ansicht()

    def _ansicht(self):
        ansicht = orchestrator_ansicht.OrchestratorAnsicht(
            Projekt("Test", self.wurzel, False), self.sprecher)
        self.addCleanup(ansicht.deleteLater)
        return ansicht

    def _verlauf_text(self) -> str:
        datei = orchestrator.verlauf_datei()
        return datei.read_text(encoding="utf-8") if datei.exists() else ""

    def test_aufruf_und_ergebnis_erscheinen_und_werden_gespeichert(self):
        a = self.ansicht
        a._werkzeug("Bash", {"command": "git status"})
        a._werkzeug_ergebnis("Bash", {"command": "git status"}, "fertig", "")
        text = a.verlauf.toPlainText()
        self.assertIn("→ führt aus: git status", text)
        self.assertIn("← fertig", text)
        self.assertIn("befehl: → führt aus: git status", self._verlauf_text())

    def test_nichts_wird_gesprochen(self):
        self.ansicht._werkzeug("Bash", {"command": "ls"})
        self.ansicht._werkzeug_ergebnis("Bash", {}, "fehler", "x")
        self.sprecher.sprich.assert_not_called()
        self.sprecher.ton.assert_not_called()

    def test_schluessel_nicht_im_feld_und_nicht_im_verlauf(self):
        self.ansicht._werkzeug("Bash", {"command": "curl -H 'Authorization: Bearer geheim123'"})
        self.assertNotIn("geheim123", self.ansicht.verlauf.toPlainText())
        self.assertNotIn("geheim123", self._verlauf_text())
        self.assertIn(orchestrator.VERBORGEN, self.ansicht.verlauf.toPlainText())

    def test_schalter_aus_unterdrueckt_zeilen(self):
        self.einstellungen = {"orchestrator_befehle_anzeigen": False}
        self.ansicht._werkzeug("Bash", {"command": "ls"})
        self.ansicht._werkzeug_ergebnis("Bash", {}, "fertig", "")
        self.assertEqual(self.ansicht.verlauf.toPlainText(), "")
        self.assertNotIn("befehl:", self._verlauf_text())

    def test_schalter_vorgabe_ist_an(self):
        self.assertTrue(orchestrator.befehle_anzeigen())

    def test_vorlesen_enthaelt_zeilen_nicht(self):
        a = self.ansicht
        a._letzte_antwort = "Das ist die Antwort."
        a._werkzeug("Bash", {"command": "ls"})
        a._werkzeug_ergebnis("Bash", {}, "fertig", "")
        quelle = a._vorlese_quelle()
        self.assertEqual(quelle, "Das ist die Antwort.")
        self.assertNotIn("→", quelle)
        self.assertNotIn("←", quelle)

    def test_antworttext_bleibt_ohne_zeilen(self):
        a = self.ansicht
        a._werkzeug("Bash", {"command": "ls"})
        self.assertEqual(a._antwort_teile, [])

    def test_verlauf_wird_beim_oeffnen_wieder_angezeigt(self):
        self.ansicht._absatz("Frage?", "auftrag")
        self.ansicht._werkzeug("Bash", {"command": "ls"})
        self.ansicht._werkzeug_ergebnis("Bash", {}, "fertig", "")
        neu = self._ansicht()
        text = neu.verlauf.toPlainText()
        self.assertIn("Frage?", text)
        self.assertIn("→ führt aus: ls", text)
        self.assertIn("← fertig", text)
        self.assertLess(text.index("Frage?"), text.index("→ führt aus"))

    def test_wiederanzeige_ohne_schalter_laesst_zeilen_weg(self):
        self.ansicht._absatz("Frage?", "auftrag")
        self.ansicht._werkzeug("Bash", {"command": "ls"})
        self.einstellungen = {"orchestrator_befehle_anzeigen": False}
        text = self._ansicht().verlauf.toPlainText()
        self.assertIn("Frage?", text)
        self.assertNotIn("→", text)

    def test_alter_verlauf_ohne_zeilen_laedt(self):
        datei = orchestrator.verlauf_datei()
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_text(
            "[2026-10-01 09:00:00] auftrag: ▶  Du: Hallo\n"
            "[2026-10-01 09:00:05] antwort: Orchestrator: Erste Zeile\nzweite Zeile\n"
            "[2026-10-01 09:00:09] hinweis: —  Fertig\n", encoding="utf-8")
        text = self._ansicht().verlauf.toPlainText()
        self.assertIn("Du: Hallo", text)   # Rich-Text faltet die Doppelleerzeichen
        self.assertIn("Erste Zeile", text)
        self.assertIn("zweite Zeile", text)
        self.assertIn("Fertig", text)

    def test_geladene_befehlszeile_mit_schluessel_wird_verborgen(self):
        datei = orchestrator.verlauf_datei()
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_text("[2026-10-01 09:00:00] befehl: → führt aus: KEY=abc\n", encoding="utf-8")
        text = self._ansicht().verlauf.toPlainText()
        self.assertNotIn("abc", text)
        self.assertIn(orchestrator.VERBORGEN, text)

    def test_fehlender_verlauf_ist_leer(self):
        self.assertEqual(orchestrator.verlauf_laden(), [])


if __name__ == "__main__":
    unittest.main()
