# Vorhaben "Leitstand" (Block 72/73)

Entscheidung von Robert vom 01.10.2026: nachts oder wenn Robert nicht da ist,
übernimmt Leitstand die Rolle der KI im Chat, die nicht selbstständig auf
Berichte reagieren darf. Chat und Claude Code bleiben unverändert im
Max-Abo; Leitstand fragt für die Weiter/Wiederholen/Stopp-Entscheidung ein
eigenes, separat abgerechnetes Modell - wählbar zwischen Gemini (Vorgabe) und
Anthropic (Block 73, Entscheidung von Robert vom 01.10.2026, selber Tag).

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

## Anbieter (Block 73)

Wählbar in F12 → Leitstand, zwei sich ausschließende Auswahlfelder, Vorgabe
Gemini (`einstellungen.json`, Schlüssel `leitstand_anbieter`,
`core.leitstand.anbieter()`). Jede Wahl wird sofort gesichert und angesagt
("Leitstand nutzt Gemini." bzw. "Leitstand nutzt Anthropic Haiku.").

- **Gemini** `gemini-3.5-flash-lite` (ai.google.dev/gemini-api/docs/models,
  Stand 01.10.2026: "vorherige Generation" des Flash-Lite-Modells; für neue
  Projekte rät die Dokumentation zu 3.5 Flash-Lite oder 3.8 Flash - für eine
  reine Weiter/Wiederholen/Stopp-Entscheidung reicht 3.5 Flash-Lite).
  Erzwingt JSON über `generationConfig.responseMimeType`. Mit dem echten
  Schlüssel aus `leitstand_zugang.txt` gegengeprüft: Verbindungstest
  ("Antworte mit OK") und ein JSON-Testaufruf im Entscheidungsschema liefen
  beide über die echte REST-Schnittstelle korrekt.
- **Anthropic** `claude-haiku-4-5-20251001`, Messages-API
  (platform.claude.com/docs/en/models/overview, Stand 01.10.2026 per
  WebFetch geprüft: weiterhin das schnellste/günstigste Modell der
  aktuellen Reihe, kein schnellerer Nachfolger vorhanden - **Anthropics
  eigene Angabe nennt dafür ein Retirement nicht vor dem 15.10.2026, also
  schon in rund zwei Wochen**; danach kann die Kennung ohne weitere
  Ankündigung scheitern und müsste neu geprüft werden). Ohne den von Gemini
  bekannten erzwungenen JSON-Modus - `core.leitstand._json_dekodieren` fängt
  einen üblichen Markdown-Zaun um die Antwort zusätzlich ab. Mangels eines im
  Datenordner hinterlegten Anthropic-Schlüssels bei Auftragsende nur mit
  nachgebildeten Antworten getestet (`core/test_leitstand.py`), nicht mit
  einem echten Aufruf - Endpunkt, Kopfzeilen und Antwortform
  (`usage.input_tokens`/`output_tokens`) stammen aus der offiziellen
  Schnellstart-Dokumentation, nicht aus Vermutung.

Beide Anbieter nutzen reine REST-Aufrufe über `requests` (wie
`core/bruecke.py`), keine eigene SDK-Abhängigkeit, und dasselbe
Entscheidungsschema/dieselben Grenzen.

## Schlüssel

`%LOCALAPPDATA%\CWB\leitstand_zugang.txt` (`core/pfade.py`,
`LEITSTAND_ZUGANG_DATEI`) - wie beim PC-Token der Brücke nie geloggt, nie
angezeigt, nicht in Git:

- `gemini_api_key=...` - fehlt er, sagt CWB "Kein Gemini-Schlüssel
  hinterlegt." und hält sofort an, sobald ein Nachtplan-Auftrag ihn bräuchte.
- `anthropic_api_key=...` - fehlt er, während Anthropic gewählt ist, sagt
  CWB "Kein Anthropic-Schlüssel hinterlegt." und fällt auf Gemini zurück
  (`core.leitstand.wirksamer_anbieter`); fehlt dann auch der Gemini-
  Schlüssel, gilt die Zeile darüber.

## Nutzung im Nachtbericht (Block 73)

Jeder gelungene Aufruf zählt in `core.leitstand.Zustand.nutzung`
(Anbieter → Aufrufe, Eingabe-/Ausgabe-Token aus der jeweiligen `usage`-
Antwort) - global über die Nacht, nicht je Projekt, wie `anzahl_auftraege`.
Jeder geschriebene `nachtbericht.md` listet den nächtlichen Gesamtstand unter
"Nutzung diese Nacht" - eine Schätzung zur Kosteneinschätzung, kein
Abrechnungsbeleg; ein an einem Netzfehler oder kaputtem JSON gescheiterter
Aufruf zählt nicht mit, weil dann kein verlässliches `usage`-Feld vorliegt.

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
- `anthropic_api_key` fehlt bislang in `leitstand_zugang.txt` - der
  geforderte echte Verbindungstest für Anthropic konnte deshalb nicht
  durchgeführt werden, nur mit nachgebildeten Antworten. Robert müsste die
  Zeile ergänzen, dann lässt sich der Verbindungstest nachholen.
- Anthropics Retirement-Angabe für `claude-haiku-4-5-20251001` nennt den
  15.10.2026 als frühestmöglichen Termin - nur rund zwei Wochen nach diesem
  Auftrag. Wird die Kennung danach abgeschaltet, meldet sich das als
  LeitstandNetzFehler (HTTP-Fehlerstatus) und Leitstand hält an; die Kennung
  müsste dann neu geprüft und eingetragen werden.
