# SPEC: Divoom Timebox Evo als Claude-Usage-Anzeige

## 1. Auftrag

Ein macOS-Daemon zeigt den aktuellen Claude-Verbrauch (5h-Session + Wochenlimit) permanent auf dem 16x16-Display einer Divoom Timebox Evo an, angebunden über Bluetooth RFCOMM.

Kein iOS-App-Projekt. Keine Divoom-App-Integration. Die Divoom-App wird komplett umgangen.

## 2. Umgebung

- macOS, Apple Silicon
- Timebox Evo dauerhaft am Schreibtisch, gepairt, in Reichweite
- Claude Code lokal eingeloggt (Token liegt in `~/.claude/.credentials.json` oder im macOS-Keychain unter dem Service `Claude Code-credentials`)
- Python 3.11+, Xcode Command Line Tools (`swiftc`), Homebrew

## 3. Referenz-Repos

Vor dem ersten Codeschreiben klonen und lesen. Nicht raten, was drinsteht — reinschauen.

| Repo | Rolle im Projekt |
|---|---|
| `ismkdc/ditoo-clawdmeter` | **Hauptbasis.** Divoom 16x16 + Claude Usage, macOS-Bluetooth via Swift/IOBluetooth, Renderer, CLI-Struktur. Zielgerät ist der Ditoo, nicht die Evo. |
| `HermannBjorgvin/Clawdmeter` | **Datenschicht.** Ursprungsprojekt. Der Daemon (`daemon/claude-usage-daemon.sh`) liest den OAuth-Token, pollt die Usage und pusht alle 60s. Die Poll-, Reconnect- und Token-Refresh-Logik ist hier am ausgereiftesten. |
| `RomRider/node-divoom-timebox-evo` | **Protokoll-Referenz.** `PROTOCOL.md` ist die maßgebliche Doku für die Timebox Evo. |
| `spezifisch/divo` | **Evo-Gegenprobe.** Python, unterstützt Timebox Evo explizit, enthält funktionierende Raw-Frames zum Kreuztesten. GPL-3.0 — Code nur als Referenz lesen, nicht kopieren. |
| `d03n3rfr1tz3/hass-divoom` | **Fallback-Protokollimplementierung** in Python, mehrere Divoom-Geräte, aktiv gepflegt. Quelle für Channel-/Escaping-Verhalten. |
| `ohugonnot/claude-code-statusline` | **Endpoint-Referenz** für `api/oauth/usage` und Token-Handling. |

Es gibt Stand heute **kein** Repo für Timebox Evo + Claude Usage. Das ist der Teil, den wir bauen.

## 4. Zielarchitektur

```
[Anthropic API] -> usage_source.py -> Snapshot(JSON)
                                        |
                                        v
                                   render.py -> 16x16 RGB-Frame (Pillow)
                                        |
                                        v
                             protocol.py -> Divoom-Paket (Byteframe)
                                        |
                                        v
                       transport_macos (Swift/IOBluetooth) -> RFCOMM -> Timebox Evo
```

Vier klar getrennte Schichten. Jede muss isoliert testbar sein — Renderer ohne Hardware, Protokoll ohne Netz, Datenquelle ohne Display.

## 5. Harte Constraints

**Bluetooth / Timebox Evo**

- RFCOMM-Channel **1** (nicht 2 wie beim Ditoo).
- Die Evo sendet beim Connect **kein `HELLO`**. Ältere Timeboxen tun das. Wenn der Code nach dem Verbinden blockierend liest, hängt er. Prüfen und ggf. entfernen.
- Es gibt zwei Bluetooth-Identitäten: `Timebox-evo-audio` und `Timebox-evo-light`. Nur die Light-Seite erreicht das Display. Ein `/dev/cu.*-audio`-Port führt garantiert ins Leere.
- Payload-Escaping (`0x01/0x02/0x03`) ist bei neuerer Firmware nicht nötig, bei älterer schon. Als konfigurierbaren Schalter bauen, Default aus. Wenn Bilder verschoben oder zerrissen ankommen, ist das der erste Verdacht — nicht der Renderer.
- Socket **offen halten**. Nicht pro Update neu verbinden.

**Datenquelle**

- Primär: `https://api.anthropic.com/api/oauth/usage` mit dem Claude-Code-OAuth-Token. Liefert 5h- und 7d-Utilization in Prozent plus ISO-Reset-Zeitstempel. **Undokumentiert** — Struktur zuerst per `curl` verifizieren und das tatsächliche Response-Schema in `docs/findings.md` festhalten, bevor Parsing-Code entsteht.
- **Nicht** die `/v1/messages`-Header-Variante (`anthropic-ratelimit-unified-5h-utilization`) als Primärquelle verwenden. Sie verbraucht Quota, um Quota zu messen, und liefert das Wochenlimit nicht. Höchstens als Fallback.
- **Nicht** ccusage oder JSONL-Parsing verwenden. Das sind Schätzungen aus lokalen Logs und weichen nachweislich von den echten Werten ab.
- Polling-Intervall 60s, innere Schleife alle 5s für schnelle Disconnect-Erkennung.
- Bei Token-Ablauf, Netzfehler oder HTTP-Fehler: letzten bekannten Wert weiter anzeigen und als `stale` markieren. Niemals crashen, niemals das Display auf 0% setzen.

**Code**

- Keine Kommentare im Code — weder inline noch zeilenweise. Sprechende Namen statt Kommentaren.
- Keine Secrets ins Repo, kein Token in Logs, keine Tokenwerte in Fehlermeldungen.

## 6. Datenkontrakt

Interne Repräsentation zwischen Datenquelle und Renderer:

```json
{
  "session_pct": 0,
  "session_resets_at": "ISO8601",
  "weekly_pct": 0,
  "weekly_resets_at": "ISO8601",
  "fetched_at": "ISO8601",
  "stale": false
}
```

Der Renderer kennt ausschließlich diese Struktur. Er darf nie direkt auf die API zugreifen.

## 7. Render-Spec (16x16)

- **Äußerer Ring**: 5h-Session-Auslastung als Kreisfüllung. Farbschwellen: 0–59 grün, 60–79 gelb, 80–94 orange, 95–100 rot.
- **Mitte**: zweistellige Prozentzahl der Session. Bei 100 einstellig auf `!!` oder Vollfläche ausweichen — dreistellig ist auf 16x16 nicht lesbar.
- **Unterste Pixelzeile (16 Pixel)**: Wochenlimit als horizontaler Balken in eigener Akzentfarbe (z.B. blau/violett), damit er nicht mit den Ring-Ampelfarben verwechselt wird.
- **Stale-Zustand**: Ring gedimmt oder ein einzelnes Eckpixel als Indikator. Kein Blinken.
- Nicht zwischen Session und Woche alternieren. Beides muss gleichzeitig ablesbar sein.

Jeder Renderpfad muss ohne Hardware als PNG ausgebbar sein (`preview`-Kommando), skaliert auf mindestens 256x256 zur Sichtprüfung.

## 8. Meilensteine

Streng der Reihe nach. Nach jedem Meilenstein stoppen und Ergebnis berichten.

**M0 — Recherche**
Repos aus Abschnitt 3 klonen (nach `refs/`, nicht ins Projekt). `PROTOCOL.md` und die Protokollmodule von ditoo-clawdmeter und divo lesen. Ergebnis: `docs/findings.md` mit — Aufbau eines Divoom-Frames, konkretes Bildkommando für die Evo, Unterschiede Ditoo/Evo, offene Fragen.
*Abnahme:* findings.md existiert und beantwortet, ob das Ditoo-Bildkommando unverändert für die Evo taugt.

**M1 — Renderer ohne Hardware**
`render.py` + `preview`-CLI. Ring, Zahl, Wochenbalken, Stale-Zustand. PNG-Output.
*Abnahme:* `preview --session 82 --weekly 41` erzeugt ein PNG, das der Spec entspricht. Kein Bluetooth, kein Netz.

**M2 — Transport**
Swift-Helper aus ditoo-clawdmeter bauen. `list-devices`, `configure --channel 1 --mac ...`, Rohbytes senden.
*Abnahme:* Ein statisches Testbild erscheint auf der Timebox Evo.
*Stopp-Regel:* Wenn hier nach zwei Ansätzen nichts ankommt, nicht weiterbauen — stattdessen einen bekannten Raw-Frame aus dem divo-README senden, um Transport von Protokoll zu trennen, und melden.

**M3 — Datenquelle**
`usage_source.py`. Token laden (Datei und Keychain), Endpoint abfragen, Snapshot bauen, Fehlerpfade. Vorher per `curl` das echte Schema prüfen.
*Abnahme:* `usage --json` gibt einen validen Snapshot aus, dessen Werte mit `/usage` in Claude Code übereinstimmen.

**M4 — Daemon**
Poll-Schleife 60s, Socket-Wiederverwendung, Reconnect mit Backoff, Stale-Handling, Logging nach `~/Library/Logs/`.
*Abnahme:* Läuft 30 Minuten durch, überlebt einmaliges Ausschalten der Timebox und einen Netzausfall.

**M5 — Autostart**
`launchd`-Agent (`~/Library/LaunchAgents/`), `KeepAlive`, Start bei Login. Install-/Uninstall-Skript.
*Abnahme:* Nach Neustart läuft die Anzeige ohne manuellen Eingriff.

**M6 — README**
Setup, Troubleshooting-Sektion mit den Fallstricken aus Abschnitt 5.

## 9. Verbote

- Keine iOS-App, keine Divoom-App-Integration, kein WLAN-Pfad.
- Kein Copy-Paste aus GPL-Code (divo, hass-divoom) ohne bewusste Lizenzentscheidung. Als Referenz lesen ist in Ordnung.
- Keine Meilensteine überspringen, kein "ich baue schon mal M4 vor".
- Keine erfundenen Byte-Sequenzen. Jedes Protokoll-Byte muss aus einer der Referenzen belegbar sein oder am Gerät verifiziert werden.
- Keine Kommentare im Code.
