'use strict';
// Main window renderer. Everything shown here is derived from the engine's replies and events; the
// engine is the single source of truth for recording and mute state.
(() => {
  const {
    groupMeetings, fmtClock, fmtEta, escapeHtml, statusDot, timelineSegments, prettyHotkey,
    decideAfterRecordingEnded, transcribingResolved, settingsFromForm, DEFAULT_MIC_LABEL,
  } = window.TL;
  const api = window.api;
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const BARS = 22;
  const MODEL_TEXT = 'Downloading speech model (first time only, ~480 MB)…';

  const store = {
    status: null, // last engine status/state
    lastDevices: null, // {mic, outputs} from the last status seen while recording
    settings: null,
    meetings: [],
    activeFolder: null,
    meeting: null, // get_meeting result for activeFolder
    view: 'idle', // idle | rec | prog | tx
    tab: 'all',
    search: { query: '', counts: new Map() },
    progressByFolder: {},
    liveMoments: [], // [[a, b]] built from mute transitions since the recording started
    liveStart: null,
    clockBase: 0, // performance.now() at elapsed 0 of the current recording
    levels: { others: 0, me: 0 },
    busy: false,
    stopRequested: false, // this UI called stop() and is waiting for the engine to confirm
    endedFolder: null, // recording that ended without our stop(); may still turn out to be queued
  };

  // ---- engine access --------------------------------------------------------
  function errText(err) {
    return String((err && err.message) || err).replace(/^Error invoking remote method '[^']+': (Error: )?/, '');
  }

  // Resolves to the result, or null after showing a toast when the call fails.
  async function call(cmd, args) {
    try {
      return await api.call(cmd, args);
    } catch (err) {
      toast(errText(err), true);
      return null;
    }
  }

  async function ui(action, payload) {
    try {
      return await api.ui(action, payload);
    } catch (err) {
      toast(errText(err), true);
      return null;
    }
  }

  // ---- toasts & banner ------------------------------------------------------
  function toast(msg, isError = false) {
    const el = document.createElement('div');
    el.className = 'toast' + (isError ? ' err' : '');
    el.textContent = msg;
    $('toasts').appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  // The engine banner stays until the user dismisses it or a user-initiated action succeeds.
  function showBanner(text) {
    $('banner-text').textContent = text;
    $('banner').hidden = false;
  }

  function hideBanner() {
    $('banner').hidden = true;
  }

  // ---- formatting -----------------------------------------------------------
  const dayFmt = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  const timeFmt = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' });

  function parseDate(iso) {
    const d = iso ? new Date(iso) : null;
    return d && !Number.isNaN(d.getTime()) ? d : null;
  }

  function dayLabel(d) {
    if (!d) return '';
    const n = new Date();
    const days = Math.round((new Date(n.getFullYear(), n.getMonth(), n.getDate())
      - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
    if (days === 0) return 'Today';
    if (days === 1) return 'Yesterday';
    return dayFmt.format(d).replace(',', '');
  }

  function fmtMinutes(s) {
    return s == null ? '' : `${Math.max(1, Math.round(s / 60))} min`;
  }

  function hotkeyKeys() {
    return prettyHotkey((store.settings && store.settings.hotkey) || '<ctrl>+<alt>+m');
  }

  function chip(text) {
    return `<span class="chip">${escapeHtml(text)}</span>`;
  }

  function deviceChips(d) {
    if (!d) return '';
    const outs = (d.outputs || []).join(', ');
    return (outs ? chip('🎧 ' + outs) : '') + chip('🎤 ' + (d.mic || 'No microphone'));
  }

  // ---- state from the engine ------------------------------------------------
  function isRecording() {
    return !!(store.status && store.status.recording);
  }

  function applyStatus(st) {
    if (!st || typeof st !== 'object') return;
    const prev = store.status;
    const wasRec = !!(prev && prev.recording);
    store.status = st;
    if (st.recording) {
      store.lastDevices = { mic: st.mic, outputs: st.outputs || [] };
      store.clockBase = performance.now() - (st.elapsed_s || 0) * 1000;
      if (!wasRec || prev.folder !== st.folder) {
        store.liveMoments = [];
        store.liveStart = st.muted ? null : st.elapsed_s;
        store.activeFolder = st.folder;
        store.meeting = null;
        store.view = 'rec';
        $('title').value = '';
      } else if (prev.muted && !st.muted) {
        store.liveStart = st.elapsed_s;
      } else if (!prev.muted && st.muted && store.liveStart !== null) {
        store.liveMoments.push([store.liveStart, st.elapsed_s]);
        store.liveStart = null;
      }
    } else if (wasRec) {
      // The recording ended (big button, stop button, pill, tray or engine restart).
      if (store.liveStart !== null) {
        store.liveMoments.push([store.liveStart, prev.elapsed_s]);
        store.liveStart = null;
      }
      const next = decideAfterRecordingEnded(prev, st, store.stopRequested);
      if (next && (store.view === 'rec' || store.activeFolder === next.folder)) {
        if (next.view === 'prog') showTranscribing(next.folder);
        else showEnded(next.folder);
      }
    }
    render();
  }

  function showTranscribing(folder) {
    if (!folder) return;
    store.activeFolder = folder;
    store.meeting = null;
    store.view = 'prog';
    store.endedFolder = folder; // if a stale list ever bounces us to tx, a queued status brings us back
    loadMeeting(folder);
    refreshMeetings(); // a fresh list supersedes any in-flight (stale) one
  }

  // The recording ended without this UI's stop() (engine crash/restart, or a stop from the pill or
  // tray). Show its transcript view; refreshMeetings() moves it to Transcribing if the engine queued it.
  function showEnded(folder) {
    store.activeFolder = folder;
    store.endedFolder = folder;
    store.meeting = null;
    store.view = 'tx';
    store.tab = 'all';
    loadMeeting(folder);
    refreshMeetings();
  }

  let loadSeq = 0;
  async function loadMeeting(folder) {
    const seq = ++loadSeq;
    const m = await call('get_meeting', { folder });
    if (seq !== loadSeq || store.activeFolder !== folder) return null;
    if (m) store.meeting = m;
    render();
    return m;
  }

  let meetingsSeq = 0;
  async function refreshMeetings() {
    const seq = ++meetingsSeq;
    const list = await call('list_meetings');
    if (seq !== meetingsSeq || !Array.isArray(list)) return;
    store.meetings = list;
    for (const f of Object.keys(store.progressByFolder)) {
      const it = list.find((m) => m.folder === f);
      if (!it || it.status === 'transcribed' || it.status === 'not transcribed') delete store.progressByFolder[f];
    }
    const item = list.find((m) => m.folder === store.activeFolder);
    if (store.view === 'prog' && transcribingResolved(item, store.progressByFolder[store.activeFolder])) {
      store.view = 'tx';
      render();
      loadMeeting(store.activeFolder);
      return;
    }
    if (store.view === 'tx' && item && item.folder === store.endedFolder
      && (item.status === 'queued' || item.status === 'transcribing')) {
      store.endedFolder = null;
      store.view = 'prog';
      render();
      return;
    }
    renderSidebar();
    if (store.view === 'prog') renderProg();
  }

  let meetingsTimer = null;
  function scheduleMeetings() {
    clearTimeout(meetingsTimer);
    meetingsTimer = setTimeout(() => {
      refreshMeetings();
      if (store.search.query) runSearch(store.search.query);
    }, 150);
  }

  async function refreshSettings() {
    const s = await call('get_settings');
    if (s) store.settings = s;
  }

  // ---- actions --------------------------------------------------------------
  async function startRecording() {
    if (store.busy || isRecording()) return;
    store.busy = true;
    renderSidebar();
    try {
      const st = await call('start', { title: $('title').value.trim() });
      if (st) {
        hideBanner();
        applyStatus(st);
      }
    } finally {
      store.busy = false;
      renderSidebar();
    }
  }

  async function stopRecording() {
    if (store.busy || !isRecording()) return;
    store.busy = true;
    renderSidebar();
    store.stopRequested = true;
    try {
      const r = await call('stop');
      if (r) hideBanner();
      if (r && r.folder && (store.activeFolder !== r.folder || store.view !== 'prog')) showTranscribing(r.folder);
      const st = await call('status');
      if (st) applyStatus(st);
    } finally {
      store.stopRequested = false;
      store.busy = false;
      render();
    }
  }

  async function toggleMute() {
    if (!isRecording() || store.status.nomic) return;
    const st = await call('toggle_mute');
    if (st) {
      hideBanner();
      applyStatus(st);
    }
  }

  function openMeeting(folder) {
    const item = store.meetings.find((m) => m.folder === folder);
    if (!item) return;
    store.activeFolder = folder;
    store.endedFolder = null;
    if (item.status === 'recording') {
      store.view = 'rec';
      render();
      return;
    }
    if (!store.meeting || store.meeting.folder !== folder) store.meeting = null;
    store.view = effectiveStatus(item) === 'transcribing' || item.status === 'queued' ? 'prog' : 'tx';
    store.tab = 'all';
    render();
    return loadMeeting(folder);
  }

  function goIdle() {
    store.activeFolder = null;
    store.meeting = null;
    store.view = 'idle';
    render();
    $('title').focus();
  }

  async function transcribeAgain() {
    const folder = store.activeFolder;
    if (!folder) return;
    const r = await call('transcribe_again', { folder });
    if (r) {
      hideBanner();
      store.endedFolder = null;
      store.view = 'prog';
      render();
      refreshMeetings();
    }
  }

  // ---- settings dialog ------------------------------------------------------
  const SF = {
    model: 's-model', model_path: 's-model-path', hotkey: 's-hotkey', out: 's-out', theme: 's-theme',
  };
  let settingsSaving = false;

  function setFieldError(el, msg) {
    el.textContent = msg || '';
    el.hidden = !msg;
  }

  async function openSettings() {
    const dlg = $('settings-dlg');
    if (dlg.open) return;
    setFieldError($('s-hotkey-err'), '');
    setFieldError($('s-error'), '');
    await refreshSettings();
    const s = store.settings || {};
    const mics = await call('list_mics');
    const names = Array.isArray(mics) ? mics.slice() : [];
    if (s.mic_device && !names.includes(s.mic_device)) names.push(s.mic_device); // keep a saved but unplugged mic
    $('s-mic').innerHTML = [DEFAULT_MIC_LABEL, ...names]
      .map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
    $(SF.model).value = s.model || 'small.en';
    $(SF.model_path).value = s.model_path || '';
    $('s-mic').value = s.mic_device || DEFAULT_MIC_LABEL;
    $(SF.hotkey).value = s.hotkey || '';
    $('s-follow').checked = !!s.follow_teams_shortcut;
    $('s-delete').checked = !!s.delete_audio_after;
    $(SF.out).value = s.output_dir || '';
    $(SF.theme).value = s.theme || 'system';
    $('s-mic-note').hidden = !isRecording();
    settingsSaving = false;
    $('s-save').disabled = false;
    if (dlg.open) return; // a second click while the lists were loading
    dlg.showModal();
    $(SF.model).focus();
  }

  function closeSettings() {
    if ($('settings-dlg').open) $('settings-dlg').close();
  }

  async function pickInto(id) {
    const dir = await ui('pickFolder');
    if (dir) $(id).value = dir;
  }

  async function saveSettings() {
    if (settingsSaving) return;
    settingsSaving = true;
    $('s-save').disabled = true;
    setFieldError($('s-hotkey-err'), '');
    setFieldError($('s-error'), '');
    try {
      const form = settingsFromForm({
        model: $(SF.model).value, model_path: $(SF.model_path).value, mic: $('s-mic').value,
        hotkey: $(SF.hotkey).value, follow_teams_shortcut: $('s-follow').checked,
        delete_audio_after: $('s-delete').checked, output_dir: $(SF.out).value, theme: $(SF.theme).value,
      });
      let saved;
      try {
        saved = await api.call('save_settings', form);
      } catch (err) {
        const msg = errText(err);
        setFieldError(/shortcut/i.test(msg) ? $('s-hotkey-err') : $('s-error'), msg);
        return;
      }
      store.settings = saved && typeof saved === 'object' ? saved : form;
      closeSettings();
      ui('setTheme', { theme: store.settings.theme || form.theme });
      refreshMeetings(); // output_dir may have changed
      render(); // footer model label and the idle hotkey hint
    } finally {
      settingsSaving = false;
      $('s-save').disabled = false;
    }
  }

  function wireSettings() {
    $('settings-link').addEventListener('click', openSettings);
    $('settings-form').addEventListener('submit', (e) => {
      e.preventDefault();
      saveSettings();
    });
    $('s-cancel').addEventListener('click', closeSettings);
    $('s-model-path-pick').addEventListener('click', () => pickInto(SF.model_path));
    $('s-out-pick').addEventListener('click', () => pickInto(SF.out));
    // Esc closes a modal <dialog> natively and focus stays trapped inside it.
  }

  // ---- search ---------------------------------------------------------------
  let searchSeq = 0;
  let searchTimer = null;
  async function runSearch(q) {
    const seq = ++searchSeq;
    if (!q) {
      store.search = { query: '', counts: new Map() };
      render();
      return;
    }
    const res = await call('search', { query: q });
    if (seq !== searchSeq) return;
    store.search = { query: q, counts: new Map((res || []).map((r) => [r.folder, r.count])) };
    render();
  }

  // ---- rendering: sidebar ---------------------------------------------------
  function effectiveStatus(item) {
    if (item.status !== 'recording' && item.status !== 'transcribed' && store.progressByFolder[item.folder]) {
      return 'transcribing';
    }
    return item.status;
  }

  function itemProgress(item) {
    const p = store.progressByFolder[item.folder];
    return p ? p.frac : (item.progress || 0);
  }

  function itemSub(item, status) {
    if (status === 'recording') return `<span id="rec-sub">Recording · ${fmtClock(recElapsed(), true)}</span>`;
    if (status === 'transcribing') {
      const p = store.progressByFolder[item.folder];
      if (p && p.stage === 'model') return 'Downloading model…';
      return isRecording() ? 'Paused while recording' : `Transcribing ${Math.round(itemProgress(item) * 100)}%`;
    }
    if (status === 'queued') return isRecording() ? 'Queued · paused while recording' : 'Queued';
    const d = parseDate(item.start);
    const parts = [];
    if (d) {
      const label = dayLabel(d);
      parts.push((label === 'Today' || label === 'Yesterday' ? '' : label + ' · ') + timeFmt.format(d));
    }
    if (status === 'not transcribed') parts.push('Not transcribed');
    else if (item.duration_s != null) parts.push(fmtMinutes(item.duration_s));
    let s = escapeHtml(parts.join(' · '));
    const hits = store.search.counts.get(item.folder);
    const n = Number(hits) || 0;
    if (store.search.query && n) s += ` · <span class="hits">${n} match${n === 1 ? '' : 'es'}</span>`;
    return s;
  }

  function renderSidebar() {
    const rec = isRecording();
    const big = $('bigbtn');
    big.textContent = rec ? '■ Stop recording' : '● New recording';
    big.classList.toggle('stop', rec);
    big.disabled = store.busy;

    const q = store.search.query.toLowerCase();
    let items = store.meetings;
    if (q) {
      items = items.filter((m) => store.search.counts.has(m.folder)
        || String(m.title || '').toLowerCase().includes(q)
        || ['recording', 'queued', 'transcribing'].includes(effectiveStatus(m)));
    }
    const groups = groupMeetings(items.map((m) => ({ ...m, status: effectiveStatus(m) })), new Date());
    let html = '';
    for (const g of groups) {
      html += `<div class="group">${escapeHtml(g.label)}</div>`;
      for (const it of g.items) {
        const active = it.folder === store.activeFolder && store.view !== 'idle';
        const bar = it.status === 'transcribing' && !rec
          ? `<div class="pbar"><i style="width:${(itemProgress(it) * 100).toFixed(1)}%"></i></div>` : '';
        html += `<button type="button" class="item${active ? ' active' : ''}" data-folder="${escapeHtml(it.folder)}">`
          + `<div class="t"><span class="dot" style="background:${statusDot(it.status)}"></span>`
          + `<span>${escapeHtml(it.title || 'Meeting')}</span></div>`
          + `<div class="s">${itemSub(it, it.status)}</div>${bar}</button>`;
      }
    }
    if (!html) html = `<div class="empty">${q ? 'No matches' : 'No meetings yet'}</div>`;
    $('list').innerHTML = html;
    $('foot-model').textContent = `${(store.settings && store.settings.model) || 'small.en'} · 🔒 offline`;
  }

  // ---- rendering: main views ------------------------------------------------
  function render() {
    renderSidebar();
    for (const v of ['idle', 'rec', 'prog', 'tx']) $('v-' + v).classList.toggle('on', store.view === v);
    if (store.view !== 'tx') txView.pause();
    if (store.view === 'idle') renderIdle();
    else if (store.view === 'rec') renderRec();
    else if (store.view === 'prog') renderProg();
    else txView.render();
  }

  function renderIdle() {
    const fallback = { mic: (store.settings && store.settings.mic_device) || 'Default microphone', outputs: [] };
    $('idle-devices').innerHTML = deviceChips(store.lastDevices || fallback);
    const keys = hotkeyKeys().map((k) => `<kbd class="k">${escapeHtml(k)}</kbd>`).join(' ');
    $('idle-hint').innerHTML = `Everything you hear is recorded. Your mic starts <b>muted</b> — press ${keys} when you speak.`;
    $('start-btn').disabled = store.busy;
  }

  function recElapsed() {
    if (!isRecording()) return 0;
    return Math.max(0, (performance.now() - store.clockBase) / 1000);
  }

  function renderRec() {
    const st = store.status;
    if (!st || !st.recording) {
      // The recording view is only meaningful while recording.
      store.view = store.activeFolder ? 'prog' : 'idle';
      render();
      return;
    }
    $('rtitle').textContent = st.title || 'Meeting';
    $('rmeta').innerHTML = deviceChips({ mic: st.mic, outputs: st.outputs }) + chip('🔒 Stays on this PC');
    const mute = $('mute');
    mute.hidden = !!st.nomic;
    $('nomic').hidden = !st.nomic;
    mute.classList.toggle('on', !st.muted);
    mute.classList.toggle('off', !!st.muted);
    $('mlabel').textContent = st.muted ? 'MUTED' : 'LIVE';
    $('slash').style.display = st.muted ? '' : 'none';
    $('mhint').textContent = 'Click or ' + hotkeyKeys().join('+');
    $('mestate').textContent = st.nomic ? 'no microphone' : (st.muted ? 'muted' : 'live');
    $('recpane').classList.toggle('live', !st.muted && !st.nomic);
    tick();
  }

  function drawTrack(el, moments, total) {
    el.innerHTML = timelineSegments(moments, total)
      .map((s) => `<i style="left:${s.leftPct}%;width:${s.widthPct}%"></i>`).join('');
  }

  // Runs ~4x a second while recording: timer text and the live timeline.
  function tick() {
    if (!isRecording()) return;
    const e = recElapsed();
    const sub = $('rec-sub');
    if (sub) sub.textContent = 'Recording · ' + fmtClock(e, true);
    if (store.view !== 'rec') return;
    $('rtime').textContent = fmtClock(e);
    $('rtime2').textContent = fmtClock(e, true);
    const moments = store.liveStart !== null ? store.liveMoments.concat([[store.liveStart, e]]) : store.liveMoments;
    drawTrack($('track'), moments, Math.max(e, 1));
  }

  function drawMeters() {
    const t = Date.now() / 1000;
    const rec = isRecording() && store.view === 'rec';
    const set = (el, v) => {
      const amp = rec ? Math.min(1, (v || 0) * 3) : 0;
      [...el.children].forEach((b, i) => {
        const wave = 0.55 + 0.45 * Math.abs(Math.sin(t * 3 + i * 0.7));
        const h = amp * 100 * wave * (0.75 + 0.5 * Math.random());
        b.style.height = Math.max(6, Math.min(100, h)) + '%';
      });
    };
    set($('bo'), store.levels.others);
    set($('bm'), store.levels.me);
  }

  function activeItem() {
    return store.meetings.find((m) => m.folder === store.activeFolder) || null;
  }

  function renderProg() {
    const item = activeItem();
    const m = store.meeting;
    const title = (m && m.title) || (item && item.title) || 'Meeting';
    $('ptitle').textContent = title;
    const d = parseDate((m && m.start) || (item && item.start));
    $('pmeta').innerHTML = `<span>${escapeHtml(dayLabel(d) || '')}</span><span>· transcribing on this PC</span>`;
    let p = store.progressByFolder[store.activeFolder];
    if (!p && item && item.status === 'transcribing') p = { frac: item.progress || 0, eta_s: null, stage: 'transcribe' };
    const ring = $('ring');
    ring.classList.remove('spin', 'idle-ring');
    if (isRecording()) {
      ring.style.setProperty('--v', p ? p.frac * 100 : 0);
      $('pct').textContent = p ? Math.round(p.frac * 100) + '%' : '—';
      $('pstage').textContent = 'Paused while recording';
      $('eta').textContent = 'Transcription continues when the recording stops';
    } else if (p && p.stage === 'model') {
      ring.classList.add('spin');
      $('pct').textContent = '';
      $('pstage').textContent = MODEL_TEXT;
      $('eta').textContent = 'You can keep working, it runs quietly';
    } else if (p) {
      ring.style.setProperty('--v', p.frac * 100);
      $('pct').textContent = Math.round(p.frac * 100) + '%';
      $('pstage').textContent = 'Transcribing…';
      $('eta').textContent = `${fmtEta(p.eta_s)} · you can keep working, it runs quietly`;
    } else {
      ring.classList.add('idle-ring');
      $('pct').textContent = '0%';
      $('pstage').textContent = 'Waiting to transcribe…';
      $('eta').textContent = 'estimating…';
    }
  }

  // ---- wiring ---------------------------------------------------------------
  function buildBars() {
    $('bo').innerHTML = '<i></i>'.repeat(BARS);
    $('bm').innerHTML = '<i></i>'.repeat(BARS);
  }

  function wire() {
    // Not recording: show Idle with the title box focused (its Start / Enter starts). Recording: stop.
    $('bigbtn').addEventListener('click', () => (isRecording() ? stopRecording() : goIdle()));
    $('banner-x').addEventListener('click', hideBanner);
    $('start-form').addEventListener('submit', (e) => {
      e.preventDefault();
      startRecording();
    });
    $('stop-btn').addEventListener('click', stopRecording);
    $('mute').addEventListener('click', toggleMute);
    $('pill-btn').addEventListener('click', () => ui('minimiseToPill'));
    wireSettings();

    $('list').addEventListener('click', (e) => {
      const el = e.target.closest('.item');
      if (el) openMeeting(el.dataset.folder);
    });

    $('q').addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      const q = e.target.value.trim();
      searchTimer = setTimeout(() => runSearch(q), 200);
    });
    $('q').addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.target.value = '';
        clearTimeout(searchTimer);
        runSearch('');
      }
    });

    // Ctrl+Alt+M is a global hotkey owned by the engine, so it is not handled here (it would toggle twice).
    window.addEventListener('keydown', (e) => {
      if (e.ctrlKey && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        $('q').focus();
        $('q').select();
      }
    });

    api.on('state', applyStatus);
    // Stop/start requested from the pill or tray run through the same paths as the buttons.
    api.onUi('requestStop', stopRecording);
    api.onUi('requestStart', startRecording);
    api.on('levels', (d) => {
      store.levels = d || { others: 0, me: 0 };
      drawMeters();
    });
    api.on('progress', (d) => {
      if (!d || !d.folder) return;
      store.progressByFolder[d.folder] = d;
      renderSidebar();
      if (store.view === 'prog' && store.activeFolder === d.folder) renderProg();
    });
    api.on('transcribed', async (d) => {
      if (!d || !d.folder) return;
      delete store.progressByFolder[d.folder];
      if (store.activeFolder === d.folder && (store.view === 'prog' || store.view === 'tx')) {
        const m = await loadMeeting(d.folder);
        if (m && store.activeFolder === d.folder && store.view === 'prog') {
          store.view = 'tx';
          store.tab = 'all';
          render();
        }
      }
    });
    api.on('error', (d) => {
      toast((d && d.message) || 'Something went wrong', true);
      if (d && d.folder) {
        delete store.progressByFolder[d.folder];
        if (store.activeFolder === d.folder && store.view === 'prog') {
          store.view = 'tx';
          loadMeeting(d.folder);
          render();
        }
      }
    });
    api.on('meetings_changed', () => {
      refreshSettings();
      scheduleMeetings();
    });
    api.on('engine_exit', () => {
      showBanner('Recording engine stopped unexpectedly — your audio so far is saved');
      // The engine restarts on its own; pick up its fresh state shortly after.
      setTimeout(refreshAll, 3000);
    });
    api.on('engine_failed', (d) => {
      const cmd = (d && d.command) || 'engine';
      showBanner(`Couldn't start the recording engine (${cmd}). See %APPDATA%\\TeamsListener\\app.log.`);
    });

    setInterval(tick, 250);
  }

  async function refreshAll() {
    const st = await api.call('status').catch(() => null);
    if (!st) return;
    applyStatus(st);
    refreshMeetings();
  }

  let txView = null;

  async function boot() {
    buildBars();
    txView = window.TLViews.transcript({
      store, $, ui, toast, errText, activeItem, transcribeAgain, parseDate, fmtMinutes, dayFmt, timeFmt,
    });
    wire();
    const [st, settings] = await Promise.all([call('status'), call('get_settings')]);
    if (settings) store.settings = settings;
    if (st) applyStatus(st);
    await refreshMeetings();
    render();
    if (params.get('smokeOpen')) {
      const newest = store.meetings.find((m) => m.status === 'transcribed');
      if (newest) await openMeeting(newest.folder);
    }
    if (params.get('smokeIdle')) $('bigbtn').click(); // reach Idle the way a user would
    if (params.get('smokeSettings')) await openSettings();
    requestAnimationFrame(() => api.ui('smokeReady').catch(() => {}));
  }

  boot();
})();
