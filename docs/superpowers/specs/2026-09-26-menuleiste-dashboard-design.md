# Menüleisten-Menü als Dashboard

Stand: 2026-09-26. Betrifft nur `tools/menubar.swift`. Daten, Daemon und Anzeige auf der
Timebox bleiben unverändert.

## Warum

Das Menü war eine Liste aus Textzeilen. Vier davon erklärten den blauen Punkt, zwei
beschrieben je einen Dienst ("Zähler läuft" und darunter "Zähler stoppen"). Die beiden
Zahlen, um die es geht, standen in einer einzigen Zeile ganz oben.

## Was entsteht

### Kopf: zwei Kacheln nebeneinander

Eine Zeile, zwei gleich breite Kacheln mit schwach gefülltem Hintergrund.

| | links | rechts |
|---|---|---|
| Ring | Sitzung, wie das Symbol in der Menüleiste, ohne Ziffern | Woche, gleiche Farbskala |
| Überschrift | Sitzung | Woche |
| Zahl | 14 % | 26 % |
| Hinweis | frei um 18:49 | 91 % der Woche um |

Der blaue Punkt am Ring bleibt und sitzt an derselben Stelle wie auf dem Gerät. Ist der
Wochenpunkt auf Tage oder Stunden eingeschränkt, heißt der Hinweis "91 % der Zeit um".
Fehlt die Rücksetzzeit, entfällt der Hinweis. Ohne Messwert steht dort "noch kein Messwert".

Darunter eine schmale Zeile: "zuletzt 14:08:55 Uhr", bei veralteten Werten mit dem Zusatz
"veraltet", und rechts die Schaltfläche "auffrischen", die das Menü schließt.

Die vier Erklärzeilen zum blauen Punkt entfallen.

### Schalter statt Zeilenpaare

Zähler und Tonschutz bekommen je eine Zeile mit Symbol, Namen und einem Schalter rechts.
Der Schalter zeigt, ob der Dienst läuft, und startet oder stoppt ihn. Läuft der Zähler
nicht, steht unter der Helligkeit der Hinweis, dass sie erst mit dem Zähler wirkt.

Die Helligkeit wird zur Zeile aus Sonnensymbol, Regler und Prozentwert rechts.

### Wochentage sichtbar

Statt eines Untermenüs eine Reihe aus sieben Tasten, Mo bis So, gewählte Tage gefüllt.
Der letzte Tag lässt sich nicht abwählen. Die Stundenwahl bleibt ein Untermenü, weil sie
sechs Vorgaben hat, und zeigt den gewählten Wert im Titel.

### Fuß

Neu anmelden, Protokoll öffnen, Menü beenden, jeweils mit Symbol.

## Umsetzung

Eigene Ansichten in Menüeinträgen, wie sie der Helligkeitsregler heute schon benutzt. Das
Menü bleibt ein gewöhnliches Menüleisten-Menü. Alle Farben kommen aus den Systemfarben,
damit Hell und Dunkel und die gewählte Akzentfarbe von selbst stimmen. Symbole kommen aus
SF Symbols.

`ringImage` bekommt Größe, Strichstärke, Punktgröße und einen Schalter für die Ziffern als
Parameter, damit dasselbe Zeichnen die Menüleiste mit 20 Punkt und die Kacheln mit 36
Punkt bedient.

Ein freistehendes Fenster statt des Menüs wäre freier in der Gestaltung, müsste sich aber
selbst um Tastatur, Platzierung und Schließen kümmern. Der Gewinn rechtfertigt das nicht.

## Was gleich bleibt

Das Symbol in der Menüleiste, die gelesenen Dateien, `state.json`, die Mitteilung bei
abgelaufener Anmeldung, die Dateien für Helligkeit, Wochentage und Stunden.
