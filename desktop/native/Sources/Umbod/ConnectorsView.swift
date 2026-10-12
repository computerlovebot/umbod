import SwiftUI
import AppKit
import UmbodCore

private enum ConnectorSheet: Identifiable {
    case add, edit(String), manage(String)
    var id: String { switch self { case .add: "add"; case .edit(let id): "edit-\(id)"; case .manage(let id): "manage-\(id)" } }
}
struct ServersView: View {
    @EnvironmentObject var model: AppModel
    @State private var sheet: ConnectorSheet?
    @Binding var selectedConnector: String?
    @State private var removal: String?
    // An offline draft receives its backend ID after first successful discovery.
    // Keep the selected detail and sheet attached through its stable host identity.
    private func connector(_ id: String) -> [String: Any]? {
        model.servers.first {
            $0["id"] as? String == id ||
            (id.hasPrefix("pending:") && $0["host_id"] as? String == String(id.dropFirst("pending:".count)))
        }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            if let id = selectedConnector, let connector = connector(id) {
                Button { selectedConnector = nil } label: { Label("All connectors", systemImage: "chevron.left") }
                ConnectorToolsView(connector: connector, manage: { sheet = .manage(id) }).id(id)
            } else {
                Button { sheet = .add } label: { Label("Add connector", systemImage: "plus") }.buttonStyle(BrandButtonStyle(primary: true)).accessibilityIdentifier("connectors.add")
                if model.servers.isEmpty {
                    ContentUnavailableView("No connectors yet", systemImage: "externaldrive.badge.plus", description: Text("Add a connector to make its tools available to your apps."))
                } else {
                    Panel {
                        ForEach(model.servers.indices, id: \.self) { index in
                            let server = model.servers[index]
                            let id = server["id"] as? String ?? ""
                            let tools = model.tools.filter { ($0["name"] as? String ?? "").hasPrefix(id + ".") }
                            if index > 0 { Divider() }
                            HStack(spacing: 16) {
                                Button { selectedConnector = id } label: {
                                    HStack(spacing: 14) {
                                        ConnectorIconView(
                                            source: server["icon_url"] as? String,
                                            fallbackSystemName: server["transport"] as? String == "stdio" ? "terminal" : "network"
                                        )
                                        VStack(alignment: .leading, spacing: 6) {
                                            Text(server["name"] as? String ?? "Connector").font(.system(size: 15, weight: .semibold))
                                            Text(model.statuses[id] ?? "Disconnected").font(.caption).foregroundStyle(Brand.muted)
                                        }
                                        Spacer()
                                        Text("\(tools.filter { model.allowedTools.contains($0["name"] as? String ?? "") }.count) / \(tools.count) tools enabled").font(.caption).foregroundStyle(Brand.muted)
                                        Image(systemName: "chevron.right").foregroundStyle(Brand.muted)
                                    }.padding(.vertical, 6).contentShape(Rectangle())
                                }.buttonStyle(.plain).accessibilityIdentifier("connector.row.\(server["name"] as? String ?? "")")
                                Menu {
                                    Button("Connection settings") { sheet = .manage(id) }
                                    Button("Connect / rediscover") { model.act(["action":"connect", "id":id]) }.disabled(model.busy || model.signInActivities[id] != nil)
                                    Button("Edit connection") { sheet = .edit(id) }
                                    Divider()
                                    Button("Remove connector", role: .destructive) { removal = id }
                                } label: { Image(systemName: "ellipsis").frame(width: 22, height: 22) }
                                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().help("Manage \(server["name"] as? String ?? "connector")")
                            }
                        }
                    }
                }
            }
        }
        .onChange(of: selectedConnector) { _, _ in model.notice = ""; model.error = "" }
        .sheet(item: $sheet) { route in
            switch route {
            case .add: ServerEditor(draft: ServerDraft(), onSaved: { selectedConnector = $0 })
            case .edit(let id):
                if let server = connector(id) { ServerEditor(draft: ServerDraft(server), onSaved: { selectedConnector = $0 }) }
            case .manage(let id):
                if let server = connector(id) {
                    ConnectorManagementView(server: server, edit: { sheet = .edit(id) })
                }
            }
        }
        .confirmationDialog("Remove this connector and its tool permissions?", isPresented: Binding(get: { removal != nil }, set: { if !$0 { removal = nil } }), titleVisibility: .visible) {
            Button("Remove connector", role: .destructive) {
                if let id = removal { model.act(["action":"server_remove", "id":id]); if selectedConnector == id { selectedConnector = nil } }
                removal = nil
            }
        }
    }
}
private struct ConnectorIconView: View {
    let source: String?
    let fallbackSystemName: String

    var body: some View {
        Group {
            if let source, let icon = ConnectorIconSource(source) {
                switch icon {
                case .embedded(let data):
                    if let image = NSImage(data: data) {
                        Image(nsImage: image).resizable().scaledToFit()
                    } else {
                        fallback
                    }
                case .remote(let url):
                    AsyncImage(url: url) { phase in
                        if let image = phase.image {
                            image.resizable().scaledToFit()
                        } else {
                            fallback
                        }
                    }
                }
            } else {
                fallback
            }
        }
        .frame(width: 38, height: 38)
        .background(Brand.accentSoft, in: RoundedRectangle(cornerRadius: 10))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var fallback: some View {
        Image(systemName: fallbackSystemName)
            .font(.system(size: 20))
            .foregroundStyle(Brand.accent)
    }
}
struct ConnectorManagementView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let server: [String: Any]
    var edit: () -> Void
    var continueSetup: (() -> Void)? = nil
    @State private var clientID = ""
    @State private var scopes = ""
    @State private var authDetails: [String: Any] = [:]
    @State private var checkingSignIn = false
    private var availableScopes: [String] { authDetails["available_scopes"] as? [String] ?? [] }
    @State private var advancedSignIn = false
    private var id: String { server["id"] as? String ?? "" }
    private var oauthStatus: String {
        switch model.oauthStatuses[id] {
        case "pending": "Waiting for browser sign-in…"
        case "sign_in_required": "Sign-in required"
        case "signed_in": "Signed in"
        case "failed": "Sign-in failed. Try again."
        case "discovery_failed": "Authorized. Retry tool discovery."
        case "cancelled": "Sign-in cancelled. Retry when ready."
        default: server["oauth"] as? Bool == true ? "Signed in" : "Not signed in"
        }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack { Text(server["name"] as? String ?? "Connection settings").font(.title2.bold()); Spacer(); Button("Done") { dismiss() } }.padding(28)
            ScrollView { VStack(alignment: .leading, spacing: 20) {
            StatusMessages()
            if model.busy {
                HStack { ProgressView().controlSize(.small); Text(model.activity) }
            }
            if let activity = model.signInActivities[id] {
                HStack { ProgressView().controlSize(.small); Text(activity); Button("Cancel sign-in") { model.cancelSignIn(id) } }
                    .accessibilityIdentifier("connector.progress")
                if let url = model.signInURLs[id] {
                    HStack {
                        Button("Reopen browser") { model.reopenSignIn(id) }
                        Button("Copy sign-in link") { model.copy(url.absoluteString) }
                    }
                    Text("Use the browser profile for the account you want to connect. You can paste the link into another profile.").font(.caption)
                }
            }
            Text(model.statuses[id] ?? "Disconnected").foregroundStyle(Brand.muted)
            if let continueSetup, model.statuses[id] == "Connected" {
                Text("Your connection is ready. Next, choose which tools your apps can use.")
                Button("Choose tools", action: continueSetup).buttonStyle(BrandButtonStyle(primary: true))
                    .accessibilityIdentifier("connector.choose-tools")
            }
            Panel {
                Text("Connection").font(.headline)
                Text(server["transport"] as? String == "stdio" ? (server["command"] as? String ?? "") : (server["url"] as? String ?? "")).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                HStack {
                    Button("Connect / rediscover") { model.act(["action":"connect", "id":id]) }.disabled(model.busy || model.signInActivities[id] != nil)
                    Button("Edit connection", action: edit)
                }
            }
            if server["transport"] as? String == "http" {
                Panel {
                    Text("Browser sign-in (OAuth)").font(.headline)
                    Text(oauthStatus).font(.callout).foregroundStyle(Brand.muted)
                    Button(checkingSignIn ? "Checking…" : "Check sign-in requirements") { checkSignIn() }.disabled(checkingSignIn || model.signInActivities[id] != nil)
                    if let registration = authDetails["registration"] as? String, registration != "unknown" {
                        Text(registration == "automatic" ? "This server supports automatic client registration." : registration == "hosted_metadata" ? "This server supports Umbod’s public OAuth identity." : "This server requires a registered OAuth client. Open advanced options for the callback URL and client ID.").font(.caption)
                    }
                    if authDetails["endpoint_differs"] as? Bool == true, let endpoint = authDetails["canonical_endpoint"] as? String {
                        Text("The server advertises a different endpoint:").font(.caption)
                        Text(endpoint).font(.caption).textSelection(.enabled)
                        HStack { Button("Copy suggested endpoint") { model.copy(endpoint) }; Button("Edit endpoint", action: edit) }
                        Text("Review the address before using it. Umbod has not forwarded your credentials to it.").font(.caption)
                    }
                    if !availableScopes.isEmpty {
                        DisclosureGroup("Choose provider permissions (\(scopes.split(separator: " ").count) selected)") {
                            VStack(alignment: .leading, spacing: 8) { HStack {
                                Button("Select all permissions") { scopes = availableScopes.joined(separator: " ") }
                                Button("Clear permissions") { scopes = "" }
                            }
                            ForEach(availableScopes, id: \.self) { scope in
                                Toggle(scope, isOn: Binding(get: { scopes.split(separator: " ").map(String.init).contains(scope) }, set: { enabled in
                                    var chosen = Set(scopes.split(separator: " ").map(String.init))
                                    if enabled { chosen.insert(scope) } else { chosen.remove(scope) }
                                    scopes = chosen.sorted().joined(separator: " ")
                                })).toggleStyle(.checkbox).font(.caption)
                            } }.frame(maxWidth: .infinity, alignment: .leading)
                        }
                        if scopes.isEmpty { Text("Choose the permissions you want before signing in. Scope names are supplied by the provider.").font(.caption) }
                    }
                    Text("Provider access and enabled tools are separate. Disabling a tool in Umbod does not revoke the provider’s permission.").font(.caption)
                    if let granted = authDetails["granted_scopes"] as? String, !granted.isEmpty {
                        DisclosureGroup("Provider-granted permissions") { Text(granted).font(.caption).textSelection(.enabled) }
                    }
                    Text("The account and workspace are selected in your provider’s browser. MCP does not always report them to Umbod.").font(.caption).foregroundStyle(Brand.muted)
                    Button { advancedSignIn.toggle() } label: {
                        HStack {
                            Text("Advanced sign-in options")
                            Spacer()
                            Image(systemName: advancedSignIn ? "chevron.up" : "chevron.down")
                        }.frame(maxWidth: .infinity).contentShape(Rectangle())
                    }
                    if advancedSignIn {
                        TextField("Public client ID (optional)", text: $clientID)
                        Text("If automatic registration is unavailable, register a native public OAuth client with your provider. Use PKCE, no client secret, and this callback URL:").font(.caption)
                        if let callback = authDetails["callback_url"] as? String {
                            HStack { Text(callback).font(.caption).textSelection(.enabled); Button("Copy callback URL") { model.copy(callback) } }
                        }
                        TextField("OAuth scopes (optional, space-separated)", text: $scopes)
                        Text("Limit the permissions requested at sign-in. Leave blank to use the provider's defaults.").font(.caption)
                    }
                    HStack {
                        Button("Sign in with browser") { model.signIn(id, clientID: clientID, scopes: scopes) }.disabled(checkingSignIn || (!availableScopes.isEmpty && scopes.isEmpty) || authDetails["endpoint_differs"] as? Bool == true)
                        Button("Refresh token") { model.act(["action":"oauth_refresh", "id":id], success: "Token refreshed and transport reconnected.") }
                        Button("Sign out") { model.act(["action":"oauth_logout", "id":id]) }
                    }.disabled(model.busy || model.signInActivities[id] != nil)
                    DisclosureGroup("Connection diagnostics") {
                        Text("Contains setup stages and timestamps only; no tokens, messages, or tool results.").font(.caption)
                        Button("Copy diagnostics") { model.copy((try? JSONText.encode(authDetails["diagnostics"] ?? [])) ?? "[]") }
                    }
                    Text("Signing in automatically connects and discovers your tools.").font(.caption).foregroundStyle(Brand.muted)
                }
            }
        }.padding(.horizontal, 28).padding(.bottom, 28) } }.frame(width: 680).frame(maxHeight: 740).modifier(BrandAppearance())
        .task {
            model.notice = ""
            model.error = model.oauthErrors[id] ?? ""
            scopes = server["oauth_scopes"] as? String ?? ""
            if server["transport"] as? String == "http" {
                authDetails = (try? await model.backend.request(["action": "oauth_details", "id": id])) ?? [:]
                if authDetails["has_authorization"] as? Bool != true { checkSignIn() }
            }

        }
        .onChange(of: model.oauthStatuses[id]) { _, _ in
            Task { authDetails = (try? await model.backend.request(["action": "oauth_details", "id": id])) ?? authDetails }
        }
    }
    private func checkSignIn() {
        checkingSignIn = true
        Task {
            defer { checkingSignIn = false }
            do { authDetails = try await model.backend.request(["action": "oauth_discover", "id": id]) }
            catch { model.error = error.localizedDescription }
        }
    }

}
struct ConnectorToolsView: View {
    @EnvironmentObject var model: AppModel
    let connector: [String: Any]
    var manage: () -> Void
    @State private var query = ""
    @State private var filter = "All tools"
    @State private var selectedName: String?
    @State private var bulkAllow: Bool?
    @State private var bulkNames: [String] = []
    @State private var checkedTools: Set<String> = []
    private var id: String { connector["id"] as? String ?? "" }
    private var tools: [[String: Any]] {
        model.tools.filter { ($0["name"] as? String ?? "").hasPrefix(id + ".") }
            .sorted { ($0["name"] as? String ?? "") < ($1["name"] as? String ?? "") }
    }
    private var filtered: [[String: Any]] {
        tools.filter { tool in
            let name = tool["name"] as? String ?? ""
            let enabled = model.allowedTools.contains(name)
            let readOnly = (tool["annotations"] as? [String: Any])?["readOnlyHint"] as? Bool == true
            return (filter == "All tools" || (filter == "Reported read-only" && readOnly) ||
                    (filter == "Enabled" && enabled) || (filter == "Disabled" && !enabled)) &&
                (query.isEmpty || name.localizedCaseInsensitiveContains(query) || (tool["description"] as? String ?? "").localizedCaseInsensitiveContains(query))
        }
    }
    private var selected: [String: Any]? { filtered.first { $0["name"] as? String == selectedName } ?? filtered.first }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                VStack(alignment: .leading, spacing: 8) {
                    Text(connector["name"] as? String ?? "Connector").font(.system(size: 24, weight: .semibold))
                    Text("\(model.statuses[id] ?? "Disconnected") · \(tools.filter { model.allowedTools.contains($0["name"] as? String ?? "") }.count) of \(tools.count) tools enabled").foregroundStyle(Brand.muted)
                }
                Spacer()
                Button("Connection settings", action: manage)
            }
            Text("Enabled tools are available to every app connected to Umbod.").font(.callout).foregroundStyle(Brand.muted)
                .padding(14).frame(maxWidth: .infinity, alignment: .leading).background(Brand.soft, in: RoundedRectangle(cornerRadius: 8))
            HStack(spacing: 12) {
                TextField("Search tools…", text: $query).frame(maxWidth: 340)
                Picker("Show", selection: $filter) { ForEach(["All tools", "Enabled", "Disabled", "Reported read-only"], id: \.self) { Text($0) } }.frame(width: 180)
                Spacer()
                Button("Enable all") { prepareBulk(tools, allow: true) }
                    .disabled(model.busy || tools.isEmpty || tools.allSatisfy { model.allowedTools.contains($0["name"] as? String ?? "") })
                    .accessibilityIdentifier("tools.enable-all")
                Button("Disable all") { prepareBulk(tools, allow: false) }
                    .disabled(model.busy || !tools.contains { model.allowedTools.contains($0["name"] as? String ?? "") })
                    .accessibilityIdentifier("tools.disable-all")
            }
            if model.busy {
                HStack { ProgressView().controlSize(.small); Text(model.activity) }
            }
            HStack {
                Button("Select filtered (\(filtered.count))") { checkedTools.formUnion(filtered.compactMap { $0["name"] as? String }) }
                Button("Clear selection") { checkedTools.removeAll() }.disabled(checkedTools.isEmpty)
                Text("\(checkedTools.count) selected").font(.caption)
                Spacer()
                Button("Enable selected") { prepareBulk(tools.filter { checkedTools.contains($0["name"] as? String ?? "") }, allow: true) }.disabled(checkedTools.isEmpty || model.busy)
                Button("Disable selected") { prepareBulk(tools.filter { checkedTools.contains($0["name"] as? String ?? "") }, allow: false) }.disabled(checkedTools.isEmpty || model.busy)
            }
            if filter == "Reported read-only" {
                Text("Read-only labels are supplied by the server. Review descriptions and provider permissions; these labels are not security guarantees.").font(.caption).foregroundStyle(Brand.muted)
            }
            if tools.isEmpty {
                ContentUnavailableView("No tools discovered", systemImage: "wrench.and.screwdriver", description: Text("Open connection settings to connect or rediscover tools."))
            } else if filtered.isEmpty {
                ContentUnavailableView.search(text: query)
            } else {
                HStack(alignment: .top, spacing: 24) {
                    ScrollView {
                        VStack(spacing: 0) {
                            ForEach(filtered.indices, id: \.self) { index in
                                let tool = filtered[index]
                                let name = tool["name"] as? String ?? ""
                                HStack(spacing: 10) {
                                    Toggle("Select \(String(name.dropFirst(id.count + 1)))", isOn: Binding(get: { checkedTools.contains(name) }, set: { if $0 { checkedTools.insert(name) } else { checkedTools.remove(name) } })).labelsHidden().toggleStyle(.checkbox)
                                        .accessibilityIdentifier("tool.select.\(String(name.dropFirst(id.count + 1)))")
                                    Button { selectedName = name } label: {
                                        Text(String(name.dropFirst(id.count + 1))).font(.system(size: 12, design: .monospaced))
                                            .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 10).contentShape(Rectangle())
                                    }.buttonStyle(.plain).accessibilityAddTraits(selected?["name"] as? String == name ? [.isSelected] : [])
                                    permissionToggle(name)
                                }.padding(.horizontal, 14).padding(.vertical, 5)
                                    .background(selected?["name"] as? String == name ? Brand.accentSoft : Brand.canvas)
                                if index < filtered.count - 1 { Divider() }
                            }
                        }
                    }.frame(maxWidth: .infinity).frame(height: 470).clipShape(RoundedRectangle(cornerRadius: 12))
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Brand.border))
                    ScrollView {
                        if let tool = selected {
                            let name = tool["name"] as? String ?? ""
                            VStack(alignment: .leading, spacing: 20) {
                                Text("TOOL DETAILS").font(.system(size: 10, design: .monospaced)).tracking(1).foregroundStyle(Brand.muted)
                                Text(String(name.dropFirst(id.count + 1))).font(.system(size: 15, weight: .semibold, design: .monospaced)).textSelection(.enabled)
                                if let readOnly = (tool["annotations"] as? [String: Any])?["readOnlyHint"] as? Bool {
                                    Text(readOnly ? "Server reports: read-only (not a security guarantee)" : "Server reports: may change data").font(.caption).foregroundStyle(Brand.muted)
                                }
                                Text(tool["description"] as? String ?? "No description provided.").font(.system(size: 14)).lineSpacing(4).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                                HStack { Text(model.allowedTools.contains(name) ? "Enabled for your apps" : "Disabled for your apps"); Spacer(); permissionToggle(name) }
                                Divider()
                                DisclosureGroup("Input schema") {
                                    Text((try? JSONText.encode(tool["inputSchema"] ?? [:])) ?? "{}").font(.system(size: 12, design: .monospaced)).textSelection(.enabled).padding(.top, 12)
                                }.id(name)
                            }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }.frame(maxWidth: .infinity).frame(height: 470).background(Brand.soft, in: RoundedRectangle(cornerRadius: 12))
                }
            }
        }
        .task(id: id) { model.notice = ""; model.error = model.oauthErrors[id] ?? "" }
        .sheet(isPresented: Binding(get: { bulkAllow != nil }, set: { if !$0 { bulkAllow = nil } })) {
            VStack(alignment: .leading, spacing: 16) {
                Text("\(bulkAllow == true ? "Enable" : "Disable") \(bulkNames.count) tools?").font(.title2.bold())
                Text("This applies to every connected app. Provider authorization is unchanged.").font(.callout)
                Text("Only these tools will change:").font(.headline)
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        ForEach(bulkNames, id: \.self) { Text($0).font(.system(.caption, design: .monospaced)).textSelection(.enabled) }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }.frame(maxHeight: 280)
                HStack {
                    Button("Cancel") { bulkAllow = nil }.keyboardShortcut(.cancelAction)
                    Spacer()
                    Button(bulkAllow == true ? "Enable these tools" : "Disable these tools") {
                        if let allow = bulkAllow {
                            model.act(["action": "grant_tools", "id": id, "tools": bulkNames, "allow": allow], success: "Updated \(bulkNames.count) tools.")
                        }
                        bulkAllow = nil
                    }.buttonStyle(.borderedProminent)
                }
            }.padding(28).frame(width: 560).modifier(BrandAppearance())
        }
    }
    private func prepareBulk(_ selection: [[String: Any]], allow: Bool) {
        bulkNames = selection.compactMap { $0["name"] as? String }.map { String($0.dropFirst(id.count + 1)) }
        bulkAllow = allow
    }
    private func permissionToggle(_ name: String) -> some View {
        Toggle("Allow \(String(name.dropFirst(id.count + 1)))", isOn: Binding(get: { model.allowedTools.contains(name) }, set: { model.act(["action":"grant", "tool":name, "allow":$0]) }))
            .accessibilityIdentifier("tool.allow.\(String(name.dropFirst(id.count + 1)))").labelsHidden().toggleStyle(.switch).controlSize(.small).disabled(model.busy)
    }
}
