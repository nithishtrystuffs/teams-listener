// Pure helpers shared by the renderer (window.TL) and the Node tests (module.exports).
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TL = api;
}(typeof self !== 'undefined' ? self : this, () => {
  const ACTIVE = new Set(['recording', 'queued', 'transcribing']);
  const ORDER = ['Now', 'Today', 'Yesterday', 'This week', 'Older'];
  const DAY = 86400000;

  function dayStart(d) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  }

  function groupOf(item, now) {
    if (ACTIVE.has(item.status)) return 'Now';
    const d = item.start ? new Date(item.start) : null;
    if (!d || Number.isNaN(d.getTime())) return 'Older';
    const days = Math.round((dayStart(now) - dayStart(d)) / DAY);
    if (days <= 0) return 'Today';
    if (days === 1) return 'Yesterday';
    if (days < 7) return 'This week';
    return 'Older';
  }

  function groupMeetings(list, now) {
    const buckets = new Map(ORDER.map((l) => [l, []]));
    for (const item of list || []) buckets.get(groupOf(item, now)).push(item);
    return ORDER.filter((l) => buckets.get(l).length).map((label) => ({ label, items: buckets.get(label) }));
  }

  const pad = (n) => String(n).padStart(2, '0');

  function fmtClock(sec, short = false) {
    const s = Math.max(0, Math.floor(Number(sec) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const x = s % 60;
    return short ? `${pad(m + h * 60)}:${pad(x)}` : `${pad(h)}:${pad(m)}:${pad(x)}`;
  }

  function fmtEta(sec) {
    if (sec === null || sec === undefined || !Number.isFinite(Number(sec))) return 'estimating…';
    if (sec < 60) return 'Less than a minute left';
    return `About ${Math.ceil(sec / 60)} min left`;
  }

  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c]);
  }

  // Escapes the text and wraps case-insensitive matches of query in <mark>. Matching runs on the raw
  // text, so a query never matches inside an entity such as &amp;.
  function highlight(text, query) {
    const raw = String(text ?? '');
    const q = String(query ?? '').trim();
    if (!q) return escapeHtml(raw);
    const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    let out = '';
    let last = 0;
    for (const mt of raw.matchAll(re)) {
      out += escapeHtml(raw.slice(last, mt.index)) + '<mark>' + escapeHtml(mt[0]) + '</mark>';
      last = mt.index + mt[0].length;
    }
    return out + escapeHtml(raw.slice(last));
  }

  function statusDot(status) {
    switch (status) {
      case 'transcribed': return 'var(--green)';
      case 'recording': return 'var(--red)';
      case 'transcribing':
      case 'queued': return 'var(--accent)';
      default: return 'var(--faint)';
    }
  }

  const MIN_SEG = 0.8;
  function timelineSegments(moments, total) {
    const t = Math.max(Number(total) || 0, 0);
    return (moments || []).map(([a, b]) => {
      if (t <= 0) return { leftPct: 0, widthPct: 100 };
      const widthPct = Math.min(100, Math.max(((Math.max(b, a) - a) / t) * 100, MIN_SEG));
      // Keep the segment inside the track: left + width <= 100.
      const leftPct = Math.min(Math.max(0, (a / t) * 100), 100 - widthPct);
      return { leftPct: Math.round(leftPct * 1e6) / 1e6, widthPct };
    });
  }

  // What to show when a recording ends. A stop this UI asked for goes to Transcribing; an unexpected
  // end (engine crash/restart) opens the Transcript view, which offers Transcribe. null = no transition.
  function decideAfterRecordingEnded(prev, status, stopRequested) {
    if (!prev || !prev.recording || !prev.folder) return null;
    if (status && status.recording && status.folder === prev.folder) return null;
    if (status && status.recording) return null; // a new recording replaced it; the rec view takes over
    return { folder: prev.folder, view: stopRequested ? 'prog' : 'tx' };
  }

  // True when the Transcribing view for this list item has nothing left to wait for.
  function transcribingResolved(item, progress) {
    if (!item || progress) return false;
    return item.status === 'transcribed' || item.status === 'not transcribed';
  }

  const KEY_NAMES = { ctrl: 'Ctrl', alt: 'Alt', shift: 'Shift', cmd: 'Win', win: 'Win', space: 'Space' };
  // "<ctrl>+<alt>+m" -> ["Ctrl", "Alt", "M"]
  function prettyHotkey(hk) {
    return String(hk || '').split('+').map((p) => p.trim().replace(/^<|>$/g, '')).filter(Boolean)
      .map((k) => KEY_NAMES[k.toLowerCase()] || k.toUpperCase());
  }

  function basename(p) {
    const parts = String(p || '').split(/[\\/]/).filter(Boolean);
    return parts[parts.length - 1] || '';
  }

  function audioUrl(folder, track) {
    return `app-audio://meeting/${encodeURIComponent(basename(folder))}/${track}.flac`;
  }

  const DEFAULT_MIC_LABEL = 'Default communications mic';

  // Form field values -> the dict save_settings expects.
  function settingsFromForm(f) {
    const str = (v) => String(v ?? '').trim();
    return {
      model: str(f.model),
      model_path: str(f.model_path) || null,
      mic_device: !str(f.mic) || str(f.mic) === DEFAULT_MIC_LABEL ? null : str(f.mic),
      hotkey: str(f.hotkey),
      follow_teams_shortcut: !!f.follow_teams_shortcut,
      delete_audio_after: !!f.delete_audio_after,
      output_dir: str(f.output_dir),
      theme: str(f.theme),
    };
  }

  // Engine `state` events and status replies carry a monotonic `seq`. An RPC reply can reach a window
  // after a newer `state` event, so a status with a lower seq than the last applied one is stale.
  // No seq: apply (older engine, test fakes). Negative seq: the engine went away, a reset marker.
  function shouldApplyState(lastSeq, st) {
    if (!st || typeof st !== 'object') return false;
    if (typeof st.seq !== 'number' || st.seq < 0) return true;
    if (typeof lastSeq !== 'number') return true;
    return st.seq >= lastSeq;
  }

  // The last-applied seq after applying st.
  function seqAfter(lastSeq, st) {
    return st && typeof st.seq === 'number' ? st.seq : lastSeq;
  }

  return {
    shouldApplyState, seqAfter,
    groupMeetings, fmtClock, fmtEta, escapeHtml, highlight, statusDot, timelineSegments,
    prettyHotkey, basename, audioUrl, decideAfterRecordingEnded, transcribingResolved,
    settingsFromForm, DEFAULT_MIC_LABEL,
  };
}));
