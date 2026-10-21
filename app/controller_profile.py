"""Wykrywanie dostępnych odczytów i tworzenie profilu sterownika.

Moduł nie zapisuje żadnych parametrów do sterownika. Pracuje wyłącznie na
ostatnim snapshotcie odczytanym przez PlumBox/PyPlumIO.
"""

from __future__ import annotations

from typing import Any

from .common import is_scalar, utc_now_iso
from .mappings import PARAMETER_META, SENSOR_META


KNOWN_ECOMAX_860P4_VALUES = [
    "state", "state_label", "heating_temp", "return_temp", "water_heater_temp",
    "feeder_temp", "optical_temp", "heating_target", "water_heater_target",
    "boiler_power", "boiler_load", "fan_power", "fuel_level", "fuel_consumption",
    "fuel_burned", "modules", "product", "frame_errors",
]

KNOWN_ECOMAX_860P4_PARAMETERS = [
    "ecomax_control", "heating_target_temp", "water_heater_target_temp",
    "water_heater_hysteresis", "summer_mode", "summer_mode_enable_temp",
    "summer_mode_disable_temp", "heating_hysteresis", "boiler_power_100",
    "boiler_power_50", "boiler_power_30", "airflow_power_100", "airflow_power_50",
    "airflow_power_30", "fuel_calorific_value", "max_fuel_flow",
    "feeder_calibration",
]


def _safe_path(path: str) -> str:
    return "/".join(part.strip().replace(" ", "_").replace(".", "_") for part in path.split("/") if part.strip())


def _label_from_key(key: str, scope: str = "value") -> str:
    if scope == "value" and key in SENSOR_META:
        return str(SENSOR_META[key].get("label") or key)
    if scope in {"parameter", "mixer_parameter"}:
        meta = PARAMETER_META.get(f"{key}:mixer") or PARAMETER_META.get(key)
        if meta:
            return str(meta.get("label") or key)
    return key.replace("_", " ").replace("/", " / ").strip().capitalize()


def _unit_from_key(key: str, value: Any = None, scope: str = "value") -> str | None:
    """Zwraca wyłącznie jednostkę z potwierdzonego katalogu odczytów.

    Jednostki parametrów są przekazywane do ``_entity`` bezpośrednio ze
    snapshotu PyPlumIO. Nieznanych pól auto-detect nie opisujemy na podstawie
    samej nazwy klucza.
    """
    if scope == "value" and key in SENSOR_META:
        return SENSOR_META[key].get("unit")
    return None


def _device_class_from_unit(unit: str | None, key: str) -> str | None:
    if unit == "°C":
        return "temperature"
    if unit in {"kW", "W"}:
        return "power"
    return None


def _entity(
    path: str,
    key: str,
    value: Any,
    scope: str,
    writable: bool = False,
    available: bool = True,
    unit: str | None = None,
) -> dict[str, Any]:
    resolved_unit = str(unit) if unit not in {None, ""} else _unit_from_key(key, value, scope)
    out = {
        "path": _safe_path(path),
        "key": key,
        "label": _label_from_key(key, scope),
        "unit": resolved_unit,
        "type": type(value).__name__ if value is not None else "null",
        "domain": "binary_sensor" if isinstance(value, bool) else "sensor",
        "writable": bool(writable),
        "available": bool(available),
    }
    device_class = _device_class_from_unit(resolved_unit, key)
    if device_class:
        out["device_class"] = device_class
    return out


def _parameter_native(parameter: dict[str, Any]) -> Any:
    if "native_value" in parameter:
        return parameter.get("native_value")
    return parameter.get("value")


def detected_entities(snapshot: dict[str, Any], *, include_parameters: bool = True, include_mixers: bool = True, include_statistics: bool = False) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    values = snapshot.get("values", {}) if isinstance(snapshot.get("values"), dict) else {}
    for key, value in values.items():
        if is_scalar(value):
            entities.append(_entity(f"value/{key}", key, value, "value"))

    if include_parameters:
        params = snapshot.get("parameters", {}) if isinstance(snapshot.get("parameters"), dict) else {}
        for key, parameter in params.items():
            if isinstance(parameter, dict):
                entities.append(_entity(
                    f"parameter/{key}", key, _parameter_native(parameter), "parameter",
                    writable=bool(parameter.get("writable")), unit=parameter.get("unit"),
                ))

    if include_mixers:
        mixers = snapshot.get("mixers", {}) if isinstance(snapshot.get("mixers"), dict) else {}
        for mixer_index, mixer in mixers.items():
            if not isinstance(mixer, dict):
                continue
            for key, value in (mixer.get("values") or {}).items():
                if is_scalar(value):
                    entities.append(_entity(f"mixer/{mixer_index}/value/{key}", key, value, "mixer_value"))
            for key, parameter in (mixer.get("parameters") or {}).items():
                if isinstance(parameter, dict):
                    entities.append(_entity(
                        f"mixer/{mixer_index}/parameter/{key}", key, _parameter_native(parameter),
                        "mixer_parameter", writable=bool(parameter.get("writable")),
                        unit=parameter.get("unit"),
                    ))

    if include_statistics:
        stats = snapshot.get("statistics", {}) if isinstance(snapshot.get("statistics"), dict) else {}
        for key, value in stats.items():
            if is_scalar(value):
                entities.append(_entity(f"statistics/{key}", key, value, "statistics"))

    return entities


def fixed_ecomax860p4_profile(snapshot: dict[str, Any]) -> dict[str, Any]:
    values = snapshot.get("values", {}) if isinstance(snapshot.get("values"), dict) else {}
    params = snapshot.get("parameters", {}) if isinstance(snapshot.get("parameters"), dict) else {}
    entities: list[dict[str, Any]] = []
    for key in KNOWN_ECOMAX_860P4_VALUES:
        entities.append(_entity(f"value/{key}", key, values.get(key), "value", available=key in values))
    for key in KNOWN_ECOMAX_860P4_PARAMETERS:
        parameter = params.get(key)
        native = _parameter_native(parameter) if isinstance(parameter, dict) else None
        entities.append(_entity(
            f"parameter/{key}", key, native, "parameter",
            writable=bool(isinstance(parameter, dict) and parameter.get("writable")),
            available=key in params,
            unit=parameter.get("unit") if isinstance(parameter, dict) else None,
        ))
    # Mieszacze są dynamiczne nawet w profilu stałym, bo liczba mieszaczy zależy od instalacji.
    mixers_only = detected_entities({"values": {}, "parameters": {}, "mixers": snapshot.get("mixers", {})}, include_parameters=False, include_mixers=True)
    entities.extend(mixers_only)
    return {
        "mode": "fixed_ecomax860p4",
        "name": "Profil stały: ecoMAX 860P4 / diagnostyka użytkownika",
        "generated_at": utc_now_iso(),
        "connected": bool(snapshot.get("connected")),
        "simulation": bool(snapshot.get("simulation")),
        "alerts_available": isinstance(snapshot.get("alerts"), list),
        "entities": entities,
        "counts": {
            "available": sum(1 for e in entities if e.get("available")),
            "defined": len(entities),
        },
        "note": "Profil pokazuje znane pola z diagnostyki ecoMAX 860P4, a nieznane pola nadal są dostępne w MQTT raw i /api/snapshot.",
    }


def auto_profile(snapshot: dict[str, Any]) -> dict[str, Any]:
    entities = detected_entities(snapshot, include_parameters=True, include_mixers=True, include_statistics=False)
    return {
        "mode": "auto_detect",
        "name": "Profil automatyczny: tylko odczyty wykryte w sterowniku",
        "generated_at": utc_now_iso(),
        "connected": bool(snapshot.get("connected")),
        "simulation": bool(snapshot.get("simulation")),
        "alerts_available": isinstance(snapshot.get("alerts"), list),
        "entities": entities,
        "counts": {
            "available": len(entities),
            "defined": len(entities),
        },
        "note": "Profil tworzony z aktualnego snapshotu. Home Assistant Discovery publikuje tylko wykryte encje.",
    }


def build_controller_profile(snapshot: dict[str, Any], mode: str = "fixed_ecomax860p4") -> dict[str, Any]:
    if str(mode).lower() in {"auto", "auto_detect", "dynamic"}:
        return auto_profile(snapshot)
    return fixed_ecomax860p4_profile(snapshot)
