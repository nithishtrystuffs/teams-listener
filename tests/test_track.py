import json

import numpy as np

from teams_listener.audio.track import Resampler, TrackWriter


def test_resampler_48k_stereo_to_16k_mono():
    r = Resampler(48000, 2)
    out = np.concatenate([r.process(np.full((4800, 2), 0.5, np.float32)) for _ in range(10)])
    assert out.dtype == np.int16 and abs(len(out) - 16000) < 400  # soxr HQ holds ~341 samples (21 ms) of filter delay
    assert abs(int(out[-1000:].mean()) - 16383) < 300


def test_resampler_clips_out_of_range():
    r = Resampler(16000, 1)
    out = np.concatenate([r.process(np.full((1600, 1), 3.0, np.float32)) for _ in range(5)])
    assert out[-100:].min() >= 32000 and out.max() <= 32767


def test_first_write_sets_offset(tmp_path):
    w = TrackWriter(tmp_path, "others-1", "others", "Speakers", clock_start=100.0)
    w.write(np.ones(1600, np.int16), arrival_time=102.1)  # ends at 2.1 s -> starts at 2.0 s
    w.close()
    assert w.offset_samples == 32000
    side = json.loads((tmp_path / "tracks/others-1.json").read_text())
    assert side == {"kind": "others", "device": "Speakers", "offset_samples": 32000}


def test_gap_filled_with_silence(tmp_path):
    w = TrackWriter(tmp_path, "others-1", "others", "Speakers", clock_start=0.0)
    w.write(np.ones(1600, np.int16), arrival_time=0.1)
    w.write(np.ones(1600, np.int16), arrival_time=5.1)  # 4.9 s with no frames delivered
    w.close()
    data = np.fromfile(tmp_path / "tracks/others-1.pcm", np.int16)
    assert len(data) == round(5.1 * 16000)
    assert (data[1600:-1600] == 0).all()


def test_small_jitter_not_filled(tmp_path):
    w = TrackWriter(tmp_path, "me-1", "me", "Mic", clock_start=0.0)
    w.write(np.ones(1600, np.int16), 0.1)
    w.write(np.ones(1600, np.int16), 0.25)
    w.close()
    assert w.samples_written == 3200


def test_empty_write_is_noop(tmp_path):
    w = TrackWriter(tmp_path, "me-1", "me", "Mic", clock_start=0.0)
    w.write(np.zeros(0, np.int16), 1.0)
    assert w.offset_samples is None and w.samples_written == 0
    w.close()
