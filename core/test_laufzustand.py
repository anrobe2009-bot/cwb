"""
CWB - Code Workbench
Tests fuer den einheitlichen Laufzustand (Werkbank._laeuft, Faden-Merker
faden_beschaeftigt, Projektwechsel bei laufendem Auftrag, Band, F2,
Herzschlag, Faden-Absturz, RUN-Rueckstellung).

Wie in test_statusleiste.py: kein echtes Qt-Fenster, sondern ein schlanker
Traeger, der die echten, ungebundenen Methoden aus Werkbank und SitzungsFaden
benutzt.

Aufruf: python -m unittest core.test_laufzustand -v
"""

import asyncio
import queue
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

try:
    from . import faden as faden_modul
    from . import fenster
except ImportError:
    import faden as faden_modul
    import fenster

Werkbank = fenster.Werkbank


def _thread(laeuft: bool, wait_ergebnis: bool = True):
    return types.SimpleNamespace(
        isRunning=lambda: laeuft, wait=lambda ms=0: wait_ergebnis,
        not_aus=mock.Mock(), art="run")


class _FadenAttrappe:
    def __init__(self, beschaeftigt=False, wait_ergebnis=True):
        self.faden_beschaeftigt = beschaeftigt
        self.sitzung = None
        self._wait = wait_ergebnis
        self.aufrufe: list[str] = []

    def not_aus(self):
        self.aufrufe.append("not_aus")

    def frage_beantworten(self, ja):
        self.aufrufe.append("frage_beantworten")

    def wartende_verwerfen(self):
        self.aufrufe.append("verwerfen")

    def beenden(self):
        self.aufrufe.append("beenden")

    def wait(self, ms=0):
        self.aufrufe.append("wait")
        return self._wait


class _Traeger:
    PROJEKT = types.SimpleNamespace(name="CWB", pfad="/tmp")
    FADEN_ENDE_WARTEZEIT_MS = 10

    _laeuft = Werkbank._laeuft
    _arbeit_laeuft = Werkbank._arbeit_laeuft
    _code_laeuft = Werkbank._code_laeuft
    _bericht_laedt_hoch = Werkbank._bericht_laedt_hoch
    _laeuft_art = Werkbank._laeuft_art
    _laeuft_satz = Werkbank._laeuft_satz
    _dauer_wort = staticmethod(Werkbank._dauer_wort)
    _laeuft_kennung = Werkbank._laeuft_kennung
    _laeuft_beenden = Werkbank._laeuft_beenden
    _projekt_wechseln = Werkbank._projekt_wechseln
    _wo_stehen_wir = Werkbank._wo_stehen_wir
    _statusleiste_satz = Werkbank._statusleiste_satz
    _wartet_kennungen = Werkbank._wartet_kennungen
    _bereit = Werkbank._bereit
    _ereignis = Werkbank._ereignis
    _faden_abgestuerzt = Werkbank._faden_abgestuerzt
    _herzschlag_ansagen = Werkbank._herzschlag_ansagen
    _band_beschreibung_aktualisieren = Werkbank._band_beschreibung_aktualisieren
    _sekunden_seit_beginn = Werkbank._sekunden_seit_beginn
    _terminal_aktiv = Werkbank._terminal_aktiv
    _eingang_auftrag = Werkbank._eingang_auftrag
    _dublette_abgewiesen = Werkbank._dublette_abgewiesen
    _text_glaetten = Werkbank._text_glaetten
    DUBLETTE_FENSTER_SEKUNDEN = Werkbank.DUBLETTE_FENSTER_SEKUNDEN

    def __init__(self, faden=None):
        self.projekt = self.PROJEKT
        self.faden = faden or _FadenAttrappe()
        self.sprecher = mock.Mock()
        self.balken = mock.Mock()
        self._auftrag_laeuft = False
        self._kontingent_info = None
        self._terminal_faden = None
        self._bild_faden = None
        self._bruecke_berichte = []
        self._nachtberichte = []
        self._laufender_block_nummer = 375
        self._laufender_quelle = "Eingabe"
        self._laufender_zeit = datetime(2026, 10, 21, 9, 0)
        self._auftrags_beginn = None
        self._terminal_beginn = None
        self._bild_beginn = None
        self._letzte_taetigkeit = ""
        self._letzte_taetigkeit_zeit = None
        self._warteschlange = []
        self._sparmodus_wartend = []
        self._bruecke_code_nummer = None
        self._aktueller_block_nummer = None
        self._eingang_code_datei = None
        self._schliessen_erzwingen = False
        self.wechselt = False
        self._letzter_zustand = "bereit"
        self._abbruch_antwort = True
        self.zustaende: list[str] = []
        self._auftragsverlauf = []
        self.letzter_auftrag = ""
        self._auftrags_uhr = mock.Mock()
        self._status_zeigen = mock.Mock()
        self._verlauf_anhaengen = mock.Mock()
        self._warteschlange_zeigen = mock.Mock()
        self._statusleiste_aktualisieren = mock.Mock()
        self._taetigkeit_zeigen = mock.Mock()
        self._dublette_melden = mock.Mock()
        self._bruecke_bericht_hochladen = mock.Mock()
        self._bruecke_protokoll_ablegen = mock.Mock()
        self._eingang_auftrag_geschuetzt = mock.Mock()
        self._start_fenster_erzeugt = False

    def _zustand_zeigen(self, zustand):
        self.zustaende.append(zustand)

    def _abbruch_bestaetigen(self, frage):
        self.frage = frage
        return self._abbruch_antwort

    def close(self):
        self.geschlossen = True


class LaeuftTest(unittest.TestCase):
    def test_nichts_laeuft(self):
        self.assertFalse(_Traeger()._laeuft())

    def test_faden_beschaeftigt_zaehlt_auch_ohne_fenstermerker(self):
        t = _Traeger(_FadenAttrappe(beschaeftigt=True))
        self.assertTrue(t._laeuft())
        self.assertEqual(t._laeuft_art(), "Code")

    def test_terminal_bild_und_upload_zaehlen(self):
        t = _Traeger()
        t._terminal_faden = _thread(True)
        self.assertTrue(t._laeuft())
        self.assertEqual(t._laeuft_art(), "Run")
        t._terminal_faden = None
        t._bild_faden = _thread(True)
        self.assertEqual(t._laeuft_art(), "Bild")
        t._bild_faden = None
        t._bruecke_berichte = [_thread(True)]
        self.assertTrue(t._laeuft())
        self.assertFalse(t._arbeit_laeuft())


class ProjektwechselTest(unittest.TestCase):
    def test_ohne_bestaetigung_wird_nichts_beendet_und_nicht_gewechselt(self):
        t = _Traeger(_FadenAttrappe(beschaeftigt=True))
        t._auftrag_laeuft = True
        t._abbruch_antwort = False
        with mock.patch.object(fenster, "Start") as start:
            t._projekt_wechseln()
        start.assert_not_called()
        self.assertEqual(t.faden.aufrufe, [])
        self.assertFalse(t.wechselt)
        self.assertIn("Auftrag 375 läuft noch", t.frage)

    def test_endet_der_lauf_nicht_gibt_es_keinen_wechsel(self):
        t = _Traeger(_FadenAttrappe(beschaeftigt=True, wait_ergebnis=False))
        t._auftrag_laeuft = True
        with mock.patch.object(fenster, "Start") as start:
            t._projekt_wechseln()
        start.assert_not_called()
        self.assertFalse(t.wechselt)
        self.assertTrue(t._schliessen_erzwingen)

    def test_bestaetigt_not_aus_verwirft_wartende_und_wartet_auf_ende(self):
        t = _Traeger(_FadenAttrappe(beschaeftigt=True))
        t._auftrag_laeuft = True
        with mock.patch.object(fenster, "Start") as start, \
                mock.patch.object(fenster, "auftragsjournal"), \
                mock.patch.object(fenster, "OFFENE_FENSTER", []):
            t._projekt_wechseln()
        self.assertEqual(t.faden.aufrufe[:5],
                         ["not_aus", "frage_beantworten", "verwerfen", "beenden", "wait"])
        start.assert_called_once()
        self.assertTrue(t.wechselt)

    def test_leerlauf_wechselt_ohne_frage(self):
        t = _Traeger()
        t._abbruch_antwort = False   # wuerde ablehnen, wird aber nicht gefragt
        with mock.patch.object(fenster, "Start") as start, \
                mock.patch.object(fenster, "auftragsjournal"), \
                mock.patch.object(fenster, "OFFENE_FENSTER", []):
            t._projekt_wechseln()
        start.assert_called_once()


class BandTest(unittest.TestCase):
    def test_bereit_und_fertig_bleiben_waehrend_des_laufs_aus(self):
        t = _Traeger(_FadenAttrappe(beschaeftigt=True))   # z.B. im Nachtrag
        t._bereit()
        t._ereignis("fertig", "Fertig", "")
        t._ereignis("bereit", "Bereit", "")
        self.assertEqual(t.zustaende, [])
        t.sprecher.melde.assert_not_called()

    def test_andere_zustaende_gehen_durch(self):
        t = _Traeger(_FadenAttrappe(beschaeftigt=True))
        t._ereignis("liest", "liest", "", taetigkeit="liest")
        self.assertEqual(t.zustaende, ["liest"])

    def test_denkt_im_leerlauf_laesst_das_band_in_ruhe(self):
        # Ursache des haengenden "denkt": der Code-Index meldet beim Verbinden
        # "denkt", ohne dass ein Auftrag laeuft, und danach kein "fertig".
        t = _Traeger()
        for zustand in ("denkt", "liest", "schreibt", "fuehrt_aus"):
            t._ereignis(zustand, "Indiziere", "")
        self.assertEqual(t.zustaende, [])
        t._ereignis("fehler", "Fehler", "")
        self.assertEqual(t.zustaende, ["fehler"])

    def test_im_leerlauf_setzt_bereit_das_band(self):
        t = _Traeger()
        t.faden.sitzung = None
        t._bereit()
        self.assertEqual(t.zustaende, ["bereit"])

    def test_upload_haelt_das_band_ebenfalls_fest(self):
        t = _Traeger()
        t._bruecke_berichte = [_thread(True)]
        t._bereit()
        self.assertEqual(t.zustaende, [])


class F2Test(unittest.TestCase):
    def _gesprochen(self, t):
        with mock.patch.object(fenster, "wartende_dateien", return_value=[]):
            t._wo_stehen_wir()
        return t.sprecher.sprich.call_args[0][0]

    def test_f2_stimmt_mit_der_leiste_ueberein(self):
        t = _Traeger()
        t._auftrag_laeuft = True
        t._auftrags_beginn = datetime.now() - timedelta(minutes=4, seconds=5)
        t._letzte_taetigkeit = "liest fenster.py"
        satz = self._gesprochen(t)
        self.assertNotIn("Nichts laeuft", satz)
        self.assertIn("Es läuft 375", satz)
        self.assertIn("Art Code", satz)
        self.assertIn("Projekt CWB", satz)
        self.assertIn("seit 4 Minuten", satz)
        self.assertIn("Läuft: 375", satz)

    def test_f2_terminal_allein_sagt_nicht_nichts_laeuft(self):
        t = _Traeger()
        t._terminal_faden = _thread(True)
        satz = self._gesprochen(t)
        self.assertIn("Art Run", satz)
        self.assertNotIn("Nichts laeuft", satz)

    def test_f2_im_leerlauf_nutzt_die_sitzung(self):
        t = _Traeger()
        t.faden.sitzung = types.SimpleNamespace(stand=lambda: "Nichts laeuft gerade.",
                                                 laeuft=False)
        satz = self._gesprochen(t)
        self.assertIn("Nichts laeuft gerade.", satz)
        self.assertIn("Läuft: –", satz)


class WartetTest(unittest.TestCase):
    def test_laufende_kennung_steht_nicht_auch_unter_wartet(self):
        t = _Traeger()
        t._auftrag_laeuft = True
        zeit = datetime(2026, 10, 21, 9, 0)
        eintrag = lambda nr: ("x", [], None, nr, None, None, None, "Eingabe", zeit, None, "")
        t._warteschlange = [eintrag(375), eintrag(376)]
        with mock.patch.object(fenster, "wartende_dateien", return_value=[]):
            self.assertEqual(t._wartet_kennungen(), ["376"])


class RunLaeuftParallelTest(unittest.TestCase):
    """Block 799, Punkt 7b zurueckgezogen: Terminalbefehle laufen parallel
    zu einem CODE-Auftrag, sie werden nicht zurueckgestellt."""

    def _auftrag(self, art):
        return types.SimpleNamespace(art=art)

    def test_run_admin_und_bild_laufen_waehrend_code_sofort(self):
        for art in ("run", "admin", "bild"):
            t = _Traeger(_FadenAttrappe(beschaeftigt=True))
            t._eingang_auftrag(self._auftrag(art))
            t._eingang_auftrag_geschuetzt.assert_called_once()

    def test_belegtes_terminal_stellt_weiter_zurueck(self):
        t = _Traeger()
        t._terminal_faden = _thread(True)
        with self.assertRaises(fenster.AuftragSpaeter):
            t._eingang_auftrag(self._auftrag("run"))


class _Feld:
    """Minimales Textfeld: sammelt Absaetze, kennt clear()."""

    def __init__(self, name):
        self._name = name
        self.absaetze: list[str] = []
        self.verticalScrollBar = lambda: types.SimpleNamespace(
            setValue=lambda v: None, maximum=lambda: 0)

    def objectName(self):
        return self._name

    def append(self, html_text):
        self.absaetze.append(html_text)

    def clear(self):
        self.absaetze.clear()


class _Label:
    def __init__(self):
        self.t = ""
        self.beschreibung = ""

    def text(self):
        return self.t

    def setText(self, t):
        self.t = t

    def setAccessibleDescription(self, t):
        self.beschreibung = t


class _Bereiche(_Traeger):
    _ausgabe_leeren = Werkbank._ausgabe_leeren
    _verlauf_anhaengen = Werkbank._verlauf_anhaengen
    _absatz_schreiben = Werkbank._absatz_schreiben
    _terminal_aktiv = Werkbank._terminal_aktiv
    _zustand_text = Werkbank._zustand_text
    _bereiche_aktualisieren = Werkbank._bereiche_aktualisieren

    def __init__(self, faden=None):
        super().__init__(faden)
        self._verlauf_anhaengen = types.MethodType(Werkbank._verlauf_anhaengen, self)
        self.verlauf = _Feld("verlauf")
        self.terminal_verlauf = _Feld("terminal_verlauf")
        self.claude_zustand = _Label()
        self.terminal_zustand = _Label()
        self._terminal_beginn = None
        self._verlauf_waechst = False


class AusgabenGetrenntTest(unittest.TestCase):
    def test_terminalausgabe_geht_nur_in_den_terminalbereich(self):
        t = _Bereiche()
        t._verlauf_anhaengen("claude sagt", "antwort")
        t._verlauf_anhaengen("ls -l", "terminal")
        self.assertEqual(len(t.verlauf.absaetze), 1)
        self.assertEqual(len(t.terminal_verlauf.absaetze), 1)
        self.assertIn("claude sagt", t.verlauf.absaetze[0])
        self.assertIn("ls -l", t.terminal_verlauf.absaetze[0])

    def test_terminalstart_leert_den_claude_verlauf_nicht(self):
        t = _Bereiche()
        t._verlauf_anhaengen("Antwort von Claude", "antwort")
        t._verlauf_anhaengen("alte Ausgabe", "terminal")
        t._ausgabe_leeren("Terminalbefehl (run)", t.terminal_verlauf)
        self.assertEqual(t.terminal_verlauf.absaetze, [])
        self.assertEqual(len(t.verlauf.absaetze), 1)

    def test_claude_start_leert_den_terminalbereich_nicht(self):
        t = _Bereiche()
        t._verlauf_anhaengen("Terminal-Text", "terminal")
        t._ausgabe_leeren("Auftrag an Claude Code")
        self.assertEqual(len(t.terminal_verlauf.absaetze), 1)

    def test_laufender_terminalbefehl_haelt_claude_text_nicht_zurueck(self):
        t = _Bereiche()
        t._terminal_faden = _thread(True)
        t._verlauf_anhaengen("sofort sichtbar", "antwort")
        self.assertEqual(len(t.verlauf.absaetze), 1)
        self.assertFalse(hasattr(Werkbank, "_verlauf_puffer"))


class ZustandsanzeigenTest(unittest.TestCase):
    def test_beide_bereit(self):
        t = _Bereiche()
        t._bereiche_aktualisieren()
        self.assertEqual(t.claude_zustand.t, "Claude: bereit")
        self.assertEqual(t.terminal_zustand.t, "Terminal: bereit")

    def test_nur_terminal_laeuft(self):
        t = _Bereiche()
        t._terminal_faden = _thread(True)
        t._terminal_beginn = datetime.now() - timedelta(seconds=12)
        t._bereiche_aktualisieren()
        self.assertEqual(t.claude_zustand.t, "Claude: bereit")
        self.assertEqual(t.terminal_zustand.t, "Terminal: läuft seit 12 Sekunden")

    def test_nur_claude_laeuft(self):
        t = _Bereiche(_FadenAttrappe(beschaeftigt=True))
        t._auftrags_beginn = datetime.now() - timedelta(minutes=3, seconds=5)
        t._bereiche_aktualisieren()
        self.assertEqual(t.claude_zustand.t, "Claude: läuft seit 3 Minuten")
        self.assertEqual(t.terminal_zustand.t, "Terminal: bereit")

    def test_beide_unabhaengig(self):
        t = _Bereiche(_FadenAttrappe(beschaeftigt=True))
        t._auftrags_beginn = datetime.now() - timedelta(minutes=2)
        t._terminal_faden = _thread(True)
        t._terminal_beginn = datetime.now() - timedelta(seconds=5)
        t._bereiche_aktualisieren()
        self.assertIn("2 Minuten", t.claude_zustand.t)
        self.assertIn("5 Sekunden", t.terminal_zustand.t)
        # Terminal fertig, Claude laeuft weiter
        t._terminal_faden = _thread(False)
        t._bereiche_aktualisieren()
        self.assertIn("läuft", t.claude_zustand.t)
        self.assertEqual(t.terminal_zustand.t, "Terminal: bereit")

    def test_screenreader_beschreibung_nur_beim_wechsel(self):
        t = _Bereiche()
        t._terminal_faden = _thread(True)
        t._terminal_beginn = datetime.now() - timedelta(seconds=1)
        t._bereiche_aktualisieren()
        erste = t.terminal_zustand.beschreibung
        t._terminal_beginn = datetime.now() - timedelta(seconds=30)
        t._bereiche_aktualisieren()
        self.assertEqual(t.terminal_zustand.beschreibung, erste)

    def test_beginn_je_quelle_fuer_f2(self):
        t = _Traeger()
        t._terminal_beginn = datetime.now() - timedelta(seconds=40)
        t._auftrags_beginn = datetime.now() - timedelta(seconds=400)
        self.assertEqual(t._sekunden_seit_beginn("Run"), 40)
        self.assertEqual(t._sekunden_seit_beginn("Code"), 400)


class FadenAbsturzTest(unittest.TestCase):
    def test_zustand_zurueck_warteschlange_frei_und_ansage(self):
        t = _Traeger(_FadenAttrappe(beschaeftigt=True))
        t._auftrag_laeuft = True
        t._bruecke_code_nummer = 7
        t._warteschlange = [("x",) * 11, ("y",) * 11]
        with mock.patch.object(fenster, "auftragsjournal"):
            t._faden_abgestuerzt("kaputt")
        self.assertFalse(t._auftrag_laeuft)
        self.assertEqual(t._warteschlange, [])
        self.assertEqual(t.zustaende, ["fehler"])
        self.assertIsNone(t._bruecke_code_nummer)
        t._bruecke_bericht_hochladen.assert_called_once()
        t._bruecke_protokoll_ablegen.assert_called_once()
        self.assertEqual(t._bruecke_protokoll_ablegen.call_args[0][1], "fehler")
        satz = t.sprecher.sprich.call_args[0][0]
        self.assertIn("abgestürzt", satz)
        self.assertIn("2 wartende", satz)

    def test_faden_meldet_absturz_und_loescht_merker(self):
        f = faden_modul.SitzungsFaden(types.SimpleNamespace(name="x", pfad="/tmp"))
        gemeldet = []
        f.abgestuerzt_da.connect(gemeldet.append)

        async def kaputt():
            f.faden_beschaeftigt = True
            raise RuntimeError("tot")

        f._arbeiten = kaputt
        f.run()
        self.assertEqual(gemeldet, ["tot"])
        self.assertFalse(f.faden_beschaeftigt)


class FadenMerkerTest(unittest.TestCase):
    def test_merker_ist_waehrend_des_auftrags_wahr_und_danach_falsch(self):
        f = faden_modul.SitzungsFaden(types.SimpleNamespace(name="x", pfad="/tmp"))
        beobachtet = []

        class Sitzung:
            modelle = []
            modell_name = "m"
            modell = "m"

            def __init__(self, *a, **k):
                pass

            def nur_lesen_setzen(self, an):
                pass

            async def verbinden(self):
                pass

            async def auftrag(self, text, bilder):
                beobachtet.append(f.faden_beschaeftigt)
                return {"antwort": "", "geaendert": [], "abgebrochen": False}

            async def trennen(self):
                pass

        fertig = []
        f.fertig_da.connect(lambda b: fertig.append(f.faden_beschaeftigt))
        f.auftrag_geben("hallo", [])
        f.beenden()
        with mock.patch.object(faden_modul, "Sitzung", Sitzung), \
                mock.patch.object(faden_modul.Wache, "oeffnen", return_value=None):
            asyncio.run(f._arbeiten())
        self.assertEqual(beobachtet, [True])
        self.assertEqual(fertig, [False])     # beim Abschluss-Signal schon falsch
        self.assertFalse(f.faden_beschaeftigt)

    def test_wartende_verwerfen_leert_die_warteschlange(self):
        f = faden_modul.SitzungsFaden(types.SimpleNamespace(name="x", pfad="/tmp"))
        f.auftrag_geben("a", [])
        f.modell_setzen("opus")
        f.wartende_verwerfen()
        with self.assertRaises(queue.Empty):
            f.auftraege.get_nowait()


class HerzschlagTest(unittest.TestCase):
    def _lauf(self, sekunden, schalter=True):
        t = _Traeger(_FadenAttrappe(beschaeftigt=True))
        t._auftrags_beginn = datetime.now() - timedelta(seconds=sekunden)
        t._letzte_taetigkeit = "liest fenster.py"
        with mock.patch.object(fenster, "einstellungen_lesen",
                               return_value={"herzschlag_ansage": schalter}):
            t._herzschlag_ansagen()
        return t

    def test_sagt_laufzeit_und_zuletzt_an(self):
        t = self._lauf(185)
        satz = t.sprecher.sprich.call_args[0][0]
        self.assertIn("Claude läuft seit 3 Minuten", satz)
        self.assertIn("zuletzt liest fenster.py", satz)

    def test_nennt_die_quelle_auch_beim_terminal(self):
        t = _Traeger()
        t._terminal_faden = _thread(True)
        t._terminal_beginn = datetime.now() - timedelta(seconds=90)
        with mock.patch.object(fenster, "einstellungen_lesen", return_value={}):
            t._herzschlag_ansagen()
        satz = t.sprecher.sprich.call_args[0][0]
        self.assertTrue(satz.startswith("Terminal läuft seit"))

    def test_abschaltbar(self):
        self.assertFalse(self._lauf(185, schalter=False).sprecher.sprich.called)

    def test_schweigt_im_leerlauf(self):
        t = _Traeger()
        t._auftrags_beginn = datetime.now() - timedelta(minutes=5)
        with mock.patch.object(fenster, "einstellungen_lesen", return_value={}):
            t._herzschlag_ansagen()
        self.assertFalse(t.sprecher.sprich.called)

    def test_band_beschreibung_nennt_zuletzt_und_seit_wann(self):
        t = self._lauf(185)
        text = t.balken.setAccessibleDescription.call_args[0][0]
        self.assertIn("Zuletzt: liest fenster.py", text)
        self.assertIn("Claude läuft seit", text)


class DubletteTest(unittest.TestCase):
    def test_elfstellige_warteschlange_loest_keinen_valueerror_aus(self):
        t = _Traeger()
        t._warteschlange = [("hallo welt", [], None, 1, None, None, None, "Eingabe",
                             datetime.now(), None, "")]
        with mock.patch.object(fenster, "einstellungen_lesen",
                               return_value={"dubletten_pruefung": True}):
            self.assertTrue(t._dublette_abgewiesen("code", "hallo  welt"))
        t._dublette_melden.assert_called_once()


if __name__ == "__main__":
    unittest.main()
