"""
CWB - Code Workbench
Arbeitsfaden: haelt die Sitzung, damit das Fenster nie haengt.

Die Sitzung arbeitet asynchron und kann Minuten brauchen. Liefe sie im
Fenster, waere die Oberflaeche waehrenddessen taub. Darum laeuft sie in einem
eigenen Faden und meldet sich ausschliesslich ueber Qt-Signale zurueck.

Dieses Modul kennt kein Fenster und keine Gestaltung.
"""

import asyncio
import logging
import queue
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

try:
    from .grundlagen import LOG_DATEI  # noqa: F401  (richtet das Log ein)
    from .sicherheit import Projekt, Wache
    from .sitzung import Sitzung
except ImportError:
    from grundlagen import LOG_DATEI  # noqa: F401
    from sicherheit import Projekt, Wache
    from sitzung import Sitzung

log = logging.getLogger("cwb.faden")


class SitzungsFaden(QThread):
    """Führt die asynchrone Sitzung in einem eigenen Faden."""

    # zustand, ansage, detail, pfad, taetigkeit
    ereignis_da = Signal(str, str, str, str, str)
    text_da = Signal(str)
    fertig_da = Signal(dict)
    frage_da = Signal(str)
    bereit_da = Signal()
    verbrauch_da = Signal(dict)
    # Die vom Abo wirklich waehlbaren Modelle, sobald die Verbindung steht
    modelle_da = Signal(list)

    def __init__(self, projekt: Projekt, modell: str = ""):
        super().__init__()
        self.projekt = projekt
        self.modell = modell or ""
        self.auftraege: queue.Queue = queue.Queue()
        self.sitzung: Sitzung | None = None
        self._schleife: asyncio.AbstractEventLoop | None = None
        self._antwort = threading.Event()
        self._antwort_wert = False
        self.nur_lesen = False

    # -- vom Fenster gerufen ------------------------------------------------

    def auftrag_geben(self, text: str, bilder: list[Path]) -> None:
        self.auftraege.put(("auftrag", text, bilder))

    def not_aus(self) -> None:
        if self._schleife and self.sitzung:
            asyncio.run_coroutine_threadsafe(self.sitzung.not_aus(), self._schleife)

    def beenden(self) -> None:
        self.auftraege.put(("ende", "", []))

    def modell_setzen(self, wert: str) -> None:
        """Legt ein anderes Modell fest. Der Wechsel laeuft im Arbeitsfaden,
        weil er die Sitzung trennt und neu verbindet; gemeldet wird er ueber
        'modelle_da' und 'bereit_da'."""
        self.modell = wert or ""
        self.auftraege.put(("modell", self.modell, []))

    def frage_beantworten(self, ja: bool) -> None:
        self._antwort_wert = ja
        self._antwort.set()

    def nur_lesen_setzen(self, an: bool) -> None:
        """Merkt den Zustand und reicht ihn an die Sitzung weiter, sobald es
        eine gibt. Ein einzelner Wahrheitswert, darum ohne Schleifenumweg."""
        self.nur_lesen = bool(an)
        if self.sitzung is not None:
            try:
                self.sitzung.nur_lesen_setzen(self.nur_lesen)
            except Exception as fehler:  # noqa: BLE001
                log.exception("Nur-Lesen-Modus nicht gesetzt: %s", fehler)

    # -- innerhalb des Fadens ----------------------------------------------

    async def _rueckfrage(self, satz: str) -> bool:
        self._antwort.clear()
        self.frage_da.emit(satz)
        await asyncio.get_running_loop().run_in_executor(None, self._antwort.wait)
        return self._antwort_wert

    def run(self) -> None:
        self._schleife = asyncio.new_event_loop()
        asyncio.set_event_loop(self._schleife)
        try:
            self._schleife.run_until_complete(self._arbeiten())
        except Exception as fehler:  # noqa: BLE001
            log.exception("Arbeitsfaden abgestürzt: %s", fehler)
            self.ereignis_da.emit(
                "fehler", "Arbeitsfaden abgestürzt", str(fehler), "", ""
            )
        finally:
            self._schleife.close()

    async def _arbeiten(self) -> None:
        self.sitzung = Sitzung(
            Wache.oeffnen(self.projekt),
            bei_ereignis=lambda e: self.ereignis_da.emit(
                e.zustand.value, e.ansage, e.detail, e.pfad, e.taetigkeit
            ),
            bei_text=lambda t: self.text_da.emit(t),
            bei_rueckfrage=self._rueckfrage,
            bei_verbrauch=lambda v: self.verbrauch_da.emit(v),
            modell=self.modell,
        )
        self.sitzung.nur_lesen_setzen(self.nur_lesen)
        await self.sitzung.verbinden()
        self.modelle_da.emit(list(self.sitzung.modelle))
        self.bereit_da.emit()

        while True:
            art, text, bilder = await asyncio.get_running_loop().run_in_executor(
                None, self.auftraege.get
            )
            if art == "ende":
                break
            if art == "modell":
                try:
                    await self.sitzung.modell_wechseln(text)
                    self.modelle_da.emit(list(self.sitzung.modelle))
                    self.bereit_da.emit()
                except Exception as fehler:  # noqa: BLE001
                    log.exception("Modellwechsel gescheitert: %s", fehler)
                    self.ereignis_da.emit(
                        "fehler", "Modell konnte nicht gewechselt werden",
                        str(fehler), "", ""
                    )
                continue
            try:
                self.ereignis_da.emit("denkt", "Auftrag laeuft", text[:120], "", "")
                bilanz = await self.sitzung.auftrag(text, bilder)
                self.fertig_da.emit(bilanz)
            except Exception as fehler:  # noqa: BLE001
                log.exception("Auftrag gescheitert: %s", fehler)
                self.fertig_da.emit({"antwort": "", "geaendert": [], "fehler": str(fehler),
                                     "abgebrochen": False, "schritte": 0})

        await self.sitzung.trennen()
