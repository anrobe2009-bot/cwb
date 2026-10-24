"""
CWB - Code Workbench
Tests fuer core/kontingent.py (Kontingent-Stand, Hochrechnung, Stufen, Anzeige)
und die Anbindung in core/orchestrator.py. Feste Uhrzeiten, Datei im
Temp-Ordner, Einstellungen als Attrappe - nichts beruehrt den echten
Datenordner.

Aufruf: python -m unittest core.test_kontingent_stand -v
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

try:
    from . import kontingent, orchestrator
except ImportError:
    import kontingent
    import orchestrator

ZONE = kontingent.ZONE


def zeit(tag, stunde, minute=0, monat=10):
    return datetime(2026, monat, tag, stunde, minute, tzinfo=ZONE)


# 2026-10-23 ist ein Freitag, 22.10. Donnerstag, 24.10. Samstag.
FREITAG_11_30 = zeit(23, 11, 30)
SAMSTAG_11_30 = zeit(24, 11, 30)


class _Basis(unittest.TestCase):
    def setUp(self):
        self._ordner = tempfile.TemporaryDirectory()
        self.addCleanup(self._ordner.cleanup)
        self.datei = Path(self._ordner.name) / "kontingent.json"
        patcher = mock.patch.object(kontingent, "einstellungen_lesen", return_value={})
        self.einstellungen = patcher.start()
        self.addCleanup(patcher.stop)

    def setzen(self, gemessen=FREITAG_11_30, **felder):
        felder.setdefault("woche_reset", "Do 10:00")
        return kontingent.setzen(gemessen=gemessen, datei=self.datei, **felder)


class SetzenLesenTest(_Basis):
    def test_setzen_und_lesen(self):
        self.setzen(sitzung_prozent=25, sitzung_reset="14:00", woche_prozent=7,
                    quelle="foto")
        stand = kontingent.lesen(self.datei)
        self.assertEqual(stand["sitzung_prozent"], 25)
        self.assertEqual(stand["sitzung_reset"], "14:00")
        self.assertEqual(stand["woche_prozent"], 7)
        self.assertEqual(stand["woche_reset"], "Do 10:00")
        self.assertEqual(stand["quelle"], "foto")
        self.assertTrue(stand["gemessen"].startswith("2026-10-23T11:30:00"))

    def test_fehlende_felder_bleiben_erhalten(self):
        self.setzen(sitzung_prozent=25, sitzung_reset="14:00", woche_prozent=7)
        self.setzen(sitzung_prozent=30)
        stand = kontingent.lesen(self.datei)
        self.assertEqual(stand["woche_prozent"], 7)
        self.assertEqual(stand["sitzung_prozent"], 30)
        self.assertEqual(stand["sitzung_reset"], "14:00")

    def test_fehlende_datei(self):
        self.assertIsNone(kontingent.lesen(self.datei))
        self.assertIsNone(kontingent.auswerten(None))
        self.assertEqual(kontingent.zeile(None), "")

    def test_kaputte_oder_alte_datei(self):
        self.datei.write_text("kein json", encoding="utf-8")
        self.assertIsNone(kontingent.lesen(self.datei))
        self.datei.write_text(json.dumps({"woche_prozent": 5}), encoding="utf-8")
        self.assertIsNone(kontingent.lesen(self.datei))
        self.datei.write_text("[1]", encoding="utf-8")
        self.assertIsNone(kontingent.lesen(self.datei))

    def test_ungueltige_eingaben(self):
        with self.assertRaises(ValueError):
            self.setzen(woche_prozent=140)
        with self.assertRaises(ValueError):
            self.setzen(woche_prozent=5, woche_reset="Xx 10:00")
        with self.assertRaises(ValueError):
            self.setzen(sitzung_prozent=5, sitzung_reset="25:00")
        with self.assertRaises(ValueError):
            self.setzen(woche_prozent=5, quelle="geraten")
        self.assertFalse(self.datei.exists())

    def test_wochenreset_vorgabe_aus_einstellung(self):
        self.einstellungen.return_value = {"kontingent_woche_reset": "Fr 9:30"}
        stand = kontingent.setzen(woche_prozent=5, gemessen=FREITAG_11_30, datei=self.datei)
        self.assertEqual(stand["woche_reset"], "Fr 09:30")
        self.einstellungen.return_value = {"kontingent_woche_reset": "Unsinn"}
        self.assertEqual(kontingent.woche_reset_einstellung(), "Do 10:00")

    def test_kommandozeile(self):
        with mock.patch.object(kontingent, "DATEI", self.datei), \
                mock.patch("builtins.print") as ausgabe:
            code = kontingent.main(["setzen", "--sitzung", "25", "--sitzung-reset", "14:00",
                                    "--woche", "7", "--woche-reset", "Do 10:00"])
            self.assertEqual(code, 0)
            self.assertEqual(kontingent.main(["zeigen"]), 0)
            self.assertEqual(kontingent.main(["setzen", "--woche", "300"]), 1)
            self.assertEqual(kontingent.main(["setzen"]), 2)
        gedruckt = "\n".join(str(a.args[0]) for a in ausgabe.call_args_list)
        self.assertIn("Woche 7 %", gedruckt)
        self.assertIn("Stufe:", gedruckt)


class HochrechnungTest(_Basis):
    def test_sieben_prozent_am_freitag_reicht(self):
        self.setzen(woche_prozent=7)
        a = kontingent.auswerten(kontingent.lesen(self.datei), FREITAG_11_30)
        self.assertEqual(a["woche_urteil"], "reicht")
        self.assertAlmostEqual(a["woche_hochrechnung"], 46.0, delta=1)
        self.assertEqual(a["stufe"], "normal")

    def test_achtzig_prozent_am_samstag_reicht_nicht(self):
        self.setzen(gemessen=SAMSTAG_11_30, woche_prozent=80)
        a = kontingent.auswerten(kontingent.lesen(self.datei), SAMSTAG_11_30)
        self.assertEqual(a["woche_urteil"], "reicht nicht")
        self.assertGreater(a["woche_hochrechnung"], 100)

    def test_knapp_zwischen_grenze_und_hundert(self):
        # Dienstag 27.10. 22:00, 5,5 Tage verstrichen: 70 % -> rund 89 %
        gemessen = zeit(27, 22)
        self.setzen(gemessen=gemessen, woche_prozent=70)
        a = kontingent.auswerten(kontingent.lesen(self.datei), gemessen)
        self.assertEqual(a["woche_urteil"], "knapp")

    def test_kurz_nach_reset_keine_explosion(self):
        gemessen = zeit(22, 10, 5)     # fuenf Minuten nach Do 10:00
        self.setzen(gemessen=gemessen, woche_prozent=3)
        a = kontingent.auswerten(kontingent.lesen(self.datei), gemessen)
        self.assertLessEqual(a["woche_hochrechnung"], 3 / kontingent.ANTEIL_MINIMUM + 0.1)

    def test_sitzung_hochrechnung(self):
        # Reset 14:00, gemessen 11:30: 2,5 h von 5 h -> 25 % -> 50 %
        self.setzen(sitzung_prozent=25, sitzung_reset="14:00")
        a = kontingent.auswerten(kontingent.lesen(self.datei), FREITAG_11_30)
        self.assertAlmostEqual(a["sitzung_hochrechnung"], 50.0, delta=0.5)
        self.assertEqual(a["sitzung_urteil"], "reicht")

    def test_sitzung_reset_ueber_mitternacht(self):
        gemessen = zeit(23, 22)
        self.setzen(gemessen=gemessen, sitzung_prozent=40, sitzung_reset="01:00")
        a = kontingent.auswerten(kontingent.lesen(self.datei), gemessen)
        self.assertEqual(a["sitzung_reset_zeit"], zeit(24, 1))
        self.assertAlmostEqual(a["sitzung_hochrechnung"], 40 / (2 / 5), delta=0.5)
        # Nach dem Reset: Sitzung neu, nicht mehr eingerechnet
        spaeter = kontingent.auswerten(kontingent.lesen(self.datei), zeit(24, 1, 30))
        self.assertTrue(spaeter["sitzung_neu"])
        self.assertIsNone(spaeter["sitzung_hochrechnung"])

    def test_wochenreset_wird_nach_vorn_abgeleitet(self):
        self.setzen(woche_prozent=7)
        a = kontingent.auswerten(kontingent.lesen(self.datei), FREITAG_11_30)
        self.assertEqual(a["woche_reset_zeit"], zeit(29, 10))   # Do 29.10.

    def test_zeitumstellung_haelt_uhrzeit(self):
        # Umstellung auf Winterzeit am 25.10.2026: Reset bleibt 10:00 Ortszeit
        gemessen = zeit(23, 11, 30)
        reset = kontingent._naechster_wochenreset(gemessen, 3, 10, 0)
        self.assertEqual((reset.hour, reset.minute, reset.day), (10, 0, 29))
        gemessen = zeit(22, 11)    # Do nach 10:00, Reset naechste Woche ueber Umstellung
        reset = kontingent._naechster_wochenreset(gemessen, 3, 10, 0)
        self.assertEqual(reset.hour, 10)
        self.assertEqual(reset.utcoffset(), timedelta(hours=1))

    def test_zeitzone_utc_eingabe(self):
        # 09:30 UTC = 11:30 Berlin (Sommerzeit)
        aus_utc = datetime.fromisoformat("2026-10-23T09:30:00+00:00")
        self.setzen(gemessen=aus_utc, woche_prozent=7)
        a = kontingent.auswerten(kontingent.lesen(self.datei), FREITAG_11_30)
        self.assertEqual(a["alter"], timedelta(0))


class AlterStufenTest(_Basis):
    def test_frisch_und_veraltet(self):
        self.setzen(woche_prozent=7)
        stand = kontingent.lesen(self.datei)
        self.assertFalse(kontingent.auswerten(stand, FREITAG_11_30 + timedelta(hours=5, minutes=59))["veraltet"])
        a = kontingent.auswerten(stand, FREITAG_11_30 + timedelta(hours=6, minutes=1))
        self.assertTrue(a["veraltet"])
        self.assertIn("veraltet", kontingent.zeile(a))

    def test_stand_vor_wochenreset_ist_veraltet(self):
        self.setzen(woche_prozent=90)
        a = kontingent.auswerten(kontingent.lesen(self.datei), zeit(29, 10, 5))
        self.assertTrue(a["veraltet"])
        self.assertTrue(a["woche_neu"])
        self.assertEqual(a["stufe"], "normal")   # alter Wert zaehlt nicht mehr

    def test_stufen_und_schwellen(self):
        def stufe(woche=None, sitzung=None, sitzung_reset=None, gemessen=FREITAG_11_30):
            self.datei.unlink(missing_ok=True)      # kein Rest vom vorigen Stand
            self.setzen(gemessen=gemessen, woche_prozent=woche, sitzung_prozent=sitzung,
                        sitzung_reset=sitzung_reset)
            return kontingent.auswerten(kontingent.lesen(self.datei), gemessen)["stufe"]
        self.assertEqual(stufe(woche=7), "normal")
        self.assertEqual(stufe(woche=81), "sparmodus")
        self.assertEqual(stufe(woche=80.0), "sparmodus")   # Hochrechnung > 85
        self.assertEqual(stufe(woche=91), "knapp")
        self.assertEqual(stufe(woche=7, sitzung=95, sitzung_reset="14:00"), "knapp")
        # Hochrechnung allein (Stand unter 80 %): Dienstag 22:00, 5,5 von 7 Tagen
        dienstag = zeit(27, 22)
        self.assertEqual(stufe(woche=60, gemessen=dienstag), "normal")      # Linie 76 %
        self.assertEqual(stufe(woche=70, gemessen=dienstag), "sparmodus")   # Linie 89 %

    def test_schwellen_aus_einstellung(self):
        self.einstellungen.return_value = {"kontingent_spar_prozent": 50,
                                           "kontingent_knapp_prozent": 60}
        self.setzen(woche_prozent=55)
        self.assertEqual(kontingent.auswerten(kontingent.lesen(self.datei), FREITAG_11_30)["stufe"],
                         "sparmodus")
        self.setzen(woche_prozent=61)
        self.assertEqual(kontingent.auswerten(kontingent.lesen(self.datei), FREITAG_11_30)["stufe"],
                         "knapp")
        self.einstellungen.return_value = {"kontingent_spar_prozent": "x"}
        self.assertEqual(kontingent.spar_schwelle(), 80)

    def test_abgelaufene_sitzung_zaehlt_nicht_fuer_knapp(self):
        self.setzen(woche_prozent=7, sitzung_prozent=95, sitzung_reset="14:00")
        a = kontingent.auswerten(kontingent.lesen(self.datei), zeit(23, 15))
        self.assertEqual(a["stufe"], "normal")


class SdkTest(_Basis):
    ZUSTAND = {"woche_prozent": 82, "sitzung_prozent": 41,
               "woche_reset": "Do 10:00", "sitzung_reset": "16:00"}

    def test_sdk_ueberschreibt_foto(self):
        self.setzen(woche_prozent=7, sitzung_prozent=25, sitzung_reset="14:00", quelle="foto")
        stand = kontingent.sdk_uebernehmen(self.ZUSTAND, self.datei)
        self.assertEqual(stand["quelle"], "sdk")
        gelesen = kontingent.lesen(self.datei)
        self.assertEqual((gelesen["woche_prozent"], gelesen["sitzung_prozent"]), (82, 41))
        self.assertEqual(gelesen["sitzung_reset"], "16:00")

    def test_ohne_prozent_bleibt_stand(self):
        self.setzen(woche_prozent=7)
        vorher = self.datei.read_text(encoding="utf-8")
        self.assertIsNone(kontingent.sdk_uebernehmen({"woche_prozent": None}, self.datei))
        self.assertIsNone(kontingent.sdk_uebernehmen(None, self.datei))
        self.assertEqual(self.datei.read_text(encoding="utf-8"), vorher)

    def test_gleiche_werte_schreiben_nicht_neu(self):
        kontingent.sdk_uebernehmen(self.ZUSTAND, self.datei)
        erste = kontingent.lesen(self.datei)["gemessen"]
        with mock.patch.object(kontingent, "setzen") as setzen:
            kontingent.sdk_uebernehmen(self.ZUSTAND, self.datei)
            setzen.assert_not_called()
        self.assertEqual(kontingent.lesen(self.datei)["gemessen"], erste)

    def test_sitzung_liefert_neue_felder(self):
        try:
            from . import sitzung
        except ImportError:
            import sitzung
        eintrag = {"utilization": 0.82, "resets_at": zeit(29, 10).timestamp(),
                   "status": "allowed_warning", "rate_limit_type": "seven_day"}
        with mock.patch.object(sitzung, "_kontingent_prozent",
                               side_effect=lambda e: 82 if e is eintrag else None):
            z = sitzung._kontingent_zustand_berechnen(None, eintrag)
        self.assertEqual(z["woche_prozent"], 82)
        self.assertIn("woche_reset", z)
        self.assertIn("sitzung_prozent", z)


class AnzeigeTest(_Basis):
    def test_zeile_normal(self):
        self.setzen(woche_prozent=7, sitzung_prozent=25, sitzung_reset="14:00")
        z = kontingent.zeile(kontingent.auswerten(kontingent.lesen(self.datei), FREITAG_11_30))
        self.assertEqual(
            z, "Kontingent: Woche 7 % · Sitzung 25 % bis 14:00 · reicht (Stand 0 Min.)")

    def test_zeile_stufe_und_alter(self):
        self.setzen(woche_prozent=85, sitzung_prozent=25, sitzung_reset="14:00")
        z = kontingent.zeile(kontingent.auswerten(
            kontingent.lesen(self.datei), FREITAG_11_30 + timedelta(hours=7)))
        self.assertIn("sparmodus", z)
        self.assertIn("Stand 7 Std., veraltet", z)

    def test_orchestrator_anzeige_mit_stand(self):
        with mock.patch.object(kontingent, "DATEI", self.datei):
            kontingent.setzen(woche_prozent=95, gemessen=kontingent.jetzt(), datei=self.datei,
                              woche_reset="Do 10:00")
            zeile, stufe = orchestrator.kontingent_anzeige(None)
        self.assertTrue(zeile.startswith("Kontingent: Woche 95 %"))
        self.assertEqual(stufe, "knapp")

    def test_orchestrator_anzeige_sdk_ueberschreibt(self):
        with mock.patch.object(kontingent, "DATEI", self.datei):
            kontingent.setzen(woche_prozent=7, gemessen=kontingent.jetzt(), datei=self.datei,
                              woche_reset="Do 10:00")
            zeile, _ = orchestrator.kontingent_anzeige(
                {"woche_prozent": 83, "woche_anzeige": "Woche 83 %"})
        self.assertIn("Woche 83 %", zeile)
        self.assertIn("SDK", zeile)

    def test_orchestrator_anzeige_ohne_stand_alte_zeile(self):
        with mock.patch.object(kontingent, "DATEI", self.datei):
            zeile, stufe = orchestrator.kontingent_anzeige(None)
        self.assertEqual(zeile, "Kontingent: noch nicht gemeldet")
        self.assertIsNone(stufe)


if __name__ == "__main__":
    unittest.main()
