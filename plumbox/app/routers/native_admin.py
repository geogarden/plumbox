"""Natywne API zakładek systemowych V3 z zachowaniem starych stron iframe."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config import ensure_mapping_section, save_config
from ..deps import CONFIG_PATH, SESSION_COOKIE, require_admin_user, require_login_user, state
from ..users import USERS_PATH, add_user, delete_user, list_users, set_password, verify_user_password

router = APIRouter(prefix="/api/native-admin", tags=["native-admin-v3"])


class CommunicationUpdate(BaseModel):
    connection_type: str = "simulation"
    host: str = "192.168.1.50"
    port: int = Field(default=8899, ge=1, le=65535)
    serial_device: str = "/dev/ttyUSB0"
    baudrate: int = Field(default=115200, gt=0)
    profile_mode: str = "fixed_ecomax860p4"
    mqtt_enabled: bool = False
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_base_topic: str = "plumbox"
    mqtt_discovery: bool = True
    mqtt_commands_enabled: bool = True
    mqtt_allow_advanced_commands: bool = True
    mqtt_allow_critical_commands: bool = False
    mqtt_allow_power_commands: bool = True


class UserCreate(BaseModel):
    username: str
    display_name: str = ""
    password: str
    role: str = "user"


class PasswordUpdate(BaseModel):
    password: str


class AccountPasswordUpdate(BaseModel):
    old_password: str
    new_password: str
    repeat_password: str


def _read_config() -> dict[str, Any]:
    return yaml.safe_load(Path(CONFIG_PATH).read_text(encoding="utf-8")) or {}


@router.get("/communication")
async def communication_get(request: Request) -> dict[str, Any]:
    require_admin_user(request)
    cfg = _read_config()
    connection = cfg.get("connection") if isinstance(cfg.get("connection"), dict) else {}
    profile = cfg.get("profile") if isinstance(cfg.get("profile"), dict) else {}
    mqtt = cfg.get("mqtt") if isinstance(cfg.get("mqtt"), dict) else {}
    return {
        "connection_type": connection.get("type", "simulation"),
        "host": connection.get("host", "192.168.1.50"),
        "port": connection.get("port", 8899),
        "serial_device": connection.get("serial_device", "/dev/ttyUSB0"),
        "baudrate": connection.get("baudrate", 115200),
        "profile_mode": profile.get("mode", "fixed_ecomax860p4"),
        "mqtt_enabled": bool(mqtt.get("enabled", False)),
        "mqtt_host": mqtt.get("host", "127.0.0.1"),
        "mqtt_port": mqtt.get("port", 1883),
        "mqtt_username": mqtt.get("username", ""),
        "mqtt_password_configured": bool(mqtt.get("password")),
        "mqtt_base_topic": mqtt.get("base_topic", "plumbox"),
        "mqtt_discovery": bool(mqtt.get("home_assistant_discovery", True)),
        "mqtt_commands_enabled": bool(mqtt.get("commands_enabled", True)),
        "mqtt_allow_advanced_commands": bool(mqtt.get("allow_advanced_commands", True)),
        "mqtt_allow_critical_commands": bool(mqtt.get("allow_critical_commands", False)),
        "mqtt_allow_power_commands": bool(mqtt.get("allow_power_commands", True)),
    }


@router.put("/communication")
async def communication_update(payload: CommunicationUpdate, request: Request) -> dict[str, Any]:
    require_admin_user(request)
    if payload.connection_type not in {"simulation", "tcp", "serial"}:
        raise HTTPException(status_code=422, detail="Nieobsługiwany typ połączenia.")
    if payload.profile_mode not in {"fixed_ecomax860p4", "auto_detect"}:
        raise HTTPException(status_code=422, detail="Nieobsługiwany tryb profilu.")
    base_topic = payload.mqtt_base_topic.strip().strip("/")
    if not base_topic or "+" in base_topic or "#" in base_topic:
        raise HTTPException(status_code=422, detail="Base topic MQTT nie może być pusty ani zawierać znaków + lub #.")

    cfg_path = Path(CONFIG_PATH)
    cfg = _read_config()
    connection = ensure_mapping_section(cfg, "connection")
    connection.update({
        "type": payload.connection_type,
        "host": payload.host.strip() or "192.168.1.50",
        "port": payload.port,
        "serial_device": payload.serial_device.strip() or "/dev/ttyUSB0",
        "baudrate": payload.baudrate,
    })
    profile = ensure_mapping_section(cfg, "profile")
    profile.update({
        "mode": payload.profile_mode,
        "discovery_mode": "profile_entities",
        "include_parameters": True,
        "include_mixers": True,
        "include_statistics": False,
    })
    mqtt = ensure_mapping_section(cfg, "mqtt")
    current_password = str(mqtt.get("password") or "")
    mqtt.update({
        "enabled": payload.mqtt_enabled,
        "host": payload.mqtt_host.strip() or "127.0.0.1",
        "port": payload.mqtt_port,
        "username": payload.mqtt_username.strip(),
        "password": payload.mqtt_password or current_password,
        "base_topic": base_topic,
        "home_assistant_discovery": payload.mqtt_discovery,
        "commands_enabled": payload.mqtt_commands_enabled,
        "allow_advanced_commands": payload.mqtt_allow_advanced_commands,
        "allow_critical_commands": payload.mqtt_allow_critical_commands,
        "allow_power_commands": payload.mqtt_allow_power_commands,
    })
    save_config(cfg, cfg_path)
    return {"success": True, "message": "Zapisano. Uruchom ponownie usługę PlumBox."}


@router.get("/users")
async def users_get(request: Request) -> dict[str, Any]:
    require_admin_user(request)
    return {"users": list_users(USERS_PATH)}


@router.post("/users")
async def users_create(payload: UserCreate, request: Request) -> dict[str, Any]:
    require_admin_user(request)
    try:
        user = add_user(payload.username, payload.password, payload.role, payload.display_name, USERS_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "message": "Użytkownik dodany.", "user": user}


@router.put("/users/{username}/password")
async def users_password(username: str, payload: PasswordUpdate, request: Request) -> dict[str, Any]:
    require_admin_user(request)
    try:
        set_password(username, payload.password, USERS_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state.user_sessions.revoke_username(username)
    state.sessions.revoke_username(username)
    return {"success": True, "message": "Hasło zmienione."}


@router.delete("/users/{username}")
async def users_delete(username: str, request: Request) -> dict[str, Any]:
    require_admin_user(request)
    try:
        delete_user(username, USERS_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state.user_sessions.revoke_username(username)
    state.sessions.revoke_username(username)
    return {"success": True, "message": "Użytkownik usunięty."}


@router.get("/account")
async def account_get(request: Request) -> dict[str, Any]:
    return {"user": require_login_user(request)}


@router.put("/account/password")
async def account_password(payload: AccountPasswordUpdate, request: Request) -> JSONResponse:
    user = require_login_user(request)
    username = str(user.get("username", ""))
    if not verify_user_password(username, payload.old_password, USERS_PATH):
        raise HTTPException(status_code=422, detail="Obecne hasło jest nieprawidłowe.")
    if payload.new_password != payload.repeat_password:
        raise HTTPException(status_code=422, detail="Nowe hasła różnią się od siebie.")
    try:
        set_password(username, payload.new_password, USERS_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    state.user_sessions.revoke_username(username)
    state.sessions.revoke_username(username)
    token = state.user_sessions.create(user)
    response = JSONResponse({"success": True, "message": "Hasło zmienione."})
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=7 * 24 * 3600)
    return response
