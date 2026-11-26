const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const { resolveEngine, resolveAudio, isInside } = require('../src/paths');

test('resolveEngine packaged', () => {
  const r = resolveEngine({ isPackaged: true, resourcesPath: 'C:\\app\\resources', repoRoot: 'x' });
  assert.strictEqual(r.command, path.join('C:\\app\\resources', 'engine', 'teams-listener-engine.exe'));
  assert.deepStrictEqual(r.args, []);
});

test('resolveEngine development', () => {
  const r = resolveEngine({ isPackaged: false, resourcesPath: 'r', repoRoot: 'D:\\repo' });
  assert.strictEqual(r.command, path.join('D:\\repo', '.venv', 'Scripts', 'python.exe'));
  assert.deepStrictEqual(r.args, ['-m', 'teams_listener']);
});

const out = path.resolve('C:\\data\\meetings');

test('resolveAudio accepts valid url', () => {
  const p = resolveAudio(out, 'app-audio://meeting/2026-11-25_1000_Design-review/me.flac');
  assert.strictEqual(p, path.join(out, '2026-11-25_1000_Design-review', 'me.flac'));
});

test('resolveAudio decodes encoded names', () => {
  const p = resolveAudio(out, 'app-audio://meeting/' + encodeURIComponent('Q&A caf\u00e9') + '/others.flac');
  assert.strictEqual(p, path.join(out, 'Q&A caf\u00e9', 'others.flac'));
});

test('resolveAudio rejects bad input', () => {
  assert.strictEqual(resolveAudio(out, 'app-audio://meeting/..%2F..%2FWindows/me.flac'), null);
  assert.strictEqual(resolveAudio(out, 'app-audio://meeting/a%5Cb/me.flac'), null);
  assert.strictEqual(resolveAudio(out, 'app-audio://meeting/../me.flac'), null);
  assert.strictEqual(resolveAudio(out, 'app-audio://meeting/x/other.flac'), null);
  assert.strictEqual(resolveAudio(out, 'app-audio://evil/x/me.flac'), null);
  assert.strictEqual(resolveAudio(out, 'app-audio://meeting//me.flac'), null);
  assert.strictEqual(resolveAudio(out, 'app-audio://meeting/%E0%A4%A/me.flac'), null);
  assert.strictEqual(resolveAudio(out, 'garbage'), null);
  assert.strictEqual(resolveAudio('', 'app-audio://meeting/x/me.flac'), null);
});

test('isInside', () => {
  assert.ok(isInside(out, path.join(out, 'a')));
  assert.ok(!isInside(out, out));
  assert.ok(!isInside(out, out + '2'));
  assert.ok(!isInside(out, path.join(out, '..', 'x')));
  assert.ok(!isInside('', path.join(out, 'a')));
});
