const { app, BrowserWindow, ipcMain, protocol, clipboard, dialog, shell } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { Readable } = require('node:stream');
const { EngineClient } = require('./engine');
const { resolveEngine, resolveAudio, isOpenableFolder } = require('./paths');

const RENDERER_ALLOW = new Set([
  'status', 'start', 'stop', 'set_muted', 'toggle_mute', 'list_meetings', 'get_meeting',
  'search', 'transcribe_again', 'get_settings', 'save_settings', 'list_mics',
]);

const repoRoot = path.resolve(__dirname, '..', '..');
let mainWindow = null;
let engine = null;
let outputDir = '';

protocol.registerSchemesAsPrivileged([
  { scheme: 'app-audio', privileges: { stream: true, supportFetchAPI: true } },
]);

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
  app.whenReady().then(boot);
}

function broadcast(name, data) {
  for (const w of BrowserWindow.getAllWindows()) {
    if (!w.isDestroyed()) w.webContents.send('engine:event', name, data);
  }
}

async function refreshOutputDir() {
  try {
    const s = await engine.call('get_settings');
    if (s && typeof s.output_dir === 'string') outputDir = s.output_dir;
  } catch (err) {
    console.error('get_settings failed:', err.message);
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 760,
    show: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
}

function startEngine() {
  const { command, args } = resolveEngine({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    repoRoot,
  });
  // In development the engine runs with cwd = repo root so `-m teams_listener` resolves.
  const spawnEngine = app.isPackaged ? spawn : (c, a, o) => spawn(c, a, { ...o, cwd: repoRoot });
  engine = new EngineClient({ spawn: spawnEngine, command, args, env: { ...process.env } });
  engine.on('event', (name, data) => {
    if (name === 'meetings_changed') refreshOutputDir();
    broadcast(name, data);
  });
  engine.on('ready', () => {
    console.log('engine ready');
    refreshOutputDir();
  });
  engine.on('failed', (info) => {
    console.error('engine failed:', info);
    broadcast('engine_failed', info);
  });
  engine.on('exit', (code) => {
    console.error('engine exit:', code);
    broadcast('engine_exit', { code });
  });
  engine.start();
}

function registerIpc() {
  ipcMain.handle('engine:call', (_e, cmd, args) => {
    if (typeof cmd !== 'string' || !RENDERER_ALLOW.has(cmd)) {
      throw new Error('not allowed: ' + cmd);
    }
    return engine.call(cmd, args && typeof args === 'object' ? args : {});
  });

  ipcMain.handle('ui', async (_e, action, payload) => {
    switch (action) {
      case 'copyText':
        clipboard.writeText(String((payload && payload.text) ?? payload ?? ''));
        return null;
      case 'openFolder': {
        const p = payload && (payload.path || payload.folder);
        const dir = await isOpenableFolder(outputDir, p, fs.promises.stat);
        if (!dir) throw new Error('not a folder');
        const err = await shell.openPath(dir);
        return err || null;
      }
      case 'pickFolder': {
        const r = await dialog.showOpenDialog(mainWindow || undefined, { properties: ['openDirectory'] });
        return r.canceled || !r.filePaths.length ? null : r.filePaths[0];
      }
      case 'exportMarkdown': {
        const folder = payload && payload.folder;
        const dir = await isOpenableFolder(outputDir, folder, fs.promises.stat);
        if (!dir) throw new Error('not a folder');
        const src = path.join(dir, 'transcript.md');
        const r = await dialog.showSaveDialog(mainWindow || undefined, {
          defaultPath: path.basename(dir) + '.md',
          filters: [{ name: 'Markdown', extensions: ['md'] }],
        });
        if (r.canceled || !r.filePath) return null;
        await fs.promises.copyFile(src, r.filePath);
        return r.filePath;
      }
      case 'minimiseToPill':
      case 'restore':
        return null; // Task 8
      default:
        throw new Error('not allowed: ' + action);
    }
  });
}

// net.fetch(file URL) ignores Range, so serve ranges ourselves to keep <audio> seeking working.
async function serveAudio(p, range) {
  let size;
  try {
    size = (await fs.promises.stat(p)).size;
  } catch {
    return new Response('Not found', { status: 404 });
  }
  const base = { 'Content-Type': 'audio/flac', 'Accept-Ranges': 'bytes' };
  const mt = range && /^bytes=(\d*)-(\d*)$/.exec(range.trim());
  if (!mt || (mt[1] === '' && mt[2] === '')) {
    return new Response(Readable.toWeb(fs.createReadStream(p)), { status: 200, headers: { ...base, 'Content-Length': String(size) } });
  }
  let start; let end;
  if (mt[1] === '') { // suffix range
    start = Math.max(0, size - Number(mt[2]));
    end = size - 1;
  } else {
    start = Number(mt[1]);
    end = mt[2] === '' ? size - 1 : Math.min(Number(mt[2]), size - 1);
  }
  if (start >= size || start > end) {
    return new Response('Range not satisfiable', { status: 416, headers: { ...base, 'Content-Range': 'bytes */' + size } });
  }
  return new Response(Readable.toWeb(fs.createReadStream(p, { start, end })), {
    status: 206,
    headers: { ...base, 'Content-Length': String(end - start + 1), 'Content-Range': `bytes ${start}-${end}/${size}` },
  });
}

function boot() {
  protocol.handle('app-audio', async (request) => {
    const p = resolveAudio(outputDir, request.url);
    if (!p) return new Response('Not found', { status: 404 });
    return serveAudio(p, request.headers.get('range'));
  });
  registerIpc();
  startEngine();
  createWindow();
  app.on('window-all-closed', () => app.quit());
  let quitting = false;
  app.on('before-quit', (e) => {
    if (quitting || !engine) return;
    e.preventDefault();
    quitting = true;
    engine.stop().finally(() => app.quit());
  });
}
