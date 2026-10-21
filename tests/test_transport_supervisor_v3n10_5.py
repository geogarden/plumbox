import asyncio
from types import SimpleNamespace

from app.config import AppConfig
from app.plum_service import PlumService


async def wait_until(predicate, timeout=1.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def test_supervisor_restarts_unexpectedly_cancelled_transport_task():
    async def scenario():
        config = AppConfig()
        config.connection.type = "tcp"
        config.connection.reconnect_delay_seconds = 0.01
        service = PlumService(config, SimpleNamespace())
        runs = 0

        async def fake_run():
            nonlocal runs
            runs += 1
            await asyncio.Event().wait()

        service._run = fake_run
        await service.start()
        await wait_until(lambda: service._task is not None)
        first_worker = service._task
        first_worker.cancel()

        await wait_until(lambda: runs >= 2)
        health = service.transport_health()
        assert health["supervisor_alive"] is True
        assert health["task_alive"] is True
        assert health["service_restarts"] == 1
        assert "niespodziewanie anulowane" in health["last_task_exit_reason"]

        await service.stop()

    asyncio.run(scenario())


def test_normal_stop_does_not_count_as_transport_restart():
    async def scenario():
        config = AppConfig()
        config.connection.type = "tcp"
        service = PlumService(config, SimpleNamespace())

        async def fake_run():
            await asyncio.Event().wait()

        service._run = fake_run
        await service.start()
        await wait_until(lambda: service._task is not None)
        await service.stop()

        health = service.transport_health()
        assert health["supervisor_alive"] is False
        assert health["task_alive"] is False
        assert health["service_restarts"] == 0
        assert health["last_task_exit_reason"] is None

    asyncio.run(scenario())


def test_repeated_start_keeps_single_supervisor_and_worker():
    async def scenario():
        config = AppConfig()
        config.connection.type = "tcp"
        service = PlumService(config, SimpleNamespace())
        runs = 0

        async def fake_run():
            nonlocal runs
            runs += 1
            await asyncio.Event().wait()

        service._run = fake_run
        await service.start()
        await wait_until(lambda: service._task is not None)
        supervisor = service._supervisor_task
        worker = service._task
        await service.start()

        assert service._supervisor_task is supervisor
        assert service._task is worker
        assert runs == 1
        await service.stop()

    asyncio.run(scenario())
