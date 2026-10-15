"""
CWB - Code Workbench
Unit-Tests fuer Block 52 (core/sitzung.py): wiederkehrender Fehler, bei dem
Claude Code eine Hintergrundaufgabe startete und den Auftrag beendete, ohne
auf deren Ergebnis zu warten oder es umzusetzen. Geprueft werden die reine
Warnungslogik (_hintergrund_warnung, ohne laufende SDK-Verbindung) sowie die
Konstanten, mit denen core/sitzung.py Unteragenten/Hintergrundaufgaben ganz
abschaltet (HINTERGRUND_WERKZEUGE_GESPERRT) und im festen System-Zusatz
verbietet (SYSTEM_ZUSATZ).

Dazu Block 80: disallowed_tools und SYSTEM_ZUSATZ sperren nur die
Werkzeugnamen "Agent"/"Workflow" - ein Bash-Befehl mit run_in_background
oder ein Skill, der von sich aus im Hintergrund laeuft (ohne dass
run_in_background im Werkzeugaufruf steht), trifft trotzdem ein. Seit
Block 80 reagiert Sitzung._hintergrund_gestartet() darauf nicht nur mit
einer Warnung, sondern bricht die Aufgabe aktiv ab (client.stop_task) -
geprueft hier mit einer nachgebildeten TaskStartedMessage und einem
nachgebildeten Klienten statt einer echten SDK-Verbindung.

Aufruf: python -m unittest core.test_hintergrund -v
        (oder, aus dem Ordner core/: python test_hintergrund.py -v)
"""

import types
import unittest

try:
    from . import sitzung
except ImportError:
    import sitzung


class HintergrundWarnungTest(unittest.TestCase):
    """core/sitzung.py: _hintergrund_warnung() - baut den Warnungstext aus
    den beim Auftragsende noch nicht abgeschlossenen Hintergrundaufgaben."""

    def test_keine_aktive_aufgabe_ergibt_keine_warnung(self):
        self.assertIsNone(sitzung._hintergrund_warnung({}))

    def test_eine_aktive_aufgabe_nennt_beschreibung_und_id(self):
        warnung = sitzung._hintergrund_warnung(
            {"task_1": "CWB-Architektur fuer Leitstand-Modul erkunden"}
        )
        self.assertIsNotNone(warnung)
        self.assertTrue(warnung.startswith("Auftrag endete mit laufender Hintergrundaufgabe:"))
        self.assertIn("CWB-Architektur fuer Leitstand-Modul erkunden", warnung)
        self.assertIn("task_1", warnung)

    def test_mehrere_aktive_aufgaben_werden_alle_genannt(self):
        warnung = sitzung._hintergrund_warnung(
            {"task_1": "Erste Aufgabe", "task_2": "Zweite Aufgabe"}
        )
        self.assertIn("Erste Aufgabe", warnung)
        self.assertIn("Zweite Aufgabe", warnung)
        self.assertIn("task_1", warnung)
        self.assertIn("task_2", warnung)


class HintergrundaufgabenAbgeschaltetTest(unittest.TestCase):
    """core/sitzung.py: Agent und Workflow stehen in der Sperrliste, die
    _einstellungen() unveraendert an ClaudeAgentOptions.disallowed_tools
    weiterreicht - und beide tauchen auch im festen System-Zusatz als
    verboten auf."""

    def test_agent_und_workflow_sind_gesperrt(self):
        self.assertIn("Agent", sitzung.HINTERGRUND_WERKZEUGE_GESPERRT)
        self.assertIn("Workflow", sitzung.HINTERGRUND_WERKZEUGE_GESPERRT)

    def test_system_zusatz_verbietet_hintergrundbefehle(self):
        self.assertIn("Agent", sitzung.SYSTEM_ZUSATZ)
        self.assertIn("Workflow", sitzung.SYSTEM_ZUSATZ)
        self.assertIn("Hintergrund-Befehle", sitzung.SYSTEM_ZUSATZ)


class HintergrundGestartetTest(unittest.IsolatedAsyncioTestCase):
    """Block 80: Sitzung._hintergrund_gestartet() bricht eine trotz Verbot
    gestartete Hintergrundaufgabe aktiv ab, statt sie nur zu vermerken -
    geprueft auf einem nachgebildeten Fenster (types.SimpleNamespace statt
    echter Sitzung/SDK-Verbindung)."""

    @staticmethod
    def _nachricht(task_id="task-1", description="Codebase durchsuchen"):
        return sitzung.TaskStartedMessage(
            subtype="task_started", data={}, task_id=task_id,
            description=description, uuid="u-1", session_id="s-1",
        )

    async def test_stop_task_wird_mit_der_richtigen_id_aufgerufen(self):
        gestoppt = []

        class FakeKlient:
            async def stop_task(self, task_id):
                gestoppt.append(task_id)

        fake = types.SimpleNamespace(klient=FakeKlient(), _hintergrundaufgaben={})
        nachricht = self._nachricht(task_id="task-42", description="Recherche")
        await sitzung.Sitzung._hintergrund_gestartet(fake, nachricht)
        self.assertEqual(gestoppt, ["task-42"])
        self.assertEqual(fake._hintergrundaufgaben, {"task-42": "Recherche"})

    async def test_fehlschlag_beim_abbrechen_wirft_nicht(self):
        class FehlerKlient:
            async def stop_task(self, task_id):
                raise RuntimeError("Verbindung weg")

        fake = types.SimpleNamespace(klient=FehlerKlient(), _hintergrundaufgaben={})
        nachricht = self._nachricht()
        # Darf keine Ausnahme nach aussen durchlassen, sonst risse das den
        # ganzen Auftrag mit sich.
        await sitzung.Sitzung._hintergrund_gestartet(fake, nachricht)
        self.assertIn("task-1", fake._hintergrundaufgaben)


if __name__ == "__main__":
    unittest.main()
