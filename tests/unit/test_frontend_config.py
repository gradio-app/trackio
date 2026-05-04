from pathlib import Path

from trackio import frontend_config


def _make_frontend_dir(root: Path, name: str) -> Path:
    frontend_dir = root / name
    frontend_dir.mkdir(parents=True, exist_ok=True)
    (frontend_dir / "index.html").write_text("<!doctype html><title>ok</title>")
    return frontend_dir


def test_persisted_frontend_config_round_trip(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    config_path = config_home / "config.json"
    monkeypatch.setattr(frontend_config, "TRACKIO_USER_HOME", config_home)
    monkeypatch.setattr(frontend_config, "TRACKIO_CONFIG_PATH", config_path)

    frontend_dir = _make_frontend_dir(tmp_path, "starter")

    saved_path = frontend_config.set_persisted_frontend_dir(frontend_dir)
    assert saved_path == frontend_dir.resolve()
    assert frontend_config.get_persisted_frontend_dir() == frontend_dir.resolve()
    assert frontend_config.unset_persisted_frontend_dir() is True
    assert frontend_config.get_persisted_frontend_dir() is None


def test_resolve_frontend_prefers_argument_over_env_and_config(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    config_path = config_home / "config.json"
    monkeypatch.setattr(frontend_config, "TRACKIO_USER_HOME", config_home)
    monkeypatch.setattr(frontend_config, "TRACKIO_CONFIG_PATH", config_path)

    arg_dir = _make_frontend_dir(tmp_path, "arg")
    env_dir = _make_frontend_dir(tmp_path, "env")
    config_dir = _make_frontend_dir(tmp_path, "config")
    frontend_config.set_persisted_frontend_dir(config_dir)
    monkeypatch.setenv("TRACKIO_FRONTEND_DIR", str(env_dir))

    resolved = frontend_config.resolve_frontend_dir(arg_dir)

    assert resolved.path == arg_dir.resolve()
    assert resolved.source == "argument"
    assert resolved.is_custom is True


def test_resolve_frontend_invalid_nonempty_argument_falls_back_to_starter(
    tmp_path, monkeypatch
):
    invalid_dir = tmp_path / "invalid"
    invalid_dir.mkdir()
    (invalid_dir / "notes.txt").write_text("not a frontend")
    starter_dir = _make_frontend_dir(tmp_path, "starter")
    bundled_dir = _make_frontend_dir(tmp_path, "bundled")

    monkeypatch.setattr(frontend_config, "STARTER_FRONTEND_DIR", starter_dir)
    monkeypatch.setattr(frontend_config, "BUNDLED_FRONTEND_DIR", bundled_dir)

    resolved = frontend_config.resolve_frontend_dir(invalid_dir)

    assert resolved.path == starter_dir.resolve()
    assert resolved.source == "starter"
    assert resolved.used_fallback is True
    assert resolved.requested_path == invalid_dir.resolve()


def test_resolve_frontend_missing_argument_bootstraps_starter(tmp_path, monkeypatch):
    requested_dir = tmp_path / "missing"
    starter_dir = _make_frontend_dir(tmp_path, "starter")
    (starter_dir / "app.js").write_text("console.log('starter');")
    bundled_dir = _make_frontend_dir(tmp_path, "bundled")

    monkeypatch.setattr(frontend_config, "STARTER_FRONTEND_DIR", starter_dir)
    monkeypatch.setattr(frontend_config, "BUNDLED_FRONTEND_DIR", bundled_dir)

    resolved = frontend_config.resolve_frontend_dir(requested_dir)

    assert resolved.path == requested_dir.resolve()
    assert resolved.source == "argument"
    assert resolved.is_custom is True
    assert (requested_dir / "index.html").is_file()
    assert (requested_dir / "app.js").read_text() == "console.log('starter');"


def test_resolve_frontend_empty_argument_bootstraps_starter(tmp_path, monkeypatch):
    requested_dir = tmp_path / "empty"
    requested_dir.mkdir()
    starter_dir = _make_frontend_dir(tmp_path, "starter")
    (starter_dir / "styles.css").write_text("body { color: red; }")
    bundled_dir = _make_frontend_dir(tmp_path, "bundled")

    monkeypatch.setattr(frontend_config, "STARTER_FRONTEND_DIR", starter_dir)
    monkeypatch.setattr(frontend_config, "BUNDLED_FRONTEND_DIR", bundled_dir)

    resolved = frontend_config.resolve_frontend_dir(requested_dir)

    assert resolved.path == requested_dir.resolve()
    assert resolved.source == "argument"
    assert resolved.is_custom is True
    assert (requested_dir / "index.html").is_file()
    assert (requested_dir / "styles.css").read_text() == "body { color: red; }"
