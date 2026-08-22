# ClaudeCounter

Zeigt die Claude-Code-Auslastung dauerhaft auf dem 16×16-Display einer
**Divoom Timebox Evo** an — per Bluetooth RFCOMM, ohne WLAN, ohne die
Divoom-App, ohne iPhone.

![Anzeigezustände](docs/images/states.png)

Von links: ruhig · mittel · knapp · kritisch · veraltet (gedimmt) · keine Daten.

## Was auf dem Display steht

| Element | Bedeutung |
| --- | --- |
| Ring (58 Pixel) | 5-Stunden-Fenster, gefüllt nach Prozent |
| Ringfarbe | grün < 60 %, gelb < 80 %, orange < 95 %, rot darüber |
| Zahl in der Mitte | dieselbe Prozentzahl, `!!` ab 100 % |
| Unterste Zeile | 7-Tage-Fenster, violett |
| Cyaner Punkt | wo im jeweiligen Fenster die Uhr gerade steht |
| Alles gedimmt | Wert ist veraltet, die Quelle antwortet nicht |
| Leerer Ring, graues `--` | noch nie Daten gehabt |
| Orange atmender Hintergrund | eine Sitzung wartet auf deine Eingabe |

Der cyane Punkt folgt der Uhr, nicht dem Zeitpunkt der Messung. Ein Ringpixel
entspricht rund 5,2 Minuten, ein Pixel der Wochenzeile rund 10,5 Stunden.

Es wird **nie** 0 % angezeigt, wenn in Wahrheit nur die Datenquelle fehlt.

## Voraussetzungen

* macOS (entwickelt und verifiziert auf macOS 26.5.2)
* Python 3.11 oder neuer mit [Pillow](https://pypi.org/project/Pillow/)
* Xcode-Kommandozeilenwerkzeuge (für den Bluetooth-Helfer)
* Eine Divoom Timebox Evo, **mit dem Mac gekoppelt** (normale Audio-Kopplung genügt)
* Ein Claude-Konto mit aktiver Pro- oder Max-Subscription

## Einrichtung

```bash
git clone <dein-repo> ClaudeCounter
cd ClaudeCounter
python3 -m pip install -r requirements.txt
```

**1. Bluetooth-Helfer bauen.** Er muss ein `.app`-Bündel sein, siehe
[Warum ein App-Bündel](#warum-ein-app-bündel).

```bash
tools/build_native.sh
```

**2. Gerät finden.** Die Timebox muss vorher in den Systemeinstellungen
gekoppelt sein.

```bash
python3 -m claudecounter list-devices
```

**3. Gerät eintragen.** Der SPP-Kanal ist bei der Evo in aller Regel 1;
`configure` prüft ihn per SDP-Abfrage nach.

```bash
python3 -m claudecounter configure --mac AA:BB:CC:DD:EE:FF
```

**4. Testbild senden.** Beim allerersten Aufruf fragt macOS nach der
Bluetooth-Berechtigung.

```bash
python3 -m claudecounter send --session 42 --weekly 17
```

**5. Als Dienst installieren.** Startet bei der Anmeldung und zusätzlich,
sobald du Claude öffnest.

```bash
tools/install.sh
```

Wieder entfernen:

```bash
tools/uninstall.sh
```

## Bedienung

```bash
python3 -m claudecounter preview --session 82 --weekly 41 --ascii   # ohne Hardware
python3 -m claudecounter usage                                      # aktuelle Werte
python3 -m claudecounter usage --raw                                # rohe Antwort
python3 -m claudecounter brightness 40                              # 0 bis 100
python3 -m claudecounter daemon --verbose                           # im Vordergrund
python3 -m claudecounter send --session 63 --weekly 29 --breathing  # Atmen testen
python3 -m claudecounter waiting                                    # wer wartet gerade
python3 -m claudecounter waiting --clear                            # Atmen abwürgen
```

`preview` und `send` nehmen zusätzlich `--stale`, `--session-resets-in <Minuten>`
und `--weekly-resets-in <Stunden>`, um jeden Anzeigezustand ohne echte Daten
nachzustellen.

Logdatei: `~/Library/Logs/ClaudeCounter/claudecounter.log`

## Woher die Zahlen kommen

Primär aus `GET https://api.anthropic.com/api/oauth/usage`, mit dem
OAuth-Token, das Claude Code in der Keychain ablegt (`Claude Code-credentials`).
Genutzt werden genau zwei Felder:

```json
"five_hour": { "utilization": 2.0,  "resets_at": "2026-08-22T21:40:00Z" },
"seven_day": { "utilization": 50.0, "resets_at": "2026-08-24T12:59:59Z" }
```

Der Endpunkt hat ein eigenes Rate-Limit: 60 Anfragen pro Stunde lösten ein
`HTTP 429` mit `retry-after: 3578` aus. Deshalb fragt der Daemon ihn regulär nur
alle 120 Sekunden, zeichnet aber alle 60 Sekunden neu, und hält bei `429` exakt
so lange still, wie der Header sagt.

Zusätzlich fragt er **sofort nach jedem beendeten Turn** — genau dann ändert sich
der Verbrauch ja. Der `Stop`-Hook legt dafür eine Marke ab, der Daemon sieht sie
binnen fünf Sekunden. Zwei aufeinanderfolgende Anfragen liegen dabei nie näher
als `MINIMUM_FETCH_SPACING_SECONDS` (90 s) beieinander; selbst bei einem Turn
alle zehn Sekunden bleibt es damit bei 40 Anfragen pro Stunde.

Optional und kostenlos gibt es die Werte auch lokal: `tools/statusline.py` klinkt
sich als Claude-Code-Statusline ein und schreibt `rate_limits` aus deren
stdin-JSON nach `~/Library/Application Support/ClaudeCounter/usage.json`. Der
Daemon liest diese Datei bevorzugt und im 60-Sekunden-Takt. Das funktioniert nur
in der **Terminal**-Version von Claude Code; die Desktop-App ruft Statuslines
nicht auf — dort kommen die Zahlen vom Endpunkt, nach jedem Turn und sonst alle
zwei Minuten. Hooks führt die Desktop-App dagegen aus, das Atmen funktioniert
also in beiden.

Bewusst **nicht** benutzt: Header von `/v1/messages` (verbraucht Kontingent, um
Kontingent zu messen, und kennt kein Wochenfenster) sowie das Auswerten der
JSONL-Transkripte.

## Wenn eine Sitzung auf dich wartet

Der Hintergrund hinter den Ziffern atmet dann orange. Ring, Zeitpunkt-Marker und
Wochenbalken bleiben unverändert, die Prozentzahl bleibt lesbar.

Erkannt wird das über Hooks von Claude Code, nicht über macOS-Benachrichtigungen:

| Ereignis | Wirkung |
| --- | --- |
| `Notification` | Freigabe nötig, oder die Eingabe liegt seit 60 s brach → atmen |
| `UserPromptSubmit`, `SessionStart` | Eingabe kam → aufhören |
| `Stop` | Antwort fertig → aufhören, und neue Zahlen holen |
| `SessionEnd` | Sitzung vorbei → alles vergessen, neue Zahlen holen |

`Notification` ist genau das Ereignis, auf dem auch die macOS-Benachrichtigungen
sitzen — nur eben zuverlässig sichtbar. Bewusst **nicht** `Stop`: das feuert nach
jeder einzelnen Antwort, und wer nebenbei in einem anderen Fenster arbeitet,
hätte damit ein dauerhaft oranges Display.

Die Markierungen liegen in `~/Library/Application Support/ClaudeCounter/waiting/`.
`tools/install.sh` trägt die Hooks ein, `tools/uninstall.sh` nimmt sie zurück.

**Es hört auf, sobald du bei der Sitzung warst** — nicht erst, wenn du antwortest.
Bei jedem `UserPromptSubmit` merkt sich der Hook, welche App gerade vorne war;
das ist die App, in der diese Sitzung lebt. Der Daemon schaut alle fünf Sekunden
nach, ob diese App vorne ist **und** ob in den letzten 90 Sekunden jemand Maus
oder Tastatur bedient hat. Beides zusammen heißt: du hast es gesehen, die
Markierung wird gelöscht. Nur die vordere App zu sein reicht nicht — ein offenes
Fenster in einem leeren Zimmer hat niemand gesehen.

Beides wird ohne Berechtigungsabfrage gelesen, über `lsappinfo front` und
`ioreg -c IOHIDSystem`, zusammen etwa 20 ms.

Zwei Folgen davon:

* Während du vor dem Chat sitzt, atmet es gar nicht erst — du siehst die Antwort
  ja ohnehin. Es atmet nur, wenn du weggeklickt hast.
* Danach höchstens `BREATH_MAX_SECONDS` lang, aktuell **15 Minuten**. Danach
  verfällt die Markierung, egal ob gesehen oder nicht. Der Wert steht als eine
  Konstante in `claudecounter/attention.py`.

Es atmet, solange **irgendeine** Sitzung wartet, und hört erst auf, wenn jede
einzelne gesehen wurde; Sitzungen in verschiedenen Apps werden getrennt
behandelt. `claudecounter waiting` zeigt den ganzen Entscheidungsweg:

```
frontmost app: com.anthropic.claudefordesktop
last input: 1s ago (at the keyboard)
1 marker(s):
  regel-test  belongs to com.anthropic.claudefordesktop
not breathing
```

Das Atmen läuft als Endlos-Animation auf dem Gerät selbst, nicht als Bilderfolge
vom Mac — der könnte höchstens 1,4 Bilder pro Sekunde schicken. Zwölf Bilder à
320 ms gehen in acht Paketen und 0,65 Sekunden über eine einzige Verbindung.

Der Daemon zeichnet weiter im Minutentakt, schaut aber alle fünf Sekunden nach
wartenden Sitzungen; der Wechsel ist also nach wenigen Sekunden auf dem Display.

## Fehlersuche

**Die Timebox klaut die Audio-Ausgabe**
Sie meldet sich unter derselben Adresse mit den Profilen `HFP AVRCP A2DP` an,
macOS sieht also ein Headset. Abschalten lässt sich das gerätseitig nicht, in
keiner der Referenzen gibt es dafür ein Kommando. Trennen hilft nur kurz:
`claudecounter disconnect` funktioniert, aber die Timebox baut die Verbindung
binnen Sekunden selbst wieder auf. Bleibt: unter Systemeinstellungen → Ton die
gewünschte Ausgabe wählen, oder die Timebox aus der Bluetooth-Liste entfernen.

**„the Claude Code access token expired"**
Das Token wird nur erneuert, wenn die CLI wirklich benutzt wird —
`claude auth status` genügt dafür nicht. Melde dich im Terminal neu an:

```bash
claude auth login
```

Prüfen: `claude auth status` muss `"subscriptionType": "max"` (oder `"pro"`)
zeigen. Steht dort `null`, hängt an dieser Anmeldung keine Subscription, und es
gibt schlicht keine Fenster anzuzeigen.

Achtung: Die **Desktop-App und die Terminal-CLI haben getrennte Anmeldungen.**
Eine Neuanmeldung in der App erneuert den Keychain-Eintrag der CLI nicht.

**„the usage endpoint answered with HTTP 429"**
Selbst verschuldetes Rate-Limit. Der Daemon pausiert von allein; `retry-after`
zählt auf einen festen Zeitpunkt herunter und wird durch weitere Anfragen nicht
verlängert. Nichts zu tun außer warten.

**Auf der Timebox steht wieder die Uhr statt des Zählers**
Du hast am Gerät die Modustasten benutzt. Das Gerät meldet das nicht, aber der
Daemon sendet das Bild jede Minute erneut — nach spätestens 60 Sekunden ist der
Zähler von allein zurück. Sofort erzwingen:

```bash
launchctl kickstart -k gui/$UID/local.claudecounter.daemon
```

**Das Display bleibt bei `--`**
Der Daemon hatte noch nie echte Daten. Absicht — lieber ehrlich leer als eine
erfundene Null. `python3 -m claudecounter usage` zeigt den Grund.

**„could not reach the display"**
Timebox aus, außer Reichweite oder von einem anderen Gerät belegt. Der Daemon
versucht es mit wachsendem Abstand erneut (5, 10, 20 … bis 300 Sekunden).

**Der erste Versand schlägt mit SIGABRT / Exit 134 fehl**
Der Helfer wurde direkt gestartet statt über LaunchServices. Siehe unten.

**`list-devices` zeigt das Gerät nicht**
Es muss in den Systemeinstellungen gekoppelt sein. `system_profiler` verschweigt
den SPP-Dienst; erst eine frische SDP-Abfrage bringt ihn zum Vorschein — genau
das macht `configure`.

**Falscher Kanal**
```bash
python3 -m claudecounter probe --mac AA:BB:CC:DD:EE:FF
```

### Warum ein App-Bündel

Seit macOS 26 verlangt der Datenschutzwächter, dass ein Prozess über
LaunchServices oder launchd gestartet wird, bevor er IOBluetooth benutzen darf.
Eine nackte Binärdatei stirbt mit SIGABRT, selbst mit eingebettetem
`Info.plist` und Signatur. `tools/build_native.sh` erzeugt deshalb ein
`.app`-Bündel, das über `open -a` gestartet wird. Details in
[docs/findings.md](docs/findings.md) §9.2.

## Aufbau

```
claudecounter/
  protocol.py      Divoom-Drahtformat, bytegenau gegen fünf echte Aufnahmen geprüft
  render.py        16×16-Bild aus einem Messwert, Standbild und Atem-Schleife
  usage_source.py  Token, Endpunkt, lokale Datei, Fehlerklassen
  attention.py     Markierungen wartender Sitzungen
  presence.py      vorderste App und Zeit seit der letzten Eingabe
  daemon.py        Schleife, Wiederholstrategie, Protokoll
  transport.py     Brücke zum Bluetooth-Helfer
  config.py        Gerätekonfiguration
  cli.py           Unterbefehle
tools/
  bt_probe.swift   IOBluetooth-Helfer
  build_native.sh  baut und signiert das App-Bündel
  install.sh       LaunchAgent, Hooks, Statusline
  session_hook.py  trägt Hooks und Statusline in die Einstellungen ein
  statusline.py    lokale Datenquelle
  waiting_hook.py  übersetzt Claude-Code-Ereignisse in Markierungen
tests/             fünf eigenständige Suiten, ohne pytest
docs/findings.md   Protokollrecherche und alles am Gerät Verifizierte
```

Tests laufen ohne Zusatzpakete:

```bash
for suite in render protocol usage_source daemon attention; do python3 tests/test_$suite.py; done
```

## Protokoll

Rahmen: `0x01 | LEN_lo LEN_hi | CMD | ARGS… | CRC_lo CRC_hi | 0x02`, dabei
`LEN = len(ARGS)+3` und `CRC = sum(LEN_lo, LEN_hi, CMD, ARGS…) & 0xFFFF`
in Little-Endian. Für die Timebox wird **nicht** escaped.

Standbild: `CMD 0x44`, Argumente `00 0A 0A 04` plus ein Frame.
Atem-Schleife: `CMD 0x49`, Argumente Gesamtlänge (2 B), Paketnummer (1 B) und ein
200-Byte-Stück des Frame-Stroms; das Gerät spielt sie danach endlos ab.

Jedes Byte ist entweder gegen eine öffentliche Aufnahme geprüft oder am Gerät
verifiziert; erfunden wurde keines. Die Herleitung steht in
[docs/findings.md](docs/findings.md).

## Lizenz

MIT, siehe [LICENSE](LICENSE).

[divo](https://github.com/4ch1m/divo) und
[hass-divoom](https://github.com/dylandoamaral/hass-divoom) (beide GPL) wurden
ausschließlich als Referenz gelesen. Es wurde kein Code übernommen.
