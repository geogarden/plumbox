"""Konwersja obiektów PyPlumIO na JSON."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from .mappings import (
    ALERT_LABELS,
    AIRFLOW_CORRECTION_NAMES,
    ECOMAX860P4_STATE_LABELS,
    FAN_RPM_NAMES,
    STATE_LABELS,
    display_step,
    display_value,
    meta_for,
)


def simple_value(value: Any) -> Any:
    # Enum przed testem skalarnym: IntEnum (np. pyplumio DeviceState) przechodzi
    # isinstance(int), a jego str() daje "DeviceState.WORKING" na Pythonie 3.10
    # i "3" na 3.11+. Kod liczbowy ujednolica MQTT/SQLite z symulatorem.
    if isinstance(value, Enum):
        if isinstance(value, int):
            return int(value)
        return {"name": value.name, "value": value.value}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return {key: simple_value(item) for key, item in asdict(value).items()}
    if hasattr(value, "_asdict"):
        return {key: simple_value(item) for key, item in value._asdict().items()}
    if isinstance(value, dict):
        return {str(key): simple_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [simple_value(item) for item in value]
    return str(value)


def is_parameter(value: Any) -> bool:
    return all(hasattr(value, attr) for attr in ("value", "min_value", "max_value", "description"))


def unit_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def selected_parameter_label(kind: str, native: Any, meta: dict[str, Any]) -> Any:
    """Etykieta aktualnego stanu parametru (dla switch/select)."""
    if kind == "switch":
        enabled = native is True or native == 1 or str(native).lower() in {"1", "true", "on"}
        return meta.get("on_label", "Włączony") if enabled else meta.get("off_label", "Wyłączony")
    key = str(int(native) if isinstance(native, float) and native.is_integer() else native)
    return meta.get("options", {}).get(key)


def build_parameter_payload(
    name: str,
    scope: str,
    index: int,
    *,
    kind: str,
    value: Any,
    native: Any,
    minimum: Any,
    maximum: Any,
    step: Any,
    unit: Any,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Wspólny kształt słownika parametru dla dashboardu.

    Używany zarówno przez :func:`parameter_to_dict` (dane z PyPlumIO), jak i przez
    symulator — dzięki temu obie ścieżki dają identyczny payload i nie rozjadą się
    przy dodaniu nowego pola. Domyślne etykiety pokrywają się z ``meta_for``, więc
    działa tak samo dla surowego ``PARAMETER_META`` i dla przetworzonej meta.
    """
    return {
        "name": name,
        "scope": scope,
        "index": index,
        "label": meta.get("label", name.replace("_", " ").capitalize()),
        "section": meta.get("section", "other"),
        "risk": meta.get("risk", "advanced"),
        "access": meta.get("access", "service"),
        "kind": kind,
        "value": value,
        "native_value": native,
        "min": minimum,
        "max": maximum,
        "step": step,
        "unit": unit,
        "options": meta.get("options", {}),
        "selected_label": selected_parameter_label(kind, native, meta),
        "on_label": meta.get("on_label", "Włączony"),
        "off_label": meta.get("off_label", "Wyłączony"),
        "on_action_label": meta.get("on_action_label", "Włącz"),
        "off_action_label": meta.get("off_action_label", "Wyłącz"),
        # Parametry advanced/critical pozostają tylko do odczytu do czasu
        # potwierdzenia skal i zakresów na rzeczywistym sterowniku.
        "writable": meta.get("risk", "advanced") == "safe",
        "special_zero": bool(meta.get("special_zero", False)),
    }


def parameter_to_dict(
    name: str,
    parameter: Any,
    scope: str = "ecomax",
    index: int = 0,
    *,
    fan_rpm_enabled: bool = False,
    airflow_correction_enabled: bool = False,
) -> dict[str, Any]:
    meta = meta_for(name, scope)
    native = parameter.value

    kind = meta.get("kind")
    if not kind:
        class_name = parameter.__class__.__name__.lower()
        kind = "switch" if "switch" in class_name else "number"

    # Dla ecoMAX 860P4/PellasX część ogólnych opisów PyPlumIO ma jednostki
    # właściwe dla innych wariantów sterownika (np. % zamiast rpm). Lokalna,
    # potwierdzona sprzętowo meta ma pierwszeństwo, bez zmiany wartości natywnej.
    # Lokalna jednostka obr/min jest potwierdzona tylko dla profilu RPM.
    # W AUTO_DETECT obcego/nieznanego sterownika zachowujemy jednostkę PyPlumIO
    # zamiast opisywać surową wartość jako RPM.
    fan_transform_unverified = name in FAN_RPM_NAMES and not fan_rpm_enabled
    airflow_transform_unverified = (
        name in AIRFLOW_CORRECTION_NAMES and not airflow_correction_enabled
    )
    unit = (
        None
        if fan_transform_unverified or airflow_transform_unverified
        else unit_text(meta.get("unit"))
    )
    if not unit and not airflow_transform_unverified:
        unit = unit_text(getattr(parameter, "unit_of_measurement", None))
    if not unit and not airflow_transform_unverified:
        unit = unit_text(getattr(parameter.description, "unit_of_measurement", None))

    step = display_step(
        name,
        getattr(parameter.description, "step", 1),
        scope,
        fan_rpm_enabled=fan_rpm_enabled,
    )

    return build_parameter_payload(
        name,
        scope,
        index,
        kind=kind,
        value=display_value(
            name,
            native,
            scope,
            fan_rpm_enabled=fan_rpm_enabled,
            airflow_correction_enabled=airflow_correction_enabled,
        ),
        native=native,
        minimum=display_value(
            name,
            parameter.min_value,
            scope,
            fan_rpm_enabled=fan_rpm_enabled,
            airflow_correction_enabled=airflow_correction_enabled,
        ),
        maximum=display_value(
            name,
            parameter.max_value,
            scope,
            fan_rpm_enabled=fan_rpm_enabled,
            airflow_correction_enabled=airflow_correction_enabled,
        ),
        step=step,
        unit=unit,
        meta=meta,
    )


def alert_to_dict(alert: Any) -> dict[str, Any]:
    code_obj = getattr(alert, "code", 255)
    code = code_obj.value if isinstance(code_obj, Enum) else int(code_obj)
    from_dt = getattr(alert, "from_dt", None)
    to_dt = getattr(alert, "to_dt", None)
    if code in ALERT_LABELS:
        name = ALERT_LABELS[code]
    elif isinstance(code_obj, Enum):
        # Nie tłumaczymy nieznanego kodu na podstawie domysłu. Nazwa elementu
        # enumu PyPlumIO zachowuje informację diagnostyczną bez zmiany znaczenia.
        name = f"Alarm {code} ({code_obj.name})"
    else:
        name = f"Alarm {code}"
    return {
        "code": code,
        "name": name,
        "from": simple_value(from_dt),
        "to": simple_value(to_dt),
        "active": to_dt is None,
    }


def state_label(value: Any, *, ecomax860p4_profile_enabled: bool = False) -> str:
    if isinstance(value, Enum):
        numeric = value.value
    else:
        numeric = value
    try:
        code = int(numeric)
        if ecomax860p4_profile_enabled and code in ECOMAX860P4_STATE_LABELS:
            return ECOMAX860P4_STATE_LABELS[code]
        return STATE_LABELS.get(code, f"Stan {numeric}")
    except (TypeError, ValueError):
        return str(value)
