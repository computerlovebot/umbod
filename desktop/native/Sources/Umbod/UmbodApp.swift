import SwiftUI
import AppKit
import UmbodCore

@MainActor final class AppModel: ObservableObject {
    static let shared = AppModel()
    let backend = Backend()
    let updates = UpdateModel()
    @Published var activation = ActivationState([:])
    @Published var diagnostics: [String: Any] = [:]
    @Published var dailyCalls: [String: Int] = [:]
    @Published var dailyTrackingStarted: Int?
    @Published var toolUsage: [String: [String: Int]] = [:]
    @Published var clientSetup: [String: Any] = [:]
    var dataDirectory: URL? {
        guard let i = CommandLine.arguments.firstIndex(of: "--data-dir"), CommandLine.arguments.count > i+1 else { return nil }
        return URL(fileURLWithPath: CommandLine.arguments[i+1]).resolvingSymlinksInPath()
    }
    var clientConfig: URL {
        if dataDirectory != nil, let i = CommandLine.arguments.firstIndex(of: "--client-config"), CommandLine.arguments.count > i+1 { return URL(fileURLWithPath: CommandLine.arguments[i+1]).resolvingSymlinksInPath() }
        return ClientConfiguration.destination(home: FileManager.default.homeDirectoryForCurrentUser, dataDirectory: dataDirectory ?? (AppEnvironment.current == .dev ? AppEnvironment.current.dataDirectory : nil))
    }
    @Published var servers: [[String: Any]] = []
    @Published var tools: [[String: Any]] = []
    @Published var allowedTools: Set<String> = []
    @Published var statuses: [String: String] = [:]
    @Published var error = ""
    @Published var notice = ""
    @Published var settingsSection: SettingsSection = .general
    @Published var settingsPresented = false
    @Published var busy = false
    @Published var activity = ""
    @Published var oauthStatuses: [String: String] = [:]
    @Published var online = false
    private var starting = false
    func start() async {
        guard !starting && !backend.isRunning else { return }
        starting = true
        defer { starting = false }
        do {
            try await backend.start(directory: dataDirectory, persistent: dataDirectory == nil, testCredentials: CommandLine.arguments.contains("--test-credentials")); online = true; try await refresh()
        }
        catch { self.error = error.localizedDescription; online = false }
    }
    func refresh() async throws {
        let state = try await backend.request(["action": "status"])
        if let migration = state["migration"] as? [String: Any], migration["status"] as? String == "needs_attention" {
            error = migration["error"] as? String ?? "Migration needs attention. Restart to retry."
        }
        activation = ActivationState(state)
        diagnostics = state["diagnostics"] as? [String: Any] ?? [:]
        toolUsage = state["tool_usage"] as? [String: [String: Int]] ?? [:]
        dailyCalls = state["daily_calls"] as? [String: Int] ?? [:]
        dailyTrackingStarted = state["daily_tracking_started"] as? Int
        clientSetup = state["client_setup"] as? [String: Any] ?? [:]
        servers = state["servers"] as? [[String: Any]] ?? []
        tools = state["tools"] as? [[String: Any]] ?? []
        allowedTools = Set(state["allowed_tools"] as? [String] ?? [])
        statuses = state["statuses"] as? [String: String] ?? [:]
        oauthStatuses = state["oauth_status"] as? [String: String] ?? [:]
        online = backend.isRunning
    }
    func act(_ body: [String: Any], success: String = "") {
        Task { busy = true; error = ""; activity = body["action"] as? String == "connect" ? "Connecting and discovering tools…" : "Updating connector…"; defer { busy = false; activity = "" }
            do { _ = try await backend.request(body); try await refresh(); notice = success }
            catch { self.error = error.localizedDescription }
        }
    }
    func copy(_ text: String, message: String = "Copied to clipboard") {
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string); notice = message
    }
    func signIn(_ id: String, clientID: String) {
        Task {
            busy = true; error = ""; activity = "Opening browser sign-in…"
            defer { busy = false; activity = "" }
            do {
                let result = try await backend.request(["action": "oauth_begin", "id": id, "client_id": clientID])
                if let value = result["url"] as? String, !value.isEmpty, let url = URL(string: value) {
                    guard NSWorkspace.shared.open(url) else { throw ContractError.message("Could not open your browser. Try signing in again.") }
                }
                activity = "Waiting for browser sign-in. Complete the sign-in in your browser."
                for _ in 0..<160 {
                    try await refresh()
                    switch oauthStatuses[id] {
                    case "signed_in":
                        notice = "Signed in. Connect to discover your tools."
                        return
                    case "failed":
                        throw ContractError.message("Browser sign-in did not complete. Try again in Connection settings.")
                    default: break
                    }
                    try await Task.sleep(for: .seconds(2))
                }
                throw ContractError.message("Browser sign-in timed out. Try again in Connection settings.")
            } catch { self.error = error.localizedDescription }
        }
    }

}
@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Refresh the running Dock icon even when macOS cached an older bundle icon.
        if let iconURL = Bundle.main.url(forResource: "UmbodBrand", withExtension: "icns"),
           let icon = NSImage(contentsOf: iconURL) {
            NSApp.applicationIconImage = icon
        }
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationWillTerminate(_ notification: Notification) { AppModel.shared.backend.stop() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { sender.windows.first(where: { $0.title == AppEnvironment.current.name })?.makeKeyAndOrderFront(nil) }
        return true
    }
}
@main struct UmbodApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel.shared
    var body: some Scene {
        Window(AppEnvironment.current.name, id: "main") { Workspace().environmentObject(model).frame(minWidth: 950, minHeight: 680).task { Task { await model.start() } }.task { await model.updates.monitor() } }
            .defaultSize(width: 1120, height: 780)
            .commands {
                CommandGroup(replacing: .newItem) {}
                CommandGroup(after: .appInfo) { CheckForUpdatesMenuButton().environmentObject(model) }
                CommandGroup(replacing: .appSettings) { SettingsMenuButton().environmentObject(model) }
            }
        MenuBarExtra(AppEnvironment.current.name, systemImage: "point.3.connected.trianglepath.dotted") { BackgroundMenu() }
    }
}
enum Page: String, CaseIterable, Identifiable {
    case overview = "Overview", servers = "Connectors"
    var id: String { rawValue }
}
struct Workspace: View {
    @EnvironmentObject var model: AppModel
    @State private var page: Page? = .overview
    @State private var selectedConnector: String?
    @State private var addingConnector = false
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 8) {
                    UmbodMark().fill(.black).frame(width: 40, height: 40)
                    Text(AppEnvironment.current.name).font(.system(size: 24, weight: .semibold)).tracking(-1.44)
                }.padding(.horizontal, 4)
                Text(AppEnvironment.current == .dev ? "DEVELOPMENT" : "LOCAL WORKSPACE").font(.system(size: 10, design: .monospaced))
                    .tracking(0.8).foregroundStyle(Brand.muted)
                    .padding(.horizontal, 12).padding(.top, 18).padding(.bottom, 12)
                VStack(spacing: 4) {
                    ForEach(Page.allCases) { item in
                        Button { selectedConnector = nil; page = item } label: {
                            Label(item.rawValue, systemImage: item == .overview ? "square.grid.2x2" : "point.3.connected.trianglepath.dotted").frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(NavigationButtonStyle(selected: page == item))
                        .accessibilityAddTraits(page == item ? [.isSelected] : [])
                    }
                }
                Spacer()
                Button {
                    model.settingsSection = .general
                    model.settingsPresented = true
                } label: {
                    Label("Settings", systemImage: "gearshape").frame(maxWidth: .infinity, alignment: .leading)
                }.buttonStyle(NavigationButtonStyle(selected: false)).padding(.bottom, 12)
                VStack(alignment: .leading, spacing: 6) {
                    Rectangle().fill(Brand.border).frame(height: 1).padding(.bottom, 6)
                    Label(model.online ? "Gateway running" : "Gateway offline", systemImage: "circle.fill")
                        .font(.system(size: 12, weight: .semibold)).foregroundStyle(model.online ? Brand.accent : Brand.muted)
                    Text("Private. Local. Yours.").font(.system(size: 12)).foregroundStyle(Brand.muted)
                }.padding(.horizontal, 8)
            }.padding(.horizontal, 16).padding(.top, 26).padding(.bottom, 18)
                .frame(width: 232).background(Brand.soft)
            Rectangle().fill(Brand.border).frame(width: 1)
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    if page != .servers || selectedConnector == nil {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text((page ?? .overview).rawValue).font(.system(size: 32, weight: .semibold)).tracking(-1.28)
                            Text(subtitle).font(.system(size: 15)).foregroundStyle(Brand.muted).lineSpacing(5)
                        }
                        Spacer()
                        if model.busy { ProgressView().controlSize(.small) }
                        Button { Task { do { try await model.refresh() } catch { model.error = error.localizedDescription } } } label: {
                            Image(systemName: "arrow.clockwise")
                        }.help("Refresh connection status")
                    }
                    }
                    StatusMessages()
                    UpdateBanner(updates: model.updates)
                    switch page ?? .overview { case .overview: Overview(addConnector: { addingConnector = true }); case .servers: ServersView(selectedConnector: $selectedConnector) }
                }.padding(.horizontal, 40).padding(.vertical, 48).frame(maxWidth: 1440, alignment: .leading)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }.background(Brand.canvas)
        }
        .sheet(isPresented: $addingConnector) { ServerEditor(draft: ServerDraft(), onSaved: { selectedConnector = nil; page = .servers }).environmentObject(model) }
        .disabled(model.settingsPresented)
        .accessibilityHidden(model.settingsPresented)
        .overlay {
            if model.settingsPresented {
                GeometryReader { geometry in
                    ZStack {
                        Color.black.opacity(0.28)
                            .onTapGesture { model.settingsPresented = false }
                            .accessibilityHidden(true)
                        SettingsView()
                            .frame(width: min(1000, geometry.size.width - 96),
                                   height: min(800, geometry.size.height - 96))
                            .clipShape(RoundedRectangle(cornerRadius: 16))
                            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.border))
                            .shadow(color: .black.opacity(0.2), radius: 24, y: 12)
                    }.frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
        }
        .modifier(BrandAppearance())
    }
    var subtitle: String { switch page ?? .overview {
        case .overview: "Your tool activity across connected apps."
        case .servers: "Choose a connector to manage its tools."
    } }
}
struct Panel<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View { VStack(alignment: .leading, spacing: 16) { content }.padding(18).frame(maxWidth: .infinity, alignment: .leading).background(Brand.canvas, in: RoundedRectangle(cornerRadius: 12)).overlay(RoundedRectangle(cornerRadius: 12).stroke(Brand.border)) }
}
struct ServerEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) var dismiss
    @StateObject private var editor: ConnectorEditor
    private let onSaved: () -> Void
    init(draft: ServerDraft, onSaved: @escaping () -> Void = {}) {
        _editor = StateObject(wrappedValue: ConnectorEditor(draft: draft))
        self.onSaved = onSaved
    }
    @State private var localError = ""
    @State private var authenticationExpanded = false
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 8) {
                Text(editor.draft.id.isEmpty ? "Add connector" : "Edit connector").font(.system(size: 26, weight: .semibold))
                Text("Connect a tool source. You choose which tools your agents can use.").foregroundStyle(Brand.muted)
            }.frame(maxWidth: .infinity, alignment: .leading)
            ScrollView { VStack(alignment: .leading, spacing: 16) {
                TextField("Name", text: $editor.draft.name).accessibilityIdentifier("connector.name")
                Picker("Connection", selection: $editor.draft.transport) { Text("Local process (stdio)").tag("stdio"); Text("HTTP URL").tag("http") }.accessibilityIdentifier("connector.transport")
                if editor.draft.transport == "stdio" {
                    TextField("Executable (absolute path)", text: $editor.draft.command).accessibilityIdentifier("connector.command")
                    Text("The executable supplied by your MCP server, for example /opt/homebrew/bin/uvx.").font(.caption).foregroundStyle(Brand.muted)
                    Text("Arguments · one per line, no shell quoting").font(.caption).foregroundStyle(Brand.muted)
                    TextEditor(text: $editor.draft.arguments).accessibilityIdentifier("connector.arguments").font(.system(.body, design: .monospaced)).frame(height: 65).padding(8).background(Brand.canvas).overlay(RoundedRectangle(cornerRadius: 8).stroke(Brand.border).allowsHitTesting(false))
                } else {
                    TextField("Endpoint URL", text: $editor.draft.url).accessibilityIdentifier("connector.url")
                    Text("If sign-in is needed, you can do that after saving.").font(.caption).foregroundStyle(Brand.muted)
                }
                Button { authenticationExpanded.toggle() } label: {
                    HStack {
                        Image(systemName: "key")
                        Text("Authentication").fontWeight(.medium)
                        Text("Optional").foregroundStyle(Brand.muted)
                        Spacer()
                        Image(systemName: authenticationExpanded ? "chevron.up" : "chevron.down")
                    }.frame(maxWidth: .infinity).padding(.vertical, 5).contentShape(Rectangle())
                }.accessibilityIdentifier("connector.authentication")
                if authenticationExpanded {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(editor.draft.transport == "http" ? "For browser sign-in, leave this blank and sign in after saving." : "Only needed if your server requires a secret environment variable.")
                            .font(.caption).foregroundStyle(Brand.muted)
                        TextField(editor.draft.transport == "stdio" ? "Environment variable name" : "Header name", text: $editor.credentialName)
                        SecureField(editor.draft.transport == "stdio" ? "Secret value" : "Header value (e.g. Bearer …)", text: $editor.credential)
                        Text("Saved securely in macOS Keychain. Existing credentials are kept when left blank.").font(.caption).foregroundStyle(Brand.muted)
                    }.padding(16).background(Brand.soft, in: RoundedRectangle(cornerRadius: 10))
                }
            }.padding(2) }.textFieldStyle(BrandTextFieldStyle()).disabled(editor.saving)
            if !editor.draft.id.isEmpty { Text("Changing connection details requires reconnecting. Renaming keeps the connection and enabled tools.").font(.caption).foregroundStyle(Brand.muted) }
            if !localError.isEmpty { Text(localError).foregroundStyle(Brand.danger) }
            HStack { Spacer(); Button("Cancel") { dismiss() }; Button(editor.saving ? "Saving…" : "Save connector") { save() }.buttonStyle(BrandButtonStyle(primary: true)).disabled(editor.saving || editor.draft.name.isEmpty).accessibilityIdentifier("connector.save") }
        }.padding(28).frame(width: 580, height: editor.draft.transport == "stdio" ? (authenticationExpanded ? 710 : 550) : (authenticationExpanded ? 570 : 410)).modifier(BrandAppearance())
        .onChange(of: editor.draft.transport) { _, transport in
            if editor.credential.isEmpty { editor.credentialName = transport == "http" ? "Authorization" : "" }
        }
    }
    func save() {
        Task {
            do {
                localError = ""
                try await editor.save { try await model.backend.request($0) }
                try await model.refresh()
                dismiss()
                onSaved()
            } catch { localError = error.localizedDescription }
        }
    }
}
struct ConnectionView: View {
    @EnvironmentObject var model: AppModel
    @State private var copying = false
    private var configuration: String { (try? ClientConfiguration.bridge(bundlePath: Bundle.main.bundlePath, environment: .current, executable: model.dataDirectory == nil ? AppEnvironment.current.gatewayExecutable : nil)) ?? "" }
    private var endpoint: String { "http://\(model.backend.gateway)/mcp" }
    private var command: String {
        let document = try? JSONSerialization.jsonObject(with: Data(configuration.utf8)) as? [String: Any]
        let servers = document?["mcpServers"] as? [String: [String: Any]]
        return servers?[AppEnvironment.current.serverName]?["command"] as? String ?? ""
    }
    var body: some View {
        Panel {
            Label("Standard IO (stdio)", systemImage: "terminal").font(.headline)
            Text("Add this configuration to your agent’s MCP settings.").foregroundStyle(Brand.muted)
            VStack(alignment: .leading, spacing: 8) {
                Text("Command").font(.caption).foregroundStyle(Brand.muted)
                Text(command).font(.system(size: 12, design: .monospaced)).textSelection(.enabled)
                Text("Arguments").font(.caption).foregroundStyle(Brand.muted).padding(.top, 4)
                Text("bridge --profile \(AppEnvironment.current.rawValue)").font(.system(size: 12, design: .monospaced)).textSelection(.enabled)
            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                .background(Brand.soft, in: RoundedRectangle(cornerRadius: 8))
            Button(copying ? "Copying…" : "Copy configuration") { copyConfiguration() }
                .buttonStyle(BrandButtonStyle(primary: true)).disabled(copying)
        }
        Panel {
            Label("HTTP", systemImage: "link").font(.headline)
            Text("For MCP clients running on this Mac. Use the URL and bearer token below.").foregroundStyle(Brand.muted)
            HStack {
                Text(endpoint).font(.system(size: 12, design: .monospaced)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button("Copy URL") { model.copy(endpoint, message: "MCP URL copied.") }
                    .disabled(!model.online)
            }.padding(12).background(Brand.soft, in: RoundedRectangle(cornerRadius: 8))
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Bearer token").font(.subheadline.weight(.medium))
                    // Never fetch the real token for display or accessibility.
                    Text("••••••••••••••••").font(.system(.body, design: .monospaced))
                        .accessibilityLabel("Connection token hidden")
                }
                Spacer()
                Button("Copy token") { copyConfiguration(token: true) }.disabled(copying)
            }
            Text("This secret lets your agent use the tools you enable in Umbod.").font(.caption).foregroundStyle(Brand.muted)
        }
        .task { do { _ = try await model.backend.request(["action": "connection_setup"]) } catch { if !Task.isCancelled { model.error = error.localizedDescription } } }
    }
    private func copyConfiguration(token: Bool = false) {
        Task {
            copying = true
            defer { copying = false }
            do {
                _ = try await model.backend.request(["action": "connection_setup"])
                if token {
                    let value = try await model.backend.request(["action": "connection_token"])
                    if let credential = value["token"] as? String { model.copy(credential, message: "Token copied.") }
                } else { model.copy(configuration, message: "Configuration copied.") }
            } catch { model.error = error.localizedDescription }
        }
    }
}
enum SettingsSection: String, CaseIterable {
    case general = "General", mcp = "MCP"
    var symbol: String { self == .general ? "slider.horizontal.3" : "point.3.connected.trianglepath.dotted" }
    var subtitle: String {
        self == .general ? "Keep Umbod up to date and ready to use." : "Connect your agent to Umbod. Choose either method below."
    }
}
struct SettingsMenuButton: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        Button("Settings…") {
            model.settingsSection = .general
            openWindow(id: "main")
            model.settingsPresented = true
        }.keyboardShortcut(",", modifiers: .command)
    }
}
struct StatusMessages: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        if !model.error.isEmpty {
            HStack { Image(systemName: "exclamationmark.triangle"); Text(model.error).textSelection(.enabled); Spacer(); Button("Dismiss") { model.error = "" } }
                .padding(16).background(Brand.dangerSoft, in: RoundedRectangle(cornerRadius: 12)).foregroundStyle(Brand.danger)
        }
        if !model.notice.isEmpty {
            HStack { Image(systemName: "checkmark.circle"); Text(model.notice); Spacer(); Button { model.notice = "" } label: { Image(systemName: "xmark") }.help("Dismiss notification") }
                .padding(16).background(Brand.accentSoft, in: RoundedRectangle(cornerRadius: 12))
        }
    }
}
struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @FocusState private var closeFocused: Bool
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                Text("SETTINGS").font(.system(size: 10, design: .monospaced))
                    .tracking(0.8).foregroundStyle(Brand.muted)
                    .padding(.horizontal, 12).padding(.bottom, 24)
                VStack(spacing: 4) {
                    ForEach(SettingsSection.allCases, id: \.self) { section in
                        Button { model.settingsSection = section } label: {
                            Label(section.rawValue, systemImage: section.symbol)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(NavigationButtonStyle(selected: model.settingsSection == section))
                        .accessibilityAddTraits(model.settingsSection == section ? [.isSelected] : [])
                    }
                }
                Spacer()
                Text("\(AppEnvironment.current.name) · \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Development")").font(.system(size: 12)).foregroundStyle(Brand.muted)
                    .padding(.horizontal, 12)
            }.padding(.horizontal, 16).padding(.vertical, 32)
                .frame(width: 212).background(Brand.soft)
            Rectangle().fill(Brand.border).frame(width: 1)
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    HStack {
                        Text(model.settingsSection.rawValue).font(.system(size: 32, weight: .semibold)).tracking(-1.28)
                        Spacer()
                        if model.busy { ProgressView().controlSize(.small) }
                        Button { model.settingsPresented = false } label: {
                            Image(systemName: "xmark")
                        }
                        .help("Close settings (Esc)")
                        .accessibilityLabel("Close settings")
                        .keyboardShortcut(.cancelAction)
                        .focused($closeFocused)
                    }
                    Text(model.settingsSection.subtitle).font(.system(size: 15)).foregroundStyle(Brand.muted)
                    StatusMessages()
                    if model.settingsSection == .mcp { ConnectionView() } else { GeneralSettingsView() }
                }.padding(40).frame(maxWidth: 900, alignment: .leading).frame(maxWidth: .infinity, alignment: .leading)
            }.background(Brand.canvas)
        }.modifier(BrandAppearance())
            .onAppear { closeFocused = true }
    }
}
struct GeneralSettingsView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        UpdatesView(updates: model.updates)
        Panel {
            HStack(spacing: 16) {
                Image(systemName: model.online ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(model.online ? Brand.accent : Brand.muted).font(.title2)
                VStack(alignment: .leading, spacing: 5) {
                    Text(model.online ? "Ready for your agents" : "Connection stopped").font(.headline)
                    Text(model.backend.updateAvailable ? "Restart to apply the latest changes." : "Umbod keeps running when you close this window.")
                        .font(.callout).foregroundStyle(Brand.muted)
                }
                Spacer()
                if !model.online || model.backend.updateAvailable {
                    Button(model.online ? "Restart" : "Start") { restart() }.disabled(model.busy)
                } else {
                    Menu {
                        Button("Restart connection") { restart() }
                        Button("Stop connection") {
                            Task {
                                model.busy = true
                                defer { model.busy = false }
                                do { try await model.backend.shutdown(); model.online = false }
                                catch { model.error = error.localizedDescription }
                            }
                        }
                    } label: { Image(systemName: "ellipsis") }
                    .help("Connection controls").accessibilityLabel("Connection controls").disabled(model.busy)
                }
            }
        }
    }
    private func restart() {
        Task {
            model.busy = true
            defer { model.busy = false }
            do { try await model.backend.shutdown(); model.online = false; await model.start() }
            catch { model.error = error.localizedDescription }
        }
    }
}
