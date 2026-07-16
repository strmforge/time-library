import AppKit
import Foundation

final class MemcoreMenuBarApp: NSObject, NSApplicationDelegate {
    private let installRoot: String
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()
    private let summaryItem = NSMenuItem()
    private var timer: Timer?

    init(installRoot: String) {
        self.installRoot = installRoot
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        configureStatusItem()
        configureMenu()
        refreshStatus(nil)
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            self?.refreshStatus(nil)
        }
    }

    private func frontDoorURL(_ path: String = "") -> URL? {
        let root = ProcessInfo.processInfo.environment["TIME_LIBRARY_ROOT"]
            ?? ProcessInfo.processInfo.environment["MEMCORE_ROOT"]
            ?? (NSHomeDirectory() + "/Library/Application Support/time-library")
        guard let portText = try? String(contentsOfFile: root + "/runtime/front_door_port", encoding: .ascii),
              let port = Int(portText.trimmingCharacters(in: .whitespacesAndNewlines)),
              (1...65535).contains(port) else { return nil }
        let suffix = path.isEmpty ? "" : (path.hasPrefix("/") ? path : "/" + path)
        return URL(string: "http://127.0.0.1:\(port)\(suffix)")
    }

    private func configureStatusItem() {
        guard let button = statusItem.button else { return }
        button.toolTip = "Time Library"
        if let image = loadBrandImage() {
            image.size = NSSize(width: 18, height: 18)
            image.isTemplate = true
            button.image = image
        } else {
            button.title = "◷"
        }
    }

    private func configureMenu() {
        summaryItem.title = text("starting")
        summaryItem.isEnabled = false
        menu.addItem(summaryItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(item(text("openConsole"), #selector(openConsole)))
        menu.addItem(item(text("checkStatus"), #selector(refreshStatus(_:))))
        menu.addItem(item(text("runCatchUp"), #selector(runCatchUp)))
        menu.addItem(item(text("restartWatcher"), #selector(restartWatcher)))
        menu.addItem(item(text("openLogs"), #selector(openLogs)))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(item(text("quit"), #selector(quit)))
        statusItem.menu = menu
    }

    private func item(_ title: String, _ selector: Selector) -> NSMenuItem {
        let menuItem = NSMenuItem(title: title, action: selector, keyEquivalent: "")
        menuItem.target = self
        return menuItem
    }

    private func loadBrandImage() -> NSImage? {
        let candidates = [
            "\(installRoot)/assets/brand/time-library-emblem.icns",
            "\(installRoot)/assets/brand/time-library-emblem.png",
            "\(installRoot)/web/assets/time_library_emblem.icns",
            "\(installRoot)/web/assets/time_library_emblem.png",
        ]
        for path in candidates {
            if let image = NSImage(contentsOfFile: path) {
                return image
            }
        }
        return nil
    }

    private func isChinese() -> Bool {
        return Locale.preferredLanguages.first?.lowercased().hasPrefix("zh") == true
    }

    private func text(_ key: String) -> String {
        let zh = [
            "starting": "Time Library: 启动中",
            "running": "Time Library: 运行中",
            "watcherAttention": "Time Library: 需要处理 watcher",
            "rawBackfill": "Time Library: 等待补扫",
            "offline": "Time Library: 控制台离线",
            "openConsole": "打开控制台",
            "checkStatus": "查看状态",
            "runCatchUp": "立即补扫",
            "restartWatcher": "重启 watcher",
            "openLogs": "打开日志",
            "quit": "退出菜单栏图标",
            "console": "控制台",
            "watcher": "监听",
            "rawLagging": "待补扫来源",
            "recordGuard": "记录守护",
            "recordCatchingUp": "正在追尾",
            "recordBackfillNeeded": "建议回填",
            "unavailable": "不可用",
            "localCapture": "本地采集",
            "ok": "正常",
            "notRunning": "未运行",
            "needsAttention": "需处理",
        ]
        let en = [
            "starting": "Time Library: starting",
            "running": "Time Library: running",
            "watcherAttention": "Time Library: watcher needs attention",
            "rawBackfill": "Time Library: raw backfill pending",
            "offline": "Time Library: console offline",
            "openConsole": "Open Console",
            "checkStatus": "Check Status",
            "runCatchUp": "Run Catch-up Now",
            "restartWatcher": "Restart Watcher",
            "openLogs": "Open Logs",
            "quit": "Quit Menu Bar Icon",
            "console": "Console",
            "watcher": "Watcher",
            "rawLagging": "Raw lagging sources",
            "recordGuard": "Record Guard",
            "recordCatchingUp": "Catching up",
            "recordBackfillNeeded": "Backfill needed",
            "unavailable": "unavailable",
            "localCapture": "Local capture",
            "ok": "ok",
            "notRunning": "not running",
            "needsAttention": "needs attention",
        ]
        return (isChinese() ? zh[key] : en[key]) ?? key
    }

    @objc private func openConsole() {
        if let url = frontDoorURL() {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func openLogs() {
        let logURL = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Logs/time-library")
        NSWorkspace.shared.open(logURL)
    }

    @objc private func runCatchUp() {
        postJSON("/api/v1/records/guardian/backfill", body: ["limit": 80])
        let python = "\(installRoot)/.venv/bin/python"
        let script = "\(installRoot)/src/memcore-cloud.py"
        let logPath = "\(NSHomeDirectory())/Library/Logs/time-library/menu-bar-catchup.log"
        let command = [
            "cd \(shellQuote(installRoot))",
            "MEMCORE_ROOT=\(shellQuote(installRoot))",
            "MEMCORE_INSTALL_ROOT=\(shellQuote(installRoot))",
            "PYTHONPATH=\(shellQuote(installRoot))",
            "PYTHONIOENCODING=utf-8",
            shellQuote(python),
            shellQuote(script),
            "--scan --source all",
            ">> \(shellQuote(logPath)) 2>&1",
        ].joined(separator: " ")
        runShell(command)
    }

    @objc private func restartWatcher() {
        let command = "launchctl kickstart -k gui/$(id -u)/com.memcorecloud.p0-watcher >/dev/null 2>&1"
        runShell(command)
    }

    @objc private func refreshStatus(_ sender: Any?) {
        DispatchQueue.global(qos: .utility).async {
            let summary = self.healthSummary()
            DispatchQueue.main.async {
                self.summaryItem.title = summary.detail
                self.statusItem.button?.toolTip = summary.tooltip
            }
        }
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    private func runShell(_ command: String) {
        DispatchQueue.global(qos: .utility).async {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/bash")
            process.arguments = ["-lc", command]
            do {
                try process.run()
                process.waitUntilExit()
            } catch {
                // The status refresh below exposes whether services are still healthy.
            }
            DispatchQueue.main.async {
                self.refreshStatus(nil)
            }
        }
    }

    private func shellQuote(_ value: String) -> String {
        return "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    private func healthSummary() -> (tooltip: String, detail: String) {
        guard fetchJSON("/api/health") != nil else {
            return (text("offline"), "\(text("console")): discovery file unavailable")
        }
        let watcher = fetchJSON("/api/watcher") as? [String: Any]
        let sync = fetchJSON("/api/v1/source-systems/continuous-sync/status") as? [String: Any]
        let guardian = fetchJSON("/api/v1/records/guardian/status?limit=80&mode=fast&compact=1") as? [String: Any]
        let syncWatcher = sync?["watcher"] as? [String: Any]
        let summary = sync?["summary"] as? [String: Any]
        let guardianSummary = guardian?["summary"] as? [String: Any]

        let watcherActive = (watcher?["active"] as? Bool == true) || (syncWatcher?["active"] as? Bool == true)
        let lagging = intValue(summary?["raw_lagging_source_count"])
        let localCaptureOK = (summary?["local_capture_ok"] as? Bool) ?? true
        let guardianAvailable = guardianSummary != nil
        let recordCount = intValue(guardianSummary?["record_count"])
        let recordGuarded = intValue(guardianSummary?["record_guarded_count"])
        let recordCatchingUp = intValue(guardianSummary?["raw_catching_up_count"])
        let recordBackfillNeeded = intValue(guardianSummary?["backfill_recommended_count"])
        let ok = watcherActive && lagging == 0 && localCaptureOK && guardianAvailable && recordBackfillNeeded == 0

        let tooltip: String
        if ok {
            tooltip = text("running")
        } else if !watcherActive {
            tooltip = text("watcherAttention")
        } else if lagging > 0 || recordBackfillNeeded > 0 {
            tooltip = text("rawBackfill")
        } else {
            tooltip = text("watcherAttention")
        }

        let recordGuardText = guardianAvailable
            ? "\(recordGuarded)/\(recordCount)"
            : text("unavailable")
        let detail = [
            "\(text("console")): front-door discovery",
            "\(text("watcher")): \(watcherActive ? text("ok") : text("notRunning"))",
            "\(text("recordGuard")): \(recordGuardText)",
            "\(text("recordCatchingUp")): \(recordCatchingUp)",
            "\(text("recordBackfillNeeded")): \(recordBackfillNeeded)",
            "\(text("rawLagging")): \(lagging)",
            "\(text("localCapture")): \(localCaptureOK ? text("ok") : text("needsAttention"))",
        ].joined(separator: "\n")
        return (tooltip, detail)
    }

    private func intValue(_ value: Any?) -> Int {
        if let intValue = value as? Int {
            return intValue
        }
        if let number = value as? NSNumber {
            return number.intValue
        }
        if let string = value as? String, let intValue = Int(string) {
            return intValue
        }
        return 0
    }

    private func fetchJSON(_ path: String) -> Any? {
        guard let url = frontDoorURL(path) else { return nil }
        var request = URLRequest(url: url)
        request.timeoutInterval = 3
        let semaphore = DispatchSemaphore(value: 0)
        var payload: Any?
        URLSession.shared.dataTask(with: request) { data, _, _ in
            defer { semaphore.signal() }
            guard let data = data else { return }
            payload = try? JSONSerialization.jsonObject(with: data, options: [])
        }.resume()
        _ = semaphore.wait(timeout: .now() + 4)
        return payload
    }

    private func postJSON(_ path: String, body: [String: Any]) {
        guard let url = frontDoorURL(path) else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 5
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token = consoleToken() {
            request.setValue(token, forHTTPHeaderField: "X-Memcore-Console-Token")
            if let scheme = url.scheme, let host = url.host, let port = url.port {
                request.setValue("\(scheme)://\(host):\(port)", forHTTPHeaderField: "Origin")
            }
        }
        request.httpBody = try? JSONSerialization.data(withJSONObject: body, options: [])
        let semaphore = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: request) { _, _, _ in
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 6)
    }

    private func consoleToken() -> String? {
        let tokenPath = "\(installRoot)/runtime/console_token"
        guard let raw = try? String(contentsOfFile: tokenPath, encoding: .utf8) else { return nil }
        let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }
}

let defaultInstallRoot = "\(NSHomeDirectory())/Library/Application Support/time-library"
let installRoot = CommandLine.arguments.dropFirst().first ?? defaultInstallRoot
let app = NSApplication.shared
let delegate = MemcoreMenuBarApp(installRoot: installRoot)
app.delegate = delegate
app.run()
