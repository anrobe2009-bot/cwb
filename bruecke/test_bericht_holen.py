# FILE: bruecke/test_bericht_holen.py
"""Tests fuer bericht_holen (bruecke/server.py): Reihenfolge, Kennzeile, Nummer.

Aufruf: python -m unittest test_bericht_holen -v   (im Ordner bruecke, mit mcp/starlette)
"""
import os
import tempfile
import unittest

_ordner = tempfile.TemporaryDirectory()
os.environ["BRUECKE_SECRET_PATH"] = "test"
os.environ["BRUECKE_PC_TOKEN"] = "test"
os.environ["BRUECKE_DB_PFAD"] = os.path.join(_ordner.name, "t.db")

import server  # noqa: E402


def _auftrag(text):
    with server._verbindung() as conn:
        return conn.execute(
            "INSERT INTO auftraege (projekt, art, text, erstellt_am) VALUES ('cwb','CODE',?,'t')",
            (text,)).lastrowid


def _bericht(nummer, text, zeit="2026-10-22T10:00:00+00:00"):
    with server._verbindung() as conn:
        conn.execute("INSERT INTO berichte (auftrag_id, text, erstellt_am) VALUES (?,?,?)",
                     (nummer, text, zeit))


class BerichtHolenTest(unittest.TestCase):

    def setUp(self):
        with server._verbindung() as conn:
            conn.execute("DELETE FROM berichte")
            conn.execute("DELETE FROM auftraege")

    def test_umgekehrte_reihenfolge(self):
        a1 = _auftrag("Block 700\nerster")
        a2 = _auftrag("Block 701\nzweiter")
        _bericht(a2, "Bericht zwei")
        _bericht(a1, "Bericht eins")  # verspaetet hochgeladen
        neu = server._bericht_lesen()
        self.assertTrue(neu.startswith(f"Auftrag {a2} | Block 701 | Zeit "))
        self.assertTrue(neu.endswith("Bericht zwei"))
        alt = server._bericht_lesen(a1)
        self.assertTrue(alt.startswith(f"Auftrag {a1} | Block 700 | Zeit "))
        self.assertTrue(alt.endswith("Bericht eins"))

    def test_hinweis_ohne_nummer_zaehlt_nicht(self):
        a = _auftrag("ohne Blockkopf")
        _bericht(a, "echter Bericht")
        _bericht(None, "Hinweis")
        antwort = server._bericht_lesen()
        self.assertTrue(antwort.endswith("echter Bericht"))
        self.assertIn("Block -", antwort.splitlines()[0])

    def test_gleicher_auftrag_juengster_upload(self):
        a = _auftrag("Block 5")
        _bericht(a, "alt")
        _bericht(a, "neu")
        self.assertTrue(server._bericht_lesen(a).endswith("neu"))

    def test_fehlende_nummer_liefert_keinen_anderen(self):
        a = _auftrag("Block 5")
        _bericht(a, "da")
        self.assertEqual(server._bericht_lesen(a + 1), "noch nicht fertig")

    def test_vorhandene_kennzeile_wird_nicht_verdoppelt(self):
        a = _auftrag("Block 9\nx")
        kopf = f"Auftrag {a} | Block 9 | Zeit 2026-10-22T11:00:00+02:00"
        _bericht(a, kopf + "\nBericht mit Kopf")
        antwort = server._bericht_lesen(a)
        self.assertEqual(antwort, kopf + "\nBericht mit Kopf")
        self.assertEqual(antwort.count("Auftrag "), 1)
        self.assertEqual(server._bericht_lesen(), antwort)

    def test_alter_bericht_ohne_kennzeile_bekommt_eine(self):
        a = _auftrag("Block 9\nx")
        _bericht(a, "Auftrag erledigt, alles gut\nzweite Zeile")  # beginnt mit "Auftrag ", ist aber keine Kennzeile
        zeilen = server._bericht_lesen(a).split("\n")
        self.assertTrue(zeilen[0].startswith(f"Auftrag {a} | Block 9 | Zeit "))
        self.assertEqual(zeilen[1], "Auftrag erledigt, alles gut")

    def test_leer(self):
        self.assertEqual(server._bericht_lesen(), "noch nicht fertig")
        _bericht(None, "nur Hinweis")
        self.assertEqual(server._bericht_lesen(), "noch nicht fertig")


if __name__ == "__main__":
    unittest.main()
# END: bruecke/test_bericht_holen.py
