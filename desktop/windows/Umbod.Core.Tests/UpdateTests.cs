using System.Text;
using Umbod.Core;

static class UpdateTests
{
    public static void Run()
    {
        static void Check(bool result, string name) { if (!result) throw new Exception(name); }
        var original = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "update-manifest.json"));
        var data = Encoding.UTF8.GetBytes(original);
        var update = DesktopUpdate.Parse(data, "0.2.0");
        Check(update?.Version == "0.10.0", "Versions compare numerically");
        Check(update!.Download.AbsoluteUri.EndsWith("Umbod-0.10.0-release-win-x64.zip", StringComparison.Ordinal), "Windows installer selected");
        Check(update.ReleaseNotes.AbsoluteUri.EndsWith("desktop-v0.10.0", StringComparison.Ordinal), "Exact release notes");
        Check(DesktopUpdate.Parse(data, "0.10.0") == null && DesktopUpdate.Parse(data, "1.0.0") == null, "No reinstalls or downgrades");
        Check(DesktopUpdate.Parse(Encoding.UTF8.GetBytes("""{"schemaVersion":1,"status":"unavailable"}"""), "0.2.0") == null, "Withdrawn releases aren't offered");
        foreach (var version in new[] { "0.2", "v0.2.0", "0.02.0", "0.2.0-beta", "-1.0.0", "2147483648.0.0", "0.2.0\n" })
        {
            var rejected = false;
            try { DesktopUpdate.Parse(data, version); } catch (InvalidDataException) { rejected = true; }
            Check(rejected, "Reject invalid installed version: " + version);
        }
        foreach (var (from, to) in new[] {
            ("\"schemaVersion\": 1", "\"schemaVersion\": 2"), ("\"available\"", "\"draft\""),
            ("unsigned-prerelease", "stable"), ("desktop-v0.10.0", "latest"),
            ("https://github.com/", "http://github.com/"), ("computerlovetech/umbod/", "someone/umbod/"),
            ("github.com/", "github.com.evil.example/"), ("win-x64.zip", "win-x64.zip?token=secret"),
            ("win-x64.zip", "win-x64.exe"), ("\"size\": 123", "\"size\": 0"),
            (new string('b', 64), "bad-hash"), (new string('a', 40), "main"), ("macos-arm64", "macos-x64") })
        {
            var rejected = false;
            try { DesktopUpdate.Parse(Encoding.UTF8.GetBytes(original.Replace(from, to, StringComparison.Ordinal)), "0.2.0"); }
            catch (Exception error) when (error is InvalidDataException or KeyNotFoundException) { rejected = true; }
            Check(rejected, "Reject unsafe update manifest: " + to);
        }
        var now = DateTimeOffset.UtcNow;
        Check(DesktopUpdate.IsDue(true, null, now) && !DesktopUpdate.IsDue(false, null, now), "Automatic preference respected");
        Check(!DesktopUpdate.IsDue(true, now.AddHours(-1), now) && DesktopUpdate.IsDue(true, now.AddDays(-1), now), "Daily scheduling");
        Check(DesktopUpdate.IsDue(true, now.AddHours(1), now), "Clock rollback recovers");
        var path = Path.Combine(Path.GetTempPath(), "umbod-update-test-" + Guid.NewGuid().ToString("N"), "preferences.json");
        try
        {
            Check(!UpdatePreferences.Load(path, false).Automatic, "Development checks default off");
            new UpdatePreferences { Automatic = false, LastAttempt = now, SkippedVersion = "0.10.0" }.Save(path);
            var saved = UpdatePreferences.Load(path, true);
            Check(!saved.Automatic && saved.LastAttempt == now && saved.SkippedVersion == "0.10.0", "Update preferences survive restart");
            File.WriteAllText(path, "invalid json");
            Check(UpdatePreferences.Load(path, true).Automatic, "Corrupt preferences don't prevent startup");
        }
        finally { if (Directory.Exists(Path.GetDirectoryName(path))) Directory.Delete(Path.GetDirectoryName(path)!, true); }
        Console.WriteLine("PASS update versions, trusted installers, malformed manifests, withdrawal, scheduling and preferences");
    }
}
