# cli.py — Kommandozeile fuer den Code-Index, ein Projektordner pro Aufruf.
# Keine feste Projektliste: CWB ruft das mit dem gerade offenen Projektpfad
# auf, egal ob der schon einmal gesehen wurde oder brandneu ist.
import argparse
import sys
import time
from pathlib import Path

import indexer


def _drucken(zeile: str) -> None:
    print(zeile)
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Code-Index fuer einen Projektordner (ChromaDB, lokal)")
    parser.add_argument("projektpfad", help="Absoluter Pfad des Projekts")
    parser.add_argument("--status", action="store_true", help="Nur Chunk-Zahl anzeigen, nicht indizieren")
    parser.add_argument("--voll", action="store_true",
                         help="Vorhandenes Manifest ignorieren und alles neu einlesen")
    args = parser.parse_args()

    pfad = str(Path(args.projektpfad))

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
