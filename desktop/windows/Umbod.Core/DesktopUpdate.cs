using System.Text.Json;
using System.Text.RegularExpressions;

namespace Umbod.Core;

public sealed record DesktopUpdate(string Version, Uri Download, string Sha256)
{
    public Uri ReleaseNotes => new($"https://github.com/computerlovetech/umbod/releases/tag/desktop-v{Version}");
    public static readonly Uri ManifestUrl = new("https://umbod.ai/desktop-downloads.json");
    private static System.Version ParseVersion(string value)
    {
        if (!Regex.IsMatch(value, @"\A(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\z") || !System.Version.TryParse(value, out var version))
            throw new InvalidDataException("Invalid desktop version.");
        return version;
    }
    public static DesktopUpdate? Parse(byte[] data, string installed)
    {
        if (data.Length > 65_536) throw new InvalidDataException("Update response is too large.");
        var current = ParseVersion(installed);
        using var document = JsonDocument.Parse(data);
        var root = document.RootElement;
        if (root.GetProperty("schemaVersion").GetInt32() != 1) throw new InvalidDataException("Unsupported update manifest.");
        if (root.GetProperty("status").GetString() == "unavailable") return null;
        var version = root.GetProperty("version").GetString() ?? "";
        var latest = ParseVersion(version);
        if (root.GetProperty("status").GetString() != "available" || root.GetProperty("tag").GetString() != $"desktop-v{version}"
            || root.GetProperty("channel").GetString() != "unsigned-prerelease"
            || !Regex.IsMatch(root.GetProperty("sourceCommit").GetString() ?? "", @"\A[a-f0-9]{40}\z"))
            throw new InvalidDataException("Invalid update manifest.");
        var assets = root.GetProperty("assets");
        if (assets.EnumerateObject().Count() != 2) throw new InvalidDataException("Invalid update assets.");
        foreach (var (platform, file) in new[] { ("macos-arm64", $"Umbod-{version}-arm64.dmg"), ("windows-x64", $"Umbod-{version}-release-win-x64.zip") })
        {
            var asset = assets.GetProperty(platform);
            if (asset.GetProperty("url").GetString() != $"https://github.com/computerlovetech/umbod/releases/download/desktop-v{version}/{file}"
                || asset.GetProperty("size").GetInt64() <= 0 || !Regex.IsMatch(asset.GetProperty("sha256").GetString() ?? "", @"\A[a-f0-9]{64}\z"))
                throw new InvalidDataException("Invalid update download.");
        }
        var windows = assets.GetProperty("windows-x64");
        return latest > current ? new(version, new Uri(windows.GetProperty("url").GetString()!), windows.GetProperty("sha256").GetString()!) : null;
    }
    public static async Task<DesktopUpdate?> CheckAsync(string installed, CancellationToken cancellation = default)
    {
        using var handler = new HttpClientHandler { AllowAutoRedirect = false, UseCookies = false, UseDefaultCredentials = false };
        using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(20), MaxResponseContentBufferSize = 65_536 };
        using var response = await client.GetAsync(ManifestUrl, cancellation);
        if (response.StatusCode != System.Net.HttpStatusCode.OK) throw new HttpRequestException("The update service is unavailable.");
        return Parse(await response.Content.ReadAsByteArrayAsync(cancellation), installed);
    }
    public static bool IsDue(bool enabled, DateTimeOffset? lastAttempt, DateTimeOffset now) =>
        enabled && (lastAttempt is null || now < lastAttempt || now - lastAttempt >= TimeSpan.FromDays(1));
}

public sealed class UpdatePreferences
{
    public bool Automatic { get; set; } = true;
    public DateTimeOffset? LastAttempt { get; set; }
    public string? SkippedVersion { get; set; }
    public static UpdatePreferences Load(string path, bool defaultAutomatic)
    {
        try { return JsonSerializer.Deserialize<UpdatePreferences>(File.ReadAllText(path)) ?? new() { Automatic = defaultAutomatic }; }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException) { return new() { Automatic = defaultAutomatic }; }
    }
    public void Save(string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllText(temporary, JsonSerializer.Serialize(this)); File.Move(temporary, path, true); }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
