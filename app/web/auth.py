import functools
import logging

import bcrypt
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


def check_password(config, password: str) -> bool:
    stored_hash = config.get("web_auth", "password_hash", default="")
    if not stored_hash:
        # No password set yet - accept "admin" as default and hash it
        if password == "admin":
            set_password(config, "admin")
            return True
        return False
    try:
        return bcrypt.checkpw(password.encode(), stored_hash.encode())
    except Exception:
        # Fallback: plaintext comparison (for initial setup without bcrypt hash)
        return password == stored_hash


def set_password(config, password: str):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    config.set("web_auth", "password_hash", hashed)
    log.info("Password updated")
