import Foundation
import Darwin
@MainActor public final class Backend {
    private var process: Process?
    private var owner: Pipe?
    private var token = ""
    private var persistent = false
    private var runtimeFile: URL?
    private var isolatedDirectory: URL?
    private var attachedPID: Int32 = 0
    public private(set) var updateAvailable = false
    public private(set) var management = ""
    public private(set) var gateway = ""
    public var processID: Int32 { process?.processIdentifier ?? attachedPID }
    public var isRunning: Bool { process?.isRunning ?? (attachedPID > 0 && kill(attachedPID, 0) == 0) }
    public init() {}
    public func start(executable: URL? = nil, directory: URL? = nil, persistent: Bool = false, environment: AppEnvironment = .current, testCredentials: Bool = false) async throws {
        guard !isRunning else { return }
        stop()
        if testCredentials && directory == nil { throw ContractError.message("Test credentials require an isolated directory") }
        var executable = executable ?? Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/umbod-desktop")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else { throw ContractError.message("Bundled gateway is missing. Reinstall Umbod.app.") }
        let contents = executable.deletingLastPathComponent().deletingLastPathComponent()
        let buildID = (try? String(contentsOf: contents.appendingPathComponent("Resources/runtime-id"), encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)) ?? "development"
        self.persistent = persistent
        self.isolatedDirectory = directory
        let directory = directory ?? environment.dataDirectory
        runtimeFile = directory.appendingPathComponent("python-runtime.json")
        if persistent {
            if let data = try? Data(contentsOf: runtimeFile!),
               let record = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               record["profile"] as? String == environment.rawValue,
               let pid = record["pid"] as? Int32,
               let address = record["management"] as? String,
               let endpoint = record["gateway"] as? String,
               Self.isLoopbackAddress(address), Self.isLoopbackAddress(endpoint) {
                let savedToken = try await Self.adminToken(executable: directory.appendingPathComponent("bin/umbod-desktop"), environment: environment, directory: self.isolatedDirectory, testCredentials: testCredentials)
                attachedPID = pid; token = savedToken; management = address; gateway = endpoint
                do {
                    let health = try await request(["action": "health"], timeout: 2)
                    guard health["profile"] as? String == environment.rawValue, health["pid"] as? Int32 == pid else {
                        throw ContractError.message("Gateway identity does not match this app.")
                    }
                    updateAvailable = health["build_id"] as? String != buildID
                    _ = try await AdministrationClient(origin: "http://\(management)", token: token).send("POST", "/desktop/migration")
                    return
                }
                catch { attachedPID = 0; token = ""; management = ""; gateway = "" }
            }
        }
        if persistent {
            guard UUID(uuidString: buildID) != nil else { throw ContractError.message("Invalid packaged runtime identity") }
            let installed = directory.appendingPathComponent("runtimes/" + buildID)
            if !FileManager.default.fileExists(atPath: installed.path) {
                let staging = directory.appendingPathComponent("runtimes/.staging-" + UUID().uuidString)
                try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
                do {
                    try FileManager.default.copyItem(at: contents, to: staging.appendingPathComponent("Contents"))
                    try FileManager.default.moveItem(at: staging, to: installed)
                } catch { try? FileManager.default.removeItem(at: staging); throw error }
            }
            executable = installed.appendingPathComponent("Contents/MacOS/umbod-desktop")
            let bin = directory.appendingPathComponent("bin")
            try FileManager.default.createDirectory(at: bin, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            for name in ["umbod-desktop", "umbod-gateway"] {
                let temporary = bin.appendingPathComponent(".bridge-" + UUID().uuidString)
                try FileManager.default.createSymbolicLink(at: temporary, withDestinationURL: executable)
                guard rename(temporary.path, bin.appendingPathComponent(name).path) == 0 else { throw ContractError.message("Cannot install agent bridge") }
            }
        }
        let child = Process(); child.executableURL = executable
        child.arguments = ["serve", "--profile", environment.rawValue]
        if let isolatedDirectory { child.arguments! += ["--data-dir", isolatedDirectory.path] }
        if persistent { child.arguments!.append("--persistent") }
        if testCredentials { child.arguments!.append("--test-credentials") }
        let input = Pipe(), output = Pipe()
        child.standardInput = input; child.standardOutput = output; child.standardError = self.isolatedDirectory == nil ? FileHandle.nullDevice : FileHandle.standardError
        token = UUID().uuidString + UUID().uuidString
        try child.run(); process = child; owner = input
        let timeout = Task { @MainActor in
            try? await Task.sleep(for: .seconds(60))
            if !Task.isCancelled && self.management.isEmpty { child.terminate(); self.stop() }
        }
        let data = await Task.detached { output.fileHandleForReading.availableData }.value
        timeout.cancel()
        let startupResult = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        if let message = startupResult?["error"] as? String { if child.isRunning { child.terminate() }; stop(); throw ContractError.message(message) }
        guard let ready = startupResult,
              let management = ready["management"] as? String, let gateway = ready["gateway"] as? String,
              Self.isLoopbackAddress(management), Self.isLoopbackAddress(gateway) else {
            if child.isRunning { child.terminate() }; stop(); throw ContractError.message("Gateway could not start. Check Keychain access and configuration, then retry.")
        }
        guard let startupToken = ready["admin_token"] as? String else { throw ContractError.message("Missing backend authentication") }
        token = startupToken
        self.management = management; self.gateway = gateway; updateAvailable = false
        _ = try await request(["action": "health"])
        _ = try await AdministrationClient(origin: "http://\(management)", token: token).send("POST", "/desktop/migration")
    }
    public func request(_ body: [String: Any], timeout: TimeInterval = 45) async throws -> [String: Any] {
        guard isRunning else { throw ContractError.message("Backend stopped. Restart it in Settings.") }
        return try await AdministrationClient(origin: "http://\(management)", token: token, timeout: timeout).action(body)
    }
    private static func isLoopbackAddress(_ address: String) -> Bool {
        guard let url = URLComponents(string: "http://" + address) else { return false }
        return url.host == "127.0.0.1" && url.port != nil && url.user == nil && url.password == nil && url.path.isEmpty && url.query == nil && url.fragment == nil
    }
    // The same installed Python executable owns every Keychain operation. Swift never
    // becomes a second Keychain client, and credentials travel only through a pipe.
    private static func adminToken(executable: URL, environment: AppEnvironment, directory: URL?, testCredentials: Bool) async throws -> String {
        let child = Process(), output = Pipe()
        child.executableURL = executable
        child.arguments = ["credential", "--profile", environment.rawValue]
        if let directory { child.arguments! += ["--data-dir", directory.path] }
        if testCredentials { child.arguments!.append("--test-credentials") }
        child.standardOutput = output; child.standardError = FileHandle.nullDevice
        try child.run()
        let data = await Task.detached { output.fileHandleForReading.readDataToEndOfFile() }.value
        child.waitUntilExit()
        guard child.terminationStatus == 0,
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let token = value["admin_token"] as? String else {
            throw ContractError.message("Cannot read the backend credential. Unlock Keychain and retry.")
        }
        return token
    }
    /// Explicitly stop this environment's gateway; never signal a PID from disk.
    public func shutdown() async throws {
        guard isRunning else { stop(); return }
        if !persistent { stop(); return }
        _ = try await request(["action": "shutdown"], timeout: 5)
        for _ in 0..<100 {
            if let runtimeFile, !FileManager.default.fileExists(atPath: runtimeFile.path) {
                stop(); return
            }
            try await Task.sleep(for: .milliseconds(50))
        }
        throw ContractError.message("Gateway is still shutting down. Wait a moment before restarting.")
    }
    /// Detach from a persistent gateway. Owned test processes still stop with the UI.
    public func stop() {
        try? owner?.fileHandleForWriting.close(); owner = nil
        if let process, !persistent {
            let deadline = Date().addingTimeInterval(4)
            while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
            if process.isRunning { process.terminate() }
        }
        process = nil; attachedPID = 0; management = ""; gateway = ""; token = ""
    }
}
