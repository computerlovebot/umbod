/// Ordered permission edits with an optimistic projection over the last saved state.
/// Owned by the main actor; only one request may be drained at a time.
public struct ToolPermissionQueue {
    public struct Edit {
        public let names: [String]
        public let allow: Bool
        public let connectorID: String?

        public var request: [String: Any] {
            if let connectorID {
                return ["action": "grant_tools", "id": connectorID,
                        "tools": names.map { String($0.dropFirst(connectorID.count + 1)) }, "allow": allow]
            }
            return ["action": "grant", "tool": names[0], "allow": allow]
        }
    }

    private var confirmed: Set<String> = []
    private var pending: [Edit] = []
    public private(set) var revision = 0
    public var first: Edit? { pending.first }
    public var isSaving: Bool { !pending.isEmpty }
    public var allowedTools: Set<String> {
        var result = confirmed
        for edit in pending { apply(edit, to: &result) }
        return result
    }

    public init() {}

    public mutating func enqueue(names: [String], allow: Bool, connectorID: String? = nil) {
        guard !names.isEmpty else { return }
        pending.append(Edit(names: names, allow: allow, connectorID: connectorID))
        revision += 1
    }

    public mutating func complete(succeeded: Bool) {
        let edit = pending.removeFirst()
        if succeeded { apply(edit, to: &confirmed) }
        revision += 1
    }

    /// Discard status snapshots that overlapped a permission write.
    public mutating func refresh(_ allowed: Set<String>, startedAt revision: Int) {
        guard pending.isEmpty, revision == self.revision else { return }
        confirmed = allowed
    }

    private func apply(_ edit: Edit, to tools: inout Set<String>) {
        if edit.allow { tools.formUnion(edit.names) }
        else { tools.subtract(edit.names) }
    }
}
