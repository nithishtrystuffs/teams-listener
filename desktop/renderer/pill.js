'use strict';
// Floating pill. Renders only what the engine's state/levels events report; the Muted/Live button asks
// the engine to toggle and waits for the next state event. The timer is display-only between events.
(() => {
  const api = window.api;
  const $ = (id) => document.getElementById(id);
  const BARS = 8;
  let st = null; // last state
  let base = 0; // performance.now() at elapsed 0
  let levels = { others: 0, me: 0 };

  $('pmini').innerHTML = '<i></i>'.repeat(BARS);

  function fmt(s) {
    s = Math.max(0, Math.floor(s));
    const h = Math.floor(s / 3600);
    const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
    const sec = String(s % 60).padStart(2, '0');
    return h ? `${h}:${m}:${sec}` : `${m}:${sec}`;
  }

  function render() {
    const rec = !!(st && st.recording);
    const nomic = !!(st && st.nomic);
    const btn = $('pmute');
    btn.classList.toggle('off', rec && !nomic && !!st.muted);
    btn.classList.toggle('on', rec && !nomic && !st.muted);
    btn.classList.toggle('nomic', nomic);
    btn.disabled = !rec || nomic;
    $('plabel').textContent = nomic ? 'No mic' : (rec && !st.muted ? 'Live' : 'Muted');
    tick();
  }

  function tick() {
    $('ptime').textContent = fmt(st && st.recording ? (performance.now() - base) / 1000 : 0);
  }

  function meters() {
    const t = Date.now() / 1000;
    const amp = st && st.recording ? Math.min(1, Math.max(levels.others || 0, levels.me || 0) * 3) : 0;
    [...$('pmini').children].forEach((b, i) => {
      const wave = 0.55 + 0.45 * Math.abs(Math.sin(t * 3 + i * 0.9));
      b.style.height = Math.max(20, Math.min(100, amp * 100 * wave * (0.75 + 0.5 * Math.random()))) + '%';
    });
  }

  api.on('state', (d) => {
    if (!d || typeof d !== 'object') return;
    st = d;
    base = performance.now() - (d.elapsed_s || 0) * 1000;
    render();
  });
  api.on('levels', (d) => {
    levels = d || { others: 0, me: 0 };
    meters();
  });

  $('pmute').addEventListener('click', () => { api.call('toggle_mute').catch(() => {}); });
  $('prestore').addEventListener('click', () => { api.ui('restore').catch(() => {}); });
  $('pstop').addEventListener('click', () => { api.ui('pillStop').catch(() => {}); });

  setInterval(tick, 250);
  render();
  api.call('status').then((d) => { if (d) { st = d; base = performance.now() - (d.elapsed_s || 0) * 1000; render(); } }).catch(() => {});
})();
