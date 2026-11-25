import numpy as np
import soundfile as sf

from teams_listener.audio.mixer import finalize_meeting, load_tracks, mix_to_file
from tests.helpers import make_track


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
    mix_to_file(tr, 50123, tmp_path / "a.flac", block=777)
    mix_to_file(tr, 50123, tmp_path / "b.flac", block=10**7)
    assert (sf.read(tmp_path / "a.flac", dtype="int16")[0] == sf.read(tmp_path / "b.flac", dtype="int16")[0]).all()


def test_finalize_with_no_others_tracks(tmp_path):
    make_track(tmp_path, "me-1", "me", 0, np.ones(32000, np.int16))
    others, me = finalize_meeting(tmp_path)
    d, _ = sf.read(others, dtype="int16")
    assert len(d) == 32000 and not d.any()


def test_finalize_truncated_pcm(tmp_path):
    make_track(tmp_path, "me-1", "me", 0, np.ones(1000, np.int16))
    with open(tmp_path / "tracks/me-1.pcm", "ab") as f:
        f.write(b"\x01")  # crash mid-sample
    _, me = finalize_meeting(tmp_path)
    assert len(sf.read(me, dtype="int16")[0]) == 1000


def test_finalize_no_tracks_gives_one_second_silence(tmp_path):
    others, me = finalize_meeting(tmp_path)
    assert len(sf.read(others, dtype="int16")[0]) == 16000 and len(sf.read(me, dtype="int16")[0]) == 16000


def test_pcm_without_sidecar_skipped(tmp_path):
    (tmp_path / "tracks").mkdir()
    np.ones(10, np.int16).tofile(tmp_path / "tracks/orphan.pcm")
    assert load_tracks(tmp_path) == []


def test_finalize_idempotent(tmp_path):
    make_track(tmp_path, "others-1", "others", 0, np.full(500, 7, np.int16))
    finalize_meeting(tmp_path)
    others, _ = finalize_meeting(tmp_path)
    assert len(sf.read(others, dtype="int16")[0]) == 500
