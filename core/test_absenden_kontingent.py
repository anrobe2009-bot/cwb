"""
CWB - Code Workbench
Tests fuer den Weg "Kontingenttor haelt einen CODE-Auftrag" in
Werkbank._absenden (core/fenster.py) zusammen mit core/kontingentsperre.py.

Der Platzhalter kommt aus core/test_absenden.py und bekommt zusaetzlich die
echten Methoden des Kontingentwegs (_naechsten_starten, _kontingent_*).
Uhr, Kontingentstand, Freigabedatei und Gehalten-Datei sind Attrappen bzw.
liegen in einem Temp-Ordner: keine echte kontingent.json, keine Schreib-
zugriffe auf den Datenordner, kein Fenster.

Aufruf: python -m unittest core.test_absenden_kontingent -v
"""

import copy
import logging
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from . import bloecke, fenster, kontingent, kontingentsperre as sperre
    from .fenster import MARKIERUNG_ADMIN, MARKIERUNG_BILD, MARKIERUNG_CODE, MARKIERUNG_RUN, Werkbank
    from .test_absenden import _AbsendenTraeger
except ImportError:
    import bloecke
    import fenster
    import kontingent
    import kontingentsperre as sperre
    from fenster import MARKIERUNG_ADMIN, MARKIERUNG_BILD, MARKIERUNG_CODE, MARKIERUNG_RUN, Werkbank
    from test_absenden import _AbsendenTraeger

log = logging.getLogger(__name__)

ZONE = kontingent.ZONE
# Freitag, 23.10.2026, 12:00
JETZT = datetime(2026, 10, 23, 12, 0, tzinfo=ZONE)


def stand(sitzung=20, woche=7):
    return {"sitzung_prozent": sitzung, "sitzung_reset": "14:00",
            "woche_prozent": woche, "woche_reset": "Do 10:00",
            "gemessen": datetime(2026, 10, 23, 11, 0, tzinfo=ZONE).isoformat(),
            "quelle": "foto"}


class _KontingentTraeger(_AbsendenTraeger):
    """Wie _AbsendenTraeger, aber mit dem echten Kontingentweg."""

    _naechsten_starten = Werkbank._naechsten_starten
    _kontingent_gehalten_zeigen = Werkbank._kontingent_gehalten_zeigen
    _kontingent_nummern = Werkbank._kontingent_nummern
    _kontingent_freigeben = Werkbank._kontingent_freigeben
    _kontingent_sperre_pruefen = Werkbank._kontingent_sperre_pruefen

    def __init__(self, text: str, tor: sperre.Tor):
        super().__init__(text)
        self._kontingent_tor = tor
        # Echte Methode, aber mit Aufzeichnung der Aufrufe.
        self._kontingent_urteil_melden = mock.Mock(
            wraps=Werkbank._kontingent_urteil_melden.__get__(self))
        self.wechselt = False
        self._warteschlange_zeigen = mock.Mock()
        self._statusleiste_aktualisieren = mock.Mock()
        self._zustand_zeigen = mock.Mock()
        self._kontingent_sperre_uhr = mock.Mock()
        self._kontingent_sperre_uhr.isActive.return_value = False
        self._terminal_markierung = mock.Mock()
        self._bild_markierung = mock.Mock()

    def neuer_text(self, text: str) -> None:
        self.eingabe.toPlainText.return_value = text


class _Grundlage(unittest.TestCase):
    """Attrappen-Uhr, Temp-Dateien und Hilfen; selbst ohne Tests."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ordner = Path(temp.name)
        self.freigabe = self.ordner / "freigabe.json"
        self.gehalten = self.ordner / "gehalten.json"
        self._speicher: dict = {}
        self.jetzt = JETZT  # die Attrappen-Uhr: Tests stellen sie vor
        for muster in (
            mock.patch.object(kontingent, "einstellungen_lesen", return_value={}),
            mock.patch.object(kontingent, "jetzt", side_effect=lambda: self.jetzt),
            mock.patch.object(sperre, "FREIGABE_DATEI", self.freigabe),
            mock.patch.object(sperre, "GEHALTEN_DATEI", self.gehalten),
            mock.patch.object(fenster, "auftragsjournal"),
            mock.patch.object(bloecke, "einstellungen_lesen",
                              lambda: copy.deepcopy(self._speicher)),
            mock.patch.object(bloecke, "einstellungen_schreiben",
                              lambda werte: self._speicher.update(copy.deepcopy(werte))),
        ):
            muster.start()
            self.addCleanup(muster.stop)

    def tor(self, wert, schalter=True) -> sperre.Tor:
        # `schalter` darf ein Bool oder ein Aufruf sein (um ihn mitten im Test
        # umzulegen).
        wahr = schalter if callable(schalter) else (lambda: schalter)
        return sperre.Tor(lambda zeit: kontingent.auswerten(wert, zeit),
                          self.freigabe, wahr)

    def traeger(self, text: str, wert, schalter=True) -> _KontingentTraeger:
        return _KontingentTraeger(text, self.tor(wert, schalter))

    @staticmethod
    def code(auftrag: str, nummer: int = 1, kopf: str = "") -> str:
        return (f"{MARKIERUNG_CODE}\nBlock {nummer}\nProjekt: CWB_TestEndeZuEnde\n"
                f"{kopf}{auftrag}\nEnde Block {nummer}")


class KontingentTorTest(_Grundlage):
    # a) knapp: gehalten
    def test_knapp_haelt_code_auftrag_in_der_warteschlange(self):
        t = self.traeger(self.code("Tu etwas."), stand(sitzung=95))
        t._absenden()
        t._auftrag_starten.assert_not_called()
        self.assertEqual(len(t._warteschlange), 1)
        self.assertIn("Tu etwas.", t._warteschlange[0][0])
        t._taetigkeit_zeigen.assert_called_with("wartet auf Kontingent bis 14:00")
        t._status_zeigen.assert_called_with("wartet auf Kontingent bis 14:00")
        t._zustand_zeigen.assert_called_with("wartet_kontingent")
        t._verlauf_anhaengen.assert_any_call("Kontingent knapp: wartet auf Kontingent bis 14:00.",
                                             "hinweis")
        t._kontingent_urteil_melden.assert_not_called()

    def test_knapp_durch_woche_nennt_wochentag(self):
        t = self.traeger(self.code("Tu etwas."), stand(woche=95))
        t._absenden()
        t._auftrag_starten.assert_not_called()
        t._status_zeigen.assert_called_with("wartet auf Kontingent bis Do 10:00")

    # b) RUN, ADMIN, BILD laufen durch
    def test_run_admin_bild_laufen_trotz_knapp_durch(self):
        for marke, ziel in ((MARKIERUNG_RUN, "_terminal_markierung"),
                            (MARKIERUNG_ADMIN, "_terminal_markierung"),
                            (MARKIERUNG_BILD, "_bild_markierung")):
            with self.subTest(marke=marke):
                t = self.traeger(f"{marke}\necho hallo", stand(sitzung=99, woche=99))
                t._absenden()
                getattr(t, ziel).assert_called_once()
                t._auftrag_starten.assert_not_called()
                self.assertEqual(t._warteschlange, [])
                t._kontingent_urteil_melden.assert_not_called()

    # c) Sparmodus: laeuft, teures Modell herabgesetzt
    def test_sparmodus_setzt_opus_auf_sonnet_herab(self):
        t = self.traeger(self.code("Tu etwas.", kopf="Modell: Opus\n"), stand(woche=82))
        t._absenden()
        t._auftrag_starten.assert_called_once()
        self.assertEqual(t._auftrag_starten.call_args[1]["modell_wunsch"], "sonnet")
        self.assertEqual(t._warteschlange, [])
        urteil = t._kontingent_urteil_melden.call_args[0][0]
        self.assertEqual((urteil.aktion, urteil.modell), (sperre.HERAB, "sonnet"))

    def test_sparmodus_laesst_sonnet_unveraendert(self):
        t = self.traeger(self.code("Tu etwas.", kopf="Modell: Sonnet\n"), stand(woche=82))
        t._absenden()
        t._auftrag_starten.assert_called_once()
        self.assertEqual(t._auftrag_starten.call_args[1]["modell_wunsch"], "sonnet")

    # d) einmalige Freigabe
    def test_freigabe_startet_genau_einen_gehaltenen_auftrag(self):
        t = self.traeger(self.code("Erster.", 1), stand(sitzung=95))
        t._absenden()
        t.neuer_text(self.code("Zweiter.", 2))
        t._absenden()
        t._auftrag_starten.assert_not_called()
        self.assertEqual(len(t._warteschlange), 2)

        t._kontingent_freigeben()
        self.assertEqual(t._auftrag_starten.call_count, 1)
        self.assertIn("Erster.", t._auftrag_starten.call_args[0][0])
        self.assertEqual(len(t._warteschlange), 1)
        self.assertFalse(self.freigabe.exists())

        # Die Sperre gilt wieder: der zweite bleibt gehalten.
        t._naechsten_starten()
        self.assertEqual(t._auftrag_starten.call_count, 1)
        self.assertEqual(len(t._warteschlange), 1)
        self.assertIn("Zweiter.", t._warteschlange[0][0])

    def test_freigabe_vor_dem_absenden_gilt_fuer_einen_neuen_auftrag(self):
        sperre.freigabe_geben(self.freigabe, JETZT)
        t = self.traeger(self.code("Erster.", 1), stand(sitzung=95))
        t._absenden()
        t._auftrag_starten.assert_called_once()
        t.neuer_text(self.code("Zweiter.", 2))
        t._absenden()
        t._auftrag_starten.assert_called_once()
        self.assertEqual(len(t._warteschlange), 1)

    # e) Schalter aus
    def test_schalter_aus_haelt_nichts(self):
        t = self.traeger(self.code("Tu etwas."), stand(sitzung=99, woche=99), schalter=False)
        t._absenden()
        t._auftrag_starten.assert_called_once()
        self.assertEqual(t._warteschlange, [])
        t._zustand_zeigen.assert_not_called()

    def test_schalter_aus_setzt_auch_kein_modell_herab(self):
        t = self.traeger(self.code("Tu etwas.", kopf="Modell: Opus\n"), stand(woche=90),
                         schalter=False)
        t._absenden()
        self.assertEqual(t._auftrag_starten.call_args[1]["modell_wunsch"], "opus")

    def test_keine_schreibzugriffe_auf_den_echten_datenordner(self):
        t = self.traeger(self.code("Tu etwas."), stand(sitzung=95))
        t._absenden()
        self.assertFalse(sperre.GEHALTEN_DATEI.is_relative_to(sperre.DATENORDNER))
        self.assertFalse(sperre.FREIGABE_DATEI.is_relative_to(sperre.DATENORDNER))


class ZeitgeberTest(_Grundlage):
    """Werkbank._kontingent_sperre_pruefen: der 60-Sekunden-Zeitgeber. Der
    echte Zeitgeber laeuft nie; die Tests rufen die Methode selbst und stellen
    die Attrappen-Uhr (self.jetzt) vor."""

    VOR_RESET = datetime(2026, 10, 23, 12, 30, tzinfo=ZONE)
    NACH_RESET = datetime(2026, 10, 23, 14, 1, tzinfo=ZONE)   # Sitzungsreset 14:00

    def gehalten_traeger(self, schalter=True, anzahl=2, mit_nummern=True):
        """Traeger mit `anzahl` gehaltenen Auftraegen (Nummern 11, 12, ...).
        Ein Start belegt den Traeger wie in Wirklichkeit (_auftrag_laeuft)."""
        t = self.traeger(self.code("Auftrag 1.", 1), stand(sitzung=95), schalter)

        def start(*_args, **_kwargs):
            t._auftrag_laeuft = True
        t._auftrag_starten.side_effect = start
        for i in range(1, anzahl + 1):
            t.neuer_text(self.code(f"Auftrag {i}.", i))
            t._absenden(bruecke_nummer=10 + i if mit_nummern else None)
        self.assertEqual(len(t._warteschlange), anzahl)
        t._auftrag_starten.assert_not_called()
        return t

    def gestartete(self, t) -> list:
        return [aufruf[0][0] for aufruf in t._auftrag_starten.call_args_list]

    # a) knapp -> normal: nacheinander
    def test_nach_dem_reset_starten_gehaltene_nacheinander(self):
        t = self.gehalten_traeger()
        self.assertIsNotNone(sperre.gehalten_text(11, self.gehalten))
        self.assertIsNotNone(sperre.gehalten_text(12, self.gehalten))

        self.jetzt = self.NACH_RESET
        t._kontingent_sperre_pruefen()
        self.assertEqual(len(self.gestartete(t)), 1)
        self.assertIn("Auftrag 1.", self.gestartete(t)[0])
        self.assertEqual(len(t._warteschlange), 1)
        self.assertIsNone(sperre.gehalten_text(11, self.gehalten))
        self.assertIsNotNone(sperre.gehalten_text(12, self.gehalten))

        # Der erste laeuft noch: der Zeitgeber startet den zweiten nicht.
        t._kontingent_sperre_pruefen()
        self.assertEqual(len(self.gestartete(t)), 1)

        # Ende des ersten (Werkbank._fertig ruft _naechsten_starten).
        t._auftrag_laeuft = False
        t._naechsten_starten()
        self.assertEqual(len(self.gestartete(t)), 2)
        self.assertIn("Auftrag 2.", self.gestartete(t)[1])
        self.assertEqual(t._warteschlange, [])
        self.assertIsNone(sperre.gehalten_text(12, self.gehalten))

    def test_ende_der_sperre_wird_einmal_gemeldet(self):
        t = self.gehalten_traeger()
        t._kontingent_sperre_pruefen()                 # noch knapp: Ton "beginn" schon vorbei
        t.sprecher.ton.reset_mock()
        self.jetzt = self.NACH_RESET
        t._kontingent_sperre_pruefen()
        t.sprecher.ton.assert_called_once_with("wartet")
        t._kontingent_sperre_uhr.stop.assert_called()

    # b) normale Stufe, nichts gehalten
    def test_zeitgeber_ohne_gehaltene_auftraege_tut_nichts(self):
        t = self.traeger(self.code("Egal."), stand())
        for _ in range(3):
            t._kontingent_sperre_pruefen()
        t._auftrag_starten.assert_not_called()
        self.assertEqual(t._warteschlange, [])
        t._zustand_zeigen.assert_not_called()
        t._status_zeigen.assert_not_called()
        t.sprecher.ton.assert_not_called()
        self.assertEqual(t._kontingent_sperre_uhr.stop.call_count, 3)

    # c) es laeuft schon einer
    def test_laeuft_schon_einer_warten_gehaltene(self):
        t = self.gehalten_traeger()
        self.jetzt = self.NACH_RESET
        t._auftrag_laeuft = True
        for _ in range(3):
            t._kontingent_sperre_pruefen()
        t._auftrag_starten.assert_not_called()
        self.assertEqual(len(t._warteschlange), 2)
        self.assertIsNotNone(sperre.gehalten_text(11, self.gehalten))
        # Ist der Auftrag zu Ende, geht es beim naechsten Tick los.
        t._auftrag_laeuft = False
        t._kontingent_sperre_pruefen()
        self.assertEqual(len(self.gestartete(t)), 1)

    def test_waehrend_projektwechsel_startet_nichts(self):
        t = self.gehalten_traeger()
        self.jetzt = self.NACH_RESET
        t.wechselt = True
        t._kontingent_sperre_pruefen()
        t._auftrag_starten.assert_not_called()
        self.assertEqual(len(t._warteschlange), 2)

    # d) bleibt knapp
    def test_bleibt_knapp_startet_nichts(self):
        t = self.gehalten_traeger()
        self.jetzt = self.VOR_RESET
        for _ in range(3):
            t._kontingent_sperre_pruefen()
        t._auftrag_starten.assert_not_called()
        self.assertEqual(len(t._warteschlange), 2)
        t._status_zeigen.assert_called_with("wartet auf Kontingent bis 14:00")
        t._kontingent_sperre_uhr.start.assert_called()

    def test_bleibt_knapp_mit_leerer_liste_ohne_absturz(self):
        t = self.traeger(self.code("Egal."), stand(sitzung=95))
        t._kontingent_sperre_pruefen()
        t._kontingent_sperre_pruefen()
        t._auftrag_starten.assert_not_called()
        self.assertEqual(t._warteschlange, [])
        t._kontingent_sperre_uhr.stop.assert_called()

    def test_zeitgeber_verbraucht_keine_handfreigabe(self):
        t = self.gehalten_traeger()
        self.jetzt = self.VOR_RESET
        sperre.freigabe_geben(self.freigabe, self.VOR_RESET)
        # Der Zeitgeber fragt nur (verbrauchen=False), der Start verbraucht dann.
        t._kontingent_sperre_pruefen()
        self.assertEqual(len(self.gestartete(t)), 1)
        self.assertFalse(self.freigabe.exists())

    # e) nie doppelt
    def test_zweimal_feuern_vor_abschluss_startet_nie_doppelt(self):
        t = self.gehalten_traeger(anzahl=1)
        t._auftrag_starten.side_effect = None          # Start "noch nicht abgeschlossen"
        self.jetzt = self.NACH_RESET
        t._kontingent_sperre_pruefen()
        t._kontingent_sperre_pruefen()
        self.assertEqual(len(self.gestartete(t)), 1)
        self.assertEqual(t._warteschlange, [])

    def test_zweimal_feuern_startet_jeden_auftrag_hoechstens_einmal(self):
        t = self.gehalten_traeger()
        t._auftrag_starten.side_effect = None          # Start "noch nicht abgeschlossen"
        self.jetzt = self.NACH_RESET
        t._kontingent_sperre_pruefen()
        t._kontingent_sperre_pruefen()
        t._kontingent_sperre_pruefen()
        texte = self.gestartete(t)
        self.assertEqual(len(texte), 2)
        self.assertEqual(len(set(texte)), 2)

    def test_neustart_der_oberflaeche_startet_nichts_aus_der_gehalten_datei(self):
        """kontingent_gehalten.json dient nur der Anzeige: ein frischer Traeger
        mit leerer Warteschlange startet trotz Eintraegen nichts."""
        sperre.gehalten_vermerken(11, self.NACH_RESET, self.gehalten)
        t = self.traeger(self.code("Egal."), stand())
        self.jetzt = self.NACH_RESET
        t._kontingent_sperre_pruefen()
        t._auftrag_starten.assert_not_called()

    # f) Schalter aus
    def test_schalter_aus_gibt_gehaltene_beim_naechsten_tick_frei(self):
        """Tatsaechliches Verhalten: der Zeitgeber fragt das Tor, das bei
        ausgeschaltetem Schalter immer "start" sagt - die gehaltenen Auftraege
        laufen also beim naechsten Tick los, nacheinander, auch ohne Reset."""
        schalter = {"an": True}
        t = self.gehalten_traeger(schalter=lambda: schalter["an"])
        self.jetzt = self.VOR_RESET
        t._kontingent_sperre_pruefen()
        t._auftrag_starten.assert_not_called()

        schalter["an"] = False
        t._kontingent_sperre_pruefen()
        self.assertEqual(len(self.gestartete(t)), 1)
        self.assertIn("Auftrag 1.", self.gestartete(t)[0])
        self.assertEqual(len(t._warteschlange), 1)
        # Auch jetzt nacheinander: der zweite erst nach Ende des ersten.
        t._kontingent_sperre_pruefen()
        self.assertEqual(len(self.gestartete(t)), 1)
        t._auftrag_laeuft = False
        t._naechsten_starten()
        self.assertEqual(len(self.gestartete(t)), 2)


if __name__ == "__main__":
    unittest.main()
