"""
CWB - Code Workbench
Unit-Tests fuer core/bruecke.py (Vorhaben "Bruecke", Stufe B3).

Laufen ohne echten Server: requests.request wird durch einen Schein-Server
ersetzt (unittest.mock), der je nach Basis-Adresse (lokal/öffentlich)
antwortet oder einen Netzfehler wirft. Der Thread BrueckenFaden selbst wird
nicht gestartet (keine Qt-Ereignisschleife in Tests) - getestet werden die
reinen Funktionen und `_einen_durchlauf` direkt.

Aufruf: python -m unittest core.test_bruecke -v
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

try:
    from . import bruecke, eingangsordner
except ImportError:
    import bruecke
    import eingangsordner


def markierung_erkennen(text: str) -> tuple[str, str]:
    kopf, _, rest = text.partition("\n")
    art = {"#CODE#": "code", "#RUN#": "run", "#ADMIN#": "admin", "#BILD#": "bild"}.get(
        kopf.strip().upper()
    )
    if art:
        return art, rest.strip()
    return "", text.strip()


class SchonServer:
    """Ersetzt requests.request: `lokal_antwort` bzw. `oeffentlich_antwort`
    sind Funktionen (methode, url, **kwargs) -> requests.Response oder lösen
    requests.RequestException aus, um einen Netzfehler nachzubilden."""

    def __init__(self, lokal=None, oeffentlich=None):
        self.lokal = lokal
        self.oeffentlich = oeffentlich
        self.aufrufe: list[tuple[str, str]] = []

    def __call__(self, methode, url, **kwargs):
        self.aufrufe.append((methode, url))
        if url.startswith(bruecke.LOKALE_BASIS):
            if self.lokal is None:
                raise requests.ConnectionError("lokal nicht erreichbar (Test)")
            return self.lokal(methode, url, **kwargs)
        if self.oeffentlich is None:
            raise requests.ConnectionError("öffentlich nicht erreichbar (Test)")
        return self.oeffentlich(methode, url, **kwargs)


def _antwort(status=200, daten=None) -> mock.Mock:
    antwort = mock.Mock(spec=requests.Response)
    antwort.status_code = status
    antwort.content = b"x" if daten is not None else b""
    antwort.json.return_value = daten
    if status >= 400:
        antwort.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    else:
        antwort.raise_for_status.return_value = None
    return antwort


ZUGANG = bruecke.Zugangsdaten(
    connector_url="https://connector.beispiel.de/geheim123/mcp",
    pc_token="t-geheim",
)


class BasisUrlTest(unittest.TestCase):

    def test_mcp_wird_abgeschnitten(self):
        lokal, oeffentlich = bruecke._basis_urls(ZUGANG.connector_url)
        self.assertEqual(lokal, "http://localhost:55557/geheim123")
        self.assertEqual(oeffentlich, "https://connector.beispiel.de/geheim123")

    def test_ohne_mcp_bleibt_unveraendert(self):
        lokal, oeffentlich = bruecke._basis_urls("https://x.de/pfad")
        self.assertEqual(lokal, "http://localhost:55557/pfad")
        self.assertEqual(oeffentlich, "https://x.de/pfad")


class ZugangsdatenTest(unittest.TestCase):

    def test_fehlende_datei_ergibt_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "fehlt.txt"
            with mock.patch.object(bruecke, "BRUECKE_ZUGANG_DATEI", pfad):
                self.assertIsNone(bruecke.zugangsdaten_lesen())

    def test_vollstaendige_datei_wird_gelesen(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "zugang.txt"
            pfad.write_text("connector_url=https://x.de/geheim\npc_token=abc123\n",
                             encoding="utf-8")
            with mock.patch.object(bruecke, "BRUECKE_ZUGANG_DATEI", pfad):
                zugang = bruecke.zugangsdaten_lesen()
            self.assertEqual(zugang.connector_url, "https://x.de/geheim")
            self.assertEqual(zugang.pc_token, "abc123")

    def test_unvollstaendige_datei_ergibt_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "zugang.txt"
            pfad.write_text("connector_url=https://x.de/geheim\n", encoding="utf-8")
            with mock.patch.object(bruecke, "BRUECKE_ZUGANG_DATEI", pfad):
                self.assertIsNone(bruecke.zugangsdaten_lesen())


class AnfrageTest(unittest.TestCase):
    """Lokal bevorzugt, Fallback auf öffentlich bei jedem Fehler."""

    def test_lokal_erfolgreich_oeffentlich_wird_nicht_versucht(self):
        server = SchonServer(
            lokal=lambda *a, **k: _antwort(200, {"auftrag": {"nummer": 1, "text": "x"}})
        )
        with mock.patch.object(bruecke.requests, "request", server):
            auftrag = bruecke.abholen(ZUGANG)
        self.assertEqual(auftrag, {"nummer": 1, "text": "x"})
        self.assertEqual(len(server.aufrufe), 1)
        self.assertTrue(server.aufrufe[0][1].startswith(bruecke.LOKALE_BASIS))

    def test_lokal_scheitert_oeffentlich_greift(self):
        server = SchonServer(
            oeffentlich=lambda *a, **k: _antwort(200, {"auftrag": {"nummer": 2, "text": "y"}})
        )
        with mock.patch.object(bruecke.requests, "request", server):
            auftrag = bruecke.abholen(ZUGANG)
        self.assertEqual(auftrag, {"nummer": 2, "text": "y"})
        self.assertEqual(len(server.aufrufe), 2)

    def test_beide_scheitern_wirft_bruecken_fehler(self):
        server = SchonServer()
        with mock.patch.object(bruecke.requests, "request", server):
            with self.assertRaises(bruecke.BrueckenFehler):
                bruecke.abholen(ZUGANG)

    def test_kein_auftrag_wartet(self):
        server = SchonServer(lokal=lambda *a, **k: _antwort(204))
        with mock.patch.object(bruecke.requests, "request", server):
            self.assertIsNone(bruecke.abholen(ZUGANG))

    def test_auftrag_none_gilt_als_kein_auftrag(self):
        """Die tatsaechliche Antwort des Servers (server.py, cwb_abholen),
        wenn die Warteschlange leer ist: {"auftrag": None}, nicht 204."""
        server = SchonServer(lokal=lambda *a, **k: _antwort(200, {"auftrag": None}))
        with mock.patch.object(bruecke.requests, "request", server):
            self.assertIsNone(bruecke.abholen(ZUGANG))

    def test_antwort_ohne_text_feld_gilt_als_kein_auftrag(self):
        server = SchonServer(lokal=lambda *a, **k: _antwort(200, {"auftrag": {}}))
        with mock.patch.object(bruecke.requests, "request", server):
            self.assertIsNone(bruecke.abholen(ZUGANG))

    def test_antwort_ohne_auftragsfeld_gilt_als_kein_auftrag(self):
        server = SchonServer(lokal=lambda *a, **k: _antwort(200, {}))
        with mock.patch.object(bruecke.requests, "request", server):
            self.assertIsNone(bruecke.abholen(ZUGANG))

    def test_quittieren_sendet_auftrag_nummer(self):
        gesehen = {}

        def lokal(methode, url, headers=None, **kwargs):
            gesehen["methode"] = methode
            gesehen["url"] = url
            gesehen["json"] = kwargs.get("json")
            return _antwort(200)

        server = SchonServer(lokal=lokal)
        with mock.patch.object(bruecke.requests, "request", server):
            bruecke.quittieren(ZUGANG, 11)
        self.assertEqual(gesehen["methode"], "POST")
        self.assertTrue(gesehen["url"].endswith("/quittung"))
        self.assertEqual(gesehen["json"], {"auftrag_nummer": 11})

    def test_bericht_hochladen_sendet_pc_token_header(self):
        gesehen = {}

        def lokal(methode, url, headers=None, **kwargs):
            gesehen["methode"] = methode
            gesehen["headers"] = headers
            gesehen["json"] = kwargs.get("json")
            return _antwort(200)

        server = SchonServer(lokal=lokal)
        with mock.patch.object(bruecke.requests, "request", server):
            bruecke.bericht_hochladen(ZUGANG, 7, "Fertig.")
        self.assertEqual(gesehen["methode"], "POST")
        self.assertEqual(gesehen["headers"]["X-PC-Token"], ZUGANG.pc_token)
        self.assertEqual(gesehen["json"], {"auftrag_nummer": 7, "text": "Fertig."})


class EinenDurchlaufTest(unittest.TestCase):
    """`BrueckenFaden._einen_durchlauf` ohne Qt-Ereignisschleife: direkt als
    gewöhnliche Methode auf einer nicht gestarteten Instanz aufgerufen."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._eingang = Path(self._tmp.name) / "eingang"
        self._patch_eingang = mock.patch.object(eingangsordner, "EINGANG_ORDNER", self._eingang)
        self._patch_eingang.start()
        self.addCleanup(self._patch_eingang.stop)
        self._patch_bruecke_eingang = mock.patch.object(bruecke.eingangsordner, "EINGANG_ORDNER",
                                                          self._eingang)
        self._patch_bruecke_eingang.start()
        self.addCleanup(self._patch_bruecke_eingang.stop)
        self._zugang_datei = Path(self._tmp.name) / "zugang.txt"
        self._zugang_datei.write_text(
            "connector_url=https://x.de/geheim\npc_token=abc\n", encoding="utf-8"
        )
        self._patch_zugang = mock.patch.object(bruecke, "BRUECKE_ZUGANG_DATEI", self._zugang_datei)
        self._patch_zugang.start()
        self.addCleanup(self._patch_zugang.stop)
        self.faden = bruecke.BrueckenFaden(markierung_erkennen)

    def _dateien(self) -> list[dict]:
        if not self._eingang.is_dir():
            return []
        return [json.loads(p.read_text(encoding="utf-8"))
                for p in self._eingang.glob("*.json")]

    def test_code_auftrag_landet_im_eingangsordner(self):
        quittiert = {}

        def lokal(methode, url, headers=None, json=None, **kwargs):
            if url.endswith("/abholen"):
                return _antwort(
                    200, {"auftrag": {"nummer": 5, "projekt": "CWB", "text": "#CODE#\nTu etwas."}}
                )
            quittiert["json"] = json
            return _antwort(200)

        server = SchonServer(lokal=lokal)
        with mock.patch.object(bruecke.requests, "request", server):
            self.faden._einen_durchlauf()
        dateien = self._dateien()
        self.assertEqual(len(dateien), 1)
        self.assertEqual(dateien[0]["quelle"], "bruecke")
        self.assertEqual(dateien[0]["projekt"], "CWB")
        self.assertEqual(dateien[0]["auftrag_nummer"], 5)
        self.assertIn("#CODE#", dateien[0]["text"])
        self.assertEqual(quittiert["json"], {"auftrag_nummer": 5})
        self.assertIn(5, self.faden._abgelegt)

    def test_admin_auftrag_wird_abgelehnt_und_nicht_abgelegt(self):
        hochgeladen = {}
        quittiert = {}

        def lokal(methode, url, headers=None, json=None, **kwargs):
            if url.endswith("/abholen"):
                return _antwort(200, {"auftrag": {"nummer": 9, "text": "#ADMIN#\nGet-Service"}})
            if url.endswith("/quittung"):
                quittiert["json"] = json
                return _antwort(200)
            hochgeladen["json"] = json
            return _antwort(200)

        server = SchonServer(lokal=lokal)
        with mock.patch.object(bruecke.requests, "request", server):
            self.faden._einen_durchlauf()
        self.assertEqual(self._dateien(), [])
        self.assertEqual(hochgeladen["json"]["auftrag_nummer"], 9)
        self.assertIn("ADMIN", hochgeladen["json"]["text"])
        self.assertEqual(quittiert["json"], {"auftrag_nummer": 9})

    def test_kein_auftrag_legt_nichts_ab(self):
        server = SchonServer(lokal=lambda *a, **k: _antwort(200, {"auftrag": None}))
        with mock.patch.object(bruecke.requests, "request", server):
            self.faden._einen_durchlauf()
        self.assertEqual(self._dateien(), [])

    def test_erneute_auslieferung_wird_nicht_doppelt_abgelegt(self):
        """Kommt derselbe Auftrag ein zweites Mal (Quittung ging beim ersten
        Mal verloren), landet er nicht noch einmal im Eingangsordner - nur
        die Quittung wird erneut versucht."""
        quittungen = []

        def lokal(methode, url, headers=None, json=None, **kwargs):
            if url.endswith("/abholen"):
                return _antwort(
                    200, {"auftrag": {"nummer": 5, "projekt": "CWB", "text": "#CODE#\nTu etwas."}}
                )
            if url.endswith("/quittung"):
                quittungen.append(json)
            return _antwort(200)

        server = SchonServer(lokal=lokal)
        with mock.patch.object(bruecke.requests, "request", server):
            self.faden._einen_durchlauf()
            self.faden._einen_durchlauf()
        self.assertEqual(len(self._dateien()), 1)
        self.assertEqual(quittungen, [{"auftrag_nummer": 5}, {"auftrag_nummer": 5}])

    def test_quittung_scheitert_bleibt_folgenlos(self):
        """Ein Netzfehler bei der Quittung lässt den Auftrag trotzdem
        abgelegt - der Server liefert ihn notfalls erneut aus."""
        def lokal(methode, url, headers=None, json=None, **kwargs):
            if url.endswith("/abholen"):
                return _antwort(
                    200, {"auftrag": {"nummer": 5, "projekt": "CWB", "text": "#CODE#\nTu etwas."}}
                )
            raise requests.ConnectionError("Quittung nicht erreichbar (Test)")

        server = SchonServer(lokal=lokal)
        with mock.patch.object(bruecke.requests, "request", server):
            self.faden._einen_durchlauf()
        self.assertEqual(len(self._dateien()), 1)

    def test_netzfehler_wirft_bruecken_fehler(self):
        server = SchonServer()
        with mock.patch.object(bruecke.requests, "request", server):
            with self.assertRaises(bruecke.BrueckenFehler):
                self.faden._einen_durchlauf()

    def test_fehlende_zugangsdaten_zaehlen_als_fehler(self):
        self._zugang_datei.unlink()
        with self.assertRaises(bruecke.BrueckenFehler):
            self.faden._einen_durchlauf()


class AusfallMeldungTest(unittest.TestCase):
    """`_fehler_merken`/`nicht_erreichbar` ohne echten Thread-Lauf: die
    Zeitmessung wird über `time.monotonic` nachgestellt."""

    def setUp(self):
        self.faden = bruecke.BrueckenFaden(markierung_erkennen)
        self.gemeldet = []
        self.faden.nicht_erreichbar.connect(lambda: self.gemeldet.append(True))

    def test_keine_meldung_vor_der_schwelle(self):
        with mock.patch.object(bruecke.time, "monotonic",
                                return_value=self.faden._letzter_erfolg + 10):
            self.faden._fehler_merken()
        self.assertEqual(self.gemeldet, [])

    def test_meldung_nach_fuenf_minuten(self):
        with mock.patch.object(
            bruecke.time, "monotonic",
            return_value=self.faden._letzter_erfolg + bruecke.AUSFALL_SCHWELLE_SEKUNDEN + 1,
        ):
            self.faden._fehler_merken()
        self.assertEqual(len(self.gemeldet), 1)

    def test_meldung_nur_einmal_pro_ausfallphase(self):
        with mock.patch.object(
            bruecke.time, "monotonic",
            return_value=self.faden._letzter_erfolg + bruecke.AUSFALL_SCHWELLE_SEKUNDEN + 1,
        ):
            self.faden._fehler_merken()
            self.faden._fehler_merken()
        self.assertEqual(len(self.gemeldet), 1)


if __name__ == "__main__":
    unittest.main()
