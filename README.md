# Teams Listener

A personal Windows app that records your Teams meetings and turns them into a timestamped transcript,
**entirely on your own laptop**. No bot joins the meeting, no admin rights are needed, and nothing is uploaded.

- **Others** = everything your PC plays (speakers, wired or Bluetooth headphones).
- **Me** = your microphone, which you **unmute in the app** only when you speak.
- After you press **Stop**, the meeting is transcribed offline with Whisper (`small.en` by default).

> **Consent:** this is a personal tool, but recording other people may still need their consent and may be
> covered by your company's policy. Check before you use it.

## Install

Build the installer once (see Development), then run **`desktop\dist\Teams Listener Setup <version>.exe`**.
It installs per user (no admin rights) to `%LOCALAPPDATA%\Programs\Teams Listener`, adds a desktop shortcut and
starts the app. The installer isn't code-signed, so Windows SmartScreen may warn: click **More info → Run anyway**.

The app opens a window and a tray icon. Pressing **● New recording** also shows a small always-on-top pill with the
mute button.

**First transcription** downloads the speech model from Hugging Face once (small.en ≈ 480 MB, medium.en ≈ 1.5 GB).
If your office network blocks that, download the model folder (e.g. `Systran/faster-whisper-small.en`) on
another network and choose it under **Settings → Model folder**.

## Using it

1. Optionally type a meeting title, then press **● New recording** when the meeting begins.
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

## Speed on this laptop (i5-8365U, no GPU)

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

Logs: `%APPDATA%\TeamsListenerpp.log`. Settings: `%APPDATA%\TeamsListener\settings.json`.

## Capture notes (spike, 2026-11-25)
- `soundcard` WASAPI loopback on this laptop delivers continuous zero-filled blocks during silence and warns
  `data discontinuity`. The app filters that warning, and the track writer's wall-clock gap-fill stays as a safety net.
- `soundcard.all_microphones()` re-enumerates devices on every call, so newly connected devices appear on the next poll.
- At build time Windows reported **no microphone** on this machine. The app keeps recording "Others" with no mic,
  and picks one up if it appears mid-meeting.

## Verified

| Check | Result |
|---|---|
| Unit tests (`pytest -m "not slow"`, `npm test --prefix desktop`) | ✅ |
| Real Whisper on speech fixture (`pytest -m slow`) | ✅ |
| End-to-end: Tk app start → unmute → speech through speakers → stop → transcript | ✅ transcript correct, meta has device + unmute events |
| Real loopback recording: tone placed at correct time, silence elsewhere | ✅ |
| Teams test call, mic muted throughout → Others only | ⏳ needs you |
| Unmute with Ctrl+Alt+M while Teams has focus → Me lines at right time, tray icon colour | ⏳ needs you (no mic was detected at build time) |
| Bluetooth headphones (realme Buds Air7) connect/disconnect mid-recording → no gap, events logged | ✅ buds→laptop speakers→buds switches captured; every sentence played was transcribed |
| Bluetooth: opening the buds' mic doesn't degrade the audio you hear | ✅ confirmed by ear |
| Speakers + unmuted mic (echo) → no duplicate Me lines | ⏳ needs you |
| Hard-kill the recording process mid-meeting → listed "not transcribed" → transcribes | ✅ (simulated with the recorder process; worth one real try in the app) |
| Close window while recording → prompt → saved and transcribed | ⏳ needs you |
| Recording CPU < 5% | ✅ ≈ 0.5% of the machine (4% of one core), measured in-process |
