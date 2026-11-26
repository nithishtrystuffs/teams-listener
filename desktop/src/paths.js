const path = require('node:path');

function resolveEngine({ isPackaged, resourcesPath, repoRoot }) {
  if (isPackaged) {
    return { command: path.join(resourcesPath, 'engine', 'teams-listener-engine.exe'), args: [] };
  }
  return { command: path.join(repoRoot, '.venv', 'Scripts', 'python.exe'), args: ['-m', 'teams_listener'] };
}

// True when p is strictly inside dir (not equal to it).
function isInside(dir, p) {
  if (!dir || !p) return false;
  const base = path.resolve(dir);
  const target = path.resolve(p);
  return target.startsWith(base + path.sep);
}

function resolveAudio(outputDir, url) {
  try {
    if (!outputDir) return null;
    const u = new URL(url);
    if (u.protocol !== 'app-audio:' || u.hostname !== 'meeting') return null;
    const parts = u.pathname.split('/').filter((s, i) => i > 0 || s !== '');
    if (parts.length !== 2) return null;
    const name = decodeURIComponent(parts[0]);
    const file = parts[1];
    if (file !== 'others.flac' && file !== 'me.flac') return null;
    if (!name || name.includes('/') || name.includes('\\') || name.includes('..')) return null;
    const result = path.join(outputDir, name, file);
    if (!path.resolve(result).startsWith(path.resolve(outputDir) + path.sep)) return null;
    return result;
  } catch {
    return null;
  }
}

// Resolved path if p is an existing directory strictly inside outputDir, else null.
async function isOpenableFolder(outputDir, p, statFn) {
  try {
    if (typeof p !== 'string' || !isInside(outputDir, p)) return null;
    const resolved = path.resolve(p);
    const st = await statFn(resolved);
    return st.isDirectory() ? resolved : null;
  } catch {
    return null;
  }
}

module.exports = { resolveEngine, resolveAudio, isInside, isOpenableFolder };
