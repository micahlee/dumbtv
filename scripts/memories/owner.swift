// A login-session application gives macOS a stable identity for local-network consent.
// It owns the foreground ADB server and hourly sync on the configured Mac.
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
    private var retryTimer: Timer?
    private var commandTimer: DispatchSourceTimer?
    private let commandQueue = DispatchQueue(label: "tv.dumbtv.review.commands")

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
        if let control = config["review_control"] as? [String: Any], control["enabled"] as? Bool == true,
           let owner = control["owner"] as? String, !owner.isEmpty {
            let directory = root.appendingPathComponent("review-commands")
            try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            let device = ReviewDevice(config: config) { [weak self] in
                DispatchQueue.main.sync { self?.ensureServer() ?? false }
            }
            let receiver = ReviewCommandQueue(directory: directory, owner: owner, perform: device.open)
            let timer = DispatchSource.makeTimerSource(queue: commandQueue)
            timer.schedule(deadline: .now(), repeating: 0.25)
            timer.setEventHandler { receiver.poll() }
            commandTimer = timer; timer.resume()
        }
        timer = Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { [weak self] _ in
            self?.refreshNow()
        }
        refreshNow()
    }

    @objc private func refreshNow() {
        guard sync == nil, connection == nil,
              let endpoint = ReviewDevice.networkEndpoint(config) else { return }
        retryTimer?.invalidate(); retryTimer = nil
        status.title = "Checking the TV…"
        // This ordinary Network-framework connection requests Local Network consent
        // for this app bundle. It is not a proxy: ADB performs all subsequent transfers.
        let check = NWConnection(to: endpoint, using: .tcp)
        connection = check
        check.stateUpdateHandler = { [weak self, weak check] state in
            guard let self = self else { return }
            switch state {
            case .ready:
                check?.stateUpdateHandler = nil; check?.cancel()
                self.connection = nil
                self.startServerAndRefresh()
            case .waiting:
                self.status.title = "Waiting for TV or Local Network permission…"
            case .failed:
                let denied = check?.currentPath?.unsatisfiedReason == .localNetworkDenied
                check?.stateUpdateHandler = nil; check?.cancel()
                self.connection = nil
                self.status.title = "TV unavailable or network access needed"
                if self.usesCloudPhotos { self.startServerAndRefresh() }
                else if !denied { self.scheduleRetry() }
            default: break
            }
        }
        check.start(queue: .main)
        DispatchQueue.main.asyncAfter(deadline: .now() + 120) { [weak self, weak check] in
            guard let self = self, self.connection === check else { return }
            let denied = check?.currentPath?.unsatisfiedReason == .localNetworkDenied
            check?.stateUpdateHandler = nil; check?.cancel(); self.connection = nil
            self.status.title = denied ? "Allow Local Network, then choose Refresh now"
                : "TV asleep; cached photos remain available"
            if self.usesCloudPhotos { self.startServerAndRefresh() }
            else if !denied { self.scheduleRetry() }
        }
    }

    private var usesCloudPhotos: Bool { config["photo_source"] as? String == "onedrive-api" }

    private func scheduleRetry() {
        retryTimer?.invalidate()
        retryTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: false) { [weak self] _ in
            self?.refreshNow()
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

    private func ensureServer() -> Bool {
        guard let adb = config["adb"] as? String else { return false }
        if server?.isRunning != true {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: adb)
            let port = config["adb_port"] as? Int ?? 5038
            process.arguments = ["-P", String(port), "nodaemon", "server"]
            process.standardOutput = log("adb-server.log")
            process.standardError = process.standardOutput
            do { try process.run(); server = process }
            catch { status.title = "TV connection helper could not start"; return false }
        }
        return true
    }

    private func startServerAndRefresh() {
        guard ensureServer() else { return }
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
                let directory = self.config["state_dir"] as? String
                    ?? self.root.appendingPathComponent("cache").path
                let url = URL(fileURLWithPath: directory).appendingPathComponent("status.json")
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
        connection?.cancel(); timer?.invalidate(); retryTimer?.invalidate()
        commandTimer?.cancel()
        if sync?.isRunning == true { sync?.terminate() }
        if server?.isRunning == true { server?.terminate() }
    }
}

let app = NSApplication.shared
let delegate = PhotoOwner()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
