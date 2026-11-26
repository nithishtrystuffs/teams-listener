# Electron Front End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Tkinter window with an Electron app that matches the approved prototype. The existing Python engine is driven over JSON lines, and everything ships as one per-user Windows installer.

**Architecture:**
- The Tkinter `App`'s orchestration moves into a UI-free `Controller`. A thin `server.py` exposes the Controller over stdin/stdout JSON lines.
- Electron's main process spawns the engine (the venv Python in development, a PyInstaller-frozen exe when packaged). It forwards commands and events to two renderers (main window and pill) through a narrow preload API.
- electron-builder ships the frozen engine as `extraResources`.

**Tech Stack:**
- Python: Python 3.11, existing libraries, `pyinstaller` (build only).
- Electron: Electron (current stable), electron-builder (NSIS).
- Renderer: plain HTML/CSS/JS. JS tests use `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-26-electron-frontend-design.md`. Approved prototype: `docs/superpowers/specs/assets/final-ui.html`.

## Global Constraints

- Windows 11 only. Node 22, npm 11, Python 3.11 venv at `.venv`. No Rust or Visual Studio.
- **No network** at runtime except faster-whisper's one-time model download. No CDN fonts or scripts. The renderer CSP is `default-src 'self'; media-src 'self' app-audio:; style-src 'self' 'unsafe-inline'; img-src 'self' data:`.
- **Renderer security:**
  - `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`.
  - Renderers reach the engine only through an allow-listed set of commands in the main process.
- **The engine is the single source of truth for recording and mute state.** Every UI surface (main window, pill, tray) renders only what the engine's last `state` reports.
- **Protocol:**
  - UTF-8 JSON, one object per line.
  - Requests: `{"id","cmd","args"}`. Replies: `{"id","ok","result"|"error"}`. Events: `{"event","data"}`.
  - The engine's real stdout carries protocol only.
- **Folder arguments** coming from the renderer must resolve inside `settings.output_dir`. Anything else is rejected with `ok:false`.
- Existing behaviour is unchanged: capture, mixing, transcript format, queue pause while recording, crash-safe tracks.
- The existing 64 fast Python tests stay green. Python test command: `.venv/Scripts/python -m pytest -q -m "not slow"`. JS tests: `npm test --prefix desktop`.
- Copy and labels follow the prototype:
  - Mute button: "MUTED" / "LIVE". Pill: "Muted" / "Live".
  - Buttons: "● New recording" / "■ Stop recording", "Ready when your call starts".
  - No-mic warning: "No microphone found — recording Others only".
  - Model download: "Downloading speech model (first time only, ~480 MB)…".
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Mute set by the global hotkey while Teams has focus.** The main window, pill and tray must all flip within about 100 ms, because the hotkey path emits `state`. They must not drift.
2. **Electron crashes or is killed during a recording.** The engine sees stdin EOF, stops the recording, writes `meta.json` (end, devices, events), and exits. The meeting appears as "not transcribed".
3. **The engine process dies.** Pending `call()`s reject at once (no hung UI), the UI shows "Recording engine stopped unexpectedly — your audio so far is saved", and the engine is restarted.
4. **Stray output on stdout.** A library print or warning written to stdout must never corrupt the protocol. `sys.stdout` is redirected to stderr, and the protocol uses a private handle.
5. **Renderer paths, and non-ASCII titles.**
   - A crafted folder name or `app-audio://` URL that points outside the output folder (`..`, an absolute path) is refused.
   - A meeting title like "Café sync — Q4" round-trips through the pipes intact.

---

### Task 1: Packaging spike — freeze the engine and prove the frozen exe can record and transcribe

**Files:**
- Create: `teams_listener/selftest.py`
- Create: `packaging/engine_entry.py`
- Create: `packaging/engine.spec`
- Create: `requirements-build.txt` (`pyinstaller`)
- Modify: `.gitignore` (add `build/`, `dist/`, `desktop/node_modules/`, `desktop/dist/`, `desktop/build/engine-dist/`)
- Test: `tests/test_selftest.py`

**Interfaces:**
- Produces: `run_selftest(wav: Path | None, record_seconds: float, engine, list_outputs, get_mic) -> dict`. It returns `{"outputs": [names], "mic": name|None, "recorded_s": {"others": float, "me": float}, "text": str|None}`.
- Produces: `teams_listener.selftest.main(argv) -> int`. It prints the dict as one JSON line. Flags: `--wav PATH`, `--record-seconds N` (default 3), `--model NAME` (default `small.en`).
- Produces: `packaging/engine_entry.py`. With `--selftest` as the first argument it calls `selftest.main(argv[1:])`; otherwise it calls `teams_listener.__main__.main()`.

- [ ] **Step 1: Write the failing test.**

```python
def test_selftest_records_and_transcribes(tmp_path):
    from tests.test_recorder import FakeDevice, FakeClock
    from tests.test_pipeline import FakeEngine, O
    out = FakeDevice("a", "Speakers", 40); mic = FakeDevice("m", "Mic", 40)
    out.clock = mic.clock = FakeClock()
    r = run_selftest(Path("tests/fixtures/fox.wav"), 0.3, FakeEngine(others=[O(0, 1, "quick brown fox")]),
                     lambda: [out], lambda n: mic)
    assert r["outputs"] == ["Speakers"] and r["mic"] == "Mic"
    assert r["recorded_s"]["others"] > 0 and "fox" in r["text"]
```

  `run_selftest` records into a temp folder using `Recorder` with the given factories and transcribes `wav` with `engine.transcribe(wav, "Others", lambda f: None)`.

- [ ] **Step 2:** Run `.venv/Scripts/python -m pytest tests/test_selftest.py -q`. Expected: FAIL, ImportError.

- [ ] **Step 3: Implement `selftest.py`.**
  - `recorded_s` = the `.pcm` byte size / 2 / 16000, summed per kind.
  - `main` wires in the real `devices.list_output_loopbacks`, `devices.get_mic` and `WhisperEngine(model)`.

- [ ] **Step 4:** Run the test. Expected: PASS.

- [ ] **Step 5: Write `packaging/engine.spec`.**
  - One-folder build, `console=True` (Electron hides the window with `windowsHide`), name `teams-listener-engine`.
  - Collect with `collect_all`/`collect_data_files`: `faster_whisper` (includes the Silero VAD `.onnx` asset), `ctranslate2`, `soundcard`, `_soundfile_data`, `soxr`, `pycaw`, `comtypes`, `pynput`.
  - Hidden imports: `pynput.keyboard._win32`, `pynput.mouse._win32`, `comtypes.stream`.
  - Install with `.venv/Scripts/pip install -r requirements-build.txt`.

- [ ] **Step 6: Build and run the frozen exe.**
  - Build: `.venv/Scripts/pyinstaller packaging/engine.spec -y --distpath build/engine-dist --workpath build/pyi`
  - Run: `build/engine-dist/teams-listener-engine/teams-listener-engine.exe --selftest --wav tests/fixtures/fox.wav --record-seconds 3`
  - Expected: one JSON line. `outputs` is non-empty, `recorded_s.others` ≥ 2.5, and `text` contains "fox" (case-insensitive).
  - If it fails: add the missing hidden import or data to the spec and rebuild. Ledger each one as a ruling.

- [ ] **Step 7: Commit.** Message: `build: PyInstaller spike for the engine with a selftest`.

---

### Task 2: Meeting library helpers (transcript parsing, live time, search, details)

**Files:**
- Create: `teams_listener/library.py`
- Test: `tests/test_library.py`

**Interfaces:**
- Produces: `parse_transcript(text: str) -> list[dict]`.
  - Each item is `{"t": float_seconds, "ts": "HH:MM:SS", "speaker": "Others"|"Me", "text": str}`.
  - Header and `_No speech detected._` lines are ignored.
- Produces: `live_moments(events: list[dict], end_s: float) -> list[tuple[float, float]]`. These are the intervals where the mic was unmuted. An unmatched `unmute` closes at `end_s`.
- Produces: `search_meetings(output_dir: Path, query: str) -> list[dict]`, returning `[{"folder": str, "count": int}]`. It is a case-insensitive substring count over each `transcript.md`, skips empty queries, and returns only count > 0.
- Produces: `meeting_details(folder: Path) -> dict` with:
  - `folder, title, start (iso), end (iso|None), duration_s (float|None), model, devices`
  - `lines` (from `parse_transcript`, or `[]`)
  - `has_transcript`
  - `live_s` (the sum of `live_moments`) and `live_moments` (a list of `[a, b]`)
  - `audio` (`{"others": path, "me": path}`, or `None` when either FLAC is missing)
  - `audio_bytes` (int)
- Produces: `resolve_meeting(output_dir: Path, folder: str) -> Path`. It raises `ValueError` unless the resolved path is a direct child directory of the resolved `output_dir`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_parse_transcript_lines():
    md = "# T — 2026-11-25 10:00 (47 min)\n\n[00:00:12] **Others:** Morning everyone.\n\n[00:01:05] **Me:** Nice — café works.\n"
    assert parse_transcript(md) == [
        {"t": 12.0, "ts": "00:00:12", "speaker": "Others", "text": "Morning everyone."},
        {"t": 65.0, "ts": "00:01:05", "speaker": "Me", "text": "Nice — café works."}]

def test_parse_transcript_empty_meeting():
    assert parse_transcript("# T — x (1 min)\n\n_No speech detected._\n") == []

def test_live_moments_pairs_and_open_end():
    ev = [{"t": 5, "type": "unmute"}, {"t": 9, "type": "mute"}, {"t": 20, "type": "unmute"}]
    assert live_moments(ev, 30.0) == [(5, 9), (20, 30.0)]

def test_search_counts_case_insensitive(tmp_path):
    a = tmp_path / "2026-11-25_1000_A"; a.mkdir()
    (a / "transcript.md").write_text("[00:00:01] **Others:** Deploy on Friday. deploy!", encoding="utf-8")
    (tmp_path / "2026-11-24_1000_B").mkdir()
    assert search_meetings(tmp_path, "DEPLOY") == [{"folder": str(a), "count": 2}]
    assert search_meetings(tmp_path, "  ") == []

def test_meeting_details_without_audio(tmp_path):
    f = fake_meeting(tmp_path / "2026-11-25_1430_Standup")
    d = meeting_details(f)
    assert d["title"] == "Standup" and d["audio"] is None and d["has_transcript"] is False and d["duration_s"] == 3.0

def test_resolve_meeting_rejects_escape(tmp_path):
    (tmp_path / "m").mkdir()
    assert resolve_meeting(tmp_path, str(tmp_path / "m")) == (tmp_path / "m").resolve()
    for bad in ["..", str(tmp_path.parent), str(tmp_path / "m" / ".." / ".."), "C:\\Windows"]:
        with pytest.raises(ValueError): resolve_meeting(tmp_path, bad)
```

- [ ] **Step 2:** Run `.venv/Scripts/python -m pytest tests/test_library.py -q`. Expected: FAIL, ImportError.
- [ ] **Step 3: Implement `library.py`.**
  - Line regex: `^\[(\d{2}):(\d{2}):(\d{2})\] \*\*(Others|Me):\*\* (.*)$`, multiline.
  - Read files as UTF-8.
- [ ] **Step 4:** Run the tests. Expected: 6 passed.
- [ ] **Step 5: Commit.** Message: `feat: meeting library helpers for the new UI`.

---

### Task 3: Model-download stage in the transcription queue

**Files:**
- Modify: `teams_listener/transcribe/engine.py`
- Modify: `teams_listener/transcribe/pipeline.py`
- Test: `tests/test_pipeline.py` (append)

**Interfaces:**
- Produces: `WhisperEngine.needs_download() -> bool`.
  - Returns False if `model_path` is set.
  - Otherwise it tries `faster_whisper.utils.download_model(name, local_files_only=True)` and returns False on success, True on any exception.
- Produces: `TranscriptionQueue(..., on_stage: Callable[[Path, str], None] | None = None)`.
  - Before transcribing a job it calls `on_stage(folder, "model")` if the engine has `needs_download()` and it returns True.
  - It always calls `on_stage(folder, "transcribe")` right before `transcribe_meeting`.
  - Existing callers without `on_stage` still work.

- [ ] **Step 1: Write the failing test.**

```python
def test_queue_reports_model_stage_when_download_needed(tmp_path):
    class DL(FakeEngine):
        def needs_download(self): return True
    stages, done = [], threading.Event()
    q = TranscriptionQueue(lambda: DL(), lambda: Settings(), lambda *a: None,
                           lambda f, p: done.set(), lambda f, e: done.set(),
                           on_stage=lambda f, s: stages.append(s))
    q.submit(fake_meeting(tmp_path)); assert done.wait(10); q.shutdown()
    assert stages == ["model", "transcribe"]
```

- [ ] **Step 2:** Run `.venv/Scripts/python -m pytest tests/test_pipeline.py -q`. Expected: the new test FAILs (TypeError: unexpected keyword `on_stage`).
- [ ] **Step 3:** Implement both changes.
- [ ] **Step 4:** Run the full fast suite. Expected: all pass.
- [ ] **Step 5: Commit.** Message: `feat: report a model-download stage before first transcription`.

---

### Task 4: Controller — UI-free orchestration

**Files:**
- Create: `teams_listener/controller.py`
- Modify: `teams_listener/audio/recorder.py` (add the `output_names` property)
- Modify: `teams_listener/config.py` (add `theme: str = "system"`; allowed values `system|light|dark`; an invalid value resets to `system`)
- Test: `tests/test_controller.py`, `tests/test_recorder.py` (append), `tests/test_config.py` (append)

**Interfaces:**
- Consumes:
  - `Recorder`, `TranscriptionQueue(on_stage=…)` (Task 3)
  - `library.*` (Task 2)
  - `MuteHotkeys`, `load_settings`/`save_settings`
  - `make_meeting_dir`, `MeetingMeta`, `write_meta`, `list_meetings`, `read_meta`
- Produces: `Recorder.output_names -> list[str]`, the names of the currently active output devices.
- Produces the Controller class:
  ```
  Controller(emit: Callable[[str, dict], None],
             settings_path: Path | None = None,
             recorder_factory=None, queue_factory=None, hotkeys_factory=None,
             mic_lister=devices.list_mic_names, clock=time.monotonic)
  ```
  The defaults build the real objects, exactly as `ui/app.py` does today.
- Methods (all thread-safe; the hotkey thread may call `toggle_mute`):

  | Method | Returns / does |
  |---|---|
  | `status()` | `{recording, muted, title, folder, elapsed_s, mic, outputs, nomic}` |
  | `start(title: str)` | Returns `status()`. Raises `RuntimeError` if already recording. Same steps as `App.start_recording`, including `queue.pause()`. Title defaults to "Meeting". |
  | `stop()` | Returns `{"folder": str}`. Same steps as `App.stop_recording`, then submits to the queue. |
  | `set_muted(muted: bool)`, `toggle_mute()` | Each emits `state`. |
  | `list_meetings()` | Items: `{folder, title, start, duration_s, status, progress}`. `status` is one of `recording`, `queued`, `transcribing`, `transcribed`, `not transcribed`. |
  | `get_meeting(folder)` | `meeting_details(resolve_meeting(...))` |
  | `search(query)` | Search results (see Task 2) |
  | `transcribe_again(folder)` | Same rules as `App.transcribe_again`. Raises `RuntimeError("This meeting is still recording.")`. |
  | `get_settings()` | The settings as a dict |
  | `save_settings(d: dict)` | Validates the hotkey with `HotKey.parse` (`ValueError` → error reply), saves, restarts hotkeys, emits `meetings_changed` |
  | `list_mics()` | Mic names |
  | `poll()` | Called about every 100 ms. While recording it emits `levels {others, me}`, and emits `state` when `mic_name` or `output_names` changed. |
  | `shutdown()` | Stops any recording (writing meta), stops hotkeys, shuts down the queue |

- Events emitted:
  - `state` (the `status()` dict) on start, stop, mute change and device change.
  - `progress {folder, frac, eta_s, stage}`; the stage comes from the queue's `on_stage`, and frac/eta from `on_progress`.
  - `transcribed {folder}`, `error {folder, message}`, `meetings_changed` (after start, stop, done, error, submit).

- [ ] **Step 1: Write the failing tests** in `tests/test_controller.py`. Use a `FakeRecorder` (records `muted`, `start`/`stop` calls, `levels`, `mic_name`, `output_names`, and `stop()` returning a `RecordingSummary`), a `FakeQueue` (`submit`, `pause`, `resume`, `busy`, and the callbacks captured), and a no-op hotkeys factory. Tests:
  - `test_start_writes_meta_pauses_queue_and_emits_state`: after `start("Café sync — Q4")`, `meta.json` has that title, `queue.paused` is True, and the last event is `("state", {... "recording": True, "muted": True})`.
  - `test_start_twice_raises`.
  - `test_stop_writes_end_events_and_submits`: `meta.end` is set, `meta.events` equals the summary events, `queue.submitted == [folder]`, the queue is resumed, and `meetings_changed` is emitted.
  - `test_toggle_mute_from_any_thread_emits_state`: call `toggle_mute` from a `threading.Thread`; the recorder is unmuted and a `state` event with `muted: False` is emitted.
  - `test_poll_emits_levels_and_state_on_mic_change`.
  - `test_list_meetings_marks_recording_and_transcribing`.
  - `test_get_meeting_rejects_outside_folder` (raises `ValueError`).
  - `test_transcribe_again_refuses_recording_folder`.
  - `test_progress_event_carries_stage`: fire `on_stage(folder, "model")`, then `on_progress(folder, 0.0, None)`, and expect `progress` with `stage: "model"`.
  - `test_shutdown_while_recording_saves_meta`.
  - In `test_recorder.py`, `test_output_names_lists_active`. In `test_config.py`, `test_invalid_theme_resets`.
- [ ] **Step 2:** Run `.venv/Scripts/python -m pytest tests/test_controller.py tests/test_recorder.py tests/test_config.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement `Controller` (port the logic from `ui/app.py`; keep the Tk app working), `output_names` and `theme`.
- [ ] **Step 4:** Run the full fast suite. Expected: all pass.
- [ ] **Step 5: Commit.** Message: `feat: UI-free Controller (start/stop/mute/meetings/settings) with events`.

---

### Task 5: JSON-lines engine server

**Files:**
- Create: `teams_listener/server.py`
- Modify: `teams_listener/__main__.py` (default runs the server; `--tk` runs the old Tk `App`)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: the `Controller` (Task 4).
- Produces: `Server(controller_factory: Callable[[Callable[[str, dict], None]], Controller], inp: TextIO, out: TextIO, poll_interval: float = 0.1)`.
  - `.serve()` blocks until stdin EOF or a `quit` command, then calls `controller.shutdown()`.
  - `.handle(line: str) -> dict | None` returns the reply.
  - Writes are serialised with a lock; each message is one line plus a flush.
- Commands map 1:1 to Controller methods. Allow-list: `status, start, stop, set_muted, toggle_mute, list_meetings, get_meeting, search, transcribe_again, get_settings, save_settings, list_mics, quit`.
  - An unknown command gives `ok:false, error:"unknown command: X"`.
  - Any exception gives `ok:false, error:str(e)`.
  - Invalid JSON gives `{"id": null, "ok": false, "error": "bad request"}`.
- A background thread calls `controller.poll()` every `poll_interval` seconds.
- `main()`:
  - Sets up logging to `app.log` as `__main__` does today.
  - Builds the protocol streams with `io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")` and `io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")`.
  - Then sets `sys.stdout = sys.stderr`, logs `server started (frozen=<sys.frozen>)`, and calls `Server(Controller, inp, out).serve()`.

- [ ] **Step 1: Write the failing tests** with a `FakeController` that records calls.
  - `test_reply_matches_id`: `{"id":7,"cmd":"status"}` gives `{"id":7,"ok":true,"result":{...}}`.
  - `test_unknown_command_and_bad_json`.
  - `test_exception_becomes_error_reply`.
  - `test_events_are_written_as_lines`: the controller emits from another thread, and the output contains `{"event":"state",...}` on its own line.
  - `test_eof_shuts_down_controller`: `serve()` on `io.StringIO('{"id":1,"cmd":"status"}\n')` returns, and `shutdown` was called.
  - `test_utf8_title_round_trip`: `start` with "Café sync — Q4" over `io.TextIOWrapper(io.BytesIO(...), encoding="utf-8")`; the fake receives the exact string.
  - `test_main_redirects_stray_prints`: call `main()` with patched streams; a `print("noise")` inside the fake controller's `status` must not appear in the protocol output.
- [ ] **Step 2:** Run `.venv/Scripts/python -m pytest tests/test_server.py -q`. Expected: FAIL, ImportError.
- [ ] **Step 3:** Implement `server.py` and the `__main__` switch.
- [ ] **Step 4:** Run the full fast suite. Expected: all pass. Then a manual check: `echo {"id":1,"cmd":"status"} | .venv/Scripts/python -m teams_listener`. Expected: one reply line, `"recording": false`, and the process exits on EOF.
- [ ] **Step 5: Commit.** Message: `feat: JSON-lines engine server; python -m teams_listener runs it (--tk for the old UI)`.

---

### Task 6: Electron scaffold, engine client and secure bridge

**Files:**
- Create: `desktop/package.json`
  - Scripts: `start` = `electron .`, `test` = `node --test test/`, `dist` (Task 10).
  - devDependencies: `electron`, `electron-builder`.
- Create: `desktop/src/engine.js`, `desktop/src/paths.js`, `desktop/src/preload.js`
- Create: `desktop/src/main.js` (minimal: single-instance lock, one window loading `renderer/index.html` with a placeholder, IPC wiring)
- Test: `desktop/test/engine.test.js`, `desktop/test/paths.test.js`

**Interfaces:**
- Produces: `class EngineClient extends EventEmitter` in `engine.js`, constructed as `new EngineClient({ spawn, command, args, env, restartDelayMs = 1000 })`.
  - `start()` spawns with `{ windowsHide: true, stdio: ['pipe','pipe','pipe'], env: {...env, PYTHONIOENCODING:'utf-8', PYTHONUNBUFFERED:'1'} }`.
  - `call(cmd, args = {}) -> Promise<result>`. It rejects with `Error(error)` on `ok:false`, and with `Error('engine stopped')` for every pending call when the child exits.
  - Emits `'event'(name, data)` for event lines, `'exit'(code)` on exit, and `'ready'` after the first successful `status` reply.
  - It restarts after an unexpected exit, but not after `stop()`.
  - It splits stdout on `\n` across chunk boundaries, and logs and ignores non-JSON lines.
- Produces: `resolveEngine({ isPackaged, resourcesPath, repoRoot }) -> { command, args }` in `paths.js`.
  - Packaged: `resourcesPath/engine/teams-listener-engine.exe` with `[]`.
  - Development: `repoRoot/.venv/Scripts/python.exe` with `['-m','teams_listener']`.
- Produces: `resolveAudio(outputDir, url) -> string | null` in `paths.js`. It maps `app-audio://meeting/<encodeURIComponent(folderName)>/<others|me>.flac` to an absolute path, and returns null for anything else or anything outside `outputDir`.
- Produces `preload.js`, which exposes `window.api`:
  - `call(cmd, args)` → `ipcRenderer.invoke('engine:call', cmd, args)`. The main process checks the same allow-list as the server, minus `quit`.
  - `on(name, fn)` subscribes to `'engine:event'`, and returns an unsubscribe function.
  - `ui(action, payload)` → `ipcRenderer.invoke('ui', action, payload)`. Actions: `minimiseToPill`, `restore`, `copyText`, `exportMarkdown`, `openFolder`, `pickFolder`.

- [ ] **Step 1: Write the failing tests.**
  - `engine.test.js`, using a fake spawn that returns an EventEmitter with PassThrough stdin/stdout/stderr:
    - `call resolves by id` (two calls answered out of order).
    - `ok:false rejects`.
    - `events emitted`.
    - `line split across chunks`.
    - `exit rejects pending and restarts` (the fake spawn is called twice).
    - `stop() does not restart`.
  - `paths.test.js`:
    - The packaged and development engine paths.
    - `resolveAudio` accepts `app-audio://meeting/2026-11-25_1000_Design-review/me.flac`.
    - It rejects `..%2F..%2FWindows`, `other.flac`, and the wrong host.
- [ ] **Step 2:** Run `cd desktop && npm install && npm test`. Expected: FAIL (modules missing).
- [ ] **Step 3: Implement** `engine.js`, `paths.js`, `preload.js` and the minimal `main.js`.
  - The main process forwards engine events to every BrowserWindow.
  - It registers the `app-audio` scheme as privileged (`stream: true, supportFetchAPI: true`) and serves it with `protocol.handle`. Files go through `net.fetch(pathToFileURL(p))`, which supports Range, so seeking works.
  - `outputDir` comes from `get_settings` and is refreshed on `meetings_changed`.
- [ ] **Step 4:** Run `npm test`. Expected: all pass. Then run `npm start`. Expected: the window opens, and the log shows `ready`.
- [ ] **Step 5: Commit.** Message: `feat(desktop): Electron scaffold, engine client, secure preload bridge`.

---

### Task 7: Main window UI (sidebar + Idle / Recording / Transcribing / Transcript views)

**Files:**
- Create: `desktop/renderer/index.html`, `desktop/renderer/app.css`, `desktop/renderer/app.js`
- Create: `desktop/renderer/lib/ui-helpers.js`. It is UMD-style: it sets `window.TL` in the browser and `module.exports` in Node.
- Modify: `desktop/src/main.js` (window options: `titleBarStyle:'hidden'`, `titleBarOverlay` colours from the theme, `backgroundMaterial:'mica'`, `minWidth 900`, `minHeight 600`; smoke mode)
- Test: `desktop/test/ui-helpers.test.js`

**Interfaces:**
- Consumes: `window.api` (Task 6) and the engine commands and events (Tasks 4–5).
- Produces these helpers in `ui-helpers.js`:
  - `groupMeetings(list, now: Date) -> [{label, items}]`. Labels are "Now", "Today", "Yesterday", "This week" and "Older". Recording, queued and transcribing meetings go under "Now".
  - `fmtClock(sec, short=false)`: `"00:12:43"`, or `"12:43"` when short.
  - `fmtEta(sec|null)`: `"estimating…"`, `"About N min left"` or `"Less than a minute left"`.
  - `highlight(text, query) -> html`. It escapes `& < > " '` first, then wraps case-insensitive matches in `<mark>`. The query is regex-escaped.
  - `statusDot(status)`: a CSS variable name.
  - `timelineSegments(moments, total) -> [{leftPct, widthPct}]`, with a minimum width of 0.8%.
- Smoke mode: when the env var `TL_SMOKE=<png path>` is set, the main process waits for the renderer's `ui('smokeReady')` (sent after the first `list_meetings` render), writes `capturePage()` to that path, and quits with code 0.

- [ ] **Step 1: Write the failing tests** in `ui-helpers.test.js`:
  - `groupMeetings` with fixed `now`: a meeting from 2026-11-26 10:00 is "Today", one from 11-25 is "Yesterday", one from 11-21 is "This week", one from 11-01 is "Older", and a transcribing one is "Now".
  - `fmtClock(763) === "00:12:43"` and `fmtClock(763, true) === "12:43"`.
  - `highlight('<b>Deploy</b> deploy', 'deploy')` contains `&lt;b&gt;<mark>Deploy</mark>&lt;/b&gt; <mark>deploy</mark>`.
  - `highlight('a+b', '+')` does not throw.
  - `timelineSegments([[0, 1]], 1000)[0].widthPct === 0.8`.
- [ ] **Step 2:** Run `npm test --prefix desktop`. Expected: FAIL.
- [ ] **Step 3: Implement the helpers, then port the prototype** (`docs/superpowers/specs/assets/final-ui.html`) into `index.html`, `app.css` and `app.js`, wired to the engine.
  - Theme uses CSS variables under `@media (prefers-color-scheme: dark)`, with `body` transparent so Mica shows through. The prototype's demo-only controls (Reset, the fake call background) are removed.
  - **Sidebar:**
    - The big button calls `start`/`stop`.
    - The search input is debounced to 200 ms, calls `search`, and shows "N matches" on matching items. Ctrl+K focuses it.
    - Clicking an item calls `get_meeting` and opens the Transcript view, or the Transcribing view if it is queued or transcribing.
  - **Recording view:**
    - Driven only by `state` and `levels` events. The mute button calls `toggle_mute`.
    - Meters: 22 bars, with the height derived from the level and a little random jitter.
    - The timeline uses `live_moments` built locally from mute transitions seen in `state` events since start.
    - When `nomic` is true: an amber button labelled "No microphone found — recording Others only", disabled.
  - **Transcribing view:** the ring shows `progress.frac`. When `stage === "model"` it shows the model-download text with an indeterminate ring. While recording it shows "Paused while recording".
  - **Transcript view:**
    - Lines are rendered with `highlight`. Tabs: Transcript, Only my lines, Details (devices, `live_s`, model, folder, audio size).
    - The player (two `<audio>` elements, `others` and `me`, kept in sync on play, pause and seek) is hidden when `audio` is null. Clicking a timestamp seeks both.
    - Toolbar actions: `copyText` (plain `[ts] Speaker: text` lines), `exportMarkdown`, `openFolder`, `transcribe_again`.
  - **Errors:** a failed `call` shows a toast with the error text for 5 s. The `error` event shows a toast. An engine exit shows a banner "Recording engine stopped unexpectedly — your audio so far is saved".
- [ ] **Step 4: Verify.**
  - Run `npm test --prefix desktop`. Expected: all pass.
  - Then run `TL_SMOKE=$SCRATCH/main.png npm start --prefix desktop` and read the PNG. Expected: the sidebar with the real meetings from `Documents\TeamsTranscripts`, and the Mica window.
  - Manual: Start → toggle mute (button and Ctrl+Alt+M) → Stop → progress → transcript opens, search highlights, audio plays and seeks.
- [ ] **Step 5: Commit.** Message: `feat(desktop): main window — sidebar, recording, transcribing and transcript views`.

---

### Task 8: Pill window, tray, and window lifecycle

**Files:**
- Create: `desktop/renderer/pill.html`, `desktop/renderer/pill.css`, `desktop/renderer/pill.js`
- Create: `desktop/src/tray.js`, `desktop/src/ui-state.js`
- Modify: `desktop/src/main.js`
- Test: `desktop/test/ui-state.test.js`, `desktop/test/tray.test.js`

**Interfaces:**
- Produces: `loadUiState(file) -> {pill: {x, y} | null}` and `saveUiState(file, state)`. A corrupt file falls back to the defaults. The file lives at `app.getPath('userData')/ui-state.json`.
- Produces: `trayModel(state) -> {colour: 'idle'|'muted'|'live'|'nomic', tooltip, items: [{id, label, enabled}]}`.
  - Items: `show` "Show", `startStop` "Start recording"/"Stop recording", `mute` "Unmute mic"/"Mute mic" (enabled only while recording), `quit` "Quit".
  - Tooltip strings are the same as v1 `_MIC_STYLE`.
- Pill window:
  - 340×44, `frame:false`, `transparent:true`, `resizable:false`, `skipTaskbar:true`, `alwaysOnTop` at level `'floating'`.
  - Draggable via `-webkit-app-region: drag`, with buttons set to `no-drag`.
  - The position is saved on `moved`. The default position is top-centre of the primary display.
- Tray icons: four 16×16/32×32 PNGs generated once by `packaging/make_icons.py` (Pillow, same glyph as `ui/tray.py`) into `desktop/assets/`.
- Lifecycle rules (spec):
  - While recording, minimising, `minimiseToPill` or closing the main window hides it and shows the pill.
  - Closing while recording first asks with `dialog.showMessageBox`. The buttons are "Stop and save", "Keep recording in the tray" and "Cancel", the same as v1.
  - `restore` shows and focuses the main window and hides the pill. `stop` from the pill also restores.
  - When not recording, closing hides the window to the tray.
  - Tray Quit: if recording, confirm "Stop the recording, save it and quit?". If the queue is busy, confirm "A transcription is still running. Quit anyway?". Then `engine.call('quit')`, then `app.exit()`.
  - Second instance: show and focus the main window.

- [ ] **Step 1: Write the failing tests:**
  - `ui-state`: round-trip, missing file, corrupt JSON.
  - `trayModel`: idle, muted, live, nomic, and the mute item disabled when idle.
- [ ] **Step 2:** Run `npm test --prefix desktop`. Expected: FAIL.
- [ ] **Step 3: Implement** the pill (timer, mini meter, Muted/Live toggle calling `toggle_mute`, ⤢ restore, ■ stop; all rendered from `state` and `levels` events), the tray and the lifecycle in `main.js`.
- [ ] **Step 4: Verify.**
  - Run `npm test`. Expected: pass.
  - Manual: start recording → minimise → the pill appears over Teams → drag it → Ctrl+Alt+M flips the pill, main window and tray together → ⤢ restores → restart the app → the pill is in the same place. Closing while recording shows the three-button dialog.
- [ ] **Step 5: Commit.** Message: `feat(desktop): floating pill, tray, close/minimise lifecycle, single instance`.

---

### Task 9: Settings dialog and theme

**Files:**
- Modify: `desktop/renderer/index.html`, `app.css`, `app.js` (modal dialog)
- Modify: `desktop/src/main.js` (`nativeTheme.themeSource`, titleBarOverlay colours on `nativeTheme` `updated`)
- Test: `desktop/test/ui-helpers.test.js` (append)

**Interfaces:**
- Consumes: `get_settings`, `save_settings`, `list_mics`, and `ui('pickFolder')`.
- Produces: the `settingsFromForm(form) -> dict` helper in `ui-helpers.js`.
  - It maps the "Default communications mic" choice to `mic_device: null`, trims strings, and leaves an empty `model_path` as `null`.
- Fields, with v1 labels and help text: Transcription model (small.en / medium.en), Model folder (optional), Microphone, Mute shortcut, the "Also toggle when Teams' Ctrl+Shift+M is pressed…" checkbox, "Delete audio after a successful transcription", "Save meetings in", Theme (System / Light / Dark).
- An error reply from `save_settings` (an invalid hotkey) is shown inline under the shortcut field, and the dialog stays open.
- Saving the theme sets `nativeTheme.themeSource` at once. On startup the main process applies `get_settings().theme`.

- [ ] **Step 1: Write the failing test:** `settingsFromForm` maps the default mic to `null`, an empty model folder to `null`, and keeps `theme: "dark"`.
- [ ] **Step 2:** Run `npm test --prefix desktop`. Expected: FAIL.
- [ ] **Step 3:** Implement the dialog, the theme switch and the `pickFolder` IPC (`dialog.showOpenDialog`, `openDirectory`).
- [ ] **Step 4: Verify.**
  - Run `npm test`. Expected: pass.
  - Manual: switch the theme between Light, Dark and System, and check that the title bar buttons recolour. Enter the invalid hotkey `ctrl+` and check the inline error. Change the mic, then check the next recording's chip shows it.
- [ ] **Step 5: Commit.** Message: `feat(desktop): settings dialog and light/dark/system theme`.

---

### Task 10: Installer build, launcher and docs

**Files:**
- Modify: `packaging/engine.spec` (entry is now the server via `engine_entry.py`; the selftest flag stays)
- Modify: `desktop/package.json`
  - `build` config:
    - `appId: "local.teamslistener"`, `productName: "Teams Listener"`
    - `win.target: nsis`, `win.icon: assets/icon.ico`
    - `nsis: { oneClick: true, perMachine: false, createDesktopShortcut: true }`
    - `extraResources: [{ from: "build/engine-dist/teams-listener-engine", to: "engine" }]`
    - `files: ["src/**", "renderer/**", "assets/**", "package.json"]`
  - Scripts:
    - `build:engine` = `..\\.venv\\Scripts\\pyinstaller ..\\packaging\\engine.spec -y --distpath build\\engine-dist --workpath ..\\build\\pyi`
    - `dist` = `npm run build:engine && electron-builder --win`
- Modify: `packaging/make_icons.py` (also writes `desktop/assets/icon.ico` at 256/64/32/16)
- Modify: `run.bat` → `cd /d "%~dp0desktop" && start "" "node_modules\.bin\electron.cmd" .`
- Modify: `README.md` (install from `desktop\dist\Teams Listener Setup *.exe`, the SmartScreen note, development run, `npm run dist`, the `--tk` fallback, first-run model download)
- Test: `desktop/test/paths.test.js` (already covers the packaged path; no new code paths)

- [ ] **Step 1:** Run `npm run dist --prefix desktop`. Expected: `desktop/dist/Teams Listener Setup <version>.exe` exists, about 150 MB or less.
- [ ] **Step 2:** Run `"desktop/build/engine-dist/teams-listener-engine/teams-listener-engine.exe" --selftest --wav tests/fixtures/fox.wav`. Expected: `text` contains "fox".
- [ ] **Step 3: Install and smoke-test the installed app.**
  - Run the installer, then `TL_SMOKE=$SCRATCH/installed.png "%LOCALAPPDATA%\Programs\Teams Listener\Teams Listener.exe"`.
  - Expected: the PNG shows real meetings. The engine runs from `resources\engine` (check `app.log` for `server started`, logged by `server.main`).
- [ ] **Step 4:** Do a manual end-to-end run with the installed app: record 30 s with speech playing, unmute and speak, stop, wait for the transcript, then check the lines, the "Only my lines" tab and audio playback.
- [ ] **Step 5:** Run both suites. Expected: all pass.
- [ ] **Step 6: Commit.** Message: `build: one-command Windows installer; launcher and README for the Electron app`.
