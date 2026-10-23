"""Strażnik antyhalucynacyjny: mapowania PlumBox vs realne API pyplumio.

Pilnuje, żeby ręcznie wpisane nazwy parametrów, kody alarmów i stany zgadzały
się z zainstalowaną wersją pyplumio. Test pomijany, gdy pyplumio nie jest
zainstalowane (np. szybki przebieg tylko z fastapi).
"""

from __future__ import annotations

import inspect
import re

import pytest

pyplumio = pytest.importorskip("pyplumio")


def _descriptor_names(module) -> set[str]:
    return set(re.findall(r'name="([a-z0-9_]+)"', inspect.getsource(module)))


def test_parameter_meta_names_exist_in_pyplumio():
    import pyplumio.parameters.ecomax as pe
    import pyplumio.parameters.mixer as pm
    from pyplumio.structures.ecomax_parameters import ATTR_ECOMAX_CONTROL

    from app.mappings import PARAMETER_META

    eco = _descriptor_names(pe) | {ATTR_ECOMAX_CONTROL}
    mix = _descriptor_names(pm)

    for key, meta in PARAMETER_META.items():
        name = key.split(":")[0]
        if key.endswith(":mixer") or meta.get("section") == "mixer":
            assert name in mix, f"'{name}' nie istnieje w parametrach mieszacza pyplumio"
        else:
            assert name in eco, f"'{name}' nie istnieje w parametrach ecoMAX pyplumio"


def test_alert_labels_match_alert_type_codes():
    from pyplumio.structures.alerts import AlertType

    from app.mappings import ALERT_LABELS

    real = {int(m.value) for m in AlertType}
    unknown = set(ALERT_LABELS) - real
    assert not unknown, f"Kody alarmów spoza pyplumio AlertType: {unknown}"

    # Etykiety, których wcześniejsze wersje przekłamywały diagnozę.
    assert "modułem B" in ALERT_LABELS[44]
    assert "sterowania podajnikiem" in ALERT_LABELS[52]
    # 22 (FEEDER_JAMMED) i 52 (FEEDER_CONTROL_FAILURE) muszą się różnić.
    assert ALERT_LABELS[22] != ALERT_LABELS[52]


def test_state_labels_cover_device_state_enum():
    from pyplumio.const import DeviceState

    from app.mappings import STATE_LABELS

    for member in DeviceState:
        assert int(member.value) in STATE_LABELS, f"Brak etykiety stanu {member.name}"
    # Nie przypisujemy znaczenia surowym kodom, których nie ma w enumie biblioteki.
    assert 12 not in STATE_LABELS and 23 not in STATE_LABELS


def test_known_profile_names_exist_in_pyplumio():
    import pyplumio.parameters.ecomax as pe
    from pyplumio.structures.ecomax_parameters import ATTR_ECOMAX_CONTROL

    from app.controller_profile import KNOWN_ECOMAX_860P4_PARAMETERS

    eco = _descriptor_names(pe) | {ATTR_ECOMAX_CONTROL}
    for name in KNOWN_ECOMAX_860P4_PARAMETERS:
        assert name in eco, f"'{name}' nie istnieje w parametrach ecoMAX pyplumio"
