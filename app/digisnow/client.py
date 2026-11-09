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
        self._lock = threading.RLock()
        self._should_run = False
        self._generation = 0
        self._retry_timer: threading.Timer | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self, station_ids: list[str]):
        with self._lock:
            old_client = self._retire_locked()
            self._should_run = True
            self._subscribed_stations = set(station_ids)
            generation = self._generation
        self._dispose(old_client)
        self._connect(generation)

    def stop(self):
        with self._lock:
            self._should_run = False
            old_client = self._retire_locked()
        self._dispose(old_client)

    def _retire_locked(self):
        """Invalidate attempts before detaching; the caller holds _lock."""
        self._generation += 1
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None
        old_client, self._client = self._client, None
        self._connected = False
        return old_client

    @staticmethod
    def _dispose(client):
        # loop_stop can join a callback thread: never hold _lock here.
        if client is not None:
            log.info("Stopping DigiSnow MQTT connection")
            client.loop_stop()
            client.disconnect()

    def update_credentials(self, username: str, password: str):
        log.info("Updating DigiSnow MQTT credentials")
        with self._lock:
            self._username = username
            self._password = password
            if not self._should_run:
                return
            old_client = self._retire_locked()
            generation = self._generation
        self._dispose(old_client)
        self._connect(generation)

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

    def _connect(self, generation):
        with self._lock:
            if (not self._should_run or generation != self._generation
                    or self._client is not None):
                return
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                transport="websockets",
                protocol=mqtt.MQTTv31,
            )
            client.username_pw_set(self._username, self._password)
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            client.ws_set_options(path=WS_PATH)
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            client.reconnect_delay_set(min_delay=RECONNECT_DELAY, max_delay=60)
            self._client = client
        try:
            log.info("Connecting to DigiSnow MQTT broker %s:%d", BROKER_HOST, BROKER_PORT)
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
            with self._lock:
                if self._owns(client, generation):
                    # Starting the non-blocking loop and ownership validation
                    # are atomic with stop; connect itself never holds _lock.
                    client.loop_start()
                    return
        except Exception as e:
            with self._lock:
                if self._owns(client, generation):
                    self._client = None
                    self._connected = False
                    log.error("Failed to connect to DigiSnow MQTT: %s", e)
                    timer = threading.Timer(
                        RECONNECT_DELAY, lambda: self._retry(generation, timer)
                    )
                    timer.daemon = True
                    self._retry_timer = timer
                    timer.start()
        self._dispose(client)

    def _owns(self, client, generation=None):
        return (self._should_run and self._client is client
                and (generation is None or generation == self._generation))

    def _retry(self, generation, timer):
        with self._lock:
            if (not self._should_run or generation != self._generation
                    or self._retry_timer is not timer):
                return
            self._retry_timer = None
        self._connect(generation)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        with self._lock:
            if not self._owns(client):
                return
            if reason_code == 0:
                log.info("Connected to DigiSnow MQTT broker")
                self._connected = True
                for station_id in self._subscribed_stations:
                    topic = f"{TOPIC_PREFIX}/{station_id}/assets/all"
                    client.subscribe(topic, qos=0)
                    log.info("Subscribed to %s", topic)
            else:
                log.error("DigiSnow MQTT connect failed: reason_code=%s", reason_code)
                self._connected = False

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        with self._lock:
            if not self._owns(client):
                return
            # Requested stops are logged by _dispose after retirement.
            if reason_code == 0:
                log.info("Disconnected from DigiSnow MQTT: reason_code=%s", reason_code)
            else:
                log.warning("Disconnected from DigiSnow MQTT: reason_code=%s", reason_code)
            self._connected = False

    def _on_message(self, client, userdata, msg):
        try:
            with self._lock:
                if not self._owns(client):
                    return
            # Extract station_id from topic: poulpe/DigiSnow/{station_id}/assets/all
            parts = msg.topic.split("/")
            if len(parts) >= 3:
                station_id = parts[2]
            else:
                log.warning("Unexpected topic format: %s", msg.topic)
                return

            payload = json.loads(msg.payload.decode("utf-8"))
            station_data = parse_assets(station_id, payload)
            with self._lock:
                if not self._owns(client):
                    return
                callback = self._on_station_update
            # Admission belongs to the current client. An admitted callback
            # may finish after stop; run user code without the lifecycle lock
            # so it can itself stop/restart without holding a lock during join.
            if callback:
                callback(station_data)

        except Exception as e:
            log.error("Error processing DigiSnow message: %s", e, exc_info=True)
