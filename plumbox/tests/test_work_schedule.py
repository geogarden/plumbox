"""Use the actual PyPlumIO 0.6.8 decoder/events/encoder, without a boiler."""
import asyncio
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyplumio.const import FrameType
from pyplumio.devices.ecomax import EcoMAX
from pyplumio.frames import Request
from pyplumio.structures.network_info import NetworkInfo
from pyplumio.structures.schedules import SchedulesStructure
from pyplumio.utils import join_bits, split_byte

from app.work_schedule import WorkSchedule, ScheduleConflict, validate_week


def blank():
    return [[False] * 48 for _ in range(7)]


@asynccontextmanager
async def controller(*, accept=True):
    queue = asyncio.Queue()
    device = EcoMAX(queue, NetworkInfo())
    service = SimpleNamespace(_device=device, _simulator=None, _connection=SimpleNamespace(connected=True),
                              _is_connected=lambda connection: connection.connected,
                              _write_lock=asyncio.Lock(), _safe_add_audit=AsyncMock(return_value=True))
    server = SimpleNamespace(week=blank(), enabled=1, parameter=3, low=0, high=20,
                             reply=True, metadata=True, writes=[])
    manager = WorkSchedule(service)
    manager.READ_TIMEOUT = .06

    async def run():
        while True:
            request = await queue.get()
            if request.frame_type == FrameType.REQUEST_SET_SCHEDULE:
                payload = request.message
                server.writes.append(payload[:])
                if accept:
                    server.enabled = payload[2]
                    bits = [bit for byte in payload[4:] for bit in split_byte(byte)]
                    wire = [bits[i:i + 48] for i in range(0, 336, 48)]
                    server.week = wire[1:] + wire[:1]
            elif request.frame_type == FrameType.REQUEST_SCHEDULES and server.reply:
                wire = [server.week[6], *server.week[:6]]
                metadata = bytes([server.parameter, server.low, server.high]) if server.metadata else b'\xff' * 3
                payload = bytearray([16, 1, 1, 3, server.enabled]) + metadata
                payload += bytearray(join_bits(day[i:i+8]) for day in wire for i in range(0, 48, 8))
                data, _ = SchedulesStructure(request).decode(payload)
                await asyncio.gather(*(device.dispatch(name, value) for name, value in data.items()))

    worker = asyncio.create_task(run())
    try:
        yield manager, server, service
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        await device.shutdown()


def test_all_weekday_and_half_hour_bits_round_trip():
    async def check():
        for day in range(7):
            for slot in range(48):
                week = blank(); week[day][slot] = True
                request = await Request.create(FrameType.REQUEST_SET_SCHEDULE, data={
                    'type': 'boiler_work', 'switch': 1, 'parameter': 3,
                    'schedule': [week[6], *week[:6]],
                })
                payload = request.message
                assert payload[:4] == bytes([1, 3, 1, 3])
                wire_day = (day + 1) % 7
                assert payload[4 + wire_day * 6 + slot // 8] == 1 << (7 - slot % 8)
                assert sum(byte.bit_count() for byte in payload[4:]) == 1
    asyncio.run(check())


def test_real_events_and_write_readback_preserve_metadata_and_other_days():
    async def check():
        async with controller() as (manager, server, service):
            server.week[6][47] = True
            before = await manager.read()
            assert before['available'] and before['enabled']
            assert before['week'][6][47]
            desired = validate_week(before['week']); desired[0][12] = True
            result = await manager.write(desired, False, before['revision'])
            assert result['success'] and result['readback_confirmed']
            assert result['schedule']['week'] == desired
            assert server.writes[0][:4] == bytes([1, 3, 0, 3])
            assert len(server.writes) == 1
            # PyPlumIO's cache changes only via the actual simulated response.
            assert service._device.data['schedules']['boiler_work'].monday.schedule['06:00'] is True
            service._safe_add_audit.assert_awaited_once()
    asyncio.run(check())


def test_external_edit_prevents_write_and_unchanged_plan_sends_nothing():
    async def check():
        async with controller() as (manager, server, _):
            before = await manager.read()
            assert (await manager.write(before['week'], True, before['revision']))['success']
            assert not server.writes
            server.week[2][19] = True
            with pytest.raises(ScheduleConflict):
                await manager.write(before['week'], True, before['revision'])
            assert not server.writes
    asyncio.run(check())


def test_old_cached_data_or_unrelated_frames_never_confirm_a_read():
    async def check():
        async with controller() as (manager, server, service):
            assert (await manager.read())['available']
            server.reply = False
            await service._device.dispatch('heating_temp', 67)
            assert not (await manager.read(force=True))['available']
            assert not server.writes
    asyncio.run(check())


def test_missing_fresh_parameter_cannot_use_its_previous_cached_value():
    async def check():
        async with controller() as (manager, server, _):
            assert (await manager.read())['available']
            server.metadata = False
            assert not (await manager.read(force=True))['available']
            assert not server.writes
    asyncio.run(check())


def test_ignored_write_is_unconfirmed_and_is_never_repeated():
    async def check():
        async with controller(accept=False) as (manager, server, _):
            before = await manager.read()
            desired = blank(); desired[4][0] = True
            result = await manager.write(desired, True, before['revision'])
            assert not result['success'] and result['status'] == 'unconfirmed'
            assert len(server.writes) == 1
    asyncio.run(check())


def test_disconnected_or_invalid_week_cannot_send_a_command():
    async def check():
        async with controller() as (manager, server, service):
            before = await manager.read()
            invalid = blank(); invalid[0][0] = 1
            with pytest.raises(ValueError):
                await manager.write(invalid, True, before['revision'])
            service._connection.connected = False
            with pytest.raises(RuntimeError):
                await manager.write(blank(), True, before['revision'])
            assert not (await manager.read())['available']
            assert not server.writes
    asyncio.run(check())


def test_api_requires_login_pin_admin_and_confirmation(client, monkeypatch):
    from app.deps import state
    week = blank()
    payload = {'week': week, 'enabled': True, 'revision': 'a' * 64, 'confirmed': True}
    writer = AsyncMock(return_value={'success': True})
    monkeypatch.setattr(state.service.work_schedule, 'write', writer)
    assert client.put('/api/work-schedule', json=payload).status_code == 401
    token = client.post('/api/auth/unlock', json={'pin': '1234'}).json()['token']
    headers = {'X-Plumbox-Token': token}
    assert client.put('/api/work-schedule', json={**payload, 'confirmed': False}, headers=headers).status_code == 409
    invalid = blank(); invalid[0][0] = 'on'
    assert client.put('/api/work-schedule', json={**payload, 'week': invalid}, headers=headers).status_code == 422
    assert client.put('/api/work-schedule', json=payload, headers=headers).status_code == 200
    writer.assert_awaited_once()
    from app.users import add_user, delete_user
    add_user('schedule_reader', 'readerpass123', role='readonly')
    try:
        client.post('/login', data={'username': 'schedule_reader', 'password': 'readerpass123'})
        assert client.put('/api/work-schedule', json=payload, headers=headers).status_code == 403
    finally:
        delete_user('schedule_reader')
    writer.assert_awaited_once()


def test_api_work_schedule_read_is_private(anon_client):
    assert anon_client.get('/api/work-schedule').status_code == 401
