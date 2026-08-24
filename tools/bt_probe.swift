import Foundation
import IOBluetooth

var reportedExitCode: Int32 = 0

func finish(_ code: Int32) -> Never {
    reportedExitCode = code
    exit(code)
}

func note(_ text: String) {
    FileHandle.standardError.write((text + "\n").data(using: .utf8)!)
}

func formatAddress(_ device: IOBluetoothDevice) -> String {
    return device.addressString ?? "unknown"
}

func dumpServices(_ device: IOBluetoothDevice) {
    let serialPortUUID = IOBluetoothSDPUUID.uuid16(0x1101)
    guard let records = device.services as? [IOBluetoothSDPServiceRecord], !records.isEmpty else {
        print("  no SDP service records cached")
        return
    }
    print("  \(records.count) service record(s):")
    for record in records {
        var channelID: BluetoothRFCOMMChannelID = 0
        let hasChannel = record.getRFCOMMChannelID(&channelID) == kIOReturnSuccess
        let name = record.getServiceName() ?? "(unnamed)"
        let isSerialPort = record.matchesUUIDArray([serialPortUUID])
        var line = "    - \(name)"
        if hasChannel {
            line += "  rfcomm-channel=\(channelID)"
        } else {
            line += "  rfcomm-channel=none"
        }
        if isSerialPort {
            line += "  [SPP 0x1101]"
        }
        print(line)
    }
}

final class SDPProbe: NSObject {
    var finished = false

    @objc func sdpQueryComplete(_ device: IOBluetoothDevice!, status: IOReturn) {
        if status != kIOReturnSuccess {
            note("sdp query failed, status \(status)")
        }
        finished = true
    }

    func run(_ device: IOBluetoothDevice, timeout: TimeInterval) {
        let status = device.performSDPQuery(self)
        if status != kIOReturnSuccess {
            note("performSDPQuery returned \(status)")
        }
        let deadline = Date().addingTimeInterval(timeout)
        while !finished && Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        if !finished {
            note("sdp query timed out after \(timeout)s, showing cached records")
        }
    }
}

final class InquiryProbe: NSObject, IOBluetoothDeviceInquiryDelegate {
    var finished = false
    var found: [IOBluetoothDevice] = []

    func deviceInquiryDeviceFound(_ sender: IOBluetoothDeviceInquiry!, device: IOBluetoothDevice!) {
        found.append(device)
        let name = device.name ?? "(no name yet)"
        print("  found \(formatAddress(device))  \(name)")
    }

    func deviceInquiryComplete(_ sender: IOBluetoothDeviceInquiry!, error: IOReturn, aborted: Bool) {
        finished = true
    }

    func run(seconds: Int) {
        guard let inquiry = IOBluetoothDeviceInquiry(delegate: self) else {
            note("could not create inquiry")
            return
        }
        inquiry.inquiryLength = UInt8(max(1, min(60, seconds)))
        inquiry.updateNewDeviceNames = true
        let status = inquiry.start()
        if status != kIOReturnSuccess {
            note("inquiry start failed, status \(status)")
            return
        }
        let deadline = Date().addingTimeInterval(TimeInterval(seconds) + 10.0)
        while !finished && Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        inquiry.stop()
    }
}

func commandList() {
    guard let paired = IOBluetoothDevice.pairedDevices() as? [IOBluetoothDevice] else {
        print("no paired devices")
        return
    }
    print("paired devices:")
    for device in paired {
        let name = device.name ?? "(unnamed)"
        print("  \(formatAddress(device))  \(name)")
    }
}

func commandSDP(_ address: String) {
    guard let device = IOBluetoothDevice(addressString: address) else {
        note("could not resolve address \(address)")
        finish(3)
    }
    let name = device.name ?? "(unnamed)"
    print("device \(formatAddress(device))  \(name)")
    print("  connected=\(device.isConnected())  paired=\(device.isPaired())")
    SDPProbe().run(device, timeout: 10.0)
    dumpServices(device)
}

func commandScan(_ seconds: Int) {
    print("scanning \(seconds)s for discoverable devices:")
    InquiryProbe().run(seconds: seconds)
    print("scan done")
}

final class RFCOMMSender: NSObject, IOBluetoothRFCOMMChannelDelegate {
    private let packets: [[UInt8]]
    private let listenSeconds: TimeInterval
    private var openStatus: IOReturn?
    private var writeStatus: IOReturn?
    private var bytesWritten = 0
    private var channelClosed = false

    init(packets: [[UInt8]], listenSeconds: TimeInterval) {
        self.packets = packets
        self.listenSeconds = listenSeconds
    }

    func rfcommChannelOpenComplete(_ rfcommChannel: IOBluetoothRFCOMMChannel!, status error: IOReturn) {
        openStatus = error
        guard error == kIOReturnSuccess else { return }
        let mtu = rfcommChannel.getMTU()
        note("channel open, mtu \(mtu)")
        guard !packets.isEmpty else {
            writeStatus = kIOReturnSuccess
            return
        }
        for packet in packets {
            guard !packet.isEmpty else { continue }
            if packet.count > Int(mtu) {
                note("packet of \(packet.count) bytes exceeds the channel mtu of \(mtu)")
                writeStatus = kIOReturnMessageTooLarge
                return
            }
            var buffer = packet
            let length = buffer.count
            let status = buffer.withUnsafeMutableBytes { raw -> IOReturn in
                return rfcommChannel.writeSync(raw.baseAddress, length: UInt16(length))
            }
            if status != kIOReturnSuccess {
                writeStatus = status
                return
            }
            bytesWritten += length
        }
        writeStatus = kIOReturnSuccess
    }

    func rfcommChannelData(_ rfcommChannel: IOBluetoothRFCOMMChannel!, data dataPointer: UnsafeMutableRawPointer!, length: Int) {
        let received = Data(bytes: dataPointer, count: length)
        print("rx \(received.map { String(format: "%02x", $0) }.joined(separator: " "))")
    }

    func rfcommChannelClosed(_ rfcommChannel: IOBluetoothRFCOMMChannel!) {
        channelClosed = true
    }

    private func pump(untilTrue condition: () -> Bool, timeout: TimeInterval) {
        let deadline = Date().addingTimeInterval(timeout)
        while !condition() && Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
    }

    func run(address: String, channelID: BluetoothRFCOMMChannelID, openTimeout: TimeInterval) -> Int32 {
        guard let device = IOBluetoothDevice(addressString: address) else {
            note("could not resolve address \(address)")
            return 3
        }
        var channel: IOBluetoothRFCOMMChannel?
        let requestStatus = device.openRFCOMMChannelAsync(&channel, withChannelID: channelID, delegate: self)
        if requestStatus != kIOReturnSuccess {
            note("openRFCOMMChannelAsync failed, status \(requestStatus)")
            return 4
        }

        pump(untilTrue: { self.openStatus != nil }, timeout: openTimeout)
        guard let opened = openStatus else {
            note("channel open timed out after \(openTimeout)s")
            channel?.close()
            return 5
        }
        if opened != kIOReturnSuccess {
            note("channel open failed, status \(opened)")
            channel?.close()
            return 6
        }

        pump(untilTrue: { self.writeStatus != nil }, timeout: 10.0)
        guard let written = writeStatus else {
            note("write did not complete")
            channel?.close()
            return 7
        }
        if written != kIOReturnSuccess {
            note("write failed, status \(written)")
            channel?.close()
            return 8
        }

        print("wrote \(bytesWritten) bytes to rfcomm channel \(channelID)")
        if listenSeconds > 0 {
            pump(untilTrue: { self.channelClosed }, timeout: listenSeconds)
        }
        channel?.close()
        return 0
    }
}

func decodeHexLine(_ line: Substring, path: String) -> [UInt8] {
    let digits = line.filter { $0.isHexDigit }
    guard digits.count % 2 == 0, !digits.isEmpty else {
        note("every packet line must hold an even, non-zero number of hex digits")
        finish(65)
    }
    var bytes: [UInt8] = []
    var index = digits.startIndex
    while index < digits.endIndex {
        let next = digits.index(index, offsetBy: 2)
        guard let value = UInt8(digits[index..<next], radix: 16) else {
            note("invalid hex in \(path)")
            finish(65)
        }
        bytes.append(value)
        index = next
    }
    return bytes
}

func readHexPackets(path: String) -> [[UInt8]] {
    guard let text = try? String(contentsOfFile: path, encoding: .utf8) else {
        note("could not read \(path)")
        finish(66)
    }
    let lines = text.split(whereSeparator: { $0.isNewline })
    let packets = lines.filter { $0.contains(where: { $0.isHexDigit }) }
        .map { decodeHexLine($0, path: path) }
    guard !packets.isEmpty else {
        note("payload file must contain at least one packet")
        finish(65)
    }
    return packets
}

func commandSend(_ address: String, _ channelID: Int, _ path: String, _ listenSeconds: Double) {
    let packets = readHexPackets(path: path)
    let total = packets.reduce(0) { $0 + $1.count }
    print("sending \(packets.count) packet(s), \(total) bytes to \(address) channel \(channelID)")
    let sender = RFCOMMSender(packets: packets, listenSeconds: listenSeconds)
    let code = sender.run(address: address, channelID: BluetoothRFCOMMChannelID(channelID), openTimeout: 20.0)
    if code != 0 {
        finish(code)
    }
}

func commandDisconnect(_ address: String) {
    guard let device = IOBluetoothDevice(addressString: address) else {
        note("could not resolve address \(address)")
        finish(3)
    }
    guard device.isConnected() else {
        print("\(address) is already disconnected")
        return
    }
    let status = device.closeConnection()
    if status != kIOReturnSuccess {
        note("closeConnection failed, status \(status)")
        finish(9)
    }
    print("\(address) disconnected")
}

atexit {
    print("done \(reportedExitCode)")
    fflush(stdout)
}

let arguments = CommandLine.arguments
guard arguments.count >= 2 else {
    note("usage: bt_probe list | sdp <ADDRESS> | scan [SECONDS] | send <ADDRESS> <CHANNEL> <HEXFILE> [LISTEN_SECONDS] | disconnect <ADDRESS>")
    finish(64)
}

switch arguments[1] {
case "list":
    commandList()
case "sdp":
    guard arguments.count >= 3 else {
        note("usage: bt_probe sdp <ADDRESS>")
        finish(64)
    }
    commandSDP(arguments[2])
case "send":
    guard arguments.count >= 5 else {
        note("usage: bt_probe send <ADDRESS> <CHANNEL> <HEXFILE> [LISTEN_SECONDS]")
        finish(64)
    }
    guard let channelID = Int(arguments[3]) else {
        note("channel must be a number")
        finish(64)
    }
    let listenSeconds = arguments.count >= 6 ? (Double(arguments[5]) ?? 0.0) : 0.0
    commandSend(arguments[2], channelID, arguments[4], listenSeconds)
case "disconnect":
    guard arguments.count >= 3 else {
        note("usage: bt_probe disconnect <ADDRESS>")
        finish(64)
    }
    commandDisconnect(arguments[2])
case "scan":
    let seconds = arguments.count >= 3 ? (Int(arguments[2]) ?? 12) : 12
    commandScan(seconds)
default:
    note("unknown command \(arguments[1])")
    finish(64)
}
