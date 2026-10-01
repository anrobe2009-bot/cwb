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
        self.assertFalse(zurueck.exists())  # zweiter Versuch: erledigt
        self.assertTrue((eingangsordner.erledigt_ordner() / "a.json").exists())
        self.assertEqual(versuche["anzahl"], 2)


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
        self.assertEqual(eingangsordner.fremde_projekte("max-friends"), {})

    def test_eigenes_projekt_zaehlt_nicht_mit(self):
        self._datei_anlegen("a.json", {"quelle": "lokal", "projekt": "CWB", "text": "x"})
        self.assertEqual(eingangsordner.fremde_projekte("CWB"), {})

    def test_datei_ohne_projektfeld_zaehlt_nicht_mit(self):
        self._datei_anlegen("a.json", {"quelle": "lokal", "text": "x"})
        self.assertEqual(eingangsordner.fremde_projekte("CWB"), {})

    def test_fremde_dateien_werden_je_projekt_gezaehlt(self):
        self._datei_anlegen("a.json", {"quelle": "bruecke", "projekt": "CWB", "text": "x"})
        self._datei_anlegen("b.json", {"quelle": "bruecke", "projekt": "CWB", "text": "x"})
        self._datei_anlegen("c.json", {"quelle": "bruecke", "projekt": "hausgemacht", "text": "x"})
        ergebnis = eingangsordner.fremde_projekte("max-friends")
        self.assertEqual(ergebnis, {"CWB": 2, "hausgemacht": 1})

    def test_gross_klein_schreibung_zaehlt_zusammen(self):
        self._datei_anlegen("a.json", {"quelle": "bruecke", "projekt": "CWB", "text": "x"})
        self._datei_anlegen("b.json", {"quelle": "bruecke", "projekt": "cwb", "text": "x"})
        ergebnis = eingangsordner.fremde_projekte("max-friends")
        self.assertEqual(ergebnis, {"CWB": 2})


class GemischteWarteschlangeTest(EingangsordnerTestBasis):
    """Block 63: Bildet den Blick des Eingangswaechters nach (core/
    eingangsordner.py, Eingangswaechter._nachsehen) - fuer jede wartende
    Datei, aelteste zuerst, wird ohne passendes Projekt uebersprungen, sonst
    verarbeitet. Reproduziert den gemeldeten Fehler: drei Auftraege fuer
    Projekt CWB vor einem fuer max-friends, geoeffnet ist max-friends."""

    def _blick(self, projekt_name: str, ausfuehren) -> None:
        for pfad in eingangsordner.wartende_dateien():
            if not eingangsordner.passend_fuer_projekt(pfad, projekt_name):
                continue
            eingangsordner.verarbeiten(pfad, markierung_erkennen, ausfuehren)

    def test_passender_auftrag_laeuft_trotz_aelterer_fremder_auftraege(self):
        namen = ["a.json", "b.json", "c.json", "d.json"]
        projekte = ["CWB", "CWB", "CWB", "max-friends"]
        for index, (name, projekt) in enumerate(zip(namen, projekte)):
            pfad = self._datei_anlegen(
                name, {"quelle": "bruecke", "projekt": projekt, "text": f"#CODE#\nAuftrag {name}"}
            )
            os.utime(pfad, (1000 + index, 1000 + index))

        empfangen = []
        self._blick("max-friends", lambda auftrag: empfangen.append(auftrag.datei.name))

        # Nur der passende (juengste) Auftrag lief - die drei fuer CWB
        # blockieren ihn nicht und bleiben unangetastet liegen.
        self.assertEqual(empfangen, ["d.json"])
        verbliebene = {p.name for p in eingangsordner.wartende_dateien()}
        self.assertEqual(verbliebene, {"a.json", "b.json", "c.json"})
        # Keine der drei wurde je beansprucht (ausgefuehrt, verschoben o. ae.) -
        # einzig der gelaufene Auftrag (d.json) landet in erledigt/.
        self.assertFalse(list(eingangsordner.in_bearbeitung_ordner().glob("*.json")))
        erledigt = {p.name for p in eingangsordner.erledigt_ordner().glob("*.json")}
        self.assertEqual(erledigt, {"d.json"})

    def test_urspruengliche_reihenfolge_bleibt_beim_naechsten_blick_erhalten(self):
        for index, name in enumerate(["a.json", "b.json"]):
            pfad = self._datei_anlegen(
                name, {"quelle": "bruecke", "projekt": "CWB", "text": f"#CODE#\n{name}"}
            )
            os.utime(pfad, (1000 + index, 1000 + index))

        # Oeffnet zunaechst ein fremdes Projekt: nichts laeuft, nichts wird
        # beansprucht - die Reihenfolge der beiden wartenden Dateien bleibt.
        self._blick("max-friends", lambda auftrag: None)
        self.assertEqual(
            [p.name for p in eingangsordner.wartende_dateien()], ["a.json", "b.json"]
        )

        # Erst wenn CWB offen ist, laufen beide, aelteste zuerst.
        empfangen = []
        self._blick("CWB", lambda auftrag: empfangen.append(auftrag.datei.name))
        self.assertEqual(empfangen, ["a.json", "b.json"])


if __name__ == "__main__":
    unittest.main()
