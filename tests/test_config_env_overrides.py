"""Empty environment variables must not override persisted config (Switchboard#89).

docker-compose passes every mapped variable as ``${VAR:-}``, so an entry left
blank in .env reaches the container as an empty string.
"""
import json

import pytest

from app.config import Config


@pytest.fixture(autouse=True)
def _plain_mode(monkeypatch):
    # SUPERVISOR_TOKEN switches Config to the HA add-on path /data/config.json.
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    for var in ("HA_MQTT_HOST", "HA_MQTT_PORT", "HA_MQTT_USERNAME",
                "HA_MQTT_PASSWORD", "SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_persisted_key_survives_empty_secret_key(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"secret_key": "k" * 64}), encoding="utf-8")
    monkeypatch.setenv("SECRET_KEY", "")

    cfg = Config(str(path))

    assert cfg.get("secret_key") == "k" * 64
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["secret_key"] == "k" * 64


def test_generated_key_is_stable_across_boots(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setenv("SECRET_KEY", "")

    first = Config(str(path)).get("secret_key")
    second = Config(str(path)).get("secret_key")

    assert len(first) == 64
    assert first == second


def test_empty_mqtt_host_keeps_configured_host(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"ha_mqtt": {"host": "mqtt.lan"}}),
                    encoding="utf-8")
    monkeypatch.setenv("HA_MQTT_HOST", "")

    assert Config(str(path)).get("ha_mqtt", "host") == "mqtt.lan"


def test_non_empty_env_values_still_override(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"secret_key": "k" * 64}), encoding="utf-8")
    monkeypatch.setenv("SECRET_KEY", "pinned-value")
    monkeypatch.setenv("HA_MQTT_PORT", "1884")

    cfg = Config(str(path))

    assert cfg.get("secret_key") == "pinned-value"
    assert cfg.get("ha_mqtt", "port") == 1884
