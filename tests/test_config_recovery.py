"""An unreadable config.json must never be overwritten with defaults (#26).

The file holds the configured stations, the MQTT settings saved from the web
UI, the DigiSnow credentials and the session key, so losing it loses state the
user cannot easily rebuild.
"""
import json
import logging
import pathlib

import pytest

from app import config as config_module
from app.config import DEFAULT_CONFIG, Config


@pytest.fixture(autouse=True)
def _plain_mode(monkeypatch):
    # SUPERVISOR_TOKEN switches Config to the HA add-on path /data/config.json.
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    for var in ("HA_MQTT_HOST", "HA_MQTT_PORT", "HA_MQTT_USERNAME",
                "HA_MQTT_PASSWORD", "SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)


def _backups(path):
    return sorted(path.parent.glob(path.name + ".corrupt-*"))


def _assert_moved_aside(path, original, caplog):
    backups = _backups(path)
    assert len(backups) == 1
    assert backups[0].read_bytes() == original

    errors = [r for r in caplog.records
              if r.name == "app.config" and r.levelno == logging.ERROR]
    assert errors, "the recovery must be logged at ERROR"
    message = errors[-1].getMessage()
    assert str(path) in message
    assert backups[0].name in message

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["stations"] == []
    assert len(on_disk["secret_key"]) == 64


def test_truncated_config_is_moved_aside(tmp_path, caplog):
    path = tmp_path / "config.json"
    original = b'{"stations": [{"id": "font-romeu"'
    path.write_bytes(original)

    with caplog.at_level(logging.ERROR, logger="app.config"):
        cfg = Config(str(path))

    assert cfg.get_stations() == []
    _assert_moved_aside(path, original, caplog)


def test_non_utf8_config_is_moved_aside(tmp_path, caplog):
    path = tmp_path / "config.json"
    original = b"\xff\xfe{\x00"
    path.write_bytes(original)

    with caplog.at_level(logging.ERROR, logger="app.config"):
        Config(str(path))

    _assert_moved_aside(path, original, caplog)


def test_non_object_config_is_moved_aside(tmp_path, caplog):
    path = tmp_path / "config.json"
    original = b"[]"
    path.write_bytes(original)

    with caplog.at_level(logging.ERROR, logger="app.config"):
        Config(str(path))

    _assert_moved_aside(path, original, caplog)


def test_unreadable_config_stops_startup_without_writing(tmp_path, monkeypatch,
                                                         caplog):
    path = tmp_path / "config.json"
    original = json.dumps({"stations": [{"id": "font-romeu"}]}).encode()
    path.write_bytes(original)

    def _fail(self):
        raise OSError(5, "I/O error")

    monkeypatch.setattr(pathlib.Path, "read_bytes", _fail)

    with caplog.at_level(logging.ERROR, logger="app.config"):
        with pytest.raises(RuntimeError):
            Config(str(path))

    monkeypatch.undo()
    assert path.read_bytes() == original
    assert _backups(path) == []
    errors = [r for r in caplog.records
              if r.name == "app.config" and r.levelno == logging.ERROR]
    assert any(str(path) in r.getMessage() for r in errors)


def test_failed_rename_stops_startup_without_writing(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    original = b"{not json"
    path.write_bytes(original)

    def _fail(self, target):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(pathlib.Path, "replace", _fail)

    with pytest.raises(RuntimeError):
        Config(str(path))

    monkeypatch.undo()
    assert path.read_bytes() == original
    assert _backups(path) == []


def test_failed_save_leaves_previous_file_and_no_temp_file(tmp_path,
                                                           monkeypatch):
    path = tmp_path / "config.json"
    cfg = Config(str(path))
    before = path.read_bytes()

    def _fail(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("app.config.os.replace", _fail)

    with pytest.raises(OSError):
        cfg.add_station("font-romeu")

    assert path.read_bytes() == before
    assert list(tmp_path.glob("config.json.*.tmp")) == []


def test_valid_config_loads_unchanged(tmp_path):
    path = tmp_path / "config.json"
    stations = [{"id": "font-romeu", "display_name": "Font-Romeu"}]
    path.write_text(json.dumps({"stations": stations, "secret_key": "k" * 64}),
                    encoding="utf-8")

    cfg = Config(str(path))

    assert cfg.get_stations() == stations
    assert cfg.get("secret_key") == "k" * 64
    assert _backups(path) == []


def test_missing_config_is_created(tmp_path):
    path = tmp_path / "data" / "config.json"

    Config(str(path))

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["stations"] == []
    assert len(on_disk["secret_key"]) == 64
    assert _backups(path) == []


def test_defaults_are_not_shared_with_the_loaded_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(b"{broken")

    cfg = Config(str(path))
    cfg.add_station("font-romeu")

    assert DEFAULT_CONFIG["stations"] == []
    assert config_module.DEFAULT_CONFIG["digisnow_credentials"]["username"] == ""
