from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
import yaml

from app.security import create_pin_hash
from app.users import ensure_initial_admin

DATA = Path("/data")
OPTIONS_PATH = DATA / "options.json"
CONFIG_PATH = Path(os.environ.get("PLUMBOX_CONFIG", "/data/config.yaml"))
USERS_PATH = Path(os.environ.get("PLUMBOX_USERS", "/data/users.yaml"))
INITIAL_PASSWORD_PATH = DATA / "initial_admin_password.txt"
INITIAL_PIN_PATH = DATA / "initial_pin.txt"
EXAMPLE_CONFIG = Path("/opt/plumbox/config/config.example.yaml")


def read_options() -> dict:
    if not OPTIONS_PATH.exists():
        return {}
    try:
        data = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def make_config(options: dict, preserved_pin_hash: str | None = None) -> dict:
    if EXAMPLE_CONFIG.exists():
        cfg = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8")) or {}
    else:
        cfg = {}
    cfg.setdefault("connection", {})
    cfg.setdefault("web", {})
    cfg.setdefault("security", {})
    cfg.setdefault("history", {})
    cfg.setdefault("mqtt", {})
    cfg.setdefault("profile", {})
    ctype = str(options.get("connection_type") or "simulation")
    if ctype not in {"simulation", "serial", "tcp"}:
        ctype = "simulation"
    cfg["connection"].update({
        "type": ctype,
        "host": str(options.get("tcp_host") or "192.168.1.50"),
        "port": int(options.get("tcp_port") or 8899),
        "serial_device": str(options.get("serial_device") or "/dev/ttyUSB0"),
        "baudrate": int(options.get("baudrate") or 115200),
        "reconnect_delay_seconds": 5,
        "connect_timeout_seconds": 10,
        "device_timeout_seconds": 60,
        "stale_frame_timeout_seconds": 45,
        "cleanup_timeout_seconds": 12,
    })
    cfg["web"].update({"host": "0.0.0.0", "port": 8080, "title": "PlumBox", "poll_interval_seconds": 1})
    pin = str(options.get("initial_pin") or "")
    if len(pin) >= 4:
        pin_hash = create_pin_hash(pin)
    elif preserved_pin_hash:
        pin_hash = preserved_pin_hash
    else:
        raise ValueError("PIN musi mieć co najmniej 4 znaki.")
    cfg["security"].update({
        "login_required": False,
        "pin": None,
        "pin_hash": pin_hash,
        "session_hours": 12,
        "require_pin_for_all_writes": True,
        # advanced_writes=true (utrzymane w GPT SOL zgodnie z decyzją użytkownika):
        # zapisy advanced/critical dozwolone po PIN + potwierdzeniu, tylko admin.
        "safe_writes_only": not bool(options.get("advanced_writes", True)),
    })
    cfg["history"].update({"enabled": True, "database_path": "/data/plumbox.db", "sample_interval_seconds": 30, "retention_days": 365})
    profile_mode = str(options.get("profile_mode") or "auto_detect")
    if profile_mode not in {"fixed_ecomax860p4", "auto_detect"}:
        profile_mode = "auto_detect"
    cfg["profile"].update({
        "mode": profile_mode,
        "discovery_mode": "profile_entities",
        "include_parameters": True,
        "include_mixers": True,
        "include_statistics": False,
    })
    cfg["mqtt"].update({
        "enabled": bool(options.get("mqtt_enabled", False)),
        "host": str(options.get("mqtt_host") or "core-mosquitto"),
        "port": int(options.get("mqtt_port") or 1883),
        "username": str(options.get("mqtt_username") or ""),
        "password": str(options.get("mqtt_password") or ""),
        "base_topic": str(options.get("mqtt_base_topic") or "plumbox"),
        "home_assistant_discovery": bool(options.get("mqtt_discovery", True)),
        "commands_enabled": bool(options.get("mqtt_commands_enabled", True)),
        "allow_advanced_commands": bool(options.get("mqtt_allow_advanced_commands", True)),
        "allow_critical_commands": bool(options.get("mqtt_allow_critical_commands", False)),
        "allow_power_commands": bool(options.get("mqtt_allow_power_commands", True)),
    })
    cfg["timezone"] = "Europe/Warsaw"
    cfg["log_level"] = "INFO"
    return cfg


def existing_pin_hash() -> str | None:
    if not CONFIG_PATH.exists():
        return None
    try:
        current = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        security = current.get("security", {}) if isinstance(current, dict) else {}
        stored_hash = security.get("pin_hash") if isinstance(security, dict) else None
        if stored_hash:
            return str(stored_hash)
        plain_pin = security.get("pin") if isinstance(security, dict) else None
        if plain_pin and len(str(plain_pin)) >= 4:
            return create_pin_hash(str(plain_pin))
    except Exception:
        return None
    return None


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    options = read_options()
    apply_options = bool(options.get("apply_options_on_start", False))
    if apply_options or not CONFIG_PATH.exists():
        preserved_pin_hash = existing_pin_hash()
        if not str(options.get("initial_pin") or ""):
            if preserved_pin_hash:
                print("[PlumBox] Zachowano dotychczasowy PIN z istniejącej konfiguracji.")
            else:
                options["initial_pin"] = f"{secrets.randbelow(100_000_000):08d}"
                INITIAL_PIN_PATH.write_text(str(options["initial_pin"]) + "\n", encoding="utf-8")
                os.chmod(INITIAL_PIN_PATH, 0o600)
                print("[PlumBox] Wygenerowano PIN; zapisano go w /data/initial_pin.txt")
        if apply_options and CONFIG_PATH.exists():
            print("[PlumBox] UWAGA: apply_options_on_start nadpisuje ustawienia połączenia, profilu i MQTT wartościami z opcji dodatku.")
        CONFIG_PATH.write_text(
            yaml.safe_dump(make_config(options, preserved_pin_hash), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.chmod(CONFIG_PATH, 0o600)
    initial_password = str(options.get("initial_admin_password") or "") or None
    generated = ensure_initial_admin(USERS_PATH, password=initial_password)
    if generated:
        INITIAL_PASSWORD_PATH.write_text("Login: admin\nHasło: " + generated + "\n", encoding="utf-8")
        os.chmod(INITIAL_PASSWORD_PATH, 0o600)
        print("[PlumBox] Utworzono konto admin. Hasło zapisane w /data/initial_admin_password.txt")
    else:
        print("[PlumBox] Plik użytkowników już istnieje — nie zmieniam kont.")
    print(f"[PlumBox] Konfiguracja: {CONFIG_PATH}")
    print(f"[PlumBox] Użytkownicy: {USERS_PATH}")


if __name__ == "__main__":
    main()
