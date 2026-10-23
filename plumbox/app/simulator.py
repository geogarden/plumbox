"""Symulator ecoMAX do uruchamiania dashboardu bez kotła."""

from __future__ import annotations

import math
import random
import time
from typing import Any

from .common import utc_now_iso
from .mappings import PARAMETER_META
from .serializer import build_parameter_payload


class Simulator:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.parameters: dict[str, dict[str, Any]] = {}
        self._create_parameters()

    def _add(
        self,
        name: str,
        value: Any,
        minimum: Any,
        maximum: Any,
        step: Any = 1,
        unit: str | None = None,
        scope: str = "ecomax",
        index: int = 0,
        kind: str = "number",
    ) -> None:
        meta = PARAMETER_META.get(name, {})
        self.parameters[f"{scope}:{index}:{name}"] = build_parameter_payload(
            name,
            scope,
            index,
            kind=meta.get("kind", kind),
            value=value,
            native=value,
            minimum=minimum,
            maximum=maximum,
            step=step,
            unit=unit,
            meta=meta,
        )

    def _create_parameters(self) -> None:
        self._add("ecomax_control", True, False, True, kind="switch")
        self._add("heating_target_temp", 75, 60, 85, unit="°C")
        self._add("heating_pump_enable_temp", 54, 30, 80, unit="°C")
        self._add("heating_hysteresis", 17, 1, 30, unit="°C")
        self._add("boiler_power_100", 12, 9, 16, unit="kW")
        self._add("boiler_power_50", 8, 5, 11, unit="kW")
        self._add("boiler_power_30", 4, 3, 7, unit="kW")
        self._add("h2_hysteresis", 9, 1, 30, unit="°C")
        self._add("h1_hysteresis", 3, 1, 30, unit="°C")
        self._add("max_fuel_flow", 6.6, 1, 40, step=0.2, unit="kg/h")
        self._add("fuel_calorific_value", 5.0, 0.1, 25, step=0.1, unit="kWh/kg")
        self._add("airflow_correction_100", 0, -15, 30, unit="%")
        self._add("airflow_correction_50", 1, -15, 19, unit="%")
        self._add("airflow_correction_30", 3, -70, 22, unit="%")
        self._add("water_heater_target_temp", 50, 20, 70, unit="°C")
        self._add("water_heater_hysteresis", 9, 1, 30, unit="°C")
        self._add("water_heater_work_mode", 2, 0, 2, kind="select")
        self._add("water_heater_disinfection", False, False, True, kind="switch")
        self._add("summer_mode", 1, 0, 1, kind="select")
        self._add("summer_mode_enable_temp", 16, 5, 30, unit="°C")
        self._add("summer_mode_disable_temp", 12, 1, 15, unit="°C")
        self._add("mixer_target_temp", 50, 20, 70, unit="°C", scope="mixer")
        self._add("min_target_temp", 20, 20, 69, unit="°C", scope="mixer")
        self._add("max_target_temp", 70, 21, 90, unit="°C", scope="mixer")
        self._add("work_mode", 1, 0, 3, kind="select", scope="mixer")
        self._add("mixer_input_dead_zone", 2.0, 0, 4, step=0.1, unit="°C", scope="mixer")
        self._add("kindling_airflow_power", 1450, 400, 2850, step=10, unit="obr/min")
        self._add("kindling_test_time", 60, 10, 240, unit="s")
        self._add("kindling_time", 7, 1, 20, unit="min")
        self._add("warming_up_time", 50, 2, 500, step=2, unit="s")
        self._add("stabilization_time", 60, 1, 200, unit="min")
        self._add("stabilization_airflow_power", 1250, 400, 2850, step=10, unit="obr/min")
        self._add("supervision_time", 0, 0, 60, unit="min")
        self._add("fuel_detection_time", 1, 0, 5, unit="min")
        self._add("burning_off_max_time", 30, 1, 60, unit="min")
        self._add("burning_off_min_time", 3, 1, 60, unit="min")
        self._add("burning_off_airflow_power", 1600, 1000, 2100, step=10, unit="obr/min")
        self._add("cleaning_begin_time", 40, 10, 250, unit="s")
        self._add("burning_off_cleaning_time", 2, 1, 30, unit="min")
        self._add("cleaning_airflow_power", 2100, 400, 2850, step=10, unit="obr/min")
        self._add("boiler_alert_temp", 85, 85, 95, unit="°C")
        self._add("max_feeder_temp", 60, 30, 80, unit="°C")

    def snapshot(self) -> dict[str, Any]:
        elapsed = time.monotonic() - self.started
        wave = math.sin(elapsed / 35)
        heating = 67.5 + wave * 5.2 + random.uniform(-0.12, 0.12)
        boiler_load = max(0, min(100, 58 + math.sin(elapsed / 19) * 32))
        state = 3 if heating < 74.5 else 5

        values = {
            "state": state,
            "state_label": "Praca" if state == 3 else "Postój",
            "heating_temp": round(heating, 1),
            "return_temp": round(49 + wave * 2.4, 1),
            "water_heater_temp": round(47 + math.sin(elapsed / 80) * 1.4, 1),
            "feeder_temp": round(24 + math.sin(elapsed / 55), 1),
            "optical_temp": round(max(0, min(100, 20 + boiler_load * 0.8)), 1),
            "heating_target": 75,
            "water_heater_target": 50,
            "boiler_power": round(12 * boiler_load / 100, 1),
            "boiler_load": round(boiler_load),
            "fan_power": round(22 + boiler_load * 0.42),
            "fuel_level": 72,
            "fuel_consumption": round(0.3 + boiler_load / 100 * 1.8, 2),
            "fan": state == 3,
            "feeder": state == 3 and int(elapsed) % 8 < 3,
            "heating_pump": heating > 54,
            "water_heater_pump": False,
            "lighter": False,
            "alarm": False,
            "pending_alerts": 0,
            "modules": {"module_a": "5.41.19.P1", "panel": "5.21.18"},
        }

        ecomax_params = {
            key.split(":", 2)[2]: value
            for key, value in self.parameters.items()
            if key.startswith("ecomax:")
        }
        mixer_params = {
            key.split(":", 2)[2]: value
            for key, value in self.parameters.items()
            if key.startswith("mixer:")
        }

        return {
            "timestamp": utc_now_iso(),
            "connected": True,
            "simulation": True,
            "connection_error": None,
            "values": values,
            "parameters": ecomax_params,
            "mixers": {
                "0": {
                    "values": {
                        "current_temp": round(42 + math.sin(elapsed / 50) * 2, 1),
                        "target_temp": 50,
                        "pump": True,
                    },
                    "parameters": mixer_params,
                }
            },
            "alerts": [],
            "statistics": {
                "connected_since": utc_now_iso(),
                "received_frames": int(elapsed),
                "sent_frames": 0,
                "connection_losses": 0,
            },
        }

    def set_parameter(self, scope: str, index: int, name: str, value: Any) -> bool:
        key = f"{scope}:{index}:{name}"
        parameter = self.parameters.get(key)
        if not parameter:
            raise KeyError(name)

        if parameter["kind"] == "number":
            numeric = float(value)
            if numeric < float(parameter["min"]) or numeric > float(parameter["max"]):
                raise ValueError("Wartość poza zakresem.")
            value = int(numeric) if numeric.is_integer() else numeric
        elif parameter["kind"] == "switch":
            value = bool(value)
        elif parameter["kind"] == "select":
            value = int(value)

        parameter["value"] = value
        parameter["native_value"] = value

        if parameter["kind"] == "select":
            parameter["selected_label"] = parameter.get("options", {}).get(str(value))
        elif parameter["kind"] == "switch":
            parameter["selected_label"] = (
                parameter.get("on_label", "Włączony")
                if value
                else parameter.get("off_label", "Wyłączony")
            )

        return True
