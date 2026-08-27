import AppKit
import Foundation
import UserNotifications

let counterLabel = "local.claudecounter.daemon"
let audioGuardLabel = "local.claudecounter.audioguard"

let stateDirectory = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/ClaudeCounter")
let logFile = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Logs/ClaudeCounter/claudecounter.log")
let stateFile = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/ClaudeCounter/state.json")
let brightnessFile = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/ClaudeCounter/brightness")
let weekdaysFile = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/ClaudeCounter/weekdays")
let dayhoursFile = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/ClaudeCounter/dayhours")
let defaultBrightness = 50
let minutesPerDay = 24 * 60
let weekdayNames = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
let everyDay: Set<Int> = Set(0...6)

func activeDays() -> Set<Int> {
    guard let text = try? String(contentsOf: weekdaysFile, encoding: .utf8) else { return everyDay }
    let marks = Array(text.trimmingCharacters(in: .whitespacesAndNewlines))
    guard marks.count == 7, marks.allSatisfy({ $0 == "0" || $0 == "1" }) else { return everyDay }
    let chosen = Set(marks.indices.filter { marks[$0] == "1" })
    return chosen.isEmpty ? everyDay : chosen
}

func writeActiveDays(_ days: Set<Int>) {
    let chosen = days.isEmpty ? everyDay : days
    let marks = (0..<7).map { chosen.contains($0) ? "1" : "0" }.joined()
    try? FileManager.default.createDirectory(
        at: weekdaysFile.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try? marks.write(to: weekdaysFile, atomically: true, encoding: .utf8)
}

func spokenDays(_ days: Set<Int>) -> String {
    if days == everyDay { return "alle Tage" }
    if days == Set(0...4) { return "Mo–Fr" }
    return (0..<7).filter { days.contains($0) }.map { weekdayNames[$0] }.joined(separator: ", ")
}

struct HourWindow: Equatable {
    let opens: Int
    let shuts: Int
}

let wholeDay = HourWindow(opens: 0, shuts: minutesPerDay)

func spelledClock(_ minutes: Int) -> String {
    return String(format: "%02d:%02d", minutes / 60, minutes % 60)
}

func minutesFromClock(_ text: String) -> Int? {
    let pieces = text.trimmingCharacters(in: .whitespaces).split(separator: ":")
    guard pieces.count == 2, let hours = Int(pieces[0]), let minutes = Int(pieces[1])
    else { return nil }
    let total = hours * 60 + minutes
    guard total >= 0, total <= minutesPerDay else { return nil }
    return total
}

func hourWindowFrom(_ text: String) -> HourWindow? {
    let pieces = text.replacingOccurrences(of: "\u{2013}", with: "-").split(separator: "-")
    guard pieces.count == 2,
          let opens = minutesFromClock(String(pieces[0])),
          let shuts = minutesFromClock(String(pieces[1])),
          opens < shuts
    else { return nil }
    return HourWindow(opens: opens, shuts: shuts)
}

func activeHours() -> HourWindow {
    guard let text = try? String(contentsOf: dayhoursFile, encoding: .utf8) else { return wholeDay }
    return hourWindowFrom(text.trimmingCharacters(in: .whitespacesAndNewlines)) ?? wholeDay
}

func writeActiveHours(_ hours: HourWindow) {
    try? FileManager.default.createDirectory(
        at: dayhoursFile.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    let spelled = spelledClock(hours.opens) + "-" + spelledClock(hours.shuts) + "\n"
    try? spelled.write(to: dayhoursFile, atomically: true, encoding: .utf8)
}

let hourPresets: [HourWindow] = [
    wholeDay,
    HourWindow(opens: 6 * 60, shuts: minutesPerDay),
    HourWindow(opens: 7 * 60, shuts: minutesPerDay),
    HourWindow(opens: 8 * 60, shuts: minutesPerDay),
    HourWindow(opens: 7 * 60, shuts: 22 * 60),
    HourWindow(opens: 9 * 60, shuts: 18 * 60),
]

func spokenHours(_ hours: HourWindow) -> String {
    if hours == wholeDay { return "ganzer Tag" }
    if hours.shuts == minutesPerDay { return "ab \(spelledClock(hours.opens))" }
    return "\(spelledClock(hours.opens))\u{2013}\(spelledClock(hours.shuts))"
}

func wantedBrightness() -> Int {
    guard let text = try? String(contentsOf: brightnessFile, encoding: .utf8),
          let level = Int(text.trimmingCharacters(in: .whitespacesAndNewlines))
    else { return defaultBrightness }
    return max(0, min(100, level))
}

func writeWantedBrightness(_ level: Int) {
    try? FileManager.default.createDirectory(
        at: brightnessFile.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try? String(level).write(to: brightnessFile, atomically: true, encoding: .utf8)
}
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
    let weeklyResetsAt: Date?
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
            sessionResetsAt: momentFrom(root["session_resets_at"]),
            weeklyResetsAt: momentFrom(root["weekly_resets_at"])
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
        sessionResetsAt: nil,
        weeklyResetsAt: nil
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

func openTheNotificationSettings() {
    guard let panel = URL(
        string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension"
    ) else { return }
    NSWorkspace.shared.open(panel)
}

func explainMissingClaude() {
    let alert = NSAlert()
    alert.messageText = "Claude Code nicht gefunden"
    alert.informativeText =
        "Das Programm claude liess sich nicht finden. Melde dich von Hand an: "
        + "ein Terminal öffnen und dort claude auth login eingeben."
    alert.runModal()
}

let loginTroubleCategory = "anmeldung-abgelaufen"
let loginTroubleAction = "jetzt-anmelden"
let announceAgainAfter: TimeInterval = 6 * 60 * 60

final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Notifier()

    private var announcedTrouble: String?
    private var announcedAt: Date?
    private var allowed = false

    func begin() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        let logIn = UNNotificationAction(
            identifier: loginTroubleAction,
            title: "Jetzt anmelden",
            options: [.foreground]
        )
        center.setNotificationCategories([
            UNNotificationCategory(
                identifier: loginTroubleCategory,
                actions: [logIn],
                intentIdentifiers: [],
                options: []
            )
        ])
        center.requestAuthorization(options: [.alert, .sound]) { [weak self] granted, _ in
            DispatchQueue.main.async { self?.allowed = granted }
        }
    }

    func permissionState(_ answer: @escaping (UNAuthorizationStatus) -> Void) {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            DispatchQueue.main.async { answer(settings.authorizationStatus) }
        }
    }

    func loginIsBack() {
        announcedTrouble = nil
        announcedAt = nil
    }

    func announceLoginIsGone(_ trouble: String, _ spoken: String) {
        if announcedTrouble == trouble, let when = announcedAt,
           Date().timeIntervalSince(when) < announceAgainAfter {
            return
        }
        announcedTrouble = trouble
        announcedAt = Date()

        let note = UNMutableNotificationContent()
        note.title = "Claude-Anmeldung abgelaufen"
        note.body = spoken + ". Die Auslastung wird bis zur Neuanmeldung nicht mehr aktualisiert."
        note.categoryIdentifier = loginTroubleCategory
        note.sound = .default
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(
                identifier: loginTroubleCategory,
                content: note,
                trigger: nil
            )
        )
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler answer: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        answer([.banner, .list, .sound])
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler done: @escaping () -> Void
    ) {
        let chosen = response.actionIdentifier
        if chosen == loginTroubleAction || chosen == UNNotificationDefaultActionIdentifier {
            NSApp.activate(ignoringOtherApps: true)
            if !startLoginInTerminal() {
                explainMissingClaude()
            }
        }
        done()
    }
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

let weeklyWindow: TimeInterval = 7 * 24 * 60 * 60

func mondayBasedWeekday(_ moment: Date) -> Int {
    return (Calendar.current.component(.weekday, from: moment) + 5) % 7
}

func nextLocalMidnight(_ moment: Date) -> Date? {
    let calendar = Calendar.current
    guard let tomorrow = calendar.date(
        byAdding: .day, value: 1, to: calendar.startOfDay(for: moment)
    ) else { return nil }
    return calendar.startOfDay(for: tomorrow)
}

func localDayOpening(_ moment: Date, _ minutes: Int) -> Date {
    let calendar = Calendar.current
    let midnight = calendar.startOfDay(for: moment)
    if minutes >= minutesPerDay {
        return nextLocalMidnight(moment) ?? midnight.addingTimeInterval(TimeInterval(minutes * 60))
    }
    return calendar.date(
        bySettingHour: minutes / 60, minute: minutes % 60, second: 0, of: midnight
    ) ?? midnight.addingTimeInterval(TimeInterval(minutes * 60))
}

func activeSecondsBetween(
    _ start: Date, _ end: Date, _ days: Set<Int>, _ hours: HourWindow
) -> TimeInterval {
    var cursor = start
    var counted: TimeInterval = 0
    while cursor < end {
        guard let boundary = nextLocalMidnight(cursor), boundary > cursor else { break }
        let segmentEnd = min(boundary, end)
        if days.contains(mondayBasedWeekday(cursor)) {
            let opens = localDayOpening(cursor, hours.opens)
            let shuts = localDayOpening(cursor, hours.shuts)
            counted += max(0, min(segmentEnd, shuts).timeIntervalSince(max(cursor, opens)))
        }
        cursor = segmentEnd
    }
    return counted
}

func weeklyElapsedFraction(
    _ resetsAt: Date?, _ days: Set<Int>, _ hours: HourWindow
) -> Double? {
    guard let passingTime = elapsedFraction(resetsAt, weeklyWindow) else { return nil }
    if days == everyDay && hours == wholeDay { return passingTime }
    let now = Date()
    let windowStart = now.addingTimeInterval(-passingTime * weeklyWindow)
    let windowEnd = windowStart.addingTimeInterval(weeklyWindow)
    let wholeWindow = activeSecondsBetween(windowStart, windowEnd, days, hours)
    guard wholeWindow > 0 else { return passingTime }
    return min(1.0, activeSecondsBetween(windowStart, now, days, hours) / wholeWindow)
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
    private var notificationState: UNAuthorizationStatus = .notDetermined
    private let brightnessLabel = NSTextField(labelWithString: "")
    private let brightnessSlider = NSSlider()

    override init() {
        super.init()
        menu.delegate = self
        statusItem.menu = menu
        Notifier.shared.begin()
        redrawTitle()
        watchLogin()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 20.0, repeats: true) { [weak self] _ in
            self?.redrawTitle()
            self?.watchLogin()
        }
    }

    private func watchLogin() {
        Notifier.shared.permissionState { [weak self] status in
            self?.notificationState = status
        }
        let state = publishedState()
        if let trouble = state?.trouble, loginIsGone(trouble) {
            Notifier.shared.announceLoginIsGone(
                trouble,
                spokenTrouble(trouble, state?.troubleReason) ?? trouble
            )
        } else if state?.trouble == nil {
            Notifier.shared.loginIsBack()
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
            if let weeklyResets = reading.weeklyResetsAt {
                let days = activeDays()
                let hours = activeHours()
                let passed = weeklyElapsedFraction(weeklyResets, days, hours) ?? 0.0
                let narrowed = days != everyDay || hours != wholeDay
                let scope = narrowed ? "der gewählten Zeit" : "der Woche"
                menu.addItem(disabled(
                    "blauer Punkt Woche: \(Int((passed * 100).rounded())) % \(scope) um"
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
        if notificationState == .denied {
            menu.addItem(disabled("Mitteilungen sind abgeschaltet"))
            menu.addItem(action("Mitteilungen einschalten …", #selector(openNotificationSettings)))
        }
        menu.addItem(.separator())

        let counterRuns = serviceIsLoaded(counterLabel)
        menu.addItem(disabled(counterRuns ? "Zähler läuft" : "Zähler gestoppt"))
        menu.addItem(action(counterRuns ? "Zähler stoppen" : "Zähler starten", #selector(toggleCounter)))
        menu.addItem(action("Anzeige jetzt auffrischen", #selector(askForRefresh)))
        menu.addItem(brightnessRow(counterRuns))
        menu.addItem(weekdayChoice())
        menu.addItem(hourChoice())
        menu.addItem(.separator())

        let guardRuns = serviceIsLoaded(audioGuardLabel)
        menu.addItem(disabled(guardRuns ? "Tonschutz läuft" : "Tonschutz gestoppt"))
        menu.addItem(action(guardRuns ? "Tonschutz stoppen" : "Tonschutz starten", #selector(toggleAudioGuard)))
        menu.addItem(.separator())

        menu.addItem(action("Bei Claude neu anmelden …", #selector(logInAgain)))
        menu.addItem(action("Protokoll öffnen", #selector(openLog)))
        menu.addItem(action("Menü beenden", #selector(leave)))
    }

    private func brightnessRow(_ counterRuns: Bool) -> NSMenuItem {
        let level = wantedBrightness()
        brightnessLabel.stringValue = counterRuns
            ? "Helligkeit \(level) %"
            : "Helligkeit \(level) % (wirkt, sobald der Zähler läuft)"
        brightnessLabel.font = NSFont.menuFont(ofSize: 13)
        brightnessLabel.textColor = counterRuns ? .labelColor : .secondaryLabelColor
        brightnessLabel.frame = NSRect(x: 14, y: 25, width: 260, height: 16)

        brightnessSlider.minValue = 0
        brightnessSlider.maxValue = 100
        brightnessSlider.doubleValue = Double(level)
        brightnessSlider.isContinuous = true
        brightnessSlider.target = self
        brightnessSlider.action = #selector(brightnessMoved(_:))
        brightnessSlider.frame = NSRect(x: 14, y: 3, width: 260, height: 20)

        let row = NSView(frame: NSRect(x: 0, y: 0, width: 288, height: 46))
        row.addSubview(brightnessLabel)
        row.addSubview(brightnessSlider)

        let entry = NSMenuItem()
        entry.view = row
        return entry
    }

    private func weekdayChoice() -> NSMenuItem {
        let chosen = activeDays()
        let days = NSMenu()
        days.autoenablesItems = false
        for day in 0..<7 {
            let entry = NSMenuItem(
                title: weekdayNames[day],
                action: #selector(toggleWeekday(_:)),
                keyEquivalent: ""
            )
            entry.target = self
            entry.tag = day
            entry.state = chosen.contains(day) ? .on : .off
            entry.isEnabled = !(chosen.count == 1 && chosen.contains(day))
            days.addItem(entry)
        }
        days.addItem(.separator())
        let everything = NSMenuItem(
            title: "Alle Tage zählen",
            action: #selector(countEveryDay),
            keyEquivalent: ""
        )
        everything.target = self
        everything.isEnabled = chosen != everyDay
        days.addItem(everything)

        let entry = NSMenuItem(
            title: "Wochenpunkt zählt: \(spokenDays(chosen))",
            action: nil,
            keyEquivalent: ""
        )
        entry.submenu = days
        return entry
    }

    private func hourChoice() -> NSMenuItem {
        let chosen = activeHours()
        let spans = NSMenu()
        spans.autoenablesItems = false
        for preset in hourPresets {
            let entry = NSMenuItem(
                title: spokenHours(preset),
                action: #selector(pickHours(_:)),
                keyEquivalent: ""
            )
            entry.target = self
            entry.tag = preset.opens * 10000 + preset.shuts
            entry.state = preset == chosen ? .on : .off
            spans.addItem(entry)
        }
        if !hourPresets.contains(chosen) {
            spans.addItem(.separator())
            let current = NSMenuItem(title: spokenHours(chosen), action: nil, keyEquivalent: "")
            current.state = .on
            current.isEnabled = false
            spans.addItem(current)
        }

        let entry = NSMenuItem(
            title: "Wochenpunkt zählt Stunden: \(spokenHours(chosen))",
            action: nil,
            keyEquivalent: ""
        )
        entry.submenu = spans
        return entry
    }

    @objc private func pickHours(_ sender: NSMenuItem) {
        writeActiveHours(
            HourWindow(opens: sender.tag / 10000, shuts: sender.tag % 10000)
        )
    }

    @objc private func toggleWeekday(_ sender: NSMenuItem) {
        var chosen = activeDays()
        if chosen.contains(sender.tag) {
            guard chosen.count > 1 else { return }
            chosen.remove(sender.tag)
        } else {
            chosen.insert(sender.tag)
        }
        writeActiveDays(chosen)
    }

    @objc private func countEveryDay() {
        writeActiveDays(everyDay)
    }

    @objc private func brightnessMoved(_ slider: NSSlider) {
        let level = Int(slider.doubleValue.rounded())
        brightnessLabel.stringValue = "Helligkeit \(level) %"
        writeWantedBrightness(level)
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

    @objc private func openNotificationSettings() {
        openTheNotificationSettings()
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
