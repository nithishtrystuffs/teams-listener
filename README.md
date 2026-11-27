# Teams Listener

[![CI](https://github.com/nithishtrystuffs/teams-listener/actions/workflows/ci.yml/badge.svg)](https://github.com/nithishtrystuffs/teams-listener/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A Windows app that records your Teams (or any) meetings and turns them into a timestamped transcript,
**entirely on your own PC**. No bot joins the meeting, no admin rights are needed, and nothing is uploaded.

- **Others** = everything your PC plays (speakers, wired or Bluetooth headphones).
- **Me** = your microphone, which you **unmute in the app** only when you speak.
- After you press **Stop**, the meeting is transcribed offline with [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (`small.en` by default). English only for now.

> **Consent:** recording other people may require their consent by law and may be covered by your employer's
> policy. You are responsible for how you use this tool.

> Not affiliated with or endorsed by Microsoft. "Microsoft Teams" is a trademark of Microsoft Corporation.

## Requirements

- Windows 10 or 11, 64-bit
- ~400 MB disk for the app, plus ~480 MB for the `small.en` speech model (downloaded once)
- No GPU needed

## Install

Download **`Teams Listener Setup <version>.exe`** from [Releases](https://github.com/nithishtrystuffs/teams-listener/releases),
or build it yourself (see Development).
It installs per user (no admin rights) to `%LOCALAPPDATA%\Programs\teams-listener`, adds a desktop shortcut and
starts the app. The installer isn't code-signed, so Windows SmartScreen may warn: click **More info → Run anyway**.

The app opens a window and a tray icon. While a recording runs, minimising or hiding the window shows a small
always-on-top pill with the timer, the mute button and Stop.

**First transcription** downloads the speech model from Hugging Face once (small.en ≈ 480 MB, medium.en ≈ 1.5 GB).
If your office network blocks that, download the model folder (e.g. `Systran/faster-whisper-small.en`) on
another network and choose it under **Settings → Model folder**.

## Using it

1. Press **● New recording** to open the title screen, optionally type a meeting title, then press **● Start**
   when the meeting begins.
2. The big mic button starts **MUTED**. Press it, or the shortcut **Ctrl+Alt+M**, to go **LIVE**
   when you speak, then press again to mute. The shortcut works while Teams has focus.
   The tray icon is grey when idle, red when recording and muted, and green when recording and live.
3. Press **■ Stop recording**. Transcription starts in the background with a progress bar and an estimate of the time left.
   You can start another recording while it runs: transcription **pauses** while you record and resumes when you stop, so calls stay smooth.
4. Open a meeting from **Recent meetings** to read the transcript, switch to **Only my lines**, play the audio
   or open the folder.

Closing the window keeps the app in the tray. If a recording is running it asks whether to stop and save.
Use **Quit** in the tray menu to exit.

### Mute shortcut and Teams' own shortcut
**Settings → "Also toggle when Teams' Ctrl+Shift+M is pressed"** lets one key press mute or unmute both Teams and
the app. The app only listens to the key, so Teams still receives it. The catch is that clicking Teams' mute button
with the mouse can't be detected, so the two can drift out of sync. That's why it's off by default. The app's
MUTED/LIVE label is what counts.

### Bluetooth headphones
They work. The app records every output device at once, so it doesn't matter whether Teams plays to
"Headphones" (stereo) or "Headset" (hands-free), and connecting or disconnecting mid-meeting doesn't lose audio.
**Tip:** in Teams, choose your **laptop's built-in mic** as the microphone and keep the Bluetooth headphones as the
speaker. The headphones then stay in high-quality mode, and both sides transcribe better.

### Laptop speakers
If you're on speakers and unmuted, your mic also hears the remote people. The app drops "Me" lines that duplicate
an "Others" line at the same moment.

## Output

Each meeting gets a folder in `Documents\TeamsTranscripts\` (changeable in Settings):

```
2026-11-25_1430_Standup\
  transcript.md   ← [00:00:05] **Others:** … / [00:00:19] **Me:** …
  others.flac     ← mixed remote audio (16 kHz mono)
  me.flac         ← your mic (silence while muted)
  meta.json       ← times, devices, device switches, mute/unmute times, model
  tracks\         ← raw per-device recordings (written continuously, safe against crashes)
```

The audio is kept unless you enable **Settings → Delete audio after a successful transcription**.
If the app or PC crashes mid-meeting, the raw tracks survive. The meeting shows as **not transcribed**;
select it and press **Transcribe again**.

## Speed (measured on an i5-8365U laptop, no GPU)

Measured on 2 min 17 s of clear English speech (Windows TTS), CPU only:

| Model | Time per hour of meeting | Notes |
|---|---|---|
| `small.en` (default) | **≈ 22 min** | Accurate on clear speech; may slip on names and jargon |
| `medium.en` | **≈ 2 h 40 min** | Slightly better wording; only worth it for an important meeting left overnight |

Real meetings with crosstalk or accents can take a bit longer. Silence is skipped, so a quiet meeting is faster.

Recording itself uses about 0.5% of the CPU. Transcription never runs during a recording: an unfinished one pauses
when you press Start and carries on after Stop.

## Development

The Python engine (`teams_listener/`) is driven by the Electron app in `desktop/` over JSON lines on stdin/stdout.

```bat
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
npm install --prefix desktop

run.bat                               :: dev launcher (or: npm start --prefix desktop)
.venv\Scripts\pytest -m "not slow"    :: fast Python tests
.venv\Scripts\pytest -m slow          :: real Whisper (tiny.en) on a speech fixture
npm test --prefix desktop             :: JS tests

.venv\Scripts\pip install -r requirements-build.txt
npm run dist --prefix desktop         :: PyInstaller engine + NSIS installer in desktop\dist
.venv\Scripts\python -m teams_listener --tk   :: old Tkinter UI, as a fallback
```

Logs: `%APPDATA%\TeamsListener\app.log`. Settings: `%APPDATA%\TeamsListener\settings.json`.

## How it works

- **Capture:** WASAPI loopback on every output device plus your mic, via [`soundcard`](https://github.com/bastibe/SoundCard).
  Devices that connect or disconnect mid-meeting are picked up automatically. Audio is written continuously to
  per-device tracks on one meeting clock, so a crash never loses what was recorded.
- **Transcription:** after Stop, the tracks are mixed to `others.flac` / `me.flac` and transcribed separately
  with faster-whisper on the CPU; "Me" lines that echo an "Others" line are dropped.
- **App:** an Electron front end talks to the Python engine over JSON lines on stdin/stdout. The engine is the
  single source of truth for recording and mute state.

Design notes live in [`docs/superpowers/specs/`](docs/superpowers/specs/).

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Security issues: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
