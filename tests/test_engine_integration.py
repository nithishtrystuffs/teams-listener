from pathlib import Path

import pytest

from teams_listener.transcribe.engine import WhisperEngine

FIXTURE = Path(__file__).parent / "fixtures" / "fox.wav"


@pytest.mark.slow
def test_whisper_tiny_transcribes_fixture():
    progress = []
    segs = WhisperEngine("tiny.en").transcribe(FIXTURE, "Others", progress.append)
    text = " ".join(s.text for s in segs).lower()
    assert "fox" in text
    assert all(s.speaker == "Others" for s in segs)
    assert progress[-1] == 1.0
