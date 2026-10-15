"""Memory Hub - Aufraeummodus.

Geht den Bestand eines Projekts durch wie ein Kind, das abends sein Zimmer
aufraeumt, und macht Vorschlaege:

  A. Inhaltsleere Eintraege   - Meldungen ueber das Schreiben selbst
                                ("Eingetragen.", "Eintrag ergaenzt.")
  B. Doppelungen              - zwei Eintraege mit derselben Aussage,
                                der ausfuehrlichere bleibt
  C. Offene Punkte            - [OFFEN]-Vermerke, die laut spaeterem Eintrag
                                behoben sind -> als erledigt markieren
  D. Ueberholte Eintraege     - ein spaeterer Eintrag beschreibt dieselbe
                                Sache anders -> nur zur Kenntnis

Nichts wird blind geloescht: analysieren() liefert einen Bericht zum
Vorlesen, ausfuehren() setzt nur ausdruecklich genannte Nummern um und
legt jeden entfernten Eintrag vorher im Papierkorb ab (JSONL neben der
Datenbank), aus dem wiederherstellen() ihn zurueckholt. Angeheftete
Eintraege werden nie angefasst. Im Zweifel: behalten.

Nutzung:
  python aufraeumen.py hausgemacht                   Bericht, nichts aendern
  python aufraeumen.py hausgemacht --loeschen 1160,1216 --erledigt 1199
  python aufraeumen.py --wiederherstellen 1160
"""

import difflib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory_db as db  # noqa: E402

log = logging.getLogger("cwb.aufraeumen")

PAPIERKORB = os.path.join(os.path.dirname(db.DB_PATH), "aufraeum_papierkorb.jsonl")

# Sicherheitsstufen: "hoch" darf auf Zuruf weg, "mittel" soll Robert hoeren
# und bestaetigen, "niedrig" ist nur ein Hinweis ohne Vorschlag.
HOCH, MITTEL, NIEDRIG = "hoch", "mittel", "niedrig"

# Grenzwerte, bewusst konservativ
LEER_MAX_SICHER = 150     # Meta-Meldung bis hierhin: sicher leer
LEER_MAX_PRUEFEN = 260    # bis hierhin: leer, aber zur Pruefung
DOPPEL_SICHER_RATIO = 0.90
DOPPEL_SICHER_JACCARD = 0.80
DOPPEL_VERDACHT_JACCARD = 0.50
DOPPEL_ENTHALTEN = 0.80   # Woerter des kuerzeren im laengeren enthalten
OFFEN_MIN_ANTEIL = 0.40   # Anteil gemeinsamer Schluesselwoerter
OFFEN_MIN_WOERTER = 3
UEBERHOLT_JACCARD_MIN = 0.20   # nur Hinweis, darum lockerer als bei Doppelungen
UEBERHOLT_ENTHALTEN = 0.50

META_MUSTER = [
    r"^(eingetragen|erg[aä]nzt|notiert|gespeichert|erledigt)\.?$",
    r"^eintrag (im tagebuch )?(erg[aä]nzt|geschrieben|nachgetragen|gesetzt)\.?$",
    r"^eintrag (in|im) .{0,40}(geschrieben|erg[aä]nzt|nachgetragen)",
    r"zusammenfassung (steht|stand) (bereits|schon)",
    r"steht (bereits|schon) im tagebuch",
    r"keine (neuen )?offenen punkte",
    r"nichts (zu erg[aä]nzen|nachzutragen)",
    r"keine erg[aä]nzung n[oö]tig",
    r"^(nur|lediglich) (den|die|das) .{0,40}(nachgetragen|erg[aä]nzt)",
]

ERLEDIGT_WOERTER = {
    "behoben", "erledigt", "umgesetzt", "gebaut", "eingebaut", "entfernt",
    "abgeschlossen", "repariert", "korrigiert", "bereinigt", "ersetzt",
    "geloest", "gelöst", "zusammengefuehrt", "zusammengeführt", "fertiggestellt",
    "angelegt", "eingerichtet", "beantwortet", "geklaert", "geklärt",
    "umgestellt", "ausgeweitet", "vereinheitlicht", "zurueckgesetzt",
}

STOPP = {
    "aber", "alle", "allen", "aller", "alles", "also", "auch", "beim", "bereits",
    "bewusst", "damit", "dann", "dass", "denselben", "derselbe", "dieselbe",
    "diese", "diesem", "diesen", "dieser", "dieses", "dort", "durch", "eine",
    "einem", "einen", "einer", "eines", "eintrag", "erst", "etwa", "haben",
    "hier", "ihre", "ihren", "immer", "jetzt", "kann", "kein", "keine", "mehr",
    "nach", "nicht", "noch", "nur", "oder", "ohne", "robert", "roberts", "schon",
    "sein", "seine", "seit", "sich", "sind", "sowie", "statt", "steht", "stehen",
    "tagebuch", "ueber", "über", "unter", "weil", "weiterhin", "wenn", "werden",
    "wird", "wurde", "wurden", "zwei", "drei", "vier", "beide", "beiden",
    "gefunden", "geprueft", "geprüft", "offen", "ausstehend", "steht", "aus",
    "laut", "sowohl", "waehrend", "während", "bisher", "spaeter", "später",
    "dabei", "davon", "dafuer", "dafür", "darum", "sonst", "somit", "danach",
}


# ------------------------------------------------------------------ Hilfen

def _norm(text):
    t = re.sub(r"\[(OFFEN|ERLEDIGT)[^\]]*\]\s*", "", text or "", flags=re.IGNORECASE)
    t = t.lower().replace("ß", "ss")
    t = re.sub(r"[`\"„“‚‘'»«()\[\]{}<>:;,.!?/\\|*_#\-–—]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _woerter(text):
    """Bedeutungstragende Woerter: mindestens 4 Zeichen, keine Stoppwoerter."""
    return {w for w in re.findall(r"\w+", _norm(text)) if len(w) >= 4 and w not in STOPP}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _ist_offen(text):
    return "[OFFEN]" in (text or "").upper()


def _kurz(text, n=110):
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _meta_treffer(text):
    n = _norm(text)
    return any(re.search(m, n) for m in META_MUSTER)


# ------------------------------------------------------------ Datenklassen

@dataclass
class Vorschlag:
    nummer: int
    art: str            # "leer" | "doppelt" | "offen_erledigt" | "ueberholt"
    stufe: str          # HOCH | MITTEL | NIEDRIG
    aktion: str         # "loeschen" | "erledigt" | "keine"
    ziel: dict          # der betroffene Eintrag
    grund: str
    bezug: dict | None = None   # der Eintrag, der bleibt / der aufloest / der ueberholt

    def zeile(self):
        was = {"loeschen": "entfernen", "erledigt": "als erledigt markieren",
               "keine": "nur zur Kenntnis"}[self.aktion]
        s = "%d. #%d (%s) %s. %s. Text: „%s“" % (
            self.nummer, self.ziel["id"], self.ziel["category"], was, self.grund,
            _kurz(self.ziel["content"]))
        if self.bezug:
            s += " — Bezug #%d: „%s“" % (self.bezug["id"], _kurz(self.bezug["content"], 90))
        return s


@dataclass
class Bericht:
    projekt: str
    geprueft: int
    vorschlaege: list = field(default_factory=list)

    def nach_art(self, art):
        return [v for v in self.vorschlaege if v.art == art]

    def text(self):
        z = ["Aufräumbericht %s: %d Einträge geprüft, %d Vorschläge. Vorschau, nichts geändert."
             % (self.projekt, self.geprueft, len(self.vorschlaege)), ""]
        abschnitte = [
            ("leer", "A. Inhaltsleer – Meldungen über das Schreiben, ohne eigene Aussage. Vorschlag: entfernen."),
            ("doppelt", "B. Doppelungen – dieselbe Aussage zweimal. Vorschlag: den kürzeren entfernen, der ausführlichere bleibt."),
            ("offen_erledigt", "C. Offene Punkte, laut späterem Eintrag vermutlich erledigt. Vorschlag: als erledigt markieren."),
            ("ueberholt", "D. Möglicherweise überholt – ein späterer Eintrag beschreibt dieselbe Sache. Kein Vorschlag, nur zur Kenntnis."),
        ]
        for art, titel in abschnitte:
            gruppe = self.nach_art(art)
            if not gruppe:
                continue
            z.append(titel)
            for v in gruppe:
                stufe = "" if v.stufe == HOCH else " [%s – bitte prüfen]" % v.stufe
                z.append("  " + v.zeile() + stufe)
            z.append("")
        loeschen = [v.ziel["id"] for v in self.vorschlaege if v.aktion == "loeschen"]
        erledigt = [v.ziel["id"] for v in self.vorschlaege if v.aktion == "erledigt"]
        if loeschen or erledigt:
            z.append("Zum Ausführen alle oder einzelne Nummern nennen. Vorgeschlagen:")
            if loeschen:
                z.append("  löschen: %s" % ",".join(str(i) for i in loeschen))
            if erledigt:
                z.append("  erledigt: %s" % ",".join(str(i) for i in erledigt))
            z.append("Entferntes landet im Papierkorb %s und lässt sich zurückholen." % PAPIERKORB)
        else:
            z.append("Nichts aufzuräumen – das Zimmer ist ordentlich.")
        return "\n".join(z)


# ---------------------------------------------------------------- Analyse

def analysieren(projekt):
    """Prueft den Bestand eines Projekts und liefert einen Bericht. Aendert nichts."""
    eintraege = sorted(db.list_memories(project=projekt, limit=5000), key=lambda e: e["id"])
    bericht = Bericht(projekt=projekt, geprueft=len(eintraege))
    frei = [e for e in eintraege if not e.get("pinned")]
    weg = set()      # ids, die schon einen Loesch-Vorschlag haben
    nr = [0]

    def neu(art, stufe, aktion, ziel, grund, bezug=None):
        nr[0] += 1
        bericht.vorschlaege.append(Vorschlag(nr[0], art, stufe, aktion, ziel, grund, bezug))

    # A. Inhaltsleer
    for e in frei:
        text = e["content"]
        if not _meta_treffer(text):
            continue
        laenge = len(text.strip())
        if laenge <= LEER_MAX_SICHER:
            neu("leer", HOCH, "loeschen", e, "Meldung über das Schreiben selbst, kein Inhalt")
            weg.add(e["id"])
        elif laenge <= LEER_MAX_PRUEFEN:
            neu("leer", MITTEL, "loeschen", e, "Meldung über das Schreiben, enthält aber einen Nebensatz")
            weg.add(e["id"])

    # Vorberechnung fuer B-D
    kandidaten = [e for e in frei if e["id"] not in weg]
    norm = {e["id"]: _norm(e["content"]) for e in kandidaten}
    woerter = {e["id"]: _woerter(e["content"]) for e in kandidaten}

    # B. Doppelungen (aelter vs. neuer)
    for i, a in enumerate(kandidaten):
        if a["id"] in weg:
            continue
        for b in kandidaten[i + 1:]:
            if b["id"] in weg or a["id"] in weg:
                continue
            wa, wb = woerter[a["id"]], woerter[b["id"]]
            jac = _jaccard(wa, wb)
            if jac < 0.3:
                continue
            ratio = difflib.SequenceMatcher(None, norm[a["id"]], norm[b["id"]]).ratio()
            kurz, lang = (a, b) if len(a["content"]) <= len(b["content"]) else (b, a)
            if ratio >= DOPPEL_SICHER_RATIO or jac >= DOPPEL_SICHER_JACCARD:
                neu("doppelt", HOCH, "loeschen", kurz,
                    "%d %% gleicher Text, #%d ist ausführlicher (%d statt %d Zeichen)"
                    % (round(ratio * 100), lang["id"], len(lang["content"]), len(kurz["content"])),
                    bezug=lang)
                weg.add(kurz["id"])
                continue
            wk, wl = woerter[kurz["id"]], woerter[lang["id"]]
            enthalten = len(wk & wl) / len(wk) if wk else 0.0
            if jac >= DOPPEL_VERDACHT_JACCARD or (
                    enthalten >= DOPPEL_ENTHALTEN and len(kurz["content"]) <= 0.7 * len(lang["content"])):
                # Ein [OFFEN]-Punkt neben seiner ausfuehrlichen Beschreibung ist
                # keine Doppelung, sondern Absicht -> ueberspringen
                if _ist_offen(kurz["content"]) != _ist_offen(lang["content"]):
                    continue
                neu("doppelt", MITTEL, "loeschen", kurz,
                    "%d %% gemeinsame Schlüsselwörter, #%d sagt dasselbe ausführlicher"
                    % (round(max(jac, enthalten) * 100), lang["id"]), bezug=lang)
                weg.add(kurz["id"])

    # C. [OFFEN], laut spaeterem Eintrag erledigt
    for o in kandidaten:
        if o["id"] in weg or not _ist_offen(o["content"]):
            continue
        wo = woerter[o["id"]]
        if len(wo) < OFFEN_MIN_WOERTER:
            continue
        bester, beste_quote = None, 0.0
        for s in kandidaten:
            if s["id"] <= o["id"] or s["id"] in weg or _ist_offen(s["content"]):
                continue
            ws = woerter[s["id"]]
            gemeinsam = wo & ws
            quote = len(gemeinsam) / len(wo)
            # Drei Wege zum Treffer: viele gemeinsame Woerter bei langem
            # Vermerk, oder ein hoher Anteil bei kurzem Vermerk. Immer nur,
            # wenn der spaetere Eintrag von Erledigung spricht.
            passt = (len(gemeinsam) >= 5 and quote >= 0.25) \
                or (len(gemeinsam) >= OFFEN_MIN_WOERTER and quote >= OFFEN_MIN_ANTEIL) \
                or (len(gemeinsam) >= 2 and quote >= 0.6 and len(wo) <= 4)
            if passt and (ws & ERLEDIGT_WOERTER) and quote > beste_quote:
                bester, beste_quote = s, quote
        if bester:
            neu("offen_erledigt", MITTEL, "erledigt", o,
                "%d %% der Schlüsselwörter tauchen im späteren Eintrag #%d auf, der von Erledigung spricht"
                % (round(beste_quote * 100), bester["id"]), bezug=bester)

    # D. Ueberholt oder Tagebuch-Wiederholung (nur Hinweis). Typischer Fall:
    # dieselbe Erkenntnis einmal als Entscheidung, einmal als Tagebuch-Notiz
    # vom selben Tag -- die Notiz traegt meist nur "Build lief" zusaetzlich.
    schon = {v.ziel["id"] for v in bericht.vorschlaege}
    for i, a in enumerate(kandidaten):
        if a["id"] in weg or a["id"] in schon or _ist_offen(a["content"]):
            continue
        bester, beste = None, 0.0
        for b in kandidaten[i + 1:]:
            if b["id"] in weg or b["id"] in schon or _ist_offen(b["content"]):
                continue
            wa, wb = woerter[a["id"]], woerter[b["id"]]
            jac = _jaccard(wa, wb)
            kleiner = wa if len(wa) <= len(wb) else wb
            enthalten = len(wa & wb) / len(kleiner) if kleiner else 0.0
            if jac >= UEBERHOLT_JACCARD_MIN and enthalten >= UEBERHOLT_ENTHALTEN and enthalten > beste:
                bester, beste = b, enthalten
        if bester:
            # Der kuerzere ist der Kandidat fuers Wegraeumen, egal wer aelter ist
            kurz, lang = (a, bester) if len(a["content"]) <= len(bester["content"]) else (bester, a)
            if kurz["category"] == "Notiz" and lang["category"] != "Notiz":
                grund = "Tagebuch-Notiz wiederholt vermutlich die %s #%d (%d %% der Wörter dort enthalten)" % (
                    lang["category"], lang["id"], round(beste * 100))
            else:
                grund = "%d %% der Wörter auch in #%d – derselbe Gegenstand, anders beschrieben" % (
                    round(beste * 100), lang["id"])
            neu("ueberholt", NIEDRIG, "keine", kurz, grund, bezug=lang)
            schon.add(kurz["id"]); schon.add(lang["id"])

    log.info("Aufräumanalyse %s: %d Einträge, %d Vorschläge", projekt, len(eintraege), len(bericht.vorschlaege))
    return bericht


# ------------------------------------------------------------- Ausfuehren

def _in_papierkorb(eintrag, grund):
    try:
        os.makedirs(os.path.dirname(PAPIERKORB), exist_ok=True)
        with open(PAPIERKORB, "a", encoding="utf-8") as f:
            f.write(json.dumps({"entfernt_am": db._now(), "grund": grund, **eintrag},
                               ensure_ascii=False) + "\n")
        return True
    except OSError as fehler:
        log.error("Papierkorb nicht schreibbar: %s", fehler)
        return False


def ausfuehren(projekt, loeschen=(), erledigt=(), grund="Aufräummodus"):
    """Setzt genannte Vorschlaege um. Nur Eintraege des Projekts, nie angeheftete.
    Jeder geloeschte Eintrag wandert vorher in den Papierkorb."""
    meldungen = []
    for mid in loeschen:
        e = db.get_memory(int(mid))
        if not e:
            meldungen.append("#%s gibt es nicht." % mid); continue
        if e["project"] != projekt:
            meldungen.append("#%s gehört zu %s, nicht zu %s – übersprungen." % (mid, e["project"], projekt)); continue
        if e.get("pinned"):
            meldungen.append("#%s ist angeheftet – übersprungen." % mid); continue
        if not _in_papierkorb(e, grund):
            meldungen.append("#%s nicht gelöscht: Papierkorb nicht schreibbar." % mid); continue
        db.delete_memory(e["id"])
        meldungen.append("#%s entfernt (im Papierkorb)." % mid)
    for mid in erledigt:
        e = db.get_memory(int(mid))
        if not e or e["project"] != projekt:
            meldungen.append("#%s nicht gefunden oder falsches Projekt." % mid); continue
        if not _ist_offen(e["content"]):
            meldungen.append("#%s ist kein offener Punkt." % mid); continue
        neu = re.sub(r"\[OFFEN\]\s*", "[ERLEDIGT %s] " % db._now()[:10], e["content"], count=1, flags=re.IGNORECASE)
        db.update_memory(e["id"], content=neu)
        meldungen.append("#%s als erledigt markiert." % mid)
    log.info("Aufräumen %s: %d gelöscht, %d erledigt", projekt, len(loeschen), len(erledigt))
    return "\n".join(meldungen) if meldungen else "Nichts angegeben, nichts geändert."


def papierkorb_lesen():
    if not os.path.exists(PAPIERKORB):
        return []
    aus = []
    with open(PAPIERKORB, encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if zeile:
                try:
                    aus.append(json.loads(zeile))
                except json.JSONDecodeError:
                    log.warning("Papierkorb-Zeile unlesbar: %s", zeile[:80])
    return aus


def wiederherstellen(ids):
    """Holt geloeschte Eintraege aus dem Papierkorb zurueck (neue Nummer, alter Text)."""
    korb = papierkorb_lesen()
    meldungen = []
    for mid in ids:
        treffer = [k for k in korb if int(k.get("id", -1)) == int(mid)]
        if not treffer:
            meldungen.append("#%s ist nicht im Papierkorb." % mid); continue
        k = treffer[-1]
        neu = db.add_memory(k["content"], category=k.get("category", "Notiz"),
                            project=k.get("project", db.GLOBAL), source=k.get("source", "manuell"),
                            pinned=k.get("pinned", 0))
        meldungen.append("#%s wiederhergestellt als #%s." % (mid, neu))
    return "\n".join(meldungen) if meldungen else "Nichts angegeben."


# ------------------------------------------------------------------ CLI

def _ids(text):
    return [int(x) for x in re.findall(r"\d+", text or "")]


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description="Memory Hub aufräumen")
    p.add_argument("projekt", nargs="?", help="Projektname")
    p.add_argument("--loeschen", help="Eintragsnummern, kommagetrennt")
    p.add_argument("--erledigt", help="Eintragsnummern, kommagetrennt")
    p.add_argument("--wiederherstellen", help="Eintragsnummern aus dem Papierkorb")
    a = p.parse_args(argv)
    db.init_db()
    if a.wiederherstellen:
        print(wiederherstellen(_ids(a.wiederherstellen))); return
    if not a.projekt:
        p.error("Projektname fehlt.")
    if a.loeschen or a.erledigt:
        print(ausfuehren(a.projekt, _ids(a.loeschen), _ids(a.erledigt))); return
    print(analysieren(a.projekt).text())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main(sys.argv[1:])
