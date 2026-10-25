from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
import importlib.util
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from urllib.parse import urljoin, urlparse

import pytest


def _login(client, username: str, password: str) -> None:
    response = client.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    assert response.status_code == 303


def test_readonly_cannot_unlock_or_read_audit(anon_client):
    from app.users import USERS_PATH, add_user, load_users

    if "reader" not in load_users(USERS_PATH)["users"]:
        add_user("reader", "readerpass123", "readonly", path=USERS_PATH)
    _login(anon_client, "reader", "readerpass123")
    assert anon_client.post("/api/auth/unlock", json={"pin": "1234"}).status_code == 403
    assert anon_client.get("/api/audit").status_code == 403


def test_user_can_write_safe_but_cannot_power_off(anon_client):
    from app.users import USERS_PATH, add_user, load_users

    if "operator" not in load_users(USERS_PATH)["users"]:
        add_user("operator", "operatorpass123", "user", path=USERS_PATH)
    _login(anon_client, "operator", "operatorpass123")
    unlocked = anon_client.post("/api/auth/unlock", json={"pin": "1234"})
    token = unlocked.json()["token"]
    headers = {"X-Plumbox-Token": token}
    assert anon_client.post("/api/set", json={"name": "heating_target_temp", "value": 68}, headers=headers).status_code == 200
    assert anon_client.post("/api/controller/power", json={"enabled": False, "confirmed": True}, headers=headers).status_code == 403


def test_control_token_is_bound_to_login_identity(anon_client):
    from app.users import USERS_PATH, add_user, load_users

    if "operator2" not in load_users(USERS_PATH)["users"]:
        add_user("operator2", "operatorpass456", "user", path=USERS_PATH)
    _login(anon_client, "operator2", "operatorpass456")
    token = anon_client.post("/api/auth/unlock", json={"pin": "1234"}).json()["token"]
    _login(anon_client, "admin", "testpass123")
    response = anon_client.post(
        "/api/set",
        json={"name": "heating_target_temp", "value": 67},
        headers={"X-Plumbox-Token": token},
    )
    assert response.status_code == 403


def test_audit_failure_does_not_hide_successful_device_write():
    from app.config import AppConfig
    from app.plum_service import PlumService

    class BrokenAudit:
        async def add_audit(self, *_args, **_kwargs):
            raise OSError("disk full")

    service = PlumService(AppConfig(), BrokenAudit())
    result = asyncio.run(service.set_parameter("ecomax", 0, "heating_target_temp", 66))
    assert result["success"] is True
    assert result["audit_saved"] is False


def test_late_readback_confirms_write_even_when_transport_returns_false():
    """Brak natychmiastowego ACK nie jest błędem, jeśli odczyt wraca z żądaną wartością."""
    from types import SimpleNamespace

    from app.config import AppConfig
    from app.plum_service import PlumService

    class Database:
        async def add_audit(self, *_args, **_kwargs):
            return None

    class Device:
        def __init__(self, statistics):
            self.data = {"max_fuel_flow": SimpleNamespace(value=6.8)}
            self.statistics = statistics

        async def set(self, _name, value):
            async def delayed_update():
                await asyncio.sleep(0.02)
                self.data["max_fuel_flow"].value = value
                self.statistics.received_frames += 1

            asyncio.create_task(delayed_update())
            return False

    config = AppConfig()
    config.connection.type = "tcp"
    config.security.safe_writes_only = False
    service = PlumService(config, Database())
    service.WRITE_READBACK_TIMEOUT_SECONDS = 0.2
    service.WRITE_READBACK_INTERVAL_SECONDS = 0.01
    statistics = SimpleNamespace(received_frames=10)
    service._device = Device(statistics)
    service._connection = SimpleNamespace(connected=True, statistics=statistics)
    service.snapshot["parameters"] = {"max_fuel_flow": {"value": 6.8}}

    result = asyncio.run(service.set_parameter("ecomax", 0, "max_fuel_flow", 6.6))

    assert result["success"] is True
    assert result["status"] == "confirmed"
    assert "nowej ramki" in result["message"]


def test_missing_readback_is_unconfirmed_not_reported_as_rejection():
    from types import SimpleNamespace

    from app.config import AppConfig
    from app.plum_service import PlumService

    class Database:
        async def add_audit(self, *_args, **_kwargs):
            return None

    class Device:
        data = {"max_fuel_flow": SimpleNamespace(value=6.8)}

        async def set(self, _name, _value):
            # Dokładnie przypadek sprzętowy: biblioteka zwraca ACK/True,
            # ale regulator nadal raportuje starą wartość.
            return True

    config = AppConfig()
    config.connection.type = "tcp"
    config.security.safe_writes_only = False
    service = PlumService(config, Database())
    service.WRITE_READBACK_TIMEOUT_SECONDS = 0.02
    service.WRITE_READBACK_INTERVAL_SECONDS = 0.005
    service._device = Device()
    service._connection = SimpleNamespace(
        connected=True,
        statistics=SimpleNamespace(received_frames=10),
    )
    service.snapshot["parameters"] = {"max_fuel_flow": {"value": 6.8}}

    result = asyncio.run(service.set_parameter("ecomax", 0, "max_fuel_flow", 6.6))

    assert result["success"] is False
    assert result["status"] == "unconfirmed"
    assert result["transport_accepted"] is True
    assert result["readback_confirmed"] is False
    assert "nie otrzymano świeżego potwierdzenia" in result["message"]


def test_cached_parameter_value_is_not_mistaken_for_fresh_confirmation():
    from types import SimpleNamespace

    from app.config import AppConfig
    from app.plum_service import PlumService

    class Database:
        async def add_audit(self, *_args, **_kwargs):
            return None

    class Device:
        data = {"max_fuel_flow": SimpleNamespace(value=6.8)}

        async def set(self, _name, value):
            # Symuluje bibliotekę, która lokalnie podmieniła cache, ale nie
            # odebrano po zapisie żadnej nowej ramki z transportu.
            self.data["max_fuel_flow"].value = value
            return True

    config = AppConfig()
    config.connection.type = "tcp"
    config.security.safe_writes_only = False
    service = PlumService(config, Database())
    service.WRITE_READBACK_TIMEOUT_SECONDS = 0.02
    service.WRITE_READBACK_INTERVAL_SECONDS = 0.005
    service._device = Device()
    service._connection = SimpleNamespace(
        connected=True,
        statistics=SimpleNamespace(received_frames=10),
    )
    service.snapshot["parameters"] = {"max_fuel_flow": {"value": 6.8}}

    result = asyncio.run(service.set_parameter("ecomax", 0, "max_fuel_flow", 6.6))

    assert result["success"] is False
    assert result["readback_confirmed"] is False


def test_unverified_controller_keeps_airflow_correction_in_native_scale():
    from app.mappings import display_value, native_value

    assert display_value("airflow_correction_100", 101) == 101
    assert native_value("airflow_correction_100", 1) == 1
    assert display_value(
        "airflow_correction_100",
        101,
        airflow_correction_enabled=True,
    ) == 1


def test_live_refresh_preserves_unsaved_parameter_draft():
    root = Path(__file__).resolve().parents[1]
    js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "parameterDrafts: new Map()" in js
    assert "const editorValue = draft !== undefined ? draft : parameter.value" in js
    assert "state.parameterDrafts.set(stepButton.dataset.stepParameter, input.value)" in js
    assert 'state.parameterDrafts.set(input.id.replace(/^input-/, ""), input.value)' in js
    assert "state.parameterDrafts.delete(id)" in js


def test_failed_connection_clears_stale_device(monkeypatch):
    from app.config import AppConfig
    from app.plum_service import PlumService

    class Connection:
        connected = True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            raise TimeoutError("no controller")

    fake = SimpleNamespace(open_tcp_connection=lambda *_args, **_kwargs: Connection())
    monkeypatch.setitem(sys.modules, "pyplumio", fake)
    config = AppConfig()
    config.connection.type = "tcp"
    service = PlumService(config, SimpleNamespace())
    service._device = object()
    try:
        asyncio.run(service._connection_session())
    except TimeoutError:
        pass
    assert service._device is None
    assert service._connection is None


def test_clean_disconnect_is_reported_and_clears_device(monkeypatch):
    from app.config import AppConfig
    from app.plum_service import PlumService

    class Connection:
        connected = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            return SimpleNamespace(data={})

    monkeypatch.setitem(sys.modules, "pyplumio", SimpleNamespace(open_tcp_connection=lambda *_args, **_kwargs: Connection()))
    config = AppConfig()
    config.connection.type = "tcp"
    service = PlumService(config, SimpleNamespace())
    try:
        asyncio.run(service._connection_session())
    except ConnectionError as exc:
        assert "przerwane" in str(exc)
    else:
        raise AssertionError("Rozłączenie nie zostało zgłoszone")
    assert service._device is None
    assert service._connection is None


def test_stalled_tcp_frames_force_reconnect_after_router_restart():
    """Event TCP może zostać ustawiony po zaniku routera; postęp ramek jest źródłem prawdy."""
    from app.config import AppConfig
    from app.plum_service import PlumService

    config = AppConfig()
    config.connection.type = "tcp"
    config.connection.stale_frame_timeout_seconds = 45
    service = PlumService(config, SimpleNamespace())
    connection = SimpleNamespace(statistics=SimpleNamespace(received_frames=100))
    service._last_received_frames = 100
    service._last_frame_progress_at = 10.0

    assert service._connection_frames_stalled(connection, now=54.9) is False
    assert service._connection_frames_stalled(connection, now=55.0) is True

    # Każda nowa poprawna ramka zeruje licznik czasu martwego połączenia.
    connection.statistics.received_frames = 101
    assert service._connection_frames_stalled(connection, now=60.0) is False
    assert service._last_frame_progress_at == 60.0


def test_tcp_keepalive_is_enabled_before_waiting_for_first_ecomax_frame(monkeypatch):
    from app.config import AppConfig
    from app.plum_service import PlumService

    class Socket:
        def __init__(self):
            self.calls = []

        def setsockopt(self, level, option, value):
            self.calls.append((level, option, value))

    class Transport:
        def __init__(self, sock):
            self.sock = sock
            self.aborted = False

        def get_extra_info(self, name):
            assert name == "socket"
            return self.sock

        def abort(self):
            self.aborted = True

    sock = Socket()
    transport = Transport(sock)

    class Connection:
        connected = False

        def __init__(self):
            self.protocol = SimpleNamespace(
                writer=SimpleNamespace(
                    _writer=SimpleNamespace(transport=transport),
                )
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            self.protocol.writer = None
            return False

        async def get(self, *_args, **_kwargs):
            # Najważniejsza regresja: keepalive musi być aktywny przed get(),
            # bo właśnie get() czeka 60 s na pierwszą ramkę.
            assert sock.calls
            return SimpleNamespace(data={})

    monkeypatch.setitem(
        sys.modules,
        "pyplumio",
        SimpleNamespace(open_tcp_connection=lambda *_args, **_kwargs: Connection()),
    )
    config = AppConfig()
    config.connection.type = "tcp"
    service = PlumService(config, SimpleNamespace())

    with pytest.raises(ConnectionError):
        asyncio.run(service._connection_session())

    import socket

    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in sock.calls


def test_keepalive_private_api_failure_does_not_break_connection(monkeypatch):
    from app.config import AppConfig
    from app.plum_service import PlumService

    class BrokenTransport:
        def get_extra_info(self, _name):
            raise RuntimeError("PyPlumIO internals changed")

        def abort(self):
            return None

    class Connection:
        connected = False
        protocol = SimpleNamespace(
            writer=SimpleNamespace(
                _writer=SimpleNamespace(transport=BrokenTransport()),
            )
        )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            return SimpleNamespace(data={})

    monkeypatch.setitem(
        sys.modules,
        "pyplumio",
        SimpleNamespace(open_tcp_connection=lambda *_args, **_kwargs: Connection()),
    )
    config = AppConfig()
    config.connection.type = "tcp"
    service = PlumService(config, SimpleNamespace())

    # Błąd prywatnego hooka nie może zastąpić właściwego wyniku sesji.
    with pytest.raises(ConnectionError, match="przerwane"):
        asyncio.run(service._connection_session())


def test_failed_session_aborts_transport_captured_before_pyplumio_cleanup(monkeypatch):
    from app.config import AppConfig
    from app.plum_service import PlumService

    class Transport:
        aborted = False

        def get_extra_info(self, _name):
            return None

        def abort(self):
            self.aborted = True

    transport = Transport()

    class Connection:
        connected = True

        def __init__(self):
            self.protocol = SimpleNamespace(
                writer=SimpleNamespace(
                    _writer=SimpleNamespace(transport=transport),
                )
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            # Tak zachowuje się shutdown PyPlumIO: writer znika przed finally
            # PlumBoxa. Test dowodzi, że używamy zachowanej referencji transportu.
            self.protocol.writer = None
            return False

        async def get(self, *_args, **_kwargs):
            raise TimeoutError

    monkeypatch.setitem(
        sys.modules,
        "pyplumio",
        SimpleNamespace(open_tcp_connection=lambda *_args, **_kwargs: Connection()),
    )
    config = AppConfig()
    config.connection.type = "tcp"
    service = PlumService(config, SimpleNamespace())

    with pytest.raises(TimeoutError):
        asyncio.run(service._connection_session())

    assert transport.aborted is True
    assert service._device is None
    assert service._connection is None


def test_failed_negotiations_rebuild_and_quiesce_each_pyplumio_session(monkeypatch):
    from app.config import AppConfig
    from app.plum_service import PlumService

    events = []
    connections = []

    class Transport:
        def __init__(self, session):
            self.session = session
            self.aborted = False

        def get_extra_info(self, _name):
            return None

        def abort(self):
            self.aborted = True
            events.append((self.session, "abort"))

    class Owner:
        def __init__(self, session):
            self.session = session
            self.tasks = set()

        def cancel_tasks(self):
            events.append((self.session, "cancel"))
            return True

        async def wait_until_done(self):
            events.append((self.session, "wait"))

    class Connection(Owner):
        connected = True

        def __init__(self, session):
            super().__init__(session)
            self.transport = Transport(session)
            self.protocol = Owner(session)
            self.protocol.writer = SimpleNamespace(
                _writer=SimpleNamespace(transport=self.transport),
            )
            self.protocol.statistics = SimpleNamespace(
                received_frames=0,
                failed_frames=0,
                sent_frames=1,
            )
            self.protocol.reader = None

        async def __aenter__(self):
            events.append((self.session, "enter"))
            return self

        async def __aexit__(self, *_args):
            # Najważniejsza gwarancja: transport i zadania są domknięte jeszcze
            # przed wejściem do PyPlumIO __aexit__.
            assert self.transport.aborted is True
            assert (self.session, "wait") in events
            events.append((self.session, "exit"))
            return False

        async def get(self, *_args, **_kwargs):
            raise TimeoutError("no ecomax")

    def open_connection(*_args, **_kwargs):
        connection = Connection(len(connections) + 1)
        connections.append(connection)
        return connection

    monkeypatch.setitem(
        sys.modules,
        "pyplumio",
        SimpleNamespace(open_tcp_connection=open_connection),
    )
    config = AppConfig()
    config.connection.type = "tcp"
    service = PlumService(config, SimpleNamespace())

    for _ in range(2):
        with pytest.raises(TimeoutError, match="no ecomax"):
            asyncio.run(service._connection_session())

    assert len(connections) == 2
    assert connections[0] is not connections[1]
    assert service._session_sequence == 2
    assert service._active_session_id is None
    for session in (1, 2):
        assert events.index((session, "abort")) < events.index((session, "exit"))
        assert events.index((session, "wait")) < events.index((session, "exit"))


def test_session_diagnostics_separate_valid_failed_and_buffered_data():
    from app.config import AppConfig
    from app.plum_service import PlumService

    service = PlumService(AppConfig(), SimpleNamespace())
    connection = SimpleNamespace(
        protocol=SimpleNamespace(
            statistics=SimpleNamespace(
                received_frames=12,
                failed_frames=3,
                sent_frames=7,
            ),
            reader=SimpleNamespace(
                _reader=SimpleNamespace(buffer=bytearray(b"raw")),
            ),
        ),
    )

    assert service._session_diagnostics(connection) == {
        "received_frames": 12,
        "failed_frames": 3,
        "sent_frames": 7,
        "buffered_bytes": 3,
    }


def test_real_pyplumio_has_no_frame_handler_left_after_repeated_timeouts():
    """Trzy nieudane negocjacje nie mogą zostawić czytników starej sesji."""
    from app.config import AppConfig
    from app.plum_service import PlumService

    async def scenario():
        peer_tasks = set()

        async def hold_peer(reader, writer):
            try:
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()

        def accepted(reader, writer):
            task = asyncio.create_task(hold_peer(reader, writer))
            peer_tasks.add(task)
            task.add_done_callback(peer_tasks.discard)

        server = await asyncio.start_server(accepted, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        config = AppConfig()
        config.connection.type = "tcp"
        config.connection.host = "127.0.0.1"
        config.connection.port = port
        config.connection.device_timeout_seconds = 0.05
        service = PlumService(config, SimpleNamespace())

        try:
            for _ in range(3):
                with pytest.raises(asyncio.TimeoutError):
                    await service._connection_session()
                await asyncio.sleep(0)
                leaked = [
                    task
                    for task in asyncio.all_tasks()
                    if task is not asyncio.current_task()
                    and not task.done()
                    and task.get_name() in {"frame_handler_task", "reconnect_task"}
                ]
                assert leaked == []
            assert service._session_sequence == 3
        finally:
            server.close()
            await server.wait_closed()
            if peer_tasks:
                await asyncio.gather(*tuple(peer_tasks), return_exceptions=True)

    asyncio.run(scenario())


def test_timeout_produces_readable_connection_error_and_bridge_hint():
    from app.config import AppConfig
    from app.plum_service import PlumService

    config = AppConfig()
    config.connection.type = "tcp"
    config.connection.device_timeout_seconds = 60
    service = PlumService(config, SimpleNamespace())

    first = service._connection_error_message(TimeoutError(), 1)
    third = service._connection_error_message(TimeoutError(), 3)

    assert first
    assert "60 s" in first
    assert "żadnej ramki" in first
    assert "Nieudane próby" not in first
    assert "Nieudane próby: 3" in third
    assert "PlumBridge" in third


def test_successful_handshake_resets_consecutive_failure_counter(monkeypatch):
    from app.config import AppConfig
    from app.plum_service import PlumService

    class Connection:
        connected = False
        protocol = SimpleNamespace(writer=None)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            return SimpleNamespace(data={})

    monkeypatch.setitem(
        sys.modules,
        "pyplumio",
        SimpleNamespace(open_tcp_connection=lambda *_args, **_kwargs: Connection()),
    )
    config = AppConfig()
    config.connection.type = "tcp"
    service = PlumService(config, SimpleNamespace())
    service._consecutive_connection_failures = 2

    with pytest.raises(ConnectionError):
        asyncio.run(service._connection_session())

    assert service._consecutive_connection_failures == 0


def test_mqtt_clears_stale_retained_topics():
    from app.config import MqttConfig
    from app.mqtt import MqttPublisher

    class Info:
        rc = 0

    class Client:
        def __init__(self):
            self.calls = []

        def publish(self, topic, payload, **kwargs):
            self.calls.append((topic, payload, kwargs))
            return Info()

    publisher = MqttPublisher(MqttConfig(enabled=True, home_assistant_discovery=False))
    publisher._client = Client()
    publisher._mqtt = SimpleNamespace(MQTT_ERR_SUCCESS=0)
    publisher._connected = True
    asyncio.run(publisher.publish({"connected": True, "values": {"old": 1}, "profile": {}}))
    asyncio.run(publisher.publish({"connected": True, "values": {"new": 2}, "profile": {}}))
    assert ("plumbox/value/old", "", {"qos": 0, "retain": True}) in publisher._client.calls


def test_frontend_has_no_root_bound_runtime_urls(client):
    import re

    app_js = client.get("/assets/app.js").text
    index = client.get("/").text
    login = client.get("/login").text
    assert '`${protocol}://${location.host}/ws`' not in app_js
    assert 'register("/assets/' not in app_js
    # Każdy href/src zaczynający się od "/" gubi prefiks HA Ingress. Wzorzec
    # łapie całą klasę (w tym /manifest.webmanifest), nie tylko /assets/.
    root_bound = re.findall(r'(?:href|src)="/[^/"][^"]*"', index + login)
    assert not root_bound, f"Root-bound URL w HTML: {root_bound}"


def test_frontend_does_not_generate_measurements(client):
    app_js = client.get("/assets/app.js").text
    assert "Math.sin(" not in app_js
    assert "state.overviewHistory.length > 2 ?" not in app_js
    assert 'val("fuel_burned", val("fuel_consumption"' not in app_js
    assert "Brak historii" in app_js


def test_service_worker_refreshes_static_assets(client):
    worker = client.get("/service-worker.js").text
    assert "fetch(event.request)" in worker
    # Wersjonowane adresy zasobów: bez nich przeglądarka może podawać stary
    # styles.css/app.js z cache HTTP po aktualizacji wydania.
    index = client.get("/").text
    cache_version = re.search(r'plumbox-gptsol-static-v(\d+)', worker)
    asset_version = re.search(r'ASSET_VERSION = "gptsol-(\d+)"', worker)
    assert cache_version and asset_version
    assert cache_version.group(1) == asset_version.group(1)
    version = f"gptsol-{asset_version.group(1)}"
    assert f"assets/styles.css?v={version}" in index
    assert f"assets/app.js?v={version}" in index


def test_v3n9_select_cards_and_approved_typography(client):
    app_js = client.get("/assets/app.js").text
    styles = client.get("/assets/styles.css").text

    # Select i przycisk są dwoma pionowymi wierszami, ale zachowują dotychczasowe
    # data-save-parameter, więc ścieżka zapisu i delegacja zdarzeń nie zmieniają się.
    assert (
        "</select></div><div class=\"parameter-actions\"><button "
        "class=\"save-button\" ${disabled} data-save-parameter="
    ) in app_js
    assert ">Zapisz do sterownika</button></div>`;" in app_js
    assert ".select-editor { display: grid; grid-template-columns: 1fr; gap: 8px; }" in styles
    assert ".select-editor .save-button" not in styles

    # Umiarkowane wartości zaakceptowane w podglądzie V3N9.
    assert "font-weight: 600; font-size: 14px; text-align: left;" in styles
    assert "font-size: clamp(46px, 5vw, 60px);" in styles
    assert "font-size: 12px; font-weight: 800; letter-spacing: .12em;" in styles
    assert "font-size: 27px; font-weight: 800; color: var(--text-strong); line-height: 1.15;" in styles
    assert ".metric-value small { font-size: 13.5px;" in styles


def test_oled_theme_uses_green_palette(client):
    styles = client.get("/assets/styles.css").text
    app_js = client.get("/assets/app.js").text
    index = client.get("/").text

    oled = styles.split(':root[data-theme="oled"]', 1)[1].split(':root[data-theme="light"]', 1)[0]
    assert "--bg: #07110f" in oled
    assert "--surface: #0c1916" in oled
    assert "--accent: #47e6a4" in oled
    assert "--chart-s1: #47e6a4" in oled
    assert "--chart-s2: #ff9f43" in oled
    assert 'oled: "#07110f"' in app_js
    assert 'data-theme-set="oled">◐<span>OLED</span>' in index


def test_gptsol10_dashboard_has_requested_metric_order_and_full_width_chart(client):
    app_js = client.get("/assets/app.js").text
    styles = client.get("/assets/styles.css").text
    overview = app_js.split("function overviewHtml()", 1)[1].split("function parametersForSection", 1)[0]
    markers = [
        "PODAJNIK",
        "OBCIĄŻENIE",
        "WENTYLATOR",
        "MIESZACZ",
        "CWU",
        "POZIOM PALIWA",
        "ALARMY AKTYWNE",
    ]
    positions = [overview.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert all(label not in overview for label in ("MOC CHWILOWA", "PŁOMIEŃ", "POWRÓT", "PELLET DZISIAJ", "SPALANIE CHWILOWE", "USTAWIENIA SPALANIA"))
    assert 'data-open-view="alarms"' in overview
    assert "STAN KOTŁA" not in overview
    assert "OSTATNIE ALARMY" not in overview
    assert 'class="bottom-row bottom-row-full"' in overview
    top_cards = overview.split('<div class="top-cards">', 1)[1].split('</div>\n\n        <div class="metric-row">', 1)[0]
    assert all(marker in top_cards for marker in ("PODAJNIK", "OBCIĄŻENIE"))
    assert "grid-template-columns: 1.7fr repeat(3, 1fr)" in styles


def test_embedded_system_pages_follow_green_oled_palette():
    from app.admin_pages import STYLE

    oled = STYLE.split(':root[data-theme="oled"]', 1)[1].split("@media", 1)[0]
    assert "--bg:#07110f" in oled
    assert "--surface:#0c1916" in oled
    assert "--s2:#10211d" in oled
    assert "--accent:#47e6a4" in oled


def test_frontend_refreshes_parameter_views_and_detects_stale_websocket(client):
    app_js = client.get("/assets/app.js").text
    assert "refreshActiveSnapshotView();" in app_js
    assert "liveParameterViews" in app_js
    assert "Date.now() - state.lastWebsocketAt > 6000" in app_js
    assert 'state.activeView === "mixer"' in app_js
    assert 'parametersForSection("mixer").length === 0' in app_js
    assert 'state.websocket?.readyState !== WebSocket.OPEN || websocketStale' in app_js


def test_release_builder_syncs_every_runtime_app_file():
    """Wydanie nie może mieć nowego UI i starych mapowań/serializera."""
    from pathlib import Path

    from tools.build_gptsol_releases import ROOT, SHARED_FILES

    synchronized = set(SHARED_FILES)
    runtime_files = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "app").rglob("*")
        if path.is_file()
        and path.suffix != ".pyc"
        and "__pycache__" not in path.parts
    }
    assert runtime_files <= synchronized
    assert "app/mappings.py" in synchronized
    assert "app/serializer.py" in synchronized


def test_frontend_distinguishes_unconfirmed_write_from_error(client):
    app_js = client.get("/assets/app.js").text
    styles = client.get("/assets/styles.css").text
    assert 'result.status === "unconfirmed" ? "warning"' in app_js
    assert "audit-result unconfirmed" not in app_js  # klasa powstaje dynamicznie z bezpiecznej stałej
    assert ".audit-result.unconfirmed" in styles
    assert ".toast.warning" in styles


def test_int_enum_values_serialize_as_numeric_codes():
    """IntEnum (pyplumio DeviceState) ma iść do MQTT/SQLite jako kod, nie str(enum).

    str(IntEnum) daje "DeviceState.WORKING" na Pythonie 3.10 i "3" na 3.11+ —
    payload nie może zależeć od wersji interpretera.
    """
    from enum import Enum, IntEnum

    from app.mqtt import _scalar_text
    from app.serializer import simple_value

    class FakeDeviceState(IntEnum):
        WORKING = 3

    stored = simple_value(FakeDeviceState.WORKING)
    assert stored == 3 and type(stored) is int
    assert _scalar_text(stored) == "3"

    class PlainEnum(Enum):
        CELSIUS = "°C"

    assert simple_value(PlainEnum.CELSIUS) == {"name": "CELSIUS", "value": "°C"}


def test_mqtt_raw_topics_skip_profile_metadata():
    from app.config import MqttConfig
    from app.mqtt import MqttPublisher

    class Info:
        rc = 0

    class Client:
        def __init__(self):
            self.calls = []

        def publish(self, topic, payload, **kwargs):
            self.calls.append(topic)
            return Info()

    publisher = MqttPublisher(MqttConfig(enabled=True, home_assistant_discovery=False))
    publisher._client = Client()
    publisher._mqtt = SimpleNamespace(MQTT_ERR_SUCCESS=0)
    publisher._connected = True
    snapshot = {
        "connected": True,
        "values": {"heating_temp": 67.5},
        "parameters": {
            "heating_target_temp": {"native_value": 75, "value": 75, "label": "Temperatura zadana", "options": {}},
        },
        "mixers": {
            "0": {
                "values": {"current_temp": 42.0},
                "parameters": {"mixer_target_temp": {"native_value": 50, "label": "Zadana mieszacza"}},
            }
        },
        "profile": {"entities": [{"path": "value/heating_temp", "label": "Kocioł", "unit": "°C"}]},
    }
    asyncio.run(publisher.publish(snapshot))
    calls = publisher._client.calls
    leaked = [t for t in calls if t.startswith("plumbox/raw/profile") or t.endswith("/label") or t.endswith("/options")]
    assert leaked == [], f"raw/** nie może zawierać metadanych UI: {leaked}"
    assert "plumbox/raw/values/heating_temp" in calls
    assert "plumbox/raw/parameters/heating_target_temp" in calls
    assert "plumbox/raw/mixers/0/values/current_temp" in calls
    assert "plumbox/raw/mixers/0/parameters/mixer_target_temp" in calls
    assert "plumbox/profile" in calls


def test_communication_form_does_not_leak_and_keeps_mqtt_password(client):
    import yaml

    from app.deps import CONFIG_PATH

    base_form = {
        "connection_type": "simulation",
        "host": "192.168.1.50",
        "port": "8899",
        "serial_device": "/dev/ttyUSB0",
        "baudrate": "115200",
        "profile_mode": "fixed_ecomax860p4",
        "mqtt_enabled": "1",
        "mqtt_host": "127.0.0.1",
        "mqtt_port": "1883",
        "mqtt_username": "plum",
        "mqtt_base_topic": "plumbox",
        "mqtt_discovery": "1",
    }
    saved = client.post(
        "/communication",
        data={**base_form, "mqtt_password": "sekret-brokera-123"},
        follow_redirects=False,
    )
    assert saved.status_code == 303

    page = client.get("/communication").text
    assert "sekret-brokera-123" not in page

    resaved = client.post("/communication", data={**base_form, "mqtt_password": ""}, follow_redirects=False)
    assert resaved.status_code == 303
    cfg = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8"))
    assert cfg["mqtt"]["password"] == "sekret-brokera-123"

    # Sprzątanie: nie zostawiamy mqtt.enabled=true we współdzielonym configu testów.
    cleanup_form = {key: value for key, value in base_form.items() if key != "mqtt_enabled"}
    assert client.post(
        "/communication", data={**cleanup_form, "mqtt_password": ""}, follow_redirects=False
    ).status_code == 303
    cfg = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8"))
    assert cfg["mqtt"]["enabled"] is False


def test_daily_fuel_integrates_only_fresh_measurements(tmp_path):
    from app.database import Database

    database = Database(str(tmp_path / "fuel.db"))

    async def scenario():
        await database.initialize()
        for timestamp, rate in (
            ("2026-07-14T00:00:00+00:00", 3.6),
            ("2026-07-14T00:05:00+00:00", 7.2),
        ):
            await database.add_sample({
                "timestamp": timestamp,
                "connected": True,
                "values": {"fuel_consumption": rate},
                "mixers": {},
            })
        return await database.fuel_consumption_between(
            datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 14, 0, 12, tzinfo=timezone.utc),
        )

    # 5 min × 3.6 kg/h + maks. 5 min × 7.2 kg/h; ostatnie 2 min to luka.
    assert asyncio.run(scenario()) == pytest.approx(0.9)


def test_summary_endpoint_exposes_measured_daily_fuel(client):
    payload = client.get("/api/summary").json()
    assert set(payload) == {"fuel_today_kg", "timezone", "since"}
    assert payload["fuel_today_kg"] is None or payload["fuel_today_kg"] >= 0


def test_controller_profile_uses_parameter_units_from_snapshot():
    from app.controller_profile import detected_entities

    snapshot = {
        "values": {},
        "parameters": {
            "airflow_power_100": {"native_value": 65, "unit": "%", "writable": False},
            "fuel_calorific_value": {"native_value": 4.8, "unit": "kWh/kg", "writable": False},
        },
        "mixers": {},
    }
    entities = {entity["key"]: entity for entity in detected_entities(snapshot)}
    assert entities["airflow_power_100"]["unit"] == "%"
    assert entities["fuel_calorific_value"]["unit"] == "kWh/kg"


def test_live_snapshot_keeps_mixer_parameters_when_one_frame_is_sparse():
    from app.plum_service import PlumService

    previous = {
        "connected": True,
        "values": {"heating_temp": 70},
        "parameters": {"heating_target_temp": {"value": 75}},
        "mixers": {
            "0": {
                "values": {"current_temp": 44, "pump": True},
                "parameters": {"mixer_target_temp": {"value": 50}},
            }
        },
        "statistics": {"received_frames": 10},
    }
    sparse_frame = {
        "connected": True,
        "values": {"heating_temp": 71},
        "parameters": {},
        "mixers": {},
        "statistics": {"received_frames": 11},
    }

    merged = PlumService._merge_live_snapshot(previous, sparse_frame)

    assert merged["values"]["heating_temp"] == 71
    assert merged["parameters"]["heating_target_temp"]["value"] == 75
    assert merged["mixers"]["0"]["values"] == {"current_temp": 44, "pump": True}
    assert merged["mixers"]["0"]["parameters"]["mixer_target_temp"]["value"] == 50
    assert merged["statistics"]["received_frames"] == 11


def test_live_snapshot_drops_cache_after_disconnect():
    from app.plum_service import PlumService

    previous = {
        "connected": True,
        "values": {},
        "parameters": {},
        "mixers": {"0": {"values": {"current_temp": 44}, "parameters": {}}},
        "statistics": {},
    }
    offline = {
        "connected": False,
        "values": {},
        "parameters": {},
        "mixers": {},
        "statistics": {},
    }

    assert PlumService._merge_live_snapshot(previous, offline)["mixers"] == {}


def test_failed_parameter_group_requests_are_retried_without_restart(tmp_path):
    """Regresja ze snapshotu 2026-07-18: frame error 50, mieszacz 0/8 parametrów."""
    import asyncio

    from app.config import AppConfig
    from app.database import Database
    from app.plum_service import PlumService

    class Device:
        def __init__(self):
            self.data = {
                "frame_errors": [61, 50],
                "ecomax_parameters": True,
                "mixers": {0: object()},
            }
            self.requests = []

        async def request(self, name, frame_type, retries=3, timeout=3.0):
            self.requests.append((name, int(frame_type), retries, timeout))
            self.data[name] = True
            return True

    config = AppConfig()
    config.connection.type = "tcp"
    service = PlumService(config, Database(str(tmp_path / "retry.db")))
    device = Device()
    service._device = device
    service._connection = SimpleNamespace(connected=True)

    missing = service._missing_parameter_groups(device)
    assert missing == [("mixer_parameters", 50)]
    asyncio.run(service._retry_parameter_groups(device, missing))
    assert device.requests == [("mixer_parameters", 50, 3, 3.0)]
    assert service._missing_parameter_groups(device) == []

    # Analogiczna utrata głównej grupy (frame 49) też ma być odzyskiwana.
    device.data = {"frame_errors": [49], "mixers": {}}
    assert service._missing_parameter_groups(device) == [("ecomax_parameters", 49)]

    # Product/UID (frame 57) jest zależnością bramki RPM i też musi wrócić bez restartu.
    device.data = {"frame_errors": [57], "mixers": {}}
    device.requests = []
    missing = service._missing_parameter_groups(device)
    assert missing == [("product", 57)]
    asyncio.run(service._retry_parameter_groups(device, missing))
    assert device.requests == [("product", 57, 3, 3.0)]


def test_unknown_enum_alert_keeps_library_identifier():
    from app.serializer import alert_to_dict

    class FutureAlert(Enum):
        EXAMPLE_DIAGNOSTIC = 57

    payload = alert_to_dict(SimpleNamespace(code=FutureAlert.EXAMPLE_DIAGNOSTIC, from_dt=None, to_dt=None))
    assert payload["name"] == "Alarm 57 (EXAMPLE_DIAGNOSTIC)"


def test_unverified_raw_state_is_not_translated():
    from app.serializer import state_label

    assert state_label(12) == "Stan 12"
    assert state_label(23) == "Stan 23"


def test_product_211_profile_labels_startup_state_6_as_cleaning_only_for_that_profile():
    from app.serializer import state_label

    assert state_label(6) == "Czuwanie"
    assert state_label(6, ecomax860p4_profile_enabled=True) == "Czyszczenie"
    assert state_label(2, ecomax860p4_profile_enabled=True) == "Rozpalanie"
    assert state_label(3, ecomax860p4_profile_enabled=True) == "Praca"


def test_deep_user_actions_redirect_back_to_users(anon_client):
    from app.users import USERS_PATH, add_user, load_users

    username = "redirect_operator"
    if username not in load_users(USERS_PATH)["users"]:
        add_user(username, "redirectpass123", "user", path=USERS_PATH)
    _login(anon_client, "admin", "testpass123")

    password_response = anon_client.post(
        "/users/password",
        data={"username": username, "password": "redirectpass456"},
        follow_redirects=False,
    )
    assert password_response.status_code == 303
    password_target = urlparse(urljoin("http://testserver/users/password", password_response.headers["location"]))
    assert password_target.path == "/users"

    delete_response = anon_client.post(
        "/users/delete",
        data={"username": username},
        follow_redirects=False,
    )
    assert delete_response.status_code == 303
    delete_target = urlparse(urljoin("http://testserver/users/delete", delete_response.headers["location"]))
    assert delete_target.path == "/users"


def test_deep_anonymous_path_redirects_to_root_login(anon_client):
    response = anon_client.get("/users/delete", follow_redirects=False)
    assert response.status_code == 303
    target = urlparse(urljoin("http://testserver/users/delete", response.headers["location"]))
    assert target.path == "/login"


def test_login_attempts_are_rate_limited(anon_client):
    for _ in range(5):
        response = anon_client.post(
            "/login",
            data={"username": "rate_limit_probe", "password": "wrong-password"},
            follow_redirects=False,
        )
        assert response.status_code == 303
    blocked = anon_client.post(
        "/login",
        data={"username": "rate_limit_probe", "password": "wrong-password"},
        follow_redirects=False,
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_pin_attempts_are_rate_limited(anon_client):
    _login(anon_client, "admin", "testpass123")
    for _ in range(5):
        assert anon_client.post("/api/auth/unlock", json={"pin": "0000"}).status_code == 401
    blocked = anon_client.post("/api/auth/unlock", json={"pin": "0000"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_addon_config_can_preserve_existing_pin_hash():
    if importlib.util.find_spec("addon_init") is None:
        pytest.skip("Test dotyczy wyłącznie pakietu dodatku Home Assistant")
    from addon_init import make_config

    preserved = "scrypt$existing$safely-preserved"
    config = make_config({"initial_pin": ""}, preserved_pin_hash=preserved)
    assert config["security"]["pin"] is None
    assert config["security"]["pin_hash"] == preserved


def test_auto_detect_does_not_guess_unknown_units():
    from app.controller_profile import detected_entities

    entities = detected_entities({"values": {"unknown_power": 50, "mystery_temp": 21}, "parameters": {}, "mixers": {}})
    by_key = {entity["key"]: entity for entity in entities}
    assert by_key["unknown_power"]["unit"] is None
    assert "device_class" not in by_key["unknown_power"]
    assert by_key["mystery_temp"]["unit"] is None


def test_database_state_is_defensively_normalized():
    from app.database import integer_or_none

    class RawState(Enum):
        WORK = 3

    assert integer_or_none(RawState.WORK) == 3
    assert integer_or_none({"name": "WORK", "value": 3}) == 3
    assert integer_or_none({"unexpected": "shape"}) is None


def test_websocket_broadcast_rejects_revoked_session():
    from app.deps import WebSocketHub, state

    class Socket:
        def __init__(self):
            self.accepted = False
            self.closed = None
            self.sent = []

        async def accept(self):
            self.accepted = True

        async def close(self, code):
            self.closed = code

        async def send_json(self, payload):
            self.sent.append(payload)

    async def scenario():
        hub = WebSocketHub()
        socket = Socket()
        await hub.connect(socket, "revoked-token")
        await hub.broadcast({"connected": True})
        return hub, socket

    had_store = hasattr(state, "user_sessions")
    old_store = getattr(state, "user_sessions", None)
    state.user_sessions = SimpleNamespace(get=lambda _token: None)
    try:
        hub, socket = asyncio.run(scenario())
    finally:
        if had_store:
            state.user_sessions = old_store
        else:
            delattr(state, "user_sessions")
    assert socket.accepted is True
    assert socket.closed == 1008
    assert socket.sent == []
    assert hub.clients == {}


def test_recent_last_login_does_not_rewrite_users_file(tmp_path, monkeypatch):
    import app.users as users_module

    path = tmp_path / "users.yaml"
    users_module.ensure_initial_admin(path, password="recentlogin123")
    data = users_module.load_users(path)
    data["users"]["admin"]["last_login_at"] = datetime.now(timezone.utc).isoformat()
    users_module.save_users(data, path)
    writes = []
    monkeypatch.setattr(users_module, "save_users", lambda *_args, **_kwargs: writes.append(True))
    assert users_module.authenticate("admin", "recentlogin123", path) is not None
    assert writes == []


def test_advanced_writes_follow_config_and_require_admin(anon_client):
    """GPT SOL: safe_writes_only=false odblokowuje advanced/critical,
    ale wyłącznie dla admina i z jawnym potwierdzeniem."""
    from app.deps import state
    from app.users import USERS_PATH, add_user, load_users

    if "adv_operator" not in load_users(USERS_PATH)["users"]:
        add_user("adv_operator", "advoperator123", "user", path=USERS_PATH)

    _login(anon_client, "admin", "testpass123")
    admin_token = anon_client.post("/api/auth/unlock", json={"pin": "1234"}).json()["token"]
    admin_headers = {"X-Plumbox-Token": admin_token}
    payload = {"name": "boiler_power_100", "value": 12, "confirmed": True}

    old_flag = state.config.security.safe_writes_only
    try:
        state.config.security.safe_writes_only = True
        assert anon_client.post("/api/set", json=payload, headers=admin_headers).status_code == 403

        state.config.security.safe_writes_only = False
        no_confirm = anon_client.post("/api/set", json={**payload, "confirmed": False}, headers=admin_headers)
        assert no_confirm.status_code == 409
        allowed = anon_client.post("/api/set", json=payload, headers=admin_headers)
        assert allowed.status_code == 200 and allowed.json()["success"] is True

        # writable w snapshotcie podąża za konfiguracją
        snapshot = anon_client.get("/api/snapshot").json()
        assert snapshot["parameters"]["boiler_power_100"]["writable"] is True

        # zwykły user nadal nie może zapisywać advanced/critical
        _login(anon_client, "adv_operator", "advoperator123")
        user_token = anon_client.post("/api/auth/unlock", json={"pin": "1234"}).json()["token"]
        denied = anon_client.post("/api/set", json=payload, headers={"X-Plumbox-Token": user_token})
        assert denied.status_code == 403
    finally:
        state.config.security.safe_writes_only = old_flag


def test_discovery_marks_instant_readings_for_ha_statistics():
    """Encje sensor z jednostką chwilową dostają state_class=measurement,
    żeby HA budował z nich statystyki długoterminowe."""
    import json as json_module

    from app.config import MqttConfig
    from app.mqtt import MqttPublisher

    class Info:
        rc = 0

    class Client:
        def __init__(self):
            self.payloads = {}

        def publish(self, topic, payload, **_kwargs):
            self.payloads[topic] = payload
            return Info()

    publisher = MqttPublisher(MqttConfig(enabled=True))
    publisher._client = Client()
    publisher._mqtt = SimpleNamespace(MQTT_ERR_SUCCESS=0)
    publisher._connected = True
    entities = [
        {"path": "value/heating_temp", "label": "Kocioł", "unit": "°C", "domain": "sensor"},
        {"path": "value/fuel_burned", "label": "Spalone paliwo", "unit": "kg", "domain": "sensor"},
        {"path": "value/fan", "label": "Wentylator", "unit": None, "domain": "binary_sensor"},
    ]
    publisher._publish_discovery({"profile": {"name": "test"}}, entities)
    configs = {topic: json_module.loads(payload) for topic, payload in publisher._client.payloads.items() if payload}
    temp = configs["homeassistant/sensor/plumbox/value_heating_temp/config"]
    assert temp["state_class"] == "measurement"
    assert temp["device_class"] == "temperature" if "device_class" in temp else True
    burned = configs["homeassistant/sensor/plumbox/value_fuel_burned/config"]
    assert "state_class" not in burned
    fan = configs["homeassistant/binary_sensor/plumbox/value_fan/config"]
    assert "state_class" not in fan and fan["payload_on"] == "True"


def test_airflow_correction_offset_is_hardware_confirmed():
    """Potwierdzone 2026-07-17 na ecoMAX 860P4 użytkownika: korekty nadmuchu
    mają natywne przesunięcie +100 (natywne 101 = +1 na panelu kotła).
    Pozostałe parametry nadal bez przeliczania."""
    from app.mappings import display_value, native_value

    assert display_value("airflow_correction_100", 101, airflow_correction_enabled=True) == 1
    assert display_value("airflow_correction_100", 80, airflow_correction_enabled=True) == -20
    assert display_value("airflow_correction_50", 100, airflow_correction_enabled=True) == 0
    assert native_value("airflow_correction_30", -5, airflow_correction_enabled=True) == 95
    assert native_value("airflow_correction_100", 1, airflow_correction_enabled=True) == 101
    # Brak dowodu = brak przeliczania.
    assert display_value("heating_target_temp", 75) == 75
    assert display_value("airflow_correction_100", None, airflow_correction_enabled=True) is None


def test_fan_rpm_scale_is_hardware_confirmed_for_ecomax_860p4_pe():
    """Pary native/RPM potwierdzone snapshotem PlumBox i ekranami ecoNET."""
    from app.mappings import (
        display_step,
        display_value,
        fan_rpm_profile_enabled,
        fan_rpm_profile_state,
        native_value,
    )

    confirmed = {
        "kindling_airflow_power": (115, 1450),
        "stabilization_airflow_power": (95, 1250),
        "burning_off_airflow_power": (130, 1600),
        "cleaning_airflow_power": (180, 2100),
    }
    for name, (native, rpm) in confirmed.items():
        assert display_value(name, native, fan_rpm_enabled=True) == rpm
        assert native_value(name, rpm, fan_rpm_enabled=True) == native
        assert display_step(name, 1, fan_rpm_enabled=True) == 10

    with pytest.raises(ValueError, match="co 10 obr/min"):
        native_value("kindling_airflow_power", 1455, fan_rpm_enabled=True)

    assert fan_rpm_profile_enabled("fixed_ecomax860p4", 211) is True
    assert fan_rpm_profile_enabled("fixed_ecomax860p4", None) is True
    assert fan_rpm_profile_enabled("auto_detect", 211) is True
    assert fan_rpm_profile_state("fixed_ecomax860p4", 211)["status"] == "verified"
    assert fan_rpm_profile_state("fixed_ecomax860p4", None)["status"] == "fixed_fallback"


def test_fan_rpm_scale_is_not_applied_to_unknown_auto_detect_controller():
    """Regresja audytu Opusa: komentarz o product ID nie może zastępować bramki."""
    from app.mappings import (
        display_step,
        display_value,
        fan_rpm_profile_enabled,
        fan_rpm_profile_state,
        native_value,
    )

    assert fan_rpm_profile_enabled("auto_detect", 999) is False
    assert fan_rpm_profile_enabled("auto_detect", None) is False
    assert fan_rpm_profile_state("auto_detect", 999)["status"] == "foreign"
    assert fan_rpm_profile_state("auto_detect", None)["status"] == "inactive"
    assert fan_rpm_profile_state("fixed_ecomax860p4", 999)["status"] == "foreign"
    assert display_value("kindling_airflow_power", 115) == 115
    assert native_value("kindling_airflow_power", 1450) == 1450
    assert display_step("kindling_airflow_power", 1) == 1


def test_pellasx_service_sections_match_econet_and_hardware_photos():
    """Potwierdzone przez ecoNET i zdjęcia panelu PellasX 2026-07-18.

    PyPlumIO opisuje część prędkości wentylatora jako %, ale sterownik
    koduje je jako (RPM - 300) / 10; dashboard prezentuje rzeczywiste RPM.
    """
    from app.mappings import meta_for

    expected = {
        "kindling_airflow_power": ("Moc nadmuchu w trybie rozpalanie", "obr/min"),
        "kindling_airflow_delay": ("Czas przedmuchu przed rozpalaniem", "s"),
        "kindling_test_time": ("Czas testu zapłonu", "s"),
        "kindling_finish_threshold_temp": ("Próg detekcji płomienia przy czujniku optycznym", "%"),
        "kindling_time": ("Czas pracy grzałki w rozpalaniu", "min"),
        "warming_up_time": ("Czas rozgrzewania grzałki przed rozpalaniem", "s"),
        "kindling_min_power_time": ("Czas stabilizacji", "min"),
        "stabilization_time": ("Czas nadmuchu po rozpaleniu", "s"),
        "stabilization_airflow_power": ("Nadmuch po rozpaleniu", "obr/min"),
        "burning_off_max_time": ("Maksymalny czas wygaszania kotła", "min"),
        "burning_off_min_time": ("Minimalny czas po jakim kocioł kończy wygaszanie", "min"),
        "burning_off_airflow_power": ("Moc nadmuchu wygaszanie", "obr/min"),
        "burning_off_fan_work": ("Czas pracy nadmuchu w wygaszaniu", "s"),
        "burning_off_fan_pause": ("Przerwa nadmuchu w wygaszaniu", "s"),
        "start_burning_off": ("Próg detekcji płomienia rozpoczynający przedmuch wygaszania", "%"),
        "stop_burning_off": ("Próg detekcji płomienia kończący przedmuch wygaszania", "%"),
        "cleaning_begin_time": ("Czas czyszczenia w trybie rozpalanie", "s"),
        "burning_off_cleaning_time": ("Czas czyszczenia w wygaszaniu", "min"),
        "cleaning_airflow_power": ("Moc nadmuchu w trybie czyszczenia", "obr/min"),
        "warming_up_pause_time": ("Czas pracy do automatycznego czyszczenia kotła", "godz."),
        "supervision_time": ("Czas nadzoru", "min"),
    }
    for name, (label, unit) in expected.items():
        meta = meta_for(name)
        assert meta["label"] == label
        assert meta["unit"] == unit
        assert meta["section"] in {"kindling", "burning_off", "cleaning", "supervision"}


def test_pellasx_cwu_priority_codes_match_hardware():
    """Użytkownik potwierdził na kotle, że wcześniejsze opisy 1/2 były odwrócone."""
    from app.mappings import meta_for

    options = meta_for("water_heater_work_mode")["options"]
    assert options["1"] == "Praca z priorytetem"
    assert options["2"] == "Praca bez priorytetu"


def test_all_econet_screenshot_parameters_exist_and_have_exact_labels():
    """Komplet z ekranów Parametry użytkownika i Parametry serwisowe."""
    from app.mappings import meta_for

    user = {
        "heating_target_temp": "Temperatura zadana kotła",
        "fuzzy_logic": "Tryb pracy kotła",
        "thermostat_mode": "Wybór termostatu kotła",
        "h2_hysteresis": "Histereza H2 pracy kotła",
        "h1_hysteresis": "Histereza H1 pracy kotła",
        "heating_hysteresis": "Histereza pracy kotła",
        "boiler_power_100": "Moc kotła w kW dla pracy na poziomie 100%",
        "boiler_power_50": "Moc kotła w kW dla pracy na poziomie 50%",
        "boiler_power_30": "Moc kotła w kW dla pracy na poziomie 30%",
        "airflow_correction_30": "Korekta mocy nadmuchu przy 30% mocy kotła",
        "airflow_correction_50": "Korekta mocy nadmuchu przy 50% mocy kotła",
        "airflow_correction_100": "Korekta mocy nadmuchu przy 100% mocy kotła",
        "water_heater_target_temp": "Temperatura zadana zasobnika CWU",
        "water_heater_work_mode": "Tryb pracy pompy CWU",
        "water_heater_hysteresis": "Histereza zasobnika CWU",
        "water_heater_disinfection": "Dezynfekcja zbiornika CWU",
        "mixer_target_temp:mixer": "Temperatura zadana obiegu grzewczego",
        "thermostat_mode:mixer": "Wybór termostatu obiegu",
        "thermostat_decrease_target_temp:mixer": "Obniżenie temperatury zadanej obiegu przy rozwartym styku termostatu",
        "summer_mode": "Tryb LATO",
        "summer_mode_enable_temp": "Temperatura wejścia w tryb LATO",
        "summer_mode_disable_temp": "Temperatura wyjścia z trybu LATO",
    }
    service = {
        "min_heating_target_temp": "Minimalna temperatura zadana kotła",
        "max_heating_target_temp": "Maksymalna temperatura zadana kotła",
        "heating_pump_enable_temp": "Temperatura załączenia pompy kotła",
        "pause_heating_for_water_heater": "Czas postoju pompy kotła od CWU",
        "increase_heating_temp_for_water_heater": "Podwyższenie temperatury zadanej kotła od CWU, mieszaczy lub bufora",
        "disable_pump_on_thermostat": "Wyłączenie pompy kotła od termostatu",
        "boiler_alert_temp": "Temperatura alarmu przegrzania kotła",
        "max_feeder_temp": "Maksymalna temperatura podajnika",
        "external_boiler_temp": "Temperatura wyłączenia kotła zewnętrznego",
        "kindling_airflow_power": "Moc nadmuchu w trybie rozpalanie",
        "kindling_test_time": "Czas testu zapłonu",
        "kindling_time": "Czas pracy grzałki w rozpalaniu",
        "warming_up_time": "Czas rozgrzewania grzałki przed rozpalaniem",
        "kindling_finish_threshold_temp": "Próg detekcji płomienia przy czujniku optycznym",
        "kindling_min_power_time": "Czas stabilizacji",
        "stabilization_time": "Czas nadmuchu po rozpaleniu",
        "stabilization_airflow_power": "Nadmuch po rozpaleniu",
        "min_fan_power": "Minimalna moc nadmuchu jaką może ustawić użytkownik",
        "max_fuel_flow": "Szybkość podawania paliwa przez podajnik",
        "fuel_calorific_value": "Kaloryczność paliwa",
        "fuel_detection_time": "Czas detekcji braku paliwa",
        "burning_off_max_time": "Maksymalny czas wygaszania kotła",
        "burning_off_min_time": "Minimalny czas po jakim kocioł kończy wygaszanie",
        "burning_off_airflow_power": "Moc nadmuchu wygaszanie",
        "burning_off_fan_work": "Czas pracy nadmuchu w wygaszaniu",
        "burning_off_fan_pause": "Przerwa nadmuchu w wygaszaniu",
        "start_burning_off": "Próg detekcji płomienia rozpoczynający przedmuch wygaszania",
        "stop_burning_off": "Próg detekcji płomienia kończący przedmuch wygaszania",
        "cleaning_begin_time": "Czas czyszczenia w trybie rozpalanie",
        "burning_off_cleaning_time": "Czas czyszczenia w wygaszaniu",
        "cleaning_airflow_power": "Moc nadmuchu w trybie czyszczenia",
        "warming_up_pause_time": "Czas pracy do automatycznego czyszczenia kotła",
        "supervision_time": "Czas nadzoru",
        "min_water_heater_target_temp": "Minimalna temperatura zadana zasobnika CWU",
        "max_water_heater_target_temp": "Maksymalna temperatura zadana zasobnika CWU",
        "water_heater_work_extension": "Czas wydłużenia ładowania zasobnika CWU",
        "min_target_temp:mixer": "Minimalna temperatura zadana obiegu grzewczego",
        "max_target_temp:mixer": "Maksymalna temperatura zadana obiegu grzewczego",
        "work_mode:mixer": "Obsługa mieszacza",
        "mixer_input_dead_zone:mixer": "Nieczułość obiegu mieszacza",
        "disable_pump_on_thermostat:mixer": "Wyłączenie pompy mieszacza od termostatu",
    }

    for key, label in user.items():
        scope = "mixer" if key.endswith(":mixer") else "ecomax"
        meta = meta_for(key.removesuffix(":mixer"), scope)
        assert meta["label"] == label
        assert meta["access"] == "user"
    for key, label in service.items():
        scope = "mixer" if key.endswith(":mixer") else "ecomax"
        meta = meta_for(key.removesuffix(":mixer"), scope)
        assert meta["label"] == label
        assert meta["access"] == "service"


def test_service_work_view_contains_all_four_econet_parameters_in_order():
    root = Path(__file__).resolve().parents[1]
    js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")

    expected = 'fuel_calibration: ["min_fan_power", "max_fuel_flow", "fuel_calorific_value", "fuel_detection_time"]'
    assert expected in js
    assert 'fuel_calibration: "PRACA"' in js
    assert 'data-view="fuel_calibration"><span>⚙</span>Praca' in html
    assert html.index('data-view="fuel_calibration"') > html.index('<div class="nav-group">Serwis</div>')
    assert "function userFirst(parameters)" in js


def test_econet_user_and_mixer_labels_are_preserved():
    from app.mappings import meta_for

    expected = {
        "fuzzy_logic": "Tryb pracy kotła",
        "thermostat_mode": "Wybór termostatu kotła",
        "water_heater_target_temp": "Temperatura zadana zasobnika CWU",
        "water_heater_work_mode": "Tryb pracy pompy CWU",
        "water_heater_hysteresis": "Histereza zasobnika CWU",
        "mixer_target_temp": "Temperatura zadana obiegu grzewczego",
        "thermostat_decrease_target_temp": "Obniżenie temperatury zadanej obiegu przy rozwartym styku termostatu",
        "work_mode": "Obsługa mieszacza",
        "mixer_input_dead_zone": "Nieczułość obiegu mieszacza",
        "thermostat_mode:mixer": "Wybór termostatu obiegu",
    }
    for name, label in expected.items():
        scope = "mixer" if name.endswith(":mixer") else "ecomax"
        raw_name = name.removesuffix(":mixer")
        assert meta_for(raw_name, scope)["label"] == label


def test_hardware_fan_speed_is_scaled_to_rpm():
    from types import SimpleNamespace

    from app.serializer import parameter_to_dict

    parameter = SimpleNamespace(
        value=115,
        min_value=10,
        max_value=255,
        unit_of_measurement="%",
        description=SimpleNamespace(step=1, unit_of_measurement="%"),
    )
    payload = parameter_to_dict(
        "kindling_airflow_power",
        parameter,
        fan_rpm_enabled=True,
    )
    assert payload["value"] == 1450
    assert payload["native_value"] == 115
    assert payload["min"] == 400
    assert payload["max"] == 2850
    assert payload["step"] == 10
    assert payload["unit"] == "obr/min"


def test_unknown_controller_keeps_native_fan_value_and_pyplumio_unit():
    from types import SimpleNamespace

    from app.serializer import parameter_to_dict

    parameter = SimpleNamespace(
        value=115,
        min_value=10,
        max_value=255,
        unit_of_measurement="%",
        description=SimpleNamespace(step=1, unit_of_measurement="%"),
    )
    payload = parameter_to_dict("kindling_airflow_power", parameter)
    assert payload["value"] == 115
    assert payload["native_value"] == 115
    assert payload["min"] == 10
    assert payload["max"] == 255
    assert payload["step"] == 1
    assert payload["unit"] == "%"


def test_auto_detect_uses_snapshot_product_id_to_gate_fan_rpm(tmp_path):
    from types import SimpleNamespace

    from app.config import AppConfig
    from app.database import Database
    from app.plum_service import PlumService

    parameter = SimpleNamespace(
        value=115,
        min_value=10,
        max_value=255,
        unit_of_measurement="%",
        description=SimpleNamespace(step=1, unit_of_measurement="%"),
    )
    connection = SimpleNamespace(connected=True, statistics={})

    def snapshot_for(product_id, mode="auto_detect", include_product=True):
        config = AppConfig()
        config.connection.type = "tcp"
        config.profile.mode = mode
        service = PlumService(config, Database(str(tmp_path / f"{product_id}.db")))
        data = {"kindling_airflow_power": parameter}
        if include_product:
            data["product"] = {"id": product_id, "model": f"test-{product_id}"}
        device = SimpleNamespace(data=data)
        return service._build_snapshot(connection, device)

    known_snapshot = snapshot_for(211)
    known = known_snapshot["parameters"]["kindling_airflow_power"]
    assert known["value"] == 1450
    assert known["unit"] == "obr/min"
    assert known_snapshot["hardware_profile"]["status"] == "verified"

    foreign_snapshot = snapshot_for(999)
    foreign = foreign_snapshot["parameters"]["kindling_airflow_power"]
    assert foreign["value"] == 115
    assert foreign["unit"] == "%"
    assert foreign_snapshot["hardware_profile"]["status"] == "foreign"

    auto_missing = snapshot_for(None, include_product=False)
    assert auto_missing["parameters"]["kindling_airflow_power"]["value"] == 115
    assert auto_missing["hardware_profile"]["status"] == "inactive"

    fixed_missing = snapshot_for(None, mode="fixed_ecomax860p4", include_product=False)
    assert fixed_missing["parameters"]["kindling_airflow_power"]["value"] == 1450
    assert fixed_missing["hardware_profile"]["status"] == "fixed_fallback"


def test_hardware_identification_source_is_visible_in_model_badge():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="modelSourceBadge"' in html
    assert 'fixed_fallback: "MODEL: FIXED"' in js
    assert 'inactive: "MODEL: NIEZNANY"' in js
    assert 'modelBadge.title = hardware.label || "Źródło identyfikacji modelu"' in js


def test_html_pages_are_not_browser_cached(client, anon_client):
    """Bez no-store przeglądarka odtwarzała dashboard z cache po wylogowaniu
    (HA Ingress: powrót do zakładki pokazywał pusty panel zamiast logowania)."""
    assert client.get("/").headers.get("cache-control") == "no-store"
    assert anon_client.get("/login").headers.get("cache-control") == "no-store"
    # statyki pozostają cache'owalne (wersjonowane adresy)
    assert client.get("/assets/styles.css").headers.get("cache-control") != "no-store"


def test_boiler_on_off_requires_explicit_confirmation(anon_client):
    """Włączenie/wyłączenie kotła (ecomax_control, risk=safe) wymaga confirmed=true."""
    _login(anon_client, "admin", "testpass123")
    token = anon_client.post("/api/auth/unlock", json={"pin": "1234"}).json()["token"]
    headers = {"X-Plumbox-Token": token}

    denied = anon_client.post("/api/set", json={"name": "ecomax_control", "value": True}, headers=headers)
    assert denied.status_code == 409

    allowed = anon_client.post(
        "/api/set",
        json={"name": "ecomax_control", "value": True, "confirmed": True},
        headers=headers,
    )
    assert allowed.status_code == 200 and allowed.json()["success"] is True


def test_account_password_change_requires_old_password(anon_client):
    from app.users import USERS_PATH, add_user, load_users, verify_user_password

    if "haslo_tester" not in load_users(USERS_PATH)["users"]:
        add_user("haslo_tester", "starehaslo123", "user", path=USERS_PATH)
    _login(anon_client, "haslo_tester", "starehaslo123")

    wrong = anon_client.post(
        "/account",
        data={"old_password": "zle-haslo", "new_password": "nowehaslo123", "repeat_password": "nowehaslo123"},
        follow_redirects=False,
    )
    assert wrong.status_code == 303 and "error" in wrong.headers["location"]
    assert verify_user_password("haslo_tester", "starehaslo123", USERS_PATH)

    changed = anon_client.post(
        "/account",
        data={"old_password": "starehaslo123", "new_password": "nowehaslo123", "repeat_password": "nowehaslo123"},
        follow_redirects=False,
    )
    assert changed.status_code == 303 and "message" in changed.headers["location"]
    assert verify_user_password("haslo_tester", "nowehaslo123", USERS_PATH)
    # bieżąca sesja dostała nowy token w cookie i nadal działa
    assert anon_client.get("/account").status_code == 200


def test_dockerfile_env_has_no_dangling_continuation():
    from pathlib import Path

    root = Path(__file__).parents[1]
    candidates = [root / "Dockerfile", root / "docker" / "Dockerfile"]
    dockerfiles = [path.read_text(encoding="utf-8") for path in candidates if path.exists()]
    assert dockerfiles
    for dockerfile in dockerfiles:
        assert "PLUMBOX_USERS=/data/users.yaml \\\n\n" not in dockerfile


def test_installation_specific_pump_labels_are_explicit():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'deviceLine("♨", "Pompa kotłowa"' in app_js
    assert 'deviceLine("◉", "Pompa CO za mieszaczem"' in app_js
    assert 'deviceLine("♨", "Pompa CO"' not in app_js
    assert 'deviceLine("◉", "Pompa mieszacza"' not in app_js

