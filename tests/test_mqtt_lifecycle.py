"""Connection generations own retries, clients and callbacks (#31).

Timers are manually fired, including after cancellation to model a callback
already dispatched. No test contacts a broker or sleeps for a retry delay.
"""
import logging
import socket
import threading
from types import SimpleNamespace

import pytest

from app.digisnow import client as digisnow
from app.homeassistant import publisher as homeassistant


class Config:
    def __init__(self, host="broker.invalid"):
        self.settings = {"host": host, "port": 1883}

    def get(self, *keys, default=None):
        if keys == ("ha_mqtt",):
            return self.settings
        return default

    def get_station(self, station_id):
        return None


@pytest.fixture
def network(monkeypatch):
    env = SimpleNamespace(clients=[], timers=[], outcomes=[], attempts=0)

    class Client:
        def __init__(self, **kwargs):
            self.running = False
            self.disconnected = False
            self.subscriptions = []
            self.credentials = None
            self.loop_starts = 0
            self.on_disconnect = None
            self.cleanup_hook = None
            env.clients.append(self)

        def username_pw_set(self, username, password):
            self.credentials = (username, password)

        def tls_set(self, **kwargs):
            pass

        def ws_set_options(self, **kwargs):
            pass

        def reconnect_delay_set(self, **kwargs):
            self.reconnect_settings = kwargs

        def connect(self, *args, **kwargs):
            env.attempts += 1
            outcome = env.outcomes.pop(0) if env.outcomes else None
            if isinstance(outcome, Exception):
                raise outcome
            if callable(outcome):
                outcome(self)

        def loop_start(self):
            self.loop_starts += 1
            self.running = True

        def loop_stop(self):
            if self.cleanup_hook:
                self.cleanup_hook()
            self.running = False

        def disconnect(self):
            self.disconnected = True
            if self.on_disconnect:
                self.on_disconnect(self, None, None, 0)

        def subscribe(self, topic, qos=0):
            self.subscriptions.append(topic)

        def unsubscribe(self, topic):
            self.subscriptions.remove(topic)

        def publish(self, *args, **kwargs):
            pass

    class Timer:
        def __init__(self, interval, function, args=None, kwargs=None):
            self.interval = interval
            self.function = function
            self.args = args or ()
            self.kwargs = kwargs or {}
            self.cancelled = False
            self.daemon = False
            env.timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

        def fire(self):
            # Cancellation cannot recall a callback already executing.
            self.function(*self.args, **self.kwargs)

    # These are the module aliases used by both implementations.
    monkeypatch.setattr(digisnow.mqtt, "Client", Client)
    monkeypatch.setattr(digisnow.threading, "Timer", Timer)
    return env


@pytest.fixture(params=["digisnow", "ha"])
def case(request, network):
    if request.param == "digisnow":
        target = digisnow.DigiSnowClient("synthetic-user", "synthetic-password")
        start = lambda: target.start(["station-a"])
    else:
        target = homeassistant.HAPublisher(Config(), None)
        start = target.start
    yield SimpleNamespace(target=target, start=start, network=network,
                          kind=request.param)
    target.stop()


def test_retry_cannot_reconnect_after_stop(case):
    env, target = case.network, case.target
    env.outcomes.append(ConnectionRefusedError("synthetic failure"))
    case.start()
    timer = env.timers[-1]
    target.stop()
    timer.fire()
    assert env.attempts == 1
    assert len(env.clients) == 1
    assert timer.cancelled
    assert not target.connected
    assert not any(client.running for client in env.clients)


def test_old_retry_cannot_replace_restarted_client(case):
    env, target = case.network, case.target
    env.outcomes.append(ConnectionRefusedError("synthetic failure"))
    case.start()
    timer = env.timers[-1]
    target.stop()
    case.start()
    current = target._client
    timer.fire()
    assert env.attempts == 2
    assert target._client is current
    assert sum(client.running for client in env.clients) == 1
    target.stop()
    assert not any(client.running for client in env.clients)


def test_stop_during_connect_prevents_loop_start(case, caplog):
    env, target = case.network, case.target
    env.outcomes.append(lambda client: target.stop())
    with caplog.at_level(logging.ERROR):
        case.start()
    assert env.clients[0].disconnected
    assert env.clients[0].loop_starts == 0
    assert target._client is None
    assert not env.timers
    assert not caplog.records


def test_restart_during_connect_keeps_new_client(case):
    env, target = case.network, case.target
    env.outcomes.append(lambda client: case.start())
    case.start()
    old, current = env.clients
    assert target._client is current
    assert old.disconnected and old.loop_starts == 0
    assert current.loop_starts == 1
    assert not env.timers


def test_stale_connect_failure_cannot_schedule_retry(case):
    env, target = case.network, case.target

    def restart_then_fail(client):
        case.start()
        raise ConnectionRefusedError("obsolete attempt")

    env.outcomes.append(restart_then_fail)
    case.start()
    assert target._client is env.clients[-1]
    assert env.clients[-1].running
    assert not env.timers


@pytest.mark.parametrize("restart", [False, True])
def test_other_thread_retires_blocking_connect(case, restart):
    entered, release, retired = (threading.Event() for _ in range(3))
    errors = []

    def blocked_connect(client):
        entered.set()
        if not release.wait(3):
            errors.append("connect was not released")

    def retire():
        try:
            case.target.stop()
            if restart:
                case.start()
        except Exception as error:
            errors.append(error)
        finally:
            retired.set()

    case.network.outcomes.append(blocked_connect)
    attempt = threading.Thread(target=case.start, daemon=True)
    attempt.start()
    assert entered.wait(1)
    stopper = threading.Thread(target=retire, daemon=True)
    stopper.start()
    try:
        assert retired.wait(1), "connect held the lifecycle lock"
    finally:
        release.set()
        attempt.join(2)
        stopper.join(2)
    assert not errors
    assert not attempt.is_alive() and not stopper.is_alive()
    old = case.network.clients[0]
    assert old.disconnected and old.loop_starts == 0
    if restart:
        current = case.network.clients[-1]
        assert case.target._client is current
        assert current.loop_starts == 1
    else:
        assert case.target._client is None
    case.target.stop()
    assert not any(client.running for client in case.network.clients)


def test_retired_callbacks_do_not_mutate_current_lifecycle(case, monkeypatch):
    target, env = case.target, case.network
    case.start()
    old = target._client
    target.stop()
    case.start()
    current = target._client
    republished = []
    if case.kind == "ha":
        target._station_cache["station-a"] = object()
        monkeypatch.setattr(target, "publish_station_data", republished.append)
    old.on_connect(old, None, None, 0)
    assert not target.connected
    assert not old.subscriptions
    assert not republished
    current.on_connect(current, None, None, 0)
    assert target.connected
    before = list(republished)
    old.on_disconnect(old, None, None, 7)
    old.on_connect(old, None, None, 7)
    assert target.connected
    assert republished == before
    assert env.attempts == 2


def test_retired_digisnow_message_is_ignored(network, monkeypatch):
    delivered = []
    parsed = object()
    monkeypatch.setattr(digisnow, "parse_assets", lambda *args: parsed)
    target = digisnow.DigiSnowClient("user", "password", delivered.append)
    target.start(["station-a"])
    old = target._client
    target.start(["station-a"])
    message = SimpleNamespace(topic="poulpe/DigiSnow/station-a/assets/all", payload=b"{}")
    old.on_message(old, None, message)
    assert delivered == []
    current = target._client
    current.on_message(current, None, message)
    assert delivered == [parsed]
    target.stop()


def test_current_retry_connects_and_is_consumed_once(case):
    env, target = case.network, case.target
    env.outcomes.append(ConnectionRefusedError("synthetic failure"))
    case.start()
    timer = env.timers[-1]
    assert timer.interval == 10
    assert timer.daemon
    timer.fire()
    current = target._client
    timer.fire()
    assert env.attempts == 2
    assert current.running
    current.on_connect(current, None, None, 0)
    assert target.connected
    assert current.reconnect_settings == {"min_delay": 10, "max_delay": 60}
    current.on_disconnect(current, None, None, 7)
    assert not target.connected


def test_station_callback_can_stop_without_holding_lifecycle_lock(network, monkeypatch):
    acquired = threading.Event()
    delivered = []
    monkeypatch.setattr(digisnow, "parse_assets", lambda *args: object())
    target = digisnow.DigiSnowClient("user", "password")

    def acquire_on_other_thread():
        with target._lock:
            acquired.set()

    def cleanup():
        thread = threading.Thread(target=acquire_on_other_thread, daemon=True)
        thread.start()
        try:
            assert acquired.wait(1), "user callback retained lifecycle lock"
        finally:
            thread.join(1)

    def update(data):
        target.stop()
        delivered.append(data)

    target._on_station_update = update
    target.start(["station-a"])
    current = target._client
    current.cleanup_hook = cleanup
    message = SimpleNamespace(topic="poulpe/DigiSnow/station-a/assets/all", payload=b"{}")
    current.on_message(current, None, message)
    assert acquired.is_set() and len(delivered) == 1
    assert target._client is None and not current.running


def test_retirement_during_message_parse_prevents_delivery(network, monkeypatch):
    delivered = []
    target = digisnow.DigiSnowClient("user", "password", delivered.append)

    def parse_then_stop(*args):
        target.stop()
        return object()

    monkeypatch.setattr(digisnow, "parse_assets", parse_then_stop)
    target.start(["station-a"])
    current = target._client
    message = SimpleNamespace(topic="poulpe/DigiSnow/station-a/assets/all", payload=b"{}")
    current.on_message(current, None, message)
    assert delivered == []


def test_cleanup_does_not_hold_lifecycle_lock(case):
    case.start()
    acquired = threading.Event()

    def acquire_on_other_thread():
        with case.target._lock:
            acquired.set()

    def cleanup():
        thread = threading.Thread(target=acquire_on_other_thread, daemon=True)
        thread.start()
        try:
            assert acquired.wait(1), "cleanup held the callback lock"
        finally:
            thread.join(1)

    case.target._client.cleanup_hook = cleanup
    case.target.stop()


def test_credentials_restart_pending_retry_and_preserve_stations(network):
    target = digisnow.DigiSnowClient("old-user", "old-password")
    network.outcomes.append(ConnectionRefusedError("synthetic failure"))
    target.start(["station-a"])
    timer = network.timers[-1]
    target.update_credentials("new-user", "new-password")
    current = target._client
    timer.fire()
    assert timer.cancelled
    assert network.attempts == 2
    assert current.credentials == ("new-user", "new-password")
    current.on_connect(current, None, None, 0)
    assert current.subscriptions == ["poulpe/DigiSnow/station-a/assets/all"]
    target.subscribe_station("station-b")
    target.unsubscribe_station("station-b")
    assert current.subscriptions == ["poulpe/DigiSnow/station-a/assets/all"]
    target.stop()
    target.update_credentials("stopped-user", "stopped-password")
    assert network.attempts == 2
    target.start(["station-a"])
    assert target._client.credentials == ("stopped-user", "stopped-password")
    target.stop()


def test_expected_digisnow_disconnect_logs_info(network, caplog):
    target = digisnow.DigiSnowClient("user", "password")
    target.start([])
    current = target._client
    with caplog.at_level(logging.INFO, logger=digisnow.__name__):
        current.on_disconnect(current, None, None, 0)
        target.stop()
    assert caplog.records
    assert all(record.levelno == logging.INFO for record in caplog.records)
    caplog.clear()
    target.start([])
    current = target._client
    with caplog.at_level(logging.WARNING, logger=digisnow.__name__):
        current.on_disconnect(current, None, None, 7)
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    target.stop()


def test_ha_retry_backoff_and_success_reset(network):
    target = homeassistant.HAPublisher(Config(), None)
    network.outcomes[:] = [ConnectionRefusedError("offline") for _ in range(7)]
    target.start()
    for _ in range(6):
        network.timers[-1].fire()
    assert [timer.interval for timer in network.timers] == [10, 20, 40, 80, 160, 300, 300]
    network.timers[-1].fire()
    current = target._client
    current.on_connect(current, None, None, 0)
    assert target._connect_retry_delay == 10
    assert target._dns_failures == 0
    assert target.config_error is None
    target.stop()


@pytest.mark.parametrize("host,has_error", [("", False), ("192.168.1.x", True)])
def test_ha_missing_or_placeholder_host_does_not_connect(network, host, has_error):
    target = homeassistant.HAPublisher(Config(host), None)
    target.start()
    assert network.attempts == 0
    assert not network.timers
    assert bool(target.config_error) == has_error
    target.stop()


def test_ha_permanent_dns_disables_and_restart_recovers(network):
    target = homeassistant.HAPublisher(Config(), None)
    network.outcomes[:] = [socket.gaierror(socket.EAI_NONAME, "missing") for _ in range(6)]
    target.start()
    for _ in range(5):
        network.timers[-1].fire()
    assert network.attempts == 6
    assert len(network.timers) == 5
    assert target.config_error
    old_timer = network.timers[-1]
    old_timer.fire()
    assert network.attempts == 6
    target.start()
    assert network.attempts == 7
    assert target.config_error is None
    assert target._dns_failures == 0
    target.stop()


def test_ha_transient_dns_resets_permanent_failure_count(network):
    target = homeassistant.HAPublisher(Config(), None)
    network.outcomes[:] = [socket.gaierror(socket.EAI_NONAME, "missing"),
                           socket.gaierror(socket.EAI_AGAIN, "temporary")]
    target.start()
    assert target._dns_failures == 1
    network.timers[-1].fire()
    assert target._dns_failures == 0
    assert target.config_error is None
    target.stop()
