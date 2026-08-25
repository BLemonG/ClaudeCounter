import AppKit
import Foundation

let counterLabel = "local.claudecounter.daemon"
let audioGuardLabel = "local.claudecounter.audioguard"

let stateDirectory = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/ClaudeCounter")
let logFile = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Logs/ClaudeCounter/claudecounter.log")
let stateFile = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/ClaudeCounter/state.json")
let agentDirectory = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/LaunchAgents")

@discardableResult
func run(_ launchPath: String, _ arguments: [String]) -> (status: Int32, output: String) {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: launchPath)
    task.arguments = arguments
    let pipe = Pipe()
    task.standardOutput = pipe
    task.standardError = pipe
    do {
        try task.run()
    } catch {
        return (-1, "")
    }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    task.waitUntilExit()
    return (task.terminationStatus, String(data: data, encoding: .utf8) ?? "")
}

func serviceTarget(_ label: String) -> String {
    return "gui/\(getuid())/\(label)"
}

func serviceIsLoaded(_ label: String) -> Bool {
    return run("/bin/launchctl", ["print", serviceTarget(label)]).status == 0
}

func startService(_ label: String) {
    let plist = agentDirectory.appendingPathComponent("\(label).plist").path
    if FileManager.default.fileExists(atPath: plist) {
        run("/bin/launchctl", ["bootstrap", "gui/\(getuid())", plist])
    }
    run("/bin/launchctl", ["kickstart", "-k", serviceTarget(label)])
}

func stopService(_ label: String) {
    run("/bin/launchctl", ["bootout", serviceTarget(label)])
}

struct Reading {
    let session: Double
    let weekly: Double
    let stale: Bool
    let moment: String
    let sessionResetsAt: Date?
}

func momentFrom(_ value: Any?) -> Date? {
    guard let text = value as? String, !text.isEmpty else { return nil }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let parsed = formatter.date(from: text) { return parsed }
    formatter.formatOptions = [.withInternetDateTime]
    return formatter.date(from: text)
}

func clockText(_ moment: Date?, _ pattern: String) -> String? {
    guard let moment = moment else { return nil }
    let formatter = DateFormatter()
    formatter.dateFormat = pattern
    return formatter.string(from: moment)
}

struct PublishedState {
    let reading: Reading?
    let trouble: String?
    let troubleReason: String?
}

func publishedState() -> PublishedState? {
    guard let data = try? Data(contentsOf: stateFile),
          let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    else { return nil }
    var reading: Reading?
    if let session = root["session_pct"] as? Double, let weekly = root["weekly_pct"] as? Double {
        reading = Reading(
            session: session,
            weekly: weekly,
            stale: (root["stale"] as? Bool) ?? false,
            moment: clockText(momentFrom(root["fetched_at"]), "HH:mm:ss") ?? "",
            sessionResetsAt: momentFrom(root["session_resets_at"])
        )
    }
    return PublishedState(
        reading: reading,
        trouble: root["trouble"] as? String,
        troubleReason: root["trouble_reason"] as? String
    )
}

func loginIsGone(_ trouble: String?) -> Bool {
    return trouble == "ExpiredCredentials" || trouble == "MissingCredentials"
}

func spokenTrouble(_ trouble: String?, _ reason: String?) -> String? {
    guard let trouble = trouble else { return nil }
    switch trouble {
    case "ExpiredCredentials":
        return "Anmeldung abgelaufen"
    case "MissingCredentials":
        return "keine Claude-Code-Anmeldung gefunden"
    case "RateLimited":
        return "zu viele Abfragen, der Zähler wartet"
    case "EndpointUnavailable":
        return "Anthropic antwortet gerade nicht"
    default:
        return reason ?? trouble
    }
}

func latestReading() -> Reading? {
    return publishedState()?.reading ?? loggedReading()
}

func loggedReading() -> Reading? {
    guard let handle = try? FileHandle(forReadingFrom: logFile) else { return nil }
    defer { try? handle.close() }
    let size = (try? handle.seekToEnd()) ?? 0
    let window = UInt64(min(size, 8192))
    try? handle.seek(toOffset: size - window)
    guard let data = try? handle.readToEnd(),
          let text = String(data: data, encoding: .utf8) else { return nil }
    let pattern = try? NSRegularExpression(
        pattern: #"^(\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})),\d+\s+INFO\s+session ([\d.]+)% weekly ([\d.]+)%( \(stale\))?"#,
        options: [.anchorsMatchLines]
    )
    guard let expression = pattern else { return nil }
    let range = NSRange(text.startIndex..<text.endIndex, in: text)
    guard let match = expression.matches(in: text, range: range).last else { return nil }
    func piece(_ index: Int) -> String {
        guard let found = Range(match.range(at: index), in: text) else { return "" }
        return String(text[found])
    }
    guard let session = Double(piece(3)), let weekly = Double(piece(4)) else { return nil }
    return Reading(
        session: session,
        weekly: weekly,
        stale: !piece(5).isEmpty,
        moment: piece(2),
        sessionResetsAt: nil
    )
}

let loginArguments = "auth login"

func claudeExecutable() -> String? {
    let home = NSHomeDirectory()
    let candidates = [
        home + "/.local/bin/claude",
        home + "/.claude/local/claude",
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ]
    for candidate in candidates where FileManager.default.isExecutableFile(atPath: candidate) {
        return candidate
    }
    let shell = Process()
    shell.executableURL = URL(fileURLWithPath: "/bin/zsh")
    shell.arguments = ["-lic", "command -v claude"]
    let pipe = Pipe()
    shell.standardOutput = pipe
    shell.standardError = FileHandle.nullDevice
    guard (try? shell.run()) != nil else { return nil }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    shell.waitUntilExit()
    let found = String(data: data, encoding: .utf8)?
        .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    return found.isEmpty ? nil : found
}

func shellQuoted(_ text: String) -> String {
    return "'" + text.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

func startLoginInTerminal() -> Bool {
    guard let claude = claudeExecutable() else { return false }
    let script = FileManager.default.temporaryDirectory
        .appendingPathComponent("claude-anmelden.command")
    let body = """
    #!/bin/zsh
    echo 'Claude Code neu anmelden. Dieses Fenster kann danach geschlossen werden.'
    echo
    \(shellQuoted(claude)) \(loginArguments)
    """
    guard (try? body.write(to: script, atomically: true, encoding: .utf8)) != nil else {
        return false
    }
    try? FileManager.default.setAttributes(
        [.posixPermissions: 0o700], ofItemAtPath: script.path
    )
    return NSWorkspace.shared.open(script)
}

func explainMissingClaude() {
    let alert = NSAlert()
    alert.messageText = "Claude Code nicht gefunden"
    alert.informativeText =
        "Das Programm claude liess sich nicht finden. Melde dich von Hand an: "
        + "ein Terminal öffnen und dort claude auth login eingeben."
    alert.runModal()
}

let sessionGreen = NSColor(srgbRed: 0.0, green: 220.0 / 255.0, blue: 80.0 / 255.0, alpha: 1.0)
let sessionYellow = NSColor(srgbRed: 245.0 / 255.0, green: 200.0 / 255.0, blue: 0.0, alpha: 1.0)
let sessionOrange = NSColor(srgbRed: 1.0, green: 120.0 / 255.0, blue: 0.0, alpha: 1.0)
let sessionRed = NSColor(srgbRed: 240.0 / 255.0, green: 40.0 / 255.0, blue: 40.0 / 255.0, alpha: 1.0)
let timeMarker = NSColor(srgbRed: 0.0, green: 190.0 / 255.0, blue: 1.0, alpha: 1.0)

let staleAlpha: CGFloat = 0.45
let iconSide: CGFloat = 20.0
let ringThickness: CGFloat = 2.2
let markerRadius: CGFloat = 1.5
let sessionWindow: TimeInterval = 5 * 60 * 60

func elapsedFraction(_ resetsAt: Date?, _ window: TimeInterval) -> Double? {
    guard let resetsAt = resetsAt else { return nil }
    let sinceWindowStart = (window - resetsAt.timeIntervalSinceNow)
        .truncatingRemainder(dividingBy: window)
    let elapsed = sinceWindowStart < 0 ? sinceWindowStart + window : sinceWindowStart
    return elapsed / window
}

func sessionColor(_ percent: Double) -> NSColor {
    if percent < 60.0 { return sessionGreen }
    if percent < 80.0 { return sessionYellow }
    if percent < 95.0 { return sessionOrange }
    return sessionRed
}

func drawTimeMarker(_ fraction: Double?, _ center: NSPoint, _ radius: CGFloat, _ stale: Bool) {
    guard let fraction = fraction else { return }
    let radians = (90.0 - 360.0 * fraction) * Double.pi / 180.0
    let spot = NSPoint(
        x: center.x + radius * CGFloat(cos(radians)),
        y: center.y + radius * CGFloat(sin(radians))
    )
    let dot = NSBezierPath(
        ovalIn: NSRect(
            x: spot.x - markerRadius,
            y: spot.y - markerRadius,
            width: markerRadius * 2.0,
            height: markerRadius * 2.0
        )
    )
    (stale ? timeMarker.withAlphaComponent(staleAlpha) : timeMarker).setFill()
    dot.fill()
}

func ringImage(percent: Double?, stale: Bool, elapsed: Double?) -> NSImage {
    let image = NSImage(size: NSSize(width: iconSide, height: iconSide), flipped: false) { _ in
        let center = NSPoint(x: iconSide / 2.0, y: iconSide / 2.0)
        let radius = (iconSide - ringThickness) / 2.0 - 0.5

        let track = NSBezierPath()
        track.appendArc(withCenter: center, radius: radius, startAngle: 0, endAngle: 360)
        track.lineWidth = ringThickness
        NSColor.labelColor.withAlphaComponent(0.22).setStroke()
        track.stroke()

        guard let value = percent else {
            let mark = NSAttributedString(
                string: "–",
                attributes: [
                    .font: NSFont.systemFont(ofSize: 10, weight: .semibold),
                    .foregroundColor: NSColor.labelColor.withAlphaComponent(0.5),
                ]
            )
            let size = mark.size()
            mark.draw(at: NSPoint(x: center.x - size.width / 2.0, y: center.y - size.height / 2.0))
            drawTimeMarker(elapsed, center, radius, stale)
            return true
        }

        let filled = max(0.0, min(100.0, value))
        if filled > 0 {
            let sweep = 360.0 * filled / 100.0
            let arc = NSBezierPath()
            arc.appendArc(
                withCenter: center,
                radius: radius,
                startAngle: 90,
                endAngle: 90 - sweep,
                clockwise: true
            )
            arc.lineWidth = ringThickness
            arc.lineCapStyle = .round
            let color = sessionColor(filled)
            (stale ? color.withAlphaComponent(staleAlpha) : color).setStroke()
            arc.stroke()
        }

        let shown = Int(filled.rounded())
        let pointSize: CGFloat = shown >= 100 ? 6.0 : (shown >= 10 ? 8.0 : 9.5)
        let digits = NSAttributedString(
            string: "\(shown)",
            attributes: [
                .font: NSFont.monospacedDigitSystemFont(ofSize: pointSize, weight: .bold),
                .foregroundColor: NSColor.labelColor.withAlphaComponent(stale ? 0.55 : 1.0),
            ]
        )
        let size = digits.size()
        digits.draw(at: NSPoint(x: center.x - size.width / 2.0, y: center.y - size.height / 2.0))
        drawTimeMarker(elapsed, center, radius, stale)
        return true
    }
    image.isTemplate = false
    return image
}

final class MenuController: NSObject, NSMenuDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let menu = NSMenu()
    private var refreshTimer: Timer?

    override init() {
        super.init()
        menu.delegate = self
        statusItem.menu = menu
        redrawTitle()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 20.0, repeats: true) { [weak self] _ in
            self?.redrawTitle()
        }
    }

    private func redrawTitle() {
        let reading = latestReading()
        statusItem.button?.title = ""
        statusItem.button?.image = ringImage(
            percent: reading?.session,
            stale: reading?.stale ?? true,
            elapsed: elapsedFraction(reading?.sessionResetsAt, sessionWindow)
        )
        statusItem.button?.toolTip = reading.map {
            "Sitzung \(Int($0.session.rounded())) % · Woche \(Int($0.weekly.rounded())) %"
        } ?? "noch kein Messwert"
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        redrawTitle()
        menu.removeAllItems()

        if let reading = latestReading() {
            let headline = reading.stale
                ? "Sitzung \(Int(reading.session.rounded())) % · Woche \(Int(reading.weekly.rounded())) % (veraltet)"
                : "Sitzung \(Int(reading.session.rounded())) % · Woche \(Int(reading.weekly.rounded())) %"
            menu.addItem(disabled(headline))
            menu.addItem(disabled("zuletzt \(reading.moment) Uhr"))
            if let resets = reading.sessionResetsAt, let at = clockText(resets, "HH:mm") {
                let elapsed = elapsedFraction(resets, sessionWindow) ?? 0.0
                menu.addItem(disabled(
                    "blauer Punkt: \(Int((elapsed * 100).rounded())) % der 5 Stunden um, frei um \(at) Uhr"
                ))
            }
        } else {
            menu.addItem(disabled("noch kein Messwert"))
        }
        let state = publishedState()
        if let spoken = spokenTrouble(state?.trouble, state?.troubleReason) {
            menu.addItem(disabled(spoken))
        }
        if loginIsGone(state?.trouble) {
            menu.addItem(action("Jetzt neu anmelden …", #selector(logInAgain)))
        }
        menu.addItem(.separator())

        let counterRuns = serviceIsLoaded(counterLabel)
        menu.addItem(disabled(counterRuns ? "Zähler läuft" : "Zähler gestoppt"))
        menu.addItem(action(counterRuns ? "Zähler stoppen" : "Zähler starten", #selector(toggleCounter)))
        menu.addItem(action("Anzeige jetzt auffrischen", #selector(askForRefresh)))
        menu.addItem(.separator())

        let guardRuns = serviceIsLoaded(audioGuardLabel)
        menu.addItem(disabled(guardRuns ? "Tonschutz läuft" : "Tonschutz gestoppt"))
        menu.addItem(action(guardRuns ? "Tonschutz stoppen" : "Tonschutz starten", #selector(toggleAudioGuard)))
        menu.addItem(.separator())

        menu.addItem(action("Bei Claude neu anmelden …", #selector(logInAgain)))
        menu.addItem(action("Protokoll öffnen", #selector(openLog)))
        menu.addItem(action("Menü beenden", #selector(leave)))
    }

    private func disabled(_ title: String) -> NSMenuItem {
        let entry = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        entry.isEnabled = false
        return entry
    }

    private func action(_ title: String, _ selector: Selector) -> NSMenuItem {
        let entry = NSMenuItem(title: title, action: selector, keyEquivalent: "")
        entry.target = self
        return entry
    }

    @objc private func toggleCounter() {
        serviceIsLoaded(counterLabel) ? stopService(counterLabel) : startService(counterLabel)
        redrawTitle()
    }

    @objc private func toggleAudioGuard() {
        serviceIsLoaded(audioGuardLabel) ? stopService(audioGuardLabel) : startService(audioGuardLabel)
    }

    @objc private func askForRefresh() {
        let request = stateDirectory.appendingPathComponent("refresh-please")
        try? Data().write(to: request)
    }

    @objc private func logInAgain() {
        if !startLoginInTerminal() {
            explainMissingClaude()
        }
    }

    @objc private func openLog() {
        NSWorkspace.shared.open(logFile)
    }

    @objc private func leave() {
        NSApp.terminate(nil)
    }
}

let application = NSApplication.shared
application.setActivationPolicy(.accessory)
let controller = MenuController()
application.run()
