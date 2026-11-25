# Teams Listener

(Full README written in Task 9.)

## Capture notes (spike, 2026-11-25)
- `soundcard` WASAPI loopback on this laptop (Realtek speakers) delivers **continuous zero-filled blocks during silence**,
  emitting `SoundcardRuntimeWarning: data discontinuity` — the app filters this warning. The TrackWriter's wall-clock
  gap-fill remains as a safety net for drivers that stop delivering frames.
- `soundcard.all_microphones()` creates a fresh device enumerator on each call, so newly connected devices
  (e.g. Bluetooth headphones) appear on the next poll without restarting.
- At spike time Windows had **no capture device** (`default_microphone()` → `0x80070490`); the app must keep
  recording "Others" when no mic exists.
- Bluetooth hot-plug not yet verified on hardware — part of the Task 9 manual checklist.
