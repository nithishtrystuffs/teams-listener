from teams_listener.config import Settings, load_settings, save_settings


def test_missing_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "s.json") == Settings()


def test_roundtrip(tmp_path):
    s = Settings(model="medium.en", follow_teams_shortcut=True)
    save_settings(s, tmp_path / "s.json")
    assert load_settings(tmp_path / "s.json") == s


def test_save_creates_parent_dirs(tmp_path):
    save_settings(Settings(), tmp_path / "a" / "b" / "s.json")
    assert (tmp_path / "a" / "b" / "s.json").exists()


def test_corrupt_file_gives_defaults_and_backup(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    assert load_settings(p) == Settings()
    assert (tmp_path / "s.json.bak").exists()


def test_unknown_keys_ignored_and_bad_model_reset(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"model": "large-v3", "zzz": 1}')
    assert load_settings(p).model == "small.en"


def test_invalid_theme_resets(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"theme": "neon"}')
    assert load_settings(p).theme == "system"
    assert Settings().theme == "system"
