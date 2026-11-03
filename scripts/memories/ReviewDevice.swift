import Foundation
import Network
import Darwin

final class ReviewDevice {
    let config: [String: Any]
    let ensureServer: () -> Bool
    init(config: [String: Any], ensureServer: @escaping () -> Bool) {
        self.config = config; self.ensureServer = ensureServer
    }
    private func reachable(_ host: String) -> Bool {
        let done = DispatchSemaphore(value: 0)
        let connection = NWConnection(host: NWEndpoint.Host(host), port: 5555, using: .tcp)
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
    private func adb(_ arguments: [String], until deadline: Date) -> String? {
        guard Date() < deadline, let executable = config["adb"] as? String,
              let device = config["device"] as? String else { return nil }
        let port = config["adb_port"] as? Int ?? 5038
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        // An explicit server host forbids the client's local auto-start path.
        process.arguments = ["-H", "127.0.0.1", "-P", String(port), "-s", device] + arguments
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
              let device = config["device"] as? String, let host = device.split(separator: ":").first else { return "unavailable" }
        let deadline = min(Date().addingTimeInterval(27), Date(timeIntervalSince1970: Double(command.executeBefore) / 1000))
        if !reachable(String(host)) {
            guard live(), wake(control) else { return live() ? "unavailable" : "expired" }
            let wakeDeadline = min(deadline, Date().addingTimeInterval(14))
            while Date() < wakeDeadline && !reachable(String(host)) { Thread.sleep(forTimeInterval: 0.25) }
        }
        guard live() else { return "expired" }
        guard Date() < deadline, reachable(String(host)), ensureServer() else { return "unavailable" }
        Thread.sleep(forTimeInterval: 1)
        guard live(), let _ = adb(["connect", device], until: deadline),
              adb(["get-state"], until: deadline)?.trimmingCharacters(in: .whitespacesAndNewlines) == "device" else { return live() ? "unavailable" : "expired" }
        guard live(), adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], until: deadline) != nil else { return live() ? "uncertain" : "expired" }
        guard live(), adb(["shell", "am", "start", "-n", "tv.dumbtv.home/.Home"], until: deadline) != nil else { return live() ? "uncertain" : "expired" }
        Thread.sleep(forTimeInterval: 3)
        guard live(), adb(["shell", "am", "start", "-n", "tv.dumbtv.home/.DailyReview"], until: deadline) != nil else { return live() ? "uncertain" : "expired" }
        guard let focus = adb(["shell", "dumpsys", "window", "windows"], until: deadline),
              focus.split(separator: "\n").contains(where: { $0.contains("mCurrentFocus") && $0.contains("tv.dumbtv.home.DailyReview") }) else { return "uncertain" }
        return "shown"
    }
}
