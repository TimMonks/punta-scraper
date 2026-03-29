import logging
import os
import signal
import sys
import threading

from app.config import Config
from app.digisnow.client import DigiSnowClient
from app.digisnow.credential_fetcher import CredentialFetcher
from app.homeassistant.publisher import HAPublisher
from app.homeassistant.status_mapper import StatusMapper
from app.models import StationData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("digisnow-scraper")

shutdown_event = threading.Event()


def main():
    log.info("Starting DigiSnow Scraper")

    # 1. Load config
    config = Config()

    # 2. Initialize status mapper
    status_mapper = StatusMapper(config)

    # 3. Initialize HA publisher
    ha_publisher = HAPublisher(config, status_mapper)

    # 4. Callback: DigiSnow -> status mapper -> HA publisher
    def on_station_update(station_data: StationData):
        # Apply status mapping to all entities
        for sector in station_data.sectors.values():
            for lift in sector.lifts:
                lift.mapped_status = status_mapper.map_status(lift.opening_status)
            for slope in sector.slopes:
                slope.mapped_status = status_mapper.map_status(slope.opening_status)
        ha_publisher.publish_station_data(station_data)
        log.info(
            "Station %s updated: %d sectors",
            station_data.station_id,
            len(station_data.sectors),
        )

    # 5. Initialize credential fetcher (callback set after client creation)
    credential_fetcher = CredentialFetcher(config)

    # 6. Get MQTT credentials
    username, password = credential_fetcher.get_credentials()

    # 7. Initialize DigiSnow client
    digisnow_client = DigiSnowClient(
        username=username,
        password=password,
        on_station_update=on_station_update,
    )

    # Wire up credential refresh callback now that client exists
    credential_fetcher._on_updated = lambda u, p: digisnow_client.update_credentials(u, p)

    # 8. Start HA publisher
    ha_publisher.start()

    # 9. Start DigiSnow client with configured stations
    station_ids = [s["id"] for s in config.get_stations() if s.get("enabled", True)]
    if station_ids:
        digisnow_client.start(station_ids)
        log.info("Subscribed to stations: %s", ", ".join(station_ids))
    else:
        log.info("No stations configured yet. Add via web UI.")
        digisnow_client.start([])

    # 10. Start credential refresh timer
    credential_fetcher.start()

    # 11. Start Flask web server
    from app.web.app import create_app

    flask_app = create_app(config, digisnow_client, ha_publisher, credential_fetcher)

    # In HA add-on mode, skip auth for ingress requests (HA handles auth)
    if config.ha_addon:
        log.info("HA add-on mode: ingress auth handled by Supervisor")

    def run_web():
        from waitress import serve
        port = int(os.environ.get("INGRESS_PORT", 8099))
        log.info("Web UI starting on http://0.0.0.0:%d", port)
        serve(flask_app, host="0.0.0.0", port=port, _quiet=True)

    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()

    # 12. Handle shutdown signals
    def handle_signal(signum, frame):
        log.info("Shutdown signal received")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    log.info("DigiSnow Scraper is running")

    # Block until shutdown
    shutdown_event.wait()

    # Cleanup
    log.info("Shutting down...")
    credential_fetcher.stop()
    digisnow_client.stop()
    ha_publisher.stop()
    log.info("Shutdown complete")


if __name__ == "__main__":
    main()
