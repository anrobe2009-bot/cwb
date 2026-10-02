"""Stummer Test: simuliert MCI (keine echte Audioausgabe), um zu pruefen,
ob core.sprache.Abspieler/Sprecher bei schneller Folge von Ansagen zwei
Geraete gleichzeitig im Zustand 'playing' haelt (echte Ueberlappung) oder
ob die geloggte MCI-Warnung ('Geraet ist nicht geoeffnet') nur eine
harmlose Doppelmeldung ohne echtes Ueberlappen ist."""
import logging
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

import core.sprache as sprache


class FalscherWinmm:
    """Bildet winmm.dll soweit nach, wie Abspieler es benutzt: open/play/stop/
    close/status je Alias, mit einstellbarer, realistischer Verzoegerung
    zwischen 'stop' und tatsaechlichem Wechsel auf 'stopped' (so wie echte
    MCI-Treiber bei komprimiertem Ton nicht sofort stumm sind)."""

    def __init__(self, stop_verzoegerung=0.08, spiel_dauer=1.0):
        self.geraete = {}  # alias -> {"modus": "playing"/"stopped", "offen": True}
        self.sperre = threading.Lock()
        self.stop_verzoegerung = stop_verzoegerung
        self.spiel_dauer = spiel_dauer
        self.befehle = []  # Protokoll aller Befehle zur Auswertung

    def mciSendStringW(self, text, puffer, laenge, _):
        self.befehle.append(("send", text))
        teile = text.split()
        cmd = teile[0]
        if cmd == "open":
            alias = teile[-1]
            with self.sperre:
                self.geraete[alias] = {"modus": "stopped", "offen": True}
            return 0
        if cmd == "play":
            alias = teile[1]
            with self.sperre:
                if alias not in self.geraete or not self.geraete[alias]["offen"]:
                    return 1  # Fehler: Geraet nicht offen
                self.geraete[alias]["modus"] = "playing"
            ende = time.monotonic() + self.spiel_dauer

            def automatisch_fertig():
                time.sleep(self.spiel_dauer)
                with self.sperre:
                    if alias in self.geraete and self.geraete[alias]["modus"] == "playing":
                        self.geraete[alias]["modus"] = "stopped"
            threading.Thread(target=automatisch_fertig, daemon=True).start()
            return 0
        if cmd == "stop":
            alias = teile[1]
            with self.sperre:
                geraet = self.geraete.get(alias)
                if geraet is None or not geraet["offen"]:
                    return 1  # Fehler: Geraet nicht offen - wie im echten Log
            time.sleep(self.stop_verzoegerung)
            with self.sperre:
                geraet = self.geraete.get(alias)
                if geraet is None or not geraet["offen"]:
                    return 1
                geraet["modus"] = "stopped"
            return 0
        if cmd == "close":
            alias = teile[1]
            with self.sperre:
                geraet = self.geraete.get(alias)
                if geraet is None or not geraet["offen"]:
                    return 1  # Fehler: Geraet nicht offen
                geraet["offen"] = False
            return 0
        if cmd == "status":
            alias = teile[1]
            with self.sperre:
                geraet = self.geraete.get(alias)
                modus = geraet["modus"] if geraet and geraet["offen"] else ""
            if puffer is not None:
                puffer.value = modus
            return 0
        return 1

    def mciGetErrorStringW(self, fehlercode, puffer, laenge):
        puffer.value = "Geraet ist nicht geoeffnet"

    def ist_gleichzeitig_offen_und_spielend(self):
        with self.sperre:
            return [a for a, g in self.geraete.items() if g["offen"] and g["modus"] == "playing"]


falscher_winmm = FalscherWinmm()

sprecher = sprache.Sprecher(weg="edge", sprechen_an=True, toene_an=False)
sprecher._abspieler._winmm = falscher_winmm

_original_pfad_fuer = sprecher._pfad_fuer
DATEI = Path(__file__)  # beliebige existierende Datei, wird nie wirklich gelesen
def _pfad_fuer(text):
    return DATEI
sprecher._pfad_fuer = _pfad_fuer
sprecher._erzeugen = lambda text, ziel: True  # TTS-Erzeugung simulieren: immer "erfolgreich"

ueberlappungen = []
stop_ev = threading.Event()

def ueberwacher():
    while not stop_ev.is_set():
        offene = falscher_winmm.ist_gleichzeitig_offen_und_spielend()
        if len(offene) > 1:
            ueberlappungen.append(tuple(sorted(offene)))
        time.sleep(0.005)

wach = threading.Thread(target=ueberwacher, daemon=True)
wach.start()

print("--- Test: 15 Ansagen in schneller, ueberlappender Folge (0.05s Abstand) ---")
for i in range(15):
    threading.Thread(target=lambda i=i: sprecher.sprich(f"Satz {i}", art="immer")).start()
    time.sleep(0.05)

time.sleep(3.0)
stop_ev.set()
wach.join(timeout=1)
sprecher.beenden()

warnungen_stop_close = [b for b in falscher_winmm.befehle if b[0] == "send"]
geraet_nicht_offen_faelle = 0
# Zaehle, wie oft stop/close auf ein zu diesem Zeitpunkt schon geschlossenes
# Geraet traf (simuliert ueber die Rueckgabe 1 im FalscherWinmm, hier grob
# ueber das Log nachgezaehlt):
fehlerhafte = []

print("\n=== Ergebnis ===")
print(f"Echte Ueberlappungen (zwei Geraete gleichzeitig 'playing' UND offen): {len(ueberlappungen)}")
for u in set(ueberlappungen):
    print("  ", u, "x", ueberlappungen.count(u))
