"""
CWB - Code Workbench
Tests fuer die Linux-Freigaben (core/pfade.py: linux_freigaben,
freigaben_linux_ergaenzen, freigaben_lesen) und dafuer, dass die Sperrliste
fuer Zugangsdaten trotz Freigabe von Home hart bleibt (core/sicherheit.py).
Alles in Temp-Ordnern, keine echten Einstellungen, keine Fenster.
"""

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import pfade, sicherheit
except ImportError:
    import pfade
    import sicherheit

log = logging.getLogger(__name__)


@unittest.skipIf(sys.platform == "win32", "Linux-Freigaben gibt es nur unter Linux")
class LinuxFreigaben(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.heim = Path(self._temp.name).resolve() / "heim"
        self.heim.mkdir()
        self.datei = Path(self._temp.name) / "einstellungen.json"
        alt = pfade.EINSTELLUNGEN_DATEI
        pfade.EINSTELLUNGEN_DATEI = self.datei
        self.addCleanup(setattr, pfade, "EINSTELLUNGEN_DATEI", alt)
        patch = mock.patch.object(Path, "home", return_value=self.heim)
        patch.start()
        self.addCleanup(patch.stop)

    def _pfade(self) -> list[str]:
        return [e["pfad"] for e in pfade.freigaben_lesen()]

    def test_vorgaben_enthalten_home_tmp_media_mnt(self):
        pfadliste = [e["pfad"] for e in pfade.linux_freigaben()]
        self.assertEqual(pfadliste[0], str(self.heim))
        self.assertIn("/tmp", pfadliste)
        self.assertIn("/mnt", pfadliste)
        self.assertIn(str(Path("/media") / self.heim.name), pfadliste)

    def test_erster_aufruf_legt_liste_und_werkzeugordner_an(self):
        pfadliste = self._pfade()
        for erwartet in (str(self.heim), "/tmp", "/mnt"):
            self.assertIn(erwartet, pfadliste)
        self.assertTrue((self.heim / ".cwb-werkzeuge").is_dir())

    def test_bestehende_liste_wird_einmal_ergaenzt_ohne_duplikate(self):
        self.datei.write_text(json.dumps({"freigaben": [
            {"name": "Projekte", "pfad": str(self.heim / "projekte")},
            {"name": "Tmp", "pfad": "/tmp"},
        ]}), encoding="utf-8")
        pfadliste = self._pfade()
        self.assertEqual(pfadliste.count("/tmp"), 1)
        self.assertIn(str(self.heim), pfadliste)
        self.assertIn("/mnt", pfadliste)
        self.assertEqual(len(self._pfade()), len(pfadliste))

    def test_entfernte_freigabe_kommt_nicht_zurueck(self):
        self._pfade()
        pfade.freigabe_entfernen("/mnt")
        self.assertNotIn("/mnt", self._pfade())

    def test_vorhandener_werkzeugordner_bleibt_unberuehrt(self):
        ordner = self.heim / ".cwb-werkzeuge"
        ordner.mkdir()
        (ordner / "x.txt").write_text("a", encoding="utf-8")
        self._pfade()
        self.assertTrue((ordner / "x.txt").is_file())


@unittest.skipIf(sys.platform == "win32", "Linux-Pfade")
class GeheimnisseBleibenGesperrt(unittest.TestCase):
    """Home ist freigegeben, Schluessel- und Tokendateien bleiben trotzdem
    in jedem Ordner gesperrt."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.heim = Path(self._temp.name).resolve() / "heim"
        (self.heim / "projekt").mkdir(parents=True)
        (self.heim / "sonst").mkdir()
        (self.heim / ".ssh").mkdir()
        (self.heim / ".aws").mkdir()
        freigaben = [{"name": "Home", "pfad": str(self.heim)},
                     {"name": "tmp", "pfad": "/tmp"}]
        patch = mock.patch.object(sicherheit, "freigaben_lesen", return_value=freigaben)
        patch.start()
        self.addCleanup(patch.stop)
        self.grenze = sicherheit.Ordnergrenze(self.heim / "projekt")

    def _urteil(self, pfad):
        return self.grenze.pruefe(pfad)

    def test_gewoehnliche_datei_in_home_ist_frei(self):
        datei = self.heim / "sonst" / "notiz.txt"
        datei.write_text("a", encoding="utf-8")
        self.assertTrue(self._urteil(datei).frei)

    def test_tmp_ist_frei(self):
        self.assertTrue(self._urteil("/tmp/cwb_test_frei.txt").frei)

    def test_geheimnisse_bleiben_trotz_home_gesperrt(self):
        gesperrt = [
            self.heim / "sonst" / ".env",
            self.heim / "sonst" / ".env.local",
            self.heim / "projekt" / ".env",
            self.heim / ".ssh" / "id_ed25519",
            self.heim / ".ssh" / "config",
            self.heim / ".aws" / "credentials",
            self.heim / "sonst" / "server.pem",
            self.heim / "sonst" / "privat.key",
            self.heim / "sonst" / "api_token.json",
            self.heim / "sonst" / "secrets.yaml",
            self.heim / ".netrc",
            Path("/tmp/.env"),
            Path("/tmp/dienst.pem"),
        ]
        for pfad in gesperrt:
            with self.subTest(pfad=str(pfad)):
                self.assertTrue(self._urteil(pfad).verboten, f"nicht gesperrt: {pfad}")

    def test_gnupg_bleibt_trotz_home_gesperrt(self):
        """Das Urteil der Ordnergrenze gilt fuer Lesen wie Schreiben."""
        (self.heim / ".gnupg").mkdir()
        for pfad in (self.heim / ".gnupg",
                     self.heim / ".gnupg" / "pubring.kbx",
                     self.heim / ".gnupg" / "private-keys-v1.d" / "abc.key",
                     self.heim / "sonst" / ".gnupg" / "trustdb.gpg"):
            with self.subTest(pfad=str(pfad)):
                urteil = self._urteil(pfad)
                self.assertTrue(urteil.verboten, f"nicht gesperrt: {pfad}")
                self.assertFalse(urteil.frei)

    def test_harte_ordnersperren_gelten_weiter(self):
        for pfad in ("/etc/hosts", "/usr/bin/python3", "/root/x"):
            with self.subTest(pfad=pfad):
                self.assertTrue(self._urteil(pfad).verboten)


if __name__ == "__main__":
    unittest.main()
