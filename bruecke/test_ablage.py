# FILE: bruecke/test_ablage.py
"""Tests fuer das Ablagefach (bruecke/ablage.py). Ohne MCP und ohne Netz.

Aufruf: python -m unittest test_ablage -v   (im Ordner bruecke)
"""
import datetime
import os
import tempfile
import unittest

import ablage

UTC = datetime.timezone.utc


class AblageTest(unittest.TestCase):

    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.ordner.name, "t.db")
        ablage.init(self.db)

    def tearDown(self):
        self.ordner.cleanup()

    def test_eintraege_werden_nie_ueberschrieben(self):
        a = ablage.ablegen(self.db, "erster", art="bericht", auftrag_nummer=5)
        b = ablage.ablegen(self.db, "zweiter", art="bericht", auftrag_nummer=5)
        self.assertEqual((a, b), (1, 2))
        self.assertIn("erster", ablage.lesen(self.db, a))
        self.assertIn("zweiter", ablage.lesen(self.db, b))

    def test_ohne_auftragsnummer_und_projekt(self):
        n = ablage.ablegen(self.db, "Build ok", art="build")
        self.assertIn("Auftrag -", ablage.liste(self.db))
        self.assertEqual(n, 1)

    def test_art_wird_geprueft_und_normalisiert(self):
        with self.assertRaises(ValueError):
            ablage.ablegen(self.db, "x", art="quatsch")
        n = ablage.ablegen(self.db, "x", art=" FEHLER ")
        self.assertIn("| fehler |", ablage.liste(self.db))
        self.assertEqual(n, 1)

    def test_leerer_oder_zu_langer_text_abgelehnt(self):
        with self.assertRaises(ValueError):
            ablage.ablegen(self.db, "   ")
        with self.assertRaises(ValueError):
            ablage.ablegen(self.db, "x" * (ablage.MAX_TEXT + 1))

    def test_liste_kurz_ohne_volltext_neueste_zuerst(self):
        ablage.ablegen(self.db, "a" * 50, projekt="p1", titel="Alt")
        ablage.ablegen(self.db, "b" * 7, projekt="p2", titel="Neu", art="fehler", auftrag_nummer=3)
        zeilen = ablage.liste(self.db).splitlines()
        self.assertEqual(len(zeilen), 2)
        self.assertTrue(zeilen[0].startswith("Nr 2 |"))
        self.assertIn("Auftrag 3 | p2 | fehler | Neu | 7 Zeichen", zeilen[0])
        self.assertNotIn("bbbbbbb", ablage.liste(self.db))

    def test_liste_filter(self):
        ablage.ablegen(self.db, "x", projekt="p1", art="hinweis")
        ablage.ablegen(self.db, "y", projekt="p2", art="fehler")
        ablage.ablegen(self.db, "z", projekt="p2", art="hinweis")
        self.assertEqual(len(ablage.liste(self.db, projekt="p2").splitlines()), 2)
        self.assertEqual(len(ablage.liste(self.db, art="fehler").splitlines()), 1)
        self.assertEqual(len(ablage.liste(self.db, anzahl=1).splitlines()), 1)
        self.assertEqual(ablage.liste(self.db, projekt="gibtsnicht"), "Keine Protokolle gefunden.")

    def test_liste_seit(self):
        alt = datetime.datetime.now(UTC) - datetime.timedelta(days=3)
        ablage.ablegen(self.db, "alt", jetzt=alt)
        ablage.ablegen(self.db, "neu")
        self.assertEqual(len(ablage.liste(self.db, seit="1d").splitlines()), 1)
        self.assertEqual(len(ablage.liste(self.db, seit="5d").splitlines()), 2)
        gestern = (datetime.datetime.now(UTC) - datetime.timedelta(days=1)).isoformat()
        self.assertEqual(len(ablage.liste(self.db, seit=gestern).splitlines()), 1)
        with self.assertRaises(ValueError):
            ablage.liste(self.db, seit="irgendwann")

    def test_lesen_stueckweise(self):
        n = ablage.ablegen(self.db, "0123456789")
        stueck = ablage.lesen(self.db, n, von=2, bis=5)
        kopf, _, text = stueck.partition("\n")
        self.assertEqual(text, "234")
        self.assertIn("weiter mit von=5", kopf)
        ende = ablage.lesen(self.db, n, von=5)
        self.assertTrue(ende.endswith("56789"))
        self.assertIn("Ende", ende.splitlines()[0])

    def test_lesen_ohne_bis_ist_begrenzt(self):
        n = ablage.ablegen(self.db, "x" * (ablage.LESE_BLOCK + 500))
        kopf, _, text = ablage.lesen(self.db, n).partition("\n")
        self.assertEqual(len(text), ablage.LESE_BLOCK)
        self.assertIn(f"weiter mit von={ablage.LESE_BLOCK}", kopf)

    def test_lesen_unbekannt_und_dahinter(self):
        with self.assertRaises(ValueError):
            ablage.lesen(self.db, 99)
        n = ablage.ablegen(self.db, "abc")
        self.assertIn("liegt dahinter", ablage.lesen(self.db, n, von=10))

    def test_aufraeumen_nach_14_tagen(self):
        jetzt = datetime.datetime.now(UTC)
        ablage.ablegen(self.db, "uralt", jetzt=jetzt - datetime.timedelta(days=15))
        ablage.ablegen(self.db, "frisch", jetzt=jetzt - datetime.timedelta(days=13))
        n = ablage.ablegen(self.db, "heute", jetzt=jetzt)
        zeilen = ablage.liste(self.db).splitlines()
        self.assertEqual(len(zeilen), 2)
        self.assertEqual(n, 3)

    def test_aufraeumen_ab_2000_aelteste_zuerst(self):
        with ablage.verbindung(self.db) as conn:
            jetzt = datetime.datetime.now(UTC).isoformat()
            conn.executemany(
                "INSERT INTO protokolle (zeit, art, text) VALUES (?, 'hinweis', 'x')",
                [(jetzt,)] * ablage.MAX_EINTRAEGE)
        n = ablage.ablegen(self.db, "ueber der Grenze")
        with ablage.verbindung(self.db) as conn:
            anzahl = conn.execute("SELECT COUNT(*) AS n FROM protokolle").fetchone()["n"]
            kleinste = conn.execute("SELECT MIN(nummer) AS m FROM protokolle").fetchone()["m"]
        self.assertEqual(anzahl, ablage.MAX_EINTRAEGE)
        self.assertEqual(kleinste, 2)
        self.assertEqual(n, ablage.MAX_EINTRAEGE + 1)


if __name__ == "__main__":
    unittest.main()
# END: bruecke/test_ablage.py
