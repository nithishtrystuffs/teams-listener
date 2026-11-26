'use strict';
// Transcript view: lines with search highlights, tabs, details and the two-track audio player.
window.TLViews = window.TLViews || {};
window.TLViews.transcript = (ctx) => {
  const {
    store, $, ui, toast, errText, activeItem, transcribeAgain, parseDate, fmtMinutes, dayFmt, timeFmt,
  } = ctx;
  const { fmtClock, escapeHtml, highlight, timelineSegments, audioUrl } = window.TL;

  function fmtLive(s) {
    const m = Math.floor(s / 60);
    const x = Math.round(s % 60);
    return m ? `${m} min ${x} s` : `${x} s`;
  }

  function fmtBytes(n) {
    if (!n) return '0 MB';
    return n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(0.1, n / 1e6).toFixed(n >= 1e7 ? 0 : 1)} MB`;
  }

  function transcriptText(m) {
    return (m.lines || []).map((l) => `[${l.ts}] ${l.speaker}: ${l.text}`).join('\n');
  }

  // ---- transcript view ------------------------------------------------------
  let txKey = '';
  let lastTxMeeting = null;
  function renderTx() {
    const m = store.meeting && store.meeting.folder === store.activeFolder ? store.meeting : null;
    const item = activeItem();
    $('ttitle').textContent = (m && m.title) || (item && item.title) || 'Meeting';
    const chipEl = $('tchip');
    chipEl.hidden = !m;
    if (m) {
      chipEl.textContent = m.has_transcript ? '✓ Transcribed' : 'Not transcribed';
      chipEl.classList.toggle('ok', !!m.has_transcript);
    }
    const meta = [];
    if (m) {
      const d = parseDate(m.start);
      if (d) meta.push(`${dayFmt.format(d).replace(',', '')} · ${timeFmt.format(d)}`);
      if (m.duration_s != null) meta.push(fmtMinutes(m.duration_s));
      const who = new Set((m.lines || []).map((l) => l.speaker));
      if (who.size) meta.push(who.size === 2 ? 'Others & Me' : `${[...who][0]} only`);
    }
    $('tmeta').innerHTML = meta.map((s, i) => `<span>${i ? '· ' : ''}${escapeHtml(s)}</span>`).join('');
    const hasTx = !!(m && m.has_transcript);
    $('copy-btn').disabled = !hasTx;
    $('export-btn').disabled = !hasTx;
    $('folder-btn').disabled = !m;
    $('again-btn').disabled = !m || (item && item.status === 'recording');
    $('again-btn').textContent = hasTx || !m ? '↻ Transcribe again' : '↻ Transcribe';
    for (const b of $('tabs').children) b.classList.toggle('on', b.dataset.tab === store.tab);
    setupPlayer(m);

    const key = [store.activeFolder, store.tab, store.search.query, m ? 1 : 0].join('|');
    if (key === txKey && m === lastTxMeeting) return;
    txKey = key;
    lastTxMeeting = m;
    $('tx').innerHTML = m ? txBody(m) : '<div class="placeholder">Loading…</div>';
    $('tx').scrollTop = 0;
  }

  function txBody(m) {
    if (store.tab === 'details') return detailsHtml(m);
    if (!m.has_transcript) {
      return '<div class="placeholder">This meeting hasn\'t been transcribed yet.<br>'
        + '<button class="btn primary" type="button" data-action="transcribe">↻ Transcribe</button></div>';
    }
    const lines = (m.lines || []).filter((l) => store.tab === 'all' || l.speaker === 'Me');
    if (!lines.length) {
      return `<div class="placeholder">${store.tab === 'me' ? 'You didn\'t speak in this meeting.' : 'No speech was found in this meeting.'}</div>`;
    }
    const canSeek = !!m.audio;
    return lines.map((l) => {
      const c = l.speaker === 'Me' ? 'm' : 'o';
      return `<div class="line"><button type="button" class="ts" data-t="${Number(l.t) || 0}"${canSeek ? ' title="Play from here"' : ' disabled'}>${escapeHtml(l.ts)}</button>`
        + `<span class="av ${c}">${c === 'm' ? 'M' : 'O'}</span>`
        + `<div><div class="who ${c}">${escapeHtml(l.speaker)}</div><p>${highlight(l.text, store.search.query)}</p></div></div>`;
    }).join('');
  }

  function detailsHtml(m) {
    const devices = (m.devices || []).map((d) => `<b>${escapeHtml(d)}</b>`);
    const moments = m.live_moments || [];
    const rows = [
      devices.length ? `Recorded from ${devices.join(' and ')}` : 'Recorded devices unknown',
      moments.length
        ? `You were live for <b>${fmtLive(m.live_s || 0)}</b> across ${moments.length} moment${moments.length === 1 ? '' : 's'}`
        : 'You stayed muted for the whole meeting',
    ];
    let track = '';
    if (moments.length && m.duration_s) {
      track = '<div class="track">' + timelineSegments(moments, m.duration_s)
        .map((s) => `<i style="left:${s.leftPct}%;width:${s.widthPct}%"></i>`).join('') + '</div>';
    }
    rows.push(`Model: <b>${escapeHtml(m.model || 'not transcribed yet')}</b> · `
      + (m.audio_bytes ? `audio kept (${fmtBytes(m.audio_bytes)})` : 'no audio kept'));
    rows.push(`Folder: <b>${escapeHtml(m.folder)}</b>`);
    return `<div class="details">${rows[0]}<br>${rows[1]}${track}<br>${rows[2]}<br>${rows[3]}</div>`;
  }

  // ---- audio player (two tracks kept in sync) -------------------------------
  const ao = $('a-others');
  const am = $('a-me');
  let playerFolder = null;

  function setupPlayer(m) {
    const show = !!(m && m.audio);
    $('player-wrap').hidden = !show;
    if (!show) {
      if (playerFolder) {
        pauseAudio();
        ao.removeAttribute('src');
        am.removeAttribute('src');
        playerFolder = null;
      }
      return;
    }
    if (playerFolder === m.folder) return;
    playerFolder = m.folder;
    ao.src = audioUrl(m.folder, 'others');
    am.src = audioUrl(m.folder, 'me');
    updatePlayer();
  }

  function audioDuration() {
    const d = Math.max(Number.isFinite(ao.duration) ? ao.duration : 0, Number.isFinite(am.duration) ? am.duration : 0);
    return d || (store.meeting && store.meeting.duration_s) || 0;
  }

  function updatePlayer() {
    const dur = audioDuration();
    $('pos').textContent = fmtClock(ao.currentTime);
    $('dur').textContent = fmtClock(dur);
    $('seek-fill').style.width = dur ? Math.min(100, (ao.currentTime / dur) * 100) + '%' : '0';
    $('play-btn').textContent = ao.paused ? '▶' : '❚❚';
    $('play-btn').title = ao.paused ? 'Play' : 'Pause';
  }

  function playAudio() {
    am.currentTime = ao.currentTime;
    Promise.all([ao.play(), am.play()]).catch((err) => toast('Couldn\'t play the audio: ' + errText(err), true));
  }

  function pauseAudio() {
    if (!ao.paused) ao.pause();
    if (!am.paused) am.pause();
  }

  function seekTo(t) {
    const x = Math.max(0, Math.min(t, audioDuration() || t));
    ao.currentTime = x;
    am.currentTime = x;
    updatePlayer();
  }

  ao.addEventListener('timeupdate', () => {
    if (!ao.paused && !am.paused && Math.abs(am.currentTime - ao.currentTime) > 0.25) am.currentTime = ao.currentTime;
    updatePlayer();
  });
  for (const ev of ['play', 'pause', 'loadedmetadata', 'durationchange']) ao.addEventListener(ev, updatePlayer);
  ao.addEventListener('pause', () => { if (!am.paused) am.pause(); });
  ao.addEventListener('ended', () => am.pause());
  ao.addEventListener('error', () => { if (playerFolder) toast('Couldn\'t load the meeting audio', true); });

  function seekFromPointer(e) {
    const r = $('seek').getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    seekTo(frac * audioDuration());
  }

  function wire() {
  $('tabs').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-tab]');
    if (!b) return;
    store.tab = b.dataset.tab;
    renderTx();
  });
  $('tx').addEventListener('click', (e) => {
    const ts = e.target.closest('.ts');
    if (ts && !ts.disabled) {
      seekTo(Number(ts.dataset.t) || 0);
      playAudio();
      return;
    }
    if (e.target.closest('[data-action="transcribe"]')) transcribeAgain();
  });

  $('copy-btn').addEventListener('click', async () => {
    if (!store.meeting) return;
    const r = await window.api.ui('copyText', { text: transcriptText(store.meeting) }).then(() => true, (err) => {
      toast(errText(err), true);
      return false;
    });
    if (r) toast('Transcript copied');
  });
  $('export-btn').addEventListener('click', async () => {
    if (!store.meeting) return;
    const p = await ui('exportMarkdown', { folder: store.meeting.folder });
    if (p) toast('Saved to ' + p);
  });
  $('folder-btn').addEventListener('click', () => store.meeting && ui('openFolder', { path: store.meeting.folder }));
  $('again-btn').addEventListener('click', transcribeAgain);

  $('play-btn').addEventListener('click', () => (ao.paused ? playAudio() : pauseAudio()));
  $('seek').addEventListener('pointerdown', (e) => {
    $('seek').setPointerCapture(e.pointerId);
    seekFromPointer(e);
  });
  $('seek').addEventListener('pointermove', (e) => {
    if ($('seek').hasPointerCapture(e.pointerId)) seekFromPointer(e);
  });
  }

  wire();
  return { render: renderTx, pause: pauseAudio };
};
