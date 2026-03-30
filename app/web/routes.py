import json
import logging
import threading
import time

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.digisnow.client import DigiSnowClient
from app.web.auth import login_required

log = logging.getLogger(__name__)
bp = Blueprint("main", __name__)


def _get_config():
    return current_app.config["APP_CONFIG"]


def _get_digisnow() -> DigiSnowClient:
    return current_app.config["DIGISNOW_CLIENT"]


def _get_publisher():
    return current_app.config["HA_PUBLISHER"]


def _get_fetcher():
    return current_app.config["CREDENTIAL_FETCHER"]


# --- Auth ---

@bp.route("/login")
def login():
    error = request.args.get("error")
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    from app.web.oidc import build_logout_url
    logout_url = build_logout_url()
    session.clear()
    if logout_url:
        return redirect(logout_url)
    return redirect(url_for("main.login"))


# --- Dashboard ---

@bp.route("/")
def dashboard():
    config = _get_config()
    digisnow = _get_digisnow()
    publisher = _get_publisher()
    stations = config.get_stations()

    # Get cached station data from publisher
    station_data = {}
    for s in stations:
        cached = publisher._station_cache.get(s["id"])
        if cached:
            station_data[s["id"]] = cached

    is_authenticated = bool(
        session.get("authenticated") or (config and config.ha_addon)
    )

    return render_template(
        "dashboard.html",
        stations=stations,
        station_data=station_data,
        digisnow_connected=digisnow.connected,
        ha_connected=publisher.connected,
        authenticated=is_authenticated,
    )


# --- Station API ---

@bp.route("/api/stations", methods=["GET"])
def list_stations():
    config = _get_config()
    publisher = _get_publisher()
    stations = config.get_stations()
    result = []
    for s in stations:
        cached = publisher._station_cache.get(s["id"])
        info = {**s}
        if cached:
            info["lifts_open"] = sum(
                sec.lifts_open for sec in cached.sectors.values()
            )
            info["lifts_total"] = sum(
                sec.lifts_total for sec in cached.sectors.values()
            )
            info["slopes_open"] = sum(
                sec.slopes_open for sec in cached.sectors.values()
            )
            info["slopes_total"] = sum(
                sec.slopes_total for sec in cached.sectors.values()
            )
            info["last_received"] = (
                cached.last_received.isoformat() if cached.last_received else None
            )
        result.append(info)
    return jsonify(result)


@bp.route("/api/stations", methods=["POST"])
@login_required
def add_station():
    data = request.get_json()
    station_id = data.get("id", "").strip().lower()
    display_name = data.get("display_name", "").strip()
    if not station_id:
        return jsonify({"error": "Station ID required"}), 400

    config = _get_config()
    station = config.add_station(station_id, display_name)
    _get_digisnow().subscribe_station(station_id)
    return jsonify(station), 201


@bp.route("/api/stations/<station_id>", methods=["DELETE"])
@login_required
def remove_station(station_id):
    config = _get_config()
    publisher = _get_publisher()

    # Remove HA entities
    cached = publisher._station_cache.get(station_id)
    if cached:
        publisher.remove_station_entities(station_id, cached)

    _get_digisnow().unsubscribe_station(station_id)
    config.remove_station(station_id)
    return jsonify({"ok": True})


@bp.route("/api/stations/search", methods=["GET"])
@login_required
def search_station():
    """Check if a station ID exists on DigiSnow by probing its widget endpoint."""
    import requests

    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify({"error": "Search query required"}), 400

    try:
        url = f"https://{query}.digisnow.app/v1/widget/widgetversion"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return jsonify({"id": query, "exists": True})
        else:
            return jsonify({"id": query, "exists": False})
    except requests.RequestException:
        return jsonify({"id": query, "exists": False})


@bp.route("/api/stations/<station_id>/track", methods=["PUT"])
@login_required
def update_tracking(station_id):
    data = request.get_json()
    config = _get_config()
    config.update_station(station_id, {
        "tracked_lifts": data.get("tracked_lifts", []),
        "tracked_slopes": data.get("tracked_slopes", []),
        "track_all": data.get("track_all", False),
    })
    return jsonify({"ok": True})


@bp.route("/api/stations/<station_id>/status", methods=["GET"])
def station_status(station_id):
    publisher = _get_publisher()
    cached = publisher._station_cache.get(station_id)
    if not cached:
        return jsonify({"error": "No data"}), 404

    config = _get_config()
    station_config = config.get_station(station_id)
    track_all = station_config.get("track_all", True) if station_config else True
    tracked_lifts = set(station_config.get("tracked_lifts", [])) if station_config else set()
    tracked_slopes = set(station_config.get("tracked_slopes", [])) if station_config else set()

    sectors = []
    for sector in cached.sectors.values():
        lifts = []
        for l in sector.lifts:
            if track_all or l.id in tracked_lifts:
                lifts.append({
                    "id": l.id,
                    "name": l.name,
                    "type": l.type,
                    "status": l.mapped_status or l.opening_status,
                    "raw_status": l.opening_status,
                    "comments": l.comments,
                    "hours": l.opening_hours,
                })
        slopes = []
        for s in sector.slopes:
            if track_all or s.id in tracked_slopes:
                slopes.append({
                    "id": s.id,
                    "name": s.name,
                    "difficulty": s.difficulty,
                    "status": s.mapped_status or s.opening_status,
                    "raw_status": s.opening_status,
                    "hours": s.opening_hours,
                })
        sectors.append({
            "name": sector.name,
            "lifts": lifts,
            "slopes": slopes,
            "lifts_open": sector.lifts_open,
            "lifts_total": sector.lifts_total,
            "slopes_open": sector.slopes_open,
            "slopes_total": sector.slopes_total,
        })

    return jsonify({
        "station_id": station_id,
        "last_received": cached.last_received.isoformat() if cached.last_received else None,
        "sectors": sectors,
    })


# --- Settings ---

@bp.route("/api/settings/ha-mqtt", methods=["GET"])
@login_required
def get_ha_mqtt():
    config = _get_config()
    ha = config.get("ha_mqtt", default={})
    # Don't expose password
    return jsonify({
        "host": ha.get("host", ""),
        "port": ha.get("port", 1883),
        "username": ha.get("username", ""),
        "has_password": bool(ha.get("password", "")),
        "discovery_prefix": ha.get("discovery_prefix", "homeassistant"),
        "state_topic_prefix": ha.get("state_topic_prefix", "digisnow"),
    })


@bp.route("/api/settings/ha-mqtt", methods=["PUT"])
@login_required
def update_ha_mqtt():
    data = request.get_json()
    config = _get_config()
    publisher = _get_publisher()

    for key in ["host", "port", "username", "discovery_prefix", "state_topic_prefix"]:
        if key in data:
            val = int(data[key]) if key == "port" else data[key]
            config.set("ha_mqtt", key, val)
    if "password" in data and data["password"]:
        config.set("ha_mqtt", "password", data["password"])

    # Reconnect publisher with new settings
    publisher.stop()
    publisher.start()

    return jsonify({"ok": True})


@bp.route("/api/settings/mapping", methods=["GET"])
@login_required
def get_mapping():
    config = _get_config()
    return jsonify(config.get("status_mapping", default={}))


@bp.route("/api/settings/mapping", methods=["PUT"])
@login_required
def update_mapping():
    data = request.get_json()
    config = _get_config()
    config.set("status_mapping", data)
    return jsonify({"ok": True})


# --- Health (no auth) ---

@bp.route("/api/health")
def health():
    digisnow = _get_digisnow()
    publisher = _get_publisher()
    return jsonify({
        "digisnow_connected": digisnow.connected,
        "ha_mqtt_connected": publisher.connected,
    })
