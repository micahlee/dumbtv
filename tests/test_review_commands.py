"""Synthetic native queue tests: no network, ADB or household data."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('swiftc') and __import__('sys').platform == 'darwin', 'native Mac helper')
class ReviewCommands(unittest.TestCase):
    def test_expiry_denial_replay_and_interrupted_claim(self):
        with tempfile.TemporaryDirectory(prefix='review-queue-test-') as tmp:
            stage = Path(tmp)
            (stage / 'main.swift').write_text(r'''
import Foundation
import Darwin
let root = URL(fileURLWithPath: CommandLine.arguments[1])
let stamp: Int64 = 1_793_703_600_000
var effects = 0
func run(_ name: String, age: Int64 = 0, owner: String = "synthetic", mode: Int = 0o600,
         suffix: String = "request", mutate: (inout [String: Any]) -> Void = { _ in }) -> String? {
    let dir = root.appendingPathComponent(name)
    try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
    let id = UUID().uuidString.lowercased()
    var command: [String: Any] = ["contract": ReviewCommand.contract, "operationID": id, "owner": owner,
        "issuedAt": stamp - age, "expiresAt": stamp - age + 7_200_000, "executeBefore": min(stamp + 30_000, stamp - age + 7_200_000)]
    mutate(&command)
    let file = dir.appendingPathComponent(id + "." + suffix)
    let data = try! JSONSerialization.data(withJSONObject: command)
    assert(FileManager.default.createFile(atPath: file.path, contents: data, attributes: [.posixPermissions: mode]))
    let queue = ReviewCommandQueue(directory: dir, owner: "synthetic", now: { stamp }, perform: { _ in effects += 1; return "shown" })
    queue.poll(); queue.poll()
    if let data = try? Data(contentsOf: dir.appendingPathComponent(id + ".result")),
       let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any] { return result["status"] as? String }
    return nil
}
assert(run("last-ms", age: 7_199_999) == "shown")
assert(effects == 1)
assert(run("exact-cutoff", age: 7_200_000) == "expired")
assert(run("late", age: 7_200_001) == "expired")
assert(run("wrong-owner", owner: "someone-else") == nil)
assert(run("public-file", mode: 0o644) == nil)
assert(run("arbitrary-command", mutate: { $0["shell"] = "forbidden" }) == nil)
assert(run("renewed-window", mutate: { $0["expiresAt"] = stamp + 10_800_000 }) == "expired")
assert(run("future", age: -6000) == "expired")
assert(run("offline-helper-too-late", mutate: { $0["executeBefore"] = stamp }) == "expired")
assert(run("crash-recovery", suffix: "working") == "uncertain")
assert(effects == 1)
let linkDir = root.appendingPathComponent("symlinks")
try! FileManager.default.createDirectory(at: linkDir, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
let id = UUID().uuidString.lowercased()
let external = root.appendingPathComponent("external.json")
let bytes = try! JSONSerialization.data(withJSONObject: ["contract": ReviewCommand.contract, "operationID": id, "owner": "synthetic", "issuedAt": stamp, "expiresAt": stamp + 7_200_000, "executeBefore": stamp + 30_000])
try! bytes.write(to: external)
try! FileManager.default.createSymbolicLink(at: linkDir.appendingPathComponent(id + ".request"), withDestinationURL: external)
ReviewCommandQueue(directory: linkDir, owner: "synthetic", now: { stamp }, perform: { _ in effects += 1; return "shown" }).poll()
assert(effects == 1)
print("expiry, owner, strict command, permissions, symlink, replay and crash recovery passed")
''')
            subprocess.run(['swiftc', str(stage / 'main.swift'), str(ROOT / 'scripts/memories/ReviewLaunch.swift'), '-o', str(stage / 'test')], check=True, timeout=60)
            subprocess.run([str(stage / 'test'), str(stage)], check=True, timeout=10)

    def test_native_connection_prefers_exact_service_and_rejects_invalid_identity(self):
        with tempfile.TemporaryDirectory(prefix='review-endpoint-test-') as tmp:
            stage = Path(tmp)
            (stage / 'main.swift').write_text(r'''
import Foundation
import Network
let configured: [String: Any] = ["device_service": "adb-SYNTHETIC", "device": "obsolete.local:5555"]
assert(ReviewDevice.serviceSerial(configured) == "SYNTHETIC")
guard case let .service(name, type, domain, _) = ReviewDevice.networkEndpoint(configured)! else { fatalError("service was not preferred") }
assert(name == "adb-SYNTHETIC" && type == "_adb._tcp" && domain == "local.")
for invalid in ["", "Android.local", "adb-", "adb-bad._tcp.local", "adb-a\n"] {
    let bad: [String: Any] = ["device_service": invalid, "device": "obsolete.local:5555"]
    assert(ReviewDevice.networkEndpoint(bad) == nil)
}
guard case let .hostPort(host, port) = ReviewDevice.networkEndpoint(["device": "fixture.local:5556"])! else { fatalError("legacy endpoint unavailable") }
assert(String(describing: host) == "fixture.local" && port.rawValue == 5556)
print("serial-based service selection, invalid-identity denial and legacy endpoint passed")
''')
            subprocess.run(['swiftc', str(stage / 'main.swift'), str(ROOT / 'scripts/memories/ReviewDevice.swift'),
                            str(ROOT / 'scripts/memories/ReviewLaunch.swift'), '-o', str(stage / 'test')], check=True, timeout=60)
            subprocess.run([str(stage / 'test')], check=True, timeout=10)
