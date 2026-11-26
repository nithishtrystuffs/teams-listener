const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { loadUiState, saveUiState, pillPosition } = require('../src/ui-state');

function tmp() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'tl-ui-')), 'ui-state.json');
}

test('round-trip', () => {
  const f = tmp();
  saveUiState(f, { pill: { x: 10, y: 20 } });
  assert.deepStrictEqual(loadUiState(f), { pill: { x: 10, y: 20 } });
});

test('missing file gives defaults', () => {
  assert.deepStrictEqual(loadUiState(tmp()), { pill: null });
});

test('corrupt json gives defaults', () => {
  const f = tmp();
  fs.writeFileSync(f, '{not json');
  assert.deepStrictEqual(loadUiState(f), { pill: null });
});

test('invalid pill shape gives defaults', () => {
  const f = tmp();
  fs.writeFileSync(f, JSON.stringify({ pill: { x: 'a', y: 2 } }));
  assert.deepStrictEqual(loadUiState(f), { pill: null });
});

const size = { width: 340, height: 44 };
const primary = { x: 0, y: 0, width: 1920, height: 1040 };
const displays = [primary, { x: 1920, y: 0, width: 1280, height: 1024 }];

test('pillPosition default is top-centre of primary', () => {
  assert.deepStrictEqual(pillPosition(null, displays, primary, size), { x: 790, y: 22 });
});

test('pillPosition keeps a visible saved position', () => {
  assert.deepStrictEqual(pillPosition({ x: 2000, y: 100 }, displays, primary, size), { x: 2000, y: 100 });
});

test('pillPosition falls back when off every display', () => {
  assert.deepStrictEqual(pillPosition({ x: 5000, y: 100 }, displays, primary, size), { x: 790, y: 22 });
  assert.deepStrictEqual(pillPosition({ x: -900, y: -900 }, displays, primary, size), { x: 790, y: 22 });
});

test('pillPosition respects primary work-area origin', () => {
  const p = { x: 100, y: 50, width: 1000, height: 700 };
  assert.deepStrictEqual(pillPosition(null, [p], p, size), { x: 430, y: 72 });
});
