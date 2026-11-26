const test = require('node:test');
const assert = require('node:assert');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { EngineClient } = require('../src/engine');

function makeFake() {
  const children = [];
  const spawn = () => {
    const c = new EventEmitter();
    c.stdin = new PassThrough();
    c.stdout = new PassThrough();
    c.stderr = new PassThrough();
    c.killed = false;
    c.kill = () => { c.killed = true; c.emit('exit', null); };
    c.sent = [];
    let buf = '';
    c.stdin.on('data', d => {
      buf += d.toString();
      let i;
      while ((i = buf.indexOf('\n')) >= 0) { c.sent.push(JSON.parse(buf.slice(0, i))); buf = buf.slice(i + 1); }
    });
    c.stdin.on('end', () => setImmediate(() => c.emit('exit', 0)));
    children.push(c);
    return c;
  };
  return { spawn, children };
}
const tick = () => new Promise(r => setImmediate(r));
const mk = (extra = {}) => {
  const f = makeFake();
  const e = new EngineClient({ spawn: f.spawn, command: 'py', args: ['-m', 'x'], env: {}, restartDelayMs: 1, ...extra });
  return { f, e };
};
const reply = (c, obj) => c.stdout.write(JSON.stringify(obj) + '\n');

test('call resolves by id (out of order)', async () => {
  const { f, e } = mk(); e.start();
  const c = f.children[0];
  const a = e.call('a'), b = e.call('b');
  await tick();
  const ids = c.sent.filter(m => m.cmd === 'a' || m.cmd === 'b');
  reply(c, { id: ids[1].id, ok: true, result: 'B' });
  reply(c, { id: ids[0].id, ok: true, result: 'A' });
  assert.strictEqual(await a, 'A');
  assert.strictEqual(await b, 'B');
  await e.stop();
});

test('ok:false rejects', async () => {
  const { f, e } = mk(); e.start();
  const p = e.call('x');
  await tick();
  const m = f.children[0].sent.find(m => m.cmd === 'x');
  reply(f.children[0], { id: m.id, ok: false, error: 'boom' });
  await assert.rejects(p, { message: 'boom' });
  await e.stop();
});

test('events emitted', async () => {
  const { f, e } = mk(); e.start();
  const got = [];
  e.on('event', (n, d) => got.push([n, d]));
  reply(f.children[0], { event: 'state', data: { a: 1 } });
  await tick();
  assert.deepStrictEqual(got, [['state', { a: 1 }]]);
  await e.stop();
});

test('line split across chunks, non-JSON ignored', async () => {
  const { f, e } = mk(); e.start();
  const got = [];
  e.on('event', (n) => got.push(n));
  const c = f.children[0];
  c.stdout.write('not json\n{"event":"lev');
  await tick();
  c.stdout.write('els","data":{}}\n');
  await tick();
  assert.deepStrictEqual(got, ['levels']);
  await e.stop();
});

test('ready after first status reply', async () => {
  const { f, e } = mk();
  let ready = 0; e.on('ready', () => ready++);
  e.start();
  const c = f.children[0];
  await tick();
  const m = c.sent.find(m => m.cmd === 'status');
  assert.ok(m);
  reply(c, { id: m.id, ok: true, result: {} });
  await tick();
  assert.strictEqual(ready, 1);
  await e.stop();
});

test('exit rejects pending and restarts', async () => {
  const { f, e } = mk(); e.start();
  const exits = []; e.on('exit', c => exits.push(c));
  const p = e.call('slow');
  p.catch(() => {});
  await tick();
  f.children[0].emit('exit', 1);
  await assert.rejects(p, { message: 'engine stopped' });
  await new Promise(r => setTimeout(r, 20));
  assert.strictEqual(f.children.length, 2);
  assert.deepStrictEqual(exits, [1]);
  await e.stop();
});

test('stop() does not restart', async () => {
  const { f, e } = mk(); e.start();
  await e.stop();
  await new Promise(r => setTimeout(r, 20));
  assert.strictEqual(f.children.length, 1);
  await assert.rejects(e.call('x'), { message: 'engine stopped' });
});

test('spawn error emits failed, no restart', async () => {
  const { f, e } = mk();
  const failed = []; e.on('failed', x => failed.push(x));
  e.start();
  f.children[0].emit('error', new Error('spawn ENOENT'));
  await new Promise(r => setTimeout(r, 20));
  assert.strictEqual(failed.length, 1);
  assert.strictEqual(failed[0].command, 'py');
  assert.match(failed[0].message, /ENOENT/);
  assert.strictEqual(f.children.length, 1);
  await assert.rejects(e.call('x'), { message: 'engine stopped' });
});

test('crash loop (5 in 60s) emits failed and stops restarting', async () => {
  const { f, e } = mk();
  const failed = []; e.on('failed', x => failed.push(x));
  e.start();
  for (let i = 0; i < 5; i++) {
    f.children[i].emit('exit', 1);
    await new Promise(r => setTimeout(r, 15));
  }
  assert.strictEqual(f.children.length, 5);
  assert.deepStrictEqual(failed, [{ command: 'py', message: 'engine keeps crashing' }]);
});

test('multibyte utf-8 split across chunks is decoded intact', async () => {
  const { f, e } = mk(); e.start();
  const got = [];
  e.on('event', (n) => got.push(n));
  const buf = Buffer.from('{"event":"\u00e9","data":{}}\n');
  const i = buf.indexOf(0xc3) + 1;
  f.children[0].stdout.write(buf.subarray(0, i));
  await tick();
  f.children[0].stdout.write(buf.subarray(i));
  await tick();
  assert.deepStrictEqual(got, ['\u00e9']);
  await e.stop();
});

test('call times out, rejects and forgets the pending call', async () => {
  const { f, e } = mk({ callTimeoutMs: 20, longCallTimeoutMs: 60 });
  e.start();
  const t0 = Date.now();
  await assert.rejects(e.call('get_settings'), { message: 'engine did not reply: get_settings' });
  assert.ok(Date.now() - t0 < 55);
  await new Promise(r => setTimeout(r, 5));
  assert.strictEqual(e._pending.size, 0); // the startup status timed out too
  await e.stop();
});

test('stop, start and transcribe_again get the longer timeout', async () => {
  const { f, e } = mk({ callTimeoutMs: 20, longCallTimeoutMs: 80 });
  e.start();
  const c = f.children[0];
  const p = e.call('stop');
  let settled = false;
  p.catch(() => {}).finally(() => { settled = true; });
  await new Promise(r => setTimeout(r, 40));
  assert.strictEqual(settled, false); // past the short timeout, still waiting
  await assert.rejects(p, { message: 'engine did not reply: stop' });
  const sent = c.sent.find(m => m.cmd === 'stop');
  assert.ok(!e._pending.has(sent.id));
  await e.stop();
});

test('a reply after the timeout is ignored', async () => {
  const { f, e } = mk({ callTimeoutMs: 10 });
  e.start();
  const c = f.children[0];
  const p = e.call('status');
  await assert.rejects(p, /did not reply/);
  const sent = c.sent.filter(m => m.cmd === 'status').pop();
  reply(c, { id: sent.id, ok: true, result: {} }); // late: must not throw
  await tick();
  await e.stop();
});

test('default timeouts are 30 s and 60 s', () => {
  const e = new EngineClient({ spawn: () => {}, command: 'x' });
  assert.strictEqual(e.callTimeoutMs, 30000);
  assert.strictEqual(e.longCallTimeoutMs, 60000);
});

test('engine is spawned detached (outlives an Electron crash) with piped stdio and no window', async () => {
  const seen = [];
  const f = makeFake();
  const spawn = (cmd, args, opts) => { seen.push(opts); return f.spawn(cmd, args, opts); };
  const e = new EngineClient({ spawn, command: 'py', restartDelayMs: 1 });
  e.start();
  assert.strictEqual(seen[0].detached, true);
  assert.strictEqual(seen[0].windowsHide, true);
  assert.deepStrictEqual(seen[0].stdio, ['pipe', 'pipe', 'pipe']);
  await e.stop();
});
