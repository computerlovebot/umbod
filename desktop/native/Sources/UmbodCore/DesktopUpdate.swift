import Foundation

public struct DesktopVersion: Comparable, Sendable {
    private let parts: [Int]
    public init(_ value: String) throws {
        let strings = value.split(separator: ".", omittingEmptySubsequences: false)
        guard strings.count == 3, strings.allSatisfy({
            !$0.isEmpty && ($0 == "0" || !$0.hasPrefix("0")) && $0.allSatisfy({ $0 >= "0" && $0 <= "9" })
                && Int($0).map({ $0 <= Int32.max }) == true
        }) else { throw ContractError.message("Invalid desktop version") }
        parts = strings.map { Int($0)! }
    }
    public static func < (lhs: Self, rhs: Self) -> Bool { lhs.parts.lexicographicallyPrecedes(rhs.parts) }
}

public struct DesktopUpdate: Sendable {
    public let version: String
    public let download: URL
    public let sha256: String
    public var releaseNotes: URL { URL(string: "https://github.com/computerlovetech/umbod/releases/tag/desktop-v\(version)")! }
    public static let manifestURL = URL(string: "https://umbod.ai/desktop-downloads.json")!

    private struct Manifest: Decodable {
        let schemaVersion: Int
        let status: String
        let version: String?
        let tag: String?
        let sourceCommit: String?
        let channel: String?
        let assets: [String: Asset]?
    }
    private struct Asset: Decodable { let url: String; let sha256: String; let size: Int64 }

    public static func parse(_ data: Data, installed: String) throws -> DesktopUpdate? {
        guard data.count <= 65_536 else { throw ContractError.message("Update response is too large") }
        let current = try DesktopVersion(installed)
        let manifest = try JSONDecoder().decode(Manifest.self, from: data)
        guard manifest.schemaVersion == 1 else { throw ContractError.message("Unsupported update manifest") }
        if manifest.status == "unavailable" { return nil }
        guard manifest.status == "available", let version = manifest.version,
              manifest.tag == "desktop-v\(version)", manifest.channel == "unsigned-prerelease",
              isHex(manifest.sourceCommit ?? "", count: 40), let assets = manifest.assets,
              (Set(assets.keys) == Set(["macos-arm64"]) || Set(assets.keys) == Set(["macos-arm64", "windows-x64"])) else {
            throw ContractError.message("Invalid update manifest")
        }
        let latest = try DesktopVersion(version)
        // The optional Windows entry is read-only compatibility with historical releases.
        let files = ["macos-arm64": "Umbod-\(version)-arm64.dmg", "windows-x64": "Umbod-\(version)-release-win-x64.zip"]
        for platform in assets.keys {
            let file = files[platform]!
            guard let asset = assets[platform], asset.size > 0, isHex(asset.sha256, count: 64),
                  asset.url == "https://github.com/computerlovetech/umbod/releases/download/desktop-v\(version)/\(file)" else {
                throw ContractError.message("Invalid update download")
            }
        }
        guard latest > current, let asset = assets["macos-arm64"] else { return nil }
        return DesktopUpdate(version: version, download: URL(string: asset.url)!, sha256: asset.sha256)
    }
    private static func isHex(_ value: String, count: Int) -> Bool {
        value.count == count && value.allSatisfy { ("0"..."9").contains($0) || ("a"..."f").contains($0) }
    }
    public static func check(installed: String) async throws -> DesktopUpdate? {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.urlCredentialStorage = nil
        configuration.timeoutIntervalForRequest = 15
        configuration.timeoutIntervalForResource = 20
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let request = URLRequest(url: manifestURL, cachePolicy: .reloadIgnoringLocalCacheData)
        let (bytes, response) = try await session.bytes(for: request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200,
              response.url == manifestURL else { throw ContractError.message("The update service is unavailable") }
        var data = Data()
        for try await byte in bytes {
            guard data.count < 65_536 else { throw ContractError.message("Update response is too large") }
            data.append(byte)
        }
        return try parse(data, installed: installed)
    }
    public static func isDue(enabled: Bool, lastAttempt: Date?, now: Date = Date()) -> Bool {
        guard enabled else { return false }
        guard let lastAttempt else { return true }
        let elapsed = now.timeIntervalSince(lastAttempt)
        return elapsed < 0 || elapsed >= 86_400
    }
}
