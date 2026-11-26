const { app, BrowserWindow, ipcMain, protocol, clipboard, dialog, shell, nativeTheme, screen, Tray, Menu, nativeImage } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { Readable } = require('node:stream');
const { EngineClient } = require('./engine');
const { resolveEngine, resolveAudio, isOpenableFolder } = require('./paths');
const { trayModel, stateAfterEngineEvent } = require('./tray');
const { loadUiState, saveUiState, pillPosition } = require('./ui-state');

const RENDERER_ALLOW = new Set([
  'status', 'start', 'stop', 'set_muted', 'toggle_mute', 'list_meetings', 'get_meeting',
  'search', 'transcribe_again', 'get_settings', 'save_settings', 'list_mics',
]);

const repoRoot = path.resolve(__dirname, '..', '..');
let mainWindow = null;
let engine = null;
let outputDir = '';
let pillWindow = null;
let tray = null;
let lastState = null; // last engine `state` forwarded to the windows
let isQuitting = false;
let uiState = { pill: null };
const PILL_SIZE = { width: 340, height: 44 };

protocol.registerSchemesAsPrivileged([
  { scheme: 'app-audio', privileges: { stream: true, supportFetchAPI: true } },
]);

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => showMain());
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

// Title bar overlay (native caption buttons) colours, matched to the renderer theme.
function overlayColors() {
  return nativeTheme.shouldUseDarkColors
    ? { color: '#00000000', symbolColor: '#ececf1', height: 38 }
    : { color: '#00000000', symbolColor: '#16181d', height: 38 };
}

const isRecording = () => !!(lastState && lastState.recording);
const mainAlive = () => !!(mainWindow && !mainWindow.isDestroyed());
const pillAlive = () => !!(pillWindow && !pillWindow.isDestroyed());

function showPill() {
  if (pillAlive()) pillWindow.showInactive();
}

function hidePill() {
  if (pillAlive()) pillWindow.hide();
}

function showMain() {
  if (mainAlive()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
  hidePill();
}

function hideMainToPill() {
  if (mainAlive()) mainWindow.hide();
  showPill();
}

function sendUi(name, data) {
  if (mainAlive()) mainWindow.webContents.send('ui:event', name, data);
}

// Stop goes through the main window so it shows Transcribing at once; direct if the window is gone.
function requestStop() {
  if (mainAlive() && !mainWindow.webContents.isCrashed()) sendUi('requestStop');
  else if (engine) engine.call('stop').catch((err) => console.error('stop failed:', err.message));
}

function requestStart() {
  if (mainAlive() && !mainWindow.webContents.isCrashed()) sendUi('requestStart');
  else if (engine) engine.call('start', { title: '' }).catch((err) => console.error('start failed:', err.message));
}

function toggleMute() {
  if (engine) engine.call('toggle_mute').catch((err) => console.error('toggle_mute failed:', err.message));
}

const uiStateFile = () => path.join(app.getPath('userData'), 'ui-state.json');

function createPill() {
  uiState = loadUiState(uiStateFile());
  const displays = screen.getAllDisplays().map((d) => d.workArea);
  const pos = pillPosition(uiState.pill, displays, screen.getPrimaryDisplay().workArea, PILL_SIZE);
  pillWindow = new BrowserWindow({
    ...PILL_SIZE,
    x: pos.x,
    y: pos.y,
    useContentSize: true,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  pillWindow.setAlwaysOnTop(true, 'floating');
  let saveTimer = null;
  pillWindow.on('moved', () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      if (!pillAlive()) return;
      const [x, y] = pillWindow.getPosition();
      uiState = { ...uiState, pill: { x, y } };
      saveUiState(uiStateFile(), uiState);
    }, 300);
  });
  pillWindow.on('closed', () => { pillWindow = null; });
  pillWindow.loadFile(path.join(__dirname, '..', 'renderer', 'pill.html'));
}

function trayIcon(colour) {
  return nativeImage.createFromPath(path.join(__dirname, '..', 'assets', `tray-${colour}.png`));
}

const TRAY_ACTIONS = {
  show: () => showMain(),
  startStop: () => (isRecording() ? requestStop() : requestStart()),
  mute: () => toggleMute(),
  quit: () => quitFromTray(),
};

function updateTray() {
  if (!tray) return;
  const m = trayModel(lastState);
  tray.setImage(trayIcon(m.colour));
  tray.setToolTip(m.tooltip);
  tray.setContextMenu(Menu.buildFromTemplate(m.items.map((it) => ({
    label: it.label,
    enabled: it.enabled,
    click: TRAY_ACTIONS[it.id],
  }))));
}

function createTray() {
  tray = new Tray(trayIcon('idle'));
  tray.on('click', () => showMain());
  updateTray();
}

function onState(data) {
  const wasRec = isRecording();
  lastState = data;
  updateTray();
  const nowRec = isRecording();
  if (!nowRec) hidePill();
  else if (!wasRec && !(mainAlive() && mainWindow.isVisible() && !mainWindow.isMinimized())) showPill();
}

async function confirm(message, buttons, defaultId, cancelId, detail) {
  const opts = { type: 'question', buttons, defaultId, cancelId, message, detail, noLink: true };
  const parent = mainAlive() && mainWindow.isVisible() ? mainWindow : null;
  const r = parent ? await dialog.showMessageBox(parent, opts) : await dialog.showMessageBox(opts);
  return r.response;
}

let closeDialogOpen = false;
async function onMainClose(e) {
  if (isQuitting) return;
  e.preventDefault();
  if (!isRecording()) {
    mainWindow.hide();
    return;
  }
  if (closeDialogOpen) return;
  closeDialogOpen = true;
  try {
    const r = await confirm('A meeting is being recorded.',
      ['Stop and save', 'Keep recording in the tray', 'Cancel'], 1, 2, 'Stop recording and save it?');
    if (r === 0) {
      requestStop();
      if (mainAlive()) mainWindow.hide();
    } else if (r === 1) {
      if (isRecording()) hideMainToPill(); // the recording may have ended while the dialog was open
      else if (mainAlive()) mainWindow.hide();
    }
  } finally {
    closeDialogOpen = false;
  }
}

async function queueBusy() {
  try {
    const list = await engine.call('list_meetings');
    return Array.isArray(list) && list.some((m) => m.status === 'queued' || m.status === 'transcribing');
  } catch {
    return false;
  }
}

const withTimeout = (p, ms) => Promise.race([p.catch(() => {}), new Promise((r) => setTimeout(r, ms))]);

let quitInProgress = false;
async function quitFromTray() {
  if (quitInProgress) return;
  quitInProgress = true;
  try {
    if (isRecording()) {
      if (await confirm('Stop the recording, save it and quit?', ['Stop and quit', 'Cancel'], 0, 1) !== 0) {
        quitInProgress = false;
        return;
      }
      // Stopping queues the meeting; the engine's quit stops it. Ask about the queue afterwards.
      try { await engine.call('stop'); } catch (err) { console.error('stop before quit failed:', err.message); }
    }
    if (await queueBusy()) {
      if (await confirm('A transcription is still running. Quit anyway?', ['Quit anyway', 'Cancel'], 1, 1) !== 0) {
        quitInProgress = false;
        return;
      }
    }
    isQuitting = true;
    if (engine) {
      await withTimeout(engine.call('quit'), 5000);
      await withTimeout(engine.stop(), 8000);
    }
    app.exit(0);
  } catch (err) {
    console.error('quit failed:', err);
    quitInProgress = false;
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    show: true,
    title: 'Teams Listener',
    titleBarStyle: 'hidden',
    titleBarOverlay: overlayColors(),
    backgroundMaterial: 'mica',
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  mainWindow.on('close', onMainClose);
  // Windows shutdown/logoff: never block it with the close dialog; stop the engine so audio is saved.
  const onSessionEnd = () => {
    isQuitting = true;
    if (engine) engine.stop().catch(() => {});
  };
  mainWindow.on('session-end', onSessionEnd);
  mainWindow.on('minimize', () => {
    if (isRecording()) hideMainToPill(); // while recording, minimise means "to the pill"
  });
  const query = {};
  if (process.env.TL_SMOKE_OPEN) query.smokeOpen = '1';
  if (process.env.TL_SMOKE_IDLE) query.smokeIdle = '1';
  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'), { query });
}

nativeTheme.on('updated', () => {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.setTitleBarOverlay(overlayColors());
});

// Smoke mode (TL_SMOKE=<png path>): screenshot once the renderer reports its first render, then quit.
let smokeDone = false;
function smokeExit(code) {
  if (smokeDone) return;
  smokeDone = true;
  const stopped = engine ? engine.stop().catch(() => {}) : Promise.resolve();
  const timeout = new Promise((r) => setTimeout(r, 6000));
  Promise.race([stopped, timeout]).finally(() => app.exit(code));
}

async function smokeCapture() {
  if (!process.env.TL_SMOKE || !mainWindow) return;
  await new Promise((r) => setTimeout(r, 300));
  try {
    const img = await mainWindow.webContents.capturePage();
    await fs.promises.writeFile(process.env.TL_SMOKE, img.toPNG());
    console.log('smoke screenshot written:', process.env.TL_SMOKE);
    smokeExit(0);
  } catch (err) {
    console.error('smoke capture failed:', err);
    smokeExit(1);
  }
}

// Dev-only (TL_SMOKE_PILL=<png>): show the pill with a fake state pushed to it alone, capture it, exit.
async function smokePill(file) {
  await new Promise((r) => pillWindow.webContents.once('did-finish-load', r));
  await new Promise((r) => setTimeout(r, 800));
  pillWindow.webContents.send('engine:event', 'state', { recording: true, muted: true, elapsed_s: 763 });
  showPill();
  await new Promise((r) => setTimeout(r, 500));
  try {
    const img = await pillWindow.webContents.capturePage();
    await fs.promises.writeFile(file, img.toPNG());
    console.log('smoke pill written:', file);
    smokeExit(0);
  } catch (err) {
    console.error('smoke pill failed:', err);
    smokeExit(1);
  }
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
    if (name === 'state') onState(data);
    broadcast(name, data);
  });
  engine.on('ready', () => {
    console.log('engine ready');
    refreshOutputDir();
    // A (re)started engine emits no state until something changes, so resync every surface.
    engine.call('status').then((st) => {
      if (st && typeof st === 'object') {
        onState(st);
        broadcast('state', st);
      }
    }).catch((err) => console.error('status after ready failed:', err.message));
  });
  engine.on('failed', (info) => {
    console.error('engine failed:', info);
    onState(stateAfterEngineEvent('failed', lastState));
    broadcast('engine_failed', info);
  });
  engine.on('exit', (code) => {
    console.error('engine exit:', code);
    onState(stateAfterEngineEvent('exit', lastState));
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
      case 'smokeReady':
        smokeCapture();
        return null;
      case 'minimiseToPill':
        if (isRecording()) hideMainToPill();
        else if (mainAlive()) mainWindow.minimize();
        return null;
      case 'restore':
        showMain();
        return null;
      case 'pillStop':
        requestStop();
        showMain();
        return null;
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
  // Dev-only theme override until Settings > Theme exists (Task 9).
  if (['light', 'dark', 'system'].includes(process.env.TL_THEME)) nativeTheme.themeSource = process.env.TL_THEME;
  if (process.env.TL_SMOKE) {
    setTimeout(() => {
      console.error('smoke: renderer never signalled smokeReady');
      smokeExit(1);
    }, 20000).unref();
  }
  registerIpc();
  startEngine();
  createWindow();
  createPill();
  createTray();
  if (process.env.TL_SMOKE_PILL) smokePill(process.env.TL_SMOKE_PILL);
  app.on('window-all-closed', () => app.quit());
  let stopped = false;
  app.on('before-quit', (e) => {
    isQuitting = true;
    if (stopped || !engine) return;
    e.preventDefault();
    stopped = true;
    engine.stop().finally(() => app.quit());
  });
}
