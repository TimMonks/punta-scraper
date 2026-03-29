import logging
import re
import threading
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

# Known fallback credentials (extracted from widget JS 2026-03-29)
FALLBACK_USERNAME = "digiPoulpe"
FALLBACK_PASSWORD = "WyumfcItTe2ZJ1HhOovJ"


class CredentialFetcher:
    def __init__(self, config, on_credentials_updated=None):
        self._config = config
        self._on_updated = on_credentials_updated
        self._timer: threading.Timer | None = None
        self._refresh_hours = config.get("credential_refresh_hours", default=24)

    def start(self):
        self._schedule_next()

    def stop(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def fetch_now(self, station_id: str = "valfrejus") -> tuple[str, str]:
        """Fetch current MQTT credentials from widget JS. Returns (username, password)."""
        try:
            username, password = self._extract_from_widget(station_id)
            self._config.set("digisnow_credentials", "username", username)
            self._config.set("digisnow_credentials", "password", password)
            self._config.set(
                "digisnow_credentials",
                "last_fetched",
                datetime.now(timezone.utc).isoformat(),
            )
            log.info("DigiSnow MQTT credentials updated successfully")
            if self._on_updated:
                self._on_updated(username, password)
            return username, password
        except Exception as e:
            log.warning("Failed to fetch credentials: %s", e)
            return self._get_cached_or_fallback()

    def get_credentials(self) -> tuple[str, str]:
        """Get cached credentials, or fetch if none cached."""
        cached_user = self._config.get("digisnow_credentials", "username", default="")
        cached_pass = self._config.get("digisnow_credentials", "password", default="")
        if cached_user and cached_pass:
            return cached_user, cached_pass
        # Try to fetch from first configured station
        stations = self._config.get_stations()
        station_id = stations[0]["id"] if stations else "valfrejus"
        return self.fetch_now(station_id)

    def _get_cached_or_fallback(self) -> tuple[str, str]:
        cached_user = self._config.get("digisnow_credentials", "username", default="")
        cached_pass = self._config.get("digisnow_credentials", "password", default="")
        if cached_user and cached_pass:
            return cached_user, cached_pass
        log.warning("Using fallback credentials")
        return FALLBACK_USERNAME, FALLBACK_PASSWORD

    def _extract_from_widget(self, station_id: str) -> tuple[str, str]:
        """Fetch the DigiSnow widget JS and extract MQTT credentials."""
        # Step 1: Get widget version
        version_url = f"https://{station_id}.digisnow.app/v1/widget/widgetversion"
        resp = requests.get(version_url, timeout=10)
        resp.raise_for_status()
        # Response can be JSON like {"widgetVersion":"1.0.42"} or plain text
        try:
            version_data = resp.json()
            version = version_data.get("widgetVersion", resp.text.strip().strip('"'))
        except (ValueError, AttributeError):
            version = resp.text.strip().strip('"')
        log.debug("Widget version for %s: %s", station_id, version)

        # Step 2: Fetch versioned widget JS
        js_url = f"https://{station_id}.digisnow.app/widget/widget-digisnow.{version}.js"
        resp = requests.get(js_url, timeout=30)
        resp.raise_for_status()
        js_content = resp.text

        # Step 3: Extract MQTT credentials
        # The config is structured as: mqtt:{host:"...",port:"...",userName:"...",password:"..."}
        # Find the mqtt config block and extract userName and password from it
        username, password = self._extract_mqtt_creds(js_content)

        if not username or not password:
            raise ValueError("Could not extract MQTT credentials from widget JS")

        log.info("Extracted credentials: user=%s", username)
        return username, password

    def _extract_mqtt_creds(self, js: str) -> tuple[str | None, str | None]:
        # Look for the mqtt config object: mqtt:{host:"...",userName:"...",password:"..."}
        # or mqtt:{"host":"...","userName":"...","password":"..."}
        mqtt_block = re.search(r'mqtt\s*:\s*\{([^}]{10,200})\}', js)
        if not mqtt_block:
            return None, None

        block = mqtt_block.group(1)
        username = None
        password = None

        for name in ["userName", "username"]:
            m = re.search(rf'{name}\s*:\s*["\']([^"\']+)["\']', block)
            if m:
                username = m.group(1)
                break

        for name in ["password"]:
            m = re.search(rf'{name}\s*:\s*["\']([^"\']+)["\']', block)
            if m:
                password = m.group(1)
                break

        return username, password

    def _schedule_next(self):
        interval = self._refresh_hours * 3600
        self._timer = threading.Timer(interval, self._periodic_refresh)
        self._timer.daemon = True
        self._timer.start()

    def _periodic_refresh(self):
        stations = self._config.get_stations()
        station_id = stations[0]["id"] if stations else "valfrejus"
        log.info("Periodic credential refresh using station: %s", station_id)
        self.fetch_now(station_id)
        self._schedule_next()
