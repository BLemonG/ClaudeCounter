import CoreAudio
import Foundation

let systemObject = AudioObjectID(kAudioObjectSystemObject)

struct GuardedDirection {
    let label: String
    let scope: AudioObjectPropertyScope
    let selectors: [AudioObjectPropertySelector]
    let rememberedFileName: String
    let preferredTransports: [UInt32]
}

let guardedDirections = [
    GuardedDirection(
        label: "output",
        scope: AudioObjectPropertyScope(kAudioObjectPropertyScopeOutput),
        selectors: [
            kAudioHardwarePropertyDefaultOutputDevice,
            kAudioHardwarePropertyDefaultSystemOutputDevice,
        ],
        rememberedFileName: "last-good-output",
        preferredTransports: [
            kAudioDeviceTransportTypeBluetooth,
            kAudioDeviceTransportTypeBluetoothLE,
            kAudioDeviceTransportTypeBuiltIn,
        ]
    ),
    GuardedDirection(
        label: "input",
        scope: AudioObjectPropertyScope(kAudioObjectPropertyScopeInput),
        selectors: [kAudioHardwarePropertyDefaultInputDevice],
        rememberedFileName: "last-good-input",
        preferredTransports: [
            kAudioDeviceTransportTypeBuiltIn,
            kAudioDeviceTransportTypeBluetooth,
            kAudioDeviceTransportTypeBluetoothLE,
        ]
    ),
]

func propertyAddress(
    _ selector: AudioObjectPropertySelector,
    scope: AudioObjectPropertyScope = AudioObjectPropertyScope(kAudioObjectPropertyScopeGlobal)
) -> AudioObjectPropertyAddress {
    return AudioObjectPropertyAddress(
        mSelector: selector,
        mScope: scope,
        mElement: AudioObjectPropertyElement(kAudioObjectPropertyElementMain)
    )
}

let momentFormatter: DateFormatter = {
    let formatter = DateFormatter()
    formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
    return formatter
}()

func stamped(_ message: String) -> String {
    return momentFormatter.string(from: Date()) + "  " + message
}

func note(_ message: String) {
    FileHandle.standardError.write(Data((stamped(message) + "\n").utf8))
}

func announce(_ message: String) {
    print(stamped(message))
    fflush(stdout)
}

func stringProperty(_ device: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String {
    var address = propertyAddress(selector)
    var value: CFString = "" as CFString
    var size = UInt32(MemoryLayout<CFString>.size)
    let status = withUnsafeMutablePointer(to: &value) { pointer -> OSStatus in
        return AudioObjectGetPropertyData(device, &address, 0, nil, &size, pointer)
    }
    return status == noErr ? value as String : ""
}

func deviceName(_ device: AudioObjectID) -> String {
    return stringProperty(device, kAudioObjectPropertyName)
}

func deviceUniqueIdentifier(_ device: AudioObjectID) -> String {
    return stringProperty(device, kAudioDevicePropertyDeviceUID)
}

func deviceTransport(_ device: AudioObjectID) -> UInt32 {
    var address = propertyAddress(kAudioDevicePropertyTransportType)
    var value: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    let status = AudioObjectGetPropertyData(device, &address, 0, nil, &size, &value)
    return status == noErr ? value : 0
}

func carriesChannels(_ device: AudioObjectID, scope: AudioObjectPropertyScope) -> Bool {
    var address = propertyAddress(kAudioDevicePropertyStreamConfiguration, scope: scope)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(device, &address, 0, nil, &size) == noErr, size > 0 else {
        return false
    }
    let storage = UnsafeMutableRawPointer.allocate(
        byteCount: Int(size),
        alignment: MemoryLayout<AudioBufferList>.alignment
    )
    defer { storage.deallocate() }
    guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, storage) == noErr else {
        return false
    }
    let buffers = UnsafeMutableAudioBufferListPointer(storage.assumingMemoryBound(to: AudioBufferList.self))
    return buffers.reduce(0) { $0 + Int($1.mNumberChannels) } > 0
}

func devicesCarrying(_ scope: AudioObjectPropertyScope) -> [AudioObjectID] {
    var address = propertyAddress(kAudioHardwarePropertyDevices)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(systemObject, &address, 0, nil, &size) == noErr, size > 0 else {
        return []
    }
    var devices = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(systemObject, &address, 0, nil, &size, &devices) == noErr else {
        return []
    }
    return devices.filter { carriesChannels($0, scope: scope) }
}

func currentDefault(_ selector: AudioObjectPropertySelector) -> AudioObjectID {
    var address = propertyAddress(selector)
    var device = AudioObjectID(0)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    let status = AudioObjectGetPropertyData(systemObject, &address, 0, nil, &size, &device)
    return status == noErr ? device : 0
}

func makeDefault(_ device: AudioObjectID, _ selector: AudioObjectPropertySelector) -> Bool {
    var address = propertyAddress(selector)
    var target = device
    return AudioObjectSetPropertyData(
        systemObject,
        &address,
        0,
        nil,
        UInt32(MemoryLayout<AudioObjectID>.size),
        &target
    ) == noErr
}

final class DirectionGuard {
    private let direction: GuardedDirection
    private let unwantedFragment: String
    private let rememberedPath: URL
    private var rememberedUniqueIdentifier: String?
    private let queue: DispatchQueue

    init(direction: GuardedDirection, unwantedFragment: String, stateDirectory: URL) {
        self.direction = direction
        self.unwantedFragment = unwantedFragment.lowercased()
        self.rememberedPath = stateDirectory.appendingPathComponent(direction.rememberedFileName)
        self.queue = DispatchQueue(label: "local.claudecounter.audioguard.\(direction.label)")
        let stored = try? String(contentsOf: rememberedPath, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        self.rememberedUniqueIdentifier = (stored?.isEmpty == false) ? stored : nil
    }

    private func isUnwanted(_ device: AudioObjectID) -> Bool {
        guard device != 0 else { return false }
        return deviceName(device).lowercased().contains(unwantedFragment)
    }

    private func remember(_ device: AudioObjectID) {
        let identifier = deviceUniqueIdentifier(device)
        guard !identifier.isEmpty, identifier != rememberedUniqueIdentifier else { return }
        rememberedUniqueIdentifier = identifier
        try? identifier.write(to: rememberedPath, atomically: true, encoding: .utf8)
    }

    private func replacement() -> AudioObjectID? {
        let candidates = devicesCarrying(direction.scope).filter { !isUnwanted($0) }
        guard !candidates.isEmpty else { return nil }
        if let identifier = rememberedUniqueIdentifier,
           let stored = candidates.first(where: { deviceUniqueIdentifier($0) == identifier }) {
            return stored
        }
        for transport in direction.preferredTransports {
            if let match = candidates.first(where: { deviceTransport($0) == transport }) {
                return match
            }
        }
        let physical = candidates.first { deviceTransport($0) != kAudioDeviceTransportTypeVirtual }
        return physical ?? candidates.first
    }

    private func enforce(_ selector: AudioObjectPropertySelector) {
        let device = currentDefault(selector)
        guard device != 0 else { return }
        if !isUnwanted(device) {
            remember(device)
            return
        }
        guard let chosen = replacement() else {
            note("no other \(direction.label) device available, leaving \(deviceName(device)) in place")
            return
        }
        if makeDefault(chosen, selector) {
            remember(chosen)
            announce("moved \(direction.label) from \(deviceName(device)) back to \(deviceName(chosen))")
        } else {
            note("could not move \(direction.label) away from \(deviceName(device))")
        }
    }

    func start() {
        for selector in direction.selectors {
            var address = propertyAddress(selector)
            let status = AudioObjectAddPropertyListenerBlock(systemObject, &address, queue) { [weak self] _, _ in
                self?.enforce(selector)
            }
            if status != noErr {
                note("could not watch the \(direction.label) default, status \(status)")
                exit(2)
            }
        }
        queue.async {
            for selector in self.direction.selectors {
                self.enforce(selector)
            }
        }
    }
}

let arguments = CommandLine.arguments
guard arguments.count >= 2, !arguments[1].isEmpty else {
    note("usage: audio_guard <NAME FRAGMENT TO AVOID> [STATE DIRECTORY]")
    exit(1)
}

let stateDirectory = arguments.count >= 3
    ? URL(fileURLWithPath: arguments[2])
    : FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/ClaudeCounter")

try? FileManager.default.createDirectory(at: stateDirectory, withIntermediateDirectories: true)

let guards = guardedDirections.map {
    DirectionGuard(direction: $0, unwantedFragment: arguments[1], stateDirectory: stateDirectory)
}
for one in guards {
    one.start()
}
announce("watching the default input and output, keeping them away from names containing \(arguments[1])")
CFRunLoopRun()
