import UmbodCore

func toolPermissionQueueTests() {
    var queue = ToolPermissionQueue()
    queue.refresh(["c.a", "c.b"], startedAt: queue.revision)
    let staleRevision = queue.revision
    queue.enqueue(names: ["c.a"], allow: false)
    queue.enqueue(names: ["c.b"], allow: false)
    precondition(queue.allowedTools.isEmpty, "Multiple clicks must display immediately")
    precondition(queue.first?.request["tool"] as? String == "c.a")
    queue.refresh(["c.a", "c.b"], startedAt: queue.revision)
    precondition(queue.allowedTools.isEmpty, "Polling must not overwrite pending edits")
    queue.complete(succeeded: true)
    queue.complete(succeeded: false)
    precondition(queue.allowedTools == ["c.b"], "Failure reverts only the failed edit")
    queue.refresh(["c.a", "c.b"], startedAt: staleRevision)
    precondition(queue.allowedTools == ["c.b"], "An old refresh must not undo completed writes")

    queue.enqueue(names: ["c.a"], allow: true)
    queue.enqueue(names: ["c.a"], allow: false)
    queue.enqueue(names: ["c.a"], allow: true)
    queue.complete(succeeded: false)
    precondition(queue.allowedTools.contains("c.a"), "Failure must preserve a later click on the same tool")
    queue.complete(succeeded: true)
    precondition(queue.allowedTools.contains("c.a"))
    queue.complete(succeeded: true)
    precondition(queue.allowedTools == ["c.a", "c.b"])

    queue.enqueue(names: ["c.a", "c.b"], allow: false, connectorID: "c")
    precondition(queue.first?.request["tools"] as? [String] == ["a", "b"])
    queue.enqueue(names: ["c.a"], allow: true)
    queue.complete(succeeded: true)
    precondition(queue.allowedTools == ["c.a"], "Single edits after a bulk edit must win")
    queue.complete(succeeded: true)
    precondition(!queue.isSaving)
    queue.refresh(["c.b"], startedAt: queue.revision)
    precondition(queue.allowedTools == ["c.b"], "Idle reconciliation must use backend facts")
    ContractTests.log("PASS: optimistic permission edits, ordered bulk/single changes, rollback and stale refresh protection")
}
