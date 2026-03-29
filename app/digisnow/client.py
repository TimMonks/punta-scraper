import json
import logging
import ssl
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from app.digisnow.parser import parse_assets
from app.models import StationData

log = logging.getLogger(__name__)

BROKER_HOST = "wss.mqtt.digibox.app"
BROKER_PORT = 443
WS_PATH = "/mqtt"
TOPIC_PREFIX = "poulpe/DigiSnow"
RECONNECT_DELAY = 10


class DigiSnowClient:
    def __init__(
        self,
        username: str,
        password: str,
        on_station_update: Optional[Callable[[StationData], None]] = None,
    ):
        self._username = username
        self._password = password
        self._on_station_update = on_station_update
        self._subscribed_stations: set[str] = set()
        self._client: mqtt.Client | None = None
        self._connected = False
        self._lock = threading.Lock()
        self._should_run = False

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self, station_ids: list[str]):
        self._should_run = True
        self._subscribed_stations = set(station_ids)
        self._connect()

    def stop(self):
        self._should_run = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
        self._connected = False

    def update_credentials(self, username: str, password: str):
        log.info("Updating DigiSnow MQTT credentials")
        self._username = username
        self._password = password
        if self._client:
            self.stop()
            stations = list(self._subscribed_stations)
            self.start(stations)

    def subscribe_station(self, station_id: str):
        with self._lock:
            self._subscribed_stations.add(station_id)
            if self._connected and self._client:
                topic = f"{TOPIC_PREFIX}/{station_id}/assets/all"
                self._client.subscribe(topic, qos=0)
                log.info("Subscribed to %s", topic)

    def unsubscribe_station(self, station_id: str):
        with self._lock:
            self._subscribed_stations.discard(station_id)
            if self._connected and self._client:
                topic = f"{TOPIC_PREFIX}/{station_id}/assets/all"
                self._client.unsubscribe(topic)
                log.info("Unsubscribed from %s", topic)

    def _connect(self):
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            transport="websockets",
            protocol=mqtt.MQTTv31,
        )
        self._client.username_pw_set(self._username, self._password)
        self._client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self._client.ws_set_options(path=WS_PATH)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._client.reconnect_delay_set(
            min_delay=RECONNECT_DELAY, max_delay=60
        )

        try:
            log.info("Connecting to DigiSnow MQTT broker %s:%d", BROKER_HOST, BROKER_PORT)
            self._client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
            self._client.loop_start()
        except Exception as e:
            log.error("Failed to connect to DigiSnow MQTT: %s", e)
            if self._should_run:
                threading.Timer(RECONNECT_DELAY, self._connect).start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            log.info("Connected to DigiSnow MQTT broker")
            self._connected = True
            # Subscribe to all configured stations
            for station_id in self._subscribed_stations:
                topic = f"{TOPIC_PREFIX}/{station_id}/assets/all"
                client.subscribe(topic, qos=0)
                log.info("Subscribed to %s", topic)
        else:
            log.error("DigiSnow MQTT connect failed: reason_code=%s", reason_code)
            self._connected = False

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        log.warning("Disconnected from DigiSnow MQTT: reason_code=%s", reason_code)
        self._connected = False

    def _on_message(self, client, userdata, msg):
        try:
            # Extract station_id from topic: poulpe/DigiSnow/{station_id}/assets/all
            parts = msg.topic.split("/")
            if len(parts) >= 3:
                station_id = parts[2]
            else:
                log.warning("Unexpected topic format: %s", msg.topic)
                return

            payload = json.loads(msg.payload.decode("utf-8"))
            station_data = parse_assets(station_id, payload)

            if self._on_station_update:
                self._on_station_update(station_data)

        except Exception as e:
            log.error("Error processing DigiSnow message: %s", e, exc_info=True)
