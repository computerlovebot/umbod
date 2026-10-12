import Combine
import Foundation

/// Owns the submission used by the native editor. Only the backend assigns connector IDs.
@MainActor public final class ConnectorEditor: ObservableObject {
    @Published public var draft: ServerDraft
    @Published public var credentialName = "Authorization"
    @Published public var credential = ""
    @Published public private(set) var saving = false
    private let credentialNamespace: String
    private var credentialsChanged = false

    public init(draft: ServerDraft) {
        self.draft = draft
        credentialNamespace = draft.id.isEmpty ? UUID().uuidString.lowercased() : draft.id
    }

    public func save(request: @MainActor ([String: Any]) async throws -> [String: Any]) async throws {
        guard !saving else { throw ContractError.message("A connector save is already in progress") }
        saving = true
        defer { saving = false }
        var payload = try draft.payload()
        if !credential.isEmpty {
            guard !credentialName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw ContractError.message("Enter a credential header or environment name")
            }
            let reference = "upstream:\(credentialNamespace):\(credentialName)"
            let key = draft.transport == "stdio" ? "env" : "headers"
            var references = payload[key] as? [String: String] ?? [:]
            references[credentialName] = reference
            let encoded = try JSONText.encode(references)
            _ = try await request(["action": "secret_set", "reference": reference, "value": credential])
            // Retain the stored reference if saving the connector fails and the user retries.
            if key == "env" { draft.environmentReferences = encoded }
            else { draft.headerReferences = encoded }
            credential = ""
            credentialsChanged = true
            payload[key] = references
        }
        if credentialsChanged { payload["reconnect"] = true }
        let response = try await request(["action": "server_save", "server": payload])
        guard let server = response["server"] as? [String: Any], let id = server["id"] as? String, !id.isEmpty else {
            throw ContractError.message("The backend did not return a connector identity. Refresh the connector list before retrying.")
        }
        // A refresh failure after a successful save must not turn a retry into another create.
        draft.id = id
        credentialsChanged = false
    }
}
