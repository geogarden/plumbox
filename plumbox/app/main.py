"""Aplikacja FastAPI PlumBox: montaż, cykl życia, bramka logowania, routery.

Właściwe endpointy są w :mod:`app.routers` (pages/users/admin/api), współdzielony
stan i autoryzacja w :mod:`app.deps`, a strony administracyjne w
:mod:`app.admin_pages`. Tu zostaje tylko sklejenie całości.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import yaml
from pathlib import Path
from .boiler_monitor import BoilerMonitor, DEFAULT_NOTIFICATIONS
from .ha_notifications import HomeAssistantNotifications
from . import __version__
from .config import load_config
from .database import Database
from .deps import (
    CONFIG_PATH,
    INITIAL_ADMIN_PASSWORD_FILE,
    PUBLIC_PATHS,
    PUBLIC_PREFIXES,
    STATIC_DIR,
    WebSocketHub,
    current_user_from_request,
    snapshot_callback,
    state,
)
from .mqtt import MqttPublisher
from .plum_service import PlumService
from .routers import admin, api, native_admin, pages, users, boiler
from .security import AttemptLimiter, SessionManager
from .users import USERS_PATH, UserSessionStore, ensure_initial_admin

_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.config = load_config(CONFIG_PATH)

    logging.basicConfig(
        level=getattr(logging, state.config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    state.database = Database(
        state.config.history.database_path,
        retention_days=state.config.history.retention_days,
    )
    await state.database.initialize()
    state.sessions = SessionManager(state.config.security.session_hours)
    state.user_sessions = UserSessionStore(getattr(state.config.security, "login_session_hours", 24))
    state.login_attempts = AttemptLimiter(max_attempts=5, window_seconds=300)
    state.pin_attempts = AttemptLimiter(max_attempts=5, window_seconds=300)
    try:
        generated_password = ensure_initial_admin(USERS_PATH)
        if generated_password:
            INITIAL_ADMIN_PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
            INITIAL_ADMIN_PASSWORD_FILE.write_text(f"Login: admin\nHasło: {generated_password}\n", encoding="utf-8")
            INITIAL_ADMIN_PASSWORD_FILE.chmod(0o600)
    except Exception:
        _LOGGER.exception("Nie udało się przygotować konta administratora.")
    state.hub = WebSocketHub()
    state.mqtt = MqttPublisher(state.config.mqtt, state.config.profile)
    state.service = PlumService(state.config, state.database, snapshot_callback)
    state.mqtt.set_command_handlers(
        state.service.set_parameter,
        state.service.set_controller_power,
    )
    await state.mqtt.start()
    await state.service.start()

    try:
        raw_config = yaml.safe_load(Path(CONFIG_PATH).read_text(encoding="utf-8")) or {}
        raw_notifications = raw_config.get("notifications") or {}
        notification_settings = boiler.NotificationSettings.model_validate(raw_notifications).model_dump()
        if "targets" not in raw_notifications:
            notification_settings["targets"] = [raw_notifications["target"]] if raw_notifications.get("target") else []
    except Exception:
        _LOGGER.warning("Niepoprawne ustawienia powiadomień — wyłączono wysyłkę.")
        notification_settings = dict(DEFAULT_NOTIFICATIONS)
    state.monitor = BoilerMonitor(
        lambda: state.service.snapshot, state.config.history.database_path,
        notification_settings, HomeAssistantNotifications(), state.config.timezone,
    )
    try:
        await state.monitor.start()
    except Exception:
        state.monitor.initialization_error = "Moduł statystyk jest niedostępny. Sprawdź logi dodatku."
        _LOGGER.exception("Nie udało się uruchomić modułu cykli; silnik nadal działa.")

    cleanup_task = asyncio.create_task(periodic_cleanup(), name="plumbox-db-cleanup")
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await state.monitor.stop()
        except Exception:
            _LOGGER.exception("Nie udało się zapisać stanu statystyk.")
        await state.service.stop()
        await state.mqtt.stop()


async def periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(24 * 3600)
        try:
            await state.database.cleanup()
        except Exception:
            _LOGGER.exception("Nie udało się wyczyścić starej historii.")


app = FastAPI(
    title="PlumBox API",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


def relative_location(request_path: str, location: str) -> str:
    """Zamienia lokalny redirect na ścieżkę względną bez gubienia głębokości.

    Jest to potrzebne pod Home Assistant Ingress: bezwzględne ``/users``
    zgubiłoby prefiks Ingress, a samo ``users`` z żądania ``/users/delete``
    prowadziłoby błędnie do ``/users/users``.
    """
    parsed = urlsplit(location)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return location

    segments = [part for part in request_path.split("/") if part]
    base_depth = len(segments) if request_path.endswith("/") else max(0, len(segments) - 1)
    prefix = "../" * base_depth
    target = parsed.path.lstrip("/")
    if target:
        relative = prefix + target
        if request_path == "/":
            relative = "./" + relative
    else:
        relative = prefix or "./"
    if parsed.query:
        relative += "?" + parsed.query
    if parsed.fragment:
        relative += "#" + parsed.fragment
    return relative


def _no_store_for_html(response) -> None:
    """Strony HTML nie mogą trafiać do cache przeglądarki.

    Bez Cache-Control przeglądarka potrafiła odtworzyć dashboard z cache po
    wylogowaniu (powrót do zakładki pod HA Ingress pokazywał pusty panel
    zamiast strony logowania). Statyki w /assets/ mają wersjonowane adresy
    i celowo pozostają cache'owalne.
    """
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-store"


@app.middleware("http")
async def login_gate(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        response = await call_next(request)
        location = response.headers.get("location")
        if location and location.startswith("/") and not location.startswith("//"):
            response.headers["location"] = relative_location(path, location)
        _no_store_for_html(response)
        return response
    if path == "/favicon.ico":
        return await call_next(request)
    user = current_user_from_request(request)
    if not user:
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Zaloguj się do PlumBox.", "code": "auth_required"})
        return RedirectResponse(url=relative_location(path, "/login"), status_code=303)
    response = await call_next(request)
    location = response.headers.get("location")
    if location and location.startswith("/") and not location.startswith("//"):
        response.headers["location"] = relative_location(path, location)
    _no_store_for_html(response)
    return response


app.include_router(pages.router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(api.router)
app.include_router(native_admin.router)

app.include_router(boiler.router)
