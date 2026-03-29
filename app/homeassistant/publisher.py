import json
import logging
import re
import threading
from typing import Optional

import paho.mqtt.client as mqtt

from app.homeassistant.status_mapper import StatusMapper
from app.models import LiftStatus, SlopeStatus, StationData

log = logging.getLogger(__name__)

RECONNECT_DELAY = 10


def _slugify(text: str) -> str:
    """Convert text to a slug suitable for MQTT topics and entity IDs."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


class HAPublisher:
    def __init__(self, config, status_mapper: StatusMapper):
        self._config = config
        self._mapper = status_mapper
        self._client: mqtt.Client | None = None
        self._connected = False
        self._should_run = False
        self._lock = threading.Lock()
        # Cache of last known station data for republishing on reconnect
        self._station_cache: dict[str, StationData] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self):
        self._should_run = True
        self._connect()

    def stop(self):
        self._should_run = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
        self._connected = False

    def publish_station_data(self, station_data: StationData):
        """Publish lift/slope status updates to HA MQTT broker."""
        self._station_cache[station_data.station_id] = station_data

        if not self._connected:
            log.debug("HA MQTT not connected, caching data for later")
            return

        station_config = self._config.get_station(station_data.station_id)
        if not station_config:
            return

        track_all = station_config.get("track_all", True)
        tracked_lifts = set(station_config.get("tracked_lifts", []))
        tracked_slopes = set(station_config.get("tracked_slopes", []))

        prefix = self._config.get("ha_mqtt", "state_topic_prefix", default="digisnow")
        discovery_prefix = self._config.get(
            "ha_mqtt", "discovery_prefix", default="homeassistant"
        )
        sid = station_data.station_id

        for sector in station_data.sectors.values():
            for lift in sector.lifts:
                if not track_all and lift.id not in tracked_lifts:
                    continue
                mapped = self._mapper.map_status(lift.opening_status)
                lift.mapped_status = mapped
                self._publish_entity(
                    discovery_prefix, prefix, sid, "lift", lift
                )

            for slope in sector.slopes:
                if not track_all and slope.id not in tracked_slopes:
                    continue
                mapped = self._mapper.map_status(slope.opening_status)
                slope.mapped_status = mapped
                self._publish_entity(
                    discovery_prefix, prefix, sid, "slope", slope
                )

    def remove_station_entities(self, station_id: str, station_data: StationData | None = None):
        """Remove all HA entities for a station by publishing empty discovery payloads."""
        if not self._connected or not station_data:
            return

        discovery_prefix = self._config.get(
            "ha_mqtt", "discovery_prefix", default="homeassistant"
        )

        for sector in station_data.sectors.values():
            for lift in sector.lifts:
                unique_id = f"digisnow_{station_id}_lift_{lift.id}"
                topic = f"{discovery_prefix}/sensor/{unique_id}/config"
                self._client.publish(topic, "", retain=True)
            for slope in sector.slopes:
                unique_id = f"digisnow_{station_id}_slope_{slope.id}"
                topic = f"{discovery_prefix}/sensor/{unique_id}/config"
                self._client.publish(topic, "", retain=True)

        self._station_cache.pop(station_id, None)

    def _publish_entity(
        self,
        discovery_prefix: str,
        state_prefix: str,
        station_id: str,
        entity_type: str,  # "lift" or "slope"
        entity: LiftStatus | SlopeStatus,
    ):
        unique_id = f"digisnow_{station_id}_{entity_type}_{entity.id}"
        state_topic = f"{state_prefix}/{station_id}/{entity_type}/{entity.id}/state"
        attrs_topic = f"{state_prefix}/{station_id}/{entity_type}/{entity.id}/attributes"

        # Publish discovery config
        discovery_topic = f"{discovery_prefix}/sensor/{unique_id}/config"
        entity_slug = _slugify(entity.name)

        icon = "mdi:ski-lift" if entity_type == "lift" else "mdi:ski"
        discovery_payload = {
            "name": entity.name,
            "unique_id": unique_id,
            "object_id": f"{entity_slug}_status",
            "state_topic": state_topic,
            "json_attributes_topic": attrs_topic,
            "icon": icon,
            "device": {
                "name": f"DigiSnow {station_id.title()}",
                "identifiers": [f"digisnow_{station_id}"],
                "manufacturer": "DigiSnow Scraper",
                "model": "Ski Station Monitor",
            },
        }

        self._client.publish(
            discovery_topic,
            json.dumps(discovery_payload),
            retain=True,
        )

        # Publish state
        self._client.publish(state_topic, entity.mapped_status, retain=True)

        # Publish attributes
        if isinstance(entity, LiftStatus):
            attrs = {
                "raw_status": entity.opening_status,
                "type": entity.type,
                "sector": entity.sector_name,
                "comments": entity.comments,
                "opening_hours": entity.opening_hours,
                "season": entity.season,
                "last_update": entity.last_update,
            }
        else:
            attrs = {
                "raw_status": entity.opening_status,
                "difficulty": entity.difficulty,
                "sector": entity.sector_name,
                "opening_hours": entity.opening_hours,
                "last_update": entity.last_update,
            }

        self._client.publish(attrs_topic, json.dumps(attrs), retain=True)

    def _connect(self):
        ha_mqtt = self._config.get("ha_mqtt", default={})
        host = ha_mqtt.get("host", "")
        if not host:
            log.warning("HA MQTT host not configured, publisher disabled")
            return

        port = int(ha_mqtt.get("port", 1883))
        username = ha_mqtt.get("username", "")
        password = ha_mqtt.get("password", "")

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        self._client.reconnect_delay_set(
            min_delay=RECONNECT_DELAY, max_delay=60
        )

        try:
            log.info("Connecting to HA MQTT broker %s:%d", host, port)
            self._client.connect(host, port, keepalive=60)
            self._client.loop_start()
        except Exception as e:
            log.error("Failed to connect to HA MQTT: %s", e)
            if self._should_run:
                threading.Timer(RECONNECT_DELAY, self._connect).start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            log.info("Connected to HA MQTT broker")
            self._connected = True
            # Republish cached data
            for station_data in self._station_cache.values():
                self.publish_station_data(station_data)
        else:
            log.error("HA MQTT connect failed: reason_code=%s", reason_code)
            self._connected = False

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        log.warning("Disconnected from HA MQTT: reason_code=%s", reason_code)
        self._connected = False
