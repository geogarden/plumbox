"""Strona administracyjna „Komunikacja i MQTT” — edycja config.yaml."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..admin_pages import render_communication_page
from ..config import ensure_mapping_section, save_config
from ..deps import CONFIG_PATH, form_dict, require_admin_user

router = APIRouter()


@router.get("/communication", include_in_schema=False)
async def communication_page(request: Request, message: str | None = None, error: str | None = None) -> HTMLResponse:
    require_admin_user(request)
    cfg = yaml.safe_load(Path(CONFIG_PATH).read_text(encoding="utf-8")) or {}
    return HTMLResponse(render_communication_page(cfg, message, error))


@router.post("/communication", include_in_schema=False)
async def communication_save(request: Request) -> RedirectResponse:
    require_admin_user(request)
    data = await form_dict(request)
    try:
        cfg_path = Path(CONFIG_PATH)
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        connection_type = data.get("connection_type") or "simulation"
        profile_mode = data.get("profile_mode") or "fixed_ecomax860p4"
        port = int(data.get("port") or 8899)
        baudrate = int(data.get("baudrate") or 115200)
        mqtt_port = int(data.get("mqtt_port") or 1883)
        base_topic = (data.get("mqtt_base_topic") or "plumbox").strip().strip("/")
        if connection_type not in {"simulation", "tcp", "serial"}:
            raise ValueError("Nieobsługiwany typ połączenia.")
        if profile_mode not in {"fixed_ecomax860p4", "auto_detect"}:
            raise ValueError("Nieobsługiwany tryb profilu.")
        if not 1 <= port <= 65535 or not 1 <= mqtt_port <= 65535:
            raise ValueError("Port musi mieścić się w zakresie 1-65535.")
        if baudrate <= 0:
            raise ValueError("Baudrate musi być liczbą dodatnią.")
        if not base_topic or "+" in base_topic or "#" in base_topic:
            raise ValueError("Base topic MQTT nie może być pusty ani zawierać znaków + lub #.")
        connection = ensure_mapping_section(cfg, "connection")
        connection.update({
            "type": connection_type,
            "host": data.get("host") or "192.168.1.50",
            "port": port,
            "serial_device": data.get("serial_device") or "/dev/ttyUSB0",
            "baudrate": baudrate,
        })
        profile = ensure_mapping_section(cfg, "profile")
        profile.update({
            "mode": profile_mode,
            "discovery_mode": "profile_entities",
            "include_parameters": True,
            "include_mixers": True,
            "include_statistics": False,
        })
        mqtt = ensure_mapping_section(cfg, "mqtt")
        # Hasła brokera nie odsyłamy do przeglądarki, więc puste pole formularza
        # oznacza „bez zmian". Wyczyszczenie hasła wymaga edycji config.yaml.
        mqtt_password = data.get("mqtt_password") or ""
        if not mqtt_password:
            mqtt_password = str(mqtt.get("password") or "")
        mqtt.update({
            "enabled": data.get("mqtt_enabled") == "1",
            "host": data.get("mqtt_host") or "127.0.0.1",
            "port": mqtt_port,
            "username": data.get("mqtt_username") or "",
            "password": mqtt_password,
            "base_topic": base_topic,
            "home_assistant_discovery": data.get("mqtt_discovery") == "1",
            "commands_enabled": data.get("mqtt_commands_enabled") == "1",
            "allow_advanced_commands": data.get("mqtt_allow_advanced_commands") == "1",
            "allow_critical_commands": data.get("mqtt_allow_critical_commands") == "1",
            "allow_power_commands": data.get("mqtt_allow_power_commands") == "1",
        })
        save_config(cfg, cfg_path)
        return RedirectResponse(url="/communication?" + urlencode({"message": "Zapisano. Uruchom ponownie usługę PlumBox."}), status_code=303)
    except Exception as exc:
        return RedirectResponse(url="/communication?" + urlencode({"error": str(exc)}), status_code=303)
