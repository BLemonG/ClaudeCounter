# M0 — Recherche: Divoom Timebox Evo Protokoll & Claude-Usage-Datenquelle

Stand: 2026-08-22. Alle Aussagen unten sind entweder aus geklontem Quellcode in `refs/`
belegt oder rechnerisch an bekannten funktionierenden Frames verifiziert. Nichts ist geraten.

---

## 1. Aufbau eines Divoom-Frames

### 1.1 Äußere Nachricht (alle Kommandos)

```
0x01 | LEN_lo LEN_hi | CMD | ARGS… | CRC_lo CRC_hi | 0x02
     └────────────── über diesen Bereich wird die CRC gebildet ──┘
```

- `LEN` = `len(ARGS) + 3` (1 Byte CMD + 2 Byte CRC), little-endian.
  Das Längenfeld zählt sich selbst **nicht** mit.
- `CRC` = `sum(LEN_lo, LEN_hi, CMD, ARGS…) & 0xFFFF`, little-endian, **2 Byte**.
- Rahmenbytes `0x01` / `0x02` liegen außerhalb der CRC.

Belege:
[`node-divoom-timebox-evo/PROTOCOL.md:66-87`](../refs/node-divoom-timebox-evo/PROTOCOL.md),
[`divo/divo/packet.py:33-46`](../refs/divo/divo/packet.py),
[`hass-divoom/custom_components/divoom/devices/divoom.py:234-291`](../refs/hass-divoom/custom_components/divoom/devices/divoom.py),
[`ditoo-clawdmeter/ditoo_clawdmeter/protocol.py:35-51`](../refs/ditoo-clawdmeter/ditoo_clawdmeter/protocol.py).

**Rechnerisch verifiziert** an den drei Roh-Frames aus dem divo-README (Mudkip, Nyan Cat,
4-Farb-Test): 2-Byte-CRC über `LEN…ARGS` stimmt in allen drei Fällen exakt.

### 1.2 Bild-Frame (Payload von CMD `0x44`)

```
0x44 | 00 0A 0A 04 | 0xAA | FLEN_lo FLEN_hi | TTTT | PAL_FLAG | NCOL | COLORS… | PIXELS…
     └ Fixheader  ┘        └─────────── FRAME_DATA, ab 0xAA gezählt ──────────┘
```

| Feld | Bedeutung |
|---|---|
| `00 0A 0A 04` | Fixheader für **Einzelbild** (Animationen nutzen stattdessen `LSUM_lo LSUM_hi IDX`) |
| `0xAA` | Frame-Startmarke |
| `FLEN` | Bytes von `0xAA` bis Frame-Ende, also `len(FRAME_BODY) + 3`, little-endian |
| `TTTT` | Frame-Dauer in ms, little-endian. Bei Einzelbildern egal (`0x0000` und `0x01F4`=500 sind beide belegt) |
| `PAL_FLAG` | `0x00` |
| `NCOL` | Anzahl Palettenfarben, 1 Byte; bei 256 wird `0x00` gesendet |
| `COLORS` | `NCOL × RGB` (je 3 Byte) |
| `PIXELS` | 256 Palettenindizes, bitgepackt |

`PROTOCOL.md` beschreibt `TTTT PAL_FLAG` zusammengefasst als "fixed `000000`" — das ist
dieselbe Struktur, nur unbenannt.

### 1.3 Pixel-Bitpacking

- `bits_per_pixel = ceil(log2(NCOL))`, mindestens 1.
- Pixelreihenfolge: links→rechts, oben→unten, Index `x + 16*y`.
- Packing **LSB-first**: der erste Pixel liegt in den niederwertigsten Bits des ersten Bytes.

**Verifiziert**: Ich habe den 4-Farb-Testframe aus dem divo-README mit genau diesem
Algorithmus dekodiert. Ergebnis ist eine saubere Diagonale plus 4 Paletten-Probepixel oben
links — also exakt das, was ein "Palette 4 color test" sein soll:

```
.oO#...........#      Palette: (0,0,0) (255,0,0) (255,85,0) (255,255,255)
..............#.      bits_per_pixel = 2, 64 Pixelbytes (= 256*2/8) ✓
.............#..
   … (Diagonale) …
#...............
```

Damit ist die Bitreihenfolge zweifelsfrei geklärt und muss nicht am Gerät geraten werden.

### 1.4 Weitere Kommandos (aus den Referenzen belegt)

| CMD | Bedeutung | Format |
|---|---|---|
| `0x44` | Bild setzen | siehe oben |
| `0x45` | Kanal/View umschalten | `45 CH …` — u.a. `4501 RRGGBB BB TT PP 000000` (Lightning) |
| `0x46` | Settings abfragen (liefert Antwort) | `46` |
| `0x49` | Animation senden (mehrteilig) | `49 LSUM IDX FRAMES…` |
| `0x74` | Helligkeit 0–100 | `74 BB` |

Für dieses Projekt werden **nur `0x44` und `0x74`** gebraucht.

---

## 2. Konkretes Bildkommando für die Timebox Evo

Bekannt funktionierender Frame (divo-README, "Palette 4 color test", real an einer Evo
getestet — das Repo unterstützt die Evo explizit):

```
01 5a00 44 000a0a04 aa 5300 f401 00 04 000000 ff0000 ff5500 ffffff <64 Byte Pixel> dc0c 02
```

Zerlegt:

| Bytes | Wert | Prüfung |
|---|---|---|
| `01` | Start | |
| `5a 00` | LEN = 90 | = len(ARGS)+3 ✓ |
| `44` | CMD Bild | |
| `00 0a 0a 04` | Einzelbild-Header | |
| `aa` | Framestart | |
| `53 00` | FLEN = 83 | = 2+1+1+12+64 +3 ✓ |
| `f4 01` | TTTT = 500 ms | |
| `00` | Palettenflag | |
| `04` | 4 Farben | |
| `000000 ff0000 ff5500 ffffff` | Palette | |
| 64 Byte | 256 Pixel à 2 bit | ✓ |
| `dc 0c` | CRC = 3292 & 0xFFFF | ✓ nachgerechnet |
| `02` | Ende | |

Zwei weitere Frames (Mudkip, 8 Farben, FLEN 127; Nyan Cat, 18 Farben, FLEN 221) rechnen
mit derselben Formel ebenfalls exakt auf. **Diese drei Frames sind unsere Testvektoren
für M1/M2** — der eigene Encoder muss sie byte-genau reproduzieren können, bevor
irgendwelche Hardware angefasst wird.

---

## 3. Taugt das Ditoo-Bildkommando unverändert für die Evo?

### Antwort: Ja, mit einer Ausnahme in der CRC-Breite.

**Begründung 1 — hass-divoom erzeugt für beide Geräte identische Bytes.**
`ditoo-clawdmeter/protocol.py` ist ausweislich seines eigenen Docstrings ein Port von
hass-divoom. In hass-divoom erben `Ditoo` und `Timebox` (dort ist die Evo eingeordnet,
siehe unten) die Bild-, Helligkeits- und View-Pfade unverändert aus der gemeinsamen
Basisklasse `Divoom` — es gibt **keine** Geräte-Overrides für `show_image`.

Das Repo hat aufgezeichnete Golden-Byte-Dumps pro Gerät. Ich habe alle 28 gemeinsamen
Fixtures verglichen:

```
28 von 28 Dateien byte-identisch zwischen tests/goldens/Timebox/ und tests/goldens/Ditoo/
```

inklusive `show_image_smiley16.txt` (Einzelbild, CMD `0x44`) und aller
Animationsvarianten. Das ist der stärkste verfügbare Beleg ohne Hardware.

**Begründung 2 — die Evo läuft in hass-divoom unter dem Typ `timebox`.**
`config_flow.py:209` ordnet jeden Gerätenamen, der mit `timebox` beginnt (also auch
`Timebox-evo-light`), dem Typ `timebox` zu. `devices/timebox.py` setzt `port=1`,
`screensize=16`, `escapePayload=False` — deckt sich mit den SPEC-Constraints.

**Begründung 3 — Struktur deckt sich mit den echten Evo-Frames.**
Der von `ditoo-clawdmeter/protocol.py:117-123` gebaute Byteaufbau ist Feld für Feld
derselbe wie in den divo-Roh-Frames aus Abschnitt 2.

### Die eine Abweichung: CRC-Breite

`ditoo-clawdmeter/protocol.py:35-38` (aus hass-divoom übernommen):

```python
width = 4 if total >= 65535 else 2
```

Das ist ein **Pixoo-Max-Sonderfall** (der hass-divoom-Kommentar sagt es wörtlich:
"Pixoo-Max expects more sometimes"). Für die Evo gilt laut `PROTOCOL.md` und laut allen
drei verifizierten Roh-Frames strikt `sum & 0xFFFF` in 2 Byte. `divo/packet.py:43` maskiert
ebenfalls fest auf `0xFFFF`.

Praktische Relevanz: Bei unserem Renderer (schätzungsweise 6–10 Palettenfarben,
3–4 bit/Pixel, ~130–200 Byte Nachricht) liegt die Bytesumme deutlich unter 65535, der
Zweig würde nie greifen. Er bleibt trotzdem falsch für die Evo. **Entscheidung für M1/M2:
CRC hart auf 2 Byte, `sum & 0xFFFF`.**

### Weitere Ditoo/Evo-Unterschiede

| Punkt | Ditoo | Timebox Evo |
|---|---|---|
| RFCOMM-Channel | 2 (empirisch, ditoo-clawdmeter Fallback) | **1** (`divo/bluetooth_socket.py:50`, `hass-divoom/devices/timebox.py`) |
| Bild-/Helligkeitsprotokoll | identisch | identisch (28/28 Goldens) |
| Escaping `0x01/0x02/0x03` | aus | aus (Default in hass-divoom; Kommentar: "not needed anymore") |
| Zusatzhardware | Tastatur, Mikrofon, Buttons | nicht relevant |

---

## 4. Bluetooth-Transport auf macOS

- `ditoo-clawdmeter/tools/ditoo_send.swift` löst den RFCOMM-Channel per **SDP-Lookup der
  SPP-UUID `0x1101`** auf, statt ihn hart zu setzen; der Fallback ist Channel 2. Für die
  Evo muss dieser Fallback auf **1** konfigurierbar sein.
- `AF_BLUETOOTH`/`BTPROTO_RFCOMM` existiert unter macOS nicht. Der Swift/IOBluetooth-Weg
  ist alternativlos; die Python-`RfcommTransport`-Variante ist Linux-only.
- **Kein `HELLO`-Handshake in irgendeiner Referenz.** Grep über ditoo-clawdmeter,
  Clawdmeter, divo, hass-divoom und `PROTOCOL.md` findet keine einzige Fundstelle. Alle
  Implementierungen verbinden und schreiben sofort. Der SPEC-Hinweis ist damit bestätigt:
  nach dem Connect nicht blockierend lesen.
- hass-divoom liest nach `show_image` bewusst nicht (`skipRead=True`); nur der Ping
  (`0x46`, "get view") erwartet eine Antwort.
- Maximale Nachrichtengröße: `PROTOCOL.md` empfiehlt Aufteilung alle 666 Byte. Unser
  Einzelbild bleibt weit darunter → immer ein einziger Write, kein Chunking.

### Konflikt mit dem SPEC-Constraint "Socket offen halten"

`ditoo-clawdmeter/transport.py:89-98` dokumentiert ausdrücklich das Gegenteil:

> "Each send() invokes the helper fresh … rather than holding a persistent connection —
> this matches how the Divoom app itself reconnects per-session and has proven far more
> reliable than trying to keep a long-lived IOBluetooth channel open across calls."

Der bestehende Swift-Helper ist ein Einmal-Schuss: verbinden, schreiben, nach 0,5 s
`exit(0)`. Für M4 („Socket offen halten") muss er zu einem persistenten Prozess erweitert
werden, der Frames über stdin entgegennimmt und den RFCOMM-Kanal hält. Das ist Neuarbeit,
kein Übernehmen — und sie steht gegen die Erfahrung des Ditoo-Projekts. Zu klären an der
Hardware (siehe offene Fragen).

---

## 5. Datenquelle: `api/oauth/usage`

Schema laut `claude-code-statusline` (`statusline.sh:186-225`, dort auch als undokumentiert
gekennzeichnet, Upstream-Issue anthropics/claude-code#13585):

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <accessToken>
anthropic-beta: oauth-2025-04-20
```

```json
{
  "five_hour":        { "utilization": 18.0, "resets_at": "2026-03-27T10:00:00+00:00" },
  "seven_day":        { "utilization": 17.0, "resets_at": "2026-04-02T13:00:00+00:00" },
  "seven_day_sonnet": { "utilization": 10.0, "resets_at": "2026-04-02T13:00:00+00:00" }
}
```

`utilization` ist bereits 0–100 (nicht 0–1), Reset-Zeiten sind ISO-8601. Das mappt 1:1 auf
den Datenkontrakt in SPEC §6.

### Verifikation am echten Endpoint: fehlgeschlagen — Token abgelaufen

Ich habe den Endpoint mit dem lokal gespeicherten Token abgefragt:

```
HTTP 401 — "OAuth access token has expired. Re-authenticate to continue."
```

Zustand der Credentials auf dieser Maschine:

- `~/.claude/.credentials.json` existiert **nicht**. Der Token liegt nur im Keychain.
- Keychain-Eintrag `Claude Code-credentials`: `accessToken` **abgelaufen am 2026-07-30**,
  `refreshToken` gültig noch bis **2026-08-26** (also 4 Tage), `rateLimitTier`
  = `default_claude_ai`, `subscriptionType` = null.
- Es gibt 15 weitere Keychain-Einträge `Claude Code-credentials-<hash>`. Keiner davon
  enthält ein `claudeAiOauth`-Objekt — das sind MCP-/Plugin-Credentials, keine Alternative.

Das heißt: **die Datenquelle ist aktuell nicht abfragbar.** Das echte Response-Schema
konnte ich nicht gegen den Live-Endpoint bestätigen, nur gegen die Referenzimplementierung.

Relevante Design-Entscheidung aus dem ausgereiftesten Referenz-Daemon
(`Clawdmeter/daemon/claude_usage_daemon.py:57-60`): der Daemon **refresht den Token
bewusst nie selbst** — „Claude Code owns refreshing" — sondern liest ihn bei jedem Poll neu
und zeigt bei 401/403 „keine Daten" an. Das passt exakt zum SPEC-Constraint
(stale statt Absturz, nie 0 % anzeigen). Selbst refreshen würde mit der Rotation von
Claude Code kollidieren.

Praktische Hinweise für M3, die aus dem Clawdmeter-Daemon übernommen werden sollten
(als Verhalten, nicht als kopierter Code — siehe Lizenzen unten):
- `security find-generic-password -s "Claude Code-credentials" -a "$USER" -w`
- Die Ausgabe kann ein **Hex-Dump** statt Klartext sein, wenn der gespeicherte Blob nicht
  sauber druckbar ist → vor dem Parsen auf reines Hex prüfen und dekodieren.
- Token bei jedem Poll neu lesen, nicht cachen.

---

## 6. Lizenzlage (Korrektur zur SPEC)

Die SPEC nennt in §9 „GPL-Code (divo, hass-divoom)". Tatsächlich:

| Repo | Lizenz | Nutzung |
|---|---|---|
| `RomRider/node-divoom-timebox-evo` | MIT | Doku + Code frei verwendbar |
| `d03n3rfr1tz3/hass-divoom` | **MIT** (nicht GPL) | Code darf mit Attribution übernommen werden |
| `ismkdc/ditoo-clawdmeter` | MIT | Code darf mit Attribution übernommen werden |
| `ohugonnot/claude-code-statusline` | MIT | frei verwendbar |
| `spezifisch/divo` | **GPL-3.0** | nur lesen, nichts kopieren |
| `HermannBjorgvin/Clawdmeter` | **keine Lizenzdatei** | README warnt ausdrücklich vor Fork/Copy (proprietäre Fonts + Anthropic-Assets). Nur Verhalten/Architektur als Referenz, kein Code, keine Assets. |

Das ist günstiger als in der SPEC angenommen: die Protokollschicht darf auf MIT-Basis
(hass-divoom über ditoo-clawdmeter) aufgebaut werden. Die GPL-Sperre betrifft nur divo —
das brauchen wir aber ohnehin nur als Verifikationsquelle, was reines Lesen ist.

---

## 7. Offene Fragen — nur am Gerät bzw. durch dich klärbar

**Blocker für M2 (Hardware):**

1. **Gepairt, aber nur die Audio-Identität.** Stand 2026-08-22 zeigt `system_profiler`:

   ```
   TimeBox-Evo-audio
       Address:  AA:BB:CC:DD:EE:FF
       Minor Type: Headset
       Services: 0x800019 < HFP AVRCP A2DP ACL >
   ```

   Ein `TimeBox-Evo-light` taucht nicht auf, und in den gecachten Services steht **kein
   Serial Port (SPP)**. Das Präfix `11:75:58` ist das Divoom-OUI (dieselben ersten drei
   Bytes wie in den Beispieladressen von divo und ditoo-clawdmeter).
2. **Offen: Erreicht diese eine Adresse das Display?** Zwei Möglichkeiten, in M2 zu trennen:
   - Die Evo hat eine zweite, separate Light-Adresse, die macOS nicht koppelt, weil sie
     nur SPP anbietet. Dann muss sie über eine Inquiry gefunden werden, nicht über die
     Pairing-Liste.
   - Dieselbe Adresse bietet SPP an, aber erst nach einer frischen SDP-Query — die
     `system_profiler`-Ausgabe zeigt nur gecachte Major-Services. Genau deshalb macht
     `ditoo_send.swift` vor dem Verbinden ein `performSDPQuery`.

   Erster Schritt in M2 ist damit eine SDP-Abfrage auf `AA:BB:CC:DD:EE:FF` mit der Frage,
   ob UUID `0x1101` vorhanden ist und auf welchem Channel.
3. **`blueutil` ist nicht installiert.** Das `list-devices`-Kommando von ditoo-clawdmeter
   basiert darauf (`brew install blueutil`). Alternativ bauen wir die Geräteliste direkt
   im Swift-Helper über IOBluetooth — sauberer, eine Abhängigkeit weniger. Entscheidung
   fällt in M2.
4. **Persistenter RFCOMM-Kanal vs. Reconnect-pro-Frame:** Das Ditoo-Projekt hat den
   persistenten Kanal auf macOS als unzuverlässig verworfen. Ob die Evo sich anders
   verhält (sie hat ebenfalls ein Audio-Profil, das sich mit dem Kanal beißen kann),
   ist nur empirisch zu klären. Falls der persistente Kanal nicht stabil läuft, kollidiert
   das mit SPEC §5 („Socket offen halten") und ich brauche eine Entscheidung.
5. **Braucht `0x44` einen vorherigen Kanalwechsel?** Weder `PROTOCOL.md` noch hass-divoom
   noch divo schicken vor einem Bild ein `0x45`. Vermutlich schaltet `0x44` selbst um.
   Risiko gering, aber am Gerät zu bestätigen.
6. **Escaping:** Default aus, wie in der SPEC. Zerrissene Bilder wären das Symptom für
   ältere Firmware. Nur am Gerät feststellbar.

**Blocker für M3 (deine Aktion nötig):**

7. **Es gibt keinen gültigen Claude-Code-OAuth-Token auf dieser Maschine.** Der
   Access-Token ist seit dem 30.07. abgelaufen, der Refresh-Token läuft am 26.08. ab.
   Ohne gültigen Token kann M3 weder das Schema verifizieren noch die Abnahme erfüllen
   („Werte stimmen mit `/usage` überein"). Bitte einmal in einem interaktiven
   `claude`-Terminal neu einloggen, damit der Keychain-Eintrag frisch geschrieben wird.
   Sollte Claude Code den Eintrag beim Refresh nicht zurückschreiben, müssen wir die
   Quelle für M3 neu bewerten — dann wäre der Refresh-Flow doch unsere Aufgabe, entgegen
   der Clawdmeter-Haltung.

**Design-Entscheidung für M1 (dein Call):**

8. **Ring und Wochenbalken überlappen.** SPEC §7 verlangt einen Ring als äußere
   Kreisfüllung *und* die unterste 16-Pixel-Zeile als Wochenbalken. Der Ring als
   16×16-Rahmen belegt genau diese Zeile mit. Drei saubere Auflösungen:
   - **(a)** Ring nur über Zeilen 0–14 (Rahmen eines 16×15-Felds, 58 Pixel), unterste
     Zeile frei für die Woche. Beides voll lesbar, minimal asymmetrisch. *Meine Empfehlung.*
   - (b) Ring auf 14×14 eingerückt, außen umlaufend 1 px Rand frei; Wochenbalken unten.
     Symmetrisch, aber der Ring wird kürzer (52 px) und die Mitte enger für die Ziffern.
   - (c) Wochenbalken in die Ringzeile integrieren — verletzt „nicht mit den Ampelfarben
     verwechseln".

   Ohne Gegenrede baue ich (a).

---

## 8. Zusammenfassung für M1/M2

Was ohne Hardware feststeht und direkt implementiert werden kann:

- Nachrichtenrahmen, Längenfeld, 2-Byte-CRC — verifiziert.
- Bild-Frame-Layout inkl. Palettencodierung und LSB-first-Bitpacking — verifiziert.
- Drei reale Evo-Frames als Byte-genaue Testvektoren für den eigenen Encoder.
- 28 Golden-Dumps in `refs/hass-divoom/tests/goldens/Timebox/` als zusätzliche Referenz.

Was am Gerät zu klären bleibt: Pairing/MAC/Channel, Kanalpersistenz, Escaping.
Was von dir zu klären bleibt: Token (Frage 7) und Ring-Layout (Frage 8).

## 9. Gerätekopplung und macOS-Privacy-Gate (am Gerät verifiziert, 2026-08-22)

### 9.1 Es gibt keine zweite Kopplung

Die SDP-Abfrage auf der einzigen gekoppelten Divoom-Adresse liefert:

```
device 11-75-58-65-1f-91  TimeBox-Evo-audio
  connected=true  paired=true
  7 service record(s):
    - (unnamed)  rfcomm-channel=none
    - (unnamed)  rfcomm-channel=none
    - (unnamed)  rfcomm-channel=none
    - (unnamed)  rfcomm-channel=none
    - Hands-Free unit   rfcomm-channel=1
    - Hands-Free unit   rfcomm-channel=1
    - (unnamed)  rfcomm-channel=1  [SPP 0x1101]
```

Damit ist Offene Frage 1 aus Abschnitt 7 beantwortet: Die Timebox Evo hat **eine**
Bluetooth-Adresse und **eine** Kopplung. Auf derselben Adresse liegen der
Audio-Stack (HFP/A2DP/AVRCP) und der Display-Kanal nebeneinander. Der Display-Kanal
ist **SPP, UUID `0x1101`, RFCOMM-Channel 1** — exakt der Wert, den hass-divoom für
`timebox` als `port=1` annimmt.

`system_profiler` zeigt nur die gecachten Major Service Classes und verschweigt SPP.
Nur eine frische `performSDPQuery` legt den Serial-Port-Record offen. Das erklärt,
warum ditoo-clawdmeter vor jedem Verbinden eine SDP-Abfrage fährt.

**Konsequenz für die Einrichtung:** Kopplung über die normalen macOS-Bluetooth-
Einstellungen genügt. Es gibt kein `TimeBox-Evo-light`, das zusätzlich zu koppeln wäre.

### 9.2 IOBluetooth ist auf macOS 26 hinter TCC

Getestet auf macOS 26.5.2 (25F84). Jeder Zugriff auf IOBluetooth aus einem normalen
Kommandozeilenprozess endet mit SIGABRT (Exit 134) und diesem Termination-Record:

```
"namespace":"TCC"
"details":["This app has crashed because it attempted to access privacy-sensitive
data without a usage description. The app's Info.plist must contain an
NSBluetoothAlwaysUsageDescription key ..."]
```

Getestet und **nicht** ausreichend:

| Ansatz | Ergebnis |
| --- | --- |
| Nacktes CLI-Binary | Exit 134 |
| CLI-Binary mit `__TEXT,__info_plist` via `-sectcreate`, ad-hoc signiert | Exit 134 |
| `.app`-Bundle, Binary direkt per Pfad ausgeführt | Exit 134 |
| `.app`-Bundle, gestartet über `open -a … --args` | **funktioniert** |

Zur Laufzeit ist die Usage-Description in allen Bundle-Varianten korrekt sichtbar
(`Bundle.main.object(forInfoDictionaryKey:)` liefert den Text). Die TCC-Meldung ist
also irreführend: Es fehlt nicht die Beschreibung, sondern die Zuordnung zu einem
verantwortlichen Prozess. Wird der Helper aus einer Shell ge-`exec`t, prüft TCC den
Elternprozess. Erst wenn LaunchServices den Start übernimmt, ist die App ihr eigener
responsible process.

Auch nachdem die Berechtigung einmal erteilt wurde, schlägt der direkte Exec weiter
fehl. Der Umweg ist dauerhaft, kein einmaliger Freischaltschritt.

**Konsequenzen:**

- Der Bluetooth-Helper muss ein signiertes `.app`-Bundle mit
  `NSBluetoothAlwaysUsageDescription` sein, nicht nur ein Binary.
- Für M5 folgt daraus: launchd startet den Prozess selbst und ist damit sein eigener
  responsible process. **In M5 am Gerät geprüft und bestätigt** (siehe Abschnitt 11.3):
  Ein LaunchAgent darf `open -a` aufrufen und erreicht den Helper damit ohne
  zusätzliche Freigabe.
- Ein Start pro Frame über `open` schien zunächst teuer. Gemessen sind es 0,60-0,74 s
  für den gesamten Vorgang inklusive App-Start, SDP-Abfrage, Kanalaufbau, Schreiben und
  Schliessen. Bei 60 s Pollintervall ist das vernachlässigbar, ein langlebiger Prozess
  ist nicht nötig. Damit entfällt auch der Konflikt mit SPEC 5: Reconnect pro Frame ist
  hier nicht nur zulässig, sondern der einfachere und laut ditoo-clawdmeter auf macOS
  zuverlässigere Weg.


## 10. M2 Transport, am Gerät verifiziert (2026-08-22)

### 10.1 Der Encoder reproduziert echte Referenzrahmen bytegenau

`tests/test_protocol.py` prüft `claudecounter/protocol.py` nicht gegen selbst erdachte
Erwartungswerte, sondern gegen vier reale Aufzeichnungen. Jeder Rahmen wird zerlegt,
die Pixelindizes werden entpackt und anschliessend mit dem eigenen Encoder neu gebaut.
Verlangt wird Byte-Gleichheit des kompletten Pakets:

| Testvektor | Quelle | Palette |
| --- | --- | --- |
| `send_brightness` | hass-divoom Golden, Timebox | Befehl 0x74 |
| `show_image_smiley16` | hass-divoom Golden, Timebox | 32 Farben, 5 bit |
| 4-Farb-Test | divo README | 4 Farben, 2 bit |
| 8-Farb-Test | divo README | 8 Farben, 3 bit |
| 18-Farb-Test | divo README | 18 Farben, 5 bit |

Damit sind LEN, CRC, FLEN, Frame-Marker, Palettenflag, Bitbreite und die LSB-first-
Packung nicht mehr nur hergeleitet, sondern gegen fremde Aufzeichnungen belegt.

Beim ersten Anlauf schlugen die divo-Vektoren fehl, weil ich den Hex-Text mit `cut`
und `sed` aus dem README geschnitten und dabei verstümmelt hatte. Die Rahmen werden
jetzt per Regex vollständig extrahiert. Alle fünf im README enthaltenen Rahmen
validieren gegen LEN und CRC.

### 10.2 Escaping ist für die Evo nicht nötig

hass-divoom setzt `escapePayload` nur für Aurabox und TimeboxMini auf `True`.
Für `Timebox` steht explizit `False`, mit dem Kommentar, Escaping sei nicht mehr
nötig. divo escaped generell nie. Zwei unabhängige Referenzen, gleiche Aussage:
kein Byte-Stuffing von 0x01, 0x02, 0x03 im Payload.

### 10.3 Das Gerät bestätigt jedes Paket

Nach jedem gesendeten Bildbefehl antwortet die Evo auf demselben Kanal:

```
rx 01 06 00 04 44 55 f4 97 01 02
rx 01 06 00 04 44 55 22 c5 00 02
```

LEN = 6, Kommando `0x04`, drei Argumentbytes `44 55 XX`. Das erste Argument ist das
quittierte Kommando (`0x44`), die Prüfsumme stimmt in beiden Fällen exakt nach
derselben Regel wie beim Senden. Das dritte Byte variiert und ist noch nicht gedeutet.
Ein Handshake vor dem Senden ist weiterhin nirgends nötig.

### 10.4 Gemessene Laufzeiten

| Vorgang | Dauer |
| --- | --- |
| `send` komplett, drei Messungen | 0,74 s / 0,62 s / 0,60 s |
| RFCOMM-MTU der Evo | 666 Bytes |
| Paketgrösse eines gerenderten Frames | 94 bis 132 Bytes |

Ein Frame passt mit grossem Abstand in eine einzige MTU. Segmentierung ist nicht nötig.

### 10.5 Offene Punkte aus M2

- `open` liefert den Exit-Code der gestarteten App nicht zurück. Der Helper meldet
  deshalb seinen Rückgabewert selbst als letzte Zeile (`done <code>`), und der
  Transport pollt darauf. `open --wait-apps` war zusätzlich unbrauchbar, weil
  kurzlebige Kommandos wie `list` beendet sind, bevor sich `open` anhängen kann
  (`kevent() failed: No such process`).
- Ob das Gerät nach einem Neustart oder Verbindungsabbruch von selbst wieder
  annimmt, ist noch nicht geprüft. Das gehört zum Reconnect-Verhalten in M4.


## 11. M3 bis M5, Stand 2026-08-22

### 11.1 Schema des Usage-Endpoints

Belegt aus `claude-code-statusline/statusline.sh` (Zeilen 186-224), einem laufenden
Werkzeug gegen denselben Endpoint:

```
GET https://api.anthropic.com/api/oauth/usage
    Authorization: Bearer <token>
    anthropic-beta: oauth-2025-04-20
    Content-Type: application/json

{
  "five_hour":        { "utilization": <Zahl>, "resets_at": "<ISO 8601>" },
  "seven_day":        { "utilization": <Zahl>, "resets_at": "<ISO 8601>" },
  "seven_day_sonnet": { "utilization": <Zahl>, "resets_at": "<ISO 8601>" }   // optional
}
```

`five_hour` bildet `session_pct`, `seven_day` bildet `weekly_pct` aus SPEC 6.
`seven_day_sonnet` wird nicht ausgewertet.

**Nicht zu verwechseln:** Dieselbe Datei liest an anderer Stelle
`.rate_limits.five_hour.used_percentage`. Das ist das JSON, das Claude Code seiner
Statuszeile auf stdin reicht, nicht die Antwort dieses Endpoints.

**Offen:** Der Abgleich gegen den lebenden Endpoint steht noch aus, weil der Access
Token seit 2026-07-30 abgelaufen ist. `claudecounter usage --raw` gibt die Antwort
unverändert aus, sobald ein gültiges Token vorliegt. Weicht sie ab, sind nur die
Konstanten `SESSION_FIELD`, `WEEKLY_FIELD`, `UTILIZATION_KEY` und `RESETS_AT_KEY`
in `usage_source.py` zu ändern.

Ein OAuth-Refresh wurde bewusst **nicht** durchgeführt. Der Refresh rotiert
üblicherweise das Refresh-Token und könnte die laufende Claude-Code-Anmeldung
entwerten. Das ist eine Entscheidung des Nutzers, nicht des Daemons.

### 11.2 Credentials

Auf dieser Maschine existiert `~/.claude/.credentials.json` nicht, die Zugangsdaten
liegen ausschliesslich im Schlüsselbund unter `Claude Code-credentials`. `usage_source`
versucht deshalb erst die Datei, dann den Schlüsselbund. Felder im Eintrag:
`accessToken`, `refreshToken`, `expiresAt`, `refreshTokenExpiresAt`, `scopes`,
`subscriptionType`, `rateLimitTier`.

Der Ablauf wird lokal aus `expiresAt` geprüft, bevor eine Anfrage rausgeht. Ein
abgelaufenes Token kostet damit weder Netz noch Kontingent.

### 11.3 launchd und das Privacy-Gate

Die in Abschnitt 9.2 offen gelassene Frage ist beantwortet. Ein LaunchAgent unter
`gui/$UID`, der `python3 -m claudecounter send` ausführt, erreicht das Display ohne
weitere Freigabe:

```
--- stdout ---
sent session=50 weekly=50, 135 bytes to AA:BB:CC:DD:EE:FF channel 1
--- stderr ---
```

Der Weg über `open -a` bleibt dabei zwingend. Es ist nicht so, dass launchd das
TCC-Problem aufhebt, sondern dass ein launchd-Prozess `open` genauso nutzen darf
wie eine Shell.

### 11.4 Bewusste Abweichung von SPEC 5

SPEC 5 nennt Socket-Wiederverwendung. Umgesetzt ist Reconnect pro Frame, weil auf
macOS kein persistenter Socket existiert, den man wiederverwenden könnte: Jeder
Sendevorgang startet den Helper über LaunchServices neu. Gemessen kostet das
0,60 bis 0,74 s bei 60 s Pollintervall. ditoo-clawdmeter dokumentiert denselben
Weg als den auf macOS zuverlässigeren.

Statt Socket-Wiederverwendung spart der Daemon Sendevorgänge anders: Ein Frame geht
nur raus, wenn sich seine Bytes geändert haben oder der letzte erfolgreiche Versand
länger als `FORCED_RESEND_SECONDS` (600 s) her ist.

### 11.5 Fehlerverhalten, in `tests/test_daemon.py` abgesichert

| Situation | Verhalten |
| --- | --- |
| Token abgelaufen, noch nie Daten gehabt | Display bleibt unangetastet, kein 0-Prozent-Rahmen |
| Token abgelaufen, letzter Wert bekannt | letzter Wert bleibt stehen, gedimmt als `stale` |
| Endpoint nicht erreichbar | wie oben, gilt nicht als Zustellfehler |
| Display nicht erreichbar | Backoff 5, 10, 20, 40, 80 ... bis 300 s |
| Unerwartete Ausnahme | wird geloggt, Schleife läuft weiter |
| Endpoint kommt zurück | ungedimmter Rahmen wird wiederhergestellt |

Der `stale`-Rahmen wird nicht auf Farbanteile geprüft, sondern gegen den bytegenau
gerenderten Letztstand. Zusätzlich wird ausdrücklich geprüft, dass er kein
0-Prozent-Rahmen ist.

Bei dauerhaftem Fehler loggt der Daemon einmal `WARNING`, danach nur `DEBUG`, und
alle 60 Versuche ein `INFO` als Lebenszeichen. Bei 60 s Intervall ist das stündlich.

## 12. Token-Speicher und Rate-Limit (am System verifiziert, 2026-08-22)

### 12.1 Zwei getrennte Anmeldungen auf demselben Rechner

Eine Neuanmeldung in der Claude-Desktop-App erneuert den Keychain-Eintrag der
CLI **nicht**. Beobachtet: `security find-generic-password -s "Claude Code-credentials"`
trug am 22.08. noch `mdat=20260730120511Z`, während in der Desktop-App längst eine
frische Sitzung lief.

In der Keychain liegen darüber hinaus viele Einträge `Claude Code-credentials-<8 hex>`.
Die sehen nach derselben Anmeldung aus, sind es aber nicht: ihr JSON-Wurzelschlüssel
ist `mcpOAuth`, sie enthalten die OAuth-Tokens der einzelnen MCP-Server und **kein**
`claudeAiOauth`. Sie sind für diese Datenquelle wertlos. `usage_source.py` liest
weiterhin ausschließlich den unsuffigierten Eintrag — das ist richtig so.

### 12.2 Das Refresh-Token erneuert sich nur durch echte Nutzung

`claude auth status` meldet `loggedIn: true`, auch wenn `expiresAt` längst
vorbei ist — es prüft das Refresh-Token, löst den Refresh aber nicht aus und
lässt `mdat` unverändert. Erst ein Aufruf, der wirklich an die API geht
(z. B. `claude -p ...`), tauscht das Access-Token und schreibt den Keychain-Eintrag neu.

Daraus folgt: der Daemon kann sich nicht selbst aus einem abgelaufenen Token
befreien. Er erneuert bewusst nichts — ein eigener Refresh-Grant würde das
Refresh-Token rotieren und damit die Anmeldung der CLI beschädigen, wenn das
Zurückschreiben schiefgeht. Die Erneuerung bleibt Sache der CLI.

### 12.3 `api/oauth/usage` hat ein eigenes Rate-Limit

Das war ein echter Fehler im Daemon. Bei 60 s Poll-Intervall gehen 60 Anfragen
pro Stunde an den Endpunkt; er antwortet dann mit

```
HTTP 429   retry-after: 3578
{"error":{"type":"rate_limit_error","message":"Rate limited. Please try again later."}}
```

Die alte Fassung behandelte 429 wie jeden anderen HTTP-Fehler und fragte 60 s
später erneut — das hält das Limit dauerhaft am Leben.

Korrektur:

* `usage_source.RateLimited(UsageError)` trägt `retry_after` aus dem Header.
  Fehlt der Header oder ist er unbrauchbar oder `<= 0`, greift
  `FALLBACK_RETRY_AFTER_SECONDS` (900 s).
* Anfragen an den Endpunkt sind vom Zeichnen entkoppelt. Der Daemon zeichnet
  weiterhin alle `POLL_INTERVAL_SECONDS` (60 s), fragt den Endpunkt aber
  höchstens alle `USAGE_FETCH_INTERVAL_SECONDS` (300 s) — 12 statt 60 Anfragen
  pro Stunde.
* Ein 429 verlängert die Pause auf die angekündigte Dauer. Währenddessen geht
  keine einzige Anfrage raus.
* Während der Pause bleibt der letzte bekannte Wert stehen, als `stale` markiert.
  Ohne je gehabte Daten bleibt es beim `--`-Rahmen. Nie 0 Prozent.

Abgesichert in `tests/test_usage_source.py` (Header-Auswertung samt Rückfallwert,
kein Token in der Meldung) und `tests/test_daemon.py` (Anfragetakt, Pausenlänge,
Wiederaufnahme, `stale`-Verhalten).

### 12.4 Offen: liefert der Endpoint für dieses Konto überhaupt Daten?

`claude auth status` meldet `subscriptionType: null`, und ein Inferenz-Aufruf
antwortet mit „Your organization has disabled Claude subscription access for
Claude Code“. Nach dem Token-Refresh antwortet `api/oauth/usage` nicht mehr mit
401, sondern mit 429 — das Token wird also angenommen. Ob nach Ablauf des
Limits ein 200 mit `five_hour`/`seven_day` kommt oder eine Absage wegen der
Org-Einstellung, ist noch **nicht** verifiziert. Die Schema-Prüfung aus §11.1
bleibt damit offen.

## 13. Autostart beim Öffnen von Claude (M5-Ergänzung)

Der LaunchAgent startet bei der Anmeldung und läuft dauerhaft — das ist ein
Obermenge dessen, was „starte, wenn ich Claude öffne“ verlangt, deckt aber den
Fall nicht ab, dass der Agent zwischendurch ausgehängt wurde.

Ergänzend hängt jetzt ein `SessionStart`-Hook in `~/.claude/settings.json`, der
`tools/ensure_running.sh` aufruft. Das Skript hängt den Agent bei Bedarf wieder
ein und startet ihn. Es endet immer mit Status 0 und schluckt jede Ausgabe, damit
es keine Claude-Sitzung blockieren kann; fehlt die Plist, tut es gar nichts.

Verifiziert: Agent per `launchctl bootout` vollständig ausgehängt, dann eine
Claude-Sitzung gestartet — danach `runs = 1` mit neuer PID. Der Hook, nicht
`KeepAlive`, hat ihn gestartet.

`tools/session_hook.py register|unregister` trägt den Hook ein und wieder aus;
beides ist idempotent und lässt alle übrigen Einstellungen unangetastet.
`tools/install.sh` und `tools/uninstall.sh` rufen es mit auf.

## 14. Lokale Datenquelle über die Statusline (2026-08-22)

### 14.1 Korrektur zu §11.1

In §11.1 steht `.rate_limits.five_hour.used_percentage` als „Falle" — das sei nur
das stdin-JSON der Statusline und nicht die API. Der erste Teil stimmt, die
Schlussfolgerung war falsch. Genau dieses JSON ist die **bessere** Quelle:
es entsteht lokal, kostet keine API-Anfrage und kennt kein Rate-Limit.

### 14.2 Das dokumentierte Feld

Claude Code übergibt einem `statusLine`-Kommando bei jedem Neuzeichnen ein JSON
auf stdin. Darin (belegt aus <https://code.claude.com/docs/en/statusline>):

```json
"rate_limits": {
  "five_hour": { "used_percentage": 23.5, "resets_at": 1738425600 },
  "seven_day": { "used_percentage": 41.2, "resets_at": 1738857600 }
}
```

Zwei Unterschiede zur API, die beim Umrechnen zählen:

| | API `api/oauth/usage` | Statusline-stdin |
| --- | --- | --- |
| Prozentfeld | `utilization` | `used_percentage` |
| `resets_at` | ISO-8601-Text | Unix-Epoch in Sekunden |

### 14.3 Die Brücke

`tools/statusline.py` liest das JSON, schreibt `five_hour` und `seven_day` nach
`~/Library/Application Support/ClaudeCounter/usage.json` und gibt eine kurze
Zeile für die Statusline selbst aus. Geschrieben wird über eine `.partial`-Datei
mit anschließendem `replace()`, damit der Daemon nie eine halbe Datei liest.
Jeder Fehler wird geschluckt und mit Status 0 beendet — die Statusline darf
keine Claude-Sitzung stören.

`usage_source.read_local_usage()` liest die Datei. Ist das 5-Stunden-Fenster
laut `resets_at` schon abgelaufen, gilt der Stand als `stale` und wird nicht
als aktuell ausgegeben.

`usage_source.read_usage()` nimmt jetzt zuerst die lokale Datei und greift nur
zur API, wenn die Datei fehlt oder ihr Fenster übergelaufen ist. Schlägt auch
die API fehl, kommt der lokale Stand als `stale` zurück statt gar nichts.

### 14.4 Folge für den Takt

Der Daemon liest die lokale Datei bei **jedem** Durchlauf, also im 60-s-Takt,
auch während einer laufenden API-Sperre (`Daemon.local_snapshot()`). Die API
bleibt auf höchstens eine Anfrage je 300 s begrenzt und wird nur noch als
Rückfallebene gebraucht.

Verifiziert von Ende zu Ende: dokumentiertes Beispiel-JSON in `tools/statusline.py`
gegeben → `usage.json` geschrieben → `read_local_usage()` liefert 63,4 % / 28,9 %
nicht-stale → `Daemon.tick()` erzeugt ein 135-Byte-Paket, bytegleich mit
`protocol.image_packet(renderer.render(snapshot))`, beide Zeitmarker gesetzt.

### 14.5 Preis dieser Lösung

Eine eigene `statusLine` verändert die Fußzeile von Claude Code: die meisten
Tastaturhinweise verschwinden, dafür steht dort jetzt Modell, 5h, 7d und
Kontextfüllstand. `tools/session_hook.py` überschreibt eine **bereits vorhandene**
fremde `statusLine` nicht, sondern meldet das und lässt sie stehen — dann bleibt
die API die einzige Quelle.

## 15. Zeitmarker folgt der Uhr, nicht der Abfrage

Bis hierher wurde die Position beider Zeitmarker aus `snapshot.fetched_at`
berechnet. Damit stand der Punkt zwischen zwei Abfragen still, und ein
Neuzeichnen im Minutentakt änderte kein einziges Pixel.

`render()`, `session_elapsed_fraction()` und `weekly_elapsed_fraction()` nehmen
jetzt einen Bezugszeitpunkt entgegen, der ohne Angabe „jetzt" ist. Die Prozentwerte
kommen weiter aus der Messung, die Markerposition aus der Uhr.

Auflösung, damit die Erwartung stimmt: der Ring hat 58 Pixel für 5 Stunden, ein
Pixel sind also rund 5,2 Minuten. Die Wochenzeile hat 16 Pixel für 7 Tage, ein
Pixel sind 10,5 Stunden. Ein Minutentakt zeichnet also häufiger neu, als sich
sichtbar etwas ändern kann — sichtbar wird er nur bei den Prozentzahlen.

## 16. Auflösung: es war die Anmeldung (2026-08-22, 18:55)

`claude auth login` im Terminal mit dem Konto, an dem die Subscription hängt,
hat alles gelöst. Vorher `subscriptionType: null`, danach `subscriptionType: "max"`.

Die vorherigen Befunde waren also alle Folgen **einer** Ursache: der
Keychain-Eintrag der CLI trug einen degradierten Login ohne Subscription.
Daraus folgten der 429-Dauerzustand am Usage-Endpoint, die Absage
`org_level_disabled_until` bei Inferenz und die Abwesenheit von `rate_limits`
in der Statusline (die laut Doku Pro/Max voraussetzt).

### 16.1 Schema-Prüfung aus §11.1 und §12.4 abgeschlossen

Die erste echte Antwort bestätigt die in `usage_source.py` angenommene Struktur
**ohne Korrekturbedarf**:

```json
"five_hour": { "utilization": 2.0,  "resets_at": "2026-08-22T21:40:00.373029+00:00" },
"seven_day": { "utilization": 50.0, "resets_at": "2026-08-24T12:59:59.855855+00:00" }
```

`utilization` ist ein Prozentwert von 0 bis 100, `resets_at` ISO-8601 mit Zone —
genau wie angenommen. Keine der vier Konstanten musste geändert werden.

Die Antwort enthält weit mehr Felder als benötigt (`limits[]` als Liste mit
`group`/`kind`/`percent`, `spend`, `extra_usage`, dazu mehrere `null`-Felder mit
Codenamen wie `amber_ladder`, `nimbus_quill`, `tangelo`). Bewusst ignoriert:
`five_hour` und `seven_day` sind die schmalste Schnittstelle, die den Zweck
erfüllt. Insbesondere ist `limits[]` **nicht** verwendet worden, obwohl es
dieselben Zahlen trägt — es ist eine Liste variabler Länge mit optionalem
`scope`, also deutlich brüchiger als die beiden festen Objekte.

Erster echter Versand: `session 2.0% weekly 50.0%, 135 bytes sent`.

### 16.2 Was von der lokalen Quelle bleibt

Die Statusline-Brücke aus §14 bleibt eingebaut und funktioniert, hat aber zwei
Grenzen, die am Gerät belegt wurden:

* Die **Desktop-App ruft `statusLine` nicht auf.** Belegt mit der Spurdatei
  `~/Library/Logs/ClaudeCounter/statusline.log`, die bei jedem Aufruf schreibt —
  auch wenn `rate_limits` fehlt. Während eines aktiven Zuges: kein Eintrag.
  Gegenprobe im echten Pseudo-TTY mit CLI v2.1.143: die eingebaute Fußzeile
  erschien, die eigene Statusline nicht.
* `rate_limits` erscheint laut Doku nur für Pro/Max und erst nach der ersten
  API-Antwort der Sitzung.

Sie ist damit ein Zusatz für Terminal-Nutzung, nicht die Hauptquelle. Die
Hauptquelle ist wieder `api/oauth/usage` mit höchstens einer Anfrage je 300 s.
Die Fehlerbehandlung aus §12.3 bleibt wichtig, weil der Endpoint sein
Rate-Limit unabhängig davon durchsetzt.
