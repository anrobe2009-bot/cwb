# cli.py — Kommandozeile fuer den Code-Index, ein Projektordner pro Aufruf.
# Keine feste Projektliste: CWB ruft das mit dem gerade offenen Projektpfad
# auf, egal ob der schon einmal gesehen wurde oder brandneu ist.
#
# --suche ist der zweite Aufrufweg neben dem Indizieren: core/wissen.py
# (_code_index_suchen) startet DAFUER einen eigenen Unterprozess statt
# indexer.py (chromadb/pyarrow/sentence-transformers/torch) in den CWB-
# Prozess selbst zu importieren - ein nativer Absturz dort (0xc0000005 in
# pyarrow\arrow.dll, belegt am 07.10.2026) beendete bisher CWB komplett,
# an jedem Python-Fehlernetz vorbei. Hier abstuerzen darf dieser kurzlebige
# Unterprozess dagegen gefahrlos: core/wissen.py wertet nur Rueckgabewert
# und Zeitlimit aus.
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Noetig, weil core/sitzung.py diese Datei per sys.executable als Unterprozess
# startet: das eingebettete Python der installierten Fassung liest seinen
# Suchpfad ausschliesslich aus pythonXXX._pth und haengt dabei - anders als
# ein normaler Python-Start - den Ordner des Skripts selbst nicht an
# sys.path, wodurch "import indexer" mit ModuleNotFoundError scheitert
# (gleiches Muster wie mcp_server.py).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import indexer  # noqa: E402


def _drucken(zeile: str) -> None:
    print(zeile)
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Code-Index fuer einen Projektordner (ChromaDB, lokal)")
    parser.add_argument("projektpfad", help="Absoluter Pfad des Projekts")
    parser.add_argument("--status", action="store_true", help="Nur Chunk-Zahl anzeigen, nicht indizieren")
    parser.add_argument("--voll", action="store_true",
                         help="Vorhandenes Manifest ignorieren und alles neu einlesen")
    parser.add_argument("--suche", metavar="FRAGE",
                         help="Nur suchen (kein Indizieren): Treffer als JSON auf stdout")
    parser.add_argument("--anzahl", type=int, default=5, help="Hoechstzahl Treffer bei --suche")
    args = parser.parse_args()

    pfad = str(Path(args.projektpfad))

    if args.suche is not None:
        # Keine Druckausgabe ausser der einen JSON-Zeile: core/wissen.py
        # liest ausschliesslich stdout und parst es als JSON.
        treffer = indexer.search(pfad, args.suche, n_results=args.anzahl)
        print(json.dumps(treffer, ensure_ascii=False))
        return

    if args.status:
        stats = indexer.get_collection_stats(pfad)
        _drucken(f"{stats.get('chunks', 0)} Chunks ({pfad})")
        return

    start = time.time()
    stats = indexer.index_aktualisieren(pfad, log_fn=_drucken, voll=args.voll)
    dauer = time.time() - start

    grund = stats.get("uebersprungen_grund")
    if grund:
        _drucken(f"uebersprungen ({grund}), {dauer:.2f}s")
        return
    if "error" in stats:
        _drucken(f"[FEHLER] {stats['error']}")
        return

    _drucken(
        f"{stats.get('files', 0)} Dateien, {stats.get('chunks', 0)} Chunks, "
        f"{stats.get('removed', 0)} entfernt, {stats.get('skipped', 0)} uebersprungen, "
        f"{stats.get('geprueft', 0)} geprueft, {dauer:.2f}s"
    )


if __name__ == "__main__":
    main()
