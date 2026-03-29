from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class LiftStatus:
    id: str
    name: str
    type: str  # TSD, TS, TC, TK, TR, etc.
    opening_status: str  # Raw DigiSnow status
    mapped_status: str = ""  # Mapped HA status
    last_update: str = ""
    season: str = ""
    comments: str = ""
    opening_hours: str = ""
    sector_name: str = ""


@dataclass
class SlopeStatus:
    id: str
    name: str
    difficulty: str  # green, blue, red, black, etc.
    opening_status: str
    mapped_status: str = ""
    last_update: str = ""
    sector_name: str = ""
    opening_hours: str = ""


@dataclass
class SectorData:
    name: str
    id: str
    lifts: list[LiftStatus] = field(default_factory=list)
    slopes: list[SlopeStatus] = field(default_factory=list)
    lifts_open: int = 0
    lifts_total: int = 0
    slopes_open: int = 0
    slopes_total: int = 0


@dataclass
class StationData:
    station_id: str
    sectors: dict[str, SectorData] = field(default_factory=dict)
    last_received: Optional[datetime] = None
    domain_status: str = "unknown"
