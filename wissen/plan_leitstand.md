# Vorhaben "Leitstand" (Block 72)

Entscheidung von Robert vom 01.10.2026: nachts oder wenn Robert nicht da ist,
übernimmt Leitstand die Rolle der KI im Chat, die nicht selbstständig auf
Berichte reagieren darf. Chat und Claude Code bleiben unverändert im
Max-Abo; Leitstand fragt für die Weiter/Wiederholen/Stopp-Entscheidung ein
eigenes, separat abgerechnetes Modell (Gemini).

## Ablauf

1. Abends legt die KI im Chat über die Brücke einen Nachtplan ab:
   `<Projekt>/wissen/nachtplan.md` mit nummerierten Schritten (Ziel,
   Prüfkriterium, Haltepunkte, an denen Robert entscheiden muss) und einem
   Abschnitt "Grenzen".
2. Leitstand an (Schalter in F12 → Leitstand, Kachel "Leitstand",
   Umschalt+F9; ab Werk aus): nach jedem abgeschlossenen `#CODE#`-Auftrag
   eines Projekts mit `nachtplan.md` liest `core/fenster.py`
   (`_leitstand_nach_auftrag`) den Bericht, `nachtplan.md` und
   `wissen/offen.md` und fragt über `core/leitstand.py` Gemini. Antwort in
   festem JSON: `{"entscheidung": "weiter"|"wiederholen"|"stopp", "schritt":
   N, "auftrag": "<Text für Claude Code>", "grund": "<ein Satz>"}`.
3. Bei "weiter" oder "wiederholen" legt `core/fenster.py` einen
   `#CODE#`-Block mit Blocknummer (`core.bloecke.naechste_block_nummer`) und
   Zeile "Projekt: X" über `core.eingangsordner.ablegen()` ab (Quelle
   `leitstand`, `core.leitstand.QUELLE_LEITSTAND`); er läuft danach wie jeder
   andere Eingangsordner-Auftrag, inklusive Kontingent-Warten und
   automatischem Projektwechsel.
4. Bei "stopp", einem Haltepunkt, erledigtem Plan oder einer Grenze: anhalten
   (`_leitstand_anhalten`) und `<Projekt>/wissen/nachtbericht.md` schreiben
   (Zeit, je Schritt ein Satz Ergebnis, Haltgrund). Ist die Brücke an, wird
   er zusätzlich hochgeladen (`core.bruecke.nachtbericht_hochladen`,
   `NachtberichtFaden`) - der Connector-Dienst (Projekt max-friends) braucht
   dafür noch den Endpunkt `/nachtbericht`, der dort bislang nicht existiert
   (gleiche Lage wie B2 bei der Brücke: Client-Seite ist fertig, der Server
   im anderen Projekt muss noch nachziehen).

Eine neue `nachtplan.md` (anderer Zeitstempel der Datei) hebt einen
gemerkten Haltepunkt wieder auf - `core.leitstand.Zustand.angehalten`
schlüsselt nach Projekt und `Path.stat().st_mtime` des Plans, nicht nach
Tag, damit ein neuer Plan am selben Tag sofort wieder läuft.

## Grenzen

Fest eingebaut, in F12 → Leitstand änderbar (Aufträge pro Nacht,
Wiederholungen je Schritt, Zeitlimit je Gemini-Aufruf):

- höchstens `leitstand_max_auftraege` (ab Werk 12) Leitstand-Aufträge pro
  Nacht (`core.leitstand.Zustand.anzahl_auftraege`, täglich zurückgesetzt).
- höchstens `leitstand_max_wiederholungen` (ab Werk 2) Wiederholungen je
  Schritt (`Zustand.wiederholungen`, Schlüssel `"<Projekt>::<Schritt>"`).
- nur `#CODE#`: Leitstand baut den Block immer selbst
  (`core.leitstand.codeblock_bauen`); zusätzlich prüft
  `markierung_verboten`, ob der von Gemini gelieferte Auftragstext selbst
  `#RUN#`/`#ADMIN#`/`#BILD#` enthält, und hält dann an.
- Stopp nach `MAX_FEHLSCHLAEGE_IN_FOLGE` (fest 2) Fehlschlägen hintereinander
  (`bilanz.get("fehler")` am gerade beendeten Auftrag).
- Stopp, wenn eine geänderte Datei außerhalb des Projektordners läge
  (`core.leitstand.aenderung_ausserhalb`) - prüft die von
  `core.sicherheit.Wache.auftrag_bilanz()` gemeldeten (Git-Diff-)Pfade; eine
  Freigabe außerhalb des Projekts (`core/pfade.py`, `freigaben_lesen`)
  erlaubt `core.sicherheit.Ordnergrenze` bewusst ohne Rückfrage und
  außerhalb jedes Git-Diffs - eine solche Änderung sieht diese Grenze
  grundsätzlich nicht, das ist eine bekannte Lücke, keine vollständige
  Sicherung.
- Zeitlimit je Gemini-Aufruf (`leitstand_zeitlimit_sekunden`, ab Werk 30 s).
- Protokoll jedes Aufrufs ohne Schlüssel: `core/leitstand.py` loggt nur
  Zeichenlängen und das Ergebnis (`entscheidung`, `schritt`), nie den vollen
  Inhalt von Plan, offenen Punkten oder Bericht, nie den Gemini-Schlüssel.

Gemini bekommt nur Nachtplan, `offen.md` und den Bericht des letzten
Schritts - keine Code-Dateien, keine Einkaufs-, Gesundheits- oder
Profildaten.

## Schlüssel

`%LOCALAPPDATA%\CWB\leitstand_zugang.txt` (`core/pfade.py`,
`LEITSTAND_ZUGANG_DATEI`), Zeile `gemini_api_key=...` - wie beim PC-Token
der Brücke nie geloggt, nie angezeigt, nicht in Git. Fehlt er, sagt CWB
"Kein Gemini-Schlüssel hinterlegt." und hält sofort an, sobald ein
Nachtplan-Auftrag ihn bräuchte.

## Modell

`gemini-3.5-flash-lite` (ai.google.dev/gemini-api/docs/models, Stand
01.10.2026: "vorherige Generation" des Flash-Lite-Modells; für neue Projekte
rät die Dokumentation zu 3.5 Flash-Lite oder 3.8 Flash - für eine reine
Weiter/Wiederholen/Stopp-Entscheidung reicht 3.5 Flash-Lite). Reiner
REST-Aufruf über `requests` (wie `core/bruecke.py`), keine eigene
SDK-Abhängigkeit. Mit dem echten Schlüssel aus `leitstand_zugang.txt`
gegengeprüft: Verbindungstest ("Antworte mit OK") und ein JSON-Testaufruf im
Entscheidungsschema liefen beide über die echte REST-Schnittstelle korrekt.

## Zustand

`%LOCALAPPDATA%\CWB\leitstand_zustand.json` (`core/pfade.py`,
`LEITSTAND_ZUSTAND_DATEI`) - Laufzeitstand, keine Einstellung: Zähler der
Nacht, Wiederholungen je Schritt, Haltepunkte je Projekt, der bisherige
Verlauf für den nächsten Nachtbericht. Ein anderer Kalendertag setzt alles
zurück (`core.leitstand.zustand_lesen`).

## Noch offen

- Der Connector-Dienst (Projekt max-friends) kennt den Endpunkt
  `/nachtbericht` noch nicht - der Client-Aufruf (`core/bruecke.py`,
  `nachtbericht_hochladen`) scheitert bis dahin still und bleibt nur im Log.
- Kein echter nächtlicher Testlauf mit einem wirklichen `nachtplan.md` und
  mehreren aufeinanderfolgenden Leitstand-Aufträgen im laufenden Fenster -
  geprüft wurden die reinen Funktionen (`core/test_leitstand.py`,
  `core/test_bloecke.py`) sowie ein echter, harmloser Gemini-Aufruf als
  Verbindungstest.
