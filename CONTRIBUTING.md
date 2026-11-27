# Contributing

Thanks for your interest! Bug reports, ideas and pull requests are all welcome.

## Ground rules

- **Privacy first.** The app never uploads audio or text. Changes that add network calls, telemetry or cloud
  services won't be accepted (the one exception is faster-whisper's one-time model download).
- **Never share real meeting data** in issues, PRs or test fixtures — use synthetic audio (e.g. Windows text-to-speech).
- **The engine is the source of truth** for recording and mute state; UI surfaces only render what it reports.

## Setup (Windows 10/11)

```bat
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
npm install --prefix desktop
run.bat
```

See the README's *Development* section for tests and building the installer.

## Making a change

1. Fork the repo and create a branch from `main`.
2. Write a failing test first where possible, then the fix.
   - Python: `tests/` (pytest). Hardware-dependent tests skip themselves when no device is present.
   - Desktop: `desktop/test/` (`node --test`). Keep logic in small pure modules so it can be tested without Electron.
3. Run both suites:
   ```bat
   .venv\Scripts\pytest -m "not slow"
   npm test --prefix desktop
   ```
4. Open a pull request using the template. CI runs both suites on Windows.

## Project layout

| Path | What's there |
|---|---|
| `teams_listener/` | Python engine: capture, recorder, transcription, `controller.py`, JSON-lines `server.py` |
| `desktop/` | Electron app: `src/` (main process, engine client), `renderer/` (UI) |
| `packaging/` | PyInstaller spec and icon generator |
| `docs/superpowers/` | Design specs and implementation plans |
