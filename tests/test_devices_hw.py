"""Hardware-dependent checks: skipped when the machine has no microphone."""
import pytest
import soundcard as sc

from teams_listener.audio import devices


def _has_mic():
    try:
        return bool(sc.all_microphones())
    except Exception:
        return False


@pytest.mark.skipif(not _has_mic(), reason="no microphone on this machine")
def test_default_communications_mic_resolves_after_soundcard_init():
    comm_id = devices._default_communications_capture_id()
    assert comm_id in [m.id for m in sc.all_microphones()]


@pytest.mark.skipif(not _has_mic(), reason="no microphone on this machine")
def test_default_communications_mic_resolves_from_worker_thread():
    import threading
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("id", devices._default_communications_capture_id()))
    t.start(); t.join()
    assert out["id"] in [m.id for m in sc.all_microphones()]
