const fs = require('node:fs');
const path = require('node:path');

function resolveEngine({ isPackaged, resourcesPath, repoRoot }) {
  if (isPackaged) {
    return { command: path.join(resourcesPath, 'engine', 'teams-listener-engine.exe'), args: [] };
  }
  return { command: path.join(repoRoot, '.venv', 'Scripts', 'python.exe'), args: ['-m', 'teams_listener'] };
}

// Windows paths compare case-insensitively.
const pathKey = (p) => (process.platform === 'win32' ? path.resolve(p).toLowerCase() : path.resolve(p));

// True when p is strictly inside dir (not equal to it). Works for a drive root such as D:\.
function isInside(dir, p) {
  if (!dir || !p) return false;
  const rel = path.relative(pathKey(dir), pathKey(p));
  return !!rel && rel !== '..' && !rel.startsWith('..' + path.sep) && !path.isAbsolute(rel);
}

// The real path of a directory (junctions and symlinks resolved, as the engine's Path.resolve does),
// or path.resolve(p) when it can't be resolved (e.g. it doesn't exist yet).
function realDir(p, realpath = fs.realpathSync.native) {
  if (!p) return '';
  try {
    return realpath(p);
  } catch {
    return path.resolve(p);
  }
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
    if (!isInside(outputDir, result)) return null;
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

module.exports = { resolveEngine, resolveAudio, isInside, isOpenableFolder, realDir };
