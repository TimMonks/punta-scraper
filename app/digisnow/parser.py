import logging
from datetime import datetime, timezone

from app.models import LiftStatus, SectorData, SlopeStatus, StationData

log = logging.getLogger(__name__)

DIFFICULTY_MAP = {
    "V": "green",
    "B": "blue",
    "R": "red",
    "N": "black",
}


def _map_difficulty(raw_difficulty: str) -> str:
    """Map DigiSnow difficulty codes (V/B/R/N) to color names."""
    prefix = raw_difficulty.split("-")[0] if raw_difficulty else ""
    return DIFFICULTY_MAP.get(prefix, raw_difficulty)


def parse_assets(station_id: str, raw: dict | str) -> StationData:
    """Parse the assets/all MQTT payload into a StationData object."""
    if isinstance(raw, str):
        import json
        raw = json.loads(raw)

    station = StationData(
        station_id=station_id,
        last_received=datetime.now(timezone.utc),
    )

    for key, sector_data in raw.items():
        if not key.startswith("sector_"):
            continue

        sector_id = key[len("sector_"):]
        sector_name = sector_data.get("name", sector_id)

        sector = SectorData(
            name=sector_name,
            id=sector_id,
        )

        # Parse lifts
        for lift_raw in sector_data.get("lifts", []):
            lift = LiftStatus(
                id=lift_raw.get("id", ""),
                name=lift_raw.get("name", ""),
                type=lift_raw.get("type", ""),
                opening_status=lift_raw.get("openingStatus", "unknown"),
                last_update=lift_raw.get("openingStatusLastUpdate", ""),
                season=lift_raw.get("season", ""),
                comments=(lift_raw.get("publicComments") or "").strip(),
                opening_hours=lift_raw.get("openingHours", ""),
                sector_name=sector_name,
            )
            sector.lifts.append(lift)

        # Parse slopes
        for slope_raw in sector_data.get("slopes", []):
            slope = SlopeStatus(
                id=slope_raw.get("id", ""),
                name=slope_raw.get("name", ""),
                difficulty=_map_difficulty(slope_raw.get("difficulty", "")),
                opening_status=slope_raw.get("openingStatus", "unknown"),
                last_update=slope_raw.get("openingStatusLastUpdate", ""),
                sector_name=sector_name,
                opening_hours=slope_raw.get("openingHours", ""),
            )
            sector.slopes.append(slope)

        # Parse statistics
        lift_stats = sector_data.get("liftsStatistics", {})
        sector.lifts_open = lift_stats.get("nbOpen", 0)
        sector.lifts_total = lift_stats.get("nbTotal", 0)

        slope_stats = sector_data.get("slopesStatistics", {})
        sector.slopes_open = slope_stats.get("nbOpen", 0)
        sector.slopes_total = slope_stats.get("nbTotal", 0)

        station.sectors[sector_id] = sector

    log.debug(
        "Parsed station %s: %d sectors, %d lifts, %d slopes",
        station_id,
        len(station.sectors),
        sum(len(s.lifts) for s in station.sectors.values()),
        sum(len(s.slopes) for s in station.sectors.values()),
    )

    return station
