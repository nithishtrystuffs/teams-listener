# Teams Listener — Design

Date: 2026-11-25
Status: Draft, awaiting approval

## Intent

A personal tool that produces a complete, timestamped transcript of the Microsoft Teams
meetings the user attends, running entirely on their own Windows laptop. It is for the user's
own reference (notes and recall), not for sharing or compliance. It must work regardless of
what Teams transcription the user's organization allows, and no meeting audio may leave the
machine.

## Goals

- One click to start recording when a meeting begins and one to stop when it ends.
- Capture both sides: what the PC plays ("Others") and the user's microphone ("Me").
- Work with speakers, wired headphones and **Bluetooth headphones**, including devices that
  connect, disconnect or switch Bluetooth mode (Stereo ↔ Hands-Free) mid-meeting.
- Transcribe offline after the meeting, with progress shown, producing a readable Markdown
  transcript labelled **Me** / **Others** with timestamps.
- Recording must not noticeably slow down Teams on this laptop.

## Non-goals (for v1)

- Joining meetings as a bot or using the Teams/Graph APIs.
- Cloud transcription or any upload.
- Live transcription during the meeting.
- Summaries or action items (possible later, built on the transcript file).
- Telling individual remote speakers apart (planned as v2, see Later).
- Detecting Teams calls automatically.

## Anti-goals (a failure even if it works)

- Audio or transcripts sent anywhere off the machine.
- Losing a meeting's audio because of a device switch, a crash or closing the app.
- Making the Teams call stutter or lag while recording.

## Constraints

- **Hardware:** Intel Core i5-8365U (4 cores/8 threads), Intel UHD 620 (no CUDA GPU), 16 GB RAM,
  about 45 GB free on D:. Windows 11 Pro.
- **Runtime:** Python 3.11.9 is installed.
- **Network:** an internet connection is needed once, to download the Whisper model (small is
  about 0.5 GB, medium about 1.5 GB) from Hugging Face. A corporate proxy may block this; the app
  must also accept a manually downloaded model folder.
- **Language:** all meetings are in English.
- **Teams client:** must work with Teams desktop or browser, since capture happens at the
  Windows audio level, not inside Teams.

## Approaches considered

1. **Teams' built-in transcription.** No build needed, and it gives real speaker names. But it
   depends on organization policy and the user's role in each meeting. Recommended as something to
   try in parallel, but it doesn't meet the "always works" goal.
2. **Local desktop app with offline Whisper transcription.** ← **Chosen.** Private, free, and
   independent of Teams settings. Me/Others separation is reliable because the two streams are
   captured separately. Speed is limited by the CPU, so transcription runs after the meeting.
3. **Local capture with cloud transcription** (Deepgram/AssemblyAI/Azure). Live text and better
   speaker separation, but it costs about $0.25–0.50 per hour, sends audio off the machine, and
   may conflict with company policy. Kept as a possible future swap for the transcription engine
   only.

A meeting bot was ruled out early: it needs IT/Azure admin approval and is overkill for personal
use.

## Design (decided with the user)

### 1. App shell
- Small desktop window with **Start** / **Stop**, elapsed time and a level meter for each
  stream, plus a system-tray icon. Recording starts and stops manually.
- Optional meeting title entered at Start (used in the folder name).

### 2. Recording
- **Others:** loopback capture of Windows output devices (WASAPI loopback).
  - Bluetooth headsets appear as two output devices ("Headphones" stereo and "Headset"
    hands-free), and Teams may play to either. The app records loopback from **every active
    output device at once**, each to its own track on a shared meeting clock.
  - Devices added during the meeting start a new track at the current clock offset. Devices
    removed have their track closed. Nothing is dropped during a switch.
  - At transcription time, all output tracks are mixed (summed and level-limited) into a single
    "Others" track aligned to the meeting clock.
- **Me:** the microphone. A setting chooses "follow the Windows default communications mic"
  (default) or a specific device, and remembers the choice. If the chosen mic disappears, the app
  falls back to the default and logs the switch with its timestamp.
- **Mic mute in the app (user's request):** the "Me" stream has its own mute toggle. Recording
  starts **muted**, and the user unmutes when they speak.
  - Controls: a big Mic button in the window, a tray-menu item, and a **global hotkey**
    (default `Ctrl+Alt+M`, configurable) so it works while Teams has focus.
  - Optional setting (off by default): also toggle when Teams' own mute shortcut
    `Ctrl+Shift+M` is pressed. The app only listens to the shortcut and doesn't block it, so Teams
    still gets it. Clicking Teams' mute button can't be detected, so the two can get out of sync;
    the app's own state is what counts.
  - The current state must be obvious: the tray icon changes colour (red = muted, green = live)
    and the window shows a clear MUTED/LIVE label.
  - While muted, the app **records silence** for "Me" (it doesn't stop the stream), so timestamps
    stay aligned. Mute/unmute times are saved in `meta.json`.
  - "Others" is never muted by this control.
- Audio is written **to disk as it's captured** in 16 kHz mono 16-bit chunks, so a crash
  loses at most a few seconds. On Stop, the chunks are finalised into one FLAC file per stream.
- Recording CPU load must stay low (target <5% on this machine). No transcription runs while
  recording.

### 3. Transcription (after Stop)
- Engine: **faster-whisper** on CPU (int8). Meetings are **English only**, so use the
  English-only models: default **small.en**, with **medium.en** selectable in settings. Language
  is fixed to `en` (no auto-detection). Voice-activity filtering on, to skip silence.
- Me and Others are transcribed separately, then merged by start time. Consecutive segments
  from the same speaker are joined into one paragraph if the gap is under about 2 s.
- **Echo de-duplication:** when the user is on laptop speakers, the mic also picks up the remote
  voices. "Me" segments that overlap in time with an "Others" segment and closely match its text
  are dropped.
- A progress bar shows percent done and estimated time remaining. Jobs run in a background
  worker. If a new recording finishes while one is being transcribed, it waits in a queue.
- Closing the window during transcription asks the user to confirm. An unfinished job can be
  resumed later with **Transcribe again** on that meeting folder.

### 4. Output
- One folder per meeting:
  `Documents\TeamsTranscripts\2026-11-25_1430_<title>\`
  - `others.flac`, `me.flac`
  - `transcript.md`
  - `meta.json` (start/end time, devices used and switch times, model, settings)
- `transcript.md` format:
  ```
  # <title> — 2026-11-25 14:30 (52 min)

  [00:00:05] **Others:** Morning everyone, let's get started…
  [00:00:19] **Me:** Hi, yes I can hear you.
  ```
- Setting: delete audio after a successful transcription (default **off**: keep the audio).

## Builder's calls (the builder may change these)

- Libraries: PyAudioWPatch or `soundcard` for WASAPI loopback (pick whichever handles device
  hot-plugging better in a spike); `soundfile` for FLAC; Tkinter for the window and `pystray`
  for the tray, or PySide6 if Tkinter plus tray proves awkward.
- How device changes are detected (polling the device list vs. Windows notifications).
- Exact echo-matching threshold and paragraph-joining gap.
- Settings storage (a JSON file in `%APPDATA%\TeamsListener\` is fine).
- Packaging: a venv plus a `.bat`/Start-menu shortcut for v1. A PyInstaller .exe later.
- Measure actual transcription speed for small and medium on this laptop early, and show it in
  the README.

## Later (not v1)

- Speaker separation for "Others" (e.g. pyannote), labelling Speaker 1/2/3…, estimated to add
  about 50% to processing time.
- Live rough preview with a tiny model.
- Detecting Teams calls automatically and prompting to start.
- Summaries and action items generated from `transcript.md`.
- Optional cloud transcription engine behind the same interface.

## Note on consent

This is a personal tool, but recording other people may still require their consent and may
be covered by company policy. The README should say so.
