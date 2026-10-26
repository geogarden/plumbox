from types import SimpleNamespace

import pytest
from pyplumio.const import ProductType
from pyplumio.parameters import ParameterValues
from pyplumio.parameters.ecomax import PARAMETER_TYPES as ECOMAX_TYPES, EcomaxNumber, EcomaxSwitch
from pyplumio.parameters.mixer import PARAMETER_TYPES as MIXER_TYPES, MixerNumber, MixerSwitch

from app.mappings import meta_for, native_value
from app.serializer import parameter_to_dict

MIXER_NAMES = ['weather_control', 'weather_factor', 'thermostat_operation', 'summer_work']
LAMBDA_NAMES = ['lambda_control', 'lambda_correction_range', 'oxygen_100', 'oxygen_50', 'oxygen_30', 'fuzzy_logic_oxygen_correction']


@pytest.mark.parametrize('index', [0, 2])
@pytest.mark.parametrize('name', MIXER_NAMES)
def test_mixer_weather_controls_keep_real_type_and_mixer_index(name, index):
    description = next(d for d in MIXER_TYPES[ProductType.ECOMAX_P] if d.name == name)
    switch = 'Switch' in type(description).__name__
    cls = MixerSwitch if switch else MixerNumber
    parameter = cls(device=SimpleNamespace(), description=description, values=ParameterValues(1, 0, 1 if switch else 100))
    result = parameter_to_dict(name, parameter, scope='mixer', index=index)
    assert result['section'] == 'mixer'
    assert result['scope'] == 'mixer' and result['index'] == index
    assert result['access'] == 'user' and result['writable']
    assert result['kind'] == ('switch' if switch else 'number')
    command = native_value(name, True if switch else result['value'], scope='mixer')
    parameter.validate(command)
    assert parameter._pack_value(command) == 1
    assert meta_for(name, 'ecomax')['section'] != 'mixer'


@pytest.mark.parametrize('name', LAMBDA_NAMES)
def test_lambda_controls_are_in_heating_and_preserve_service_policy_and_scaling(name):
    description = next(d for d in ECOMAX_TYPES[ProductType.ECOMAX_P] if d.name == name)
    switch = 'Switch' in type(description).__name__
    cls = EcomaxSwitch if switch else EcomaxNumber
    parameter = cls(device=SimpleNamespace(), description=description, values=ParameterValues(1, 0, 1 if switch else 100))
    result = parameter_to_dict(name, parameter)
    assert result['section'] == 'heating'
    assert result['risk'] == 'advanced' and not result['writable']
    assert result['kind'] == ('switch' if switch else 'number')
    command = native_value(name, True if switch else result['value'])
    parameter.validate(command)
    assert parameter._pack_value(command) == 1
    # No undocumented percentage unit or scaling is introduced.
    assert result['unit'] is None
