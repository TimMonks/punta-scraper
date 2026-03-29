import logging
import os

from flask import Flask

log = logging.getLogger(__name__)


def create_app(config, digisnow_client, ha_publisher, credential_fetcher):
    # Use Flask's static handling at the app level, not blueprint level
    static_folder = os.path.join(os.path.dirname(__file__), "static")
    template_folder = os.path.join(os.path.dirname(__file__), "templates")

    app = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
        static_url_path="/static",
    )
    app.secret_key = config.get("secret_key", default="change-me")

    # Store references for routes
    app.config["APP_CONFIG"] = config
    app.config["DIGISNOW_CLIENT"] = digisnow_client
    app.config["HA_PUBLISHER"] = ha_publisher
    app.config["CREDENTIAL_FETCHER"] = credential_fetcher

    from app.web.routes import bp
    app.register_blueprint(bp)

    return app
