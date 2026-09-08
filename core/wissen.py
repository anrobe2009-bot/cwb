"""
CWB - Code Workbench
Baustein 4: Projektgedächtnis.

Aufteilung:
- CLAUDE.md im Projekt        Grundlagen. Wird von Claude Code immer gelesen.
- wissen/tagebuch.md          wächst mit jeder Arbeitsstunde, neueste unten.
- wissen/offen.md             offene Punkte, das einzige, was immer eingespeist wird.
- wissen/archiv/JJJJ-MM.md    verdichtete alte Tagebucheinträge.

Der Memory Hub bleibt das Archiv. Von dort werden nur Einträge des aktuellen
Projekts gelesen, nie projektübergreifend - ausser 'global'.

Eingespeist wird in Schichten und gedeckelt, damit der Kontext nicht zuwächst.
"""

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

try:
    from .pfade import hub_datenbank
except ImportError:
    from pfade import hub_datenbank

log = logging.getLogger("cwb.wissen")

# Wo der Memory Hub liegt, steht in einstellungen.json (siehe pfade.py). Er
# darf ganz fehlen; dann arbeitet CWB nur mit dem Gedächtnis im Projekt.

MAX_TAGEBUCH = 40        # jüngste Tagebucheinträge im Kontextblock
MAX_HUB = 40             # Einträge aus dem Memory Hub im Kontextblock
ARCHIV_AB_TAGEN = 60     # ab diesem Alter wird verdichtet

ZEILE_MAX_LAENGE = 350   # jede Zeile im Kontextblock wird hierauf gekappt
BLOCK_MAX_LAENGE = 12000 # Obergrenze für den gesamten Kontextblock

HINWEIS_GEKUERZT = "\n(Gekürzt. Mehr ist über die Suche erreichbar.)"
HINWEIS_GEDAECHTNIS = (
    "\nDies ist Gedächtnis, keine Aufgabe. Arbeite nur an dem, was jetzt "
    "gefragt wird.\n"
)


def _kappen(zeile: str, laenge: int = ZEILE_MAX_LAENGE) -> str:
    """Kürzt eine einzelne Zeile auf höchstens `laenge` Zeichen."""
    zeile = zeile.rstrip()
    if len(zeile) <= laenge:
        return zeile
    return zeile[: laenge - 1].rstrip() + "…"

GRUNDLAGEN_VORLAGE = """# {name}

## Was das Projekt ist
(noch nicht ausgefüllt)

## Aufbau
(noch nicht ausgefüllt)

## Konventionen
- Strikte Trennung: keine Inline-Scripts, keine Inline-Styles, keine Inline-Event-Handler
- Barrierefreiheit hat Vorrang, die Oberfläche muss für sehende Nutzer trotzdem gut aussehen
- Flexible, responsive Raster, keine festen Pixelgrössen
- Jede neue Werkzeugdatei bekommt Fehler-Logging über das Modul logging

## Arbeitsweise
- Lies eine Datei, bevor du sie änderst.
- Antworte kurz. Ein bis drei Sätze zum Ergebnis, keine langen Erklärungen.
- Sag es in einem Satz, wenn etwas unklar, unmöglich oder unlogisch ist.

## Gedächtnis
- Offene Punkte stehen in `wissen/offen.md`.
- Was getan und entschieden wurde, steht in `wissen/tagebuch.md`.
- Beides wird von CWB gepflegt. Schreib nicht selbst hinein, ausser du wirst gefragt.
"""

# Wird nach jedem Auftrag als Anschlussfrage gestellt
NACHTRAG_ANWEISUNG = (
    "Fasse den gerade erledigten Auftrag in ein bis drei kurzen Zeilen für das "
    "Projekttagebuch zusammen. Nur Entscheidungen, Änderungen und offene Punkte. "
    "Keine Aufzählung jedes Arbeitsschritts, keine Vorrede. "
    "Steht etwas offen, schreibe die Zeile mit [OFFEN] davor."
)


@dataclass
class Eintrag:
    """Eine Zeile aus Tagebuch, offenen Punkten oder Hub."""
    datum: str
    text: str
    offen: bool = False

    def zeile(self) -> str:
        marke = "[OFFEN] " if self.offen else ""
        return f"{self.datum}  {marke}{self.text}"


# ---------------------------------------------------------------------------
# Memory Hub, lesend und anpassungsfähig
# ---------------------------------------------------------------------------

class HubLeser:
    """Liest aus memory.db. Findet die Spalten selbst, damit nichts bricht."""

    def __init__(self, datenbank: Path | None = None):
        if datenbank is None:
            datenbank = hub_datenbank()
        self.datenbank = Path(datenbank) if datenbank else None
        self.tabelle: str | None = None
        self.spalte_projekt: str | None = None
        self.spalte_text: str | None = None
        self.spalte_datum: str | None = None
        self.spalte_aktualisiert: str | None = None
        if self.datenbank is None:
            log.info("Kein Memory Hub eingestellt, es wird keiner gelesen")
        elif self.datenbank.exists():
            self._erkunden()
        else:
            log.warning("Memory Hub nicht gefunden: %s", self.datenbank)

    def _erkunden(self) -> None:
        try:
            with sqlite3.connect(f"file:{self.datenbank}?mode=ro", uri=True) as verbindung:
                tabellen = [
                    zeile[0]
                    for zeile in verbindung.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                ]
                for tabelle in tabellen:
                    spalten = [
                        zeile[1]
                        for zeile in verbindung.execute(f"PRAGMA table_info('{tabelle}')")
                    ]
                    klein = {s.lower(): s for s in spalten}
                    projekt = next(
                        (klein[k] for k in ("projekt", "project", "bereich", "kategorie")
                         if k in klein), None
                    )
                    text = next(
                        (klein[k] for k in ("text", "inhalt", "content", "eintrag", "notiz")
                         if k in klein), None
                    )
                    if projekt and text:
                        self.tabelle = tabelle
                        self.spalte_projekt = projekt
                        self.spalte_text = text
                        self.spalte_datum = next(
                            (klein[k] for k in ("datum", "date", "zeit", "created", "erstellt",
                                                "timestamp", "zeitstempel") if k in klein), None
                        )
                        self.spalte_aktualisiert = next(
                            (klein[k] for k in ("updated", "aktualisiert", "geaendert")
                             if k in klein), None
                        )
                        log.info(
                            "Hub erkannt: Tabelle %s, Projekt %s, Text %s, Datum %s, "
                            "Aktualisiert %s",
                            tabelle, projekt, text, self.spalte_datum, self.spalte_aktualisiert,
                        )
                        return
            log.warning("Keine passende Tabelle im Hub gefunden: %s", tabellen)
        except sqlite3.Error as fehler:
            log.error("Hub nicht lesbar: %s", fehler)

    @property
    def bereit(self) -> bool:
        return bool(self.tabelle and self.spalte_projekt and self.spalte_text)

    def eintraege(self, projekt: str, grenze: int = MAX_HUB) -> list[Eintrag]:
        """Offene Punkte zuerst, dann die jüngsten Einträge. Nur dieses Projekt."""
        if not self.bereit:
            return []

        datum = self.spalte_datum or "rowid"
        befehl = (
            f"SELECT {datum}, {self.spalte_text} FROM {self.tabelle} "
            f"WHERE lower({self.spalte_projekt}) IN (?, 'global') "
            f"ORDER BY {datum} DESC LIMIT ?"
        )
        try:
            with sqlite3.connect(f"file:{self.datenbank}?mode=ro", uri=True) as verbindung:
                zeilen = verbindung.execute(befehl, (projekt.lower(), grenze * 4)).fetchall()
        except sqlite3.Error as fehler:
            log.error("Hub-Abfrage gescheitert: %s", fehler)
            return []

        gefunden = []
        for zeile in zeilen:
            if not zeile[1] or not str(zeile[1]).strip():
                continue
            roh = str(zeile[1]).strip()
            offen = "[OFFEN]" in roh.upper()
            sauber = re.sub(r"\[OFFEN\]\s*", "", roh, flags=re.IGNORECASE).strip()
            gefunden.append(Eintrag(str(zeile[0])[:10], sauber, offen))
        offene = [e for e in gefunden if e.offen]
        rest = [e for e in gefunden if not e.offen]
        return (offene + rest)[:grenze]

    def suchen(self, begriff: str, projekt: str, grenze: int = 20) -> list[Eintrag]:
        if not self.bereit or not begriff.strip():
            return []
        befehl = (
            f"SELECT {self.spalte_datum or 'rowid'}, {self.spalte_text} FROM {self.tabelle} "
            f"WHERE lower({self.spalte_projekt}) IN (?, 'global') "
            f"AND {self.spalte_text} LIKE ? LIMIT ?"
        )
        try:
            with sqlite3.connect(f"file:{self.datenbank}?mode=ro", uri=True) as verbindung:
                zeilen = verbindung.execute(
                    befehl, (projekt.lower(), f"%{begriff}%", grenze)
                ).fetchall()
        except sqlite3.Error as fehler:
            log.error("Hub-Suche gescheitert: %s", fehler)
            return []
        return [Eintrag(str(z[0])[:10], str(z[1]).strip()) for z in zeilen if z[1]]

    def eintrag_schreiben(self, projekt: str, text: str, datum: str | None = None) -> bool:
        """Schreibt eine neue Zeile in die Hub-Datenbank, unter Verwendung der
        bereits erkannten Spalten. Fehlt der Hub, ist er nicht erreichbar oder
        schlaegt das Schreiben fehl, wird nur geloggt - die Sitzung darf
        davon nicht beeintraechtigt werden."""
        if not self.bereit:
            log.info("Kein Memory Hub erreichbar, Eintrag nicht geschrieben")
            return False
        spalten = [self.spalte_projekt, self.spalte_text]
        werte = [projekt, text]
        wert_datum = datum or date.today().isoformat()
        if self.spalte_datum:
            spalten.append(self.spalte_datum)
            werte.append(wert_datum)
        if self.spalte_aktualisiert:
            spalten.append(self.spalte_aktualisiert)
            werte.append(wert_datum)
        platzhalter = ", ".join("?" for _ in werte)
        befehl = (
            f"INSERT INTO {self.tabelle} ({', '.join(spalten)}) "
            f"VALUES ({platzhalter})"
        )
        try:
            with sqlite3.connect(str(self.datenbank)) as verbindung:
                verbindung.execute(befehl, werte)
                verbindung.commit()
            log.info("Eintrag in Memory Hub geschrieben (Projekt %s)", projekt)
            return True
        except sqlite3.Error as fehler:
            log.error("Eintrag nicht in Memory Hub schreibbar: %s", fehler)
            return False


# ---------------------------------------------------------------------------
# Wissensschicht im Projekt
# ---------------------------------------------------------------------------

class Wissen:
    """Grundlagen, Tagebuch und offene Punkte eines Projekts."""

    def __init__(self, projekt_pfad: Path, projekt_name: str):
        self.pfad = Path(projekt_pfad)
        self.name = projekt_name
        self.ordner = self.pfad / "wissen"
        self.archiv = self.ordner / "archiv"
        self.grundlagen_datei = self.pfad / "CLAUDE.md"
        self.tagebuch_datei = self.ordner / "tagebuch.md"
        self.offen_datei = self.ordner / "offen.md"
        self.hub = HubLeser()

    # -- Einrichten ---------------------------------------------------------

    def einrichten(self) -> bool:
        """Legt Ordner und Dateien an, falls sie fehlen. Ändert nichts Bestehendes."""
        try:
            self.archiv.mkdir(parents=True, exist_ok=True)
            if not self.grundlagen_datei.exists():
                self.grundlagen_datei.write_text(
                    GRUNDLAGEN_VORLAGE.format(name=self.name), encoding="utf-8"
                )
                log.info("CLAUDE.md angelegt in %s", self.pfad)
            if not self.tagebuch_datei.exists():
                self.tagebuch_datei.write_text(
                    f"# Tagebuch {self.name}\n\n", encoding="utf-8"
                )
            if not self.offen_datei.exists():
                self.offen_datei.write_text(
                    f"# Offene Punkte {self.name}\n\n", encoding="utf-8"
                )
            return True
        except OSError as fehler:
            log.error("Wissensordner nicht anlegbar: %s", fehler)
            return False

    # -- Lesen --------------------------------------------------------------

    def grundlagen(self) -> str:
        try:
            return self.grundlagen_datei.read_text(encoding="utf-8").strip()
        except OSError as fehler:
            log.error("CLAUDE.md nicht lesbar: %s", fehler)
            return ""

    def _zeilen(self, datei: Path) -> list[Eintrag]:
        try:
            roh = datei.read_text(encoding="utf-8").splitlines()
        except OSError as fehler:
            log.error("%s nicht lesbar: %s", datei.name, fehler)
            return []

        gefunden: list[Eintrag] = []
        for zeile in roh:
            zeile = zeile.strip()
            if not zeile or zeile.startswith("#"):
                continue
            treffer = re.match(r"^-?\s*(\d{4}-\d{2}-\d{2})\s+(.*)$", zeile)
            if treffer:
                text = treffer.group(2).strip()
                gefunden.append(
                    Eintrag(treffer.group(1), text.replace("[OFFEN]", "").strip(),
                            "[OFFEN]" in text.upper())
                )
            else:
                gefunden.append(
                    Eintrag("", zeile.lstrip("- ").replace("[OFFEN]", "").strip(),
                            "[OFFEN]" in zeile.upper())
                )
        return gefunden

    def offene_punkte(self) -> list[Eintrag]:
        aus_datei = [e for e in self._zeilen(self.offen_datei)]
        aus_tagebuch = [e for e in self._zeilen(self.tagebuch_datei) if e.offen]
        return aus_datei + aus_tagebuch

    def tagebuch(self, grenze: int = MAX_TAGEBUCH) -> list[Eintrag]:
        alle = self._zeilen(self.tagebuch_datei)
        return alle[-grenze:]

    # -- Kontextblock -------------------------------------------------------

    def kontextblock(self) -> str:
        """Wird der ersten Nachricht einer Sitzung vorangestellt.

        Gedeckelt auf BLOCK_MAX_LAENGE Zeichen, jede Zeile auf ZEILE_MAX_LAENGE.
        Offene Punkte haben Vorrang und werden nie gekürzt, danach füllt das
        Tagebuch (jüngste zuerst) und zuletzt der Memory Hub den Rest des
        Platzes. Wird dabei etwas weggelassen, folgt ein Hinweis auf die Suche.
        """
        kopf = f"# Projektgedächtnis: {self.name}"

        offen = self.offene_punkte()
        offen_teil: list[str] = []
        if offen:
            offen_teil.append("\n## Offene Punkte")
            offen_teil += [_kappen(f"- {e.text}") for e in offen]

        letzte = self.tagebuch()
        tagebuch_zeilen = [_kappen(f"- {e.zeile()}") for e in letzte]

        aus_hub = self.hub.eintraege(self.name)
        hub_zeilen = [_kappen(f"- {e.zeile()}") for e in aus_hub]

        if not offen_teil and not tagebuch_zeilen and not hub_zeilen:
            return ""

        teile = [kopf] + offen_teil
        gekuerzt = False
        rueckhalt = len(HINWEIS_GEKUERZT) + len(HINWEIS_GEDAECHTNIS) + 2

        def _passt_rest(bisher: list[str]) -> int:
            return BLOCK_MAX_LAENGE - len("\n".join(bisher)) - rueckhalt

        # Tagebuch: jüngste zuerst auffüllen, solange Platz reicht.
        if tagebuch_zeilen:
            ueberschrift = f"\n## Zuletzt gearbeitet (letzte {len(letzte)} Einträge)"
            budget = _passt_rest(teile) - len(ueberschrift)
            genommen: list[str] = []
            laenge = 0
            for zeile in reversed(tagebuch_zeilen):
                if laenge + 1 + len(zeile) > budget:
                    gekuerzt = True
                    break
                genommen.append(zeile)
                laenge += 1 + len(zeile)
            genommen.reverse()
            if genommen:
                teile += [ueberschrift] + genommen

        # Memory Hub: höchste Priorität zuerst, solange Platz reicht.
        if hub_zeilen:
            ueberschrift = f"\n## Aus dem Memory Hub ({len(aus_hub)} von vielen)"
            budget = _passt_rest(teile) - len(ueberschrift)
            genommen = []
            laenge = 0
            for zeile in hub_zeilen:
                if laenge + 1 + len(zeile) > budget:
                    gekuerzt = True
                    break
                genommen.append(zeile)
                laenge += 1 + len(zeile)
            if genommen:
                teile += [ueberschrift] + genommen
            if len(genommen) < len(hub_zeilen):
                gekuerzt = True

        if gekuerzt:
            teile.append(HINWEIS_GEKUERZT)
        teile.append(HINWEIS_GEDAECHTNIS)
        return "\n".join(teile)

    # -- Schreiben ----------------------------------------------------------

    def tagebuch_anhaengen(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        heute = date.today().isoformat()
        inhalte = [z.strip() for z in text.splitlines() if z.strip()]
        zeilen = [f"- {heute} {z}" for z in inhalte]
        try:
            with self.tagebuch_datei.open("a", encoding="utf-8") as datei:
                datei.write("\n".join(zeilen) + "\n")
        except OSError as fehler:
            log.error("Tagebuch nicht schreibbar: %s", fehler)
            return False
        for inhalt in inhalte:
            self.hub.eintrag_schreiben(self.name, inhalt, heute)
        return True

    def offen_anhaengen(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        try:
            with self.offen_datei.open("a", encoding="utf-8") as datei:
                datei.write(f"- {date.today().isoformat()} {text}\n")
            return True
        except OSError as fehler:
            log.error("Offene Punkte nicht schreibbar: %s", fehler)
            return False

    def offen_schliessen(self, suchtext: str) -> bool:
        """Entfernt die erste Zeile, die den Suchtext enthält."""
        try:
            zeilen = self.offen_datei.read_text(encoding="utf-8").splitlines()
        except OSError as fehler:
            log.error("Offene Punkte nicht lesbar: %s", fehler)
            return False

        for nummer, zeile in enumerate(zeilen):
            if suchtext.lower() in zeile.lower() and not zeile.startswith("#"):
                erledigt = zeilen.pop(nummer)
                try:
                    self.offen_datei.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
                except OSError as fehler:
                    log.error("Offene Punkte nicht schreibbar: %s", fehler)
                    return False
                self.tagebuch_anhaengen(f"Erledigt: {erledigt.lstrip('- ').strip()}")
                return True
        return False

    # -- Suchen -------------------------------------------------------------

    def suchen(self, begriff: str) -> list[Eintrag]:
        begriff = begriff.strip().lower()
        if not begriff:
            return []
        gefunden = [
            e for e in self._zeilen(self.tagebuch_datei) + self._zeilen(self.offen_datei)
            if begriff in e.text.lower()
        ]
        for datei in sorted(self.archiv.glob("*.md")):
            gefunden += [e for e in self._zeilen(datei) if begriff in e.text.lower()]
        return gefunden + self.hub.suchen(begriff, self.name)

    # -- Verdichten ---------------------------------------------------------

    def zum_verdichten(self, ab_tagen: int = ARCHIV_AB_TAGEN) -> list[Eintrag]:
        """Tagebucheinträge, die alt genug fürs Archiv sind."""
        heute = date.today()
        alt: list[Eintrag] = []
        for eintrag in self._zeilen(self.tagebuch_datei):
            if eintrag.offen or not eintrag.datum:
                continue
            try:
                wann = datetime.strptime(eintrag.datum, "%Y-%m-%d").date()
            except ValueError:
                continue
            if (heute - wann).days >= ab_tagen:
                alt.append(eintrag)
        return alt

    def verdichten(self, zusammenfassung: str, verdichtete: list[Eintrag]) -> bool:
        """Schreibt die Zusammenfassung ins Archiv und entfernt die alten Zeilen."""
        if not verdichtete or not zusammenfassung.strip():
            return False

        monat = verdichtete[0].datum[:7] or date.today().strftime("%Y-%m")
        ziel = self.archiv / f"{monat}.md"
        try:
            with ziel.open("a", encoding="utf-8") as datei:
                datei.write(
                    f"\n## Verdichtet am {date.today().isoformat()} "
                    f"({len(verdichtete)} Einträge)\n{zusammenfassung.strip()}\n"
                )
        except OSError as fehler:
            log.error("Archiv nicht schreibbar: %s", fehler)
            return False

        alte_texte = {e.text for e in verdichtete}
        try:
            zeilen = self.tagebuch_datei.read_text(encoding="utf-8").splitlines()
            behalten = [
                z for z in zeilen
                if z.startswith("#") or not z.strip()
                or not any(t and t in z for t in alte_texte)
            ]
            self.tagebuch_datei.write_text("\n".join(behalten) + "\n", encoding="utf-8")
        except OSError as fehler:
            log.error("Tagebuch nicht kürzbar: %s", fehler)
            return False

        log.info("%d Einträge verdichtet nach %s", len(verdichtete), ziel.name)
        return True


# ---------------------------------------------------------------------------
# Selbsttest
# ---------------------------------------------------------------------------

def _selbsttest() -> None:
    try:
        from .sicherheit import projekte_finden
    except ImportError:
        from sicherheit import projekte_finden

    hub = HubLeser()
    print("Memory Hub:", "erkannt" if hub.bereit else "nicht erkannt")
    if hub.bereit:
        print(f"  Tabelle {hub.tabelle}, Projekt {hub.spalte_projekt}, "
              f"Text {hub.spalte_text}, Datum {hub.spalte_datum}")

    projekte = projekte_finden()
    if not projekte:
        print("Keine Projekte gefunden.")
        return

    print("\nProjekte:")
    for nummer, projekt in enumerate(projekte, 1):
        print(f"  {nummer}. {projekt.name}")

    wahl = input("\nNummer wählen: ").strip()
    if not wahl.isdigit() or not 1 <= int(wahl) <= len(projekte):
        return
    projekt = projekte[int(wahl) - 1]

    wissen = Wissen(projekt.pfad, projekt.name)
    print("\nEinrichten:", "ok" if wissen.einrichten() else "gescheitert")
    print(f"Offene Punkte: {len(wissen.offene_punkte())}")
    print(f"Tagebuch: {len(wissen.tagebuch())} jüngste Einträge")
    print(f"Zum Verdichten: {len(wissen.zum_verdichten())} Einträge")

    block = wissen.kontextblock()
    print(f"\nKontextblock: {len(block)} Zeichen, {len(block.splitlines())} Zeilen")
    print("-" * 60)
    print(block[:1500] or "(leer)")


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    try:
        _selbsttest()
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
    except Exception as fehler:  # noqa: BLE001
        log.exception("Selbsttest abgebrochen: %s", fehler)
        print(f"Selbsttest abgebrochen: {fehler}")
