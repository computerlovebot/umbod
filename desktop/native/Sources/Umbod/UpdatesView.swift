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
        // App sessions using fixture credentials never contact the update service.
        guard !CommandLine.arguments.contains("--test-credentials") else { return }
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
            message = result == nil ? "You’re up to date." : "Umbod \(result!.version) is available."
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
                    Text("Version \(updates.installed)").foregroundStyle(Brand.muted)
                }
                Spacer()
                Button(updates.checking ? "Checking…" : "Check for Updates") { Task { await updates.check() } }
                    .disabled(updates.checking)
            }
            Toggle("Check automatically", isOn: $updates.automatic)
                .onChange(of: updates.automatic) { _, enabled in if enabled { Task { await updates.check(manual: false) } } }
            Text("We’ll let you know when an update is available. You choose when to install it.").font(.caption).foregroundStyle(Brand.muted)
            if !updates.message.isEmpty { Text(updates.message).textSelection(.enabled) }
            if let update = updates.available {
                Text("Version \(update.version) is ready").font(.headline)
                Text("Download the update, then replace Umbod in Applications. Your settings and connections stay with you.").foregroundStyle(Brand.muted)
                Text("Preview release · not notarized by Apple.").font(.caption).foregroundStyle(Brand.muted)
                HStack {
                    Button("Download Update") {
                        downloaded = NSWorkspace.shared.open(update.download)
                        if !downloaded { updates.message = "Couldn’t open your browser. Try again or open the release notes." }
                    }.buttonStyle(BrandButtonStyle(primary: true))
                    Link("Release notes", destination: update.releaseNotes)
                    Button("Skip this version") { updates.skip() }
                }
                if downloaded {
                Text("When the download finishes, quit Umbod and open the installer. Active tool calls will stop.").font(.caption).foregroundStyle(Brand.muted)
                Button("Quit and install…") { confirmQuit = true }.disabled(model.busy)
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
