"""
CWB - Code Workbench
Unit-Tests fuer Block 649/662: Modellwahl pro Auftrag ueber die optionale
Zeile "#MODELL# name" direkt nach der Markierung ODER, bei einem Auftrag ganz
ohne Markierung, als allererste Zeile (core/fenster.py,
modell_zeile_erkennen/Werkbank._modell_zeile_verarbeiten), die Zuordnung der
Namen (core/modelle.py, modellname_aufloesen), die Geltungsdauer von genau
einem Auftrag mit Ruecksprung auf die feste Voreinstellung Sonnet
(Werkbank._auftrag_starten) sowie den Rueckfall auf das vorherige Modell,
wenn der Wechsel selbst scheitert (core/sitzung.py, Sitzung.modell_wechseln).

Laeuft ohne Qt, ohne echte SDK-Verbindung und ohne Netz: core/fenster.py und
core/sitzung.py werden nur fuer ihre reinen Funktionen/unbound Methoden
importiert, mit nachgebildeten Platzhaltern statt einer echten Werkbank
bzw. Sitzung (siehe core/test_absenden.py und core/test_hintergrund.py fuer
dasselbe Muster).

Aufruf: python -m unittest core.test_modell_zeile -v
        (oder, aus dem Ordner core/: python test_modell_zeile.py -v)
        oder mit pytest: pytest core/test_modell_zeile.py -q
"""

import unittest
from types import SimpleNamespace
from unittest import mock

try:
    from . import modelle, sitzung
    from .fenster import MARKIERUNG_CODE, Werkbank, modell_zeile_erkennen
except ImportError:
    import modelle
    import sitzung
    from fenster import MARKIERUNG_CODE, Werkbank, modell_zeile_erkennen


class ModellZeileErkennenTest(unittest.TestCase):
    """core/fenster.py: modell_zeile_erkennen() - erkennt/entfernt '#MODELL#
    name' nur, wenn es die allererste Zeile von `inhalt` ist."""

    def test_ohne_zeile_bleibt_unveraendert(self):
        inhalt = "Tu etwas Normales."
        bereinigt, name = modell_zeile_erkennen(inhalt)
        self.assertEqual(bereinigt, inhalt)
        self.assertIsNone(name)

    def test_zeile_erkannt_und_entfernt(self):
        inhalt = "#MODELL# opus\nTu etwas."
        bereinigt, name = modell_zeile_erkennen(inhalt)
        self.assertEqual(bereinigt, "Tu etwas.")
        self.assertEqual(name, "opus")

    def test_gross_klein_und_leerraum_egal(self):
        inhalt = "  #modell#   Sonnet-5.5  \nTu etwas."
        bereinigt, name = modell_zeile_erkennen(inhalt)
        self.assertEqual(name, "Sonnet-5.5")
        self.assertEqual(bereinigt, "Tu etwas.")

    def test_nur_die_zeile_ohne_weiteren_text(self):
        bereinigt, name = modell_zeile_erkennen("#MODELL# haiku")
        self.assertEqual(bereinigt, "")
        self.assertEqual(name, "haiku")

    def test_nicht_an_zweiter_stelle_bleibt_normaler_text(self):
        inhalt = "Tu etwas.\n#MODELL# opus\nWeiter."
        bereinigt, name = modell_zeile_erkennen(inhalt)
        self.assertIsNone(name)
        self.assertEqual(bereinigt, inhalt)


class ModellnameAufloesenTest(unittest.TestCase):
    """core/modelle.py: modellname_aufloesen() - Zuordnung der in der
    '#MODELL#'-Zeile erlaubten Namen auf das CLI-Kuerzel bzw. den vollen
    Namen aus der Modellliste."""

    def test_opus_familie(self):
        for name in ("opus", "Opus", " opus-5 ", "OPUS-5.5"):
            self.assertEqual(modelle.modellname_aufloesen(name), "opus")

    def test_sonnet_familie(self):
        for name in ("sonnet", "sonnet-5", "Sonnet-5.5"):
            self.assertEqual(modelle.modellname_aufloesen(name), "sonnet")

    def test_haiku_familie(self):
        for name in ("haiku", "HAIKU-5", "haiku-5.5"):
            self.assertEqual(modelle.modellname_aufloesen(name), "haiku")

    def test_fable_familie_aus_der_rueckfallliste(self):
        for name in ("fable", "Fable-5", "fable-5.1"):
            self.assertEqual(modelle.modellname_aufloesen(name), "claude-fable-5-1[1m]")

    def test_fable_aus_echter_verbindungsliste(self):
        eintraege = [{"wert": "claude-fable-5-1", "voll": "claude-fable-5-1"}]
        self.assertEqual(modelle.modellname_aufloesen("fable", eintraege), "claude-fable-5-1")

    def test_volle_modell_id_direkt_akzeptiert(self):
        self.assertEqual(modelle.modellname_aufloesen("claude-sonnet-5"), "claude-sonnet-5")

    def test_unbekannter_name_ergibt_none(self):
        self.assertIsNone(modelle.modellname_aufloesen("gpt-4"))

    def test_leerer_name_ergibt_none(self):
        self.assertIsNone(modelle.modellname_aufloesen(""))
        self.assertIsNone(modelle.modellname_aufloesen(None))


class _ModellZeileTraeger:
    """Minimaler Platzhalter fuer Werkbank: traegt nur die echte Methode
    _modell_zeile_verarbeiten samt den zwei Attributen, die sie braucht."""

    _modell_zeile_verarbeiten = Werkbank._modell_zeile_verarbeiten

    def __init__(self, modell: str = "sonnet"):
        self.modell = modell
        self.modelle = list(modelle.MODELLE_RUECKFALL)


class ModellZeileVerarbeitenTest(unittest.TestCase):
    """core/fenster.py: Werkbank._modell_zeile_verarbeiten() - entscheidet,
    ob und auf welches Modell ein Auftrag umschalten soll."""

    def test_ohne_markierung_wird_wie_code_behandelt(self):
        """Block 662: ein Auftrag ganz ohne Markierung (Art "") geht genauso
        an Claude Code wie ein '#CODE#'-Auftrag - die Zeile muss darum auch
        dort erkannt und ein Wechsel vorgeschlagen werden. Vor Block 662 gab
        die frühere Bedingung `if not art` hier sofort unveraendert zurueck
        (Ursache des Fehlschlags bei Bruecken-Auftraegen ohne '#CODE#',
        Block 661: Art "ohne Markierung" im Log)."""
        traeger = _ModellZeileTraeger(modell="sonnet")
        inhalt = "#MODELL# opus\nTu etwas."
        bereinigt, sticky, hinweis = traeger._modell_zeile_verarbeiten("", inhalt)
        self.assertEqual(bereinigt, "Tu etwas.")
        self.assertEqual(sticky, "opus")
        self.assertEqual(hinweis, "")

    def test_run_zeile_entfernt_aber_kein_wechsel(self):
        traeger = _ModellZeileTraeger(modell="sonnet")
        bereinigt, sticky, hinweis = traeger._modell_zeile_verarbeiten(
            "run", "#MODELL# opus\nGet-Service")
        self.assertEqual(bereinigt, "Get-Service")
        self.assertIsNone(sticky)
        self.assertEqual(hinweis, "")

    def test_admin_zeile_entfernt_aber_kein_wechsel(self):
        traeger = _ModellZeileTraeger(modell="sonnet")
        bereinigt, sticky, hinweis = traeger._modell_zeile_verarbeiten(
            "admin", "#MODELL# opus\nGet-Service")
        self.assertEqual(bereinigt, "Get-Service")
        self.assertIsNone(sticky)

    def test_bild_zeile_entfernt_aber_kein_wechsel(self):
        traeger = _ModellZeileTraeger(modell="sonnet")
        bereinigt, sticky, hinweis = traeger._modell_zeile_verarbeiten(
            "bild", "#MODELL# opus")
        self.assertEqual(bereinigt, "")
        self.assertIsNone(sticky)

    def test_code_unbekannter_name_ergibt_hinweis(self):
        traeger = _ModellZeileTraeger(modell="sonnet")
        bereinigt, sticky, hinweis = traeger._modell_zeile_verarbeiten(
            "code", "#MODELL# gpt4\nTu etwas.")
        self.assertEqual(bereinigt, "Tu etwas.")
        self.assertIsNone(sticky)
        self.assertIn("gpt4", hinweis)
        self.assertIn("unbekannt", hinweis)

    def test_code_gleiches_modell_kein_wechsel(self):
        traeger = _ModellZeileTraeger(modell="opus")
        bereinigt, sticky, hinweis = traeger._modell_zeile_verarbeiten(
            "code", "#MODELL# opus-5.5\nTu etwas.")
        self.assertEqual(bereinigt, "Tu etwas.")
        self.assertIsNone(sticky)
        self.assertEqual(hinweis, "")

    def test_code_anderes_modell_wird_vorgeschlagen(self):
        traeger = _ModellZeileTraeger(modell="sonnet")
        bereinigt, sticky, hinweis = traeger._modell_zeile_verarbeiten(
            "code", "#MODELL# opus\nTu etwas.")
        self.assertEqual(bereinigt, "Tu etwas.")
        self.assertEqual(sticky, "opus")
        self.assertEqual(hinweis, "")

    def test_ohne_modell_zeile_bleibt_alles_leer(self):
        traeger = _ModellZeileTraeger(modell="sonnet")
        bereinigt, sticky, hinweis = traeger._modell_zeile_verarbeiten(
            "code", "Tu etwas ganz Normales.")
        self.assertEqual(bereinigt, "Tu etwas ganz Normales.")
        self.assertIsNone(sticky)
        self.assertEqual(hinweis, "")


class _AbsendenTraeger:
    """Wie core/test_absenden.py: _AbsendenTraeger, nur zusaetzlich mit
    self.modell/self.modelle und der echten _modell_zeile_verarbeiten, um
    den vollen Weg bis zu den an _auftrag_starten uebergebenen Kwargs zu
    pruefen."""

    _absenden = Werkbank._absenden
    _block_verarbeiten = Werkbank._block_verarbeiten
    _modell_zeile_verarbeiten = Werkbank._modell_zeile_verarbeiten

    def __init__(self, text: str, modell: str = "sonnet"):
        self.eingabe = mock.Mock()
        self.eingabe.toPlainText.return_value = text
        self.projekt = SimpleNamespace(name="CWB_TestModellzeile")
        self.sprecher = mock.Mock()
        self.bilder: list = []
        self.modell = modell
        self.modelle = list(modelle.MODELLE_RUECKFALL)
        self._pending_block = None
        self._holt_vorgemerkten = True
        self._sparmodus_aktiv = False
        self._sparmodus_wartend: list = []
        self._auftrag_laeuft = False
        self._kontingent_info = None
        self._warteschlange: list = []
        self._verlauf_anhaengen = mock.Mock()
        self._status_zeigen = mock.Mock()
        self._taetigkeit_zeigen = mock.Mock()
        self._auftrag_starten = mock.Mock()


class AbsendenMitModellZeileTest(unittest.TestCase):
    """Block 649: der volle Weg vom Eingabefeld bis zu den Kwargs, mit
    denen _absenden anschliessend _auftrag_starten aufruft."""

    def test_ohne_modell_zeile_kein_sticky_wechsel(self):
        rohtext = f"{MARKIERUNG_CODE}\nTu etwas Normales."
        traeger = _AbsendenTraeger(rohtext, modell="sonnet")

        traeger._absenden()

        traeger._auftrag_starten.assert_called_once()
        _args, kwargs = traeger._auftrag_starten.call_args
        self.assertIsNone(kwargs["modell_sticky"])
        self.assertEqual(kwargs["modell_hinweis"], "")

    def test_modell_zeile_direkt_nach_der_markierung_wird_weitergereicht(self):
        rohtext = f"{MARKIERUNG_CODE}\n#MODELL# opus\nTu etwas."
        traeger = _AbsendenTraeger(rohtext, modell="sonnet")

        traeger._absenden()

        traeger._auftrag_starten.assert_called_once()
        _args, kwargs = traeger._auftrag_starten.call_args
        self.assertEqual(kwargs["modell_sticky"], "opus")
        text_uebergeben = traeger._auftrag_starten.call_args[0][0]
        self.assertNotIn("#MODELL#", text_uebergeben)
        self.assertIn("Tu etwas.", text_uebergeben)

    def test_modell_zeile_ohne_markierung_wird_weitergereicht(self):
        """Block 662: ein Auftrag ganz ohne Markierung (kein '#CODE#' davor)
        muss die Zeile genauso erkennen - das war die bestaetigte Ursache von
        Block 661 (Brueckenauftrag ohne '#CODE#', Art "ohne Markierung" im
        Log, '#MODELL# sonnet' blieb unveraendert im Auftragstext stehen)."""
        rohtext = "#MODELL# opus\nTu etwas."
        traeger = _AbsendenTraeger(rohtext, modell="sonnet")

        traeger._absenden()

        traeger._auftrag_starten.assert_called_once()
        _args, kwargs = traeger._auftrag_starten.call_args
        self.assertEqual(kwargs["modell_sticky"], "opus")
        text_uebergeben = traeger._auftrag_starten.call_args[0][0]
        self.assertNotIn("#MODELL#", text_uebergeben)
        self.assertIn("Tu etwas.", text_uebergeben)

    def test_unbekannter_name_landet_als_hinweis_ohne_wechsel(self):
        rohtext = f"{MARKIERUNG_CODE}\n#MODELL# gpt4\nTu etwas."
        traeger = _AbsendenTraeger(rohtext, modell="sonnet")

        traeger._absenden()

        _args, kwargs = traeger._auftrag_starten.call_args
        self.assertIsNone(kwargs["modell_sticky"])
        self.assertIn("gpt4", kwargs["modell_hinweis"])

    def test_zeile_nicht_an_zweiter_stelle_bleibt_auftragstext(self):
        rohtext = f"{MARKIERUNG_CODE}\nTu etwas.\n#MODELL# opus\nWeiter."
        traeger = _AbsendenTraeger(rohtext, modell="sonnet")

        traeger._absenden()

        _args, kwargs = traeger._auftrag_starten.call_args
        self.assertIsNone(kwargs["modell_sticky"])
        text_uebergeben = traeger._auftrag_starten.call_args[0][0]
        self.assertIn("#MODELL# opus", text_uebergeben)


class ModellWechselnFallbackTest(unittest.IsolatedAsyncioTestCase):
    """core/sitzung.py: Sitzung.modell_wechseln() - Block 649, Punkt 7:
    scheitert der Verbindungsaufbau mit dem neuen Modell, faellt die
    Sitzung auf das vorherige zurueck, statt ohne Verbindung zu bleiben,
    meldet den Fehlschlag aber trotzdem weiter."""

    async def test_erfolgreicher_wechsel(self):
        verbunden_mit = []

        class Fake:
            modell = "sonnet"
            modell_name = "claude-sonnet-5"
            klient = object()

            async def trennen(self):
                self.klient = None

            async def verbinden(self):
                verbunden_mit.append(self.modell)
                self.modell_name = f"claude-{self.modell}-5"

        fake = Fake()
        ergebnis = await sitzung.Sitzung.modell_wechseln(fake, "opus")

        self.assertEqual(fake.modell, "opus")
        self.assertEqual(verbunden_mit, ["opus"])
        self.assertEqual(ergebnis, "claude-opus-5")

    async def test_fehlschlag_faellt_auf_vorheriges_modell_zurueck(self):
        versuche = []

        class Fake:
            modell = "sonnet"
            modell_name = "claude-sonnet-5"
            klient = object()

            async def trennen(self):
                self.klient = None

            async def verbinden(self):
                versuche.append(self.modell)
                if self.modell == "opus":
                    raise RuntimeError("Verbindung abgelehnt")
                self.modell_name = f"claude-{self.modell}-5"

        fake = Fake()
        with self.assertRaises(RuntimeError):
            await sitzung.Sitzung.modell_wechseln(fake, "opus")

        self.assertEqual(fake.modell, "sonnet")
        self.assertEqual(versuche, ["opus", "sonnet"])


class _FakeFaden:
    """Zeichnet die Reihenfolge von modell_setzen()/auftrag_geben() auf, so
    wie core/faden.py sie strikt FIFO an die Sitzung weiterreicht - genug,
    um die Reihenfolge zu pruefen, ohne eine echte Sitzung zu brauchen.
    `sitzung` ist absichtlich nicht None: das laesst Werkbank._auftrag_starten
    den Zweig fuer eine bereits verbundene Sitzung nehmen."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.sitzung = object()

    def modell_setzen(self, wert: str) -> None:
        self.calls.append(("modell", wert))

    def auftrag_geben(self, text: str, bilder: list) -> None:
        self.calls.append(("auftrag", text))


class _AuftragStartenTraeger:
    """Minimaler Platzhalter fuer Werkbank: traegt die echte Methode
    _auftrag_starten samt aller Attribute, die sie anfasst."""

    _auftrag_starten = Werkbank._auftrag_starten

    def __init__(self, modell: str = "sonnet"):
        self.modell = modell
        self.modelle = list(modelle.MODELLE_RUECKFALL)
        self.sprecher = mock.Mock()
        self.faden = _FakeFaden()
        self._auftrag_laeuft = False
        self._bruecke_code_nummer = None
        self._aktueller_block_nummer = None
        self._eingang_code_datei = None
        self._laufender_modell_wunsch = None
        self._laufender_modell_grund = None
        self._laufender_modell_hinweis = ""
        self._laufender_block_nummer = None
        self._laufender_quelle = ""
        self._laufender_zeit = None
        self._modell_eigenauftrag_rest = 0
        self._wartende_auftraege: list = []
        self._statusleiste_aktualisieren = mock.Mock()
        self._ausgabe_leeren = mock.Mock()
        self._verlauf_anhaengen = mock.Mock()
        self._status_zeigen = mock.Mock()
        self._taetigkeit_zeigen = mock.Mock()
        self.letzter_auftrag = ""
        self._aktuelle_bilder: list = []
        self.letzter_verbrauch: dict = {}
        self._auftrags_beginn = None
        self.zeit_anzeige = mock.Mock()
        self._auftrags_uhr = mock.Mock()
        self.balken = mock.Mock()


class AuftragStartenModellStickyTest(unittest.TestCase):
    """Block 662: Werkbank._auftrag_starten() - eine '#MODELL#'-Zeile
    (modell_sticky) wechselt nur fuer GENAU diesen einen Auftrag und springt
    danach zurueck auf die feste Voreinstellung (self.modell, Sonnet) -
    anders als vor Block 662, wo der Wechsel dauerhaft blieb."""

    def test_sticky_wechselt_fuer_diesen_auftrag_und_springt_zurueck(self):
        traeger = _AuftragStartenTraeger(modell="sonnet")

        traeger._auftrag_starten("Tu etwas.", [], modell_sticky="opus")

        self.assertEqual(
            traeger.faden.calls,
            [("modell", "opus"), ("auftrag", "Tu etwas."), ("modell", "sonnet")],
        )
        # self.modell (die feste Voreinstellung) bleibt unberuehrt - anders
        # als der frueher dauerhafte Wechsel vor Block 662.
        self.assertEqual(traeger.modell, "sonnet")

    def test_ohne_sticky_kein_zusaetzlicher_wechsel(self):
        traeger = _AuftragStartenTraeger(modell="sonnet")

        traeger._auftrag_starten("Tu etwas Normales.", [])

        self.assertEqual(traeger.faden.calls, [("auftrag", "Tu etwas Normales.")])

    def test_sticky_bleibt_bei_fehlerhaftem_fehlschlagendem_auftrag_erhalten(self):
        """Der Ruecksprung wird VOR dem Auftrag in die Warteschlange des
        Arbeitsfadens eingereiht (core/faden.py verarbeitet "modell" und
        "auftrag" streng der Reihe nach) - er wirkt darum auch, wenn der
        Auftrag selbst scheitert oder abgebrochen wird, ohne dass
        _auftrag_starten davon je erfaehrt."""
        traeger = _AuftragStartenTraeger(modell="sonnet")

        traeger._auftrag_starten("Tu etwas Riskantes.", [], modell_sticky="haiku")

        # Der Ruecksprung steht schon in der Warteschlange, bevor der
        # Auftrag ueberhaupt verarbeitet wurde.
        self.assertEqual(traeger.faden.calls[-1], ("modell", "sonnet"))


if __name__ == "__main__":
    unittest.main()
