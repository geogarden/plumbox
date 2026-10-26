"""API JSON PlumBox: stan, katalog, profil, historia, sterowanie."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, StrictBool

from ..audit_context import audit_actor
from ..common import utc_now_iso
from ..deps import INITIAL_PIN_FILE, current_user_from_request, require_admin_user, require_control_user, state
from ..mappings import PARAMETER_META, SECTIONS, SENSOR_META
from ..security import verify_pin
from ..work_schedule import ScheduleConflict, validate_week

router = APIRouter(prefix="/api")


class UnlockRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=128)


class SetParameterRequest(BaseModel):
    scope: str = "ecomax"
    index: int = 0
    name: str
    value: Any
    confirmed: bool = False


class PowerRequest(BaseModel):
    enabled: bool
    confirmed: bool = False


class WorkScheduleRequest(BaseModel):
    week: list[list[StrictBool]]
    enabled: bool = Field(strict=True)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: bool = False


@router.get("/work-schedule")
async def work_schedule(refresh: bool = False) -> dict[str, Any]:
    return await state.service.work_schedule.read(force=refresh)


@router.put("/work-schedule")
async def save_work_schedule(
    payload: WorkScheduleRequest, request: Request,
    x_plumbox_token: str | None = Header(default=None),
) -> dict[str, Any]:
    user = require_control_user(request, x_plumbox_token, roles={"admin"})
    if not payload.confirmed:
        raise HTTPException(status_code=409, detail="Potwierdź zapis harmonogramu do sterownika.")
    try:
        validate_week(payload.week)
        with audit_actor(str(user.get("username"))):
            return await state.service.work_schedule.write(payload.week, payload.enabled, payload.revision)
    except ScheduleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, KeyError, AttributeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def risk_for(request: SetParameterRequest) -> str:
    key = f"{request.name}:mixer" if request.scope == "mixer" else request.name
    return str(PARAMETER_META.get(key, PARAMETER_META.get(request.name, {})).get("risk", "advanced"))


@router.get("/health")
async def health() -> dict[str, Any]:
    snapshot = state.service.snapshot
    return {
        "status": "ok",
        "connected": snapshot.get("connected", False),
        "simulation": snapshot.get("simulation", False),
        "time": utc_now_iso(),
        "transport": state.service.transport_health(),
    }


@router.get("/snapshot")
async def snapshot() -> dict[str, Any]:
    return state.service.snapshot


@router.get("/catalog")
async def catalog() -> dict[str, Any]:
    return {
        "sections": SECTIONS,
        "sensors": SENSOR_META,
        "parameter_meta": PARAMETER_META,
    }


@router.get("/profile")
async def controller_profile() -> dict[str, Any]:
    return state.service.snapshot.get("profile", {})


@router.get("/discovered")
async def discovered_entities() -> dict[str, Any]:
    profile = state.service.snapshot.get("profile", {})
    return {
        "mode": profile.get("mode"),
        "name": profile.get("name"),
        "counts": profile.get("counts", {}),
        "entities": profile.get("entities", []),
    }


@router.get("/config/public")
async def public_config() -> dict[str, Any]:
    return {
        "title": state.config.web.title,
        "connection_type": state.config.connection.type,
        "history_enabled": state.config.history.enabled,
        "mqtt_enabled": state.config.mqtt.enabled,
        "pin_required": state.config.security.require_pin_for_all_writes,
    }


@router.post("/auth/unlock")
async def unlock(payload: UnlockRequest, request: Request) -> dict[str, Any]:
    user = current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Zaloguj się do PlumBox.")
    if user.get("role") not in {"admin", "user"}:
        raise HTTPException(status_code=403, detail="To konto ma dostęp tylko do odczytu.")
    host = request.client.host if request.client else "unknown"
    attempt_key = f"{host}|{str(user.get('username', '')).lower()}"
    retry_after = state.pin_attempts.retry_after(attempt_key)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail=f"Za dużo nieudanych prób PIN. Spróbuj ponownie za {retry_after} s.",
            headers={"Retry-After": str(retry_after)},
        )
    security = state.config.security
    if not verify_pin(payload.pin, security.pin, security.pin_hash):
        state.pin_attempts.record_failure(attempt_key)
        raise HTTPException(status_code=401, detail="Nieprawidłowy PIN.")
    state.pin_attempts.reset(attempt_key)

    token, expires_at = state.sessions.create(user)
    try:
        INITIAL_PIN_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
    }


@router.post("/auth/lock")
async def lock(x_plumbox_token: str | None = Header(default=None)) -> dict[str, bool]:
    state.sessions.revoke(x_plumbox_token)
    return {"success": True}


@router.get("/auth/status")
async def auth_status(request: Request, x_plumbox_token: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Zaloguj się do PlumBox.")
    session = state.sessions.get(x_plumbox_token)
    unlocked = bool(session and session.username == str(user.get("username")) and session.role == str(user.get("role")))
    return {
        "unlocked": unlocked,
        "role": user.get("role", "readonly"),
        "expires_at": session.expires_at.isoformat() if unlocked else None,
    }


@router.post("/set")
async def set_parameter(
    payload: SetParameterRequest,
    request: Request,
    x_plumbox_token: str | None = Header(default=None),
) -> dict[str, Any]:
    user = require_control_user(request, x_plumbox_token, roles={"admin", "user"})
    risk = risk_for(payload)
    if payload.name == "ecomax_control" and str(user.get("role")) != "admin":
        raise HTTPException(status_code=403, detail="Zmiana stanu kotła wymaga konta administratora.")
    if risk != "safe":
        # Zapisy advanced/critical odblokowane decyzją użytkownika (2026-07-17):
        # security.safe_writes_only=false zdejmuje blokadę, ale wymaga konta
        # admin i jawnego potwierdzenia. Wartości idą do PyPlumIO natywnie,
        # bez własnych przeliczników — zakresy waliduje biblioteka/sterownik.
        if getattr(state.config.security, "safe_writes_only", True):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Ten parametr jest tylko do odczytu (security.safe_writes_only). "
                    "Zapisy advanced/critical można włączyć w konfiguracji."
                ),
            )
        if str(user.get("role")) != "admin":
            raise HTTPException(status_code=403, detail="Zapis advanced/critical wymaga konta administratora.")
        if not payload.confirmed:
            raise HTTPException(status_code=409, detail="Wymagane potwierdzenie zmiany serwisowej.")
    elif payload.name == "ecomax_control" and not payload.confirmed:
        # Włączenie/wyłączenie kotła jest formalnie risk=safe, ale przypadkowe
        # kliknięcie ma zbyt poważne skutki — wymagamy jawnego potwierdzenia.
        raise HTTPException(status_code=409, detail="Wymagane potwierdzenie zmiany stanu kotła.")

    try:
        with audit_actor(str(user.get("username"))):
            result = await state.service.set_parameter(
                payload.scope,
                payload.index,
                payload.name,
                payload.value,
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Brak parametru: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result


@router.post("/controller/power")
async def controller_power(
    payload: PowerRequest,
    request: Request,
    x_plumbox_token: str | None = Header(default=None),
) -> dict[str, Any]:
    user = require_control_user(request, x_plumbox_token, roles={"admin"})
    if not payload.confirmed:
        raise HTTPException(status_code=409, detail="Wymagane potwierdzenie.")
    try:
        with audit_actor(str(user.get("username"))):
            return await state.service.set_controller_power(payload.enabled)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/history")
async def history(
    hours: int = Query(default=24, ge=1, le=8760),
    limit: int = Query(default=5000, ge=1, le=20000),
) -> dict[str, Any]:
    return {"rows": await state.database.history(hours=hours, limit=limit)}


@router.get("/power-runtime")
async def power_runtime() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return await state.database.power_runtime(
        now - timedelta(hours=48), now,
        max_age=2 * state.config.history.sample_interval_seconds,
    )


@router.get("/summary")
async def summary() -> dict[str, Any]:
    """Podsumowanie wyliczane wyłącznie z zapisanych lokalnie pomiarów."""
    timezone_name = str(getattr(state.config, "timezone", "Europe/Warsaw"))
    try:
        local_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_zone = timezone.utc
        timezone_name = "UTC"

    now_utc = datetime.now(timezone.utc)
    local_midnight = now_utc.astimezone(local_zone).replace(hour=0, minute=0, second=0, microsecond=0)
    since_utc = local_midnight.astimezone(timezone.utc)
    fuel_today = await state.database.fuel_consumption_between(since_utc, now_utc)
    return {
        "fuel_today_kg": round(fuel_today, 3) if fuel_today is not None else None,
        "timezone": timezone_name,
        "since": since_utc.isoformat(),
    }


@router.get("/alarms")
async def alarms(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    return {"rows": await state.database.alarms(limit)}


@router.get("/audit")
async def audit(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    require_admin_user(request)
    return {"rows": await state.database.audit(limit)}

