"""MQTT publisher with broker-confirmed state, reconnect and retained cleanup."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from typing import Any, Awaitable, Callable

from .common import is_scalar, utc_now_iso
from .config import MqttConfig, ProfileConfig
from .controller_profile import detected_entities
from .mappings import SENSOR_META

_LOGGER = logging.getLogger(__name__)

_FULL_STATE_HEARTBEAT_SECONDS = 60.0

# Confirmed PyPlumIO sensor names. Presentation changes apply to MQTT only.
_MQTT_TEMPERATURES = {
    "exhaust_temp": {"label": "Temperatura spalin"},
    "outside_temp": {},
    "current_temp": {},
}
_MQTT_TEMPERATURE_PRECISION = {"exhaust_temp": 1, "outside_temp": 1, "current_temp": 2}


def _mqtt_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    values = snapshot.get("values")
    if not isinstance(values, dict):
        return snapshot
    rounded = dict(values)
    for key, precision in _MQTT_TEMPERATURE_PRECISION.items():
        value = values.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            rounded[key] = round(float(value), precision)
    return {**snapshot, "values": rounded}

ParameterWriter = Callable[[str, int, str, Any], Awaitable[dict[str, Any]]]
PowerWriter = Callable[[bool], Awaitable[dict[str, Any]]]


def _safe_topic(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", str(value)).strip("_") or "value"


def _flatten(prefix: str, value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}/{_safe_topic(key)}" if prefix else _safe_topic(key)
            result.update(_flatten(path, child))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.update(_flatten(f"{prefix}/{index}", child))
    else:
        result[prefix] = value
    return result


def _scalar_text(value: Any) -> str:
    return "" if value is None else str(value)


def _parameter_natives(parameters: Any) -> dict[str, Any]:
    if not isinstance(parameters, dict):
        return {}
    return {
        name: (item.get("native_value", item.get("value")) if isinstance(item, dict) else item)
        for name, item in parameters.items()
    }


def _raw_source(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Zawęża snapshot do surowych danych przed spłaszczeniem do raw/**.

    Bez tego każdy parametr wnosił ~20 retained topiców metadanych UI (label,
    on_action_label, options...), a sekcja profile kolejne setki — łącznie ponad
    1300 publikacji co poll_interval. Zostają wartości natywne; pełne payloady
    są nadal dostępne w {base}/state i {base}/profile jako JSON.
    """
    source: dict[str, Any] = {}
    for key, value in snapshot.items():
        if key == "profile":
            continue
        if key == "parameters":
            source[key] = _parameter_natives(value)
        elif key == "mixers" and isinstance(value, dict):
            source[key] = {
                index: {
                    "values": mixer.get("values") or {},
                    "parameters": _parameter_natives(mixer.get("parameters")),
                }
                for index, mixer in value.items()
                if isinstance(mixer, dict)
            }
        else:
            source[key] = value
    return source


class MqttPublisher:
    def __init__(
        self,
        config: MqttConfig,
        profile: ProfileConfig | None = None,
        *,
        parameter_writer: ParameterWriter | None = None,
        power_writer: PowerWriter | None = None,
    ) -> None:
        self.config = config
        self.profile = profile or ProfileConfig()
        self._parameter_writer = parameter_writer
        self._power_writer = power_writer
        self._client: Any = None
        self._mqtt: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected = False
        self._state_topics: set[str] = set()
        self._published_payloads: dict[str, str] = {}
        self._last_full_publish_monotonic = 0.0
        self._force_full_publish = True
        self._discovery_topics: set[str] = set()
        self._discovery_signature = ""
        self._last_snapshot: dict[str, Any] = {}

    def set_command_handlers(
        self,
        parameter_writer: ParameterWriter,
        power_writer: PowerWriter,
    ) -> None:
        self._parameter_writer = parameter_writer
        self._power_writer = power_writer

    async def start(self) -> None:
        if not self.config.enabled:
            return
        self._loop = asyncio.get_running_loop()
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            _LOGGER.error("MQTT włączone, ale brakuje pakietu paho-mqtt.")
            return

        self._mqtt = mqtt
        try:
            try:
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="plumbox")
            except (AttributeError, TypeError):
                client = mqtt.Client(client_id="plumbox")
            self._client = client
            if self.config.username:
                client.username_pw_set(self.config.username, self.config.password)
            base = self.config.base_topic.rstrip("/")
            client.will_set(f"{base}/availability", "offline", qos=0, retain=True)
            client.reconnect_delay_set(min_delay=1, max_delay=60)

            def on_connect(_client: Any, _userdata: Any, _flags: Any, reason_code: Any, *_extra: Any) -> None:
                failed = bool(getattr(reason_code, "is_failure", False))
                if not failed:
                    try:
                        failed = int(reason_code) != 0
                    except (TypeError, ValueError):
                        failed = False
                self._connected = not failed
                if failed:
                    _LOGGER.error("Broker MQTT odrzucił połączenie: %s", reason_code)
                else:
                    # Broker mógł utracić retained messages podczas restartu.
                    # Pierwszy snapshot po każdym reconnect publikuje więc pełny stan.
                    self._force_full_publish = True
                    if self.config.commands_enabled:
                        command_topic = f"{self.config.base_topic.rstrip('/')}/command/#"
                        result, _mid = _client.subscribe(command_topic, qos=0)
                        success = getattr(self._mqtt, "MQTT_ERR_SUCCESS", 0)
                        if result != success:
                            _LOGGER.error("Nie udało się zasubskrybować poleceń MQTT: %s", result)

            def on_disconnect(*_args: Any) -> None:
                self._connected = False
                self._force_full_publish = True

            def on_message(_client: Any, _userdata: Any, message: Any) -> None:
                loop = self._loop
                if not loop or not self.config.commands_enabled:
                    return
                try:
                    payload = message.payload.decode("utf-8")
                except (AttributeError, UnicodeDecodeError):
                    _LOGGER.warning("Odrzucono polecenie MQTT z niepoprawnym UTF-8: %s", message.topic)
                    return
                future = asyncio.run_coroutine_threadsafe(
                    self._handle_command(str(message.topic), payload, retained=bool(message.retain)),
                    loop,
                )

                def command_done(done: Any) -> None:
                    try:
                        done.result()
                    except Exception:
                        _LOGGER.exception("Nieobsłużony błąd polecenia MQTT.")

                future.add_done_callback(command_done)

            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            client.on_message = on_message
            client.connect_async(self.config.host, self.config.port, keepalive=60)
            client.loop_start()
        except Exception:
            self._connected = False
            _LOGGER.exception("Nie udało się uruchomić klienta MQTT.")

    async def stop(self) -> None:
        client = self._client
        if not client:
            return
        if self._connected:
            try:
                info = client.publish(f"{self.config.base_topic.rstrip('/')}/availability", "offline", qos=0, retain=True)
                await asyncio.to_thread(info.wait_for_publish, 2.0)
            except Exception:
                _LOGGER.warning("Nie udało się potwierdzić publikacji MQTT offline.")
        self._connected = False
        try:
            client.disconnect()
        finally:
            client.loop_stop()

    def _publish(self, topic: str, payload: str, *, retain: bool = True) -> None:
        info = self._client.publish(topic, payload, qos=0, retain=retain)
        success = getattr(self._mqtt, "MQTT_ERR_SUCCESS", 0)
        if getattr(info, "rc", success) != success:
            raise RuntimeError(f"MQTT publish error for {topic}: {info.rc}")

    @staticmethod
    def _payload_fingerprint(topic: str, payload: str, base: str) -> str:
        """Porównuje stan bez pól zmieniających się wyłącznie z upływem czasu."""
        if topic == f"{base}/state":
            try:
                comparable = json.loads(payload)
            except (TypeError, ValueError):
                return payload
            if isinstance(comparable, dict):
                comparable.pop("timestamp", None)
                return json.dumps(
                    comparable,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
        if topic == f"{base}/raw/timestamp":
            return "<heartbeat-timestamp>"
        return payload

    async def publish(self, snapshot: dict[str, Any]) -> None:
        if not self._connected or not self._client:
            return
        snapshot = _mqtt_snapshot(snapshot)
        self._last_snapshot = snapshot
        base = self.config.base_topic.rstrip("/")
        entities = self._entities_for_snapshot(snapshot)
        topics: dict[str, str] = {
            f"{base}/state": json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
            f"{base}/availability": "online" if snapshot.get("connected") else "offline",
            f"{base}/catalog/sensors": json.dumps(SENSOR_META, ensure_ascii=False, separators=(",", ":")),
            f"{base}/profile": json.dumps(snapshot.get("profile", {}), ensure_ascii=False, separators=(",", ":")),
        }
        for key, value in (snapshot.get("values") or {}).items():
            if is_scalar(value):
                topics[f"{base}/value/{_safe_topic(key)}"] = _scalar_text(value)
        for path, value in _flatten("", _raw_source(snapshot)).items():
            if is_scalar(value):
                topics[f"{base}/raw/{path}"] = _scalar_text(value)
        for entity in entities:
            path = entity.get("path")
            value = self._state_value_for_entity(snapshot, entity)
            if path and is_scalar(value):
                topics[f"{base}/entity/{path}"] = _scalar_text(value)

        now = time.monotonic()
        full_publish = (
            self._force_full_publish
            or self._last_full_publish_monotonic <= 0
            or now - self._last_full_publish_monotonic >= _FULL_STATE_HEARTBEAT_SECONDS
        )

        def send_state() -> None:
            stale_topics = self._state_topics - topics.keys()
            for stale in stale_topics:
                self._publish(stale, "")
            sent_payloads: dict[str, str] = {}
            for topic, payload in topics.items():
                fingerprint = self._payload_fingerprint(topic, payload, base)
                if full_publish or self._published_payloads.get(topic) != fingerprint:
                    self._publish(topic, payload)
                    sent_payloads[topic] = fingerprint
            for stale in stale_topics:
                self._published_payloads.pop(stale, None)
            self._published_payloads.update(sent_payloads)
            self._state_topics = set(topics)
            if full_publish:
                self._last_full_publish_monotonic = now
                self._force_full_publish = False

        try:
            await asyncio.to_thread(send_state)
            if self.config.home_assistant_discovery:
                signature = self._discovery_hash(entities, snapshot)
                if signature != self._discovery_signature:
                    await asyncio.to_thread(self._publish_discovery, snapshot, entities)
                    self._discovery_signature = signature
        except Exception:
            _LOGGER.exception("Publikacja MQTT nie powiodła się.")

    def _entities_for_snapshot(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        entities = []
        for entity in self._base_entities_for_snapshot(snapshot):
            path = str(entity.get("path") or "")
            key = path.removeprefix("value/") if path.startswith("value/") else ""
            if key in _MQTT_TEMPERATURES:
                entity = {**entity, **_MQTT_TEMPERATURES[key], "unit": "°C", "device_class": "temperature"}
            entities.append(entity)
        return entities

    def _base_entities_for_snapshot(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        profile = snapshot.get("profile") if isinstance(snapshot.get("profile"), dict) else {}
        entities = profile.get("entities")
        if isinstance(entities, list) and self.profile.discovery_mode != "legacy_values":
            # Profil FIXED celowo ogranicza główny panel do sprawdzonych pozycji,
            # ale MQTT ma pełnić rolę lokalnego ecoNET i udostępniać wszystkie
            # parametry faktycznie obecne w bieżącym snapshotcie. Łączymy więc
            # encje profilu z autodetekcją, nie zmieniając samego profilu/UI.
            merged: dict[str, dict[str, Any]] = {
                str(item.get("path")): item
                for item in entities
                if isinstance(item, dict) and item.get("path") and item.get("available", True)
            }
            for item in detected_entities(
                snapshot,
                include_parameters=True,
                include_mixers=True,
                include_statistics=False,
            ):
                path = str(item.get("path") or "")
                if path and item.get("available", True):
                    merged.setdefault(path, item)
            return list(merged.values())
        if self.profile.mode in {"auto", "auto_detect", "dynamic"}:
            return detected_entities(snapshot, include_parameters=True, include_mixers=True, include_statistics=False)
        values = snapshot.get("values", {}) if isinstance(snapshot.get("values"), dict) else {}
        return [{"path": f"value/{key}", "key": key, "label": SENSOR_META.get(key, {}).get("label") or key, "unit": SENSOR_META.get(key, {}).get("unit"), "domain": "binary_sensor" if isinstance(value, bool) else "sensor"} for key, value in values.items() if is_scalar(value)]

    @staticmethod
    def _value_by_entity_path(snapshot: dict[str, Any], path: str | None) -> Any:
        if not path:
            return None
        parts = str(path).split("/")
        try:
            if parts[0] == "value" and len(parts) >= 2:
                return snapshot.get("values", {}).get(parts[1])
            if parts[0] == "parameter" and len(parts) >= 2:
                item = snapshot.get("parameters", {}).get(parts[1], {})
                return item.get("native_value", item.get("value"))
            if parts[0] == "mixer" and len(parts) >= 4:
                mixer = snapshot.get("mixers", {}).get(parts[1], {})
                if parts[2] == "value":
                    return mixer.get("values", {}).get(parts[3])
                item = mixer.get("parameters", {}).get(parts[3], {})
                return item.get("native_value", item.get("value"))
        except (AttributeError, IndexError, TypeError):
            return None
        return None

    @staticmethod
    def _parameter_by_entity_path(snapshot: dict[str, Any], path: str | None) -> dict[str, Any] | None:
        if not path:
            return None
        parts = str(path).split("/")
        try:
            if parts[0] == "parameter" and len(parts) == 2:
                item = snapshot.get("parameters", {}).get(parts[1])
                return item if isinstance(item, dict) else None
            if parts[0] == "mixer" and len(parts) == 4 and parts[2] == "parameter":
                item = snapshot.get("mixers", {}).get(parts[1], {}).get("parameters", {}).get(parts[3])
                return item if isinstance(item, dict) else None
        except (AttributeError, IndexError, TypeError):
            return None
        return None

    def _command_allowed(self, path: str, parameter: dict[str, Any]) -> bool:
        if not self.config.commands_enabled or not bool(parameter.get("writable")):
            return False
        name = path.rsplit("/", 1)[-1]
        if name == "ecomax_control":
            return bool(self.config.allow_power_commands)
        risk = str(parameter.get("risk") or "advanced").lower()
        if risk == "safe":
            return True
        if risk == "advanced":
            return bool(self.config.allow_advanced_commands)
        if risk == "critical":
            return bool(self.config.allow_critical_commands)
        return False

    def _entity_domain(self, snapshot: dict[str, Any], entity: dict[str, Any]) -> str:
        path = str(entity.get("path") or "")
        parameter = self._parameter_by_entity_path(snapshot, path)
        if not parameter or not self._command_allowed(path, parameter):
            return str(entity.get("domain") or "sensor")
        kind = str(parameter.get("kind") or "number").lower()
        if kind == "switch":
            return "switch"
        if kind == "select" or parameter.get("options"):
            return "select"
        return "number"

    def _state_value_for_entity(self, snapshot: dict[str, Any], entity: dict[str, Any]) -> Any:
        path = str(entity.get("path") or "")
        parameter = self._parameter_by_entity_path(snapshot, path)
        if not parameter:
            return self._value_by_entity_path(snapshot, path)
        domain = self._entity_domain(snapshot, entity)
        if domain == "switch":
            native = parameter.get("native_value", parameter.get("value"))
            enabled = native is True or native == 1 or str(native).lower() in {"1", "true", "on"}
            return "ON" if enabled else "OFF"
        if domain == "select":
            selected = parameter.get("selected_label")
            if selected not in {None, ""}:
                return selected
            native = parameter.get("native_value", parameter.get("value"))
            key = str(int(native) if isinstance(native, float) and native.is_integer() else native)
            return (parameter.get("options") or {}).get(key, key)
        # Dla number oraz parametrów pozostających sensorami publikujemy wartość
        # prezentowaną. Dzięki temu skala RPM product ID 211 jest taka sama w HA
        # i w panelu PlumBox.
        return parameter.get("value", parameter.get("native_value"))

    def _discovery_hash(self, entities: list[dict[str, Any]], snapshot: dict[str, Any]) -> str:
        profile = snapshot.get("profile") if isinstance(snapshot.get("profile"), dict) else {}
        controls = {
            str(entity.get("path")): self._parameter_by_entity_path(snapshot, entity.get("path"))
            for entity in entities
            if str(entity.get("path") or "").startswith(("parameter/", "mixer/"))
        }
        return json.dumps(
            {
                "entities": entities,
                "profile": profile.get("name"),
                "controls": controls,
                "commands": {
                    "enabled": self.config.commands_enabled,
                    "advanced": self.config.allow_advanced_commands,
                    "critical": self.config.allow_critical_commands,
                    "power": self.config.allow_power_commands,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    def _publish_discovery(self, snapshot: dict[str, Any], entities: list[dict[str, Any]]) -> None:
        base = self.config.base_topic.rstrip("/")
        current: set[str] = set()
        profile = snapshot.get("profile") if isinstance(snapshot.get("profile"), dict) else {}
        for entity in entities:
            path = str(entity.get("path") or "")
            if not path:
                continue
            domain = self._entity_domain(snapshot, entity)
            topic = f"homeassistant/{domain}/plumbox/{_safe_topic(path)}/config"
            current.add(topic)
            config: dict[str, Any] = {
                "name": f"PlumBox {entity.get('label') or path.replace('/', ' ')}",
                "unique_id": f"plumbox_{_safe_topic(path)}",
                "state_topic": f"{base}/entity/{path}",
                "availability_topic": f"{base}/availability",
                "device": {"identifiers": ["plumbox"], "name": "PlumBox", "manufacturer": "PlumBox", "model": profile.get("name", "ecoMAX local gateway")},
            }
            if entity.get("unit"):
                config["unit_of_measurement"] = entity["unit"]
            if entity.get("device_class"):
                config["device_class"] = entity["device_class"]
            if domain == "sensor" and path in {f"value/{key}" for key in _MQTT_TEMPERATURES}:
                config["suggested_display_precision"] = _MQTT_TEMPERATURE_PRECISION[path.removeprefix("value/")]
            parameter = self._parameter_by_entity_path(snapshot, path)
            if parameter and domain in {"number", "select", "switch"}:
                config["command_topic"] = f"{base}/command/{path}"
                config["optimistic"] = False
                config["qos"] = 0
                if domain == "number":
                    for source_key, target_key in (("min", "min"), ("max", "max"), ("step", "step")):
                        value = parameter.get(source_key)
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            config[target_key] = value
                    config["mode"] = "box"
                elif domain == "select":
                    options = [str(value) for value in (parameter.get("options") or {}).values()]
                    if options:
                        config["options"] = options
                elif domain == "switch":
                    config.update({"payload_on": "ON", "payload_off": "OFF"})
            # state_class=measurement włącza statystyki długoterminowe HA.
            # Tylko jednostki jednoznacznie chwilowe; kg/kWh pomijamy, bo nie
            # wiemy bez dowodu, czy to licznik czy wartość chwilowa.
            if domain == "sensor" and config.get("unit_of_measurement") in {"°C", "%", "kW", "W", "kg/h"}:
                config["state_class"] = "measurement"
            if domain == "binary_sensor":
                config.update({"payload_on": "True", "payload_off": "False"})
            # Po zmianie domeny (np. sensor -> number) usuń retained Discovery
            # poprzedniej wersji również po restarcie procesu. Sama pamięciowa
            # lista _discovery_topics nie zna tematów opublikowanych przez V3N6.
            # Najpierw usuwamy starą encję, a dopiero potem publikujemy nową.
            # W przeciwnym razie HA może chwilowo odrzucić nową domenę z powodu
            # istniejącego unique_id i po skasowaniu starej pozostawić pustkę.
            for old_domain in {"sensor", "binary_sensor", "number", "select", "switch", "button"} - {domain}:
                self._publish(f"homeassistant/{old_domain}/plumbox/{_safe_topic(path)}/config", "")
            self._publish(topic, json.dumps(config, ensure_ascii=False, separators=(",", ":")))
        for stale in self._discovery_topics - current:
            self._publish(stale, "")
        self._discovery_topics = current

    @staticmethod
    def _command_target(path: str) -> tuple[str, int, str]:
        parts = str(path).split("/")
        if len(parts) == 2 and parts[0] == "parameter":
            return "ecomax", 0, parts[1]
        if len(parts) == 4 and parts[0] == "mixer" and parts[2] == "parameter":
            return "mixer", int(parts[1]), parts[3]
        raise ValueError("Polecenia MQTT obsługują wyłącznie parametry ecoMAX i mieszacza.")

    @staticmethod
    def _parse_command_value(payload: str, domain: str, parameter: dict[str, Any]) -> Any:
        text = payload.strip()
        if domain == "switch":
            normalized = text.lower()
            if normalized in {"on", "true", "1", "włączony", "wlaczony"}:
                return True
            if normalized in {"off", "false", "0", "wyłączony", "wylaczony"}:
                return False
            raise ValueError("Przełącznik przyjmuje ON albo OFF.")
        if domain == "select":
            options = parameter.get("options") or {}
            for native, label in options.items():
                if text == str(label) or text == str(native):
                    try:
                        return int(native)
                    except (TypeError, ValueError):
                        try:
                            return float(native)
                        except (TypeError, ValueError):
                            return native
            raise ValueError("Wartość nie znajduje się na liście opcji parametru.")
        if domain == "number":
            try:
                value = float(text.replace(",", "."))
            except ValueError as exc:
                raise ValueError("Wymagana jest wartość liczbowa.") from exc
            minimum = parameter.get("min")
            maximum = parameter.get("max")
            special_zero = bool(parameter.get("special_zero"))
            if isinstance(minimum, (int, float)) and value < float(minimum) and not (special_zero and value == 0):
                raise ValueError(f"Wartość jest mniejsza niż minimum {minimum}.")
            if isinstance(maximum, (int, float)) and value > float(maximum):
                raise ValueError(f"Wartość jest większa niż maksimum {maximum}.")
            if value.is_integer():
                return int(value)
            return value
        raise ValueError("Ta encja MQTT nie obsługuje poleceń.")

    async def _publish_command_result(
        self,
        path: str,
        *,
        success: bool,
        requested: Any,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        if not self._client:
            return
        payload = {
            "timestamp": utc_now_iso(),
            "path": path,
            "success": bool(success),
            "requested_value": requested,
            "message": message,
        }
        if detail:
            payload["write"] = detail
        topic = f"{self.config.base_topic.rstrip('/')}/result/{path}"
        await asyncio.to_thread(
            self._publish,
            topic,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
        )

    async def _handle_command(self, topic: str, payload: str, *, retained: bool = False) -> None:
        prefix = f"{self.config.base_topic.rstrip('/')}/command/"
        if not topic.startswith(prefix):
            return
        path = topic[len(prefix):].strip("/")
        requested: Any = payload
        if retained:
            await self._publish_command_result(
                path,
                success=False,
                requested=requested,
                message="Odrzucono zachowane polecenie MQTT (retain).",
            )
            return
        try:
            entity = next(
                (
                    item
                    for item in self._entities_for_snapshot(self._last_snapshot)
                    if str(item.get("path") or "") == path
                ),
                None,
            )
            parameter = self._parameter_by_entity_path(self._last_snapshot, path)
            if not entity or not parameter:
                raise KeyError("Parametr nie jest dostępny w aktualnym odczycie sterownika.")
            if not self._command_allowed(path, parameter):
                raise PermissionError("Sterowanie tym parametrem nie jest dozwolone w konfiguracji MQTT.")
            domain = self._entity_domain(self._last_snapshot, entity)
            requested = self._parse_command_value(payload, domain, parameter)
            scope, index, name = self._command_target(path)
            if name == "ecomax_control":
                if not self._power_writer:
                    raise RuntimeError("Brak obsługi sterowania zasilaniem kotła.")
                result = await self._power_writer(bool(requested))
            else:
                if not self._parameter_writer:
                    raise RuntimeError("Brak obsługi zapisu parametrów.")
                result = await self._parameter_writer(scope, index, name, requested)
            await self._publish_command_result(
                path,
                success=bool(result.get("success")),
                requested=requested,
                message=str(result.get("message") or ""),
                detail=result,
            )
        except Exception as exc:
            _LOGGER.warning("Polecenie MQTT %s zostało odrzucone: %s", path, exc)
            await self._publish_command_result(
                path,
                success=False,
                requested=requested,
                message=str(exc),
            )

