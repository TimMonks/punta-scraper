import logging

from flask import Flask

log = logging.getLogger(__name__)


def create_app(config, digisnow_client, ha_publisher, credential_fetcher):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
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
