import pytest

from teams_listener.hotkeys import TEAMS_SHORTCUT, build_hotkey_map


def test_map_default():
    assert list(build_hotkey_map("<ctrl>+<alt>+m", False, lambda: None)) == ["<ctrl>+<alt>+m"]


def test_map_with_teams():
    assert set(build_hotkey_map("<ctrl>+<alt>+m", True, lambda: None)) == {"<ctrl>+<alt>+m", TEAMS_SHORTCUT}


def test_map_no_duplicate_when_same():
    assert len(build_hotkey_map("<ctrl>+<shift>+m", True, lambda: None)) == 1


def test_invalid_hotkey():
    with pytest.raises(ValueError):
        build_hotkey_map("<ctrl>+<nonsense>", False, lambda: None)


def test_callback_is_wired():
    hits = []
    m = build_hotkey_map("<ctrl>+<alt>+m", False, lambda: hits.append(1))
    m["<ctrl>+<alt>+m"]()
    assert hits == [1]
