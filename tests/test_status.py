from teams_listener.ui.status import mic_display


def test_idle():
    assert mic_display(recording=False, muted=True, mic_name=None)[0] == "idle"


def test_no_mic_is_not_shown_as_live():
    state, text = mic_display(recording=True, muted=False, mic_name=None)
    assert state == "nomic" and "NO MICROPHONE" in text and "LIVE" not in text


def test_muted_and_live():
    assert mic_display(True, True, "Laptop Mic")[0] == "muted"
    state, text = mic_display(True, False, "Laptop Mic")
    assert state == "live" and "Laptop Mic" in text
