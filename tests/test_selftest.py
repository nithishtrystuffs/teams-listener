from pathlib import Path

from teams_listener.selftest import run_selftest


def test_selftest_records_and_transcribes(tmp_path):
    from tests.test_recorder import FakeDevice, FakeClock
    from tests.test_pipeline import FakeEngine, O
    out = FakeDevice("a", "Speakers", 40); mic = FakeDevice("m", "Mic", 40)
    out.clock = mic.clock = FakeClock()
    r = run_selftest(Path("tests/fixtures/fox.wav"), 0.3, FakeEngine(others=[O(0, 1, "quick brown fox")]),
                     lambda: [out], lambda n: mic)
    assert r["outputs"] == ["Speakers"] and r["mic"] == "Mic"
    assert r["recorded_s"]["others"] > 0 and "fox" in r["text"]
