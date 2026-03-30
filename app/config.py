import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def is_ha_addon() -> bool:
    """Detect if running as a Home Assistant add-on."""
    return os.environ.get("SUPERVISOR_TOKEN") is not None


def get_ha_addon_options() -> dict:
    """Read add-on options from /data/options.json (set by HA Supervisor)."""
    options_path = Path("/data/options.json")
    if options_path.exists():
        try:
            return json.loads(options_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_ha_mqtt_service() -> dict | None:
    """Query HA Supervisor API for MQTT service credentials."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    try:
        import requests
        resp = requests.get(
            "http://supervisor/services/mqtt",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if resp.ok:
            data = resp.json().get("data", {})
            return {
                "host": data.get("host", ""),
                "port": data.get("port", 1883),
                "username": data.get("username", ""),
                "password": data.get("password", ""),
            }
    except Exception as e:
        log.warning("Failed to query HA MQTT service: %s", e)
    return None

DEFAULT_STATUS_MAPPING = {
    "open": "OPEN",
    "closed": "CLOSED",
    "should-open": "FORECAST",
    "risk-of-closure": "RISK",
    "temporary-stop": "TEMP_STOP",
    "reserved": "RESERVED",
    "out-of-period": "OFF_SEASON",
}

DEFAULT_CONFIG = {
    "ha_mqtt": {
        "host": "",
        "port": 1883,
        "username": "",
        "password": "",
        "discovery_prefix": "homeassistant",
        "state_topic_prefix": "digisnow",
    },
    "status_mapping": DEFAULT_STATUS_MAPPING,
    "stations": [],
    "digisnow_credentials": {
        "username": "",
        "password": "",
        "last_fetched": "",
    },
    "credential_refresh_hours": 24,
    "secret_key": "",
}


class Config:
    def __init__(self, config_path: str = "app/data/config.json"):
        self._ha_addon = is_ha_addon()
        if self._ha_addon:
            config_path = "/data/config.json"
            log.info("Running as HA add-on")
        self._path = Path(config_path)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    @property
    def ha_addon(self) -> bool:
        return self._ha_addon

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                log.info("Config loaded from %s", self._path)
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to load config, using defaults: %s", e)
                self._data = {}

        # Merge defaults for missing keys
        for key, default in DEFAULT_CONFIG.items():
            if key not in self._data:
                self._data[key] = default
            elif isinstance(default, dict):
                for sub_key, sub_default in default.items():
                    if sub_key not in self._data[key]:
                        self._data[key][sub_key] = sub_default

        # Apply environment variable overrides
        self._apply_env_overrides()

        # Apply HA add-on overrides
        if self._ha_addon:
            self._apply_ha_addon_overrides()

        self._save()

    def _apply_env_overrides(self):
        env_map = {
            "HA_MQTT_HOST": ("ha_mqtt", "host"),
            "HA_MQTT_PORT": ("ha_mqtt", "port"),
            "HA_MQTT_USERNAME": ("ha_mqtt", "username"),
            "HA_MQTT_PASSWORD": ("ha_mqtt", "password"),
            "SECRET_KEY": ("secret_key", None),
        }
        for env_var, path in env_map.items():
            val = os.environ.get(env_var)
            if val is not None:
                if path[1] is None:
                    self._data[path[0]] = val
                else:
                    if path[1] == "port":
                        val = int(val)
                    self._data[path[0]][path[1]] = val

        # Generate secret key if missing
        if not self._data.get("secret_key"):
            import secrets
            self._data["secret_key"] = secrets.token_hex(32)

    def _apply_ha_addon_overrides(self):
        """Apply HA add-on options and auto-discover MQTT broker."""
        options = get_ha_addon_options()

        # Auto-discover MQTT broker from Supervisor
        mqtt_service = get_ha_mqtt_service()
        if mqtt_service and not self._data["ha_mqtt"]["host"]:
            self._data["ha_mqtt"].update(mqtt_service)
            log.info("Auto-configured HA MQTT from Supervisor: %s:%s",
                     mqtt_service["host"], mqtt_service["port"])

        # Auto-add stations from add-on options
        if options.get("stations") and not self._data["stations"]:
            for station_id in options["stations"]:
                self._data["stations"].append({
                    "id": station_id,
                    "display_name": station_id,
                    "enabled": True,
                    "tracked_lifts": [],
                    "tracked_slopes": [],
                    "track_all": True,
                })
            log.info("Auto-configured stations: %s", options["stations"])

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get(self, *keys: str, default: Any = None) -> Any:
        with self._lock:
            val = self._data
            for k in keys:
                if isinstance(val, dict):
                    val = val.get(k, default)
                else:
                    return default
            return val

    def set(self, *keys_and_value: Any):
        """Set a nested config value. Last arg is the value."""
        with self._lock:
            keys = keys_and_value[:-1]
            value = keys_and_value[-1]
            target = self._data
            for k in keys[:-1]:
                target = target.setdefault(k, {})
            target[keys[-1]] = value
            self._save()

    def get_stations(self) -> list[dict]:
        return self.get("stations", default=[])

    def add_station(self, station_id: str, display_name: str = "") -> dict:
        with self._lock:
            for s in self._data["stations"]:
                if s["id"] == station_id:
                    return s
            station = {
                "id": station_id,
                "display_name": display_name or station_id,
                "enabled": True,
                "tracked_lifts": [],
                "tracked_slopes": [],
                "track_all": True,
            }
            self._data["stations"].append(station)
            self._save()
            return station

    def remove_station(self, station_id: str) -> bool:
        with self._lock:
            before = len(self._data["stations"])
            self._data["stations"] = [
                s for s in self._data["stations"] if s["id"] != station_id
            ]
            if len(self._data["stations"]) < before:
                self._save()
                return True
            return False

    def get_station(self, station_id: str) -> dict | None:
        with self._lock:
            for s in self._data["stations"]:
                if s["id"] == station_id:
                    return s
            return None

    def update_station(self, station_id: str, updates: dict):
        with self._lock:
            for s in self._data["stations"]:
                if s["id"] == station_id:
                    s.update(updates)
                    self._save()
                    return True
            return False

    @property
    def data(self) -> dict:
        with self._lock:
            return self._data.copy()
