"""
CWB - Code Workbench
Tests fuer die Absturzsicherheit (core/absturzschutz.py, core/aufpasser.py,
unterbrochene_markieren in core/eingangsordner.py, Qt-Handler in
core/grundlagen.py). Alles mit Attrappen: kein echter Absturz, kein echter
Kindprozess, kein echter Datenordner.

Aufruf: .venv/bin/python -m unittest core.test_absturzschutz -v
"""

import json
import logging
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from . import absturzschutz, aufpasser, eingangsordner, grundlagen
    from .test_eingangsordner import markierung_erkennen
except ImportError:
    import absturzschutz
    import aufpasser
    import eingangsordner
    import grundlagen
    from test_eingangsordner import markierung_erkennen

log = logging.getLogger("cwb.test_absturzschutz")


class LaufMarkerTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.marker = Path(self._tmp.name) / "lauf.marker"
        self.addCleanup(setattr, absturzschutz, "_unsauber_gemerkt", None)

    def test_erster_start_ist_sauber(self):
        self.assertFalse(absturzschutz.lauf_beginnen(self.marker))
        self.assertTrue(self.marker.exists())

    def test_sauberes_ende_loescht_marker(self):
        absturzschutz.lauf_beginnen(self.marker)
        absturzschutz.lauf_beenden_sauber(self.marker)
        self.assertFalse(self.marker.exists())
        self.assertFalse(absturzschutz.lauf_beginnen(self.marker))

    def test_stehender_marker_heisst_unsauber(self):
        absturzschutz.lauf_beginnen(self.marker)  # Lauf endet ohne Loeschen
        with self.assertLogs("cwb.absturzschutz", level="WARNING") as erfasst:
            self.assertTrue(absturzschutz.lauf_beginnen(self.marker))
        self.assertTrue(any("Letzter Lauf endete unsauber" in z for z in erfasst.output))

    def test_unsauber_wird_nur_einmal_abgeholt(self):
        self.marker.write_text("{}")
        absturzschutz.lauf_beginnen(self.marker)
        self.assertTrue(absturzschutz.unsauber_abholen())
        self.assertFalse(absturzschutz.unsauber_abholen())

    def test_beenden_ohne_marker_wirft_nichts(self):
        absturzschutz.lauf_beenden_sauber(self.marker)


class CrashDateiTest(unittest.TestCase):

    def test_haengt_an_und_schneidet_grosse_datei_ab(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "crash.log"
            pfad.write_text("x" * 5000, encoding="utf-8")
            datei = absturzschutz.crash_datei_oeffnen(pfad, max_bytes=1000)
            datei.close()
            text = pfad.read_text(encoding="utf-8")
            self.assertNotIn("xxxx", text)
            self.assertIn("--- Lauf", text)
            datei = absturzschutz.crash_datei_oeffnen(pfad, max_bytes=1000)
            datei.close()
            self.assertEqual(pfad.read_text(encoding="utf-8").count("--- Lauf"), 2)


class ProzessendeTest(unittest.TestCase):

    def test_wertung(self):
        w = absturzschutz.prozessende_werten
        self.assertEqual(w(0), "ende")
        self.assertEqual(w(absturzschutz.EXIT_NEUSTART), "neustart")
        self.assertEqual(w(-int(signal.SIGTERM)), "ende")
        self.assertEqual(w(-int(signal.SIGINT)), "ende")
        self.assertEqual(w(-int(signal.SIGSEGV)), "absturz")
        self.assertEqual(w(-int(signal.SIGABRT)), "absturz")
        self.assertEqual(w(1), "absturz")


class NeustartSchutzTest(unittest.TestCase):

    def test_drei_in_fuenf_minuten_dann_schluss(self):
        zeit = [1000.0]
        schutz = absturzschutz.NeustartSchutz(None, uhr=lambda: zeit[0])
        self.assertTrue(schutz.neustart_erlaubt())
        zeit[0] += 60
        self.assertTrue(schutz.neustart_erlaubt())
        zeit[0] += 60
        self.assertTrue(schutz.neustart_erlaubt())
        zeit[0] += 60
        self.assertFalse(schutz.neustart_erlaubt())

    def test_nach_fuenf_minuten_wieder_erlaubt(self):
        zeit = [0.0]
        schutz = absturzschutz.NeustartSchutz(None, uhr=lambda: zeit[0])
        for _ in range(3):
            self.assertTrue(schutz.neustart_erlaubt())
        self.assertFalse(schutz.neustart_erlaubt())
        zeit[0] += 301
        self.assertTrue(schutz.neustart_erlaubt())

    def test_stand_ueberlebt_neuen_aufpasser(self):
        with tempfile.TemporaryDirectory() as tmp:
            datei = Path(tmp) / "n.json"
            zeit = [500.0]
            for _ in range(3):
                self.assertTrue(
                    absturzschutz.NeustartSchutz(datei, uhr=lambda: zeit[0]).neustart_erlaubt())
            self.assertFalse(
                absturzschutz.NeustartSchutz(datei, uhr=lambda: zeit[0]).neustart_erlaubt())

    def test_kaputte_datei_zaehlt_als_leer(self):
        with tempfile.TemporaryDirectory() as tmp:
            datei = Path(tmp) / "n.json"
            datei.write_text("kein json")
            self.assertTrue(absturzschutz.NeustartSchutz(datei).neustart_erlaubt())


class _Attrappe:
    def __init__(self, code):
        self.code = code
        self.pid = 1

    def wait(self):
        return self.code


class AufpasserTest(unittest.TestCase):

    def _lauf(self, codes, schutz=None):
        aufrufe = []
        folge = iter(codes)

        def starten(argumente, nach_absturz):
            aufrufe.append(nach_absturz)
            return _Attrappe(next(folge))

        schutz = schutz or absturzschutz.NeustartSchutz(None)
        with self.assertLogs("cwb.aufpasser", level="INFO") as erfasst:
            ergebnis = aufpasser.beobachten([], schutz, starten)
        return ergebnis, aufrufe, "\n".join(erfasst.output)

    def test_sauberes_ende_greift_nicht_ein(self):
        ergebnis, aufrufe, _ = self._lauf([0])
        self.assertEqual((ergebnis, aufrufe), (0, [False]))

    def test_nutzer_beenden_greift_nicht_ein(self):
        _, aufrufe, _ = self._lauf([-int(signal.SIGTERM)])
        self.assertEqual(aufrufe, [False])

    def test_absturz_startet_neu_mit_marke_und_dann_sauber(self):
        ergebnis, aufrufe, _ = self._lauf([-int(signal.SIGSEGV), 0])
        self.assertEqual((ergebnis, aufrufe), (0, [False, True]))

    def test_gewollter_neustart_belastet_zaehler_nicht(self):
        schutz = absturzschutz.NeustartSchutz(None)
        _, aufrufe, _ = self._lauf([absturzschutz.EXIT_NEUSTART] * 5 + [0], schutz)
        self.assertEqual(aufrufe, [False] * 6)
        self.assertEqual(len(schutz._zeiten), 0)

    def test_drei_neustarts_dann_neustart_schutz(self):
        ergebnis, aufrufe, text = self._lauf([-11, -11, -11, -11, 0])
        self.assertEqual(ergebnis, 1)
        self.assertEqual(len(aufrufe), 4)  # erster Start + 3 Neustarts
        self.assertIn("Neustart-Schutz", text)


class UnterbrocheneAuftraegeTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ordner = Path(self._tmp.name) / "eingang"
        patch = mock.patch.object(eingangsordner, "EINGANG_ORDNER", self.ordner)
        patch.start()
        self.addCleanup(patch.stop)
        journal = mock.patch.object(eingangsordner.auftragsjournal, "schreibe")
        self.journal = journal.start()
        self.addCleanup(journal.stop)
        eingangsordner.sicherstellen()
        eingangsordner.annahmen_zuruecksetzen()
        self.addCleanup(eingangsordner.annahmen_zuruecksetzen)

    def _in_laeuft(self, name, nummer=None, quelle="bruecke", text="#CODE#\nTu etwas."):
        daten = {"quelle": quelle, "projekt": "CWB", "text": text}
        if nummer is not None:
            daten["auftrag_nummer"] = nummer
        pfad = eingangsordner.laeuft_ordner() / name
        pfad.write_text(json.dumps(daten), encoding="utf-8")
        return pfad

    def test_laufender_auftrag_wird_markiert_und_nicht_wiederholt(self):
        self._in_laeuft("a.json", nummer=7)
        ergebnis = eingangsordner.unterbrochene_markieren(markierung_erkennen, "CWB")
        self.assertEqual([a.auftrag_nummer for a in ergebnis], [7])
        self.assertFalse((eingangsordner.laeuft_ordner() / "a.json").exists())
        self.assertTrue((eingangsordner.unterbrochen_ordner() / "a.json").exists())
        self.assertTrue((eingangsordner.unterbrochen_ordner() / "a.txt").exists())
        schritte = [aufruf.args[0] for aufruf in self.journal.call_args_list]
        self.assertIn("unterbrochen", schritte)
        # Danach gibt es nichts mehr, was wieder_aufnehmen anstossen koennte.
        ausfuehren = mock.Mock()
        self.assertEqual(
            eingangsordner.wieder_aufnehmen(markierung_erkennen, "CWB", ausfuehren), (0, 0, 0))
        ausfuehren.assert_not_called()

    def test_fertiger_bericht_wird_nicht_erneut_gemeldet(self):
        self._in_laeuft("b.json", nummer=8)
        eingangsordner.bericht_vermerken(8)
        ergebnis = eingangsordner.unterbrochene_markieren(markierung_erkennen, "CWB")
        self.assertEqual(ergebnis, [])
        self.assertTrue((eingangsordner.erledigt_ordner() / "b.json").exists())

    def test_fremdes_projekt_bleibt_liegen(self):
        pfad = self._in_laeuft("c.json", nummer=9)
        daten = json.loads(pfad.read_text())
        daten["projekt"] = "Anderes"
        pfad.write_text(json.dumps(daten))
        self.assertEqual(eingangsordner.unterbrochene_markieren(markierung_erkennen, "CWB"), [])
        self.assertTrue(pfad.exists())

    def test_orchestrator_meldet_unterbrochen(self):
        try:
            from . import orchestrator
        except ImportError:
            import orchestrator
        self._in_laeuft("d.json", nummer=1000123, quelle="orchestrator")
        eingangsordner._nummer_beanspruchen(1000123, "d.json")
        with mock.patch.object(orchestrator, "berichte_ordner",
                               return_value=Path(self._tmp.name) / "berichte"):
            vorher = orchestrator.bericht_holen(1000123)
            eingangsordner.unterbrochene_markieren(markierung_erkennen, "CWB")
            nachher = orchestrator.bericht_holen(1000123)
        self.assertIn("noch nicht fertig", vorher)
        self.assertIn("UNTERBROCHEN", nachher)
        self.assertIn("neu bestellen", nachher)


class QtMeldungenTest(unittest.TestCase):

    def setUp(self):
        self._alt = grundlagen._qt_atspi_zaehler
        grundlagen._qt_atspi_zaehler = 0
        self.addCleanup(setattr, grundlagen, "_qt_atspi_zaehler", self._alt)

    def test_handler_schreibt_meldung_mit_stufe_ins_log(self):
        from PySide6.QtCore import QtMsgType
        with self.assertLogs("cwb.grundlagen", level="DEBUG") as erfasst:
            grundlagen.qt_meldung_behandeln(QtMsgType.QtCriticalMsg, None, "etwas kaputt")
            grundlagen.qt_meldung_behandeln(QtMsgType.QtWarningMsg, None, "nur Warnung")
        self.assertEqual([r.levelno for r in erfasst.records], [logging.ERROR, logging.WARNING])
        self.assertIn("etwas kaputt", erfasst.output[0])

    def test_setposition_meldung_wird_gezaehlt_statt_geflutet(self):
        from PySide6.QtCore import QtMsgType
        with self.assertLogs("cwb.grundlagen", level="DEBUG") as erfasst:
            for ende in (50, 100, 150, 200):
                grundlagen.qt_meldung_behandeln(
                    QtMsgType.QtWarningMsg, None,
                    f"QTextCursor::setPosition: Position '{ende}' out of range")
            grundlagen.qt_meldung_behandeln(QtMsgType.QtWarningMsg, None, "andere Meldung")
        self.assertEqual(len(erfasst.records), 2)  # eine Erklaerung + die andere Meldung
        self.assertEqual(grundlagen.qt_atspi_meldungen_gezaehlt(), 4)
        self.assertIn("AT-SPI", erfasst.output[0])

    def test_andere_setposition_meldung_bleibt_sichtbar(self):
        from PySide6.QtCore import QtMsgType
        with self.assertLogs("cwb.grundlagen", level="DEBUG") as erfasst:
            grundlagen.qt_meldung_behandeln(
                QtMsgType.QtWarningMsg, None, "QTextCursor::setPosition: Position '-1' out of range")
        self.assertEqual(len(erfasst.records), 1)


if __name__ == "__main__":
    unittest.main()
