"""
CWB - Code Workbench
Tests fuer die Kontingentsperre (core/kontingentsperre.py, Etappe 2) mit
Attrappen und festen Uhrzeiten: keine echten Prozesse, kein sichtbares Fenster.

Aufruf: python -m unittest core.test_kontingentsperre -v
        (oder, aus dem Ordner core/: python test_kontingentsperre.py -v)
"""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from . import fenster, kontingent, kontingentsperre as sperre, orchestrator
except ImportError:
    import fenster
    import kontingent
    import kontingentsperre as sperre
    import orchestrator

ZONE = kontingent.ZONE
# Freitag, 23.10.2026, 12:00
JETZT = datetime(2026, 10, 23, 12, 0, tzinfo=ZONE)


def stand(sitzung=20, woche=7, gemessen=datetime(2026, 10, 23, 11, 0, tzinfo=ZONE)):
    return {"sitzung_prozent": sitzung, "sitzung_reset": "14:00",
            "woche_prozent": woche, "woche_reset": "Do 10:00",
            "gemessen": gemessen.isoformat(), "quelle": "foto"}


def eintrag(name, modell=None, datei=None):
    return (name, [], None, None, datei, modell, None, "Eingabe", JETZT, None, "")


class Grundlage(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.addCleanup(self.ordner.cleanup)
        self.freigabe = Path(self.ordner.name) / "freigabe.json"
        self.gehalten = Path(self.ordner.name) / "gehalten.json"
        muster = patch.object(kontingent, "einstellungen_lesen", return_value={})
        muster.start()
        self.addCleanup(muster.stop)
        uhr = patch.object(kontingent, "jetzt", return_value=JETZT)
        uhr.start()
        self.addCleanup(uhr.stop)

    def tor(self, wert, schalter=None):
        if isinstance(wert, dict) or wert is None:
            def auswerter(zeit):
                return kontingent.auswerten(wert, zeit)
        else:
            auswerter = wert
        return sperre.Tor(auswerter, self.freigabe, schalter or (lambda: True))


class Stufen(Grundlage):
    def test_normal_startet(self):
        urteil = self.tor(stand()).pruefen("opus", JETZT)
        self.assertEqual(urteil.aktion, sperre.START)

    def test_sparmodus_setzt_teures_modell_herab(self):
        tor = self.tor(stand(woche=82))
        for teuer in ("opus", "fable", "claude-fable-5-1[1m]", "default"):
            urteil = tor.pruefen(teuer, JETZT)
            self.assertEqual((urteil.aktion, urteil.modell), (sperre.HERAB, "sonnet"), teuer)
            self.assertIn("Sonnet", urteil.hinweis)
        for billig in ("sonnet", "haiku", None):
            self.assertEqual(tor.pruefen(billig, JETZT).aktion, sperre.START, billig)

    def test_knapp_haelt_mit_freigabezeit(self):
        urteil = self.tor(stand(sitzung=95)).pruefen("sonnet", JETZT)
        self.assertEqual(urteil.aktion, sperre.HALTEN)
        self.assertEqual(urteil.bis, datetime(2026, 10, 23, 14, 0, tzinfo=ZONE))
        self.assertIn("14:00", urteil.hinweis)

    def test_knapp_durch_woche_nennt_wochenreset(self):
        urteil = self.tor(stand(woche=95)).pruefen(None, JETZT)
        self.assertEqual(urteil.aktion, sperre.HALTEN)
        self.assertEqual(urteil.bis, datetime(2026, 10, 29, 10, 0, tzinfo=ZONE))
        self.assertTrue(sperre.uhrzeit_text(urteil.bis, JETZT).endswith("10:00"))
        self.assertTrue(sperre.uhrzeit_text(urteil.bis, JETZT).startswith("Do"))

    def test_veraltet_startet_mit_hinweis(self):
        alt = datetime(2026, 10, 23, 4, 0, tzinfo=ZONE)
        urteil = self.tor(stand(sitzung=95, gemessen=alt)).pruefen("opus", JETZT)
        self.assertEqual(urteil.aktion, sperre.START)
        self.assertIn("veraltet", urteil.hinweis)

    def test_ohne_stand_startet(self):
        urteil = self.tor(None).pruefen("opus", JETZT)
        self.assertEqual(urteil.aktion, sperre.START)
        self.assertEqual(urteil.hinweis, "")

    def test_run_admin_bild_orchestrator_werden_nie_gehalten(self):
        tor = self.tor(stand(sitzung=99, woche=99))
        for art in ("run", "admin", "bild", "orchestrator"):
            self.assertEqual(tor.pruefen(None, JETZT, art=art).aktion, sperre.START, art)
        self.assertEqual(tor.pruefen(None, JETZT, art="code").aktion, sperre.HALTEN)

    def test_schalter_aus_laeuft_wie_etappe_1(self):
        tor = self.tor(stand(sitzung=99, woche=99), schalter=lambda: False)
        self.assertEqual(tor.pruefen("opus", JETZT).aktion, sperre.START)

    def test_fehler_in_der_auswertung_haelt_nie_auf(self):
        def kaputt(_zeit):
            raise RuntimeError("kaputt")
        self.assertEqual(self.tor(kaputt).pruefen("opus", JETZT).aktion, sperre.START)


class Aufheben(Grundlage):
    def test_sitzungsreset_hebt_auf(self):
        tor = self.tor(stand(sitzung=95))
        self.assertEqual(tor.pruefen(None, JETZT).aktion, sperre.HALTEN)
        nach = datetime(2026, 10, 23, 14, 1, tzinfo=ZONE)
        self.assertEqual(tor.pruefen(None, nach).aktion, sperre.START)

    def test_wochenreset_hebt_auf(self):
        tor = self.tor(stand(woche=95))
        self.assertEqual(tor.pruefen(None, JETZT).aktion, sperre.HALTEN)
        nach = datetime(2026, 10, 29, 10, 1, tzinfo=ZONE)
        self.assertEqual(tor.pruefen(None, nach).aktion, sperre.START)

    def test_beide_ueber_schwelle_gilt_der_spaetere_reset(self):
        urteil = self.tor(stand(sitzung=95, woche=95)).pruefen(None, JETZT)
        self.assertEqual(urteil.bis, datetime(2026, 10, 29, 10, 0, tzinfo=ZONE))
        zwischen = datetime(2026, 10, 23, 14, 1, tzinfo=ZONE)
        self.assertEqual(self.tor(stand(sitzung=95, woche=95)).pruefen(None, zwischen).aktion,
                         sperre.HALTEN)

    def test_neuer_stand_hebt_auf(self):
        aktuell = {"s": stand(sitzung=95)}
        tor = self.tor(lambda zeit: kontingent.auswerten(aktuell["s"], zeit))
        self.assertEqual(tor.pruefen(None, JETZT).aktion, sperre.HALTEN)
        aktuell["s"] = stand(sitzung=10)
        self.assertEqual(tor.pruefen(None, JETZT).aktion, sperre.START)


class Handfreigabe(Grundlage):
    def test_gilt_nur_fuer_einen_auftrag(self):
        tor = self.tor(stand(sitzung=95))
        sperre.freigabe_geben(self.freigabe, JETZT)
        erster = tor.pruefen(None, JETZT)
        self.assertEqual(erster.aktion, sperre.START)
        self.assertIn("von Hand", erster.hinweis)
        self.assertEqual(tor.pruefen(None, JETZT).aktion, sperre.HALTEN)

    def test_zeitgeber_verbraucht_sie_nicht(self):
        tor = self.tor(stand(sitzung=95))
        sperre.freigabe_geben(self.freigabe, JETZT)
        self.assertEqual(tor.pruefen(None, JETZT, verbrauchen=False).aktion, sperre.START)
        self.assertTrue(sperre.freigabe_offen(self.freigabe, JETZT))
        tor.pruefen(None, JETZT)
        self.assertFalse(sperre.freigabe_offen(self.freigabe, JETZT))


class Warteschlange(Grundlage):
    def test_gehaltene_starten_einmal_und_in_reihenfolge(self):
        tor = self.tor(stand(sitzung=95))
        schlange = [eintrag("a"), eintrag("b"), eintrag("c")]
        geholt, urteil = sperre.naechsten_holen(schlange, tor, JETZT)
        self.assertIsNone(geholt)
        self.assertEqual(urteil.aktion, sperre.HALTEN)
        self.assertEqual([e[0] for e in schlange], ["a", "b", "c"])    # nichts verworfen
        nach = datetime(2026, 10, 23, 14, 1, tzinfo=ZONE)
        gestartet = []
        while True:
            geholt, _ = sperre.naechsten_holen(schlange, tor, nach)
            if geholt is None:
                break
            gestartet.append(geholt[0])
        self.assertEqual(gestartet, ["a", "b", "c"])
        self.assertEqual(schlange, [])
        self.assertEqual(sperre.naechsten_holen(schlange, tor, nach), (None, None))

    def test_neustart_startet_nicht_doppelt(self):
        datei = Path(self.ordner.name) / "laeuft" / "0001.json"
        schlange = [eintrag("a", datei=datei)]
        self.assertTrue(sperre.schon_vorgemerkt(schlange, datei))
        # Neustart: die Schlange lebt nur im Speicher, die Datei in laeuft/ wird
        # einmal neu angenommen und hoechstens einmal eingereiht.
        neu = []
        for _ in range(2):
            if not sperre.schon_vorgemerkt(neu, datei):
                neu.append(eintrag("a", datei=datei))
        self.assertEqual(len(neu), 1)
        sperre.gehalten_vermerken(7, None, self.gehalten)   # Anzeigevermerk steuert nichts
        self.assertEqual(sperre.naechsten_holen(
            neu, self.tor(stand()), JETZT)[0][0], "a")

    def test_herabsetzen_trifft_nur_teure_wuensche(self):
        urteil = sperre.Urteil(sperre.HERAB, modell="sonnet")
        e = list(eintrag("a", modell="opus"))
        e[9] = "haiku"
        ergebnis = sperre.eintrag_herabsetzen(tuple(e), urteil)
        self.assertEqual((ergebnis[5], ergebnis[9]), ("sonnet", "haiku"))

    def test_ton_je_einmal_beginn_und_weiter(self):
        tor = self.tor(stand())
        folge = [tor.zustand_melden(h) for h in (True, True, False, False, True)]
        self.assertEqual(folge, ["beginn", None, "weiter", None, "beginn"])


class Bericht(Grundlage):
    def test_bericht_nennt_wartet_auf_kontingent(self):
        bis = datetime(2026, 10, 23, 14, 0, tzinfo=ZONE)
        sperre.gehalten_vermerken(1000005, bis, self.gehalten)
        self.assertEqual(sperre.gehalten_text(1000005, self.gehalten, JETZT),
                         "WARTET AUF KONTINGENT bis 14:00")
        self.assertIsNone(sperre.gehalten_text(1000006, self.gehalten, JETZT))
        sperre.gehalten_loeschen(1000005, self.gehalten)
        self.assertIsNone(sperre.gehalten_text(1000005, self.gehalten, JETZT))

    def test_bericht_holen_sagt_es_dem_absender(self):
        bis = datetime(2026, 10, 23, 14, 0, tzinfo=ZONE)
        sperre.gehalten_vermerken(1000005, bis, self.gehalten)
        leer = Path(self.ordner.name) / "berichte"
        leer.mkdir()
        with patch.object(sperre, "GEHALTEN_DATEI", self.gehalten), \
                patch.object(orchestrator, "berichte_ordner", return_value=leer), \
                patch.object(orchestrator, "_auftragsdatei",
                             return_value=("laeuft", "1000005.json")):
            text = orchestrator.bericht_holen(1000005)
        self.assertIn("WARTET AUF KONTINGENT", text)
        self.assertIn("kein Absturz", text)


class FensterAnschluss(Grundlage):
    """`_naechsten_starten` auf einem nachgebauten Fenster (kein echtes Qt-Fenster)."""

    def fenster_attrappe(self, werte, schlange):
        fa = MagicMock()
        fa.wechselt = False
        fa._kontingent_sperre_uhr.isActive.return_value = False
        fa._warteschlange = schlange
        fa._kontingent_tor = self.tor(werte)
        fa._kontingent_gehalten_zeigen = lambda urteil: fenster.Werkbank. \
            _kontingent_gehalten_zeigen(fa, urteil)
        fa._kontingent_urteil_melden = lambda *a: fenster.Werkbank. \
            _kontingent_urteil_melden(fa, *a)
        fa._kontingent_nummern = lambda *a: []
        return fa

    def test_knapp_startet_nichts_danach_genau_einmal_je_auftrag(self):
        schlange = [eintrag("a", "opus"), eintrag("b")]
        fa = self.fenster_attrappe(stand(sitzung=95), schlange)
        fenster.Werkbank._naechsten_starten(fa)
        fa._auftrag_starten.assert_not_called()
        self.assertEqual(len(schlange), 2)
        fa._kontingent_sperre_uhr.start.assert_called()
        fa.sprecher.ton.assert_called_once_with("wartet")           # Beginn: einmal
        fenster.Werkbank._naechsten_starten(fa)                     # nochmal geprueft
        fa.sprecher.ton.assert_called_once_with("wartet")
        nach = datetime(2026, 10, 23, 14, 1, tzinfo=ZONE)
        with patch.object(kontingent, "jetzt", return_value=nach):
            fenster.Werkbank._naechsten_starten(fa)
            fenster.Werkbank._naechsten_starten(fa)
            fenster.Werkbank._naechsten_starten(fa)
        self.assertEqual(fa._auftrag_starten.call_count, 2)
        self.assertEqual([a.args[0] for a in fa._auftrag_starten.call_args_list], ["a", "b"])
        self.assertEqual(fa.sprecher.ton.call_count, 2)            # Beginn + Weiter

    def test_sparmodus_startet_mit_sonnet(self):
        fa = self.fenster_attrappe(stand(woche=82), [eintrag("a", "opus")])
        fenster.Werkbank._naechsten_starten(fa)
        self.assertEqual(fa._auftrag_starten.call_args.kwargs["modell_wunsch"], "sonnet")
        verlauf = [a.args[0] for a in fa._verlauf_anhaengen.call_args_list]
        self.assertTrue(any("Sonnet" in zeile for zeile in verlauf))


if __name__ == "__main__":
    unittest.main()
