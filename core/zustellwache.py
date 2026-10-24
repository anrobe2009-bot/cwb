"""
CWB - Code Workbench
Zustellwache: sorgt dafuer, dass jedes Ergebnis eines Brueckenauftrags im
Chatfenster ankommt, und meldet der KI im Chat, wenn etwas lange dauert oder
nicht zugestellt werden konnte. Gilt nur fuer Brueckenauftraege.

Zustellung: Ein Eintrag gilt erst als zugestellt, wenn der Einfueger Erfolg
meldet (Rueckruf). Misslingt das Einfuegen oder wird es uebersprungen, kommt
nach dem Hochladen je ein neuer Versuch nach 10, 30 und 60 Sekunden. Ist der
Bericht 90 Sekunden nach dem Hochladen noch nicht zugestellt, geht einmal der
"CWB-Hinweis" in den Chat. Ein Bild bekommt einen einzigen Wiederholungsversuch.
Solange ein Versuch noch in der Warteschlange des Einfuegers steht, wird kein
zweiter eingereiht - so landet nichts doppelt im Chat; ein zugestellter
Eintrag wird nie erneut eingereiht.

Nachlieferung: Der Bericht liegt immer zuerst auf der Bruecke, der Chat ist nur
der Zustellweg. Ist ein Eintrag nach den Wiederholungen noch nicht
zugestellt (Chat nicht erreichbar, Robert tippt, kein Chatfenster vorn), geht
er in die Nachlieferung: sie versucht es still weiter, immer nur den aeltesten
Eintrag und streng in der Reihenfolge der Entstehung, ohne weitere Ansage (die
einzige Ansage je Eintrag kommt beim ersten Misslingen ueber `melden`). Ein
Hinweis, dessen Anlass sich erledigt hat (Bericht inzwischen zugestellt,
Auftrag beendet), entfaellt. Nach MAX_WARTEZEIT_S wird ein Eintrag verworfen;
er liegt ja auf der Bruecke. Zwischen zwei Einfuegungen liegen mindestens
NACHLIEFER_ABSTAND_S Sekunden.

Sammeln statt draengeln: Ein Ergebnis, das nicht sicher zugestellt werden kann,
bleibt hier in der Warteschlange (es liegt ohnehin auf der Bruecke). Wartet
mindestens eines davon laenger als WARTEMELDUNG_S Sekunden, sagt `melden(N)`
einmal an, wie viele warten; wiederholt wird erst, wenn die Zahl steigt.
`bei_aenderung(N)` haelt die Kachel aktuell. Ist `pruefen` gegeben, schaut die
Nachlieferung alle PRUEF_TAKT_S Sekunden nach, ob die Luft rein ist (Chat
erreichbar, seit 3 Sekunden keine Eingabe) und stellt dann von selbst zu - nachts
also sofort. `vorbereiten_manuell()`/`manuell_starten()` sind die Zustelltaste:
alle wartenden der Reihe nach, mit Abstand, ohne Ruhezeit.

Zeitwache: Ein Brueckenauftrag, der nach 15 Minuten noch nicht fertig ist,
loest einen Hinweis aus, danach alle 15 Minuten wieder.

Alles ist reines Python: Einreihen, Zeitgeber und Zielsuche kommen von
aussen (core/fenster.py), damit die Tests ohne Fenster laufen. Jede Methode
faengt ihre Fehler selbst ab und meldet sie nur im Log - ein Fehler der Wachen
darf nie einen Auftrag stoeren. Jeder Versuch steht im Auftragsjournal.
"""

import logging

try:
    from .pfade import log_einrichten
except ImportError:
    from pfade import log_einrichten

log_einrichten()
try:
    from . import auftragsjournal
except ImportError:
    import auftragsjournal

log = logging.getLogger("cwb.zustellwache")

# Wiederholungen nach dem Hochladen, in Sekunden.
BERICHT_WIEDERHOLUNGEN_S = (10, 30, 60)
BILD_WIEDERHOLUNGEN_S = (5,)
# Ab hier geht der Hinweis in den Chat, wenn der Bericht fehlt.
HINWEIS_NACH_S = 90
# Startet der Upload nie, laeuft die Uhr nach dieser Zeit trotzdem los.
UHR_NOTSTART_S = 120
# Zeitwache: Abstand der Hinweise zu einem lange laufenden Auftrag.
LAUFZEIT_TAKT_MIN = 15
# Nachlieferung: Abstand der Versuche, Abstand nach einer Zustellung, Obergrenze.
NACHLIEFER_TAKT_S = 45
NACHLIEFER_ABSTAND_S = 2
MAX_WARTEZEIT_S = 6 * 3600
# Sammeln statt draengeln.
WARTEMELDUNG_S = 20
PRUEF_TAKT_S = 5
# Nach einem echt gescheiterten Versuch erst nach dieser Pause erneut.
NACH_FEHLVERSUCH_S = 45
# Gruende, aus denen der Einfueger gar nicht erst angefangen hat (Pruefung vor
# dem Einfuegen): kein echter Fehlversuch, darum keine Pause danach.
ZURUECKGESTELLT = ("kein Chatfenster", "Zielfenster nicht lesbar", "Eingabe laeuft",
                   "Chat im Vordergrund", "Chat war gerade", "kein Zielfenster")


class _Eintrag:
    def __init__(self, nummer, art: str, text: str, ziel, bild_pfad, wiederholungen):
        self.nummer = nummer
        self.art = art
        self.text = text
        self.ziel = ziel
        self.bild_pfad = bild_pfad
        self.wiederholungen = tuple(wiederholungen)
        self.zugestellt = False
        self.laeuft = False
        self.versuche = 0
        self.uhr_gestartet = False
        self.nachliefern = False
        self.verworfen = False
        self.gemeldet = False
        self.warte_ms = 0
        self.folge = 0
        self.wartet = False
        self.lang = False
        self.timer_geplant = False
        self.sperre_ms = 0

# Terminalergebnisse bis zu dieser Laenge gehen als Volltext in den Chat, laengere
# nur als Kurzmeldung (Volltext liegt im Ablagefach der Bruecke).
TERMINAL_KURZ_GRENZE = 3000


def _kopf_klammer(projekt, block) -> str:
    teile = [str(t) for t in (projekt, f"Block {block}" if block else None) if t]
    return f" ({', '.join(teile)})" if teile else ""


def kurzmeldung_bericht(nummer, projekt, block, status: str, protokoll,
                        zeichen: int, dateien: int) -> str:
    """Die eine Zeile, die statt des Berichts in den Chat geht. status:
    "fertig", "fehler" oder "abgebrochen". Immer kurz, hoechstens zwei Saetze."""
    kopf = f"CWB: Auftrag {nummer}"
    klammer = _kopf_klammer(projekt, block)
    wo = (f"Protokoll {protokoll}" if protokoll
          else "Bericht liegt auf der Brücke (bericht_holen)")
    if status == "fehler":
        return f"{kopf} FEHLER{klammer}, {wo}."
    if status == "abgebrochen":
        return f"{kopf} ABGEBROCHEN{klammer}, {wo}."
    teile = [wo, f"{zeichen} Zeichen"]
    if dateien:
        teile.append(f"{dateien} {'Datei' if dateien == 1 else 'Dateien'} geändert")
    return f"{kopf} fertig{klammer}, {', '.join(teile)}."


def kurzmeldung_terminal(nummer, projekt, block, erfolg: bool, protokoll,
                         zeichen: int) -> str:
    """Kurzmeldung fuer ein Terminalergebnis, das zu lang fuer den Chat ist."""
    kopf = f"CWB: Terminalbefehl{' ' + str(nummer) if nummer else ''}"
    klammer = _kopf_klammer(projekt, block)
    wo = f"Protokoll {protokoll}" if protokoll else "Volltext nicht abgelegt"
    status = "fertig" if erfolg else "FEHLER"
    return f"{kopf} {status}{klammer}, {wo}, {zeichen} Zeichen."


class Zustellwache:
    """einreihen(ziel, text, bild_pfad, kennung, rueckruf) -> bool: reiht ein
    Ergebnis ein und ruft spaeter rueckruf(erfolg, grund) auf; False, wenn
    nichts eingereiht werden konnte.
    planen(ms, funktion): ruft die Funktion spaeter auf.
    ziel_ersatz(): zuletzt bekanntes Zielfenster, falls der Eintrag keins hat.
    melden(zahl): einmal, wenn Ergebnisse laenger als WARTEMELDUNG_S warten.
    pruefen(ziel, manuell=False) -> (bool, grund): ist die Luft rein?
    bei_aenderung(zahl): Zahl der wartenden Ergebnisse hat sich geaendert.
    ablegen(nummer, art, text): legt jeden CWB-Hinweis (Zeitwache, Zustellwache)
    zusaetzlich im Ablagefach der Bruecke ab; Fehler dort stoeren nie."""

    def __init__(self, einreihen, planen, ziel_ersatz=None, melden=None,
                 pruefen=None, bei_aenderung=None, ablegen=None):
        self._einreihen = einreihen
        self._planen = planen
        self._ziel_ersatz = ziel_ersatz or (lambda: None)
        self._melden = melden
        self._pruefen = pruefen
        self._bei_aenderung = bei_aenderung
        self._ablegen = ablegen
        self._angesagt = 0
        self._ansage_geplant = False
        self._zahl_bekannt = 0
        self._manuell = False
        self._manuell_versucht: set = set()
        self._eintraege: dict = {}
        self._auftraege: dict = {}
        self._folge = 0
        self._nachlieferung_aktiv = False
        self._schon_hochgeladen: set = set()

    # -- Zustellung ---------------------------------------------------------

    def zustellen(self, nummer, art: str, text: str, ziel, bild_pfad=None,
                  wiederholungen=None) -> bool:
        """Erster Versuch jetzt. Gibt es zu (nummer, art) schon einen Eintrag,
        passiert nichts - der Merker je Brueckennummer bleibt massgeblich."""
        try:
            schluessel = (nummer, art)
            if schluessel in self._eintraege:
                self._journal("zustellung_doppelt", nummer, art, "Eintrag besteht schon")
                return False
            if self._ablegen is not None and art.startswith(("hinweis", "zeit")):
                try:
                    self._ablegen(nummer, art, text)
                except Exception:  # noqa: BLE001
                    log.exception("Zustellwache: Hinweis nicht im Ablagefach")
            if wiederholungen is None:
                wiederholungen = BILD_WIEDERHOLUNGEN_S if bild_pfad else BERICHT_WIEDERHOLUNGEN_S
            eintrag = _Eintrag(nummer, art, text, ziel, bild_pfad, wiederholungen)
            self._folge += 1
            eintrag.folge = self._folge
            self._eintraege[schluessel] = eintrag
            if (bild_pfad or art.startswith(("hinweis", "zeit"))
                    or nummer in self._schon_hochgeladen):
                # Bilder und Hinweise haengen an keinem Upload: Uhr sofort.
                # Auch wenn der Upload schon durch ist (die Kurzmeldung wartet
                # auf die Protokollnummer und kommt spaeter als der Upload).
                self._uhr_starten(eintrag)
            else:
                self._planen(UHR_NOTSTART_S * 1000, lambda: self._uhr_starten(eintrag))
            return self._versuchen(eintrag)
        except Exception:  # noqa: BLE001
            log.exception("Zustellung nicht begonnen (nummer=%s art=%s)", nummer, art)
            return False

    def hochgeladen(self, nummer) -> None:
        """Der Upload des Berichts ist durch (gelungen oder endgueltig
        gescheitert): ab jetzt laeuft die Uhr der Wiederholungen."""
        try:
            self._schon_hochgeladen.add(nummer)
            for (n, _art), eintrag in list(self._eintraege.items()):
                if n == nummer:
                    self._uhr_starten(eintrag)
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: hochgeladen(%s) fehlgeschlagen", nummer)

    def ist_zugestellt(self, nummer, art: str) -> bool:
        eintrag = self._eintraege.get((nummer, art))
        return bool(eintrag and eintrag.zugestellt)

    def _uhr_starten(self, eintrag) -> None:
        try:
            if eintrag.uhr_gestartet or eintrag.zugestellt:
                return
            eintrag.uhr_gestartet = True
            for k, sekunden in enumerate(eintrag.wiederholungen, start=1):
                self._planen(int(sekunden * 1000),
                             lambda e=eintrag, k=k: self._wiederholen(e, k))
            if eintrag.art == "code" or eintrag.art == "run":
                self._planen(HINWEIS_NACH_S * 1000, lambda e=eintrag: self._hinweisen(e))
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Uhr nicht gestartet")

    def _wiederholen(self, eintrag, k: int) -> None:
        try:
            if eintrag.zugestellt:
                return
            if eintrag.laeuft:
                self._journal("zustellversuch", eintrag.nummer, eintrag.art,
                              f"wiederholung={k} uebersprungen, voriger Versuch steht noch an")
                return
            self._journal("zustellversuch", eintrag.nummer, eintrag.art, f"wiederholung={k}")
            self._versuchen(eintrag)
            if k == len(eintrag.wiederholungen) and not eintrag.zugestellt \
                    and not eintrag.laeuft:
                self._journal("zustellung_aufgegeben", eintrag.nummer, eintrag.art,
                              f"nach {eintrag.versuche} Versuchen nicht zugestellt, "
                              "Nachlieferung uebernimmt")
                self._nachliefern_anmelden(eintrag)
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Wiederholung %s fehlgeschlagen", k)

    def _hinweisen(self, eintrag) -> None:
        try:
            if eintrag.zugestellt:
                return
            self._journal("zustellung_fehlt", eintrag.nummer, eintrag.art,
                          f"nach {HINWEIS_NACH_S} s nicht zugestellt, Hinweis folgt")
            self.zustellen(
                eintrag.nummer, "hinweis_" + eintrag.art,
                f"CWB-Hinweis: Bericht zu Auftrag {eintrag.nummer} konnte nicht "
                f"eingefuegt werden.", None)
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Hinweis nicht gesendet")

    def _versuchen(self, eintrag) -> bool:
        eintrag.versuche += 1
        eintrag.laeuft = True
        kennung = auftragsjournal.kennung(eintrag.nummer, None, eintrag.art)
        if self._manuell and isinstance(kennung, dict):
            kennung = dict(kennung, manuell=True)
        ziel = eintrag.ziel or self._ziel_ersatz()
        try:
            eingereiht = self._einreihen(
                ziel, eintrag.text, eintrag.bild_pfad, kennung,
                lambda erfolg, grund="": self._ergebnis(eintrag, erfolg, grund))
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Einreihen fehlgeschlagen")
            eingereiht = False
            eintrag.laeuft = False
            self._journal("zustellversuch", eintrag.nummer, eintrag.art,
                          f"nr={eintrag.versuche} Fehler beim Einreihen")
        if not eingereiht and eintrag.laeuft:
            eintrag.laeuft = False
            self._journal("zustellversuch", eintrag.nummer, eintrag.art,
                          f"nr={eintrag.versuche} nicht eingereiht")
        return bool(eingereiht)

    def _ergebnis(self, eintrag, erfolg: bool, grund: str = "") -> None:
        try:
            eintrag.laeuft = False
            if erfolg:
                eintrag.zugestellt = True
            log.info("Zustellung %s/%s Versuch %s: %s", eintrag.nummer, eintrag.art,
                     eintrag.versuche, "geklappt" if erfolg else f"gescheitert ({grund})")
            if erfolg:
                eintrag.wartet = False
            else:
                eintrag.wartet = True
                if not grund.startswith(ZURUECKGESTELLT):
                    eintrag.sperre_ms = NACH_FEHLVERSUCH_S * 1000
                self._warten_beginnt(eintrag)
                if self._pruefen is not None:
                    self._nachliefern_anmelden(eintrag)
            self._zahl_pruefen()
            self._journal(
                "zugestellt" if erfolg else "zustellversuch", eintrag.nummer, eintrag.art,
                f"nr={eintrag.versuche} " + ("erfolgreich" if erfolg
                                              else f"gescheitert grund={grund or 'unbekannt'}"))
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Ergebnis nicht verbucht")

    # -- Sammeln statt draengeln ---------------------------------------------

    @staticmethod
    def _ist_ergebnis(eintrag) -> bool:
        return eintrag.art.startswith(("code", "run", "bild"))

    def wartende_ergebnisse(self) -> list:
        """Ergebnisse (keine Hinweise), die nicht zugestellt werden konnten."""
        return sorted((e for e in self._eintraege.values()
                       if e.wartet and self._ist_ergebnis(e)
                       and not e.zugestellt and not e.verworfen),
                      key=lambda e: e.folge)

    def _warten_beginnt(self, eintrag) -> None:
        if eintrag.timer_geplant or not self._ist_ergebnis(eintrag):
            return
        eintrag.timer_geplant = True
        self._planen(WARTEMELDUNG_S * 1000, lambda e=eintrag: self._lang_wartend(e))

    def _lang_wartend(self, eintrag) -> None:
        try:
            if eintrag.zugestellt or eintrag.verworfen:
                return
            eintrag.lang = True
            # Was in derselben Sekunde "lang" wird, kommt in EINE Ansage.
            if not self._ansage_geplant:
                self._ansage_geplant = True
                self._planen(1000, self._ansage_auswerten)
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Wartezeit nicht ausgewertet")

    def _ansage_auswerten(self) -> None:
        """Sagt an, wie viele Ergebnisse laenger als 20 Sekunden warten - nur
        wenn es mehr sind als beim letzten Mal."""
        self._ansage_geplant = False
        try:
            lange = sum(1 for e in self.wartende_ergebnisse() if e.lang)
            if lange > self._angesagt:
                self._angesagt = lange
                if self._melden is not None:
                    self._melden(lange)
            elif lange < self._angesagt:
                self._angesagt = lange
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Wartemeldung fehlgeschlagen")

    def _zahl_pruefen(self) -> None:
        """Haelt Kachel und die eine Ansage auf dem Stand."""
        try:
            wartende = self.wartende_ergebnisse()
            if len(wartende) != self._zahl_bekannt:
                self._zahl_bekannt = len(wartende)
                if self._bei_aenderung is not None:
                    self._bei_aenderung(self._zahl_bekannt)
            lange = sum(1 for e in wartende if e.lang)
            if lange == 0:
                self._angesagt = 0
            elif lange < self._angesagt:
                self._angesagt = lange     # weniger geworden: still
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Zahl der Wartenden nicht ausgewertet")

    # -- Zustelltaste --------------------------------------------------------

    def vorbereiten_manuell(self) -> tuple[int, str]:
        """(Zahl der wartenden Ergebnisse, Grund warum jetzt nicht - sonst leer)."""
        try:
            wartende = self.wartende_ergebnisse()
            if not wartende:
                return 0, ""
            if self._pruefen is not None:
                erlaubt, grund = self._ziel_pruefen(wartende[0], True)
                if not erlaubt:
                    return len(wartende), grund or "Chat nicht erreichbar"
            return len(wartende), ""
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: manuelle Zustellung nicht vorbereitet")
            return 0, "Fehler"

    def manuell_starten(self) -> None:
        """Stellt alle Wartenden der Reihe nach zu, 2 Sekunden Abstand."""
        try:
            self._manuell = True
            self._manuell_versucht = set()
            self._manuell_schritt()
        except Exception:  # noqa: BLE001
            self._manuell = False
            log.exception("Zustellwache: manuelle Zustellung fehlgeschlagen")

    def _manuell_schritt(self) -> None:
        warte_ms = NACHLIEFER_ABSTAND_S * 1000
        try:
            offen = self._ausstehend()
            if not offen:
                self._manuell = False
                return
            if not any(e.laeuft for e in self._eintraege.values()):
                eintrag = offen[0]
                if self._hinweis_erledigt(eintrag):
                    eintrag.zugestellt = True
                    self._journal("zustellung_entfallen", eintrag.nummer, eintrag.art,
                                  "Anlass des Hinweises erledigt")
                    warte_ms = 0
                elif eintrag.folge in self._manuell_versucht:
                    # Schon versucht und nicht angekommen: Schluss, kein Dauerlauf.
                    self._manuell = False
                    self._journal("zustellversuch", eintrag.nummer, eintrag.art,
                                  "manuelle Zustellung abgebrochen")
                    self._zahl_pruefen()
                    return
                else:
                    self._manuell_versucht.add(eintrag.folge)
                    self._journal("zustellversuch", eintrag.nummer, eintrag.art,
                                  f"manuell nr={eintrag.versuche + 1}")
                    self._versuchen(eintrag)
        except Exception:  # noqa: BLE001
            self._manuell = False
            log.exception("Zustellwache: manueller Schritt fehlgeschlagen")
            return
        self._planen(warte_ms, self._manuell_schritt)

    # -- Nachlieferung ------------------------------------------------------

    def _nachliefern_anmelden(self, eintrag) -> None:
        try:
            eintrag.nachliefern = True
            if not self._nachlieferung_aktiv:
                self._nachlieferung_aktiv = True
                self._planen(self._takt_ms(), self._nachliefern)
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Nachlieferung nicht angemeldet")

    def wartende(self) -> int:
        """Zahl der Eintraege, die noch nicht zugestellt sind und nachgeliefert werden."""
        return len(self._nachlieferbar())

    def _ausstehend(self) -> list:
        """Alles, was noch zugestellt werden muss, in Entstehungsreihenfolge."""
        return sorted((e for e in self._eintraege.values()
                       if (e.nachliefern or e.wartet) and not e.zugestellt
                       and not e.verworfen),
                      key=lambda e: e.folge)

    def _nachlieferbar(self) -> list:
        return sorted((e for e in self._eintraege.values()
                       if e.nachliefern and not e.zugestellt and not e.verworfen),
                      key=lambda e: e.folge)

    def _hinweis_erledigt(self, eintrag) -> bool:
        """Ein Hinweis, dessen Anlass weg ist, wird nicht mehr zugestellt."""
        if eintrag.art.startswith("hinweis_"):
            return self.ist_zugestellt(eintrag.nummer, eintrag.art[len("hinweis_"):])
        if eintrag.art.startswith("zeit"):
            if eintrag.nummer not in self._auftraege:
                return True
            # Ein neuerer Laufzeit-Hinweis zum selben Auftrag ersetzt den alten.
            return any(e.nummer == eintrag.nummer and e.art.startswith("zeit")
                       and e.folge > eintrag.folge for e in self._eintraege.values())
        return False

    def _takt_ms(self) -> int:
        return (PRUEF_TAKT_S if self._pruefen is not None else NACHLIEFER_TAKT_S) * 1000

    def _ziel_pruefen(self, eintrag, manuell: bool) -> tuple[bool, str]:
        """Prueft das Ziel des Eintrags; ist es nicht mehr brauchbar (z. B.
        Fenster nach einem Neustart weg), zaehlt das Ersatzziel, das den
        Chat notfalls selbst sucht."""
        ziel = eintrag.ziel
        if ziel:
            erlaubt, grund = self._pruefen(ziel, manuell)
            if erlaubt:
                return True, ""
            ersatz = self._ziel_ersatz()
            if not ersatz or ersatz == ziel:
                return False, grund
            eintrag.ziel = ersatz
            return self._pruefen(ersatz, manuell)
        ziel = self._ziel_ersatz()
        if not ziel:
            return False, "kein Zielfenster"
        return self._pruefen(ziel, manuell)

    def _luft_rein(self, eintrag) -> bool:
        """Chat erreichbar und Robert tippt nicht (nur mit `pruefen`)."""
        try:
            erlaubt, _grund = self._ziel_pruefen(eintrag, False)
            return bool(erlaubt)
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Luftpruefung fehlgeschlagen")
            return False

    def _nachliefern(self) -> None:
        """Ein Schritt der Nachlieferung: hoechstens der aelteste Eintrag."""
        warte_ms = self._takt_ms()
        try:
            offen = self._nachlieferbar()
            if not offen:
                self._nachlieferung_aktiv = False
                return
            if any(e.laeuft for e in self._eintraege.values()):
                warte_ms = NACHLIEFER_ABSTAND_S * 1000   # voriger Versuch steht noch an
            else:
                eintrag = offen[0]
                eintrag.warte_ms += warte_ms
                eintrag.sperre_ms = max(0, eintrag.sperre_ms - warte_ms)
                if self._manuell:
                    pass                      # die Zustelltaste arbeitet gerade
                elif eintrag.warte_ms > MAX_WARTEZEIT_S * 1000:
                    eintrag.verworfen = True
                    self._journal("zustellung_verworfen", eintrag.nummer, eintrag.art,
                                  "zu lange nicht zustellbar, liegt auf der Bruecke")
                elif self._hinweis_erledigt(eintrag):
                    eintrag.zugestellt = True
                    self._journal("zustellung_entfallen", eintrag.nummer, eintrag.art,
                                  "Anlass des Hinweises erledigt")
                elif eintrag.sperre_ms > 0 and self._pruefen is not None:
                    pass                      # Pause nach einem echten Fehlversuch
                elif self._pruefen is not None and not self._luft_rein(eintrag):
                    pass                      # Robert tippt oder kein Chat: warten
                else:
                    self._journal("zustellversuch", eintrag.nummer, eintrag.art,
                                  f"nachlieferung nr={eintrag.versuche + 1}")
                    self._versuchen(eintrag)
                    if eintrag.zugestellt or eintrag.laeuft:
                        warte_ms = NACHLIEFER_ABSTAND_S * 1000
        except Exception:  # noqa: BLE001
            log.exception("Zustellwache: Nachlieferung fehlgeschlagen")
        try:
            self._planen(warte_ms, self._nachliefern)
        except Exception:  # noqa: BLE001
            self._nachlieferung_aktiv = False
            log.exception("Zustellwache: Nachlieferung nicht neu geplant")

    # -- Zeitwache ----------------------------------------------------------

    def auftrag_beginnt(self, nummer) -> None:
        """Ein Brueckenauftrag laeuft los: nach 15 Minuten, dann alle 15 Minuten
        geht ein Hinweis in den Chat, solange er nicht fertig ist."""
        try:
            marke = object()
            self._auftraege[nummer] = marke
            self._planen(LAUFZEIT_TAKT_MIN * 60_000,
                         lambda: self._laufzeit_hinweis(nummer, marke, 1))
        except Exception:  # noqa: BLE001
            log.exception("Zeitwache: Beginn nicht vermerkt")

    def auftrag_endet(self, nummer) -> None:
        try:
            self._auftraege.pop(nummer, None)
        except Exception:  # noqa: BLE001
            log.exception("Zeitwache: Ende nicht vermerkt")

    def _laufzeit_hinweis(self, nummer, marke, k: int) -> None:
        try:
            if self._auftraege.get(nummer) is not marke:
                return
            minuten = LAUFZEIT_TAKT_MIN * k
            self._journal("zeitwache", nummer, "hinweis", f"laeuft seit {minuten} Minuten")
            self.zustellen(nummer, f"zeit{k}",
                           f"CWB-Hinweis: Auftrag {nummer} laeuft seit {minuten} Minuten.",
                           None)
        except Exception:  # noqa: BLE001
            log.exception("Zeitwache: Hinweis nicht gesendet")
        try:
            if self._auftraege.get(nummer) is marke:
                self._planen(LAUFZEIT_TAKT_MIN * 60_000,
                             lambda: self._laufzeit_hinweis(nummer, marke, k + 1))
        except Exception:  # noqa: BLE001
            log.exception("Zeitwache: naechster Hinweis nicht geplant")

    @staticmethod
    def _journal(schritt: str, nummer, art: str, detail: str) -> None:
        auftragsjournal.schreibe(schritt, detail, nummer=nummer, art=art)
