import logging

from app.config import DEFAULT_STATUS_MAPPING

log = logging.getLogger(__name__)


class StatusMapper:
    def __init__(self, config):
        self._config = config

    @property
    def mapping(self) -> dict[str, str]:
        return self._config.get("status_mapping", default=DEFAULT_STATUS_MAPPING)

    def map_status(self, digisnow_status: str) -> str:
        mapped = self.mapping.get(digisnow_status, "unknown")
        return mapped

    def update_mapping(self, new_mapping: dict[str, str]):
        self._config.set("status_mapping", new_mapping)
        log.info("Status mapping updated")
