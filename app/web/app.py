import logging
import os

from flask import Flask

log = logging.getLogger(__name__)


class IngressMiddleware:
    """Middleware that strips the ingress prefix from PATH_INFO and sets SCRIPT_NAME."""
    def __init__(self, app, prefix):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path.startswith(self.prefix):
            environ["PATH_INFO"] = path[len(self.prefix):] or "/"
            environ["SCRIPT_NAME"] = self.prefix
        return self.app(environ, start_response)


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

    # HA ingress: INGRESS_ENTRY contains the base path e.g. /api/hassio_ingress/<token>
    ingress_entry = os.environ.get("INGRESS_ENTRY", "")
    if ingress_entry:
        app.wsgi_app = IngressMiddleware(app.wsgi_app, ingress_entry)
        log.info("HA ingress base path: %s", ingress_entry)

    # Store references for routes
    app.config["APP_CONFIG"] = config
    app.config["DIGISNOW_CLIENT"] = digisnow_client
    app.config["HA_PUBLISHER"] = ha_publisher
    app.config["CREDENTIAL_FETCHER"] = credential_fetcher

    from app.web.routes import bp
    app.register_blueprint(bp)

    from app.web.oidc import bp as oidc_bp, init_oidc
    init_oidc(app)
    app.register_blueprint(oidc_bp)

    return app
