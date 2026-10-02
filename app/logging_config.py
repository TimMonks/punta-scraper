"""Root logging configuration (#10).

The Docker deployment ships stdout to Loki, so the default output is one JSON
object per line: ``{"ts", "level", "logger", "msg"}`` plus ``"exc"`` when an
exception is attached. ``LOG_FORMAT=text`` keeps the human-readable line; it is
also the default as a Home Assistant add-on, whose logs are read in the HA log
panel.
"""
import json
import logging
import os
from datetime import datetime, timezone

TEXT_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
TEXT_DATEFMT = "%Y-%m-%d %H:%M:%S"


class JsonFormatter(logging.Formatter):
    """Format each record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            entry["exc"] = record.exc_text
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def resolve_log_format(environ=None) -> str:
    """Return ``"json"`` or ``"text"`` from ``LOG_FORMAT`` and the run mode."""
    env = os.environ if environ is None else environ
    value = (env.get("LOG_FORMAT") or "").strip().lower()
    if value in ("json", "text"):
        return value
    if value:
        # Unknown value: fall back to the default and say so once configured.
        return "json"
    return "text" if env.get("SUPERVISOR_TOKEN") is not None else "json"


def configure_logging(level: int = logging.INFO, environ=None) -> str:
    """Configure the root logger; returns the format chosen."""
    env = os.environ if environ is None else environ
    fmt = resolve_log_format(env)
    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT, datefmt=TEXT_DATEFMT))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    raw = (env.get("LOG_FORMAT") or "").strip()
    if raw and raw.lower() not in ("json", "text"):
        logging.getLogger(__name__).error(
            "Unknown LOG_FORMAT %r; expected 'json' or 'text'. Using %s.", raw, fmt
        )
    return fmt
