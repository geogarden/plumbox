"""Season mode codes follow the upstream Plum ecoMAX integration's select:
https://github.com/denpamusic/homeassistant-plum-ecomax/blob/main/custom_components/plum_ecomax/select.py
"""
from types import SimpleNamespace

import pytest
from pyplumio.parameters import ParameterValues
from pyplumio.parameters.ecomax import EcomaxNumber, EcomaxNumberDescription

from app.mappings import native_value
from app.serializer import parameter_to_dict


@pytest.mark.parametrize(('code', 'label'), [(0, 'Zima'), (1, 'Lato'), (2, 'Auto')])
def test_season_mode_roundtrip_retains_native_code_and_selected_label(code, label):
    parameter = EcomaxNumber(
        device=SimpleNamespace(), description=EcomaxNumberDescription(name='summer_mode'),
        values=ParameterValues(code, 0, 2),
    )
    result = parameter_to_dict('summer_mode', parameter)
    assert result['kind'] == 'select'
    assert result['options'] == {'0': 'Zima', '1': 'Lato', '2': 'Auto'}
    assert result['selected_label'] == label
    assert result['native_value'] == code
    command = native_value('summer_mode', result['native_value'])
    assert not isinstance(command, bool) and command == code
    assert native_value('summer_mode', code) == code
    parameter.validate(command)


def test_auto_still_respects_a_controller_without_support_for_code_two():
    parameter = EcomaxNumber(
        device=SimpleNamespace(), description=EcomaxNumberDescription(name='summer_mode'),
        values=ParameterValues(0, 0, 1),
    )
    with pytest.raises(ValueError):
        parameter.validate(native_value('summer_mode', 2))
