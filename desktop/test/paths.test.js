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

test('isOpenableFolder', async () => {
  const { isOpenableFolder } = require('../src/paths');
  const stat = async (p) => ({ isDirectory: () => !p.endsWith('.exe') });
  assert.strictEqual(await isOpenableFolder(out, path.join(out, 'a'), stat), path.join(out, 'a'));
  assert.strictEqual(await isOpenableFolder(out, path.join(out, 'a', 'x.exe'), stat), null);
  assert.strictEqual(await isOpenableFolder(out, 'C:\Windows', stat), null);
  const missing = async () => { throw new Error('ENOENT'); };
  assert.strictEqual(await isOpenableFolder(out, path.join(out, 'a'), missing), null);
});

test('isInside: case-insensitive on Windows', () => {
  assert.ok(isInside('C:\\Data\\Out', 'c:\\data\\out\\m'));
  assert.ok(isInside('c:\\data\\out\\', 'C:\\Data\\Out\\m'));
});

test('isInside: drive root output folder', () => {
  assert.ok(isInside('D:\\', 'D:\\m'));
  assert.ok(isInside('D:\\', 'd:\\m\\x'));
  assert.ok(!isInside('D:\\', 'D:\\'));
  assert.ok(!isInside('D:\\', 'E:\\m'));
});

test('isInside: sibling prefix, equal path and other drive are not inside', () => {
  assert.ok(!isInside('C:\\out', 'C:\\out2'));
  assert.ok(!isInside('C:\\out', 'C:\\out2\\m'));
  assert.ok(!isInside('C:\\out', 'C:\\out'));
  assert.ok(!isInside('C:\\out', 'c:\\OUT\\'));
  assert.ok(!isInside('C:\\out', 'D:\\out\\m'));
});

test('resolveAudio: drive root and case-different output folder', () => {
  assert.strictEqual(resolveAudio('D:\\', 'app-audio://meeting/m1/me.flac'), path.join('D:\\', 'm1', 'me.flac'));
  assert.strictEqual(resolveAudio('c:\\DATA\\out', 'app-audio://meeting/m1/others.flac'),
    path.join('c:\\DATA\\out', 'm1', 'others.flac'));
});

test('realDir resolves links and falls back to path.resolve', () => {
  const { realDir } = require('../src/paths');
  assert.strictEqual(realDir('C:\\link', () => 'D:\\real'), 'D:\\real');
  assert.strictEqual(realDir('C:\\x\\..\\gone', () => { throw new Error('ENOENT'); }), path.resolve('C:\\gone'));
  assert.strictEqual(realDir('', () => 'x'), '');
});
