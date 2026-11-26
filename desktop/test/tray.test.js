const test = require('node:test');
const assert = require('node:assert');
const { trayModel } = require('../src/tray');

const item = (m, id) => m.items.find((i) => i.id === id);

test('idle', () => {
  const m = trayModel(null);
  assert.strictEqual(m.colour, 'idle');
  assert.strictEqual(m.tooltip, 'Teams Listener — idle');
  assert.strictEqual(item(m, 'startStop').label, 'Start recording');
  assert.strictEqual(item(m, 'mute').enabled, false);
  assert.strictEqual(item(m, 'mute').label, 'Mute mic');
  assert.deepStrictEqual(m.items.map((i) => i.id), ['show', 'startStop', 'mute', 'quit']);
  assert.strictEqual(trayModel({ recording: false }).colour, 'idle');
});

test('muted', () => {
  const m = trayModel({ recording: true, muted: true });
  assert.strictEqual(m.colour, 'muted');
  assert.strictEqual(m.tooltip, 'Teams Listener — recording, mic MUTED');
  assert.strictEqual(item(m, 'startStop').label, 'Stop recording');
  assert.strictEqual(item(m, 'mute').label, 'Unmute mic');
  assert.strictEqual(item(m, 'mute').enabled, true);
});

test('live', () => {
  const m = trayModel({ recording: true, muted: false });
  assert.strictEqual(m.colour, 'live');
  assert.strictEqual(m.tooltip, 'Teams Listener — recording, mic LIVE');
  assert.strictEqual(item(m, 'mute').label, 'Mute mic');
});

test('nomic', () => {
  const m = trayModel({ recording: true, muted: true, nomic: true });
  assert.strictEqual(m.colour, 'nomic');
  assert.strictEqual(m.tooltip, 'Teams Listener — recording Others only (no mic)');
});

test('show and quit always enabled', () => {
  const m = trayModel(null);
  assert.strictEqual(item(m, 'show').enabled, true);
  assert.strictEqual(item(m, 'quit').enabled, true);
});

const { stateAfterEngineEvent } = require('../src/tray');

test('engine exit or failure means not recording', () => {
  const rec = { recording: true, muted: false, title: 'x', elapsed_s: 5 };
  for (const ev of ['exit', 'failed']) {
    const s = stateAfterEngineEvent(ev, rec);
    assert.strictEqual(s.recording, false);
    assert.strictEqual(trayModel(s).colour, 'idle');
  }
});

test('other engine events leave state alone', () => {
  const rec = { recording: true, muted: true };
  assert.strictEqual(stateAfterEngineEvent('ready', rec), rec);
  assert.strictEqual(stateAfterEngineEvent('exit', null).recording, false);
});

test('stateAfterEngineEvent marks a reset seq so the next engine is not ignored', () => {
  const { stateAfterEngineEvent } = require('../src/tray');
  assert.strictEqual(stateAfterEngineEvent('exit', { seq: 12 }).seq, -1);
  assert.strictEqual(stateAfterEngineEvent('failed', { seq: 12 }).seq, -1);
});
