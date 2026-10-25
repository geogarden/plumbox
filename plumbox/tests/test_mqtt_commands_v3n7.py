from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.config import MqttConfig
from app.mappings import PARAMETER_META
from app.mqtt import MqttPublisher


class PublishInfo:
    rc = 0


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def publish(self, topic, payload, **kwargs):
        self.calls.append((topic, payload, kwargs))
        return PublishInfo()


def parameter(
    name: str,
    value,
    *,
    kind: str = "number",
    risk: str = "safe",
    minimum=0,
    maximum=100,
    step=1,
    options=None,
    writable: bool = True,
):
    options = options or {}
    key = str(value)
    return {
        "name": name,
        "scope": "ecomax",
        "index": 0,
        "label": name,
        "risk": risk,
        "kind": kind,
        "value": value,
        "native_value": value,
        "min": minimum,
        "max": maximum,
        "step": step,
        "unit": "°C" if kind == "number" else None,
        "options": options,
        "selected_label": options.get(key),
        "writable": writable,
        "special_zero": False,
    }


def snapshot():
    parameters = {
        "heating_target_temp": parameter("heating_target_temp", 75, minimum=60, maximum=85),
        "water_heater_work_mode": parameter(
            "water_heater_work_mode",
            2,
            kind="select",
            minimum=0,
            maximum=2,
            options={"0": "Wyłączony", "1": "Z priorytetem", "2": "Bez priorytetu"},
        ),
        "water_heater_disinfection": parameter(
            "water_heater_disinfection",
            False,
            kind="switch",
            risk="advanced",
            minimum=False,
            maximum=True,
        ),
        "boiler_alert_temp": parameter(
            "boiler_alert_temp",
            85,
            risk="critical",
            minimum=85,
            maximum=95,
        ),
        "ecomax_control": parameter(
            "ecomax_control",
            True,
            kind="switch",
            minimum=False,
            maximum=True,
        ),
    }
    entities = [
        {
            "path": f"parameter/{name}",
            "key": name,
            "label": item["label"],
            "unit": item["unit"],
            "domain": (
                "binary_sensor"
                if isinstance(item["native_value"], bool)
                else "sensor"
            ),
            "writable": item["writable"],
            "available": True,
        }
        for name, item in parameters.items()
    ]
    return {
        "connected": True,
        "values": {},
        "parameters": parameters,
        "mixers": {},
        "profile": {"name": "test", "entities": entities},
    }


def publisher(config: MqttConfig, *, parameter_writer=None, power_writer=None):
    instance = MqttPublisher(
        config,
        parameter_writer=parameter_writer,
        power_writer=power_writer,
    )
    instance._client = FakeClient()
    instance._mqtt = SimpleNamespace(MQTT_ERR_SUCCESS=0)
    instance._connected = True
    instance._last_snapshot = snapshot()
    return instance


def discovery_payloads(instance: MqttPublisher):
    instance._publish_discovery(instance._last_snapshot, instance._entities_for_snapshot(instance._last_snapshot))
    return {
        topic: json.loads(payload)
        for topic, payload, _kwargs in instance._client.calls
        if payload
    }


def test_state_publish_uses_delta_and_ignores_timestamp_only_changes():
    instance = publisher(MqttConfig(enabled=True, home_assistant_discovery=False))
    first = snapshot()
    first["timestamp"] = "2026-08-01T12:00:00+00:00"
    asyncio.run(instance.publish(first))
    first_count = len(instance._client.calls)
    assert first_count > 0

    second = snapshot()
    second["timestamp"] = "2026-08-01T12:00:01+00:00"
    asyncio.run(instance.publish(second))

    assert len(instance._client.calls) == first_count


def test_state_publish_sends_changed_entity_immediately():
    instance = publisher(MqttConfig(enabled=True, home_assistant_discovery=False))
    first = snapshot()
    asyncio.run(instance.publish(first))
    instance._client.calls.clear()

    changed = snapshot()
    changed["parameters"]["heating_target_temp"]["value"] = 76
    changed["parameters"]["heating_target_temp"]["native_value"] = 76
    asyncio.run(instance.publish(changed))

    topics = {topic for topic, _payload, _kwargs in instance._client.calls}
    assert "plumbox/entity/parameter/heating_target_temp" in topics


def test_state_publish_sends_full_heartbeat_after_sixty_seconds():
    instance = publisher(MqttConfig(enabled=True, home_assistant_discovery=False))
    current = snapshot()
    asyncio.run(instance.publish(current))
    expected_topics = set(instance._state_topics)
    instance._client.calls.clear()
    instance._last_full_publish_monotonic -= 60.0

    asyncio.run(instance.publish(current))

    assert {topic for topic, _payload, _kwargs in instance._client.calls} == expected_topics


def test_discovery_exposes_number_select_switch_and_keeps_dangerous_controls_read_only():
    instance = publisher(
        MqttConfig(
            enabled=True,
            commands_enabled=True,
            allow_advanced_commands=True,
            allow_critical_commands=False,
            allow_power_commands=False,
        )
    )
    configs = discovery_payloads(instance)

    number = configs["homeassistant/number/plumbox/parameter_heating_target_temp/config"]
    assert number["command_topic"] == "plumbox/command/parameter/heating_target_temp"
    assert number["min"] == 60 and number["max"] == 85 and number["step"] == 1
    assert number["optimistic"] is False

    select = configs["homeassistant/select/plumbox/parameter_water_heater_work_mode/config"]
    assert select["options"] == ["Wyłączony", "Z priorytetem", "Bez priorytetu"]

    switch = configs["homeassistant/switch/plumbox/parameter_water_heater_disinfection/config"]
    assert switch["payload_on"] == "ON" and switch["payload_off"] == "OFF"

    assert "homeassistant/sensor/plumbox/parameter_boiler_alert_temp/config" in configs
    assert "homeassistant/binary_sensor/plumbox/parameter_ecomax_control/config" in configs
    assert all(
        "command_topic" not in configs[topic]
        for topic in (
            "homeassistant/sensor/plumbox/parameter_boiler_alert_temp/config",
            "homeassistant/binary_sensor/plumbox/parameter_ecomax_control/config",
        )
    )


def test_discovery_cleans_old_sensor_topic_after_domain_change():
    instance = publisher(MqttConfig(enabled=True, commands_enabled=True))
    discovery_payloads(instance)
    assert (
        "homeassistant/sensor/plumbox/parameter_heating_target_temp/config",
        "",
        {"qos": 0, "retain": True},
    ) in instance._client.calls


def test_mqtt_control_defaults_match_local_econet_use_case():
    config = MqttConfig()
    assert config.commands_enabled is True
    assert config.allow_advanced_commands is True
    assert config.allow_critical_commands is False
    assert config.allow_power_commands is True


def test_control_states_use_home_assistant_payloads_and_visible_values():
    instance = publisher(MqttConfig(enabled=True, commands_enabled=True))
    entities = {
        item["path"]: item
        for item in instance._entities_for_snapshot(instance._last_snapshot)
    }
    assert instance._state_value_for_entity(
        instance._last_snapshot,
        entities["parameter/ecomax_control"],
    ) == "ON"
    assert instance._state_value_for_entity(
        instance._last_snapshot,
        entities["parameter/water_heater_work_mode"],
    ) == "Bez priorytetu"
    assert instance._state_value_for_entity(
        instance._last_snapshot,
        entities["parameter/heating_target_temp"],
    ) == 75


def test_advanced_parameter_stays_sensor_when_advanced_commands_are_disabled():
    instance = publisher(
        MqttConfig(
            enabled=True,
            commands_enabled=True,
            allow_advanced_commands=False,
        )
    )
    configs = discovery_payloads(instance)
    topic = (
        "homeassistant/binary_sensor/plumbox/"
        "parameter_water_heater_disinfection/config"
    )
    assert topic in configs
    assert "command_topic" not in configs[topic]


def test_fixed_profile_does_not_hide_live_parameters_from_mqtt():
    instance = publisher(MqttConfig(enabled=True, commands_enabled=True))
    live = parameter(
        "kindling_airflow_power",
        1450,
        risk="advanced",
        minimum=1000,
        maximum=2500,
        step=10,
    )
    instance._last_snapshot["parameters"]["kindling_airflow_power"] = live
    # Symulacja profilu FIXED, który nie wymienia tej pozycji.
    assert all(
        item["path"] != "parameter/kindling_airflow_power"
        for item in instance._last_snapshot["profile"]["entities"]
    )

    configs = discovery_payloads(instance)
    control = configs[
        "homeassistant/number/plumbox/parameter_kindling_airflow_power/config"
    ]
    assert control["command_topic"] == (
        "plumbox/command/parameter/kindling_airflow_power"
    )
    assert control["min"] == 1000


def test_number_command_uses_shared_writer_and_publishes_result():
    writes = []

    async def write(scope, index, name, value):
        writes.append((scope, index, name, value))
        return {
            "success": True,
            "status": "confirmed",
            "message": "Zapis potwierdzony odczytem zwrotnym.",
            "readback_confirmed": True,
        }

    async def power(_enabled):
        raise AssertionError("power writer must not be used")

    instance = publisher(
        MqttConfig(enabled=True, commands_enabled=True),
        parameter_writer=write,
        power_writer=power,
    )
    asyncio.run(
        instance._handle_command(
            "plumbox/command/parameter/heating_target_temp",
            "76",
        )
    )

    assert writes == [("ecomax", 0, "heating_target_temp", 76)]
    results = [
        json.loads(payload)
        for topic, payload, _kwargs in instance._client.calls
        if topic == "plumbox/result/parameter/heating_target_temp"
    ]
    assert len(results) == 1
    assert results[0]["success"] is True
    assert results[0]["write"]["readback_confirmed"] is True


def test_select_command_converts_label_to_native_value():
    writes = []

    async def write(scope, index, name, value):
        writes.append((scope, index, name, value))
        return {"success": True, "message": "OK"}

    async def power(_enabled):
        return {"success": True, "message": "OK"}

    instance = publisher(
        MqttConfig(enabled=True, commands_enabled=True),
        parameter_writer=write,
        power_writer=power,
    )
    asyncio.run(
        instance._handle_command(
            "plumbox/command/parameter/water_heater_work_mode",
            "Z priorytetem",
        )
    )
    assert writes == [("ecomax", 0, "water_heater_work_mode", 1)]


def test_retained_command_is_rejected_without_calling_writer():
    writes = []

    async def write(*args):
        writes.append(args)
        return {"success": True}

    async def power(enabled):
        writes.append(("power", enabled))
        return {"success": True}

    instance = publisher(
        MqttConfig(enabled=True, commands_enabled=True),
        parameter_writer=write,
        power_writer=power,
    )
    asyncio.run(
        instance._handle_command(
            "plumbox/command/parameter/heating_target_temp",
            "77",
            retained=True,
        )
    )
    assert writes == []
    result = json.loads(instance._client.calls[-1][1])
    assert result["success"] is False
    assert "retain" in result["message"]


def test_power_command_requires_separate_permission():
    power_calls = []

    async def write(*_args):
        raise AssertionError("parameter writer must not be used")

    async def power(enabled):
        power_calls.append(enabled)
        return {"success": True, "message": "Polecenie wysłane."}

    denied = publisher(
        MqttConfig(enabled=True, commands_enabled=True, allow_power_commands=False),
        parameter_writer=write,
        power_writer=power,
    )
    asyncio.run(
        denied._handle_command(
            "plumbox/command/parameter/ecomax_control",
            "OFF",
        )
    )
    assert power_calls == []

    allowed = publisher(
        MqttConfig(enabled=True, commands_enabled=True, allow_power_commands=True),
        parameter_writer=write,
        power_writer=power,
    )
    asyncio.run(
        allowed._handle_command(
            "plumbox/command/parameter/ecomax_control",
            "OFF",
        )
    )
    assert power_calls == [False]


def test_invalid_number_range_is_rejected_before_writer():
    writes = []

    async def write(*args):
        writes.append(args)
        return {"success": True}

    async def power(_enabled):
        return {"success": True}

    instance = publisher(
        MqttConfig(enabled=True, commands_enabled=True),
        parameter_writer=write,
        power_writer=power,
    )
    asyncio.run(
        instance._handle_command(
            "plumbox/command/parameter/heating_target_temp",
            "99",
        )
    )
    assert writes == []
    result = json.loads(instance._client.calls[-1][1])
    assert result["success"] is False
    assert "maksimum" in result["message"]


def test_mqtt_catalog_covers_every_live_ecomax_and_mixer_parameter():
    """MQTT must not silently inherit the narrower FIXED dashboard catalog."""
    instance = publisher(
        MqttConfig(
            enabled=True,
            commands_enabled=True,
            allow_advanced_commands=True,
            allow_critical_commands=False,
        )
    )
    service_parameters = {
        "kindling_airflow_power": parameter(
            "kindling_airflow_power",
            1450,
            risk="advanced",
            minimum=1000,
            maximum=2500,
            step=10,
        ),
        "cleaning_airflow_power": parameter(
            "cleaning_airflow_power",
            2100,
            risk="advanced",
            minimum=1000,
            maximum=2800,
            step=10,
        ),
        "max_feeder_temp": parameter(
            "max_feeder_temp",
            58,
            risk="critical",
            minimum=40,
            maximum=85,
        ),
        # A parameter unknown to the fixed dashboard must still be exported.
        "product_211_future_service_option": parameter(
            "product_211_future_service_option",
            4,
            risk="advanced",
            minimum=0,
            maximum=10,
        ),
    }
    instance._last_snapshot["parameters"].update(service_parameters)
    mixer_parameter = parameter(
        "mixer_hysteresis",
        2,
        risk="advanced",
        minimum=0,
        maximum=10,
    )
    mixer_parameter.update({"scope": "mixer", "index": 1})
    instance._last_snapshot["mixers"] = {
        "1": {
            "values": {"current_temp": 42},
            "parameters": {"mixer_hysteresis": mixer_parameter},
        }
    }

    paths = {
        str(item["path"])
        for item in instance._entities_for_snapshot(instance._last_snapshot)
    }
    expected = {
        *(f"parameter/{name}" for name in instance._last_snapshot["parameters"]),
        "mixer/1/value/current_temp",
        "mixer/1/parameter/mixer_hysteresis",
    }
    assert expected <= paths

    configs = discovery_payloads(instance)
    for name, item in service_parameters.items():
        if item["risk"] == "advanced":
            topic = f"homeassistant/number/plumbox/parameter_{name}/config"
            assert configs[topic]["command_topic"] == f"plumbox/command/parameter/{name}"
    mixer_topic = "homeassistant/number/plumbox/mixer_1_parameter_mixer_hysteresis/config"
    assert configs[mixer_topic]["command_topic"] == (
        "plumbox/command/mixer/1/parameter/mixer_hysteresis"
    )

    # Critical service settings are visible, but read-only unless explicitly enabled.
    critical_topic = "homeassistant/sensor/plumbox/parameter_max_feeder_temp/config"
    assert critical_topic in configs
    assert "command_topic" not in configs[critical_topic]


def test_critical_service_control_requires_explicit_opt_in():
    instance = publisher(
        MqttConfig(
            enabled=True,
            commands_enabled=True,
            allow_advanced_commands=True,
            allow_critical_commands=True,
        )
    )
    instance._last_snapshot["parameters"]["max_feeder_temp"] = parameter(
        "max_feeder_temp",
        58,
        risk="critical",
        minimum=40,
        maximum=85,
    )
    configs = discovery_payloads(instance)
    topic = "homeassistant/number/plumbox/parameter_max_feeder_temp/config"
    assert configs[topic]["command_topic"] == (
        "plumbox/command/parameter/max_feeder_temp"
    )


def test_mixer_service_command_uses_mixer_scope_and_index():
    writes = []

    async def write(scope, index, name, value):
        writes.append((scope, index, name, value))
        return {"success": True, "message": "OK"}

    instance = publisher(
        MqttConfig(
            enabled=True,
            commands_enabled=True,
            allow_advanced_commands=True,
        ),
        parameter_writer=write,
    )
    item = parameter(
        "mixer_hysteresis",
        2,
        risk="advanced",
        minimum=0,
        maximum=10,
    )
    item.update({"scope": "mixer", "index": 1})
    instance._last_snapshot["mixers"] = {
        "1": {"values": {}, "parameters": {"mixer_hysteresis": item}}
    }

    asyncio.run(
        instance._handle_command(
            "plumbox/command/mixer/1/parameter/mixer_hysteresis",
            "3",
        )
    )
    assert writes == [("mixer", 1, "mixer_hysteresis", 3)]


def test_every_mapped_plumbox_setting_is_exported_and_follows_risk_policy():
    """Inventory guard: adding a PlumBox mapping must not leave MQTT behind."""
    instance = publisher(
        MqttConfig(
            enabled=True,
            commands_enabled=True,
            allow_advanced_commands=True,
            allow_critical_commands=False,
        )
    )
    expected_paths = set()
    for mapped_name, meta in PARAMETER_META.items():
        if mapped_name.endswith(":mixer"):
            continue
        item = parameter(
            mapped_name,
            1,
            kind=str(meta.get("kind") or "number"),
            risk=str(meta.get("risk") or "advanced"),
            minimum=0,
            maximum=100,
        )
        instance._last_snapshot["parameters"][mapped_name] = item
        expected_paths.add(f"parameter/{mapped_name}")

    mixer_parameters = {}
    for mapped_name, meta in PARAMETER_META.items():
        if not mapped_name.endswith(":mixer"):
            continue
        name = mapped_name.removesuffix(":mixer")
        item = parameter(
            name,
            1,
            kind=str(meta.get("kind") or "number"),
            risk=str(meta.get("risk") or "advanced"),
            minimum=0,
            maximum=100,
        )
        item.update({"scope": "mixer", "index": 1})
        mixer_parameters[name] = item
        expected_paths.add(f"mixer/1/parameter/{name}")
    instance._last_snapshot["mixers"] = {
        "1": {"values": {}, "parameters": mixer_parameters}
    }

    entities = {
        str(item["path"]): item
        for item in instance._entities_for_snapshot(instance._last_snapshot)
    }
    assert expected_paths <= entities.keys()
    for path in expected_paths:
        item = instance._parameter_by_entity_path(instance._last_snapshot, path)
        assert item is not None
        expected_write = item["risk"] in {"safe", "advanced"}
        if path.endswith("/ecomax_control"):
            expected_write = instance.config.allow_power_commands
        assert instance._command_allowed(path, item) is expected_write



def test_temperature_payloads_are_rounded_in_all_mqtt_channels_without_mutating_snapshot():
    instance = publisher(MqttConfig(enabled=True, home_assistant_discovery=False))
    original = snapshot()
    original['values'] = {'exhaust_temp': 128.126, 'outside_temp': -2.874, 'heating_temp': 67.1234}
    asyncio.run(instance.publish(original))
    topics = {topic: payload for topic, payload, _ in instance._client.calls}
    for key, expected in [('exhaust_temp', '128.1'), ('outside_temp', '-2.9')]:
        assert topics[f'plumbox/value/{key}'] == expected
        assert topics[f'plumbox/raw/values/{key}'] == expected
        assert topics[f'plumbox/entity/value/{key}'] == expected
        assert json.loads(topics['plumbox/state'])['values'][key] == float(expected)
    assert topics['plumbox/entity/value/heating_temp'] == '67.1234'
    assert original['values'] == {'exhaust_temp': 128.126, 'outside_temp': -2.874, 'heating_temp': 67.1234}


def test_mqtt_temperature_name_precision_and_identity_survive_existing_profile_labels():
    instance = publisher(MqttConfig(enabled=True))
    instance._last_snapshot['values'] = {'exhaust_temp': 128.126, 'outside_temp': -2.874}
    instance._last_snapshot['profile']['entities'] += [
        {'path': 'value/exhaust_temp', 'label': 'Exhaust temp', 'domain': 'sensor'},
        {'path': 'value/outside_temp', 'label': 'Outside temperature', 'domain': 'sensor'},
    ]
    configs = discovery_payloads(instance)
    for key in ('exhaust_temp', 'outside_temp'):
        config = configs[f'homeassistant/sensor/plumbox/value_{key}/config']
        assert config['unique_id'] == f'plumbox_value_{key}'
        assert config['state_topic'] == f'plumbox/entity/value/{key}'
        assert config['unit_of_measurement'] == '°C'
        assert config['device_class'] == 'temperature'
        assert config['suggested_display_precision'] == 1
    assert configs['homeassistant/sensor/plumbox/value_exhaust_temp/config']['name'] == 'PlumBox Temperatura spalin'
    assert configs['homeassistant/sensor/plumbox/value_outside_temp/config']['name'] == 'PlumBox Outside temperature'
    assert instance._last_snapshot['profile']['entities'][-2]['label'] == 'Exhaust temp'


def test_mqtt_temperature_zero_missing_and_whole_degrees():
    instance = publisher(MqttConfig(enabled=True, home_assistant_discovery=False))
    current = snapshot()
    current['values'] = {'exhaust_temp': 128, 'outside_temp': 0}
    asyncio.run(instance.publish(current))
    topics = {topic: payload for topic, payload, _ in instance._client.calls}
    assert topics['plumbox/entity/value/exhaust_temp'] == '128.0'
    assert topics['plumbox/entity/value/outside_temp'] == '0.0'
    current['values']['exhaust_temp'] = None
    asyncio.run(instance.publish(current))
    topics = {topic: payload for topic, payload, _ in instance._client.calls}
    assert topics['plumbox/entity/value/exhaust_temp'] == ''
