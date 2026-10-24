"""
CWB - Code Workbench
Tests fuer das Diktat (core/diktat.py und der Knopf in der Orchestrator-
Ansicht). Ohne echtes Mikrofon und ohne echtes Modell: Aufnahme und Erkennung
sind ausgetauscht. Wortliste und Einstellungen liegen im Temp-Verzeichnis,
nichts geht in den echten Datenordner.

Aufruf: python -m unittest core.test_diktat -v
"""

import logging
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

try:
    from . import diktat
except ImportError:
    import diktat

SEKUNDEN = 2
ERKANNT = "Bitte prüfe das Projekt CWB. Eingabetaste."


class FalscherAufnehmer:
    def __init__(self, sekunden=SEKUNDEN):
        self.sekunden = sekunden

    def starten(self):
        pass

    def beenden(self):
        return np.zeros(int(diktat.ABTASTRATE * self.sekunden), dtype="float32")


class FalschesModell:
    def __init__(self, text=ERKANNT):
        self.aufrufe = []
        self.text = text

    def transcribe(self, audio, **kwargs):
        self.aufrufe.append(kwargs)
        return iter([mock.Mock(text=self.text)]), mock.Mock()


class DiktatBasisTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ordner = Path(temp.name)
        self.woerter = self.ordner / "diktat_woerter.txt"
        self.einstellungen = {}
        for p in (mock.patch.object(diktat, "einstellungen_lesen",
                                    side_effect=lambda: dict(self.einstellungen)),
                  mock.patch.object(diktat, "schluessel_da", return_value=False)):
            p.start()
            self.addCleanup(p.stop)

    def _lauf(self, modell, aufnehmer=None, bereinigen_aufruf=None):
        d = diktat.Diktat(aufnehmer_fabrik=lambda: aufnehmer or FalscherAufnehmer(),
                          modell_fabrik=lambda name: modell,
                          bereinigen_aufruf=bereinigen_aufruf,
                          woerter_datei=self.woerter)
        d.starten()
        ergebnis = {}
        fertig = threading.Event()

        def ok(text, senden):
            ergebnis.update(text=text, senden=senden)
            fertig.set()

        def fehler(satz):
            ergebnis.update(fehler=satz)
            fertig.set()

        def leer():
            ergebnis.update(leer=True)
            fertig.set()

        d.beenden(ok, fehler, leer)
        self.assertTrue(fertig.wait(10))
        return ergebnis


class ErkennungTest(DiktatBasisTest):
    def test_sprache_fest_deutsch_vad_wortliste_als_prompt(self):
        modell = FalschesModell()
        self._lauf(modell)
        aufruf = modell.aufrufe[0]
        self.assertEqual(aufruf["language"], "de")
        self.assertIs(aufruf["vad_filter"], True)
        self.assertEqual(aufruf["beam_size"], 1)
        for wort in ("CWB", "Orchestrator", "Claude Code", "Wispr Flow", "Leitstand"):
            self.assertIn(wort, aufruf["initial_prompt"])

    def test_wortliste_wird_mit_vorgaben_angelegt_und_nicht_ueberschrieben(self):
        diktat.woerter_anlegen(self.woerter)
        self.assertEqual(diktat.woerter_lesen(self.woerter), diktat.STANDARD_WOERTER)
        self.woerter.write_text("Eigenwort\n", encoding="utf-8")
        diktat.woerter_anlegen(self.woerter)
        self.assertEqual(diktat.woerter_lesen(self.woerter), ["Eigenwort"])

    def test_eigene_woerter_gehen_in_den_prompt(self):
        self.woerter.write_text("Zebra\nKolibri\n", encoding="utf-8")
        modell = FalschesModell()
        self._lauf(modell)
        self.assertEqual(modell.aufrufe[0]["initial_prompt"], "Zebra, Kolibri")

    def test_sendewort_am_ende_wird_entfernt_und_sendet(self):
        ergebnis = self._lauf(FalschesModell())
        self.assertEqual(ergebnis, {"text": "Bitte prüfe das Projekt CWB.", "senden": True})

    def test_eigenes_sendewort(self):
        self.einstellungen["diktat_sendewort"] = "Abschicken"
        ergebnis = self._lauf(FalschesModell("Hallo Welt, abschicken."))
        self.assertEqual(ergebnis, {"text": "Hallo Welt", "senden": True})

    def test_sendewort_mitten_im_text_loest_nichts_aus(self):
        text, senden = diktat.befehl_auswerten("Die Eingabetaste klemmt bei mir", "Eingabetaste")
        self.assertEqual((text, senden), ("Die Eingabetaste klemmt bei mir", False))
        ergebnis = self._lauf(FalschesModell("Drück die Eingabetaste noch einmal, bitte."))
        self.assertIs(ergebnis["senden"], False)
        self.assertIn("Eingabetaste", ergebnis["text"])

    def test_zu_kurze_aufnahme_ist_leer(self):
        modell = FalschesModell()
        ergebnis = self._lauf(modell, aufnehmer=FalscherAufnehmer(0.1))
        self.assertEqual(ergebnis, {"leer": True})
        self.assertEqual(modell.aufrufe, [])

    def test_fehlendes_modell_meldet_satz(self):
        def fabrik(name):
            raise diktat.DiktatFehler(f"Whisper-Modell {name} nicht gefunden.")
        d = diktat.Diktat(aufnehmer_fabrik=FalscherAufnehmer, modell_fabrik=fabrik,
                          woerter_datei=self.woerter)
        d.starten()
        ergebnis = {}
        fertig = threading.Event()
        d.beenden(lambda t, s: fertig.set(),
                  lambda satz: (ergebnis.update(satz=satz), fertig.set()),
                  fertig.set)
        self.assertTrue(fertig.wait(10))
        self.assertIn("nicht gefunden", ergebnis["satz"])
        self.assertFalse(d.erkennt)

    def test_kein_mikrofon_wirft_diktatfehler(self):
        class Kaputt:
            def starten(self):
                raise diktat.DiktatFehler("Kein Mikrofon gefunden.")
        d = diktat.Diktat(aufnehmer_fabrik=Kaputt, modell_fabrik=lambda n: FalschesModell(),
                          woerter_datei=self.woerter)
        with self.assertRaises(diktat.DiktatFehler):
            d.starten()
        self.assertFalse(d.nimmt_auf)

    def test_modell_vorgabe_und_wahl(self):
        self.assertEqual(diktat.modell_name(), diktat.STANDARD_MODELL)
        self.einstellungen["diktat_modell"] = "small"
        self.assertEqual(diktat.modell_name(), "small")
        self.einstellungen["diktat_modell"] = "riesig"
        self.assertEqual(diktat.modell_name(), diktat.STANDARD_MODELL)


class StandardUndUmstellungTest(DiktatBasisTest):
    def test_standardwerte(self):
        self.assertEqual(diktat.STANDARD_MODELL, "small")
        self.assertEqual(diktat.BEAM_GROESSE, 1)
        self.assertEqual(diktat.RECHEN_FAEDEN, 8)
        self.assertEqual(diktat.RECHENART, "int8")
        self.assertEqual(diktat.SPRACHE, "de")

    def test_echtes_modell_bekommt_acht_faeden(self):
        fabrik = mock.Mock()
        with mock.patch.dict("sys.modules", {"faster_whisper": mock.Mock(WhisperModel=fabrik)}):
            diktat._echtes_modell("small")
        kwargs = fabrik.call_args.kwargs
        self.assertEqual(kwargs["cpu_threads"], 8)
        self.assertEqual(kwargs["compute_type"], "int8")

    def _mit_schreiber(self):
        geschrieben = []
        def schreiben(werte):
            geschrieben.append(dict(werte))
            self.einstellungen.clear()
            self.einstellungen.update(werte)
        p = mock.patch.object(diktat, "einstellungen_schreiben", side_effect=schreiben)
        p.start()
        self.addCleanup(p.stop)
        return geschrieben

    def test_medium_wird_einmalig_auf_small_gestellt(self):
        geschrieben = self._mit_schreiber()
        self.einstellungen.update(diktat_modell="medium", anderes=1)
        self.assertTrue(diktat.medium_einmalig_umstellen())
        self.assertEqual(self.einstellungen["diktat_modell"], "small")
        self.assertEqual(self.einstellungen["anderes"], 1)
        # Wer danach medium waehlt, behaelt es.
        self.einstellungen["diktat_modell"] = "medium"
        self.assertFalse(diktat.medium_einmalig_umstellen())
        self.assertEqual(self.einstellungen["diktat_modell"], "medium")
        self.assertEqual(len(geschrieben), 1)

    def test_andere_einstellung_bleibt_unberuehrt(self):
        self._mit_schreiber()
        self.einstellungen["diktat_modell"] = "small"
        self.assertFalse(diktat.medium_einmalig_umstellen())
        self.assertEqual(self.einstellungen["diktat_modell"], "small")

    def test_vorladen_blockiert_nicht(self):
        self._mit_schreiber()
        self.einstellungen["orchestrator"] = True
        freigabe = threading.Event()
        geladen = threading.Event()
        def langsam(name):
            freigabe.wait(10)
            geladen.set()
            return FalschesModell()
        erkenner = diktat.Erkenner(langsam)
        with mock.patch.object(diktat, "_GEMEINSAMER_ERKENNER", erkenner):
            diktat.beim_start_vorladen()      # kehrt sofort zurueck, Laden haengt noch
            self.assertFalse(geladen.is_set())
            freigabe.set()
            self.assertTrue(geladen.wait(10))

    def test_gemeinsamer_erkenner_haelt_modell(self):
        aufrufe = []
        erkenner = diktat.Erkenner(lambda n: aufrufe.append(n) or FalschesModell())
        erkenner.holen("small")
        erkenner.holen("small")
        self.assertEqual(aufrufe, ["small"])


class BereinigungTest(DiktatBasisTest):
    def test_fehler_gibt_original(self):
        def kaputt(text):
            raise diktat.DiktatFehler("Timeout")
        self.assertEqual(diktat.bereinigen("hallo welt", kaputt), "hallo welt")

    def test_leeres_ergebnis_gibt_original(self):
        self.assertEqual(diktat.bereinigen("hallo welt", lambda t: "  "), "hallo welt")

    def test_abweichung_ueber_dreissig_prozent_gibt_original(self):
        original = "das ist ein ganz normaler satz"
        self.assertEqual(diktat.bereinigen(original, lambda t: t + " und noch ganz viel mehr Text"),
                         original)
        self.assertEqual(diktat.bereinigen(original, lambda t: "kurz"), original)

    def test_gute_bereinigung_wird_uebernommen(self):
        self.assertEqual(diktat.bereinigen("hallo welt äh wie gehts", lambda t: "Hallo Welt, wie geht's?"),
                         "Hallo Welt, wie geht's?")

    def test_bereinigung_im_ablauf_und_sendewort_bleibt(self):
        ergebnis = self._lauf(FalschesModell("hallo welt eingabetaste"),
                              bereinigen_aufruf=lambda t: t.capitalize() + ".")
        self.assertEqual(ergebnis, {"text": "Hallo welt.", "senden": True})

    def test_ohne_schluessel_still_aus(self):
        self.assertFalse(diktat.bereinigung_aktiv())
        with mock.patch.object(diktat, "schluessel_da", return_value=True):
            self.assertTrue(diktat.bereinigung_aktiv())
            self.einstellungen["diktat_bereinigung"] = False
            self.assertFalse(diktat.bereinigung_aktiv())

    def test_schluessel_steht_nie_im_log(self):
        antwort = mock.Mock()
        antwort.raise_for_status.side_effect = diktat.requests.RequestException("url?key=GEHEIM123")
        with mock.patch.object(diktat.leitstand, "api_schluessel_lesen", return_value="GEHEIM123"), \
                mock.patch.object(diktat.requests, "post", return_value=antwort), \
                self.assertLogs("cwb.diktat", level="DEBUG") as erfasst:
            self.assertEqual(diktat.bereinigen("hallo welt"), "hallo welt")
        self.assertNotIn("GEHEIM123", "\n".join(erfasst.output))


class DatenschutzTest(DiktatBasisTest):
    def test_log_enthaelt_nie_den_text(self):
        with self.assertLogs("cwb.diktat", level="DEBUG") as erfasst:
            self._lauf(FalschesModell("Streng geheimer Satz Eingabetaste"))
        log_text = "\n".join(erfasst.output)
        self.assertNotIn("geheimer", log_text)
        self.assertIn("Zeichen", log_text)
        self.assertIn("small", log_text)
        self.assertIn("Laden", log_text)
        self.assertIn("Erkennen", log_text)
        self.assertIn("Bereinigung", log_text)

    def test_audio_wird_nicht_gespeichert(self):
        quelle = Path(diktat.__file__).read_text(encoding="utf-8")
        for verboten in ("import wave", "soundfile", "np.save", ".tofile(", "write_bytes"):
            self.assertNotIn(verboten, quelle)
        arbeit = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [f.unlink() for f in arbeit.iterdir()] or arbeit.rmdir())
        alt = os.getcwd()
        os.chdir(arbeit)
        self.addCleanup(os.chdir, alt)
        self._lauf(FalschesModell())
        self.assertEqual([f.name for f in arbeit.iterdir()], [])
        # Die Wortliste liegt im Temp-Ordner des Tests, nicht im Arbeitsordner.
        self.assertTrue(self.woerter.exists())


class AnsichtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        try:
            from . import grundlagen
        except ImportError:
            import grundlagen
        cls.anwendung = QApplication.instance() or QApplication([])
        grundlagen.stil_laden(cls.anwendung)

    def setUp(self):
        try:
            from . import eingangsordner, orchestrator, orchestrator_ansicht
            from .sicherheit import Projekt
        except ImportError:
            import eingangsordner, orchestrator, orchestrator_ansicht
            from sicherheit import Projekt
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        wurzel = Path(temp.name)
        for p in (mock.patch.object(orchestrator, "ORCH_ORDNER", wurzel / "orchestrator"),
                  mock.patch.object(eingangsordner, "EINGANG_ORDNER", wurzel / "eingang")):
            p.start()
            self.addCleanup(p.stop)
        self.sprecher = mock.MagicMock()
        self.a = orchestrator_ansicht.OrchestratorAnsicht(Projekt("T", wurzel, False), self.sprecher)
        self.addCleanup(self.a.deleteLater)
        self.worte = orchestrator_ansicht.DIKTAT_WORTE

    def test_knopf_wechselt_wort_und_farbe(self):
        a = self.a
        a.diktat = mock.MagicMock(erkennt=False, nimmt_auf=False)
        self.assertEqual(a.aufnahme_knopf.text(), self.worte["bereit"])
        a.diktat_umschalten()
        a.diktat.starten.assert_called_once()
        self.assertEqual(a.aufnahme_knopf.text(), "Aufnahme läuft")
        self.assertEqual(a.aufnahme_knopf.property("zustand"), "aufnahme")
        a.diktat.nimmt_auf = True
        a.diktat_umschalten()
        self.assertEqual(a.aufnahme_knopf.text(), "Erkenne…")
        self.assertEqual(a.aufnahme_knopf.property("zustand"), "erkennt")
        a.diktat.beenden.assert_called_once()

    def test_text_an_cursor_und_nicht_gesendet(self):
        a = self.a
        a.eingabe.setPlainText("Anfang Ende")
        cursor = a.eingabe.textCursor()
        cursor.setPosition(len("Anfang"))
        a.eingabe.setTextCursor(cursor)
        with mock.patch.object(a, "senden") as senden:
            a._diktat_fertig("mitte", False)
        self.assertEqual(a.eingabe.toPlainText(), "Anfang mitte Ende")
        senden.assert_not_called()
        self.assertEqual(a.aufnahme_knopf.text(), self.worte["bereit"])

    def test_sendebefehl_sendet(self):
        a = self.a
        with mock.patch.object(a, "senden") as senden:
            a._diktat_fertig("Hallo", True)
        senden.assert_called_once()

    def test_fehler_wird_gesprochen_und_knopf_bereit(self):
        a = self.a
        a.diktat = mock.MagicMock(erkennt=False, nimmt_auf=False)
        a.diktat.starten.side_effect = diktat.DiktatFehler("Kein Mikrofon gefunden.")
        a.diktat_umschalten()
        self.sprecher.sprich.assert_called_with("Kein Mikrofon gefunden.", art="fehler")
        self.assertEqual(a.aufnahme_knopf.text(), self.worte["bereit"])

    def test_kuerzel_kollidiert_nicht(self):
        try:
            from . import orchestrator_ansicht
        except ImportError:
            import orchestrator_ansicht
        quelle = (Path(__file__).parent / "fenster.py").read_text(encoding="utf-8")
        self.assertNotIn('("Ctrl+D"', quelle)
        self.assertEqual(orchestrator_ansicht.DIKTAT_KUERZEL, "Ctrl+D")


if __name__ == "__main__":
    unittest.main()
