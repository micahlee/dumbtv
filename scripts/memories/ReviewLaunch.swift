// AXON-3095: one fixed, explicit command. Routine photo refresh never uses this path.
import Foundation
import Darwin

struct ReviewCommand: Codable {
    let contract: String
    let operationID: String
    let owner: String
    let issuedAt: Int64
    let expiresAt: Int64
    let executeBefore: Int64
    static let contract = "tv.dumbtv.review-launch/v1"
    func valid(owner expected: String) -> Bool {
        contract == Self.contract && owner == expected && !expected.isEmpty &&
            UUID(uuidString: operationID)?.uuidString.lowercased() == operationID &&
            operationID != "00000000-0000-0000-0000-000000000000"
    }
    func live(at now: Int64) -> Bool {
        issuedAt > 0 && issuedAt <= now + 5000 && issuedAt >= now - 7_200_000 &&
            expiresAt > now && expiresAt - issuedAt == 7_200_000 &&
            executeBefore > now && executeBefore <= expiresAt && executeBefore > issuedAt
    }
}

// A serial queue and retained .working receipts give at-most-once launch attempts.
// Interrupted attempts settle as uncertain; restarting never repeats a wake.
final class ReviewCommandQueue {
    let directory: URL
    let owner: String
    let now: () -> Int64
    let perform: (ReviewCommand) -> String
    init(directory: URL, owner: String, now: @escaping () -> Int64 = { Int64(Date().timeIntervalSince1970 * 1000) },
         perform: @escaping (ReviewCommand) -> String) {
        self.directory = directory; self.owner = owner; self.now = now; self.perform = perform
    }
    private func privateInfo(_ url: URL, directory: Bool = false) -> Bool {
        var info = stat()
        guard lstat(url.path, &info) == 0 else { return false }
        return info.st_uid == getuid() && info.st_mode & 0o077 == 0 &&
            info.st_mode & S_IFMT == (directory ? S_IFDIR : S_IFREG)
    }
    private func command(_ url: URL) -> ReviewCommand? {
        let fd = open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard fd >= 0 else { return nil }
        defer { close(fd) }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_uid == getuid(), info.st_mode & 0o077 == 0,
              info.st_mode & S_IFMT == S_IFREG, info.st_size > 0, info.st_size <= 2048 else { return nil }
        var bytes = [UInt8](repeating: 0, count: 2049)
        let length = read(fd, &bytes, bytes.count)
        guard length > 0, length <= 2048,
              let object = try? JSONSerialization.jsonObject(with: Data(bytes.prefix(length))) as? [String: Any],
              Set(object.keys) == Set(["contract", "operationID", "owner", "issuedAt", "expiresAt", "executeBefore"]),
              let result = try? JSONDecoder().decode(ReviewCommand.self, from: Data(bytes.prefix(length))),
              result.valid(owner: owner), result.operationID == url.deletingPathExtension().lastPathComponent else { return nil }
        return result
    }
    private func finish(_ command: ReviewCommand, status: String) {
        let result = directory.appendingPathComponent(command.operationID + ".result")
        guard !FileManager.default.fileExists(atPath: result.path) else { return }
        let tmp = directory.appendingPathComponent(".receipt-" + UUID().uuidString)
        guard let bytes = try? JSONSerialization.data(withJSONObject: ["contract": ReviewCommand.contract,
            "operationID": command.operationID, "owner": owner, "status": status]),
              FileManager.default.createFile(atPath: tmp.path, contents: bytes, attributes: [.posixPermissions: 0o600]) else { return }
        defer { try? FileManager.default.removeItem(at: tmp) }
        if let handle = try? FileHandle(forWritingTo: tmp) { try? handle.synchronize(); try? handle.close() }
        try? FileManager.default.linkItem(at: tmp, to: result)
        _ = syncDirectory()
    }
    private func syncDirectory() -> Bool {
        let fd = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        return fsync(fd) == 0
    }
    func poll() {
        guard !owner.isEmpty, privateInfo(directory, directory: true),
              let files = try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) else { return }
        for file in files.filter({ $0.pathExtension == "working" }).prefix(128) {
            if let command = command(file) { finish(command, status: "uncertain") }
        }
        for file in files.filter({ $0.pathExtension == "request" }).prefix(128) {
            guard let command = command(file) else { continue }
            let working = directory.appendingPathComponent(command.operationID + ".working")
            let result = directory.appendingPathComponent(command.operationID + ".result")
            guard !FileManager.default.fileExists(atPath: working.path),
                  !FileManager.default.fileExists(atPath: result.path) else { continue }
            // No other consumer owns this private directory. The retained claim
            // is durable before any LAN or ADB effect is allowed.
            guard rename(file.path, working.path) == 0 else { continue }
            guard syncDirectory() else { finish(command, status: "uncertain"); continue }
            guard command.live(at: now()) else { finish(command, status: "expired"); continue }
            let outcome = perform(command)
            finish(command, status: ["shown", "expired", "unavailable", "uncertain"].contains(outcome) ? outcome : "uncertain")
        }
    }
}
