import Foundation
import UmbodCore

@MainActor func connectorEditorTests() async throws {
    var draft = ServerDraft()
    draft.name = "New connector"
    let editor = ConnectorEditor(draft: draft)
    try await editor.save { request in
        precondition(request["action"] as? String == "server_save")
        precondition((request["server"] as! [String: Any])["id"] as? String == "", "New connectors must use create, never a locally generated update ID")
        return ["server": ["id": "canonical"]]
    }
    precondition(editor.draft.id == "canonical")
    try await editor.save { request in
        precondition((request["server"] as! [String: Any])["id"] as? String == "canonical", "Edits and retries after refresh failures must preserve the backend identity")
        return ["server": ["id": "canonical"]]
    }
    for transport in ["stdio", "http"] {
        draft.transport = transport
        let editor = ConnectorEditor(draft: draft)
        editor.credentialName = "FIXTURE"
        editor.credential = "fixture-only"
        var stored = ""
        var calls = 0
        do {
            try await editor.save { request in
                calls += 1
                if request["action"] as? String == "secret_set" {
                    stored = request["reference"] as! String
                    return [:]
                }
                let payload = request["server"] as! [String: Any]
                precondition(payload["id"] as? String == "")
                precondition(payload["reconnect"] as? Bool == true)
                precondition((payload[transport == "stdio" ? "env" : "headers"] as! [String: String])["FIXTURE"] == stored)
                throw ContractError.message("Fixture save failure")
            }
            preconditionFailure("Expected failure")
        } catch { precondition(error.localizedDescription == "Fixture save failure") }
        precondition(calls == 2 && !stored.isEmpty && editor.credential.isEmpty && editor.draft.id.isEmpty && !editor.saving)
        try await editor.save { request in
            precondition(request["action"] as? String == "server_save", "Retry must reuse the stored credential")
            let payload = request["server"] as! [String: Any]
            precondition(payload["id"] as? String == "")
            precondition(payload["reconnect"] as? Bool == true)
            precondition((payload[transport == "stdio" ? "env" : "headers"] as! [String: String])["FIXTURE"] == stored)
            return ["server": ["id": "pending:fixture"]]
        }
        precondition(editor.draft.id == "pending:fixture")
    }
    let invalid = ConnectorEditor(draft: draft)
    invalid.credential = "fixture-only"
    invalid.draft.headerReferences = "[]"
    do {
        try await invalid.save { _ in preconditionFailure("Validation must precede credential writes") }
        preconditionFailure("Expected validation failure")
    } catch {}
    precondition(invalid.credential == "fixture-only" && !invalid.saving)
    invalid.draft.headerReferences = "{}"
    do {
        try await invalid.save { _ in throw ContractError.message("Fixture vault failure") }
        preconditionFailure("Expected vault failure")
    } catch {}
    precondition(invalid.credential == "fixture-only" && invalid.draft.headerReferences == "{}")
    ContractTests.log("PASS: editor create/edit identities, credential failure/retry, pending identity and validation")
}
