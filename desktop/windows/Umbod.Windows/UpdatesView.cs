using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using Umbod.Core;

namespace Umbod.Windows;

public sealed partial class MainWindow
{
    private readonly StackPanel updatePrompt = new() { Margin = new Thickness(20, 4, 20, 8), Visibility = Visibility.Collapsed };
    private readonly StackPanel updateDetails = new();
    private readonly TextBlock updateStatus = new() { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 8, 0, 8) };
    private readonly System.Windows.Controls.Button checkUpdates = new() { Content = "Check for Updates" };
    private readonly DispatcherTimer updateTimer = new() { Interval = TimeSpan.FromHours(1) };
    private UpdatePreferences updatePreferences = new();
    private bool checkingUpdates;
    private string UpdatePreferencesPath => Path.Combine(profile.DataDirectory, "update-preferences.json");
    private static string InstalledVersion => typeof(MainWindow).Assembly.GetName().Version?.ToString(3) ?? "0.0.0";

    private void BuildUpdates(StackPanel panel)
    {
        if (!smoke) updatePreferences = UpdatePreferences.Load(UpdatePreferencesPath, profile.Name == "release");
        panel.Children.Add(Text("App updates", 22));
        panel.Children.Add(Text($"Installed version: {InstalledVersion}"));
        var automatic = new CheckBox { Content = "Automatically check for updates daily", IsChecked = updatePreferences.Automatic };
        automatic.Click += async (_, _) =>
        {
            updatePreferences.Automatic = automatic.IsChecked == true;
            SaveUpdatePreferences();
            if (updatePreferences.Automatic) await CheckUpdates(false);
        };
        panel.Children.Add(automatic);
        panel.Children.Add(Text("Checks umbod.ai for releases. Updates are downloaded only when you choose."));
        checkUpdates.Click += async (_, _) => await CheckUpdates(true);
        panel.Children.Add(checkUpdates);
        panel.Children.Add(updateStatus);
        panel.Children.Add(updateDetails);
        updateTimer.Tick += async (_, _) => await CheckUpdates(false);
    }
    private void SaveUpdatePreferences()
    {
        if (smoke) return;
        try { updatePreferences.Save(UpdatePreferencesPath); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        { updateStatus.Text = "Couldn’t save update preferences. Check access to the app data folder."; }
    }
    private async Task CheckUpdates(bool manual)
    {
        if (smoke || checkingUpdates || (!manual && !DesktopUpdate.IsDue(updatePreferences.Automatic, updatePreferences.LastAttempt, DateTimeOffset.UtcNow))) return;
        checkingUpdates = true; checkUpdates.IsEnabled = false;
        updateStatus.Text = "Checking for updates…";
        updatePreferences.LastAttempt = DateTimeOffset.UtcNow;
        SaveUpdatePreferences();
        var cancellation = lifetime.Token;
        try
        {
            var update = await DesktopUpdate.CheckAsync(InstalledVersion, cancellation);
            if (cancellation.IsCancellationRequested) return;
            updateDetails.Children.Clear(); updatePrompt.Children.Clear(); updatePrompt.Visibility = Visibility.Collapsed;
            updateStatus.Text = update == null ? $"No newer published update found. You have {InstalledVersion}." : $"Umbod {update.Version} is available.";
            if (update == null) return;
            updatePrompt.Children.Add(Text($"Umbod {update.Version} is available."));
            var review = new System.Windows.Controls.Button { Content = "View update" };
            review.Click += (_, _) => Tabs.SelectedIndex = 2;
            updatePrompt.Children.Add(review);
            var later = new System.Windows.Controls.Button { Content = "Later" };
            later.Click += (_, _) => updatePrompt.Visibility = Visibility.Collapsed;
            updatePrompt.Children.Add(later);
            updatePrompt.Visibility = manual || update.Version != updatePreferences.SkippedVersion ? Visibility.Visible : Visibility.Collapsed;
            updateDetails.Children.Add(Text($"Unsigned prerelease · {update.Version}", 18));
            updateDetails.Children.Add(new TextBlock { Text = "1. Download the ZIP.\n2. Close your MCP clients, then choose Quit for Update below. Active tool calls will be interrupted.\n3. Extract the entire ZIP into a new folder. Open Umbod.Windows.exe there and update any shortcuts. Your connections and settings are kept.\nWindows may require approval to open this unsigned app. Keep system security enabled.", TextWrapping = TextWrapping.Wrap });
            updateDetails.Children.Add(Button("Download Update", () => { OpenUpdateLink(update.Download); return Task.CompletedTask; }));
            updateDetails.Children.Add(Button("Release notes", () => { OpenUpdateLink(update.ReleaseNotes); return Task.CompletedTask; }));
            updateDetails.Children.Add(Button("Skip this version", () => { updatePreferences.SkippedVersion = update.Version; SaveUpdatePreferences(); updatePrompt.Visibility = Visibility.Collapsed; updateStatus.Text = "Automatic reminders for this version are skipped. You can still download it below."; return Task.CompletedTask; }));
            updateDetails.Children.Add(new Expander { Header = "Download SHA-256", Content = new TextBox { Text = update.Sha256, IsReadOnly = true, TextWrapping = TextWrapping.Wrap } });
            updateDetails.Children.Add(Button("Quit for Update…", async () =>
            {
                if (MessageBox.Show(this, "Finish downloading and close your MCP clients first. Stop the gateway and quit Umbod? Active tool calls will be interrupted.", "Quit for Update", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                await gateway.StopAsync(lifetime.Token);
                Close();
            }));
        }
        catch (Exception) when (!cancellation.IsCancellationRequested) { updateStatus.Text = "Couldn’t check for updates. Check your connection and try again."; }
        catch (OperationCanceledException) { }
        finally { checkingUpdates = false; checkUpdates.IsEnabled = true; }
    }
    private void OpenUpdateLink(Uri url)
    {
        Process.Start(new ProcessStartInfo(url.AbsoluteUri) { UseShellExecute = true });
        updateStatus.Text = "Opened in your browser. Finish downloading before quitting.";
    }
}
