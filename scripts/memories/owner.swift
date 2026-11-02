// A login-session application gives macOS a stable identity for local-network consent.
// It owns the foreground ADB server and hourly sync; no laptop or cloud tokens are involved.
import AppKit
import Foundation
import Network

final class PhotoOwner: NSObject, NSApplicationDelegate {
    private var item: NSStatusItem!
    private var status: NSMenuItem!
    private var config: [String: Any] = [:]
    private let root = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/TV Memories")
    private var server: Process?
    private var sync: Process?
    private var connection: NWConnection?
    private var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "TV Photos"
        let menu = NSMenu()
        status = NSMenuItem(title: "Starting…", action: nil, keyEquivalent: "")
        menu.addItem(status)
        let refresh = NSMenuItem(title: "Refresh now", action: #selector(refreshNow), keyEquivalent: "")
        refresh.target = self; menu.addItem(refresh)
        menu.addItem(NSMenuItem.separator())
        let quit = NSMenuItem(title: "Quit until next login", action: #selector(quitOwner), keyEquivalent: "")
        quit.target = self; menu.addItem(quit)
        item.menu = menu
        guard let data = try? Data(contentsOf: root.appendingPathComponent("config.json")),
              let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            status.title = "Photo setup is incomplete"; return
        }
        config = parsed
        timer = Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { [weak self] _ in
            self?.refreshNow()
        }
        refreshNow()
    }

    @objc private func refreshNow() {
        guard sync == nil, connection == nil,
              let device = config["device"] as? String,
              let host = device.split(separator: ":").first else { return }
        status.title = "Checking the TV…"
        // This ordinary Network-framework connection requests Local Network consent
        // for this app bundle. It is not a proxy: ADB performs all subsequent transfers.
        let check = NWConnection(host: NWEndpoint.Host(String(host)), port: 5555, using: .tcp)
        connection = check
        check.stateUpdateHandler = { [weak self, weak check] state in
            guard let self = self else { return }
            switch state {
            case .ready:
                check?.stateUpdateHandler = nil; check?.cancel()
                self.connection = nil
                self.startServerAndRefresh()
            case .waiting, .failed:
                check?.stateUpdateHandler = nil; check?.cancel()
                self.connection = nil
                self.status.title = "TV unavailable or network access needed"
            default: break
            }
        }
        check.start(queue: .main)
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self, weak check] in
            guard let self = self, self.connection === check else { return }
            check?.stateUpdateHandler = nil; check?.cancel(); self.connection = nil
            self.status.title = "TV asleep; cached photos remain available"
        }
    }

    private func log(_ name: String) -> FileHandle? {
        let url = root.appendingPathComponent(name)
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil,
                                          attributes: [.posixPermissions: 0o600])
        }
        let handle = try? FileHandle(forWritingTo: url)
        handle?.seekToEndOfFile()
        return handle
    }

    private func startServerAndRefresh() {
        guard let adb = config["adb"] as? String else { return }
        if server?.isRunning != true {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: adb)
            let port = config["adb_port"] as? Int ?? 5038
            process.arguments = ["-P", String(port), "nodaemon", "server"]
            process.standardOutput = log("adb-server.log")
            process.standardError = process.standardOutput
            do { try process.run(); server = process }
            catch { status.title = "TV connection helper could not start"; return }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in self?.runRefresh() }
    }

    private func runRefresh() {
        guard sync == nil, server?.isRunning == true else {
            status.title = "TV connection helper stopped"; return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [root.appendingPathComponent("sync.py").path,
                             "--config", root.appendingPathComponent("config.json").path]
        process.standardOutput = log("refresh.log")
        process.standardError = process.standardOutput
        process.terminationHandler = { [weak self] child in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.sync = nil
                let url = self.root.appendingPathComponent("cache/status.json")
                if child.terminationStatus == 0,
                   let data = try? Data(contentsOf: url),
                   let state = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let count = state["photos"] as? Int {
                    self.status.title = state["status"] as? String == "published"
                        ? "\(count) photos ready on the TV" : "TV asleep; \(count) photos prepared"
                } else { self.status.title = "Refresh needs attention; TV cache retained" }
            }
        }
        status.title = "Refreshing photo memories…"
        do { try process.run(); sync = process }
        catch { status.title = "Photo refresh could not start" }
    }

    @objc private func quitOwner() { NSApplication.shared.terminate(nil) }
    func applicationWillTerminate(_ notification: Notification) {
        connection?.cancel(); timer?.invalidate()
        if sync?.isRunning == true { sync?.terminate() }
        if server?.isRunning == true { server?.terminate() }
    }
}

let app = NSApplication.shared
let delegate = PhotoOwner()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
