"""Wczytywanie konfiguracji PlumBox."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any
import os
import tempfile

import yaml


@dataclass(slots=True)
class ConnectionConfig:
    type: str = "simulation"
    host: str = "192.168.1.50"
    port: int = 8899
    serial_device: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    reconnect_delay_seconds: float = 5.0
    connect_timeout_seconds: float = 10.0
    device_timeout_seconds: float = 60.0
    stale_frame_timeout_seconds: float = 45.0
    cleanup_timeout_seconds: float = 12.0


@dataclass(slots=True)
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    title: str = "PlumBox"
    poll_interval_seconds: float = 1.0


@dataclass(slots=True)
class SecurityConfig:
    pin: str | None = None
    pin_hash: str | None = None
    session_hours: int = 12
    require_pin_for_all_writes: bool = True
    # Domyślnie zapisujemy tylko parametry oznaczone jako risk=safe.
    # Advanced/critical zostają do odczytu do czasu weryfikacji realnego snapshotu sterownika.
    safe_writes_only: bool = True
    login_session_hours: int = 24


@dataclass(slots=True)
class HistoryConfig:
    enabled: bool = True
    database_path: str = "/var/lib/plumbox/plumbox.db"
    sample_interval_seconds: int = 30
    retention_days: int = 365


@dataclass(slots=True)
class ProfileConfig:
    # fixed_ecomax860p4 — stabilna wersja pod diagnostykę Mateusza.
    # auto_detect — profil tworzony z realnych pól zwróconych przez sterownik.
    mode: str = "fixed_ecomax860p4"
    discovery_mode: str = "profile_entities"
    include_parameters: bool = True
    include_mixers: bool = True
    include_statistics: bool = False


@dataclass(slots=True)
class MqttConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 1883
    username: str = ""
    password: str = ""
    base_topic: str = "plumbox"
    home_assistant_discovery: bool = True
    # V3N7: polecenia są osobną, jawną funkcją. Samo włączenie publikacji MQTT
    # nie musi automatycznie otwierać sterowania.
    commands_enabled: bool = True
    allow_advanced_commands: bool = True
    allow_critical_commands: bool = False
    allow_power_commands: bool = True


@dataclass(slots=True)
class AppConfig:
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    web: WebConfig = field(default_factory=WebConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    timezone: str = "Europe/Warsaw"
    log_level: str = "INFO"

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "AppConfig":
        def section(section_name: str, model: type) -> Any:
            raw = data.get(section_name, {})
            if not isinstance(raw, dict):
                raw = {}
            allowed = {item.name for item in fields(model)}
            return model(**{key: value for key, value in raw.items() if key in allowed})

        return cls(
            connection=section("connection", ConnectionConfig),
            web=section("web", WebConfig),
            security=section("security", SecurityConfig),
            history=section("history", HistoryConfig),
            mqtt=section("mqtt", MqttConfig),
            profile=section("profile", ProfileConfig),
            timezone=str(data.get("timezone", "Europe/Warsaw")),
            log_level=str(data.get("log_level", "INFO")).upper(),
        )


def ensure_mapping_section(data: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a writable YAML mapping, replacing an empty/null section safely."""
    section = data.get(name)
    if not isinstance(section, dict):
        section = {}
        data[name] = section
    return section


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Nie znaleziono konfiguracji: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError("Główny element konfiguracji musi być mapą YAML.")

    return AppConfig.from_mapping(raw)


def save_config(data: dict[str, Any], path: str | Path) -> None:
    """Atomically replace config so a crash cannot leave a partial YAML file."""
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    mode = config_path.stat().st_mode & 0o777 if config_path.exists() else 0o640
    fd, temporary = tempfile.mkstemp(prefix="plumbox-config-", suffix=".yaml", dir=str(config_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, config_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
