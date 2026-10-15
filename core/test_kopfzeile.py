"""
CWB - Code Workbench
Unit-Tests fuer Block 81 (core/kopfzeile.py): die reinen Hilfsfunktionen
rund um die Farbstufe und Einordnung der Such-Effizienz-Anzeige. Laufen
ohne Qt-Fenster, wie die uebrigen Tests dieses Ordners.

Aufruf: python -m unittest core.test_kopfzeile -v
        (oder, aus dem Ordner core/: python test_kopfzeile.py -v)
"""

import unittest

try:
    from . import kopfzeile
except ImportError:
    import kopfzeile


class SuchEffizienzStufeTest(unittest.TestCase):
    """core/kopfzeile.py: such_effizienz_stufe() - ordnet die Prozentzahl
    einer von vier Farbstufen zu (stil.qss, Eigenschaft "effizienzstufe")."""

    def test_kein_wert_ergibt_keine_stufe(self):
        self.assertEqual(kopfzeile.such_effizienz_stufe(None), "")

    def test_unter_70_ist_schlecht(self):
        self.assertEqual(kopfzeile.such_effizienz_stufe(0), "schlecht")
        self.assertEqual(kopfzeile.such_effizienz_stufe(69), "schlecht")

    def test_70_bis_99_ist_mittel(self):
        self.assertEqual(kopfzeile.such_effizienz_stufe(70), "mittel")
        self.assertEqual(kopfzeile.such_effizienz_stufe(99), "mittel")

    def test_100_bis_149_ist_gut(self):
        self.assertEqual(kopfzeile.such_effizienz_stufe(100), "gut")
        self.assertEqual(kopfzeile.such_effizienz_stufe(149), "gut")

    def test_ab_150_ist_sehr_gut(self):
        self.assertEqual(kopfzeile.such_effizienz_stufe(150), "sehr_gut")
        self.assertEqual(kopfzeile.such_effizienz_stufe(999), "sehr_gut")


class SuchEffizienzEinordnungTest(unittest.TestCase):
    """core/kopfzeile.py: such_effizienz_einordnung() - der barrierefreie
    Wortlaut "besser/schlechter/wie üblich" zur Zahl."""

    def test_kein_wert_ergibt_leeren_text(self):
        self.assertEqual(kopfzeile.such_effizienz_einordnung(None), "")

    def test_genau_100_ist_wie_ueblich(self):
        self.assertEqual(kopfzeile.such_effizienz_einordnung(100), "wie üblich")

    def test_ueber_100_ist_besser(self):
        self.assertEqual(kopfzeile.such_effizienz_einordnung(150), "besser als üblich")

    def test_unter_100_ist_schlechter(self):
        self.assertEqual(kopfzeile.such_effizienz_einordnung(49), "schlechter als üblich")


class ZeilenFlussTest(unittest.TestCase):
    """core/kopfzeile.py: ZeilenFluss - reine Anordnungslogik (_anordnen),
    ohne echtes Qt-Fenster: nachgebildete Eintraege mit fester sizeHint und
    isHidden() statt echter QWidgetItem/QWidget-Objekte."""

    class _FalscherEintrag:
        def __init__(self, breite, hoehe=20, versteckt=False):
            self._groesse = kopfzeile.QSize(breite, hoehe)
            self._versteckt = versteckt

        def sizeHint(self):
            return self._groesse

        def minimumSize(self):
            return self._groesse

        def widget(self):
            return self

        def isHidden(self):
            return self._versteckt

        def setGeometry(self, rect):
            self.geometrie = rect

    def _fluss(self, breiten, abstand=6):
        fluss = kopfzeile.ZeilenFluss(abstand=abstand)
        eintraege = [self._FalscherEintrag(b) for b in breiten]
        for eintrag in eintraege:
            fluss.addItem(eintrag)
        return fluss, eintraege

    def test_passt_alles_in_eine_zeile_bleibt_eine_zeile_hoch(self):
        fluss, _ = self._fluss([100, 100, 100])
        hoehe = fluss.heightForWidth(1000)
        self.assertEqual(hoehe, 20)

    def test_zu_schmal_bricht_in_zweite_zeile_um(self):
        # Je 60 Pixel breit: zwei passen nebeneinander in 150 Pixel (126
        # inklusive Abstand), der dritte muss in eine zweite Zeile.
        fluss, _ = self._fluss([60, 60, 60])
        hoehe = fluss.heightForWidth(150)
        self.assertEqual(hoehe, 2 * 20 + fluss.spacing())

    def test_versteckter_eintrag_zaehlt_nicht_mit(self):
        fluss = kopfzeile.ZeilenFluss(abstand=6)
        sichtbar = self._FalscherEintrag(100)
        versteckt = self._FalscherEintrag(2000, versteckt=True)
        fluss.addItem(sichtbar)
        fluss.addItem(versteckt)
        # Ohne den versteckten Eintrag passt eine einzige schmale Zeile -
        # mit ihm (2000 Pixel breit) muesste sie umbrechen oder ueberlaufen.
        self.assertEqual(fluss.heightForWidth(200), 20)

    def test_jede_zeile_mindestens_so_hoch_wie_ihr_hoechster_eintrag(self):
        fluss, _ = self._fluss([60, 60])
        fluss._eintraege.append(self._FalscherEintrag(60, hoehe=40))
        hoehe = fluss.heightForWidth(150)
        # Erste Zeile (zwei 60er-Eintraege nebeneinander, hoehe 20) plus
        # zweite Zeile mit dem dritten, 40 Pixel hohen Eintrag.
        self.assertEqual(hoehe, 20 + fluss.spacing() + 40)


if __name__ == "__main__":
    unittest.main()
