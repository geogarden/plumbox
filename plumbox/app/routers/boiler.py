"""API niezależnych statystyk cykli i ustawień powiadomień."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import uuid
import time
import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from ..boiler_monitor import DEFAULT_NOTIFICATIONS, notification_targets
from ..config import save_config
from ..deps import CONFIG_PATH, require_admin_user, state
from ..ha_notifications import valid_target

router = APIRouter(prefix="/api/boiler")


class NotificationSettings(BaseModel):
    enabled: bool = False
    target: str = Field(default="", max_length=128)
    targets: list[str] = Field(default_factory=list, max_length=20)
    start: bool = True
    extinguishing: bool = True
    finished: bool = True
    alarms: bool = True
    communication: bool = True
    communication_delay_seconds: int = Field(default=120, ge=30, le=1800)
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = Field(default="22:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    quiet_hours_end: str = Field(default="07:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    temperature_threshold: float | None = Field(default=None, gt=0, le=500, allow_inf_nan=False)
    threshold_hold_seconds: int = Field(default=10, ge=0, le=300)
    temperature_hysteresis: float = Field(default=3, gt=0, le=50, allow_inf_nan=False)


@router.get("/cycles")
async def cycles():
    result = state.monitor.tracker.summary()
    result["error"] = state.monitor.initialization_error
    result["simulation"] = bool(state.service.snapshot.get("simulation"))
    return result


@router.get("/notifications")
async def notifications(request: Request):
    require_admin_user(request)
    targets, error = [], ""
    try:
        targets = await state.monitor.client.targets()
    except Exception as exc:
        error = str(exc)
    return {
        "settings": state.monitor.settings, "targets": targets,
        "available": state.monitor.client.available, "error": error,
        "recent": await asyncio.to_thread(state.monitor.store.recent),
    }


@router.put("/notifications")
async def save_notifications(payload: NotificationSettings, request: Request):
    require_admin_user(request)
    selected = list(dict.fromkeys(payload.targets if "targets" in payload.model_fields_set else ([payload.target] if payload.target else [])))
    if any(not valid_target(target) for target in selected):
        raise HTTPException(status_code=422, detail="Nieprawidłowy odbiorca powiadomień.")
    if payload.enabled:
        if not selected:
            raise HTTPException(status_code=422, detail="Wybierz telefon.")
        try:
            targets = await state.monitor.client.targets()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if any(target not in targets for target in selected):
            raise HTTPException(status_code=422, detail="Ten telefon nie jest dostępny w Home Assistant.")
    path = Path(CONFIG_PATH)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    settings = payload.model_dump()
    settings["targets"] = selected
    settings["target"] = selected[0] if selected else ""
    cfg["notifications"] = settings
    await asyncio.to_thread(save_config, cfg, path)
    # Stare alarmy nie mogą zostać wysłane do nowo wybranego odbiorcy.
    await asyncio.to_thread(state.monitor.store.cancel_pending)
    previous = state.monitor.settings
    if settings["enabled"] and (not previous["enabled"] or set(notification_targets(previous)) != set(selected) or (settings["alarms"] and not previous["alarms"])):
        state.monitor.tracker.data["active_alerts"] = []
    state.monitor.unsaved_notifications.clear()
    state.monitor.settings = {**DEFAULT_NOTIFICATIONS, **settings}
    state.monitor.tracker.data["threshold_since"] = None
    state.monitor.tracker.data["threshold_notified"] = False
    return {"success": True, "message": "Zapisano ustawienia powiadomień. Restart nie jest wymagany."}


@router.post("/notifications/test")
async def test_notification(request: Request):
    require_admin_user(request)
    targets = notification_targets(state.monitor.settings)
    if not targets:
        raise HTTPException(status_code=422, detail="Najpierw wybierz i zapisz telefon.")
    last_test = getattr(state.monitor, "last_test", 0)
    if last_test and time.monotonic() - last_test < 30:
        raise HTTPException(status_code=429, detail="Odczekaj 30 sekund przed kolejnym testem.")
    state.monitor.last_test = time.monotonic()
    sent, failed = [], []
    event_id = "test-" + uuid.uuid4().hex
    for target in targets:
        try:
            await state.monitor.client.send(target, "Powiadomienie testowe z PlumBox.", event_id)
            sent.append(target)
        except Exception:
            failed.append(target)
    if failed:
        raise HTTPException(status_code=503, detail=f"HA przyjął test dla {len(sent)} z {len(targets)} telefonów. Błąd wysyłki: {', '.join(failed)}.")
    return {"success": True, "message": f"Home Assistant przyjął powiadomienie testowe dla {len(sent)} telefonów.", "sent": sent}
