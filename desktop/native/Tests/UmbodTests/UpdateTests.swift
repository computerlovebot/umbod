import Foundation
import UmbodCore

func updateTests() throws {
    let desktop = ProcessInfo.processInfo.environment["UMBOD_TEST_RESOURCES"].map { URL(fileURLWithPath: $0) } ?? URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    let data = try Data(contentsOf: desktop.appendingPathComponent("tests/fixtures/update-manifest.json"))
    let update = try DesktopUpdate.parse(data, installed: "0.2.0")
    precondition(update?.version == "0.10.0", "Compare numeric versions, not strings")
    precondition(update?.download.lastPathComponent == "Umbod-0.10.0-arm64.dmg")
    precondition(update?.releaseNotes.lastPathComponent == "desktop-v0.10.0")
    var macOnly = try JSONSerialization.jsonObject(with: data) as! [String: Any]
    var assets = macOnly["assets"] as! [String: Any]
    assets.removeValue(forKey: "windows-x64")
    macOnly["assets"] = assets
    let macUpdate = try DesktopUpdate.parse(JSONSerialization.data(withJSONObject: macOnly), installed: "0.2.0")
    precondition(macUpdate?.download == update?.download, "Accept new macOS-only releases")
    assets.removeValue(forKey: "macos-arm64")
    macOnly["assets"] = assets
    var rejectedMissingMac = false
    do { _ = try DesktopUpdate.parse(JSONSerialization.data(withJSONObject: macOnly), installed: "0.2.0") }
    catch { rejectedMissingMac = true }
    precondition(rejectedMissingMac, "A Mac installer is required")
    let equal = try DesktopUpdate.parse(data, installed: "0.10.0")
    let older = try DesktopUpdate.parse(data, installed: "1.0.0")
    precondition(equal == nil && older == nil, "Never offer same-version reinstalls or downgrades")
    let unavailable = try DesktopUpdate.parse(Data(#"{"schemaVersion":1,"status":"unavailable"}"#.utf8), installed: "0.2.0")
    precondition(unavailable == nil)
    for value in ["0.2", "v0.2.0", "0.02.0", "0.2.0-beta", "-1.0.0", "2147483648.0.0", "0.2.0\n"] {
        var rejected = false
        do { _ = try DesktopVersion(value) } catch { rejected = true }
        precondition(rejected, "Reject invalid installed version \(value)")
    }
    let original = String(decoding: data, as: UTF8.self)
    for (from, to) in [
        ("\"schemaVersion\": 1", "\"schemaVersion\": 2"),
        ("\"available\"", "\"draft\""), ("unsigned-prerelease", "stable"),
        ("desktop-v0.10.0", "latest"), ("https://github.com/", "http://github.com/"),
        ("computerlovetech/umbod/", "someone/umbod/"), ("github.com/", "github.com.evil.example/"),
        ("arm64.dmg", "arm64.dmg?token=secret"), ("arm64.dmg", "arm64.exe"),
        ("\"size\": 123", "\"size\": 0"), (String(repeating: "b", count: 64), "bad-hash"),
        (String(repeating: "a", count: 40), "main"), ("windows-x64", "windows-arm64")
    ] {
        var rejected = false
        do { _ = try DesktopUpdate.parse(Data(original.replacingOccurrences(of: from, with: to).utf8), installed: "0.2.0") }
        catch { rejected = true }
        precondition(rejected, "Reject unsafe update manifest: \(to)")
    }
    let now = Date()
    precondition(DesktopUpdate.isDue(enabled: true, lastAttempt: nil, now: now))
    precondition(!DesktopUpdate.isDue(enabled: false, lastAttempt: nil, now: now))
    precondition(!DesktopUpdate.isDue(enabled: true, lastAttempt: now.addingTimeInterval(-3600), now: now))
    precondition(DesktopUpdate.isDue(enabled: true, lastAttempt: now.addingTimeInterval(-86400), now: now))
    precondition(DesktopUpdate.isDue(enabled: true, lastAttempt: now.addingTimeInterval(1), now: now))
    print("PASS: update versions, trusted installer URLs, malformed manifests, withdrawal and daily scheduling")
}
