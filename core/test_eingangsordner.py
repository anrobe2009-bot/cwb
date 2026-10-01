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
import tempfile
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
        self.assertTrue(eingangsordner.passend_fuer_projekt(pfad, "hausgemacht"))

    def test_passendes_projekt_gross_klein_egal(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "projekt": "cwb", "text": "x"})
        self.assertTrue(eingangsordner.passend_fuer_projekt(pfad, "CWB"))

    def test_fremdes_projekt_passt_nicht(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "projekt": "hausgemacht", "text": "x"})
        self.assertFalse(eingangsordner.passend_fuer_projekt(pfad, "CWB"))


class VerarbeitenTest(EingangsordnerTestBasis):

    def test_gueltiger_auftrag_wird_ausgefuehrt_und_landet_in_erledigt(self):
        pfad = self._datei_anlegen("a.json", {"quelle": "zeitschaltung", "text": "#CODE#\nTu etwas."})
        empfangen = []
        eingangsordner.verarbeiten(pfad, markierung_erkennen, empfangen.append)
        self.assertEqual(len(empfangen), 1)
        self.assertEqual(empfangen[0].inhalt, "Tu etwas.")
        self.assertFalse(pfad.exists())
        self.assertTrue((eingangsordner.erledigt_ordner() / "a.json").exists())
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
        self.assertTrue((eingangsordner.erledigt_ordner() / "a.json").exists())

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

    def test_namenskonflikt_in_erledigt_wird_nicht_ueberschrieben(self):
        (eingangsordner.erledigt_ordner() / "a.json").write_text("alt", encoding="utf-8")
        pfad = self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        eingangsordner.verarbeiten(pfad, markierung_erkennen, lambda a: None)
        alt = eingangsordner.erledigt_ordner() / "a.json"
        self.assertEqual(alt.read_text(encoding="utf-8"), "alt")
        treffer = list(eingangsordner.erledigt_ordner().glob("a_*.json"))
        self.assertEqual(len(treffer), 1)


class WartendeDateienTest(EingangsordnerTestBasis):

    def test_ignoriert_unterordner_und_fremde_endungen(self):
        self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        (self._ordner / "b.txt").write_text("kein auftrag", encoding="utf-8")
        gefunden = eingangsordner.wartende_dateien()
        self.assertEqual([p.name for p in gefunden], ["a.json"])

    def test_leerer_ordner_ergibt_leere_liste(self):
        self.assertEqual(eingangsordner.wartende_dateien(), [])


if __name__ == "__main__":
    unittest.main()
