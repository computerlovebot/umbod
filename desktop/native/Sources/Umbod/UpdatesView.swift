import SwiftUI
import AppKit
import UmbodCore

@MainActor final class UpdateModel: ObservableObject {
    @Published var available: DesktopUpdate?
    @Published var checking = false
    @Published var message = ""
    @Published var dismissed = false
    @Published var automatic: Bool {
        didSet { defaults.set(automatic, forKey: "updates.automatic") }
    }
    let installed = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
    private let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        automatic = defaults.object(forKey: "updates.automatic") as? Bool ?? (AppEnvironment.current == .release)
    }
    func monitor() async {
        // Isolated native smoke tests never contact the update service.
        guard !CommandLine.arguments.contains("--test-credentials"), !CommandLine.arguments.contains("--smoke-report") else { return }
        while !Task.isCancelled {
            await check(manual: false)
            do { try await Task.sleep(for: .seconds(3600)) } catch { return }
        }
    }
    func check(manual: Bool = true) async {
        guard !checking else { return }
        let last = defaults.object(forKey: "updates.lastAttempt") as? Date
        guard manual || DesktopUpdate.isDue(enabled: automatic, lastAttempt: last) else { return }
        checking = true; message = "Checking for updates…"
        defaults.set(Date(), forKey: "updates.lastAttempt")
        defer { checking = false }
        do {
            let result = try await DesktopUpdate.check(installed: installed)
            available = result
            dismissed = !manual && result?.version == defaults.string(forKey: "updates.skippedVersion")
            message = result == nil ? "No newer published update found. You have \(installed)." : "Umbod \(result!.version) is available."
        } catch {
            message = "Couldn’t check for updates. Check your connection and try again."
        }
    }
    func skip() {
        defaults.set(available?.version, forKey: "updates.skippedVersion")
        dismissed = true
        message = "Automatic reminders for this version are skipped. You can still download it below."
    }
}

struct UpdateBanner: View {
    @ObservedObject var updates: UpdateModel
    @EnvironmentObject var model: AppModel
    var body: some View {
        if let update = updates.available, !updates.dismissed {
            HStack {
                Image(systemName: "arrow.down.circle")
                Text("Umbod \(update.version) is available.")
                Spacer()
                Button("View update") { model.settingsSection = .general; model.settingsPresented = true }
                Button("Later") { updates.dismissed = true }
            }.padding(16).background(Brand.accentSoft, in: RoundedRectangle(cornerRadius: 12))
        }
    }
}

struct UpdatesView: View {
    @ObservedObject var updates: UpdateModel
    @EnvironmentObject var model: AppModel
    @State private var confirmQuit = false
    @State private var downloaded = false
    var body: some View {
        Panel {
            HStack {
                VStack(alignment: .leading, spacing: 6) {
                    Text("App updates").font(.headline)
                    Text("Installed version: \(updates.installed)").foregroundStyle(Brand.muted)
                }
                Spacer()
                Button(updates.checking ? "Checking…" : "Check for Updates") { Task { await updates.check() } }
                    .disabled(updates.checking)
            }
            Toggle("Automatically check for updates daily", isOn: $updates.automatic)
                .onChange(of: updates.automatic) { _, enabled in if enabled { Task { await updates.check(manual: false) } } }
            Text("Checks umbod.ai for releases. Updates are downloaded only when you choose.").font(.caption).foregroundStyle(Brand.muted)
            if !updates.message.isEmpty { Text(updates.message).textSelection(.enabled) }
            if let update = updates.available {
                Text("Unsigned prerelease · \(update.version)").font(.headline)
                Text("1. Download and open the DMG.\n2. Close your MCP clients, then choose Quit for Update below. Active tool calls will be interrupted.\n3. Drag Umbod into Applications and replace the old app, then reopen Umbod and your clients. Your connections and settings are kept.")
                    .foregroundStyle(Brand.muted)
                Text("macOS may require approval to open this unnotarized app. Keep system security enabled.").font(.caption)
                HStack {
                    Button("Download Update") {
                        downloaded = NSWorkspace.shared.open(update.download)
                        if !downloaded { updates.message = "Couldn’t open your browser. Try again or open the release notes." }
                    }.buttonStyle(BrandButtonStyle(primary: true))
                    Link("Release notes", destination: update.releaseNotes)
                    Button("Skip this version") { updates.skip() }
                }
                DisclosureGroup("Download SHA-256") { Text(update.sha256).font(.system(size: 11, design: .monospaced)).textSelection(.enabled) }
                if downloaded { Text("Download opened in your browser. Finish downloading before quitting.").font(.caption) }
                Button("Quit for Update…") { confirmQuit = true }.disabled(model.busy)
                    .confirmationDialog("Stop the gateway and quit Umbod? Close your MCP clients first. Active tool calls will be interrupted.", isPresented: $confirmQuit) {
                        Button("Stop Gateway and Quit") {
                            Task {
                                model.busy = true
                                defer { model.busy = false }
                                do { try await model.backend.shutdown(); NSApp.terminate(nil) }
                                catch { updates.message = "Couldn’t stop the gateway: \(error.localizedDescription)" }
                            }
                        }
                        Button("Cancel", role: .cancel) {}
                    }
            }
        }
    }
}

struct CheckForUpdatesMenuButton: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        Button("Check for Updates…") {
            openWindow(id: "main")
            model.settingsSection = .general; model.settingsPresented = true
            Task { await model.updates.check() }
        }
    }
}
