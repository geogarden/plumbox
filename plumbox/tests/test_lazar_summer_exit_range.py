"""SF 11/130 correction must reach the shared native write path, not just HTML."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyplumio.devices.ecomax import EcoMAX
from pyplumio.parameters import ParameterValues
from pyplumio.parameters.ecomax import EcomaxNumber, EcomaxNumberDescription
from pyplumio.structures.network_info import NetworkInfo

from app.config import AppConfig
from app.plum_service import PlumService

NAME = 'summer_mode_disable_temp'


async def service(product_id=2, name=NAME):
    queue = asyncio.Queue()
    device = EcoMAX(queue, NetworkInfo())
    parameter = EcomaxNumber(
        device=device, description=EcomaxNumberDescription(name=name),
        values=ParameterValues(5, 1, 10), index=27,
    )
    await device.load({name: parameter, 'product': {'id': product_id}})
    connection = SimpleNamespace(connected=True, statistics=SimpleNamespace(received_frames=1))
    config = AppConfig(); config.connection.type = 'tcp'
    result = PlumService(config, SimpleNamespace(add_audit=AsyncMock()))
    result._device, result._connection = device, connection
    result.snapshot = result._build_snapshot(connection, device)
    return result, parameter, queue


def test_range_in_snapshot_does_not_fabricate_a_new_parameter_reading():
    async def check():
        instance, parameter, _ = await service()
        payload = instance.snapshot['parameters'][NAME]
        assert (payload['min'], payload['max'], payload['value']) == (1, 15, 5)
        assert parameter.values == ParameterValues(5, 1, 10)
        await instance._device.shutdown()
    asyncio.run(check())


@pytest.mark.parametrize('requested', [11, 15])
def test_shared_writer_accepts_extended_range_with_original_index_and_readback(requested):
    async def check():
        instance, parameter, queue = await service()
        task = asyncio.create_task(instance.set_parameter('ecomax', 0, NAME, requested))
        frame = await asyncio.wait_for(queue.get(), timeout=.5)
        assert frame.data == {'index': 27, 'value': requested}
        assert not task.done()  # Metadata adjustment alone cannot confirm a write.
        parameter.update(ParameterValues(requested, 1, 10))
        instance._connection.statistics.received_frames += 1
        result = await asyncio.wait_for(task, timeout=.5)
        assert result['success'] and result['readback_confirmed']
        assert queue.empty()
        await instance._device.shutdown()
    asyncio.run(check())


@pytest.mark.parametrize('requested', [0, 16, 1.5])
def test_values_outside_approved_range_or_step_are_rejected_before_send(requested):
    async def check():
        instance, _, queue = await service()
        with pytest.raises(ValueError):
            await instance.set_parameter('ecomax', 0, NAME, requested)
        assert queue.empty()
        await instance._device.shutdown()
    asyncio.run(check())


@pytest.mark.parametrize(('product_id', 'name'), [(211, NAME), (7, NAME), (None, NAME), (2, 'summer_mode_enable_temp')])
def test_other_models_and_parameters_keep_their_controller_limits(product_id, name):
    async def check():
        instance, parameter, queue = await service(product_id, name)
        assert instance.snapshot['parameters'][name]['max'] == 10
        with pytest.raises(ValueError):
            await instance.set_parameter('ecomax', 0, name, 15)
        assert parameter.max_value == 10 and queue.empty()
        await instance._device.shutdown()
    asyncio.run(check())
