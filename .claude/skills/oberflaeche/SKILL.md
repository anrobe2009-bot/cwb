---
name: oberflaeche
description: Gilt für jede Arbeit an Qt-Oberflächen und Stylesheets (PySide6, .qss). Legt Schriftabstufung, Abstände, Farben, Fokus und die Trennung von Aussehen und Code fest.
---

# Oberfläche

Regeln für jede Änderung an Qt-Widgets, Layouts und Stylesheets.

## Trennung

- Aussehen ausschließlich in `stil.qss`. Niemals `setStyleSheet` mit
  Gestaltungsangaben, keine Farben, Schriften oder Abstände im Python.
- Python setzt nur Struktur, Objektnamen und Eigenschaften; das Stylesheet
  greift über `#name` und `[eigenschaft="wert"]` darauf zu.

## Schrift

- Klare Abstufung statt überall gleich groß: Titel, Zwischenüberschrift,
  Fließtext, Nebentext — vier erkennbar verschiedene Größen.
- Größen relativ angeben (`em`, `pt` in Stufen), keine festen Pixelwerte.
- Gewicht sparsam: fett nur für Titel und den einen Akzent.

## Raum

- Großzügige, aber gleichmäßige Abstände. Ein Grundmaß wählen und alle
  Abstände als Vielfaches davon setzen.
- Innenabstand einer Kachel größer als der Abstand zwischen Text und Symbol.
- Flexible, mitwachsende Raster. Keine festen Pixelgrößen, keine feste
  Fensterbreite; Widgets dehnen sich über Stretch-Faktoren.

## Form

- Abgerundete Ecken durchgehend, gleicher Radius in der ganzen Oberfläche.
- Flache Kacheln statt dicker Rahmen: Flächenfarbe trennt die Bereiche,
  Linien nur haarfein oder gar nicht.
- Keine Verläufe, keine Schatten als Dekoration.

## Farbe

- Gedämpfte Pastelltöne auf dunklem Grund. Nichts Grelles, nichts Vollgesättigtes.
- Ein einziger Akzentton, reserviert für das jeweils Wichtigste. Wird er für
  mehreres benutzt, verliert er seine Bedeutung.
- Zustände (Fehler, Warnung, Erfolg) nie allein über Farbe — immer zusätzlich
  Text oder Symbol.
- Kontrast Text zu Grund mindestens 4,5:1, bei großem Text 3:1.

## Fokus

- Deutlicher Fokusrahmen an jedem bedienbaren Element, sichtbar auf jedem
  Untergrund, nicht nur eine Farbänderung.
- Fokus niemals ausblenden. Tab-Reihenfolge folgt der Leserichtung.
- Jedes Bedienelement hat einen sprechenden Namen für den Screenreader.
