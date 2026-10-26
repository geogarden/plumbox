"""Mixer settings retain PyPlumIO scaling and device identity."""
from types import SimpleNamespace
import pytest
from pyplumio.const import ProductType
from pyplumio.parameters import ParameterValues
from pyplumio.parameters.mixer import MixerNumber, PARAMETER_TYPES
from app.mappings import meta_for, native_value
from app.serializer import parameter_to_dict

@pytest.mark.parametrize('index', [0, 2])
@pytest.mark.parametrize('name, raw, value, low, high, step, unit', [
    ('heating_curve', 12, 1.2, 0, 4, 0.1, None),
    ('heating_curve_shift', 15, -5, -20, 20, 1, '°C'),
    ('heating_curve_shift', 25, 5, -20, 20, 1, '°C'),
])
def test_curve_payload_and_encoding(index, name, raw, value, low, high, step, unit):
    description = next(d for d in PARAMETER_TYPES[ProductType.ECOMAX_P] if d.name == name)
    parameter = MixerNumber(device=SimpleNamespace(), description=description, values=ParameterValues(raw, 0, 40))
    result = parameter_to_dict(name, parameter, scope='mixer', index=index)
    assert result['value'] == pytest.approx(value)
    assert result['min'] == pytest.approx(low)
    assert result['max'] == pytest.approx(high)
    assert result['step'] == step and result['unit'] == unit
    assert result['section'] == 'mixer'
    assert result['access'] == 'user' and result['writable']
    assert result['scope'] == 'mixer' and result['index'] == index
    command = native_value(name, result['value'], scope='mixer')
    parameter.validate(command)
    assert parameter._pack_value(command) == raw
    with pytest.raises(ValueError):
        parameter.validate(high + step)


def test_mixer_metadata_keeps_boiler_parameters_separate():
    for name in ('heating_curve', 'heating_curve_shift'):
        assert meta_for(name, 'ecomax')['section'] != 'mixer'
