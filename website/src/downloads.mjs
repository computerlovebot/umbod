const VERSION = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;
const PLATFORMS = {
  'macos-arm64': { label: 'macOS · Apple Silicon', requirements: 'macOS 14 or later. Ad-hoc signed; not notarized.', file: v => `Umbod-${v}-arm64.dmg` },
  'windows-x64': { label: 'Windows x64', requirements: 'Windows 10/11, x64. Unsigned, self-contained ZIP.', file: v => `Umbod-${v}-release-win-x64.zip` },
};
function exactKeys(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join(',') !== [...keys].sort().join(',')) throw Error('Invalid desktop manifest shape');
}
export function validateManifest(m) {
  if (m?.status === 'unavailable') {
    exactKeys(m, ['schemaVersion', 'status']);
    if (m.schemaVersion !== 1) throw Error('Unsupported manifest schema');
    return m;
  }
  exactKeys(m, ['schemaVersion', 'status', 'version', 'tag', 'sourceCommit', 'channel', 'assets']);
  if (m.schemaVersion !== 1 || m.status !== 'available' || typeof m.version !== 'string' || !VERSION.test(m.version) || m.tag !== `desktop-v${m.version}` || m.channel !== 'unsigned-prerelease' || !/^[a-f0-9]{40}$/.test(m.sourceCommit)) throw Error('Invalid desktop release');
  exactKeys(m.assets, Object.keys(PLATFORMS));
  for (const [platform, info] of Object.entries(PLATFORMS)) {
    const asset = m.assets[platform];
    exactKeys(asset, ['url', 'sha256', 'size']);
    const expected = `https://github.com/computerlovetech/umbod/releases/download/${m.tag}/${info.file(m.version)}`;
    if (asset.url !== expected || typeof asset.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(asset.sha256) || !Number.isSafeInteger(asset.size) || asset.size <= 0) throw Error('Invalid desktop asset');
  }
  return m;
}
export function detectPlatform(hints = {}, userAgent = '') {
  if (hints.mobile || /Android|iPhone|iPad|iPod/i.test(userAgent)) return 'unsupported';
  const os = (hints.platform || '').toLowerCase();
  if (os === 'macos' && hints.architecture) return hints.architecture === 'arm' && hints.bitness === '64' ? 'macos-arm64' : 'unsupported';
  if (os === 'windows' && hints.architecture) return hints.architecture === 'x86' && hints.bitness === '64' ? 'windows-x64' : 'unsupported';
  if (/Windows.*ARM/i.test(userAgent)) return 'unsupported';
  if (/Windows.*(Win64|WOW64|x64)/i.test(userAgent)) return 'windows-x64';
  if (os === 'macos' || /Macintosh|MacIntel/i.test(userAgent)) return 'macos-unknown';
  if (os === 'windows') return 'unknown';
  if (/Linux|CrOS|Windows/i.test(userAgent) || ['android', 'ios', 'linux', 'chrome os'].includes(os)) return 'unsupported';
  return 'unknown';
}
export function selectDownload(manifest, platform) {
  try {
    const m = validateManifest(manifest);
    if (m.status !== 'available') return { recommended: null, downloads: [] };
    return { recommended: Object.hasOwn(PLATFORMS, platform) ? platform : null,
      downloads: Object.entries(PLATFORMS).map(([id, info]) => ({id, ...info, ...m.assets[id], version: m.version})) };
  } catch { return { recommended: null, downloads: [] }; }
}
export async function loadManifest(fetcher = globalThis.fetch) {
  try {
    const response = await fetcher('/desktop-downloads.json', { credentials: 'omit', redirect: 'error', cache: 'no-cache', signal: AbortSignal.timeout(5000) });
    if (!response.ok || response.redirected) return null;
    return validateManifest(await response.json());
  } catch { return null; }
}
export function renderDownloads(manifest, platform) {
  const { downloads } = selectDownload(manifest, platform);
  const mac = downloads.find(item => item.id === 'macos-arm64');
  const windows = downloads.find(item => item.id === 'windows-x64');
  let state = 'Release pending';
  try { if (validateManifest(manifest).status !== 'unavailable') state = 'Temporarily unavailable'; } catch { state = 'Temporarily unavailable'; }
  const macRow = mac
    ? `<a class="platform-row platform-ready" href="${mac.url}"><span><strong>macOS</strong><small>Apple Silicon · macOS 14 or later</small></span><span class="platform-action">Download DMG <span aria-hidden="true">↓</span></span></a>`
    : `<div class="platform-row"><span><strong>macOS</strong><small>Apple Silicon · macOS 14 or later</small></span><span class="platform-status">${state}</span></div>`;
  const windowsRow = windows
    ? `<a class="platform-row platform-ready" href="${windows.url}"><span><strong>Windows</strong><small>x64 · Windows 10/11</small></span><span class="platform-action">Download ZIP <span aria-hidden="true">↓</span></span></a>`
    : `<div class="platform-row"><span><strong>Windows</strong><small>x64 · Windows 10/11</small></span><span class="platform-status">${state}</span></div>`;
  const upcoming = [['macOS Intel', 'Intel-based Macs'], ['Linux', 'Linux desktops']];
  const grid = '<div class="platform-grid">' + macRow + windowsRow + upcoming.map(([name, detail]) => `<div class="platform-row platform-upcoming"><span><strong>${name}</strong><small>${detail}</small></span><span class="platform-status">Coming soon</span></div>`).join('') + '</div>';
  const guidance = platform === 'unsupported' || platform === 'macos-unknown'
    ? '<p class="download-note">The Mac build requires an Apple M-series chip. Windows requires an x64 processor. Intel Mac and Linux builds are coming soon.</p>' : '';
  if (!mac) return grid + `<p class="download-note">${state === 'Release pending' ? 'Desktop downloads are not available yet. They will appear here after the GitHub release is published and verified.' : 'Desktop downloads could not be verified. Please try again later.'}</p>` + guidance;
  return grid + `<div class="download-release"><p>Unsigned prerelease · ${mac.version}. Mac: ad-hoc signed, not notarized. Windows: unsigned. Your operating system may require approval to open the app. Do not disable system security.</p><details><summary>Verify Mac download · SHA-256</summary><code>${mac.sha256}</code></details><details><summary>Verify Windows download · SHA-256</summary><code>${windows.sha256}</code></details></div>` + guidance;
}
export async function initializeDownloads(doc = document, nav = navigator) {
  const container = doc.getElementById('desktop-download-options');
  if (!container) return;
  let hints = nav.userAgentData || {};
  try {
    if (hints.getHighEntropyValues) hints = await Promise.race([
      hints.getHighEntropyValues(['platform', 'architecture', 'bitness', 'mobile']),
      new Promise(resolve => setTimeout(() => resolve({}), 1000)),
    ]);
  } catch { hints = {}; }
  // iPadOS can expose a Mac UA; do not recommend a Mac binary for a touch tablet.
  if (nav.maxTouchPoints > 1 && /Macintosh/i.test(nav.userAgent)) hints = {mobile: true};
  const platform = detectPlatform(hints, nav.userAgent);
  const manifest = await loadManifest();
  container.innerHTML = renderDownloads(manifest, platform);
  const selection = selectDownload(manifest, platform);
  if (selection.downloads.length) {
    for (const cta of doc.querySelectorAll('[data-desktop-cta]')) {
      cta.textContent = selection.recommended ? `Download for ${PLATFORMS[selection.recommended].label}` : 'Download desktop';
    }
  }
}

export function renderDesktopPage(html, manifest) {
  validateManifest(manifest);
  const start = '<!-- desktop-downloads:start -->';
  const end = '<!-- desktop-downloads:end -->';
  if (!html.includes(start) || !html.includes(end)) throw Error('Missing desktop HTML boundaries');
  return html.slice(0, html.indexOf(start) + start.length) + renderDownloads(manifest, 'unknown') + html.slice(html.indexOf(end));
}
