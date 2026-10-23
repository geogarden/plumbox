import asyncio
import sys
from types import SimpleNamespace

import pytest

from app.config import AppConfig
from app.plum_service import PlumService, TransportPhaseTimeout


class HangingEnterConnection:
    async def __aenter__(self):
        await asyncio.Event().wait()

    async def __aexit__(self, *_args):
        return False


class BaseEnteredConnection:
    connected = True

    def __init__(self):
        self.protocol = SimpleNamespace(
            writer=None,
            statistics=SimpleNamespace(
                received_frames=0,
                failed_frames=0,
                sent_frames=0,
            ),
            reader=None,
            tasks=set(),
        )
        self.tasks = set()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def cancel_tasks(self):
        return True

    async def wait_until_done(self):
        return None


class HangingGetConnection(BaseEnteredConnection):
    async def get(self, *_args, **_kwargs):
        await asyncio.Event().wait()


class HangingExitConnection(BaseEnteredConnection):
    async def get(self, *_args, **_kwargs):
        return SimpleNamespace()

    async def __aexit__(self, *_args):
        await asyncio.Event().wait()


def config_for_test() -> AppConfig:
    config = AppConfig()
    config.connection.type = "tcp"
    config.connection.connect_timeout_seconds = 0.03
    config.connection.device_timeout_seconds = 0.03
    config.connection.cleanup_timeout_seconds = 0.03
    config.connection.reconnect_delay_seconds = 0.01
    return config


def test_opening_tcp_timeout_is_bounded_and_identified(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "pyplumio",
        SimpleNamespace(open_tcp_connection=lambda *_a, **_k: HangingEnterConnection()),
    )
    service = PlumService(config_for_test(), SimpleNamespace())

    with pytest.raises(TransportPhaseTimeout) as captured:
        asyncio.run(service._connection_session())

    assert captured.value.phase == "opening_tcp"
    assert service.transport_health()["phase"] == "idle"


def test_waiting_for_ecomax_timeout_is_bounded_and_identified(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "pyplumio",
        SimpleNamespace(open_tcp_connection=lambda *_a, **_k: HangingGetConnection()),
    )
    service = PlumService(config_for_test(), SimpleNamespace())

    with pytest.raises(TransportPhaseTimeout) as captured:
        asyncio.run(service._connection_session())

    assert captured.value.phase == "waiting_ecomax"
    assert service.transport_health()["phase"] == "idle"


def test_hanging_exit_cannot_block_next_retry(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "pyplumio",
        SimpleNamespace(open_tcp_connection=lambda *_a, **_k: HangingExitConnection()),
    )
    service = PlumService(config_for_test(), SimpleNamespace())
    service._stop.set()

    with pytest.raises(TransportPhaseTimeout) as captured:
        asyncio.run(service._connection_session())

    assert captured.value.phase == "cleanup"
    assert service.transport_health()["phase"] == "idle"


def test_transport_health_exposes_phase_and_last_failure(monkeypatch):
    calls = 0

    def open_connection(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return HangingEnterConnection()

    monkeypatch.setitem(
        sys.modules,
        "pyplumio",
        SimpleNamespace(open_tcp_connection=open_connection),
    )
    service = PlumService(config_for_test(), SimpleNamespace())

    async def scenario():
        await service.start()
        async with asyncio.timeout(0.5):
            while calls < 2:
                await asyncio.sleep(0.01)
        health = service.transport_health()
        assert health["last_failure_phase"] == "opening_tcp"
        assert health["last_failure_at"] is not None
        assert health["phase"] in {"opening_tcp", "backoff", "idle"}
        assert health["phase_age_seconds"] >= 0
        await service.stop()

    asyncio.run(scenario())
