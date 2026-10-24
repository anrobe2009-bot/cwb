"""
CWB - Code Workbench
Unit-Tests fuer core/eingangsordner.py (Vorhaben "Bruecke", Stufe B1).

Laufen ohne Qt-Ereignisschleife und ohne den echten Datenordner anzufassen:
`eingangsordner.EINGANG_ORDNER` wird je Test durch einen temporaeren Ordner
ersetzt. Getestet werden nur die reinen Funktionen (Lesen, Ablehnen,
Verschieben) - die Qt-Klasse `Eingangswaechter` selbst ist duenner Klebstoff
um `wartende_dateien()`/`verarbeiten()` und braucht keine eigenen Tests.

Aufruf: python -m unittest core.test_eingangsordner -v
        (oder, aus dem Ordner core/: python test_eingangsordner.py -v)
"""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import eingangsordner
except ImportError:
    import eingangsordner


def markierung_erkennen(text: str) -> tuple[str, str]:
    """Nachgebaute Fassung von fenster.markierung_erkennen, nur fuer die
    vier Markierungen, ohne die Randzeichen-Behandlung des Originals -
    fuer diese Tests reicht das."""
    kopf, _, rest = text.partition("\n")
    art = {"#CODE#": "code", "#RUN#": "run", "#ADMIN#": "admin", "#BILD#": "bild"}.get(
        kopf.strip().upper()
    )
    if art:
        return art, rest.strip()
    return "", text.strip()


class EingangsordnerTestBasis(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._ordner = Path(self._tmp.name) / "eingang"
        self._patch = mock.patch.object(eingangsordner, "EINGANG_ORDNER", self._ordner)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        eingangsordner.sicherstellen()
        eingangsordner.annahmen_zuruecksetzen()
        self.addCleanup(eingangsordner.annahmen_zuruecksetzen)

    def _datei_anlegen(self, name: str, inhalt) -> Path:
        pfad = self._ordner / name
        if isinstance(inhalt, str):
            pfad.write_text(inhalt, encoding="utf-8")
        else:
            pfad.write_text(json.dumps(inhalt, ensure_ascii=False), encoding="utf-8")
        return pfad


class LesenTest(EingangsordnerTestBasis):

    def test_gueltige_datei_mit_markierung(self):
        pfad = self._datei_anlegen(
            "a.json", {"quelle": "zeitschaltung", "projekt": "CWB", "text": "#CODE#\nTu etwas."}
        )
        auftrag = eingangsordner.auftrag_lesen(pfad, markierung_erkennen)
        self.assertEqual(auftrag.quelle, "zeitschaltung")
        self.assertEqual(auftrag.projekt, "CWB")
        self.assertEqual(auftrag.art, "code")
        self.assertEqual(auftrag.inhalt, "Tu etwas.")

    def test_projekt_ist_optional(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "Ohne Markierung."})
        auftrag = eingangsordner.auftrag_lesen(pfad, markierung_erkennen)
        self.assertEqual(auftrag.projekt, "")
        self.assertEqual(auftrag.art, "")
        self.assertEqual(auftrag.inhalt, "Ohne Markierung.")

    def test_fehlende_quelle_ist_fehler(self):
        pfad = self._datei_anlegen("a.json", {"text": "Text"})
        with self.assertRaises(eingangsordner.EingangsFehler):
            eingangsordner.auftrag_lesen(pfad, markierung_erkennen)

    def test_fehlender_text_ist_fehler(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal"})
        with self.assertRaises(eingangsordner.EingangsFehler):
            eingangsordner.auftrag_lesen(pfad, markierung_erkennen)

    def test_kaputtes_json_ist_fehler(self):
        pfad = self._datei_anlegen("a.json", "{das ist kein json")
        with self.assertRaises(eingangsordner.EingangsFehler):
            eingangsordner.auftrag_lesen(pfad, markierung_erkennen)

    def test_json_liste_statt_objekt_ist_fehler(self):
        pfad = self._datei_anlegen("a.json", [1, 2, 3])
        with self.assertRaises(eingangsordner.EingangsFehler):
            eingangsordner.auftrag_lesen(pfad, markierung_erkennen)

    def test_utf8_bom_wird_gelesen(self):
        # PowerShell 5.1 (Set-Content -Encoding UTF8, siehe
        # werkzeuge/in_eingang.ps1) schreibt eine UTF-8-BOM vor den Text -
        # json.loads lehnt das roh ab ("Unexpected UTF-8 BOM").
        pfad = self._ordner / "a.json"
        inhalt = json.dumps({"quelle": "zeitschaltung", "text": "#CODE#\nTu etwas."},
                             ensure_ascii=False)
        pfad.write_bytes(b"\xef\xbb\xbf" + inhalt.encode("utf-8"))
        auftrag = eingangsordner.auftrag_lesen(pfad, markierung_erkennen)
        self.assertEqual(auftrag.quelle, "zeitschaltung")
        self.assertEqual(auftrag.art, "code")
        self.assertEqual(auftrag.inhalt, "Tu etwas.")

    def test_ohne_bom_weiterhin_lesbar(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        auftrag = eingangsordner.auftrag_lesen(pfad, markierung_erkennen)
        self.assertEqual(auftrag.inhalt, "x")


class AuftragNummerTest(EingangsordnerTestBasis):

    def test_auftrag_nummer_wird_gelesen(self):
        pfad = self._datei_anlegen(
            "a.json", {"quelle": "bruecke", "text": "x", "auftrag_nummer": 42}
        )
        auftrag = eingangsordner.auftrag_lesen(pfad, markierung_erkennen)
        self.assertEqual(auftrag.auftrag_nummer, 42)

    def test_auftrag_nummer_ist_optional(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        auftrag = eingangsordner.auftrag_lesen(pfad, markierung_erkennen)
        self.assertIsNone(auftrag.auftrag_nummer)

    def test_ungueltige_auftrag_nummer_wird_ignoriert(self):
        pfad = self._datei_anlegen(
            "a.json", {"quelle": "lokal", "text": "x", "auftrag_nummer": "nicht_numerisch"}
        )
        auftrag = eingangsordner.auftrag_lesen(pfad, markierung_erkennen)
        self.assertIsNone(auftrag.auftrag_nummer)


class AblegenTest(EingangsordnerTestBasis):

    def test_ablegen_legt_lesbare_datei_an(self):
        ziel = eingangsordner.ablegen("bruecke", "#CODE#\nTu etwas.", projekt="CWB",
                                       auftrag_nummer=7)
        self.assertTrue(ziel.is_file())
        self.assertEqual(ziel.suffix, ".json")
        auftrag = eingangsordner.auftrag_lesen(ziel, markierung_erkennen)
        self.assertEqual(auftrag.quelle, "bruecke")
        self.assertEqual(auftrag.projekt, "CWB")
        self.assertEqual(auftrag.art, "code")
        self.assertEqual(auftrag.auftrag_nummer, 7)

    def test_ablegen_ohne_auftrag_nummer(self):
        ziel = eingangsordner.ablegen("zeitschaltung", "x")
        auftrag = eingangsordner.auftrag_lesen(ziel, markierung_erkennen)
        self.assertIsNone(auftrag.auftrag_nummer)

    def test_ablegen_wird_vom_waechter_gefunden(self):
        eingangsordner.ablegen("bruecke", "x")
        self.assertEqual(len(eingangsordner.wartende_dateien()), 1)
        self.assertFalse(list(self._ordner.glob("*.teil")))


class NummernDublettenTest(EingangsordnerTestBasis):
    """Block 73: Dublettenschutz fuer Bruecken-Auftraege ueber
    auftrag_nummer, auf der Platte (`.nummern`) statt im Arbeitsspeicher."""

    def test_zweites_ablegen_mit_gleicher_nummer_wird_uebersprungen(self):
        erstes = eingangsordner.ablegen("bruecke", "x", auftrag_nummer=792)
        zweites = eingangsordner.ablegen("bruecke", "y", auftrag_nummer=792)
        self.assertIsNotNone(erstes)
        self.assertIsNone(zweites)
        self.assertEqual(len(eingangsordner.wartende_dateien()), 1)

    def test_andere_nummer_wird_normal_abgelegt(self):
        eingangsordner.ablegen("bruecke", "x", auftrag_nummer=1)
        eingangsordner.ablegen("bruecke", "y", auftrag_nummer=2)
        self.assertEqual(len(eingangsordner.wartende_dateien()), 2)

    def test_nummer_in_erledigt_wird_bei_verarbeiten_abgelehnt(self):
        # Die urspruengliche Datei "a.json" hat die Nummer 79 schon vorher
        # beansprucht (z.B. in einem frueheren CWB-Lauf) und liegt inzwischen
        # in erledigt/ - der physische Ort spielt fuer die Markierung keine
        # Rolle, nur ihr Name.
        eingangsordner._nummer_beanspruchen(79, "a.json")
        eingangsordner.erledigt_ordner().mkdir(parents=True, exist_ok=True)
        (eingangsordner.erledigt_ordner() / "a.json").write_text("{}", encoding="utf-8")
        pfad = self._datei_anlegen("b.json", {"quelle": "bruecke", "text": "x",
                                                "auftrag_nummer": 79})
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        self.assertEqual(empfangen, [])
        self.assertFalse(pfad.exists())
        self.assertTrue((eingangsordner.abgelehnt_ordner() / "b.json").exists())
        grund = (eingangsordner.abgelehnt_ordner() / "b.txt").read_text(encoding="utf-8")
        self.assertIn("79", grund)
        self.assertIn("schon da", grund)

    def test_nummer_in_laeuft_wird_bei_verarbeiten_abgelehnt(self):
        eingangsordner._nummer_beanspruchen(80, "a.json")
        eingangsordner.laeuft_ordner().mkdir(parents=True, exist_ok=True)
        (eingangsordner.laeuft_ordner() / "a.json").write_text("{}", encoding="utf-8")
        pfad = self._datei_anlegen("b.json", {"quelle": "bruecke", "text": "x",
                                                "auftrag_nummer": 80})
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        self.assertEqual(empfangen, [])
        self.assertTrue((eingangsordner.abgelehnt_ordner() / "b.json").exists())

    def test_auftrag_ohne_nummer_laeuft_trotz_fremder_nummer_normal(self):
        eingangsordner._nummer_beanspruchen(81, "a.json")
        pfad = self._datei_anlegen("b.json", {"quelle": "lokal", "text": "x"})
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        self.assertEqual(len(empfangen), 1)

    def test_derselbe_dateiname_gilt_nicht_als_dublette(self):
        """`verarbeiten()` prueft dieselbe Nummer ein zweites Mal (nach dem
        Ablegen) - fuer die eigene Datei darf das nicht als Dublette zaehlen."""
        ziel = eingangsordner.ablegen("bruecke", "#CODE#\nx", auftrag_nummer=55)
        empfangen = []
        eingangsordner.verarbeiten(ziel, markierung_erkennen, empfangen.append)
        self.assertEqual(len(empfangen), 1)
        self.assertTrue((eingangsordner.laeuft_ordner() / ziel.name).exists())

    def test_ueberlebt_neustart_simulation(self):
        """Keine Instanz, kein Modul-Zustand im Speicher noetig: eine
        Markierungsdatei, die so aussieht, als stuende sie schon von einem
        frueheren CWB-Lauf auf der Platte, wird trotzdem erkannt."""
        eingangsordner.nummern_ordner().mkdir(parents=True, exist_ok=True)
        (eingangsordner.nummern_ordner() / "999.json").write_text(
            json.dumps({"datei": "alt.json"}), encoding="utf-8"
        )
        ziel = eingangsordner.ablegen("bruecke", "x", auftrag_nummer=999)
        self.assertIsNone(ziel)

    def test_gleichzeitiges_ablegen_nur_eines_gewinnt(self):
        ergebnisse: list[Path | None] = [None, None]

        def ablegen(index: int) -> None:
            ergebnisse[index] = eingangsordner.ablegen("bruecke", f"x{index}",
                                                         auftrag_nummer=321)

        faeden = [threading.Thread(target=ablegen, args=(i,)) for i in range(2)]
        for faden in faeden:
            faden.start()
        for faden in faeden:
            faden.join()
        gewinner = [e for e in ergebnisse if e is not None]
        verlierer = [e for e in ergebnisse if e is None]
        self.assertEqual(len(gewinner), 1)
        self.assertEqual(len(verlierer), 1)
        self.assertEqual(len(eingangsordner.wartende_dateien()), 1)


class AdminSperreTest(unittest.TestCase):

    def test_admin_von_fremder_quelle_gesperrt(self):
        self.assertTrue(eingangsordner.admin_gesperrt("admin", "zeitschaltung"))
        self.assertTrue(eingangsordner.admin_gesperrt("admin", "bruecke"))

    def test_admin_von_lokal_erlaubt(self):
        self.assertFalse(eingangsordner.admin_gesperrt("admin", "lokal"))

    def test_andere_arten_nie_gesperrt(self):
        for art in ("code", "run", "bild", ""):
            self.assertFalse(eingangsordner.admin_gesperrt(art, "zeitschaltung"))


class ProjektzuordnungTest(EingangsordnerTestBasis):

    def test_ohne_projektfeld_passt_ueberall(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        self.assertTrue(eingangsordner.passend_fuer_projekt(pfad, "CWB"))
        self.assertTrue(eingangsordner.passend_fuer_projekt(pfad, "beispielprojekt"))

    def test_passendes_projekt_gross_klein_egal(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "projekt": "cwb", "text": "x"})
        self.assertTrue(eingangsordner.passend_fuer_projekt(pfad, "CWB"))

    def test_fremdes_projekt_passt_nicht(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "projekt": "beispielprojekt", "text": "x"})
        self.assertFalse(eingangsordner.passend_fuer_projekt(pfad, "CWB"))

    def test_bindestrich_und_leerzeichen_unscharf(self):
        pfad = self._datei_anlegen(
            "a.json", {"quelle": "lokal", "projekt": "Mein Projekt", "text": "x"}
        )
        self.assertTrue(eingangsordner.passend_fuer_projekt(pfad, "mein-projekt"))

    def test_alias_aus_zusatzprojekten(self):
        # Block 70, Teil C: "mein-projekt" ist nur ueber den eingetragenen
        # Alias mit "Mein und Projekt" gleichwertig - ohne ihn wuerden die
        # unterschiedlichen Woerter/Tippfehler keine Uebereinstimmung ergeben.
        pfad = self._datei_anlegen(
            "a.json", {"quelle": "bruecke", "projekt": "mein-projekt", "text": "x"}
        )
        with mock.patch.object(
            eingangsordner, "zusatzprojekte_lesen",
            return_value=[{"name": "Mein und Projekt", "pfad": "C:/Projekte/MeinProjekt",
                           "aliase": ["mein-projekt", "Mein & Projekt"]}],
        ):
            self.assertTrue(eingangsordner.passend_fuer_projekt(pfad, "Mein und Projekt"))


class ProjektGleichwertigTest(unittest.TestCase):

    def test_gross_klein_bindestrich_leerzeichen(self):
        self.assertTrue(eingangsordner.projekt_gleichwertig("CWB", "cwb"))
        self.assertTrue(eingangsordner.projekt_gleichwertig("Mein Projekt", "mein-projekt"))

    def test_ohne_alias_keine_uebereinstimmung(self):
        with mock.patch.object(eingangsordner, "zusatzprojekte_lesen", return_value=[]):
            self.assertFalse(
                eingangsordner.projekt_gleichwertig("mein-projekt", "Mein und Projekt")
            )

    def test_mit_alias_uebereinstimmung(self):
        with mock.patch.object(
            eingangsordner, "zusatzprojekte_lesen",
            return_value=[{"name": "Mein und Projekt", "pfad": "C:/Projekte/MeinProjekt",
                           "aliase": ["mein-projekt", "Mein & Projekt"]}],
        ):
            self.assertTrue(
                eingangsordner.projekt_gleichwertig("mein-projekt", "Mein und Projekt")
            )
            self.assertTrue(
                eingangsordner.projekt_gleichwertig("Mein & Projekt", "Mein und Projekt")
            )

    def test_leere_namen_sind_nicht_gleichwertig(self):
        self.assertFalse(eingangsordner.projekt_gleichwertig("", ""))
        self.assertFalse(eingangsordner.projekt_gleichwertig("CWB", ""))


class NaechsteFremdeProjektDateiTest(EingangsordnerTestBasis):

    def test_ohne_dateien_ist_none(self):
        self.assertIsNone(eingangsordner.naechste_fremde_projekt_datei("CWB"))

    def test_eigenes_und_projektloses_zaehlen_nicht(self):
        self._datei_anlegen("a.json", {"quelle": "lokal", "projekt": "CWB", "text": "x"})
        self._datei_anlegen("b.json", {"quelle": "lokal", "text": "x"})
        self.assertIsNone(eingangsordner.naechste_fremde_projekt_datei("CWB"))

    def test_aelteste_fremde_datei_gewinnt(self):
        self._datei_anlegen("a.json", {"quelle": "bruecke", "projekt": "beispielprojekt", "text": "x"})
        os.utime(self._ordner / "a.json", (1000, 1000))
        self._datei_anlegen("b.json", {"quelle": "bruecke", "projekt": "schreiber", "text": "x"})
        os.utime(self._ordner / "b.json", (2000, 2000))
        self.assertEqual(eingangsordner.naechste_fremde_projekt_datei("CWB"), "beispielprojekt")


class VerarbeitenTest(EingangsordnerTestBasis):

    def test_gueltiger_auftrag_wird_ausgefuehrt_und_bleibt_in_laeuft(self):
        # Block 70, Teil A: ein normaler Rueckkehr aus ausfuehren() heisst nur
        # "angenommen", nicht "fertig" - core/fenster.py arbeitet den Auftrag
        # meist noch asynchron ab. Die Datei darf darum NICHT schon hier nach
        # erledigt/ verschwinden, sonst waeren Bruecken-Auftraege 28/29 aus
        # dem gemeldeten Fehler verloren, sobald sie nur in die Warteschlange
        # gereiht wurden.
        pfad = self._datei_anlegen("a.json", {"quelle": "zeitschaltung", "text": "#CODE#\nTu etwas."})
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        self.assertEqual(len(empfangen), 1)
        self.assertEqual(empfangen[0].inhalt, "Tu etwas.")
        self.assertEqual(empfangen[0].datei, eingangsordner.laeuft_ordner() / "a.json")
        self.assertFalse(pfad.exists())
        self.assertTrue((eingangsordner.laeuft_ordner() / "a.json").exists())
        self.assertFalse((eingangsordner.erledigt_ordner() / "a.json").exists())
        self.assertFalse((eingangsordner.abgelehnt_ordner() / "a.json").exists())

    def test_admin_ohne_lokal_wird_abgelehnt_und_nicht_ausgefuehrt(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "bruecke", "text": "#ADMIN#\nGet-Service"})
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        self.assertEqual(empfangen, [])
        self.assertFalse(pfad.exists())
        self.assertTrue((eingangsordner.abgelehnt_ordner() / "a.json").exists())
        grund = (eingangsordner.abgelehnt_ordner() / "a.txt").read_text(encoding="utf-8")
        self.assertIn("ADMIN", grund)

    def test_admin_von_lokal_wird_ausgefuehrt(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "#ADMIN#\nGet-Service"})
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        self.assertEqual(len(empfangen), 1)
        self.assertEqual(empfangen[0].art, "admin")
        self.assertTrue((eingangsordner.laeuft_ordner() / "a.json").exists())

    def test_kaputte_datei_landet_in_abgelehnt_mit_grund(self):
        pfad = self._datei_anlegen("a.json", "kein json")
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        self.assertEqual(empfangen, [])
        self.assertTrue((eingangsordner.abgelehnt_ordner() / "a.json").exists())
        self.assertTrue((eingangsordner.abgelehnt_ordner() / "a.txt").exists())

    def test_ausfuehren_wirft_fehler_datei_landet_trotzdem_in_erledigt(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})

        def ausfuehren(_auftrag):
            raise RuntimeError("kaputt")

        eingangsordner.verarbeiten(pfad, markierung_erkennen, ausfuehren)
        self.assertTrue((eingangsordner.erledigt_ordner() / "a.json").exists())

    def test_namenskonflikt_in_laeuft_wird_nicht_ueberschrieben(self):
        (eingangsordner.laeuft_ordner() / "a.json").write_text("alt", encoding="utf-8")
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        eingangsordner.verarbeiten(pfad, markierung_erkennen, lambda a: None)
        alt = eingangsordner.laeuft_ordner() / "a.json"
        self.assertEqual(alt.read_text(encoding="utf-8"), "alt")
        treffer = list(eingangsordner.laeuft_ordner().glob("a_*.json"))
        self.assertEqual(len(treffer), 1)

    def test_auftrag_spaeter_legt_datei_unverarbeitet_zurueck(self):
        # Terminal oder Screenshot-Weg belegt (core/fenster.py,
        # _eingang_auftrag): die Datei darf nicht nach erledigt/ oder
        # abgelehnt/ verschwinden, sondern muss beim naechsten Blick erneut
        # auftauchen.
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "#RUN#\nipconfig"})

        def ausfuehren(_auftrag):
            raise eingangsordner.AuftragSpaeter("Terminal belegt")

        eingangsordner.verarbeiten(pfad, markierung_erkennen, ausfuehren)
        zurueck = self._ordner / "a.json"
        self.assertTrue(zurueck.exists())
        self.assertFalse((eingangsordner.erledigt_ordner() / "a.json").exists())
        self.assertFalse((eingangsordner.abgelehnt_ordner() / "a.json").exists())
        self.assertFalse((eingangsordner.in_bearbeitung_ordner() / "a.json").exists())
        self.assertEqual(eingangsordner.wartende_dateien(), [zurueck])

    def test_auftrag_spaeter_behaelt_reihenfolge_ueber_zeitstempel(self):
        # Path.replace() aendert den Zeitstempel nicht - die urspruengliche
        # Ankunftsreihenfolge (wartende_dateien() sortiert danach) bleibt
        # ueber eine Rueckstellung hinweg erhalten.
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "#RUN#\nipconfig"})
        vorher = pfad.stat().st_mtime

        def ausfuehren(_auftrag):
            raise eingangsordner.AuftragSpaeter("Terminal belegt")

        eingangsordner.verarbeiten(pfad, markierung_erkennen, ausfuehren)
        zurueck = self._ordner / "a.json"
        self.assertEqual(zurueck.stat().st_mtime, vorher)

    def test_auftrag_spaeter_wird_erneut_versucht_bis_erfolg(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "#RUN#\nipconfig"})
        versuche = {"anzahl": 0}

        def ausfuehren(_auftrag):
            versuche["anzahl"] += 1
            if versuche["anzahl"] < 2:
                raise eingangsordner.AuftragSpaeter("Terminal belegt")

        zurueck = self._ordner / "a.json"
        eingangsordner.verarbeiten(zurueck, markierung_erkennen, ausfuehren)
        self.assertTrue(zurueck.exists())  # erster Versuch: zurueckgestellt
        eingangsordner.verarbeiten(zurueck, markierung_erkennen, ausfuehren)
        self.assertFalse(zurueck.exists())  # zweiter Versuch: angenommen
        self.assertTrue((eingangsordner.laeuft_ordner() / "a.json").exists())
        self.assertEqual(versuche["anzahl"], 2)


class AbschliessenTest(EingangsordnerTestBasis):

    def test_abschliessen_verschiebt_von_laeuft_nach_erledigt(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        laeuft_pfad = empfangen[0].datei
        eingangsordner.abschliessen(laeuft_pfad)
        self.assertFalse(laeuft_pfad.exists())
        self.assertTrue((eingangsordner.erledigt_ordner() / "a.json").exists())

    def test_abschliessen_namenskonflikt_wird_nicht_ueberschrieben(self):
        (eingangsordner.erledigt_ordner() / "a.json").write_text("alt", encoding="utf-8")
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        eingangsordner.abschliessen(empfangen[0].datei)
        alt = eingangsordner.erledigt_ordner() / "a.json"
        self.assertEqual(alt.read_text(encoding="utf-8"), "alt")
        treffer = list(eingangsordner.erledigt_ordner().glob("a_*.json"))
        self.assertEqual(len(treffer), 1)

    def test_abschliessen_ohne_vorhandene_datei_ist_folgenlos(self):
        eingangsordner.abschliessen(eingangsordner.laeuft_ordner() / "fehlt.json")


class VerwerfenTest(EingangsordnerTestBasis):

    def test_verwerfen_verschiebt_von_laeuft_nach_abgelehnt_mit_grund(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        eingangsordner.verwerfen(empfangen[0].datei, "Not-Aus")
        self.assertFalse(empfangen[0].datei.exists())
        ziel = eingangsordner.abgelehnt_ordner() / "a.json"
        self.assertTrue(ziel.exists())
        self.assertEqual(ziel.with_suffix(".txt").read_text(encoding="utf-8"), "Not-Aus")

    def test_verwerfen_ohne_vorhandene_datei_ist_folgenlos(self):
        eingangsordner.verwerfen(eingangsordner.laeuft_ordner() / "fehlt.json", "egal")


class WiederAufnehmenTest(EingangsordnerTestBasis):
    """Block 70, Teil A: core/fenster.py ruft wieder_aufnehmen() beim Oeffnen
    eines Projekts auf - fuer Auftraege, die beim letzten Mal (Absturz,
    Neustart, Projektwechsel) nicht fertig wurden und darum noch in laeuft/
    liegen."""

    def _in_laeuft_anlegen(self, name: str, inhalt: dict, mtime: float | None = None) -> Path:
        pfad = eingangsordner.laeuft_ordner() / name
        pfad.write_text(json.dumps(inhalt, ensure_ascii=False), encoding="utf-8")
        if mtime is not None:
            os.utime(pfad, (mtime, mtime))
        return pfad

    def test_ohne_laeuft_dateien_passiert_nichts(self):
        self.assertEqual(eingangsordner.wieder_aufnehmen(markierung_erkennen, "CWB",
                                                           lambda a: None), (0, 0, 0))

    def test_passende_datei_wird_wieder_angenommen(self):
        self._in_laeuft_anlegen("a.json", {"quelle": "bruecke", "projekt": "CWB",
                                            "text": "#CODE#\nBlock 65"})
        empfangen = []
        anzahl, verworfen, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", empfangen.append)
        self.assertEqual(anzahl, 1)
        self.assertEqual(verworfen, 0)
        self.assertEqual(uebersprungen, 0)
        self.assertEqual(len(empfangen), 1)
        self.assertEqual(empfangen[0].inhalt, "Block 65")
        # Die Datei bleibt in laeuft/ liegen, bis core/fenster.py einen
        # echten Abschluss meldet (abschliessen()) - genau wie bei einem
        # frischen Auftrag.
        self.assertTrue((eingangsordner.laeuft_ordner() / "a.json").exists())

    def test_fremdes_projekt_bleibt_unangetastet(self):
        self._in_laeuft_anlegen("a.json", {"quelle": "bruecke", "projekt": "beispielprojekt",
                                            "text": "x"})
        empfangen = []
        anzahl, verworfen, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", empfangen.append)
        self.assertEqual(anzahl, 0)
        self.assertEqual(verworfen, 0)
        self.assertEqual(uebersprungen, 0)
        self.assertEqual(empfangen, [])
        self.assertTrue((eingangsordner.laeuft_ordner() / "a.json").exists())

    def test_reihenfolge_aelteste_zuerst(self):
        # mtime bewusst nur Sekunden auseinander und nah an "jetzt" - sonst
        # griffe die Alterssicherung (WIEDERAUFNAHME_MAX_ALTER_STUNDEN) und
        # beide Dateien würden übersprungen statt verglichen.
        jetzt = time.time()
        self._in_laeuft_anlegen("b.json", {"quelle": "bruecke", "text": "zweiter"},
                                 mtime=jetzt - 10)
        self._in_laeuft_anlegen("a.json", {"quelle": "bruecke", "text": "erster"},
                                 mtime=jetzt - 20)
        empfangen = []
        eingangsordner.wieder_aufnehmen(markierung_erkennen, "CWB", empfangen.append)
        self.assertEqual([a.inhalt for a in empfangen], ["erster", "zweiter"])

    def test_auftrag_spaeter_legt_datei_in_eingang_zurueck(self):
        self._in_laeuft_anlegen("a.json", {"quelle": "lokal", "text": "kein Markierungswort"})

        def ausfuehren(_auftrag):
            raise eingangsordner.AuftragSpaeter("Terminal belegt")

        anzahl, verworfen, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", ausfuehren)
        self.assertEqual(anzahl, 0)
        self.assertEqual(verworfen, 0)
        self.assertEqual(uebersprungen, 0)
        self.assertTrue((self._ordner / "a.json").exists())
        self.assertFalse((eingangsordner.laeuft_ordner() / "a.json").exists())

    def test_kaputte_datei_landet_in_abgelehnt(self):
        pfad = eingangsordner.laeuft_ordner() / "a.json"
        pfad.write_text("kein json", encoding="utf-8")
        anzahl, verworfen, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", lambda a: None)
        self.assertEqual(anzahl, 0)
        self.assertEqual(verworfen, 0)
        self.assertEqual(uebersprungen, 0)
        self.assertTrue((eingangsordner.abgelehnt_ordner() / "a.json").exists())

    def test_run_wird_nicht_automatisch_wiederholt(self):
        """Der eigentliche Auslöser des Fehlers (Nutzer, 06.10.2026): ein
        #RUN#-Befehl, der beim letzten Mal nicht fertig wurde, darf beim
        naechsten CWB-Start nicht blind erneut laufen - er koennte schon
        gewirkt oder ein eigenes Programm gestartet haben."""
        self._in_laeuft_anlegen("a.json", {"quelle": "lokal",
                                            "text": "#RUN#\nStart-Sleep 55"})
        aufgerufen = []
        anzahl, verworfen, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", aufgerufen.append)
        self.assertEqual(anzahl, 0)
        self.assertEqual(verworfen, 1)
        self.assertEqual(uebersprungen, 0)
        self.assertEqual(aufgerufen, [], "Der Befehl wurde tatsaechlich erneut ausgefuehrt")
        self.assertFalse((eingangsordner.laeuft_ordner() / "a.json").exists())
        ziel = eingangsordner.abgelehnt_ordner() / "a.json"
        self.assertTrue(ziel.exists())

    def test_admin_wird_nicht_automatisch_wiederholt(self):
        self._in_laeuft_anlegen("a.json", {"quelle": "lokal", "text": "#ADMIN#\nipconfig"})
        aufgerufen = []
        anzahl, verworfen, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", aufgerufen.append)
        self.assertEqual(anzahl, 0)
        self.assertEqual(verworfen, 1)
        self.assertEqual(uebersprungen, 0)
        self.assertEqual(aufgerufen, [])

    def test_zu_alte_datei_wird_uebersprungen_und_landet_in_abgelehnt(self):
        """Block 70, Nachbesserung: eine Datei, die laenger als
        WIEDERAUFNAHME_MAX_ALTER_STUNDEN in laeuft/ liegt, gilt als vermutlich
        schon erledigt und wird NICHT erneut angestossen - mit Logzeile,
        nicht still (hier per Rueckgabewert und Zielordner belegt)."""
        zu_alt = time.time() - (eingangsordner.WIEDERAUFNAHME_MAX_ALTER_STUNDEN + 1) * 3600
        self._in_laeuft_anlegen("a.json", {"quelle": "bruecke", "text": "#CODE#\nBlock 38"},
                                 mtime=zu_alt)
        aufgerufen = []
        anzahl, verworfen, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", aufgerufen.append)
        self.assertEqual(anzahl, 0)
        self.assertEqual(verworfen, 0)
        self.assertEqual(uebersprungen, 1)
        self.assertEqual(aufgerufen, [])
        self.assertFalse((eingangsordner.laeuft_ordner() / "a.json").exists())
        self.assertTrue((eingangsordner.abgelehnt_ordner() / "a.json").exists())

    def test_frische_datei_mit_vorhandenem_bericht_wird_uebersprungen_und_landet_in_erledigt(self):
        """Zweiter Zweig der Sicherung: `bereits_erledigt` (von core/fenster.py
        uebergeben) meldet fuer die Blocknummer schon einen gespeicherten
        Bericht - dann gilt der Auftrag als erledigt, auch wenn er noch
        frisch in laeuft/ liegt."""
        self._in_laeuft_anlegen("a.json", {"quelle": "bruecke", "text": "#CODE#\nBlock 42"})
        aufgerufen = []
        anzahl, verworfen, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", aufgerufen.append,
            bereits_erledigt=lambda nummer: nummer == 42)
        self.assertEqual(anzahl, 0)
        self.assertEqual(verworfen, 0)
        self.assertEqual(uebersprungen, 1)
        self.assertEqual(aufgerufen, [])
        self.assertFalse((eingangsordner.laeuft_ordner() / "a.json").exists())
        self.assertTrue((eingangsordner.erledigt_ordner() / "a.json").exists())

    def test_bereits_erledigt_ohne_treffer_laeuft_normal_weiter(self):
        self._in_laeuft_anlegen("a.json", {"quelle": "bruecke", "text": "#CODE#\nBlock 43"})
        aufgerufen = []
        anzahl, verworfen, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", aufgerufen.append,
            bereits_erledigt=lambda nummer: nummer == 42)
        self.assertEqual(anzahl, 1)
        self.assertEqual(uebersprungen, 0)
        self.assertEqual(len(aufgerufen), 1)


class WartendeDateienTest(EingangsordnerTestBasis):

    def test_ignoriert_unterordner_und_fremde_endungen(self):
        self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        (self._ordner / "b.txt").write_text("kein auftrag", encoding="utf-8")
        gefunden = eingangsordner.wartende_dateien()
        self.assertEqual([p.name for p in gefunden], ["a.json"])

    def test_leerer_ordner_ergibt_leere_liste(self):
        self.assertEqual(eingangsordner.wartende_dateien(), [])


class FremdeProjekteTest(EingangsordnerTestBasis):
    """core/eingangsordner.py: fremde_projekte() - Grundlage fuer den
    Kopfzeilen- und Ansage-Hinweis in core/fenster.py (Block 63)."""

    def test_ohne_dateien_ist_leer(self):
        self.assertEqual(eingangsordner.fremde_projekte("mein-projekt"), {})

    def test_eigenes_projekt_zaehlt_nicht_mit(self):
        self._datei_anlegen("a.json", {"quelle": "lokal", "projekt": "CWB", "text": "x"})
        self.assertEqual(eingangsordner.fremde_projekte("CWB"), {})

    def test_datei_ohne_projektfeld_zaehlt_nicht_mit(self):
        self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        self.assertEqual(eingangsordner.fremde_projekte("CWB"), {})

    def test_fremde_dateien_werden_je_projekt_gezaehlt(self):
        self._datei_anlegen("a.json", {"quelle": "bruecke", "projekt": "CWB", "text": "x"})
        self._datei_anlegen("b.json", {"quelle": "bruecke", "projekt": "CWB", "text": "x"})
        self._datei_anlegen("c.json", {"quelle": "bruecke", "projekt": "beispielprojekt", "text": "x"})
        ergebnis = eingangsordner.fremde_projekte("mein-projekt")
        self.assertEqual(ergebnis, {"CWB": 2, "beispielprojekt": 1})

    def test_gross_klein_schreibung_zaehlt_zusammen(self):
        self._datei_anlegen("a.json", {"quelle": "bruecke", "projekt": "CWB", "text": "x"})
        self._datei_anlegen("b.json", {"quelle": "bruecke", "projekt": "cwb", "text": "x"})
        ergebnis = eingangsordner.fremde_projekte("mein-projekt")
        self.assertEqual(ergebnis, {"CWB": 2})


class UnbekannteVerwerfenTest(EingangsordnerTestBasis):
    """core/eingangsordner.py: unbekannte_verwerfen() - Auftraege fuer ein
    Projekt, das es nicht gibt, bleiben nicht endlos im Eingang."""

    def _alt(self, name: str, inhalt, alter_s: float) -> Path:
        pfad = self._datei_anlegen(name, inhalt)
        zeit = time.time() - alter_s
        os.utime(pfad, (zeit, zeit))
        return pfad

    def test_alte_unbekannte_wird_verworfen_mit_grund(self):
        pfad = self._alt("a.json", {"quelle": "bruecke", "projekt": "WordCraft",
                                    "text": "x", "auftrag_nummer": "882"}, 16 * 60)
        ergebnis = eingangsordner.unbekannte_verwerfen(lambda n: False)
        self.assertEqual(ergebnis, [("WordCraft", "a.json")])
        self.assertFalse(pfad.exists())
        ziel = eingangsordner.abgelehnt_ordner() / "a.json"
        self.assertTrue(ziel.exists())
        self.assertIn("WordCraft", ziel.with_suffix(".txt").read_text(encoding="utf-8"))
        self.assertEqual(eingangsordner.wartende_dateien(), [])

    def test_junge_unbekannte_bleibt(self):
        self._alt("a.json", {"quelle": "bruecke", "projekt": "WordCraft", "text": "x"}, 5 * 60)
        self.assertEqual(eingangsordner.unbekannte_verwerfen(lambda n: False), [])
        self.assertEqual(len(eingangsordner.wartende_dateien()), 1)

    def test_alte_bekannte_bleibt(self):
        self._alt("a.json", {"quelle": "bruecke", "projekt": "maxfriends", "text": "x"}, 3600)
        self.assertEqual(eingangsordner.unbekannte_verwerfen(lambda n: True), [])
        self.assertEqual(len(eingangsordner.wartende_dateien()), 1)

    def test_alte_ohne_projektfeld_bleibt(self):
        self._alt("a.json", {"quelle": "lokal", "text": "x"}, 3600)
        self.assertEqual(eingangsordner.unbekannte_verwerfen(lambda n: False), [])
        self.assertEqual(len(eingangsordner.wartende_dateien()), 1)

    def test_nur_die_unbekannte_geht(self):
        self._alt("a.json", {"quelle": "bruecke", "projekt": "WordCraft", "text": "x"}, 3600)
        self._alt("b.json", {"quelle": "bruecke", "projekt": "maxfriends", "text": "x"}, 3600)
        ergebnis = eingangsordner.unbekannte_verwerfen(lambda n: n == "maxfriends")
        self.assertEqual(ergebnis, [("WordCraft", "a.json")])
        self.assertEqual([p.name for p in eingangsordner.wartende_dateien()], ["b.json"])

    def test_bekanntes_projekt_gross_klein_und_bindestrich_wird_nie_verworfen(self):
        self._alt("a.json", {"quelle": "bruecke", "projekt": "cwb", "text": "x"}, 3600)
        self._alt("b.json", {"quelle": "bruecke", "projekt": "max-friends", "text": "x"}, 3600)
        ist_bekannt = eingangsordner.bekannt_unter(["CWB", "maxfriends"])
        self.assertEqual(eingangsordner.unbekannte_verwerfen(ist_bekannt), [])
        self.assertEqual(len(eingangsordner.wartende_dateien()), 2)

    def test_leere_projektliste_verwirft_nichts(self):
        self._alt("a.json", {"quelle": "bruecke", "projekt": "WordCraft", "text": "x"}, 3600)
        ist_bekannt = eingangsordner.bekannt_unter([])
        self.assertEqual(eingangsordner.unbekannte_verwerfen(ist_bekannt), [])
        self.assertEqual(len(eingangsordner.wartende_dateien()), 1)

    def test_eingereihter_auftrag_in_laeuft_wird_nie_wegen_alters_verworfen(self):
        eingangsordner.sicherstellen()
        pfad = eingangsordner.laeuft_ordner() / "q.json"
        pfad.write_text('{"quelle": "bruecke", "projekt": "Unbekannt", "text": "x"}',
                        encoding="utf-8")
        zeit = time.time() - 5 * 3600
        os.utime(pfad, (zeit, zeit))
        self.assertEqual(eingangsordner.unbekannte_verwerfen(lambda n: False), [])
        self.assertTrue(pfad.exists())

    def test_verwerfen_schreibt_den_grund_ins_journal(self):
        eingangsordner.sicherstellen()
        pfad = eingangsordner.laeuft_ordner() / "q.json"
        pfad.write_text('{"quelle": "bruecke", "text": "x", "auftrag_nummer": 894}',
                        encoding="utf-8")
        with mock.patch.object(eingangsordner.auftragsjournal, "schreibe") as journal:
            eingangsordner.verwerfen(pfad, "Warteschlange geleert")
        self.assertEqual(journal.call_args[0][0], "verworfen")
        self.assertIn("Warteschlange geleert", journal.call_args[0][1])
        self.assertEqual(journal.call_args[1]["nummer"], 894)

    def test_verworfene_unbekannte_nennt_den_grund_im_journal(self):
        self._alt("a.json", {"quelle": "bruecke", "projekt": "WordCraft", "text": "x"}, 3600)
        with mock.patch.object(eingangsordner.auftragsjournal, "schreibe") as journal:
            eingangsordner.unbekannte_verwerfen(lambda n: False)
        self.assertIn("ist unbekannt", journal.call_args[0][1])


class GemischteWarteschlangeTest(EingangsordnerTestBasis):
    """Block 63: Bildet den Blick des Eingangswaechters nach (core/
    eingangsordner.py, Eingangswaechter._nachsehen) - fuer jede wartende
    Datei, aelteste zuerst, wird ohne passendes Projekt uebersprungen, sonst
    verarbeitet. Reproduziert den gemeldeten Fehler: drei Auftraege fuer
    Projekt CWB vor einem fuer mein-projekt, geoeffnet ist mein-projekt."""

    def _blick(self, projekt_name: str, ausfuehren) -> None:
        for pfad in eingangsordner.wartende_dateien():
            if not eingangsordner.passend_fuer_projekt(pfad, projekt_name):
                continue
            eingangsordner.verarbeiten(pfad, markierung_erkennen, ausfuehren)

    def test_passender_auftrag_laeuft_trotz_aelterer_fremder_auftraege(self):
        namen = ["a.json", "b.json", "c.json", "d.json"]
        projekte = ["CWB", "CWB", "CWB", "mein-projekt"]
        for index, (name, projekt) in enumerate(zip(namen, projekte)):
            pfad = self._datei_anlegen(
                name, {"quelle": "bruecke", "projekt": projekt, "text": f"#CODE#\nAuftrag {name}"}
            )
            os.utime(pfad, (1000 + index, 1000 + index))

        empfangen = []
        self._blick("mein-projekt", lambda auftrag: empfangen.append(auftrag.datei.name))

        # Nur der passende (juengste) Auftrag lief - die drei fuer CWB
        # blockieren ihn nicht und bleiben unangetastet liegen.
        self.assertEqual(empfangen, ["d.json"])
        verbliebene = {p.name for p in eingangsordner.wartende_dateien()}
        self.assertEqual(verbliebene, {"a.json", "b.json", "c.json"})
        # Keine der drei wurde je beansprucht (ausgefuehrt, verschoben o. ae.) -
        # einzig der angenommene Auftrag (d.json) landet in laeuft/, nicht
        # schon in erledigt/ (Block 70, Teil A).
        self.assertFalse(list(eingangsordner.in_bearbeitung_ordner().glob("*.json")))
        laeuft = {p.name for p in eingangsordner.laeuft_ordner().glob("*.json")}
        self.assertEqual(laeuft, {"d.json"})
        self.assertFalse(list(eingangsordner.erledigt_ordner().glob("*.json")))

    def test_urspruengliche_reihenfolge_bleibt_beim_naechsten_blick_erhalten(self):
        for index, name in enumerate(["a.json", "b.json"]):
            pfad = self._datei_anlegen(
                name, {"quelle": "bruecke", "projekt": "CWB", "text": f"#CODE#\n{name}"}
            )
            os.utime(pfad, (1000 + index, 1000 + index))

        # Oeffnet zunaechst ein fremdes Projekt: nichts laeuft, nichts wird
        # beansprucht - die Reihenfolge der beiden wartenden Dateien bleibt.
        self._blick("mein-projekt", lambda auftrag: None)
        self.assertEqual(
            [p.name for p in eingangsordner.wartende_dateien()], ["a.json", "b.json"]
        )

        # Erst wenn CWB offen ist, laufen beide, aelteste zuerst.
        empfangen = []
        self._blick("CWB", lambda auftrag: empfangen.append(auftrag.datei.name))
        self.assertEqual(empfangen, ["a.json", "b.json"])


class WartezeitTest(unittest.TestCase):
    """core/eingangsordner.py: `_wartezeit_setzen`/`_wartet_noch` - die reine
    Kuehlzeit-Logik hinter der Reparatur des Haengers vom 07.10.2026, ohne
    Qt und ohne echtes Warten."""

    def setUp(self):
        eingangsordner._naechster_versuch.clear()
        self.addCleanup(eingangsordner._naechster_versuch.clear)

    def test_frisch_gesetzte_wartezeit_blockt(self):
        eingangsordner._wartezeit_setzen("a.json")
        self.assertTrue(eingangsordner._wartet_noch("a.json"))

    def test_ohne_eintrag_blockt_nichts(self):
        self.assertFalse(eingangsordner._wartet_noch("nie_gesetzt.json"))

    def test_abgelaufene_wartezeit_blockt_nicht_mehr(self):
        eingangsordner._naechster_versuch["a.json"] = 0.0
        self.assertFalse(eingangsordner._wartet_noch("a.json"))


class NachsehenWiederholungTest(EingangsordnerTestBasis):
    """Belegt die Reparatur des Haengers vom 07.10.2026 (py-spy-Beleg:
    haenger/haenger_2026-10-07_10-05-48.txt): `_beanspruchen` und
    `_zurueckstellen` aendern den vom Eingangswaechter beobachteten Ordner
    selbst und loesen dadurch sofort das naechste directoryChanged aus - vor
    der Reparatur fuetterte das eine Schleife im GUI-Faden (Blick ->
    beanspruchen -> AuftragSpaeter -> zurueckstellen -> naechster Blick),
    solange eine Datei dauerhaft zurueckgestellt blieb (Terminal belegt).
    Hier werden mehrere solche Bliche direkt nacheinander simuliert - ohne
    echten QFileSystemWatcher und ohne echtes Warten, deterministisch und
    schnell."""

    def setUp(self):
        super().setUp()
        self.addCleanup(eingangsordner._naechster_versuch.clear)

    def _waechter(self, ausfuehren):
        return eingangsordner.Eingangswaechter(
            markierung_erkennen, lambda: True, lambda: "CWB", ausfuehren)

    def test_dauerhaft_zurueckgestellte_datei_wird_nicht_bei_jedem_blick_erneut_beansprucht(self):
        eingangsordner.ablegen("lokal", "#RUN#\nipconfig")

        def ausfuehren(_auftrag):
            raise eingangsordner.AuftragSpaeter("Terminal belegt")

        waechter = self._waechter(ausfuehren)
        beansprucht = {"anzahl": 0}
        original = eingangsordner._beanspruchen

        def gezaehlt(pfad):
            beansprucht["anzahl"] += 1
            return original(pfad)

        # Zehn Bliche direkt nacheinander stehen fuer zehn rasch
        # aufeinanderfolgende directoryChanged-Ereignisse.
        with mock.patch.object(eingangsordner, "_beanspruchen", gezaehlt):
            for _ in range(10):
                waechter._nachsehen()

        self.assertEqual(beansprucht["anzahl"], 1,
                          "die Datei wurde trotz Wartezeit erneut beansprucht")
        self.assertEqual(len(eingangsordner.wartende_dateien()), 1)

    def test_nach_ablauf_der_wartezeit_wird_erneut_versucht(self):
        pfad = eingangsordner.ablegen("lokal", "#RUN#\nipconfig")
        versuche = {"anzahl": 0}
        empfangen = []

        def ausfuehren(auftrag):
            versuche["anzahl"] += 1
            if versuche["anzahl"] < 2:
                raise eingangsordner.AuftragSpaeter("Terminal belegt")
            empfangen.append(auftrag)

        waechter = self._waechter(ausfuehren)
        waechter._nachsehen()
        self.assertEqual(versuche["anzahl"], 1)
        self.assertEqual(empfangen, [])

        # Statt echter Wartezeit: die Wartemarke direkt in die Vergangenheit
        # setzen, so wie es nach Ablauf von RUECKSTELL_WARTEZEIT_S aussaehe.
        eingangsordner._naechster_versuch[pfad.name] = 0.0
        waechter._nachsehen()
        self.assertEqual(versuche["anzahl"], 2)
        self.assertEqual(len(empfangen), 1)
        self.assertEqual(eingangsordner.wartende_dateien(), [])

    def test_wiedereintritt_wird_abgewiesen(self):
        # Simuliert ein directoryChanged, das (entgegen dem Normalfall einer
        # einzelnen Qt-Ereignisschleife) waehrend eines laufenden Blicks
        # eintrifft - der zweite, verschachtelte Aufruf darf nichts tun.
        eingangsordner.ablegen("lokal", "#RUN#\nipconfig")
        innerer_aufruf = {"erfolgt": False}

        def ausfuehren(_auftrag):
            waechter._nachsehen()
            innerer_aufruf["erfolgt"] = True
            raise eingangsordner.AuftragSpaeter("Terminal belegt")

        waechter = self._waechter(ausfuehren)
        waechter._nachsehen()
        self.assertTrue(innerer_aufruf["erfolgt"])
        # Trotz des verschachtelten Aufrufs wurde die Datei nur einmal
        # zurueckgestellt, nicht zusaetzlich beansprucht oder verloren.
        self.assertEqual(len(eingangsordner.wartende_dateien()), 1)


class DoppelaufnahmeTest(EingangsordnerTestBasis):
    """Ein Bruecken-Auftrag darf je Nummer nur EINMAL angenommen werden. Der
    Waechter nimmt beim Start schon an (starten -> _nachsehen); danach geht
    core/fenster.py durch wieder_aufnehmen() - und fand dieselbe Datei in
    laeuft/ noch einmal (Log 20.10.2026 15:37, "Platz 2" und "Beim Start
    wieder aufgenommen: 1")."""

    def _bruecke_auftrag(self, nummer=746, projekt="cwb", text="#CODE#\nBlock 742"):
        return eingangsordner.ablegen("bruecke", text, projekt=projekt,
                                       auftrag_nummer=nummer)

    def _waechter(self, ausfuehren):
        return eingangsordner.Eingangswaechter(
            markierung_erkennen, lambda: True, lambda: "CWB", ausfuehren)

    def test_waechter_und_wieder_aufnehmen_nehmen_nur_einmal_an(self):
        self._bruecke_auftrag()
        angenommen = []
        waechter = self._waechter(angenommen.append)
        waechter._nachsehen()
        self.assertEqual(len(angenommen), 1)
        anzahl, verworfen, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", angenommen.append)
        self.assertEqual((anzahl, verworfen, uebersprungen), (0, 0, 0))
        self.assertEqual(len(angenommen), 1, "Auftrag zweimal angenommen")
        self.assertEqual(len(list(eingangsordner.laeuft_ordner().glob("*.json"))), 1,
                         "laeuft-Datei muss bis zum Abschluss bleiben")

    def test_projektwechsel_durch_bruecken_auftrag(self):
        """Der Auftrag fuer ein anderes Projekt wartet im Eingang; das neue
        Fenster (Projekt CWB) holt ihn beim Start und geht dann durch
        wieder_aufnehmen."""
        self._bruecke_auftrag(projekt="CWB")
        angenommen = []
        neues_fenster = self._waechter(angenommen.append)
        neues_fenster.starten()
        eingangsordner.wieder_aufnehmen(markierung_erkennen, "CWB", angenommen.append)
        neues_fenster.anhalten()
        self.assertEqual(len(angenommen), 1)

    def test_nach_zweiter_annahme_auch_mit_geaendertem_dateinamen(self):
        self._bruecke_auftrag(nummer=5)
        angenommen = []
        self._waechter(angenommen.append)._nachsehen()
        # Dieselbe Nummer unter anderem Dateinamen in laeuft/ (Namenskonflikt
        # beim Verschieben haengt einen Zeitstempel an).
        alt = next(eingangsordner.laeuft_ordner().glob("*.json"))
        alt.rename(alt.with_name("anders_20261020_153745.json"))
        eingangsordner.wieder_aufnehmen(markierung_erkennen, "CWB", angenommen.append)
        self.assertEqual(len(angenommen), 1)

    def test_neues_fenster_nimmt_verlorenen_auftrag_wieder_auf(self):
        """Absturzschutz bleibt: was ein frueheres Fenster/ein frueherer
        Prozess hielt und nie abschloss, wird aufgenommen."""
        self._bruecke_auftrag(nummer=9)
        altes_fenster = []
        self._waechter(altes_fenster.append)._nachsehen()
        self.assertEqual(len(altes_fenster), 1)
        neues_fenster = []
        self._waechter(neues_fenster.append)   # leert die Liste der Annahmen
        anzahl, _v, _u = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", neues_fenster.append)
        self.assertEqual(anzahl, 1)
        self.assertEqual(len(neues_fenster), 1)

    def test_neustart_mitten_im_auftrag_startet_code_auftrag_erneut(self):
        """Neuer Prozess = leere Annahmeliste: ein unfertiger #CODE#-Auftrag
        wird gewollt wieder aufgenommen (Absturzschutz, Block 70)."""
        self._bruecke_auftrag(nummer=11)
        erster = []
        eingangsordner.verarbeiten(next(self._ordner.glob("*.json")),
                                    markierung_erkennen, erster.append)
        self.assertEqual(len(erster), 1)
        eingangsordner.annahmen_zuruecksetzen()    # frischer Prozess
        zweiter = []
        anzahl, _v, _u = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", zweiter.append)
        self.assertEqual((anzahl, len(zweiter)), (1, 1))

    def test_hochgeladener_bericht_verhindert_wiederaufnahme(self):
        self._bruecke_auftrag(nummer=13)
        erster = []
        eingangsordner.verarbeiten(next(self._ordner.glob("*.json")),
                                    markierung_erkennen, erster.append)
        eingangsordner.bericht_vermerken(13)
        self.assertTrue(eingangsordner.bericht_hochgeladen(13))
        self.assertFalse(eingangsordner.bericht_hochgeladen(14))
        eingangsordner.annahmen_zuruecksetzen()    # Neustart
        zweiter = []
        anzahl, _v, uebersprungen = eingangsordner.wieder_aufnehmen(
            markierung_erkennen, "CWB", zweiter.append)
        self.assertEqual((anzahl, uebersprungen, zweiter), (0, 1, []))
        self.assertFalse(list(eingangsordner.laeuft_ordner().glob("*.json")))
        self.assertTrue(list(eingangsordner.erledigt_ordner().glob("*.json")))

    def test_vermerk_behaelt_dateinamen_der_nummer(self):
        self._bruecke_auftrag(nummer=15)
        name = next(self._ordner.glob("*.json")).name
        eingangsordner.verarbeiten(self._ordner / name, markierung_erkennen, lambda a: None)
        eingangsordner.bericht_vermerken(15)
        self.assertEqual(eingangsordner._nummer_beanspruchen(15, name), None)
        self.assertNotEqual(eingangsordner._nummer_beanspruchen(15, "fremd.json"), None)

    def test_auftrag_spaeter_gilt_nicht_als_angenommen(self):
        self._bruecke_auftrag(nummer=17, text="#RUN#\nls")
        def spaeter(_a):
            raise eingangsordner.AuftragSpaeter("Terminal belegt")
        eingangsordner.verarbeiten(next(self._ordner.glob("*.json")),
                                    markierung_erkennen, spaeter)
        self.assertEqual(eingangsordner._angenommene_nummern, set())


if __name__ == "__main__":
    unittest.main()
