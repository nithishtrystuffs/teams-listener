const { EventEmitter } = require('node:events');

const MAX_CRASHES = 5;
const CRASH_WINDOW_MS = 60000;
const STOP_TIMEOUT_MS = 5000;
const CALL_TIMEOUT_MS = 30000;
const LONG_CALL_TIMEOUT_MS = 60000;
const LONG_CALLS = new Set(['stop', 'start', 'transcribe_again']); // may wait on devices or disk

class EngineClient extends EventEmitter {
  constructor({
    spawn, command, args = [], env = {}, restartDelayMs = 1000,
    callTimeoutMs = CALL_TIMEOUT_MS, longCallTimeoutMs = LONG_CALL_TIMEOUT_MS,
  }) {
    super();
    this._spawn = spawn;
    this.command = command;
    this.args = args;
    this.env = env;
    this.restartDelayMs = restartDelayMs;
    this.callTimeoutMs = callTimeoutMs;
    this.longCallTimeoutMs = longCallTimeoutMs;
    this._child = null;
    this._nextId = 1;
    this._pending = new Map();
    this._buf = '';
    this._stopping = false;
    this._dead = false; // failed or stopped: no further restarts
    this._crashes = [];
    this._restartTimer = null;
    this._exitWaiters = [];
  }

  start() {
    this._stopping = false;
    this._dead = false;
    this._buf = '';
    let child;
    try {
      child = this._spawn(this.command, this.args, {
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...this.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
      });
    } catch (err) {
      this._fail(err);
      return;
    }
    this._child = child;
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (d) => this._onData(d));
    child.stdout.on('error', () => {});
    child.stderr.on('data', (d) => console.error('[engine]', d.toString().trimEnd()));
    child.stderr.on('error', () => {});
    child.stdin.on('error', () => {});
    child.on('error', (err) => {
      if (this._child !== child) return;
      this._child = null;
      this._rejectAll();
      this._fail(err);
    });
    child.on('exit', (code) => this._onExit(child, code));

    this.call('status').then(() => {
      if (this._child === child) this.emit('ready');
    }).catch(() => {});
  }

  _fail(err) {
    this._dead = true;
    this._resolveExitWaiters();
    this.emit('failed', { command: this.command, message: err && err.message ? err.message : String(err) });
  }

  _onData(chunk) {
    this._buf += chunk;
    let i;
    while ((i = this._buf.indexOf('\n')) >= 0) {
      const line = this._buf.slice(0, i).trim();
      this._buf = this._buf.slice(i + 1);
      if (line) this._onLine(line);
    }
  }

  _onLine(line) {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      console.error('[engine] non-JSON line:', line);
      return;
    }
    if (!msg || typeof msg !== 'object') return;
    if (typeof msg.event === 'string') {
      this.emit('event', msg.event, msg.data);
      return;
    }
    if (msg.id == null) return;
    const p = this._pending.get(msg.id);
    if (!p) return;
    this._pending.delete(msg.id);
    if (msg.ok) p.resolve(msg.result);
    else p.reject(new Error(msg.error || 'engine error'));
  }

  _rejectAll() {
    const pending = [...this._pending.values()];
    this._pending.clear();
    for (const p of pending) p.reject(new Error('engine stopped'));
  }

  _resolveExitWaiters() {
    const w = this._exitWaiters;
    this._exitWaiters = [];
    for (const fn of w) fn();
  }

  _onExit(child, code) {
    if (this._child !== child) return;
    this._child = null;
    this._rejectAll();
    this.emit('exit', code);
    if (this._stopping || this._dead) {
      this._dead = true;
      this._resolveExitWaiters();
      return;
    }
    const now = Date.now();
    this._crashes = this._crashes.filter((t) => now - t < CRASH_WINDOW_MS);
    this._crashes.push(now);
    if (this._crashes.length >= MAX_CRASHES) {
      this._dead = true;
      this.emit('failed', { command: this.command, message: 'engine keeps crashing' });
      return;
    }
    this._restartTimer = setTimeout(() => {
      this._restartTimer = null;
      if (!this._stopping && !this._dead) this.start();
    }, this.restartDelayMs);
  }

  call(cmd, args = {}) {
    if (this._dead || !this._child) return Promise.reject(new Error('engine stopped'));
    const id = this._nextId++;
    return new Promise((resolve, reject) => {
      const ms = LONG_CALLS.has(cmd) ? this.longCallTimeoutMs : this.callTimeoutMs;
      const timer = setTimeout(() => {
        if (this._pending.get(id) !== entry) return;
        this._pending.delete(id);
        reject(new Error(`engine did not reply: ${cmd}`));
      }, ms);
      const entry = {
        resolve: (v) => { clearTimeout(timer); resolve(v); },
        reject: (e) => { clearTimeout(timer); reject(e); },
      };
      this._pending.set(id, entry);
      try {
        this._child.stdin.write(JSON.stringify({ id, cmd, args }) + '\n');
      } catch (err) {
        this._pending.delete(id);
        entry.reject(err);
      }
    });
  }

  stop() {
    this._stopping = true;
    this._dead = true;
    if (this._restartTimer) {
      clearTimeout(this._restartTimer);
      this._restartTimer = null;
    }
    const child = this._child;
    if (!child) {
      this._rejectAll();
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      let timer;
      const done = () => {
        clearTimeout(timer);
        resolve();
      };
      this._exitWaiters.push(done);
      timer = setTimeout(() => {
        try { child.kill(); } catch { /* ignore */ }
      }, STOP_TIMEOUT_MS);
      try { child.stdin.end(); } catch { /* ignore */ }
    });
  }
}

module.exports = { EngineClient };
