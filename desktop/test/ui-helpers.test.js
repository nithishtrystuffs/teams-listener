const test = require('node:test');
const assert = require('node:assert');
const {
  groupMeetings, fmtClock, fmtEta, highlight, statusDot, timelineSegments, prettyHotkey, audioUrl,
  decideAfterRecordingEnded, transcribingResolved,
} = require('../renderer/lib/ui-helpers');

const now = new Date(2026, 10, 26, 15, 0, 0); // local time, Thu 26 Nov 2026

function m(folder, start, status = 'transcribed') {
  return { folder, title: folder, start, duration_s: 60, status, progress: null };
}

test('groupMeetings buckets by day and puts active work under Now', () => {
  const list = [
    m('rec', null, 'recording'),
    m('t', '2026-11-26T10:00:00'),
    m('y', '2026-11-25T18:30:00'),
    m('w', '2026-11-21T09:00:00'),
    m('o', '2026-11-01T09:00:00'),
    m('tr', '2026-11-26T09:00:00', 'transcribing'),
    m('q', '2026-11-20T09:00:00', 'queued'),
  ];
  const groups = groupMeetings(list, now);
  const byLabel = Object.fromEntries(groups.map((g) => [g.label, g.items.map((i) => i.folder)]));
  assert.deepStrictEqual(groups.map((g) => g.label), ['Now', 'Today', 'Yesterday', 'This week', 'Older']);
  assert.deepStrictEqual(byLabel.Now, ['rec', 'tr', 'q']);
  assert.deepStrictEqual(byLabel.Today, ['t']);
  assert.deepStrictEqual(byLabel.Yesterday, ['y']);
  assert.deepStrictEqual(byLabel['This week'], ['w']);
  assert.deepStrictEqual(byLabel.Older, ['o']);
});

test('groupMeetings omits empty groups and files unknown dates under Older', () => {
  const groups = groupMeetings([m('x', null, 'not transcribed')], now);
  assert.deepStrictEqual(groups, [{ label: 'Older', items: [m('x', null, 'not transcribed')] }]);
});

test('fmtClock', () => {
  assert.strictEqual(fmtClock(763), '00:12:43');
  assert.strictEqual(fmtClock(763, true), '12:43');
  assert.strictEqual(fmtClock(3723.9), '01:02:03');
  assert.strictEqual(fmtClock(3723, true), '62:03');
});

test('fmtEta', () => {
  assert.strictEqual(fmtEta(null), 'estimating…');
  assert.strictEqual(fmtEta(undefined), 'estimating…');
  assert.strictEqual(fmtEta(30), 'Less than a minute left');
  assert.strictEqual(fmtEta(240), 'About 4 min left');
  assert.strictEqual(fmtEta(250), 'About 5 min left');
});

test('highlight escapes then marks case-insensitively', () => {
  const h = highlight('<b>Deploy</b> deploy', 'deploy');
  assert.ok(h.includes('&lt;b&gt;<mark>Deploy</mark>&lt;/b&gt; <mark>deploy</mark>'), h);
  assert.strictEqual(highlight(`a & "b" 'c'`, ''), 'a &amp; &quot;b&quot; &#39;c&#39;');
});

test('highlight with regex metacharacters does not throw', () => {
  assert.doesNotThrow(() => highlight('a+b', '+'));
  assert.strictEqual(highlight('a+b', '+'), 'a<mark>+</mark>b');
});

test('highlight does not match inside escaped entities', () => {
  assert.strictEqual(highlight('a & b', 'amp'), 'a &amp; b');
});

test('statusDot maps status to a CSS variable', () => {
  assert.strictEqual(statusDot('transcribed'), 'var(--green)');
  assert.strictEqual(statusDot('recording'), 'var(--red)');
  assert.strictEqual(statusDot('transcribing'), 'var(--accent)');
  assert.strictEqual(statusDot('queued'), 'var(--accent)');
  assert.strictEqual(statusDot('not transcribed'), 'var(--faint)');
});

test('timelineSegments enforces a minimum width', () => {
  assert.strictEqual(timelineSegments([[0, 1]], 1000)[0].widthPct, 0.8);
  assert.deepStrictEqual(timelineSegments([[50, 100]], 200), [{ leftPct: 25, widthPct: 25 }]);
  assert.deepStrictEqual(timelineSegments([[0, 5]], 0), [{ leftPct: 0, widthPct: 100 }]);
});

test('prettyHotkey', () => {
  assert.deepStrictEqual(prettyHotkey('<ctrl>+<alt>+m'), ['Ctrl', 'Alt', 'M']);
  assert.deepStrictEqual(prettyHotkey('<shift>+<cmd>+<f9>'), ['Shift', 'Win', 'F9']);
});

test('audioUrl uses the folder basename', () => {
  assert.strictEqual(audioUrl('C:\\x\\TeamsTranscripts\\2026-11-25_1826_A B', 'others'),
    'app-audio://meeting/2026-11-25_1826_A%20B/others.flac');
});

test('timelineSegments keeps left + width within 100', () => {
  for (const seg of [[999, 1000], [1000, 1000], [995, 1000]]) {
    const [s] = timelineSegments([seg], 1000);
    assert.ok(s.leftPct + s.widthPct <= 100 + 1e-9, JSON.stringify(s));
    assert.ok(s.widthPct >= 0.8 - 1e-9, JSON.stringify(s));
  }
  assert.deepStrictEqual(timelineSegments([[1000, 1000]], 1000), [{ leftPct: 99.2, widthPct: 0.8 }]);
});

const recA = { recording: true, muted: true, folder: 'A', elapsed_s: 5 };
const idle = { recording: false, muted: true, folder: null, elapsed_s: 0 };

test('decideAfterRecordingEnded: no transition means no decision', () => {
  assert.strictEqual(decideAfterRecordingEnded(null, idle, false), null);
  assert.strictEqual(decideAfterRecordingEnded(idle, idle, false), null);
  assert.strictEqual(decideAfterRecordingEnded(recA, { ...recA, muted: false }, false), null);
  assert.strictEqual(decideAfterRecordingEnded(idle, recA, false), null);
});

test('decideAfterRecordingEnded: a stop this UI asked for goes to Transcribing', () => {
  assert.deepStrictEqual(decideAfterRecordingEnded(recA, idle, true), { folder: 'A', view: 'prog' });
});

test('decideAfterRecordingEnded: an unexpected end (engine crash) goes to the Transcript view', () => {
  assert.deepStrictEqual(decideAfterRecordingEnded(recA, idle, false), { folder: 'A', view: 'tx' });
});

test('transcribingResolved: leave Transcribing only when the engine has nothing queued for it', () => {
  const it = (status) => ({ folder: 'A', status });
  assert.strictEqual(transcribingResolved(it('transcribed'), null), true);
  assert.strictEqual(transcribingResolved(it('not transcribed'), null), true);
  assert.strictEqual(transcribingResolved(it('not transcribed'), { frac: 0.2 }), false);
  assert.strictEqual(transcribingResolved(it('queued'), null), false);
  assert.strictEqual(transcribingResolved(it('transcribing'), null), false);
  assert.strictEqual(transcribingResolved(it('recording'), null), false);
  assert.strictEqual(transcribingResolved(null, null), false);
});
