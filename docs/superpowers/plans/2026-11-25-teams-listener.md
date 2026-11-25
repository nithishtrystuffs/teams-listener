# Teams Listener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Windows desktop app that records a Teams meeting (PC output = "Others", mic = "Me", with an in-app mic mute) and, after Stop, transcribes it offline into a timestamped Markdown transcript.

**Architecture:** Pure-logic modules (settings, meeting folders, track writing, mixing, segment merging, Markdown) are unit-tested. Thin hardware adapters (`soundcard` for WASAPI capture, `faster-whisper`, `pynput`, Tk/pystray) sit behind small protocols so the orchestrators (`Recorder`, `transcribe_meeting`) are tested with fakes. Recording writes raw 16 kHz mono int16 `.pcm` tracks to disk continuously. On Stop, they're mixed into `others.flac` / `me.flac`, then transcribed in a background queue.

**Tech Stack:** Python 3.11, numpy, soundcard (>=0.4.3), soxr (streaming resample), soundfile (FLAC), faster-whisper (CPU int8), comtypes/pycaw (default communications mic), pynput (global hotkeys), Tkinter + pystray + Pillow (UI), pytest.

**Spec:** `docs/superpowers/specs/2026-11-25-teams-listener-design.md`

## Global Constraints

- Windows 11, Python 3.11.9, CPU only (i5-8365U, no CUDA). No network use except the one-time model download.
- No audio or text leaves the machine.
- Meetings are English only: models `small.en` (default) and `medium.en`; `language="en"`, `vad_filter=True`, `device="cpu"`, `compute_type="int8"`.
- Internal audio format: 16000 Hz, mono, int16 (`SAMPLE_RATE = 16000`).
- Recording starts with the mic **muted**. Muted mic writes silence (stream keeps running). "Others" is never muted.
- Default hotkey `<ctrl>+<alt>+m`. Optional "follow Teams shortcut" `<ctrl>+<shift>+m`, listen-only (never suppressed), default off.
- Output: `~/Documents/TeamsTranscripts/YYYY-MM-DD_HHMM_<slug>/` containing `others.flac`, `me.flac`, `transcript.md`, `meta.json`, `tracks/`.
- Transcript line format: `[HH:MM:SS] **Me:** text` / `[HH:MM:SS] **Others:** text`. Header `# <title> — YYYY-MM-DD HH:MM (N min)`.
- Echo de-duplication: drop a Me segment if ≥50% of it overlaps an Others segment and normalized text similarity ≥0.6. Join same-speaker segments when gap <2.0 s.
- Delete-audio-after-transcription setting defaults to **off**, and deletes only after `transcript.md` is written.
- Recording must not run transcription concurrently. Target recording CPU <5%.
- Settings: `%APPDATA%\TeamsListener\settings.json`.

## Review Focus

1. **WASAPI loopback sends no frames while nothing is playing.** "Others" must still stay time-aligned: the TrackWriter fills wall-clock gaps with silence (Task 3 test `test_gap_filled_with_silence`).
2. **App crash or force close mid-meeting.** The raw `.pcm` tracks must survive and be finalizable later, including a truncated odd-byte last sample (Task 4 test `test_finalize_truncated_pcm`).
3. **No output device at all, or the only output (Bluetooth) turned off for the whole meeting.** Recording continues on the mic, and `others.flac` is silence of the full meeting length (Task 4 test `test_finalize_with_no_others_tracks`).
4. **Long meetings (3 h+).** Mixing must work in blocks, not load every track as int32 at once. The result must equal a whole-array mix (Task 4 test `test_mix_blockwise_equals_full`).
5. **Meeting with no speech, or Stop pressed after a second.** It still produces a valid transcript reading `_No speech detected._` (Task 6 test `test_render_empty`). Closing the window during a recording prompts, then stops and finalizes (Task 9 manual check).

---

### Task 1: Project scaffold and capture spike

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.gitignore`, `teams_listener/__init__.py`, `tests/__init__.py`, `tools/spike_capture.py`

**Interfaces:**
- Produces: importable package `teams_listener`; dev venv at `.venv`.

- [ ] **Step 1: `git init`, then create `.venv` with `py -3.11 -m venv .venv`.** Write `requirements.txt`: `numpy`, `soundcard>=0.4.3`, `soxr`, `soundfile`, `faster-whisper`, `comtypes`, `pycaw`, `pynput`, `pystray`, `Pillow`, `pytest`. `.gitignore`: `.venv/`, `__pycache__/`, `*.pcm`, `*.flac`, `models/`.
- [ ] **Step 2: Install.** Run: `.venv\Scripts\pip install -r requirements.txt`. Expected: exits 0.
- [ ] **Step 3: Write `tools/spike_capture.py`.** Every 1 s for 30 s, it lists `soundcard.all_microphones(include_loopback=True)`, opens a recorder at 48000 Hz on each loopback and on the default mic in one thread each, reading 4800-frame blocks. It prints per-device RMS and the wall-clock time of each block.
- [ ] **Step 4: Run the spike manually** with laptop speakers, then with Bluetooth headphones while a Teams test call ("Make a test call") plays, connecting the headphones mid-run. Expected: both Bluetooth endpoints ("Headphones" and "Headset") appear when connected, new devices show up on re-listing, and blocks stop arriving (or arrive as zeros) during silence. **Record the observed silence behaviour in the README draft**: it confirms Review Focus #1. If `soundcard` can't see newly connected devices without a restart, stop and report back before continuing.
- [ ] **Step 5: Commit** `git add -A && git commit -m "chore: scaffold project and capture spike"` (including the spec and this plan).

### Task 2: Settings and meeting folders

**Files:**
- Create: `teams_listener/config.py`, `teams_listener/meeting.py`
- Test: `tests/test_config.py`, `tests/test_meeting.py`

**Interfaces:**
- Produces:
  - `Settings` dataclass: `model: str = "small.en"`, `model_path: str | None = None`, `mic_device: str | None = None` (None = follow Windows default communications mic), `hotkey: str = "<ctrl>+<alt>+m"`, `follow_teams_shortcut: bool = False`, `delete_audio_after: bool = False`, `output_dir: str = str(Path.home() / "Documents" / "TeamsTranscripts")`
  - `ALLOWED_MODELS = ("small.en", "medium.en")`, `DEFAULT_SETTINGS_PATH: Path`
  - `load_settings(path: Path | None = None) -> Settings`, `save_settings(s: Settings, path: Path | None = None) -> None`
  - `slugify_title(title: str) -> str`, `make_meeting_dir(output_dir: Path, start: datetime, title: str) -> Path`
  - `MeetingMeta` dataclass: `title: str`, `start: datetime`, `end: datetime | None = None`, `model: str | None = None`, `devices: list[str]`, `events: list[dict]` (each `{"t": float_seconds, "type": str, "detail": str}`; types: `device_added`, `device_removed`, `mic_switched`, `mute`, `unmute`)
  - `write_meta(folder: Path, meta: MeetingMeta) -> None`, `read_meta(folder: Path) -> MeetingMeta`

- [ ] **Step 1: Write failing tests**

```python
def test_missing_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "s.json") == Settings()

def test_roundtrip(tmp_path):
    s = Settings(model="medium.en", follow_teams_shortcut=True)
    save_settings(s, tmp_path / "s.json")
    assert load_settings(tmp_path / "s.json") == s

def test_corrupt_file_gives_defaults_and_backup(tmp_path):
    p = tmp_path / "s.json"; p.write_text("{not json")
    assert load_settings(p) == Settings()
    assert (tmp_path / "s.json.bak").exists()

def test_unknown_keys_ignored_and_bad_model_reset(tmp_path):
    p = tmp_path / "s.json"; p.write_text('{"model": "large-v3", "zzz": 1}')
    assert load_settings(p).model == "small.en"

def test_slugify():
    assert slugify_title('Sprint: Review/Q4?') == "Sprint-Review-Q4"
    assert slugify_title("   ") == "meeting"
    assert len(slugify_title("x" * 200)) == 50

def test_make_meeting_dir_name_and_collision(tmp_path):
    t = datetime(2026, 11, 25, 14, 30)
    a = make_meeting_dir(tmp_path, t, "Standup")
    b = make_meeting_dir(tmp_path, t, "Standup")
    assert a.name == "2026-11-25_1430_Standup" and a.is_dir()
    assert b.name == "2026-11-25_1430_Standup-2"

def test_meta_roundtrip(tmp_path):
    m = MeetingMeta("T", datetime(2026, 11, 25, 14, 30), devices=["Speakers"],
                    events=[{"t": 1.5, "type": "unmute", "detail": ""}])
    write_meta(tmp_path, m); assert read_meta(tmp_path) == m
```

- [ ] **Step 2: Run** `.venv\Scripts\pytest tests/test_config.py tests/test_meeting.py -v`. Expected: FAIL (import errors).
- [ ] **Step 3: Implement** both modules. Slug: replace `<>:"/\|?*` with space, collapse whitespace runs to `-`, strip `-`, cut to 50 characters, empty → `meeting`. Datetimes are stored as ISO strings in `meta.json`. `save_settings` creates parent dirs.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: settings and meeting folder helpers`.

### Task 3: Resampler and TrackWriter

**Files:**
- Create: `teams_listener/audio/__init__.py`, `teams_listener/audio/track.py`
- Test: `tests/test_track.py`

**Interfaces:**
- Produces:
  - `SAMPLE_RATE = 16000`, `GAP_FILL_THRESHOLD = 3200` (0.2 s in samples)
  - `Resampler(src_rate: int, channels: int)` with `.process(frames: np.ndarray) -> np.ndarray`: float32 `(n, ch)` in [-1, 1] → int16 mono at 16 kHz. Downmix by mean, use `soxr.ResampleStream` (stateful across calls), clip before converting to int16.
  - `TrackWriter(folder: Path, track_id: str, kind: Literal["others", "me"], device_name: str, clock_start: float)` with `.write(samples: np.ndarray, arrival_time: float) -> None`, `.close() -> None`, `.samples_written: int` (includes filled silence), `.offset_samples: int | None`
  - On disk: `folder/tracks/<track_id>.pcm` (raw int16 LE, flushed after every write) and `folder/tracks/<track_id>.json` `{"kind", "device", "offset_samples"}`, written on first write.

`arrival_time` is the `perf_counter` time when the chunk's last sample was captured. Algorithm:

```
end_expected = round((arrival_time - clock_start) * SAMPLE_RATE)
first write:  offset = max(0, end_expected - len(samples)); write sidecar
later writes: end_actual = offset + samples_written + len(samples)
              if end_expected - end_actual > GAP_FILL_THRESHOLD: write zeros(end_expected - end_actual) first
```

- [ ] **Step 1: Write failing tests**

```python
def test_resampler_48k_stereo_to_16k_mono():
    r = Resampler(48000, 2)
    out = np.concatenate([r.process(np.full((4800, 2), 0.5, np.float32)) for _ in range(10)])
    assert out.dtype == np.int16 and abs(len(out) - 16000) < 200
    assert abs(int(out[-1000:].mean()) - 16383) < 300

def test_first_write_sets_offset(tmp_path):
    w = TrackWriter(tmp_path, "others-1", "others", "Speakers", clock_start=100.0)
    w.write(np.ones(1600, np.int16), arrival_time=102.1)   # ends at 2.1 s → starts at 2.0 s
    w.close()
    assert w.offset_samples == 32000
    assert json.loads((tmp_path/"tracks/others-1.json").read_text())["offset_samples"] == 32000

def test_gap_filled_with_silence(tmp_path):
    w = TrackWriter(tmp_path, "others-1", "others", "Speakers", clock_start=0.0)
    w.write(np.ones(1600, np.int16), arrival_time=0.1)
    w.write(np.ones(1600, np.int16), arrival_time=5.1)     # 4.9 s with no frames delivered
    w.close()
    data = np.fromfile(tmp_path/"tracks/others-1.pcm", np.int16)
    assert len(data) == round(5.1 * 16000)
    assert (data[1600:-1600] == 0).all()

def test_small_jitter_not_filled(tmp_path):
    w = TrackWriter(tmp_path, "me-1", "me", "Mic", clock_start=0.0)
    w.write(np.ones(1600, np.int16), 0.1); w.write(np.ones(1600, np.int16), 0.25)
    w.close()
    assert w.samples_written == 3200
```

- [ ] **Step 2: Run** `pytest tests/test_track.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `teams_listener/audio/track.py`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: streaming resampler and gap-filling track writer`.

### Task 4: Mixer and finalize

**Files:**
- Create: `teams_listener/audio/mixer.py`
- Test: `tests/test_mixer.py`

**Interfaces:**
- Consumes: the Task 3 on-disk track format.
- Produces:
  - `Track` dataclass: `kind: str`, `device: str`, `offset_samples: int`, `path: Path`, `length: int`
  - `load_tracks(folder: Path) -> list[Track]`: reads sidecars and derives `length` from the `.pcm` size, ignoring a trailing odd byte. Skips `.pcm` files without a sidecar.
  - `mix_to_file(tracks: list[Track], total_samples: int, out_path: Path, block: int = 16000 * 60) -> None`: memory-maps each pcm, sums per block in int32, clips to int16 and writes FLAC (16 kHz mono PCM_16) block by block with `soundfile.SoundFile`.
  - `finalize_meeting(folder: Path) -> tuple[Path, Path]`: returns `(others.flac, me.flac)`. `total_samples` = max(offset + length) across all tracks (0 → 1 s of silence). A kind with no tracks becomes silence of `total_samples`. Idempotent: rewrites the files if they exist.

- [ ] **Step 1: Write failing tests** (helper `make_track(folder, id, kind, offset, data)` writes pcm and sidecar directly)

```python
def test_mix_places_tracks_at_offsets(tmp_path):
    make_track(tmp_path, "others-1", "others", 0, np.full(16000, 100, np.int16))
    make_track(tmp_path, "others-2", "others", 8000, np.full(16000, 50, np.int16))
    others, _ = finalize_meeting(tmp_path)
    d, sr = sf.read(others, dtype="int16")
    assert sr == 16000 and len(d) == 24000
    assert d[0] == 100 and d[10000] == 150 and d[20000] == 50

def test_mix_clips(tmp_path):
    make_track(tmp_path, "others-1", "others", 0, np.full(100, 30000, np.int16))
    make_track(tmp_path, "others-2", "others", 0, np.full(100, 30000, np.int16))
    d, _ = sf.read(finalize_meeting(tmp_path)[0], dtype="int16")
    assert d.max() == 32767

def test_mix_blockwise_equals_full(tmp_path):
    rng = np.random.default_rng(0)
    a = rng.integers(-1000, 1000, 50000).astype(np.int16)
    make_track(tmp_path, "others-1", "others", 123, a)
    tr = load_tracks(tmp_path)
    mix_to_file(tr, 50123, tmp_path/"a.flac", block=777)
    mix_to_file(tr, 50123, tmp_path/"b.flac", block=10**7)
    assert (sf.read(tmp_path/"a.flac", dtype="int16")[0] == sf.read(tmp_path/"b.flac", dtype="int16")[0]).all()

def test_finalize_with_no_others_tracks(tmp_path):
    make_track(tmp_path, "me-1", "me", 0, np.ones(32000, np.int16))
    others, me = finalize_meeting(tmp_path)
    d, _ = sf.read(others, dtype="int16")
    assert len(d) == 32000 and not d.any()

def test_finalize_truncated_pcm(tmp_path):
    make_track(tmp_path, "me-1", "me", 0, np.ones(1000, np.int16))
    with open(tmp_path/"tracks/me-1.pcm", "ab") as f: f.write(b"\x01")   # crash mid-sample
    _, me = finalize_meeting(tmp_path)
    assert len(sf.read(me, dtype="int16")[0]) == 1000
```

- [ ] **Step 2: Run** `pytest tests/test_mixer.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `teams_listener/audio/mixer.py`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: block-wise track mixer and meeting finalize`.

### Task 5: Device adapters and Recorder

**Files:**
- Create: `teams_listener/audio/devices.py`, `teams_listener/audio/recorder.py`
- Test: `tests/test_recorder.py` (fakes only; `devices.py` is verified manually in Task 9)

**Interfaces:**
- Consumes: `Resampler`, `TrackWriter` (Task 3).
- Produces:
  - `devices.py`: `class DeviceGone(Exception)`; protocol `AudioDevice` (`id: str`, `name: str`, `open() -> AudioReader`); protocol `AudioReader` (`samplerate: int`, `channels: int`, `read() -> np.ndarray` float32 `(n, ch)` blocking about 100 ms, raises `DeviceGone`, `close()`); `list_output_loopbacks() -> list[AudioDevice]` via `soundcard.all_microphones(include_loopback=True)` filtered to `isloopback`; `get_mic(name: str | None) -> AudioDevice`. For `None`, it resolves the default **communications** capture endpoint via pycaw/comtypes (`GetDefaultAudioEndpoint(eCapture, eCommunications)`) and matches it to a soundcard mic by id, falling back to `soundcard.default_microphone()`; an unknown name also falls back. Readers open at 48000 Hz with 4800-frame blocks. Any soundcard/COM error during `read` is re-raised as `DeviceGone`.
  - `recorder.py`: `Recorder(folder: Path, list_outputs: Callable[[], list[AudioDevice]], get_mic: Callable[[str | None], AudioDevice], mic_name: str | None, poll_interval: float = 1.0, clock: Callable[[], float] = time.perf_counter)`
    - `start() -> None`: sets `clock_start`, starts the poller thread and the mic thread
    - `stop() -> RecordingSummary` (`duration_s: float`, `events: list[dict]`, `devices: list[str]`): signals threads, joins them, closes writers
    - `muted: bool` property, initially `True`; setting it appends a `mute`/`unmute` event
    - `levels() -> dict[str, float]`: latest RMS 0..1 for `"others"` (max across devices) and `"me"`
    - `events: list[dict]` (format from Task 2)
    - `Active` dataclass: `track_id: str`, `device: AudioDevice`, `reader: AudioReader`, `writer: TrackWriter`, `resampler: Resampler`, `is_mic: bool`. `_active: dict[str, Active]` maps output device id to Active (outputs only). `_open_mic() -> Active` opens `get_mic(mic_name)` as track `me-1` (then `me-2`, … on fallback).
    - Testable internals: `_poll_once() -> None` opens a reader thread for each output id not currently active (track ids `others-1`, `others-2`, … in open order; event `device_added`). `_pump_once(active) -> bool` reads one block, resamples, zeroes it if this is the mic and `muted`, writes with `arrival_time=clock()`, and returns False after closing on `DeviceGone` (event `device_removed`, or for the mic: `mic_switched` then reopen via `get_mic(None)` as a new `me-N` track).

- [ ] **Step 1: Write failing tests** with `FakeDevice(id, name, blocks)` whose reader returns 4800×2 float32 blocks of 0.5 and raises `DeviceGone` once `blocks` are used up, plus a fake clock advancing 0.1 s per `read`.

```python
def test_poll_adds_new_devices_once(tmp_path):
    outs = [FakeDevice("a", "Speakers", 5)]
    r = make_recorder(tmp_path, outs)
    r._poll_once(); r._poll_once()
    assert [e["type"] for e in r.events].count("device_added") == 1
    outs.append(FakeDevice("b", "Headset", 5)); r._poll_once()
    assert {a.track_id for a in r._active.values()} >= {"others-1", "others-2"}

def test_starts_muted_and_writes_silence(tmp_path):
    r = make_recorder(tmp_path, [])
    act = r._open_mic()
    assert r.muted is True
    r._pump_once(act); r._pump_once(act); act.writer.close()
    assert not np.fromfile(tmp_path/"tracks/me-1.pcm", np.int16).any()

def test_unmuted_mic_writes_audio_and_logs_event(tmp_path):
    r = make_recorder(tmp_path, []); act = r._open_mic()
    r.muted = False; r._pump_once(act); act.writer.close()
    assert np.fromfile(tmp_path/"tracks/me-1.pcm", np.int16).any()
    assert r.events[-1]["type"] == "unmute"

def test_device_gone_closes_track_and_logs(tmp_path):
    r = make_recorder(tmp_path, [FakeDevice("a", "BT Headphones", 1)])
    r._poll_once(); act = next(iter(r._active.values()))
    assert r._pump_once(act) is True and r._pump_once(act) is False
    assert r.events[-1] == {"t": pytest.approx(r.events[-1]["t"]), "type": "device_removed", "detail": "BT Headphones"}

def test_mic_gone_falls_back_to_default(tmp_path):
    r = make_recorder(tmp_path, [], mic=FakeDevice("m", "BT Mic", 1), default_mic=FakeDevice("d", "Laptop Mic", 99))
    act = r._open_mic(); r._pump_once(act); r._pump_once(act)
    assert any(e["type"] == "mic_switched" for e in r.events)
    assert (tmp_path/"tracks/me-2.json").exists()
```

- [ ] **Step 2: Run** `pytest tests/test_recorder.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `devices.py` and `recorder.py`. Threads loop `_pump_once` until it returns False or the stop event is set. The poller loops `_poll_once` every `poll_interval`. All shared state goes behind one `threading.Lock`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Manual smoke test:** a 20 s script records with real devices into a temp folder, then calls `finalize_meeting`. Play both FLACs back. Expected: both audible and in sync with what was played.
- [ ] **Step 6: Commit** `feat: device adapters and multi-device recorder with mic mute`.

### Task 6: Segments, echo removal, merge, Markdown

**Files:**
- Create: `teams_listener/transcribe/__init__.py`, `teams_listener/transcribe/segments.py`
- Test: `tests/test_segments.py`

**Interfaces:**
- Produces:
  - `Segment` frozen dataclass: `start: float`, `end: float`, `speaker: Literal["Me", "Others"]`, `text: str`
  - `drop_echo(me: list[Segment], others: list[Segment], min_overlap: float = 0.5, min_similarity: float = 0.6) -> list[Segment]`. Overlap is the fraction of the Me segment's duration. Similarity is `difflib.SequenceMatcher` ratio on normalized text (lowercase, punctuation removed, whitespace collapsed).
  - `merge(me: list[Segment], others: list[Segment]) -> list[Segment]`: sorted by `start`; on ties, Others first.
  - `join_paragraphs(segs: list[Segment], max_gap: float = 2.0) -> list[Segment]`
  - `format_ts(seconds: float) -> str` → `"HH:MM:SS"`
  - `render_markdown(title: str, start: datetime, duration_s: float, segs: list[Segment]) -> str`

- [ ] **Step 1: Write failing tests**

```python
O = lambda s, e, t: Segment(s, e, "Others", t)
M = lambda s, e, t: Segment(s, e, "Me", t)

def test_drop_echo_removes_matching_overlap():
    assert drop_echo([M(1.1, 3.9, "let's get started.")], [O(1.0, 4.0, "Let's get started")]) == []

def test_drop_echo_keeps_real_speech():
    me = [M(1.0, 4.0, "Yes I can hear you")]
    assert drop_echo(me, [O(1.0, 4.0, "Let's get started")]) == me

def test_merge_and_join():
    segs = join_paragraphs(merge([M(5.0, 6.0, "Hi.")], [O(0.0, 2.0, "Hello."), O(3.0, 4.0, "Welcome.")]))
    assert segs == [O(0.0, 4.0, "Hello. Welcome."), M(5.0, 6.0, "Hi.")]

def test_join_respects_gap():
    assert len(join_paragraphs([O(0, 1, "a"), O(3.5, 4, "b")])) == 2

def test_render():
    md = render_markdown("Standup", datetime(2026, 11, 25, 14, 30), 52 * 60 + 10,
                         [O(5, 9, "Morning everyone."), M(19, 21, "Hi.")])
    assert md.startswith("# Standup — 2026-11-25 14:30 (52 min)\n")
    assert "[00:00:05] **Others:** Morning everyone.\n\n[00:00:19] **Me:** Hi." in md

def test_render_empty():
    md = render_markdown("X", datetime(2026, 11, 25, 9, 0), 3, [])
    assert "(1 min)" in md and "_No speech detected._" in md
```

- [ ] **Step 2: Run** `pytest tests/test_segments.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Minutes = `max(1, round(duration_s / 60))`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: segment merge, echo removal and markdown rendering`.

### Task 7: Whisper engine, pipeline, background queue

**Files:**
- Create: `teams_listener/transcribe/engine.py`, `teams_listener/transcribe/pipeline.py`
- Test: `tests/test_pipeline.py`, `tests/test_engine_integration.py` (marked `@pytest.mark.slow`; register the marker in `pyproject.toml`)

**Interfaces:**
- Consumes: `finalize_meeting` (Task 4), `read_meta`/`write_meta` (Task 2), `drop_echo`/`merge`/`join_paragraphs`/`render_markdown` (Task 6), `Settings` (Task 2).
- Produces:
  - protocol `Engine`: `transcribe(audio: Path, speaker: Literal["Me", "Others"], on_progress: Callable[[float], None]) -> list[Segment]`
  - `WhisperEngine(model: str, model_path: str | None = None, cpu_threads: int = 4)`: lazily creates `WhisperModel(model_path or model, device="cpu", compute_type="int8", cpu_threads=cpu_threads)`; calls `transcribe(str(audio), language="en", vad_filter=True, beam_size=5)`; reports progress `seg.end / info.duration` (capped at 1.0) and calls `on_progress(1.0)` at the end. Text is stripped and empty segments are skipped.
  - `transcribe_meeting(folder: Path, engine: Engine, settings: Settings, on_progress: Callable[[float], None]) -> Path`: finalize → transcribe Others (progress 0–0.5) → transcribe Me (0.5–1.0) → `drop_echo` → `merge` → `join_paragraphs` → write `transcript.md` (title/start/duration from `meta.json`; duration = `end - start`, falling back to the FLAC length) → set `meta.model` → if `settings.delete_audio_after`, delete both FLACs and `tracks/`. Returns the transcript path.
  - `TranscriptionQueue(engine_factory: Callable[[], Engine], get_settings: Callable[[], Settings], on_progress: Callable[[Path, float, float | None], None], on_done: Callable[[Path, Path], None], on_error: Callable[[Path, Exception], None])` with `submit(folder: Path)`, `busy: bool`, `shutdown()`. It has a single worker thread and caches the engine until `settings.model` changes. ETA = `elapsed / frac * (1 - frac)` once `frac > 0.02`, otherwise `None`.

- [ ] **Step 1: Write failing tests** with `FakeEngine` returning fixed segments per speaker, and a meeting folder built with the Task 4 `make_track` helper plus `write_meta`.

```python
def test_pipeline_writes_transcript_and_keeps_audio(tmp_path):
    folder = fake_meeting(tmp_path)
    eng = FakeEngine(others=[O(0, 2, "Hello.")], me=[M(3, 4, "Hi."), M(0.1, 1.9, "hello")])
    p = transcribe_meeting(folder, eng, Settings(), lambda f: None)
    text = p.read_text()
    assert "**Others:** Hello." in text and "**Me:** Hi." in text and "hello\n" not in text
    assert (folder/"others.flac").exists() and read_meta(folder).model == "small.en"

def test_pipeline_progress_monotonic_to_one(tmp_path):
    seen = []
    transcribe_meeting(fake_meeting(tmp_path), FakeEngine(), Settings(), seen.append)
    assert seen == sorted(seen) and seen[-1] == 1.0

def test_delete_audio_after(tmp_path):
    folder = fake_meeting(tmp_path)
    transcribe_meeting(folder, FakeEngine(), Settings(delete_audio_after=True), lambda f: None)
    assert (folder/"transcript.md").exists()
    assert not (folder/"others.flac").exists() and not (folder/"tracks").exists()

def test_engine_failure_keeps_audio(tmp_path):
    folder = fake_meeting(tmp_path)
    with pytest.raises(RuntimeError):
        transcribe_meeting(folder, FailingEngine(), Settings(delete_audio_after=True), lambda f: None)
    assert (folder/"tracks").exists() and not (folder/"transcript.md").exists()

def test_queue_runs_jobs_in_order(tmp_path):
    done = []; ev = threading.Event()
    q = TranscriptionQueue(lambda: FakeEngine(), Settings, lambda *a: None,
                           lambda f, p: (done.append(f), len(done) == 2 and ev.set()), lambda f, e: None)
    a, b = fake_meeting(tmp_path / "a"), fake_meeting(tmp_path / "b")
    q.submit(a); q.submit(b); assert ev.wait(10); assert done == [a, b]; q.shutdown()
```

`tests/test_engine_integration.py` (slow): use `WhisperEngine("tiny.en")` to transcribe a short committed English speech WAV fixture. Generate it once with Windows SAPI (`System.Speech`) saying "The quick brown fox jumps over the lazy dog". Assert `"fox" in text.lower()`.

- [ ] **Step 2: Run** `pytest tests/test_pipeline.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `engine.py` and `pipeline.py`.
- [ ] **Step 4: Run** `pytest -v -m "not slow"`, then `pytest -v -m slow` (downloads tiny.en, about 75 MB). Expected: all PASS.
- [ ] **Step 5: Commit** `feat: whisper engine, transcription pipeline and queue`.

### Task 8: Mute hotkeys

**Files:**
- Create: `teams_listener/hotkeys.py`
- Test: `tests/test_hotkeys.py`

**Interfaces:**
- Produces:
  - `TEAMS_SHORTCUT = "<ctrl>+<shift>+m"`
  - `build_hotkey_map(hotkey: str, follow_teams: bool, on_toggle: Callable[[], None]) -> dict[str, Callable]`: validates with `pynput.keyboard.HotKey.parse` (raises `ValueError` on bad strings). Includes `TEAMS_SHORTCUT` only if `follow_teams` is set and it differs from `hotkey`.
  - `MuteHotkeys(hotkey: str, follow_teams: bool, on_toggle: Callable[[], None])` with `start()` / `stop()`, wrapping `pynput.keyboard.GlobalHotKeys` (which never suppresses keys, so Teams still receives Ctrl+Shift+M). `on_toggle` runs on the pynput thread, so the UI must marshal it.

- [ ] **Step 1: Write failing tests**

```python
def test_map_default():
    assert list(build_hotkey_map("<ctrl>+<alt>+m", False, lambda: None)) == ["<ctrl>+<alt>+m"]

def test_map_with_teams():
    assert set(build_hotkey_map("<ctrl>+<alt>+m", True, lambda: None)) == {"<ctrl>+<alt>+m", "<ctrl>+<shift>+m"}

def test_map_no_duplicate_when_same():
    assert len(build_hotkey_map("<ctrl>+<shift>+m", True, lambda: None)) == 1

def test_invalid_hotkey():
    with pytest.raises(ValueError):
        build_hotkey_map("<ctrl>+<nonsense>", False, lambda: None)
```

- [ ] **Step 2: Run** `pytest tests/test_hotkeys.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: global mute hotkeys`.

### Task 9: UI, tray, entry point, README, benchmark

**Files:**
- Create: `teams_listener/ui/__init__.py`, `teams_listener/ui/app.py`, `teams_listener/ui/tray.py`, `teams_listener/__main__.py`, `run.bat`, `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: `python -m teams_listener` launches the app; `run.bat` activates `.venv` and runs it with `pythonw`.

Window behaviour (Tk, main thread; background callbacks go through a `queue.Queue` drained with `root.after(100, …)`):
- **Idle:** Title entry, **Start** button, Settings button, list of recent meetings (newest first, from `output_dir`) with **Open folder** and **Transcribe again** per row.
- **Recording:** elapsed time, two level meters (Others / Me) from `Recorder.levels()` every 100 ms, a large **Mic** toggle showing **MUTED** (red) or **LIVE** (green), and **Stop**.
- **Stop:** `recorder.stop()` → write `meta.json` (end, devices, events) → `queue.submit(folder)`. Show a progress bar with percent and ETA. On done, show the "Open transcript" link. On error, show the message; audio is kept, and **Transcribe again** retries.
- **Start while a transcription is running:** allowed. Recording takes priority and the queue keeps running; the queue worker runs at lower priority (`psutil` not needed: on Windows call `ctypes.windll.kernel32.SetThreadPriority(GetCurrentThread(), -2)` in the worker). This keeps the Teams call smooth.
- **Settings dialog:** model (small.en / medium.en), model folder (optional), mic (Default communications mic + list from soundcard), hotkey, follow Teams shortcut, delete audio after, output folder. Saved with `save_settings`. Hotkeys restart when they change.
- **Closing the window:** if recording, ask "Stop recording and save?" Yes → stop, finalize and queue, then minimize to the tray. If transcribing, ask before quitting; an unfinished job can be resumed with **Transcribe again**. Otherwise, close to the tray. "Quit" lives in the tray menu.
- **Tray** (`pystray`, `run_detached`): icon drawn with Pillow (grey = idle, red = recording and muted, green = recording and live). Menu items: Show, Start/Stop, Mute/Unmute, Quit.
- **On launch:** if any meeting folder has `tracks/` but no `transcript.md`, show it in the list with a "not transcribed" badge (crash recovery, Review Focus #2).

- [ ] **Step 1: Implement** `tray.py`, `app.py`, `__main__.py` and `run.bat`.
- [ ] **Step 2: Run the full test suite** `pytest -v -m "not slow"`. Expected: all PASS.
- [ ] **Step 3: Manual checklist** (record results in the README "Verified" section):
  1. Teams test call on laptop speakers, mic muted throughout → transcript has Others lines only.
  2. Same, but unmute with `Ctrl+Alt+M` while Teams has focus and speak → Me lines appear at the right timestamps. The tray icon turns green and then red again.
  3. Bluetooth headphones: connect mid-recording, then disconnect → no gap in Others, and `meta.json` shows the device events.
  4. Laptop speakers with mic unmuted (echo) → the remote speech isn't duplicated as Me lines.
  5. Kill `pythonw` from Task Manager mid-recording → relaunch shows "not transcribed" → **Transcribe again** produces a transcript.
  6. Close the window while recording → prompt → audio saved and transcribed.
  7. While recording, Task Manager shows the app at <5% CPU.
- [ ] **Step 4: Benchmark:** transcribe a real 10-minute recording with small.en and with medium.en, and note the minutes needed per meeting hour in the README.
- [ ] **Step 5: Write `README.md`:** setup (`py -3.11 -m venv .venv`, pip install, `run.bat`), first-run model download and the manual-model-folder option for blocked networks, the Teams-side tip (laptop mic + Bluetooth headphones keeps the headphones in high-quality mode), the mute and hotkey behaviour (and why the Teams-shortcut sync can get out of step), benchmark results, a consent note, and the Verified checklist.
- [ ] **Step 6: Commit** `feat: desktop UI, tray, entry point and docs`.
