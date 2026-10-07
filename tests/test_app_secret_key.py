"""create_app must refuse to run without a session key (Switchboard#89)."""
import pytest

from app.web.app import create_app


class _StubConfig:
    ha_addon = False

    def __init__(self, secret_key):
        self._secret_key = secret_key

    def get(self, *keys, default=None):
        if keys == ("secret_key",):
            return self._secret_key
        return default


def test_create_app_refuses_empty_key():
    with pytest.raises(RuntimeError):
        create_app(_StubConfig(""), None, None, None)


def test_create_app_uses_configured_key():
    app = create_app(_StubConfig("x" * 64), None, None, None)
    assert app.secret_key == "x" * 64
