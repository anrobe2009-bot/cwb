"""
CWB - Code Workbench
Sicherheitsbaustein: Ordnergrenze, Git-Sicherungspunkte, Rollback,
Befehlsklassifizierung, Geheimnis-Sperrliste.

Reines Python, keine Oberflaeche. Direkt testbar ueber __main__.
"""

import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterable

try:
    from .pfade import (
        einstellungen_lesen,
        freigabe_hinzufuegen,
        freigaben_lesen,
        log_einrichten,
        projektwurzel,
        zusatzprojekte_lesen,
    )
except ImportError:
    from pfade import (
        einstellungen_lesen,
        freigabe_hinzufuegen,
        freigaben_lesen,
        log_einrichten,
        projektwurzel,
        zusatzprojekte_lesen,
    )

LOG_DATEI = Path(__file__).resolve().parent.parent / "cwb_fehler.log"

log_einrichten()
log = logging.getLogger("cwb.sicherheit")


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

# Wo die Projekte liegen, steht nicht hier: es wird beim ersten Start
# erfragt und in einstellungen.json gemerkt (siehe pfade.py).

# Ordner, die nie als Projekt angeboten werden.
ORDNER_AUSSCHLUSS = {
    ".git", ".idea", ".vscode", "__pycache__", "node_modules",
    "venv", ".venv", "env", "dist", "build", ".pytest_cache",
}

# Dateien und Muster, die nie gelesen oder geschrieben werden duerfen.
GEHEIMNIS_MUSTER = [
    r"(^|[\\/])\.env($|\.|[\\/])",
    r"(^|[\\/])\.env\.[^\\/]+$",
    r"(^|[\\/])secrets?\.(json|ya?ml|txt|ini|cfg)$",
    r"(^|[\\/])credentials?\.(json|ya?ml|txt|ini|cfg)$",
    r"(^|[\\/])\.netrc$",
    r"(^|[\\/])\.npmrc$",
    r"(^|[\\/])\.pypirc$",
    r"(^|[\\/])id_(rsa|ed25519|ecdsa)($|\.)",
    r"(^|[\\/])\.ssh([\\/]|$)",
    r"(^|[\\/])\.aws([\\/]|$)",
    r"(^|[\\/])[^\\/]*token[^\\/]*\.(json|txt|ini|cfg)$",
    r"(^|[\\/])[^\\/]*passwo?r?t?[^\\/]*\.(json|txt|ini|cfg)$",
    r"\.(pem|key|pfx|p12|keystore|jks)$",
]
_GEHEIMNIS_REGEX = [re.compile(m, re.IGNORECASE) for m in GEHEIMNIS_MUSTER]

# Ordner ausserhalb des Projekts, in denen ohne Rueckfrage gelesen und
# geschrieben werden darf, stehen nicht mehr fest hier eingebaut: sie kommen
# aus der gepflegten Liste im Reiter "Freigaben" der Einstellungen
# (core/pfade.py, `freigaben_lesen`). Skill-Ordner, Claude-Temp-Ordner und
# cwb-werkzeuge sind dort nur noch Voreintraege und lassen sich entfernen;
# die Sperrliste fuer Zugangsdaten gilt in jeder Freigabe unveraendert weiter.

# Erzeugte Daten: taucht nie in Bilanz oder Bericht auf.
ERZEUGTE_ORDNER = {".stimmen", ".toene", ".ablage", ".cwb", "__pycache__"}


class Stufe(Enum):
    """Wie ein Vorgang behandelt wird."""
    FREI = "frei"              # ohne Rueckfrage ausfuehren
    RUECKFRAGE = "rueckfrage"  # erst nach ausdruecklicher Zustimmung
    VERBOTEN = "verboten"      # nie ausfuehren


@dataclass
class Urteil:
    """Ergebnis einer Pruefung. Immer vorlesbar formuliert."""
    stufe: Stufe
    begruendung: str
    detail: str = ""

    @property
    def frei(self) -> bool:
        return self.stufe is Stufe.FREI

    @property
    def verboten(self) -> bool:
        return self.stufe is Stufe.VERBOTEN

    def ziel(self) -> str:
        """Der betroffene Pfad oder Befehl, immer vollstaendig."""
        return self.detail.strip()

    def ansage(self) -> str:
        """Vorlesbarer Satz. Nennt bei Rueckfrage und Ablehnung immer das Ziel."""
        if self.stufe is Stufe.FREI:
            return self.begruendung
        kopf = "Rueckfrage" if self.stufe is Stufe.RUECKFRAGE else "Abgelehnt"
        ziel = self.ziel()
        if ziel and ziel not in self.begruendung:
            return f"{kopf}: {self.begruendung}: {ziel}"
        return f"{kopf}: {self.begruendung}"


# Befehlsklassen. Reihenfolge zaehlt: verboten schlaegt Rueckfrage schlaegt frei.
BEFEHL_VERBOTEN = [
    (r"\bformat\s+[a-z]:", "Formatieren eines Laufwerks"),
    (r"\bdiskpart\b", "Diskpart-Aufruf"),
    (r"\bmkfs\b", "Dateisystem anlegen"),
    (r"\bshutdown\b|\brestart-computer\b", "Rechner herunterfahren oder neu starten"),
    (r"\bremove-item\b[^\n]*\b[a-z]:\\\s*(-recurse|$)", "Loeschen einer ganzen Laufwerkswurzel"),
    (r"\brm\s+-rf\s+/", "Rekursives Loeschen ab Wurzel"),
    (r"\breg\s+delete\b", "Loeschen in der Registrierung"),
    (r"\bcipher\s+/w", "Ueberschreiben freien Speicherplatzes"),
]

# Befehle, die Dateien schreiben, aendern oder loeschen. Nur im Nur-Lesen-Modus
# ausgewertet; dort fuehrt jeder Treffer zur harten Ablehnung.
BEFEHL_SCHREIBT = [
    (r"(^|[\s;|&(])(rm|del|erase|rmdir|rd|unlink|shred)\b", "Loeschen von Dateien"),
    (r"\bremove-item\b|\bclear-content\b", "Loeschen oder Leeren von Dateien"),
    (r"(^|[\s;|&(])(mv|cp|move|copy|xcopy|robocopy|ren|rename)\b", "Verschieben oder Kopieren"),
    (r"\bmove-item\b|\bcopy-item\b|\brename-item\b", "Verschieben oder Umbenennen"),
    (r"\bset-content\b|\badd-content\b|\bout-file\b|\bnew-item\b", "Schreiben in eine Datei"),
    (r"(^|[\s;|&(])(touch|tee|truncate|mkdir|md)\b", "Anlegen oder Ueberschreiben"),
    (r"(^|[\s;|&(])(sed|awk|perl)\b[^\n]*\s-i\b", "Datei an Ort und Stelle aendern"),
    (r">>?[^>]", "Umleitung in eine Datei"),
    (r"\bgit\s+(add|commit|rm|mv|apply|restore|revert|merge|rebase|stash|checkout|switch|reset|clean|push)\b",
     "Schreibender Git-Befehl"),
    (r"\bpip3?\s+(install|uninstall)\b", "Python-Paket installieren oder entfernen"),
    (r"\bnpm\s+(install|uninstall|update|ci)\b|\byarn\b|\bpnpm\b", "Node-Paket installieren"),
    (r"\bwinget\b|\bchoco\b|\bscoop\b", "Programminstallation"),
    (r"\bnew-itemproperty\b|\bset-itemproperty\b|\breg\s+add\b", "Aenderung in der Registrierung"),
    (r"\bcompress-archive\b|\bexpand-archive\b|\btar\s+[^\n]*-[a-z]*[xc]", "Archiv schreiben oder entpacken"),
]

# Werkzeuge, die im Nur-Lesen-Modus nie laufen duerfen.
SCHREIB_WERKZEUGE = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# Begruendungen, auf die core/sicherheit.py und die beiden Rueckfrage-
# Ausnahmen in den Einstellungen (Reiter Verhalten) sich gemeinsam beziehen -
# als Konstante, damit ein spaeterer Umbau des Wortlauts die Ausnahme nicht
# stillschweigend verfehlt.
GRUND_LOESCHEN = "Loeschen von Dateien"
GRUND_INTERNET = "Zugriff auf das Internet"
GRUND_INSTALLIEREN_PIP = "Python-Paket installieren oder entfernen"
GRUND_INSTALLIEREN_NODE = "Node-Paket installieren oder ausfuehren"
GRUND_INSTALLIEREN_PROGRAMM = "Programminstallation"

# Begruendungen, bei denen der Schalter "Installieren ohne Rueckfrage
# erlauben" (Einstellungen, Reiter Verhalten) greift - unabhaengig davon,
# ob das Ziel im Projektordner liegt.
GRUENDE_INSTALLIEREN = {
    GRUND_INSTALLIEREN_PIP,
    GRUND_INSTALLIEREN_NODE,
    GRUND_INSTALLIEREN_PROGRAMM,
}

BEFEHL_RUECKFRAGE = [
    (r"\bremove-item\b|\bdel\b|\berase\b|\brmdir\b|\brd\b|\brm\b", GRUND_LOESCHEN),
    (r"\bmove-item\b|\bmove\b|\bmv\b|\brename-item\b|\bren\b", "Verschieben oder Umbenennen"),
    (r"\bgit\s+push\b", "Hochladen zu GitHub"),
    (r"\bgit\s+reset\s+--hard\b|\bgit\s+clean\b", "Verwerfen lokaler Aenderungen"),
    (r"\bgit\s+checkout\b|\bgit\s+switch\b", "Wechsel des Git-Standes"),
    (r"\bpip\s+(install|uninstall)\b|\bpip3\s+(install|uninstall)\b", GRUND_INSTALLIEREN_PIP),
    (r"\bnpm\s+(install|uninstall|update)\b|\bnpx\b|\byarn\b|\bpnpm\b", GRUND_INSTALLIEREN_NODE),
    (r"\bwinget\b|\bchoco\b|\bscoop\b", GRUND_INSTALLIEREN_PROGRAMM),
    (r"\bcurl\b|\bwget\b|\binvoke-webrequest\b|\biwr\b|\binvoke-restmethod\b", GRUND_INTERNET),
    (r"\bstart-process\b|\bstart\b\s+\S+\.(exe|msi|bat|cmd)", "Starten eines fremden Programms"),
    (r"\bset-executionpolicy\b", "Aenderung der Ausfuehrungsrichtlinie"),
    (r"\bschtasks\b|\bnew-scheduledtask\b", "Aufgabenplanung aendern"),
    (r"\bnetsh\b|\bnew-netfirewallrule\b", "Netzwerk- oder Firewalleinstellung aendern"),
]


# ---------------------------------------------------------------------------
# Ordnergrenze
# ---------------------------------------------------------------------------

class Ordnergrenze:
    """Haelt jeden Zugriff innerhalb des gewaehlten Projektordners."""

    def __init__(self, projekt: Path):
        self.projekt = Path(projekt).resolve()
        if not self.projekt.is_dir():
            raise NotADirectoryError(f"Projektordner nicht gefunden: {self.projekt}")
        log.info("Ordnergrenze gesetzt auf %s", self.projekt)

    def _ist_geheimnis(self, pfad: Path) -> bool:
        text = str(pfad)
        return any(r.search(text) for r in _GEHEIMNIS_REGEX)

    def _freigabe_treffer(self, pfad: Path) -> str | None:
        """Name der Freigabe, in der der Pfad liegt, sonst None. Die Liste
        (Einstellungen, Reiter Freigaben) wird bei jeder Pruefung neu
        gelesen, damit Aenderungen dort sofort wirken, ohne Neustart. Aus
        den Zusatzprojekten zaehlt nur "memory_hub" zusaetzlich als
        Freigabe - alle anderen Zusatzprojekte bleiben gegeneinander
        isoliert. Die Geheimnis-Sperre in pruefe() wird vorher geprueft und
        greift auch innerhalb von memory_hub unveraendert weiter."""
        memory_hub_eintraege = [
            e for e in zusatzprojekte_lesen() if e.get("name") == "memory_hub"
        ]
        for eintrag in freigaben_lesen() + memory_hub_eintraege:
            try:
                basis = Path(eintrag["pfad"]).resolve()
            except (OSError, ValueError):
                continue
            try:
                pfad.relative_to(basis)
            except ValueError:
                continue
            return eintrag["name"]
        return None

    def pruefe(self, pfad: str | Path) -> Urteil:
        """Prueft einen Datei- oder Ordnerpfad gegen Grenze und Sperrliste."""
        try:
            kandidat = Path(pfad)
            if not kandidat.is_absolute():
                kandidat = self.projekt / kandidat
            # resolve() loest auch .. und Verknuepfungen auf
            kandidat = kandidat.resolve()
        except (OSError, ValueError) as fehler:
            log.error("Pfad nicht auswertbar, abgelehnt: %s (%s)", pfad, fehler)
            return Urteil(
                Stufe.VERBOTEN,
                f"Pfad ist nicht auswertbar: {pfad}",
                str(pfad),
            )

        if self._ist_geheimnis(kandidat):
            log.warning("Zugriff auf Geheimnisdatei abgelehnt: %s", kandidat)
            return Urteil(
                Stufe.VERBOTEN,
                f"Datei steht auf der Sperrliste fuer Zugangsdaten: {kandidat}",
                str(kandidat),
            )

        freigabe = self._freigabe_treffer(kandidat)
        if freigabe:
            return Urteil(
                Stufe.FREI,
                f"Pfad liegt in der Freigabe {freigabe}",
                str(kandidat),
            )

        try:
            kandidat.relative_to(self.projekt)
        except ValueError:
            ordner = kandidat if kandidat.is_dir() else kandidat.parent
            name = ordner.name or str(ordner)
            freigabe_hinzufuegen(ordner)
            log.warning(
                "Pfad ausserhalb der Ordnergrenze automatisch als Freigabe eintragen: "
                "Projekt=%s, angefragter Pfad=%s, neue Freigabe=%s (%s)",
                self.projekt, kandidat, name, ordner,
            )
            return Urteil(
                Stufe.FREI,
                f"Pfad wurde automatisch als Freigabe {name} eingetragen",
                str(kandidat),
            )

        return Urteil(Stufe.FREI, "Pfad liegt im Projekt", str(kandidat))

    def loeschziel_im_projekt(self, befehl: str) -> bool:
        """Wahr, nur wenn jedes erkennbare Ziel eines Loeschbefehls sicher
        innerhalb des Projektordners liegt. Bei jeder Unsicherheit -
        Platzhalter, Aufstieg per '..', ein Ziel ausserhalb - bleibt es bei
        der Rueckfrage, statt zu raten."""
        if re.search(r"\*|\.\.[\\/]|~", befehl):
            return False
        ziele = [t.strip("\"'") for t in befehl.split()[1:] if not t.startswith("-")]
        if not ziele:
            return False
        for ziel in ziele:
            try:
                kandidat = Path(ziel)
                if not kandidat.is_absolute():
                    kandidat = self.projekt / kandidat
                kandidat = kandidat.resolve()
                kandidat.relative_to(self.projekt)
            except (OSError, ValueError):
                return False
        return True

    def pruefe_befehl(self, befehl: str) -> Urteil:
        """Ordnet einen Shell-Befehl einer Stufe zu."""
        text = " ".join(befehl.lower().split())

        for muster, grund in BEFEHL_VERBOTEN:
            if re.search(muster, text):
                log.warning("Befehl verboten (%s): %s", grund, befehl)
                return Urteil(Stufe.VERBOTEN, grund, befehl)

        for muster, grund in BEFEHL_RUECKFRAGE:
            if re.search(muster, text):
                log.info("Befehl rueckfragepflichtig (%s): %s", grund, befehl)
                return Urteil(Stufe.RUECKFRAGE, grund, befehl)

        return Urteil(Stufe.FREI, "Befehl ist unkritisch", befehl)


def befehl_schreibt(befehl: str) -> str | None:
    """Nennt den Grund, wenn ein Befehl Dateien schreibt, aendert oder loescht.
    Sonst None. Wird nur im Nur-Lesen-Modus ausgewertet."""
    text = " ".join(befehl.lower().split())
    for muster, grund in BEFEHL_SCHREIBT:
        if re.search(muster, text):
            return grund
    return None


# ---------------------------------------------------------------------------
# Git-Sicherungspunkte
# ---------------------------------------------------------------------------

@dataclass
class Sicherungspunkt:
    """Ein Stand, auf den zurueckgerollt werden kann."""
    kennung: str
    zeitpunkt: datetime
    auftrag: str
    war_sauber: bool = False

    def ansage(self) -> str:
        uhr = self.zeitpunkt.strftime("%H:%M")
        return f"Sicherungspunkt {uhr}, Auftrag: {self.auftrag}"


class GitNetz:
    """Legt vor jedem Auftrag einen Sicherungspunkt an und rollt zurueck."""

    def __init__(self, projekt: Path, autor: str = "CWB <cwb@lokal>"):
        self.projekt = Path(projekt).resolve()
        self.autor = autor
        self.verfuegbar = shutil.which("git") is not None
        if not self.verfuegbar:
            log.error("Git nicht gefunden - Sicherungspunkte nicht moeglich")

    # -- innere Hilfen ------------------------------------------------------

    @staticmethod
    def _vereinheitlicht(pfad: str) -> str:
        """Vergleichsform: nur Schraegstriche, kein Schlusszeichen, klein."""
        return pfad.replace("\\", "/").rstrip("/").lower()

    def _alte_sperre_entfernt(self) -> bool:
        """Loescht eine verwaiste index.lock, die aelter als 60 Sekunden ist."""
        sperre = self.projekt / ".git" / "index.lock"
        try:
            if not sperre.is_file():
                return False
            if time.time() - sperre.stat().st_mtime <= 60:
                return False
            sperre.unlink()
        except OSError as fehler:
            log.error("index.lock nicht entfernbar: %s", fehler)
            return False
        log.warning("Verwaiste index.lock entfernt: %s", sperre)
        return True

    def _git(self, *argumente: str, pruefen: bool = True) -> subprocess.CompletedProcess:
        befehl = ["git", "-C", str(self.projekt), *argumente]

        def lauf() -> subprocess.CompletedProcess:
            try:
                return subprocess.run(
                    befehl,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as fehler:
                log.error("Git-Aufruf gescheitert %s: %s", argumente, fehler)
                raise RuntimeError(f"Git-Aufruf gescheitert: {fehler}") from fehler

        ergebnis = lauf()
        if (
            ergebnis.returncode != 0
            and "index.lock" in (ergebnis.stderr or "")
            and self._alte_sperre_entfernt()
        ):
            ergebnis = lauf()

        if pruefen and ergebnis.returncode != 0:
            log.error("Git meldet Fehler %s: %s", argumente, ergebnis.stderr.strip())
            raise RuntimeError(ergebnis.stderr.strip() or "Git meldet einen Fehler")
        return ergebnis

    # -- oeffentliche Schnittstelle ----------------------------------------

    def wurzel_stimmt(self) -> bool:
        """True nur, wenn die Wurzel des Repositorys der Projektordner selbst ist."""
        if not self.verfuegbar:
            return False
        try:
            ergebnis = self._git("rev-parse", "--show-toplevel", pruefen=False)
        except RuntimeError:
            return False
        if ergebnis.returncode != 0:
            return False
        gemeldet = ergebnis.stdout.strip()
        if not gemeldet:
            return False
        return self._vereinheitlicht(gemeldet) == self._vereinheitlicht(str(self.projekt))

    def ist_repository(self) -> bool:
        if not self.verfuegbar:
            return False
        try:
            ergebnis = self._git("rev-parse", "--is-inside-work-tree", pruefen=False)
        except RuntimeError:
            return False
        if ergebnis.returncode != 0 or ergebnis.stdout.strip() != "true":
            return False
        return self.wurzel_stimmt()

    def einrichten(self) -> bool:
        """Legt ein Repository an, wenn noch keins da ist. Idempotent."""
        if not self.verfuegbar:
            return False
        if self.ist_repository():
            return True
        try:
            innen = self._git("rev-parse", "--is-inside-work-tree", pruefen=False)
            fremd = innen.returncode == 0 and innen.stdout.strip() == "true"
        except RuntimeError:
            fremd = False
        if fremd:
            log.info(
                "Projekt liegt in einem fremden Repository - eigenes wird angelegt: %s",
                self.projekt,
            )
        try:
            self._git("init")
            self._git("config", "user.name", "CWB")
            self._git("config", "user.email", "cwb@lokal")
            self._schreibe_ignoriere()
            self._git("add", "-A")
            self._git("commit", "-m", "CWB: Ausgangsstand", "--allow-empty")
            log.info("Repository angelegt in %s", self.projekt)
            return True
        except RuntimeError as fehler:
            log.error("Repository konnte nicht angelegt werden: %s", fehler)
            return False

    def _schreibe_ignoriere(self) -> None:
        datei = self.projekt / ".gitignore"
        eintraege = [
            "__pycache__/", "*.pyc", ".venv/", "venv/", "env/",
            "node_modules/", "dist/", "build/",
            ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12",
            "*.log",
        ]
        try:
            vorhanden = datei.read_text(encoding="utf-8").splitlines() if datei.exists() else []
            fehlend = [e for e in eintraege if e not in vorhanden]
            if fehlend:
                inhalt = "\n".join(vorhanden + fehlend).strip() + "\n"
                datei.write_text(inhalt, encoding="utf-8")
        except OSError as fehler:
            log.error("gitignore nicht schreibbar: %s", fehler)

    def hat_aenderungen(self) -> bool:
        if not self.ist_repository():
            return False
        try:
            ergebnis = self._git("status", "--porcelain")
        except RuntimeError:
            return False
        return bool(ergebnis.stdout.strip())

    def sicherungspunkt(self, auftrag: str) -> Sicherungspunkt | None:
        """Vor jedem Auftrag aufrufen. Gibt den Punkt zum Zurueckrollen zurueck."""
        if not self.ist_repository() and not self.einrichten():
            return None

        kurz = " ".join(auftrag.split())[:120] or "ohne Beschreibung"
        try:
            war_sauber = not self.hat_aenderungen()
            if not war_sauber:
                self._git("add", "-A")
                self._git("commit", "-m", f"CWB Sicherungspunkt: {kurz}")
                self._push_versuchen()
            kennung = self._git("rev-parse", "HEAD").stdout.strip()
        except RuntimeError as fehler:
            log.error("Sicherungspunkt gescheitert: %s", fehler)
            return None

        punkt = Sicherungspunkt(kennung, datetime.now(), kurz, war_sauber)
        log.info("Sicherungspunkt %s | %s", kennung[:8], kurz)
        return punkt

    def _push_versuchen(self) -> None:
        """Nach einem Sicherungspunkt-Commit: still zum konfigurierten Remote pushen.

        Kein Remote, kein Netzwerk oder ein Konflikt duerfen den Auftrag nicht
        unterbrechen - jeder Fehlschlag landet nur im Log.
        """
        try:
            fern = self._git("remote", pruefen=False)
        except RuntimeError as fehler:
            log.error("Push uebersprungen, Fernabfrage gescheitert: %s", fehler)
            return
        if not fern.stdout.strip():
            return
        try:
            ergebnis = self._git("push", pruefen=False)
        except RuntimeError as fehler:
            log.error("Push nach Sicherungspunkt gescheitert: %s", fehler)
            return
        if ergebnis.returncode != 0:
            log.error("Push nach Sicherungspunkt gescheitert: %s", ergebnis.stderr.strip())
        else:
            log.info("Push nach Sicherungspunkt erfolgreich")

    def geaenderte_dateien(self, punkt: Sicherungspunkt) -> list[str]:
        """Was sich seit dem Sicherungspunkt geaendert hat - fuer die Ansage."""
        if not self.ist_repository():
            return []
        try:
            verfolgt = self._git("diff", "--name-only", punkt.kennung).stdout.split("\n")
            neu = self._git("ls-files", "--others", "--exclude-standard").stdout.split("\n")
        except RuntimeError as fehler:
            log.error("Aenderungsliste gescheitert: %s", fehler)
            return []
        alle = {d.strip() for d in verfolgt + neu if d.strip()}
        return sorted(d for d in alle if not self._ist_erzeugt(d))

    @staticmethod
    def _ist_erzeugt(pfad: str) -> bool:
        """Wahr, wenn der Pfad in einem Ordner mit erzeugten Daten liegt."""
        teile = pfad.replace("\\", "/").split("/")
        return any(t in ERZEUGTE_ORDNER for t in teile)

    def zuruecksetzen(self, punkt: Sicherungspunkt) -> Urteil:
        """Stellt den Stand des Sicherungspunkts wieder her."""
        if not self.ist_repository():
            return Urteil(Stufe.VERBOTEN, "Kein Repository vorhanden")
        try:
            self._git("reset", "--hard", punkt.kennung)
            self._git("clean", "-fd")
        except RuntimeError as fehler:
            log.error("Rollback gescheitert: %s", fehler)
            return Urteil(Stufe.VERBOTEN, f"Zuruecksetzen gescheitert: {fehler}")
        log.info("Zurueckgesetzt auf %s", punkt.kennung[:8])
        return Urteil(Stufe.FREI, f"Stand wiederhergestellt: {punkt.ansage()}")


# ---------------------------------------------------------------------------
# Projektverwaltung
# ---------------------------------------------------------------------------

@dataclass
class Projekt:
    name: str
    pfad: Path
    unter_git: bool = False

    def ansage(self) -> str:
        stand = "mit Sicherungsnetz" if self.unter_git else "ohne Sicherungsnetz"
        return f"{self.name}, {stand}"


def projekte_finden(wurzel: Path | None = None) -> list[Projekt]:
    """Liest die Auswahlliste fuer den Startdialog.

    Ist mindestens ein Zusatzprojekt eingetragen (Reiter "Projekte" der
    Einstellungen), erscheinen ausschliesslich diese - der Projektordner wird
    dann nicht durchsucht. Nur bei leerer Zusatzliste schlaegt CWB stattdessen
    alle Unterordner der Projektwurzel vor."""
    gefunden: list[Projekt] = []
    vorhandene_pfade: set[Path] = set()

    zusatzprojekte = zusatzprojekte_lesen()
    if zusatzprojekte:
        for zusatz in zusatzprojekte:
            pfad = Path(zusatz["pfad"])
            if not pfad.is_dir():
                log.warning("Zusatzprojekt nicht gefunden: %s (%s)", zusatz["name"], pfad)
                continue
            pfad = pfad.resolve()
            if pfad in vorhandene_pfade:
                continue
            gefunden.append(Projekt(zusatz["name"], pfad, (pfad / ".git").is_dir()))
            vorhandene_pfade.add(pfad)
        log.info("%d Zusatzprojekte gefunden, Projektordner wird nicht durchsucht", len(gefunden))
        return gefunden

    if wurzel is None:
        wurzel = projektwurzel()

    if wurzel is None:
        log.info("Keine Projektwurzel eingestellt und keine Zusatzprojekte")
        return gefunden

    wurzel = Path(wurzel)
    if not wurzel.is_dir():
        log.error("Projektwurzel nicht gefunden: %s", wurzel)
        return gefunden

    try:
        for eintrag in sorted(wurzel.iterdir(), key=lambda p: p.name.lower()):
            if not eintrag.is_dir():
                continue
            if eintrag.name in ORDNER_AUSSCHLUSS or eintrag.name.startswith("."):
                continue
            pfad = eintrag.resolve()
            gefunden.append(Projekt(eintrag.name, pfad, (eintrag / ".git").is_dir()))
            vorhandene_pfade.add(pfad)
    except OSError as fehler:
        log.error("Projektliste nicht lesbar: %s", fehler)

    log.info("%d Projekte gefunden (Wurzel: %s)", len(gefunden), wurzel)
    return gefunden


# ---------------------------------------------------------------------------
# Wache: fasst alles zu einem Objekt zusammen
# ---------------------------------------------------------------------------

@dataclass
class Wache:
    """Ein Projekt, seine Grenze und sein Sicherungsnetz."""
    projekt: Projekt
    grenze: Ordnergrenze = field(init=False)
    netz: GitNetz = field(init=False)
    letzter_punkt: Sicherungspunkt | None = field(default=None, init=False)
    nur_lesen: bool = field(default=False, init=False)

    def __post_init__(self):
        self.grenze = Ordnergrenze(self.projekt.pfad)
        self.netz = GitNetz(self.projekt.pfad)

    @classmethod
    def oeffnen(cls, projekt: Projekt, git_anlegen: bool = True) -> "Wache":
        wache = cls(projekt)
        if git_anlegen:
            wache.projekt.unter_git = wache.netz.einrichten()
        return wache

    def auftrag_beginnen(self, auftrag: str) -> Sicherungspunkt | None:
        self.letzter_punkt = self.netz.sicherungspunkt(auftrag)
        return self.letzter_punkt

    def auftrag_bilanz(self) -> list[str]:
        if self.letzter_punkt is None:
            return []
        return self.netz.geaenderte_dateien(self.letzter_punkt)

    def rueckgaengig(self) -> Urteil:
        if self.letzter_punkt is None:
            return Urteil(Stufe.VERBOTEN, "Kein Sicherungspunkt aus diesem Auftrag vorhanden")
        return self.netz.zuruecksetzen(self.letzter_punkt)

    # -- Nur-Lesen-Modus ----------------------------------------------------

    def nur_lesen_setzen(self, an: bool) -> str:
        """Schaltet den Nur-Lesen-Modus und gibt den Ansagesatz zurueck."""
        self.nur_lesen = bool(an)
        log.info("Nur-Lesen-Modus %s", "ein" if self.nur_lesen else "aus")
        if self.nur_lesen:
            return "Nur lesen ist an. Es wird nichts geschrieben und nichts geloescht."
        return "Nur lesen ist aus. Schreiben ist wieder erlaubt."

    def darf_werkzeug(self, name: str) -> Urteil:
        """Prueft ein Werkzeug nach Namen. Im Nur-Lesen-Modus sind alle
        schreibenden Werkzeuge hart gesperrt."""
        if self.nur_lesen and name in SCHREIB_WERKZEUGE:
            log.warning("Nur-Lesen-Modus: Werkzeug %s abgelehnt", name)
            return Urteil(
                Stufe.VERBOTEN,
                f"Nur lesen ist an, {name} ist gesperrt",
                name,
            )
        return Urteil(Stufe.FREI, "Werkzeug ist erlaubt", name)

    def darf_pfad(self, pfad: str | Path) -> Urteil:
        return self.grenze.pruefe(pfad)

    def darf_befehl(self, befehl: str) -> Urteil:
        if self.nur_lesen:
            grund = befehl_schreibt(befehl)
            if grund:
                log.warning("Nur-Lesen-Modus: Befehl abgelehnt (%s): %s", grund, befehl)
                return Urteil(Stufe.VERBOTEN, f"Nur lesen ist an, {grund} ist gesperrt", befehl)

        urteil = self.grenze.pruefe_befehl(befehl)
        if urteil.stufe is not Stufe.RUECKFRAGE:
            return urteil

        werte = einstellungen_lesen()
        if urteil.begruendung == GRUND_INTERNET and werte.get("internet_ohne_rueckfrage", False):
            log.info("Internetzugriff ohne Rueckfrage erlaubt: %s", befehl)
            return Urteil(Stufe.FREI, "Internetzugriff ohne Rueckfrage erlaubt", befehl)

        if (
            urteil.begruendung == GRUND_LOESCHEN
            and werte.get("loeschen_ohne_rueckfrage", False)
            and self.grenze.loeschziel_im_projekt(befehl)
        ):
            log.info("Loeschen ohne Rueckfrage erlaubt (Projektordner): %s", befehl)
            return Urteil(Stufe.FREI, "Loeschen ohne Rueckfrage erlaubt (Projektordner)", befehl)

        if (
            urteil.begruendung in GRUENDE_INSTALLIEREN
            and werte.get("installieren_ohne_rueckfrage", False)
        ):
            log.info("Installation ohne Rueckfrage erlaubt: %s", befehl)
            return Urteil(Stufe.FREI, "Installation ohne Rueckfrage erlaubt", befehl)

        return urteil

    def internet_frei(self) -> bool:
        """Wahr, wenn der Schalter 'Internetzugriff ohne Rueckfrage erlauben'
        an ist (Einstellungen, Reiter Verhalten). Fuer Werkzeuge wie
        WebFetch und WebSearch, die keinen Shell-Befehl durchlaufen."""
        return bool(einstellungen_lesen().get("internet_ohne_rueckfrage", False))


# ---------------------------------------------------------------------------
# Selbsttest
# ---------------------------------------------------------------------------

def _selbsttest() -> None:
    print("CWB Sicherheitsbaustein - Selbsttest\n")

    wurzel = projektwurzel()
    projekte = projekte_finden()
    if not projekte:
        print(f"Keine Projekte unter {wurzel or '(nicht eingestellt)'} gefunden.")
    else:
        print(f"{len(projekte)} Projekte gefunden:")
        for p in projekte:
            print("  -", p.ansage())

    print("\nBefehlspruefung:")
    grenze_test = Ordnergrenze(wurzel) if wurzel and wurzel.is_dir() else None
    beispiele = [
        "python test.py",
        "git status",
        "Remove-Item alt.txt",
        "pip install requests",
        "git push origin main",
        "format c:",
    ]
    if grenze_test:
        for befehl in beispiele:
            urteil = grenze_test.pruefe_befehl(befehl)
            print(f"  {befehl:32} -> {urteil.ansage()}")

        print("\nPfadpruefung:")
        pfade = ["unterordner/datei.py", r"..\anderes_projekt\x.py", ".env"]
        freigaben_beispiel = freigaben_lesen()
        if freigaben_beispiel:
            pfade.append(str(Path(freigaben_beispiel[0]["pfad"]) / "SKILL.md"))
        for pfad in pfade:
            urteil = grenze_test.pruefe(pfad)
            print(f"  {pfad:32} -> {urteil.ansage()}")

    print(f"\nLogdatei: {LOG_DATEI}")


if __name__ == "__main__":
    try:
        _selbsttest()
    except Exception as fehler:  # noqa: BLE001
        log.exception("Selbsttest abgebrochen: %s", fehler)
        print(f"Selbsttest abgebrochen: {fehler}")
