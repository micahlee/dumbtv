import Foundation
import Network
import Darwin

final class ReviewDevice {
    let config: [String: Any]
    let ensureServer: () -> Bool
    init(config: [String: Any], ensureServer: @escaping () -> Bool) {
        self.config = config; self.ensureServer = ensureServer
    }
    static func serviceSerial(_ config: [String: Any]) -> String? {
        guard let name = config["device_service"] as? String,
              let range = name.range(of: "adb-[A-Za-z0-9_-]{1,64}", options: .regularExpression),
              range == name.startIndex..<name.endIndex else { return nil }
        return String(name.dropFirst(4))
    }
    static func networkEndpoint(_ config: [String: Any]) -> NWEndpoint? {
        if config.keys.contains("device_service") {
            guard serviceSerial(config) != nil, let service = config["device_service"] as? String else { return nil }
            return .service(name: service, type: "_adb._tcp", domain: "local.", interface: nil)
        }
        guard let device = config["device"] as? String, let split = device.lastIndex(of: ":"),
              let port = UInt16(device[device.index(after: split)...]), port > 0 else { return nil }
        return .hostPort(host: .init(String(device[..<split])), port: .init(rawValue: port)!)
    }
    private func reachable(_ endpoint: NWEndpoint) -> Bool {
        let done = DispatchSemaphore(value: 0)
        let connection = NWConnection(to: endpoint, using: .tcp)
        var ready = false
        let queue = DispatchQueue(label: "tv.dumbtv.review.network")
        connection.stateUpdateHandler = { state in
            switch state { case .ready: ready = true; done.signal()
            case .failed: done.signal(); default: break }
        }
        connection.start(queue: queue)
        _ = done.wait(timeout: .now() + 1)
        connection.cancel()
        return queue.sync { ready }
    }
    private func wake(_ control: [String: Any]) -> Bool {
        guard let mac = control["wake_mac"] as? String, let broadcast = control["wake_broadcast"] as? String else { return false }
        let parts = mac.split(separator: ":")
        let bytes = parts.compactMap { UInt8($0, radix: 16) }
        guard parts.count == 6, bytes.count == 6 else { return false }
        var target = sockaddr_in()
        target.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        target.sin_family = sa_family_t(AF_INET)
        target.sin_port = UInt16(9).bigEndian
        guard inet_pton(AF_INET, broadcast, &target.sin_addr) == 1 else { return false }
        let fd = socket(AF_INET, SOCK_DGRAM, 0)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        var enabled: Int32 = 1
        guard setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &enabled, socklen_t(MemoryLayout.size(ofValue: enabled))) == 0 else { return false }
        let packet = [UInt8](repeating: 255, count: 6) + Array(repeating: bytes, count: 16).flatMap { $0 }
        let count = packet.withUnsafeBytes { buffer in
            withUnsafePointer(to: &target) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    sendto(fd, buffer.baseAddress, buffer.count, 0, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
        }
        return count == packet.count
    }
    private func adb(_ arguments: [String], device: String, until deadline: Date) -> String? {
        guard let executable = config["adb"] as? String else { return nil }
        let port = config["adb_port"] as? Int ?? 5038
        // An explicit server host forbids the client's local auto-start path.
        return run(executable, ["-H", "127.0.0.1", "-P", String(port), "-s", device] + arguments, until: deadline)
    }
    private func resolveDevice(until deadline: Date) -> String? {
        guard config.keys.contains("device_service") else { return config["device"] as? String }
        guard let expected = Self.serviceSerial(config), let service = config["device_service"] as? String else { return nil }
        let helper = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/TV Memories/device_service.py").path
        guard let output = run("/usr/bin/python3", [helper, service], until: deadline),
              let data = output.data(using: .utf8),
              let resolved = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              resolved["serial"] == expected else { return nil }
        return resolved["device"]
    }
    private func run(_ executable: String, _ arguments: [String], until deadline: Date) -> String? {
        guard Date() < deadline else { return nil }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent("tv-review-" + UUID().uuidString)
        guard FileManager.default.createFile(atPath: temp.path, contents: nil, attributes: [.posixPermissions: 0o600]),
              let handle = try? FileHandle(forWritingTo: temp) else { return nil }
        defer { try? handle.close(); try? FileManager.default.removeItem(at: temp) }
        process.standardOutput = handle; process.standardError = handle
        let done = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in done.signal() }
        do { try process.run() } catch { return nil }
        if done.wait(timeout: .now() + max(0, min(5, deadline.timeIntervalSinceNow))) == .timedOut {
            process.terminate()
            if done.wait(timeout: .now() + 0.5) == .timedOut { kill(process.processIdentifier, SIGKILL); _ = done.wait(timeout: .now() + 0.5) }
            return nil
        }
        guard process.terminationStatus == 0, let data = try? Data(contentsOf: temp), data.count < 262144 else { return nil }
        return String(data: data, encoding: .utf8)
    }
    func open(_ command: ReviewCommand) -> String {
        func live() -> Bool { command.live(at: Int64(Date().timeIntervalSince1970 * 1000)) }
        guard live() else { return "expired" }
        guard let control = config["review_control"] as? [String: Any], control["enabled"] as? Bool == true,
              let endpoint = Self.networkEndpoint(config) else { return "unavailable" }
        let deadline = min(Date().addingTimeInterval(27), Date(timeIntervalSince1970: Double(command.executeBefore) / 1000))
        if !reachable(endpoint) {
            guard live(), wake(control) else { return live() ? "unavailable" : "expired" }
            let wakeDeadline = min(deadline, Date().addingTimeInterval(14))
            while Date() < wakeDeadline && !reachable(endpoint) { Thread.sleep(forTimeInterval: 0.25) }
        }
        guard live() else { return "expired" }
        guard Date() < deadline, reachable(endpoint), ensureServer() else { return "unavailable" }
        Thread.sleep(forTimeInterval: 1)
        guard live(), let device = resolveDevice(until: deadline),
              let _ = adb(["connect", device], device: device, until: deadline),
              adb(["get-state"], device: device, until: deadline)?.trimmingCharacters(in: .whitespacesAndNewlines) == "device" else { return live() ? "unavailable" : "expired" }
        if config.keys.contains("device_service") {
            guard let expected = Self.serviceSerial(config),
                  adb(["shell", "getprop", "ro.serialno"], device: device, until: deadline)?.trimmingCharacters(in: .whitespacesAndNewlines) == expected
                else { return live() ? "unavailable" : "expired" }
        }
        guard live(), adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], device: device, until: deadline) != nil else { return live() ? "uncertain" : "expired" }
        let focusDeadline = min(deadline, Date().addingTimeInterval(6))
        guard live(), adb(["shell", "am", "start", "-a", "tv.dumbtv.home.OPEN_DAILY_REVIEW",
            "-n", "tv.dumbtv.home/.Home", "--el", "review.execute_before",
            String(Int64(focusDeadline.timeIntervalSince1970 * 1000))], device: device, until: focusDeadline) != nil
            else { return live() ? "uncertain" : "expired" }
        while live() && Date() < focusDeadline {
            if let focus = adb(["shell", "dumpsys", "window", "windows"], device: device, until: focusDeadline),
               focus.split(separator: "\n").contains(where: { $0.contains("mCurrentFocus") && $0.contains("tv.dumbtv.home.DailyReview") }) {
                return "shown"
            }
            Thread.sleep(forTimeInterval: 0.25)
        }
        return live() ? "uncertain" : "expired"
    }
}
