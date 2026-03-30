"""
OIDC integration with Authentik for centralized authentication.
"""

import logging
import os
from urllib.parse import urlencode

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, redirect, session, url_for

log = logging.getLogger(__name__)

OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "")
OIDC_REDIRECT_URI = os.environ.get("OIDC_REDIRECT_URI", "")
OIDC_END_SESSION_URL = os.environ.get("OIDC_END_SESSION_URL", "")
OIDC_ADMIN_GROUP = os.environ.get("OIDC_ADMIN_GROUP", "authentik Admins")

oauth = OAuth()
bp = Blueprint("oidc", __name__, url_prefix="/auth")


def is_oidc_configured() -> bool:
    return bool(OIDC_CLIENT_ID and OIDC_CLIENT_SECRET and OIDC_ISSUER)


def init_oidc(app):
    """Register the Authentik OIDC provider. Call once at startup."""
    if not is_oidc_configured():
        return
    oauth.init_app(app)
    oauth.register(
        name="authentik",
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        server_metadata_url=f"{OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile groups"},
    )
    log.info("OIDC configured with issuer: %s", OIDC_ISSUER)


@bp.route("/login")
def oidc_login():
    if not is_oidc_configured():
        return redirect(url_for("main.login", error="OIDC not configured"))
    redirect_uri = OIDC_REDIRECT_URI or url_for("oidc.oidc_callback", _external=True)
    return oauth.authentik.authorize_redirect(redirect_uri)


@bp.route("/callback")
def oidc_callback():
    if not is_oidc_configured():
        return redirect(url_for("main.login", error="OIDC not configured"))

    try:
        token = oauth.authentik.authorize_access_token()
    except Exception:
        log.exception("OIDC token exchange failed")
        return redirect(url_for("main.login", error="Authentication failed"))

    userinfo = token.get("userinfo")
    if userinfo is None:
        return redirect(url_for("main.login", error="Authentication failed"))

    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        return redirect(url_for("main.login", error="No email in token"))

    # Check group membership
    groups = userinfo.get("groups", [])
    if OIDC_ADMIN_GROUP not in groups:
        return redirect(url_for("main.login", error="Access denied"))

    # Set session
    session["authenticated"] = True
    session["user_email"] = email
    session["oidc_id_token"] = token.get("id_token", "")

    log.info("OIDC login: %s", email)
    return redirect(url_for("main.dashboard"))


def build_logout_url() -> str | None:
    """Build the Authentik RP-Initiated Logout URL."""
    if not OIDC_END_SESSION_URL:
        return None
    params = {}
    id_token = session.get("oidc_id_token", "")
    if id_token:
        params["id_token_hint"] = id_token
    params["post_logout_redirect_uri"] = url_for("main.login", _external=True)
    return f"{OIDC_END_SESSION_URL}?{urlencode(params)}"
