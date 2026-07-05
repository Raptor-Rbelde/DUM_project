from sentinel.config import settings as settings_module


def test_load_settings_reads_project_env_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "data" / "sentinel.sqlite"))
    (tmp_path / ".env").write_text("ELEVENLABS_API_KEY=file-key\n", encoding="utf-8")

    loaded = settings_module.load_settings()

    assert loaded.elevenlabs_api_key == "file-key"


def test_load_settings_does_not_override_exported_env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "exported-key")
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "data" / "sentinel.sqlite"))
    (tmp_path / ".env").write_text("ELEVENLABS_API_KEY=file-key\n", encoding="utf-8")

    loaded = settings_module.load_settings()

    assert loaded.elevenlabs_api_key == "exported-key"
