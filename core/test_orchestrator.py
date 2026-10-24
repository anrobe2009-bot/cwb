"""
CWB - Code Workbench
Tests fuer den Orchestrator, Etappe 1A (core/orchestrator.py,
core/orchestrator_ansicht.py und die Haken in core/sitzung.py, core/faden.py,
core/fenster.py):

- Schalter aus = nichts aendert sich (Standardwerte, Sitzung ohne Zusaetze),
- die Werkzeuge auftrag_senden / bericht_holen / status ohne echte Sitzung,
- zwei Sitzungen stoeren sich nicht (eigene Warteschlange, kein Git-Sicherungs-
  punkt in der schlanken Sitzung, eigener Systemtext und eigene Werkzeuge),
- was die Sicherheitsregeln mit adb und gradlew tun.

Aufruf: python -m unittest core.test_orchestrator -v
"""

import asyncio
import os
import re
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

try:
    from . import (eingangsordner, fenster, grundlagen, orchestrator, orchestrator_ansicht,
                   sicherheit, sitzung)
    from .bruecke import KENNZEILE_MUSTER
    from .faden import SitzungsFaden
    from .sicherheit import Projekt, Stufe
except ImportError:
    import eingangsordner
    import fenster
    import grundlagen
    import orchestrator
    import orchestrator_ansicht
    import sicherheit
    import sitzung
    from bruecke import KENNZEILE_MUSTER
    from faden import SitzungsFaden
    from sicherheit import Projekt, Stufe


class _Ordner(unittest.TestCase):
    """Legt Eingangs- und Orchestrator-Ordner in ein Temp-Verzeichnis."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        wurzel = Path(self._temp.name)
        self.eingang = wurzel / "eingang"
        self.orch = wurzel / "orchestrator"
        for p in (mock.patch.object(eingangsordner, "EINGANG_ORDNER", self.eingang),
                  mock.patch.object(orchestrator, "ORCH_ORDNER", self.orch)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._temp.cleanup)
        eingangsordner.sicherstellen()


class SchalterTest(unittest.TestCase):
    def test_standard_ist_aus(self):
        with mock.patch.object(orchestrator, "einstellungen_lesen", return_value={}):
            self.assertFalse(orchestrator.aktiv())

    def test_schalter_an(self):
        with mock.patch.object(orchestrator, "einstellungen_lesen",
                               return_value={"orchestrator": True}):
            self.assertTrue(orchestrator.aktiv())

    def test_modell_standard_sonnet(self):
        with mock.patch.object(orchestrator, "einstellungen_lesen", return_value={}):
            self.assertEqual(orchestrator.modell(), "sonnet")
        with mock.patch.object(orchestrator, "einstellungen_lesen",
                               return_value={"orchestrator_modell": "opus"}):
            self.assertEqual(orchestrator.modell(), "opus")

    def test_normale_sitzung_hat_keine_zusaetze(self):
        wache = mock.MagicMock()
        s = sitzung.Sitzung(wache)
        self.assertFalse(s.schlank)
        self.assertIsNone(s.system_zusatz)
        self.assertEqual(s.zusatz_server, {})

    def test_normale_optionen_ohne_orchestrator_server(self):
        wache = mock.MagicMock()
        wache.projekt.pfad = Path(".")
        s = sitzung.Sitzung(wache)
        with mock.patch.object(sitzung, "_memory_hub_server", return_value=None), \
                mock.patch.object(sitzung, "freigaben_lesen", return_value=[]):
            optionen = s._einstellungen()
        self.assertEqual(optionen.system_prompt["append"], sitzung.SYSTEM_ZUSATZ)
        self.assertNotIn(orchestrator.SERVER_NAME, optionen.mcp_servers)

    def test_fenster_haelt_ohne_schalter_keine_ansicht(self):
        """Die Haken im Hauptfenster sind ohne Ansicht wirkungslos."""
        for f in (types.SimpleNamespace(_orch_ansicht=None, _orch_stapel=None, _orch_nummern={}),
                  types.SimpleNamespace(),          # Fenster-Attrappen kennen die Haken nicht
                  mock.MagicMock()):                # ... oder liefern ueberall Attrappen
            self.assertFalse(fenster._orch_frage_offen(f))
            self.assertFalse(fenster._orch_ist(f, Path("x.json")))
            fenster._orch_stopp(f)      # darf nichts tun und nicht werfen
            fenster._orch_beenden(f)
            with mock.patch.object(orchestrator, "bericht_ablegen") as ablegen:
                fenster._orch_bericht(f, Path("x.json"), "Text")
                ablegen.assert_not_called()


class AuftragSendenTest(_Ordner):
    PROJEKTE = ["CWB", "hausgemacht"]

    def senden(self, art="RUN", projekt="CWB", text="echo hallo"):
        return orchestrator.auftrag_senden(art, projekt, text, projekte=self.PROJEKTE)

    def test_run_landet_im_eingang_mit_markierung(self):
        ergebnis = self.senden()
        self.assertTrue(ergebnis["ok"], ergebnis)
        dateien = list(self.eingang.glob("*.json"))
        self.assertEqual(len(dateien), 1)
        auftrag = eingangsordner.auftrag_lesen(dateien[0], fenster.markierung_erkennen)
        self.assertEqual(auftrag.quelle, "orchestrator")
        self.assertEqual(auftrag.art, "run")
        self.assertEqual(auftrag.inhalt, "echo hallo")
        self.assertEqual(auftrag.projekt, "CWB")
        self.assertEqual(auftrag.auftrag_nummer, ergebnis["nummer"])
        self.assertGreater(auftrag.auftrag_nummer, orchestrator.LOKAL_AB)

    def test_code_wird_erkannt_und_kleinschreibung_genuegt(self):
        ergebnis = self.senden(art="code", text="Baue X")
        self.assertTrue(ergebnis["ok"])
        datei = next(self.eingang.glob("*.json"))
        self.assertEqual(
            eingangsordner.auftrag_lesen(datei, fenster.markierung_erkennen).art, "code")

    def test_nummern_steigen_und_sind_eindeutig(self):
        a, b = self.senden()["nummer"], self.senden(text="echo zwei")["nummer"]
        self.assertEqual(b, a + 1)

    def test_nummern_ueberleben_neues_modul_zustand(self):
        a = self.senden()["nummer"]
        self.assertTrue((self.orch / "nummer.txt").is_file())
        self.assertEqual(orchestrator.naechste_nummer(), a + 1)

    def test_admin_und_bild_gibt_es_nicht(self):
        for art in ("ADMIN", "BILD", "", None):
            ergebnis = self.senden(art=art)
            self.assertFalse(ergebnis["ok"], art)
        self.assertEqual(list(self.eingang.glob("*.json")), [])

    def test_admin_ueber_eingang_bleibt_fuer_diese_quelle_gesperrt(self):
        self.assertTrue(eingangsordner.admin_gesperrt("admin", orchestrator.QUELLE))

    def test_unbekanntes_projekt_wird_abgelehnt(self):
        ergebnis = self.senden(projekt="gibtsnicht")
        self.assertFalse(ergebnis["ok"])
        self.assertIn("nicht bekannt", ergebnis["meldung"])
        self.assertEqual(list(self.eingang.glob("*.json")), [])

    def test_projektname_unscharf(self):
        self.assertTrue(self.senden(projekt="Haus-Gemacht")["ok"])

    def test_leerer_text_und_leeres_projekt(self):
        self.assertFalse(self.senden(text="   ")["ok"])
        self.assertFalse(self.senden(projekt="")["ok"])


class BerichtTest(_Ordner):
    def test_bericht_hat_kennzeile_vorweg(self):
        orchestrator.bericht_ablegen(1000005, "Alles gut.", block=12)
        text = orchestrator.bericht_holen(1000005)
        erste = text.split("\n", 1)[0]
        self.assertRegex(erste, KENNZEILE_MUSTER)
        self.assertTrue(erste.startswith("Auftrag 1000005 | Block 12 | Zeit "))
        self.assertTrue(text.endswith("Alles gut."))

    def test_ohne_block_steht_strich(self):
        orchestrator.bericht_ablegen(1000006, "x")
        self.assertIn("| Block - |", orchestrator.bericht_holen(1000006))

    def test_unbekannte_nummer(self):
        self.assertIn("unbekannt", orchestrator.bericht_holen(1000999))
        self.assertIn("keine Zahl", orchestrator.bericht_holen("abc"))

    def test_wartender_auftrag_sagt_wo_er_steht(self):
        nummer = orchestrator.auftrag_senden("RUN", "CWB", "echo", projekte=["CWB"])["nummer"]
        self.assertIn("wartet im Eingang", orchestrator.bericht_holen(nummer))
        datei = next(self.eingang.glob("*.json"))
        datei.replace(eingangsordner.laeuft_ordner() / datei.name)
        self.assertIn("laeuft oder wartet", orchestrator.bericht_holen(nummer))
        datei = eingangsordner.laeuft_ordner() / datei.name
        datei.replace(eingangsordner.abgelehnt_ordner() / datei.name)
        (eingangsordner.abgelehnt_ordner() / f"{datei.name}.txt").write_text(
            "Projekt unbekannt", encoding="utf-8")
        antwort = orchestrator.bericht_holen(nummer)
        self.assertIn("abgelehnt", antwort)
        self.assertIn("Projekt unbekannt", antwort)

    def test_fertiger_auftrag_liefert_bericht_auch_nach_erledigt(self):
        nummer = orchestrator.auftrag_senden("CODE", "CWB", "tu was", projekte=["CWB"])["nummer"]
        datei = next(self.eingang.glob("*.json"))
        datei.replace(eingangsordner.erledigt_ordner() / datei.name)
        self.assertIn("ohne Bericht", orchestrator.bericht_holen(nummer))
        orchestrator.bericht_ablegen(nummer, "erledigt")
        self.assertTrue(orchestrator.bericht_holen(nummer).endswith("erledigt"))

    def test_fenster_haken_legt_bericht_unter_der_nummer_ab(self):
        f = types.SimpleNamespace(_orch_nummern={"auftrag.json": 1000042})
        self.assertTrue(fenster._orch_ist(f, Path("/irgendwo/auftrag.json")))
        fenster._orch_bericht(f, Path("/irgendwo/auftrag.json"), "Ergebnis", 7)
        self.assertEqual(f._orch_nummern, {})
        self.assertIn("Ergebnis", orchestrator.bericht_holen(1000042))
        # ein fremder Auftrag (kein Orchestrator) wird nicht abgelegt
        fenster._orch_bericht(f, Path("/irgendwo/anderer.json"), "Fremd")
        self.assertIn("unbekannt", orchestrator.bericht_holen(1000043))

    def test_bericht_ohne_nummer_wird_nicht_abgelegt(self):
        self.assertIsNone(orchestrator.bericht_ablegen(None, "x"))


class StatusTest(_Ordner):
    def test_status_ohne_fenster(self):
        text = orchestrator.status()
        self.assertIn("Eingang: 0 neu", text)
        self.assertIn("Fertige Berichte: keine", text)

    def test_status_mit_fensterzustand_und_berichten(self):
        orchestrator.auftrag_senden("RUN", "CWB", "echo", projekte=["CWB"])
        orchestrator.bericht_ablegen(1000001, "a")
        text = orchestrator.status({"projekt": "CWB", "laeuft": True, "wartet": 2,
                                    "taetigkeit": "liest fenster.py"})
        self.assertIn("ein Auftrag laeuft", text)
        self.assertIn("2 warten", text)
        self.assertIn("liest fenster.py", text)
        self.assertIn("1 neu", text)
        self.assertIn("1000001", text)


class WerkzeugeTest(_Ordner):
    """Die drei Werkzeuge ueber den eingebetteten Server, mit Attrappe statt
    echter Sitzung: create_sdk_mcp_server wird abgefangen, die Handler direkt
    aufgerufen."""

    def bauen(self, zustand=None):
        gefangen = {}

        def attrappe(name, tools=None, **_):
            gefangen["name"] = name
            gefangen["tools"] = {t.name: t for t in tools}
            return {"type": "sdk", "name": name}

        with mock.patch("claude_agent_sdk.create_sdk_mcp_server", attrappe):
            orchestrator.werkzeuge_bauen(zustand)
        return gefangen

    def aufrufen(self, gefangen, name, **args):
        return asyncio.run(gefangen["tools"][name].handler(args))

    def test_servername_und_werkzeuge(self):
        gefangen = self.bauen()
        self.assertEqual(gefangen["name"], orchestrator.SERVER_NAME)
        self.assertEqual(set(gefangen["tools"]), {"auftrag_senden", "bericht_holen", "status"})

    def test_auftrag_senden_und_bericht_holen(self):
        gefangen = self.bauen()
        with mock.patch.object(orchestrator, "projekt_bekannt", return_value=True):
            antwort = self.aufrufen(gefangen, "auftrag_senden", art="RUN", projekt="CWB",
                                    text="echo hi")
        self.assertNotIn("is_error", antwort)
        self.assertIn("liegt im Eingang", antwort["content"][0]["text"])
        nummer = int(antwort["content"][0]["text"].split()[1])
        bericht = self.aufrufen(gefangen, "bericht_holen", auftrag_nummer=nummer)
        self.assertIn("wartet im Eingang", bericht["content"][0]["text"])

    def test_fehler_kommen_als_werkzeugfehler(self):
        gefangen = self.bauen()
        antwort = self.aufrufen(gefangen, "auftrag_senden", art="ADMIN", projekt="CWB",
                                text="x")
        self.assertTrue(antwort["is_error"])

    def test_status_nutzt_zustandsgeber(self):
        gefangen = self.bauen(lambda: {"projekt": "CWB", "laeuft": False, "wartet": 0})
        text = self.aufrufen(gefangen, "status")["content"][0]["text"]
        self.assertIn("nichts laeuft", text)

    def test_status_wirft_nicht_bei_defektem_geber(self):
        def kaputt():
            raise RuntimeError("weg")

        gefangen = self.bauen(kaputt)
        antwort = self.aufrufen(gefangen, "status")
        self.assertTrue(antwort["is_error"])


class _AttrappeKlient:
    def __init__(self):
        self.gesendet = []

    async def query(self, text):
        self.gesendet.append(text)

    async def receive_response(self):
        yield sitzung.ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id="x", result="ok")


class ZweiSitzungenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])

    def projekt(self):
        return Projekt("Test", Path(tempfile.gettempdir()), False)

    def test_schlanke_sitzung_macht_keinen_sicherungspunkt(self):
        wache = mock.MagicMock()
        wache.nur_lesen = False
        wache.auftrag_bilanz.return_value = []
        s = sitzung.Sitzung(wache, schlank=True)
        s.klient = _AttrappeKlient()
        ergebnis = asyncio.run(s.auftrag("Hallo"))
        wache.auftrag_beginnen.assert_not_called()
        wache.grenze.auftrag_beginnen.assert_called_once()
        self.assertIsNone(ergebnis["sicherungspunkt"])
        self.assertEqual(ergebnis["fehler"], "")
        self.assertEqual(s.klient.gesendet, ["Hallo"])   # kein Gedaechtnisblock davor

    def test_normale_sitzung_macht_weiter_ihren_sicherungspunkt(self):
        wache = mock.MagicMock()
        wache.nur_lesen = False
        wache.auftrag_bilanz.return_value = []
        s = sitzung.Sitzung(wache)
        s.klient = _AttrappeKlient()
        with mock.patch.object(s, "_protokoll_schreiben"), \
                mock.patch.object(s, "_nachtrag_stellen", new=mock.AsyncMock()):
            asyncio.run(s.auftrag("Hallo"))
        wache.auftrag_beginnen.assert_called_once()

    def test_orchestrator_optionen_haben_eigenen_text_und_werkzeuge(self):
        wache = mock.MagicMock()
        wache.projekt.pfad = Path(".")
        s = sitzung.Sitzung(
            wache, system_zusatz="ZUSATZ", zusatz_server={"cwb-orchestrator": {"type": "sdk"}},
            schlank=True)
        with mock.patch.object(sitzung, "_memory_hub_server", return_value=None), \
                mock.patch.object(sitzung, "freigaben_lesen", return_value=[]):
            optionen = s._einstellungen()
        self.assertEqual(optionen.system_prompt["preset"], "claude_code")
        self.assertEqual(optionen.system_prompt["append"], "ZUSATZ")
        self.assertIn("cwb-orchestrator", optionen.mcp_servers)

    def test_orchestratorfaden_baut_schlanke_sitzung_ohne_git(self):
        faden = orchestrator_ansicht.OrchestratorFaden(self.projekt())
        with mock.patch.object(sicherheit.Wache, "oeffnen") as oeffnen, \
                mock.patch.object(orchestrator, "werkzeuge_bauen", return_value={"type": "sdk"}):
            s = faden._sitzung_bauen()
        oeffnen.assert_called_once()
        self.assertIs(oeffnen.call_args.kwargs["git_anlegen"], False)
        self.assertTrue(s.schlank)
        self.assertIn(orchestrator.SERVER_NAME, s.zusatz_server)
        self.assertIn(sitzung.SYSTEM_ZUSATZ, s.system_zusatz)
        self.assertIn("Orchestrator", s.system_zusatz)   # wissen/orchestrator_anweisung.md

    def test_faden_haben_getrennte_warteschlangen_und_zustaende(self):
        normal = SitzungsFaden(self.projekt(), "")
        orch = orchestrator_ansicht.OrchestratorFaden(self.projekt())
        normal.auftrag_geben("a", [])
        self.assertTrue(orch.auftraege.empty())
        orch.auftrag_geben("b", [])
        orch.faden_beschaeftigt = True
        self.assertFalse(normal.faden_beschaeftigt)
        self.assertEqual(normal.auftraege.get_nowait()[1], "a")
        orch.wartende_verwerfen()
        self.assertTrue(orch.auftraege.empty())

    def test_normaler_faden_bekommt_standardsitzung(self):
        faden = SitzungsFaden(self.projekt(), "")
        with mock.patch.object(sicherheit.Wache, "oeffnen") as oeffnen:
            s = faden._sitzung_bauen()
        self.assertIsNot(oeffnen.call_args.kwargs.get("git_anlegen", True), False)
        self.assertFalse(s.schlank)


class AnsichtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anwendung = QApplication.instance() or QApplication([])

    def setUp(self):
        # Verlauf, Schlange, Berichte und Nummernzaehler gehoeren ins Temp-Verzeichnis,
        # nie in den echten Datenordner (siehe test_zz_datenordner_wache.py).
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        wurzel = Path(temp.name)
        for p in (mock.patch.object(orchestrator, "ORCH_ORDNER", wurzel / "orchestrator"),
                  mock.patch.object(eingangsordner, "EINGANG_ORDNER", wurzel / "eingang")):
            p.start()
            self.addCleanup(p.stop)
        self.sprecher = mock.MagicMock()
        self.ansicht = orchestrator_ansicht.OrchestratorAnsicht(
            Projekt("Test", Path(tempfile.gettempdir()), False), self.sprecher)
        self.addCleanup(self.ansicht.deleteLater)

    def test_aufbau_namen_und_barrierefreiheit(self):
        a = self.ansicht
        self.assertEqual(a.verlauf.accessibleName(), "Orchestrator-Verlauf")
        self.assertTrue(a.verlauf.isReadOnly())
        self.assertEqual(a.titel.text(), "Orchestrator: bereit")
        for widget in (a.titel, a.status, a.verlauf, a.eingabe, a.senden_knopf, a.stopp_knopf):
            self.assertTrue(widget.accessibleName(), widget.objectName())
            self.assertTrue(widget.objectName().startswith("orch_"))
            self.assertEqual(widget.styleSheet(), "")      # keine Inline-Styles

    def test_leeres_senden_startet_keinen_faden(self):
        self.ansicht.senden()
        self.assertIsNone(self.ansicht.faden)
        self.assertIn("Nichts zu senden", self.ansicht.status.text())

    def test_senden_reicht_text_an_eigenen_faden(self):
        faden = mock.MagicMock()
        faden.isRunning.return_value = True
        self.ansicht.faden = faden
        self.ansicht.eingabe.setPlainText("Mach Folgendes")
        self.ansicht.senden()
        faden.auftrag_geben.assert_called_once_with("Mach Folgendes", [])
        self.assertEqual(self.ansicht.eingabe.toPlainText(), "")
        self.assertIn("Mach Folgendes", self.ansicht.verlauf.toPlainText())
        self.assertEqual(self.ansicht.titel.property("zustand"), "denkt")

    def test_antwort_wird_angezeigt_und_vorgelesen(self):
        a = self.ansicht
        a._offen = 1
        a._text("Erledigt, Empfehlung: ja.")
        a._fertig({"antwort": "Erledigt, Empfehlung: ja.", "fehler": ""})
        self.assertIn("Erledigt", a.verlauf.toPlainText())
        self.assertEqual(a.titel.text(), "Orchestrator: fertig")
        self.sprecher.sprich.assert_called_once_with("Erledigt, Empfehlung: ja.", art="fertig")

    def test_fehler_ist_rot_und_wird_gesagt(self):
        a = self.ansicht
        a._offen = 1
        a._fertig({"antwort": "", "fehler": "kaputt"})
        self.assertEqual(a.titel.property("zustand"), "fehler")
        self.assertIn("FEHLER", a.verlauf.toPlainText())
        self.assertEqual(self.sprecher.sprich.call_args.kwargs["art"], "fehler")

    def test_rueckfrage_wird_gemeldet_und_beantwortet(self):
        a = self.ansicht
        gemeldet = []
        a.frage_gestellt.connect(lambda satz, kurz: gemeldet.append((satz, kurz)))
        a.faden = mock.MagicMock()
        a._frage("Darf ich installieren?", "Installieren?")
        self.assertTrue(a.frage_offen)
        self.assertEqual(gemeldet, [("Darf ich installieren?", "Installieren?")])
        self.assertEqual(a.titel.property("zustand"), "wartet")
        a.frage_beantworten(True)
        self.assertFalse(a.frage_offen)
        a.faden.frage_beantworten.assert_called_once_with(True)

    def test_stopp_beruehrt_nur_den_eigenen_faden(self):
        faden = mock.MagicMock()
        faden.isRunning.return_value = True
        faden.faden_beschaeftigt = False
        self.ansicht.faden = faden
        self.ansicht.not_aus()
        faden.wartende_verwerfen.assert_called_once()
        faden.not_aus.assert_called_once()

    def test_zurueck_knopf_meldet_den_wunsch_und_hat_namen(self):
        a = self.ansicht
        gemeldet = []
        a.zurueck_gewuenscht.connect(lambda: gemeldet.append(1))
        a.zurueck_knopf.click()
        self.assertEqual(gemeldet, [1])
        self.assertEqual(a.zurueck_knopf.accessibleName(), "Zurück zu Claude Code")
        self.assertTrue(a.zurueck_knopf.toolTip())

    def test_orchestrator_farbe_ist_keine_zustandsfarbe(self):
        stil = (Path(__file__).resolve().parent.parent / "stil.qss").read_text(encoding="utf-8")
        kachel = re.search(r'#kachel\[farbe="orchestrator"\] \{\s*background-color: (#\w+)', stil)
        knopf = re.search(r'QPushButton#orch_zurueck \{\s*background-color: (#\w+)', stil)
        self.assertTrue(kachel and knopf)
        self.assertEqual(kachel.group(1), knopf.group(1))
        zustandsfarben = re.findall(
            r'(?:#orch_titel\[zustand=[^\]]*\]|#balken\[zustand=[^\]]*\])[^{]*\{[^}]*?background(?:-color)?:\s*(#\w+)',
            stil)
        self.assertNotIn(kachel.group(1).lower(), [f.lower() for f in zustandsfarben])

    def test_zustand_fuer_werkzeug_kommt_vom_fenster(self):
        self.ansicht.fenster_zustand_setzen(lambda: {"projekt": "X", "wartet": 3})
        self.assertEqual(self.ansicht.zustand()["wartet"], 3)

    # -- Titelfarbe: Zustand als Property, Farben nur in stil.qss -------------

    def _uhr(self):
        zeit = [100.0]
        self.ansicht._uhr = lambda: zeit[0]
        return zeit

    def _ereignis(self, zustand):
        self.ansicht._ereignis(zustand, "", "", "", "", False, False)

    def test_titel_zustand_je_ereignis(self):
        a = self.ansicht
        a._offen = 1
        zeit = self._uhr()
        for zustand, erwartet in (("liest", "liest"), ("sucht", "liest"), ("denkt", "denkt"),
                                  ("schreibt", "denkt"), ("fuehrt_aus", "denkt")):
            zeit[0] += 1
            self._ereignis(zustand)
            self.assertEqual(a.titel.property("zustand"), erwartet, zustand)

    def test_titel_fertig_fehler_gestoppt(self):
        a = self.ansicht
        zeit = self._uhr()
        for bilanz, erwartet in (({"antwort": "ok", "fehler": ""}, "fertig"),
                                 ({"antwort": "", "fehler": "kaputt"}, "fehler"),
                                 ({"antwort": "", "fehler": "", "abgebrochen": True}, "gestoppt")):
            zeit[0] += 1
            a._offen = 1
            a._fertig(bilanz)
            self.assertEqual(a.titel.property("zustand"), erwartet)
            self.assertIn(erwartet, a.titel.text().lower())      # Zustand auch als Wort

    def test_stopp_zeigt_grau(self):
        faden = mock.MagicMock()
        faden.isRunning.return_value = True
        faden.faden_beschaeftigt = False
        self.ansicht.faden = faden
        self.ansicht.not_aus()
        self.assertEqual(self.ansicht.titel.property("zustand"), "gestoppt")

    def test_spaetes_ereignis_uebermalt_gestoppt_nicht(self):
        a = self.ansicht
        zeit = self._uhr()
        a._zustand_zeigen("gestoppt", "gestoppt")
        zeit[0] += 1
        a._offen = 0
        self._ereignis("liest")
        self.assertEqual(a.titel.property("zustand"), "gestoppt")

    def test_mindestanzeigedauer_haelt_schnellen_wechsel_zurueck(self):
        a = self.ansicht
        zeit = self._uhr()
        a._zustand_zeigen("liest", "liest")
        zeit[0] += 0.1                                   # nur 100 ms spaeter
        a._zustand_zeigen("denkt", "denkt")
        self.assertEqual(a.titel.property("zustand"), "liest")     # noch sichtbar
        zeit[0] += 0.6
        a._zustand_nachholen()                           # was der Zeitgeber ausloest
        self.assertEqual(a.titel.property("zustand"), "denkt")
        self.assertEqual(a.titel.text(), "Orchestrator: denkt")

    def test_nur_der_letzte_zurueckgehaltene_zustand_zaehlt(self):
        a = self.ansicht
        zeit = self._uhr()
        a._zustand_zeigen("liest", "liest")
        zeit[0] += 0.1
        a._zustand_zeigen("denkt", "denkt")
        a._zustand_zeigen("fertig", "fertig")
        zeit[0] += 1
        a._zustand_nachholen()
        self.assertEqual(a.titel.property("zustand"), "fertig")

    def test_nach_der_mindestdauer_wechselt_es_sofort(self):
        a = self.ansicht
        zeit = self._uhr()
        a._zustand_zeigen("liest", "liest")
        zeit[0] += 0.7
        a._zustand_zeigen("denkt", "denkt")
        self.assertEqual(a.titel.property("zustand"), "denkt")

    def test_farben_stehen_nur_im_stilblatt(self):
        qss = (Path(__file__).resolve().parent.parent / "stil.qss").read_text(encoding="utf-8")
        for zustand in ("bereit", "liest", "denkt", "fertig", "fehler", "gestoppt"):
            if zustand != "bereit":
                self.assertIn(f'#orch_titel[zustand="{zustand}"]', qss)
        quelle = Path(orchestrator_ansicht.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(quelle, r"#[0-9a-fA-F]{6}\b")      # keine Farben im Python-Code

    def test_vorlesetext_wird_an_satzgrenze_gekuerzt(self):
        lang = "Ein Satz. " * 100
        kurz = orchestrator_ansicht.vorlese_text(lang)
        self.assertLessEqual(len(kurz), orchestrator_ansicht.VORLESEN_MAX_ZEICHEN)
        self.assertTrue(kurz.endswith("."))

    # -- Vorlesen-Knopf ------------------------------------------------------

    def _gesprochen(self):
        return [(c.args[0], c.kwargs) for c in self.sprecher.sprich.call_args_list]

    def _markieren(self, text):
        self.ansicht.verlauf.setPlainText(text)
        cursor = self.ansicht.verlauf.textCursor()
        cursor.select(cursor.SelectionType.Document)
        self.ansicht.verlauf.setTextCursor(cursor)

    def test_vorlesen_markierung_vor_letzter_antwort(self):
        self.ansicht._letzte_antwort = "Alte Antwort."
        self._markieren("Markierter Text. Zweiter Satz.")
        self.ansicht.vorlesen_knopf.click()
        self.assertEqual([t for t, _ in self._gesprochen()],
                         ["Markierter Text.", "Zweiter Satz."])
        self.assertTrue(all(k["art"] == "immer" for _, k in self._gesprochen()))
        self.assertTrue(self._gesprochen()[1][1]["unterbrechen"] is False)
        self.assertEqual(self.ansicht.vorlesen_knopf.text(), "■ Lesen")
        self.ansicht._vorlesen_beendet()

    def test_vorlesen_ohne_markierung_letzte_antwort(self):
        self.ansicht._fertig_anzeigen({"antwort": "Das ist die Antwort."})
        self.sprecher.reset_mock()
        self.ansicht.vorlesen_knopf.click()
        self.assertEqual([t for t, _ in self._gesprochen()], ["Das ist die Antwort."])
        self.ansicht._vorlesen_beendet()

    def test_vorlesen_nichts_da(self):
        self.ansicht.vorlesen_knopf.click()
        self.assertEqual(self._gesprochen(), [("Nichts zum Vorlesen.", {"art": "immer"})])
        self.assertEqual(self.ansicht.vorlesen_knopf.text(), "Vorlesen")

    def test_zweiter_klick_bricht_ab(self):
        self._markieren("Ein Satz. Noch ein Satz.")
        self.sprecher.spricht.return_value = True
        self.ansicht.vorlesen_knopf.click()
        self.assertEqual(self.ansicht.vorlesen_knopf.text(), "■ Lesen")
        gesprochen = self.sprecher.sprich.call_count
        self.ansicht.vorlesen_knopf.click()
        self.sprecher.schweig.assert_called_once()
        self.assertEqual(self.sprecher.sprich.call_count, gesprochen)   # nichts Neues
        self.assertEqual(self.ansicht.vorlesen_knopf.text(), "Vorlesen")

    def test_knopf_zurueck_wenn_sprecher_fertig(self):
        self._markieren("Ein Satz.")
        self.sprecher.spricht.return_value = True
        self.ansicht.vorlesen_knopf.click()
        self.sprecher.spricht.return_value = False
        self.ansicht._vorlesen_pruefen()
        self.assertEqual(self.ansicht.vorlesen_knopf.text(), "Vorlesen")

    def test_klick_hebt_markierung_nicht_auf(self):
        a = self.ansicht
        a.show()
        self.addCleanup(a.hide)
        self._markieren("Markierter Text.")
        a.verlauf.setFocus()
        self.assertEqual(a.vorlesen_knopf.focusPolicy(), Qt.TabFocus)   # kein Klick-Fokus
        a.vorlesen_knopf.click()
        self.assertEqual(a.verlauf.textCursor().selectedText(), "Markierter Text.")
        a._vorlesen_beendet()

    def test_vorlesen_knopf_namen_und_farbe_nur_in_qss(self):
        k = self.ansicht.vorlesen_knopf
        self.assertEqual(k.objectName(), "orch_vorlesen")
        self.assertTrue(k.accessibleName())
        self.assertEqual(k.styleSheet(), "")
        qss = (Path(orchestrator_ansicht.__file__).parent.parent / "stil.qss").read_text(encoding="utf-8")
        self.assertIn("QPushButton#orch_vorlesen", qss)

    # -- Knopfbreite und Zeile -----------------------------------------------

    def _mit_stilblatt(self, faktor):
        """Legt stil.qss skaliert an und stellt den alten Stand danach wieder her."""
        alt = self.anwendung.styleSheet()
        roh = (Path(orchestrator_ansicht.__file__).parent.parent / "stil.qss").read_text(encoding="utf-8")
        self.anwendung.setStyleSheet(grundlagen._stil_skaliert(roh, faktor))
        self.addCleanup(self.anwendung.setStyleSheet, alt)

    def _zeigen(self, breite):
        a = self.ansicht
        a.resize(breite, 700)
        a.show()
        self.addCleanup(a.hide)
        self.anwendung.processEvents()
        self.anwendung.processEvents()

    def test_knopfbreite_bleibt_beim_beschriftungswechsel(self):
        for faktor in (1.0, 1.8):
            self._mit_stilblatt(faktor)
            self._zeigen(950)
            k = self.ansicht.vorlesen_knopf
            k.setText(orchestrator_ansicht.VORLESEN_WORT)
            ruhe = k.width()
            k.setText(orchestrator_ansicht.VORLESEN_STOPP_WORT)
            self.anwendung.processEvents()
            self.assertEqual(k.width(), ruhe, faktor)
            k.setText(orchestrator_ansicht.VORLESEN_WORT)

    def test_vorlesen_knopf_nicht_breiter_als_stopp(self):
        for faktor in (1.0, 1.8):
            self._mit_stilblatt(faktor)
            self._zeigen(600)
            a = self.ansicht
            toleranz = a.stopp_knopf.fontMetrics().averageCharWidth()
            self.assertLessEqual(a.vorlesen_knopf.width(), a.stopp_knopf.width() + toleranz, faktor)
            # Beschriftung passt vollstaendig hinein (nichts abgeschnitten).
            for wort in (orchestrator_ansicht.VORLESEN_WORT, orchestrator_ansicht.VORLESEN_STOPP_WORT):
                a.vorlesen_knopf.setText(wort)
                self.assertLessEqual(a.vorlesen_knopf.sizeHint().width(), a.vorlesen_knopf.width(), (faktor, wort))
            a.vorlesen_knopf.setText(orchestrator_ansicht.VORLESEN_WORT)

    def test_eingabefeld_behaelt_dehnung_und_platz(self):
        a = self.ansicht
        zeile = a.eingabe.parentWidget().layout()
        self.assertEqual(zeile.stretch(zeile.indexOf(a.eingabe)), 1)
        for knopf in (a.senden_knopf, a.stopp_knopf):
            self.assertEqual(zeile.stretch(zeile.indexOf(knopf)), 0)
        self.assertEqual(zeile.indexOf(a.vorlesen_knopf), -1)       # eigene Zeile
        for faktor in (1.0, 1.8):
            self._mit_stilblatt(faktor)
            self._zeigen(600)
            ohne_vorlesen = a.width() - a.senden_knopf.width() - a.stopp_knopf.width()
            self.assertGreaterEqual(a.eingabe.width(), min(ohne_vorlesen, a.width()) // 2 - 40, faktor)
            self.assertGreater(a.eingabe.width(), a.stopp_knopf.width(), faktor)

    def test_tabreihenfolge_bleibt(self):
        a = self.ansicht
        kette, w = [], a.eingabe
        for _ in range(30):
            w = w.nextInFocusChain()
            if w in (a.senden_knopf, a.stopp_knopf, a.vorlesen_knopf):
                kette.append(w)
        self.assertEqual(kette[:3], [a.senden_knopf, a.stopp_knopf, a.vorlesen_knopf])


class FensterRoutingTest(unittest.TestCase):
    """Strg+Eingabe, Eingabe und Escape je nach Ansicht - ohne echtes Fenster."""

    def fenster(self, sichtbar, frage_orch=False, frage_main=False):
        ansicht = mock.MagicMock(spec=orchestrator_ansicht.OrchestratorAnsicht)
        ansicht.frage_offen = frage_orch
        f = types.SimpleNamespace(
            _orch_ansicht=ansicht, _orch_stapel=mock.MagicMock(),
            frage_offen=frage_main, sprecher=mock.MagicMock(),
            _absenden=mock.MagicMock(), _frage_beantworten=mock.MagicMock(),
            _pending_block=None)
        f._orch_stapel.currentWidget.return_value = ansicht if sichtbar else object()
        f._orch_sichtbar = lambda: fenster.Werkbank._orch_sichtbar(f)
        f.sprecher.spricht.return_value = False
        return f

    def test_senden_in_orchestrator_ansicht(self):
        f = self.fenster(sichtbar=True)
        fenster.Werkbank._senden_taste(f)
        f._orch_ansicht.senden.assert_called_once()
        f._absenden.assert_not_called()

    def test_senden_in_normaler_ansicht(self):
        f = self.fenster(sichtbar=False)
        fenster.Werkbank._senden_taste(f)
        f._absenden.assert_called_once()
        f._orch_ansicht.senden.assert_not_called()

    def test_enter_beantwortet_orchestratorfrage_mit_ja(self):
        f = self.fenster(sichtbar=False, frage_orch=True)
        fenster.Werkbank._enter(f)
        f._orch_ansicht.frage_beantworten.assert_called_once_with(True)
        f._frage_beantworten.assert_not_called()

    def test_hauptfrage_hat_vorrang(self):
        f = self.fenster(sichtbar=False, frage_orch=True, frage_main=True)
        fenster.Werkbank._enter(f)
        f._frage_beantworten.assert_called_once_with(True)
        f._orch_ansicht.frage_beantworten.assert_not_called()

    def test_escape_beantwortet_orchestratorfrage_mit_nein(self):
        f = self.fenster(sichtbar=False, frage_orch=True)
        fenster.Werkbank._escape(f)
        f._orch_ansicht.frage_beantworten.assert_called_once_with(False)


class SicherheitsregelnTest(unittest.TestCase):
    """Was sicherheit.py mit den Befehlen tut, die der Orchestrator braucht.
    Keine Lockerung: das hier belegt nur den Ist-Stand."""

    def setUp(self):
        self.grenze = sicherheit.Ordnergrenze(Path(tempfile.gettempdir()))

    def stufe(self, befehl):
        return self.grenze.pruefe_befehl(befehl).stufe

    def test_adb_install_und_gradlew_sind_frei(self):
        self.assertIs(self.stufe("adb install -r app/build/outputs/apk/debug/app-debug.apk"),
                      Stufe.FREI)
        self.assertIs(self.stufe("./gradlew assembleDebug"), Stufe.FREI)
        self.assertIs(self.stufe("adb devices"), Stufe.FREI)

    def test_gefaehrliches_bleibt_gesperrt(self):
        self.assertIs(self.stufe("rm -rf /"), Stufe.VERBOTEN)
        self.assertIs(self.stufe("shutdown now"), Stufe.VERBOTEN)

    def test_rueckfrage_regeln_unveraendert(self):
        self.assertIs(self.stufe("sudo ls"), Stufe.RUECKFRAGE)
        self.assertIs(self.stufe("pip install x"), Stufe.RUECKFRAGE)


class AnweisungTest(unittest.TestCase):
    """Inhalt der Anweisung und Projektliste aus der Konfiguration."""

    def test_anweisung_enthaelt_duzen_kuerze_und_arbeitsteilung(self):
        text = orchestrator.anweisung_lesen()
        self.assertIn("duzt", text)
        self.assertIn("Höchstens drei kurze Sätze", text)
        self.assertIn("## Arbeitsteilung", text)
        self.assertIn("Sonnet", text)
        self.assertIn("Projekte", text)

    def test_projektliste_mit_mehreren_projekten(self):
        liste = [types.SimpleNamespace(name="CWB", pfad=Path("/p/CWB")),
                 types.SimpleNamespace(name="HAUSGEMACHT", pfad=Path("/p/hg"))]
        text = orchestrator.projektliste_text(liste)
        self.assertIn("- CWB: /p/CWB", text)
        self.assertIn("- HAUSGEMACHT: /p/hg", text)

    def test_projektliste_leer(self):
        text = orchestrator.projektliste_text([])
        self.assertIn("Keine Projekte bekannt", text)

    def test_projektliste_kommt_aus_der_verwaltung(self):
        liste = [types.SimpleNamespace(name="X", pfad=Path("/p/x"))]
        with mock.patch.object(sicherheit, "projekte_finden", return_value=liste):
            self.assertIn("- X: /p/x", orchestrator.projektliste_text())

    def test_sitzung_traegt_projektliste(self):
        faden = orchestrator_ansicht.OrchestratorFaden(
            Projekt("T", Path(tempfile.gettempdir()), False))
        with mock.patch.object(sicherheit.Wache, "oeffnen"), \
                mock.patch.object(orchestrator, "werkzeuge_bauen", return_value={"type": "sdk"}), \
                mock.patch.object(orchestrator, "projektliste_text", return_value="## Bekannte Projekte\n- Z: /z"):
            s = faden._sitzung_bauen()
        self.assertIn("- Z: /z", s.system_zusatz)


if __name__ == "__main__":
    unittest.main()
