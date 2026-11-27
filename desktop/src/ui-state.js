const fs = require('node:fs');

const DEFAULTS = () => ({ pill: null });
const finite = (n) => typeof n === 'number' && Number.isFinite(n);

function loadUiState(file) {
  try {
    const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
    const p = raw && raw.pill;
    if (p && finite(p.x) && finite(p.y)) return { pill: { x: Math.round(p.x), y: Math.round(p.y) } };
  } catch {
    // missing or corrupt: fall through to defaults
  }
  return DEFAULTS();
}

function saveUiState(file, state) {
  try {
    fs.writeFileSync(file, JSON.stringify({ pill: state && state.pill ? state.pill : null }), 'utf8');
  } catch (err) {
    console.error('ui-state save failed:', err.message);
  }
}

// Saved pill position if it is still on a display, else top-centre of the primary work area.
function pillPosition(saved, displays, primaryWorkArea, size) {
  if (saved && finite(saved.x) && finite(saved.y)) {
    const cx = saved.x + size.width / 2;
    const cy = saved.y + size.height / 2;
    const on = displays.some((d) => cx >= d.x && cx < d.x + d.width && cy >= d.y && cy < d.y + d.height);
    if (on) return { x: saved.x, y: saved.y };
  }
  const w = primaryWorkArea;
  return { x: Math.round(w.x + (w.width - size.width) / 2), y: w.y + 22 };
}

module.exports = { loadUiState, saveUiState, pillPosition };
