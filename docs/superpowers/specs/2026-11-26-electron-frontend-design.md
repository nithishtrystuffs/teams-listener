# Teams Listener — Electron front end — Design

**Date:** 2026-11-26
**Status:** Approved by the user, with mockups (prototype: `.superpowers/brainstorm/1166-1795690007/content/final-ui.html`, git-ignored; a copy is kept in `docs/superpowers/specs/assets/final-ui.html`)
**Builds on:** `2026-11-25-teams-listener-design.md`

## Intent

v1 works well in real Teams calls (verified by the user), but the Tkinter window "is not good enough". The user wants a modern, polished app window. The Python engine (capture, Bluetooth hot-plug, crash-safe tracks, Whisper, queue, hotkey) **stays as it is**. Only the front end is replaced.

## Goals

- Replace the Tkinter UI with an Electron app that matches the approved prototype.
- **One window**, with a sidebar of meetings and four views: Idle, Recording, Transcribing, Transcript.
- **Windows 11 look:**
  - Mica background, Segoe UI Variable, native title bar controls.
  - Light/dark follows Windows; a Settings override offers System, Light or Dark.
- **Recording view:**
  - A big round mute button: red with a glow when muted, green with a glow when live. Click it or press Ctrl+Alt+M.
  - Live bar meters for Others and Me, plus device chips for the output device and the mic.
  - A timer and a "when you were live" timeline strip.
  - Buttons: "Minimise to pill" and "Stop & transcribe".
  - The amber "No microphone found — recording Others only" state is kept, rendered in the new style.
- **Floating pill:**
  - A small, frameless, always-on-top, draggable window.
  - Shows the recording dot, timer, mini meter, a Mute/Live toggle, ⤢ to restore the main window, and ■ to stop.
  - Its position is remembered between sessions.
- **Transcript view:**
  - Each line shows timestamp, avatar, speaker name (Others/Me in different colours) and text.
  - Toolbar: Copy all, Export .md (save dialog), Open folder, Transcribe again.
  - An audio player for the meeting audio. Clicking a timestamp seeks the player.
  - Tabs: Transcript, Only my lines, Details. Details shows the devices, how long I was live (from mute events), model, folder and audio size.
- **Sidebar:**
  - Big button: "● New recording", which becomes "■ Stop recording" while recording.
  - Search across all transcripts (Ctrl+K). Matching meetings show a match count; matches are highlighted in the open transcript.
  - Meetings are grouped Today / Yesterday / This week / Older.
  - Each meeting has a status dot: green = transcribed, accent = transcribing (with a progress bar), grey = not transcribed, red = recording.
  - The footer has Settings and shows the model and "offline".
- **Transcribing view:** a progress ring, percentage and ETA. The rest of the app stays usable.
- **Settings dialog:** the same fields as v1, plus Theme.
  - v1 fields: model, mic device, hotkey, follow Teams shortcut, delete audio after transcription, output folder.
- **Tray icon:** coloured by state, with the same menu as v1.
- Closing the window keeps the app in the tray. If a recording is running, it asks first, as v1 does.
- **Single instance:** a second launch focuses the existing window. This also fixes a deferred v1 minor.

- **When the pill appears:**
  - While recording, the pill shows whenever the main window is minimised or hidden to the tray: through the "Minimise to pill" button, the title bar "—", or closing to the tray.
  - Restoring the main window hides the pill.
  - When not recording, minimising behaves normally.
- **Title bar:** `titleBarStyle: 'hidden'` with `titleBarOverlay`, so Windows draws the real minimise, maximise and close buttons over our Mica background.

## Non-goals

- Live transcript during the call. The laptop's CPU can't do it; transcription stays after the call.
- Bundling Python into an installer. The app runs from the repo with the existing `.venv`.
- Changes to capture, mixing, transcription quality or the transcript file format.
- macOS or Linux.
- Copying the branding or look of any real product. The design is our own.

## Anti-goals

- **The mute state must never be ambiguous.** If the UI, pill, tray and engine disagree, that is a failure even if the UI looks nice. The engine is the single source of truth, and every surface renders what the engine reports.
- **A UI crash must never lose a recording.** If Electron dies, the engine keeps recording or stops cleanly. If the engine dies, the crash-safe tracks remain and the meeting appears as "not transcribed".
- **No network.** Nothing is loaded from the internet: no CDN fonts or scripts, and a CSP that blocks remote content.

## Constraints

- Machine: Windows 11, i5-8365U, no GPU, 16 GB RAM, Node 22.16 and npm 11 available, no Rust or Visual Studio. Python 3.11 venv at `.venv`.
- Electron, current stable. Plain HTML/CSS/JS in the renderer, with no front-end framework (the prototype is vanilla and small).
- Renderer security:
  - `contextIsolation: true`, `nodeIntegration: false`.
  - A preload script exposes a narrow `window.api`.
  - Strict CSP.
- Python engine changes must keep the existing 64 fast tests green, and the new engine code must be test-first.

## Approaches considered (front end)

1. **WPF on .NET 9 with the Fluent theme.** Native and light, and it builds with the installed SDK. Not chosen: the user picked the web-based option.
2. **WinUI 3.** The most "Windows 11" look, but heavy tooling without Visual Studio. Not chosen.
3. **Web UI (Tauri or Electron). Chosen by the user.** Within it:
   - **Electron:** Node is installed, and it is mature on Windows. Mica works through `backgroundMaterial`, and tray, frameless windows and always-on-top are built in. Cost: about 150 MB.
   - **Tauri:** 5 MB, but it needs Rust plus the MSVC Build Tools (several GB), and its tray and Mica support are less direct.
   - **Pick: Electron** (my call, stated to the user).

## Architecture (decided)

```
Electron main process ──spawn──► .venv\Scripts\python.exe -m teams_listener.server
   │  ▲   stdin: JSON-lines commands   stdout: JSON-lines replies + events
   │  └── (stderr → app.log)
   ├── main window (renderer: sidebar + views)     ◄─ IPC via preload window.api
   ├── pill window (renderer: pill.html)           ◄─ same window.api
   └── Tray
```

### Python side: new module `teams_listener/server.py`

- It is a headless replacement for `ui/app.py`. It reuses `Recorder`, `TranscriptionQueue`, `MuteHotkeys`, `config`, `meeting` and `pipeline` unchanged.
- `ui/app.py`'s orchestration logic (start, stop, meta writes, queue pause/resume, submit) moves into a UI-free class `Controller` in `teams_listener/controller.py`, so it can be tested with fakes. `server.py` is only the JSON-lines transport around `Controller`.

**Protocol**

- One JSON object per line, in both directions.
- A request looks like `{"id": n, "cmd": "...", "args": {...}}`.
- A reply looks like `{"id": n, "ok": true, "result": ...}` or `{"id": n, "ok": false, "error": "message"}`.
- Events look like `{"event": "...", "data": {...}}`.

**Commands**

| Command | Purpose |
|---|---|
| `status` | Recording? muted, title, elapsed, mic name, devices |
| `start {title}` | Start a recording |
| `stop` | Stop the recording; the meeting is submitted to the queue |
| `set_muted {muted}` | Mute or unmute the mic |
| `list_meetings` | Folder, title, start, duration, status, progress |
| `get_meeting {folder}` | Meta, parsed transcript lines `[{t, speaker, text}]`, live seconds, audio path(s) or null, audio size |
| `search {query}` | `[{folder, count}]`, case-insensitive over `transcript.md` |
| `transcribe_again {folder}` | Re-run transcription |
| `get_settings` / `save_settings {…}` | Read or write settings |
| `list_mics` | Mic names for the Settings dialog |
| `quit` | Shut down the engine |

**Events**

| Event | When |
|---|---|
| `levels {others, me}` | About 10 per second while recording |
| `state {...same as status}` | On any change: start, stop, mute (including from the hotkey), mic switch |
| `progress {folder, frac, eta_s}` | During transcription |
| `transcribed {folder}` | Transcription finished |
| `error {folder?, message}` | Something failed |
| `meetings_changed` | The meetings list changed |

- **Transcript parsing:** `get_meeting` parses the existing `transcript.md` format (`[HH:MM:SS] **Speaker:** text`). Old transcripts therefore work with no format change.
- **Hotkey:** stays in Python, as pynput listen-only, so the keys still reach Teams. A hotkey toggle changes `Recorder.muted` and emits `state`.
- **stdout discipline:** stdout carries protocol only. All logging goes to `app.log`, and stray prints are redirected to stderr.
- **Engine exit:** if stdin closes (Electron died), the engine stops any recording cleanly (writes meta), then exits.
- **Audio for playback:**
  - `others.flac` and `me.flac` exist after transcription unless "delete audio" is on.
  - The player plays both together as two synced `<audio>` elements, which is the simplest option.
  - If the audio is gone, the player is hidden.
  - Files are served to the renderer through a custom `app-audio://` protocol limited to the output folder, never through arbitrary file access.

### Electron side: new folder `desktop/`

| File | Responsibility |
|---|---|
| `main.js` | App lifecycle, single-instance lock, windows, tray, engine process |
| `engine.js` | Spawns Python, matches request ids to replies, forwards events, restarts the engine if it dies |
| `preload.js` | Exposes `window.api.call(cmd, args)` and `window.api.on(event, fn)`, plus window controls (minimise to pill, restore, save file, open folder, copy) |
| `renderer/index.html`, `app.css`, `app.js` | Main window, ported from the approved prototype |
| `renderer/pill.html`, `pill.js` | The pill window |
| `renderer/lib/*.js` | Pure helpers: grouping meetings by date, formatting times, live segments from events, search highlighting. Unit-tested with `node --test` |

**Launching**

- `run.bat` starts `desktop\node_modules\.bin\electron.cmd desktop`.
- The engine path is resolved relative to the repo root.
- The Tkinter UI stays in the repo as a fallback (`python -m teams_listener --tk`) until the Electron UI is verified in a real call. Removing it is a later, separate change.

## Error handling

- **The engine fails to start** (for example, the venv is missing): the window shows a clear message with the path it tried, and the log location.
- **The engine dies mid-recording:**
  - The UI shows "Recording engine stopped unexpectedly — your audio so far is saved".
  - It restarts the engine, and the meeting appears in the list as "not transcribed", with Transcribe again available.
- **A command fails:** a toast with the error message appears; the UI does not freeze.

## Left to the builder

- Exact spacing, colours and animation details, as long as they match the prototype's look.
- Whether `Controller` events are callbacks or a queue.
- How the pill's position is persisted (Electron store file in userData).
- The Electron version (current stable at build time).

## Calls I made (for the user to check)

1. **Electron over Tauri,** because Node is already installed and Tauri needs Rust plus several GB of build tools.
2. **The Tkinter UI is kept as a fallback for now,** removed later once the new UI is proven in a call.
3. **The audio player plays the Others and Me tracks together;** there is no separate mixed file.
4. **The app runs from the repo** (`run.bat`). There is no installer and Python is not bundled.
5. **The mic-lookup fix commits** that missed PR #1 ride along on this branch.
