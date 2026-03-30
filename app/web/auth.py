import functools
import logging

from flask import redirect, session, url_for

log = logging.getLogger(__name__)


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        # In HA add-on mode, Supervisor handles auth via ingress
        from flask import current_app
        config = current_app.config.get("APP_CONFIG")
        if config and config.ha_addon:
            return f(*args, **kwargs)
        if not session.get("authenticated"):
            return redirect(url_for("main.login"))
        return f(*args, **kwargs)
    return decorated
