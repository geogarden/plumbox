"""Współdzielony stan aplikacji, hub WebSocket i zależności logowania.

Wydzielone z ``main`` tak, aby routery mogły korzystać z tego samego singletona
``state`` i tych samych funkcji autoryzacji bez importów cyklicznych.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import HTTPException, Request, WebSocket

from .config import AppConfig
from .database import Database
from .mqtt import MqttPublisher
from .plum_service import PlumService
from .security import SessionManager

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
CONFIG_PATH = os.environ.get("PLUMBOX_CONFIG", "/etc/plumbox/config.yaml")
INITIAL_ADMIN_PASSWORD_FILE = Path(
    os.environ.get("PLUMBOX_INITIAL_ADMIN_PASSWORD_FILE", "/etc/plumbox/initial_admin_password.txt")
)
INITIAL_PIN_FILE = Path(os.environ.get("PLUMBOX_INITIAL_PIN_FILE", "/data/initial_pin.txt"))

# Service worker jest rejestrowany z korzenia aplikacji, aby zachował właściwy
# zakres także poza Home Assistant Ingress. Dlatego jest osobną trasą publiczną.
PUBLIC_PATHS = {"/login", "/api/health", "/manifest.webmanifest", "/service-worker.js"}
PUBLIC_PREFIXES = ("/assets/",)
SESSION_COOKIE = "plumbox_session"


class WebSocketHub:
    def __init__(self) -> None:
        self.clients: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_token: str) -> None:
        await websocket.accept()
        async with self._lock:
            self.clients[websocket] = session_token

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.clients.pop(websocket, None)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self.clients.items())

        failed: list[WebSocket] = []
        for client, session_token in clients:
            try:
                if passwordless_panel_user() is None and (not hasattr(state, "user_sessions") or not state.user_sessions.get(session_token)):
                    await client.close(code=1008)
                    failed.append(client)
                    continue
                # Jeden porzucony lub zawieszony klient Ingress nie może zatrzymać
                # pętli odczytu i publikowania snapshotów dla wszystkich pozostałych.
                await asyncio.wait_for(client.send_json(payload), timeout=2.0)
            except Exception:
                failed.append(client)

        if failed:
            async with self._lock:
                for client in failed:
                    self.clients.pop(client, None)


class AppState:
    config: AppConfig
    database: Database
    sessions: SessionManager
    hub: WebSocketHub
    service: PlumService
    mqtt: MqttPublisher
    user_sessions: Any  # UserSessionStore
    login_attempts: Any  # AttemptLimiter
    pin_attempts: Any  # AttemptLimiter


state = AppState()


async def snapshot_callback(snapshot: dict[str, Any]) -> None:
    await state.hub.broadcast(snapshot)
    await state.mqtt.publish(snapshot)


def passwordless_panel_user() -> dict[str, Any] | None:
    """Panel access is open; writes and administrative access still require PIN."""
    config = getattr(state, "config", None)
    security = getattr(config, "security", None)
    if security is None or getattr(security, "login_required", True):
        return None
    return {"username": "panel", "display_name": "Panel", "role": "admin", "enabled": True, "passwordless": True}


def current_user_from_request(request: Request) -> dict[str, Any] | None:
    if passwordless_panel_user() is not None:
        return passwordless_panel_user()
    return state.user_sessions.get(request.cookies.get(SESSION_COOKIE)) if hasattr(state, "user_sessions") else None


def current_user_from_websocket(websocket: WebSocket) -> dict[str, Any] | None:
    if passwordless_panel_user() is not None:
        return passwordless_panel_user()
    return state.user_sessions.get(websocket.cookies.get(SESSION_COOKIE)) if hasattr(state, "user_sessions") else None


def require_login_user(request: Request) -> dict[str, Any]:
    user = current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Zaloguj się do PlumBox.")
    return user


def require_admin_user(request: Request) -> dict[str, Any]:
    user = require_login_user(request)
    if user.get("passwordless"):
        return require_control_user(request, request.headers.get("X-Plumbox-Token"), roles={"admin"})
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Wymagane konto administratora.")
    return user


def require_control_user(
    request: Request,
    token: str | None,
    *,
    roles: set[str] | None = None,
) -> dict[str, Any]:
    """Sprawdź konto, rolę i (gdy skonfigurowano) token PIN tego samego konta."""
    user = require_login_user(request)
    allowed = roles or {"admin", "user"}
    if str(user.get("role")) not in allowed:
        raise HTTPException(status_code=403, detail="To konto ma dostęp tylko do odczytu.")

    if not user.get("passwordless") and not state.config.security.require_pin_for_all_writes:
        return user

    session = state.sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Odblokuj sterowanie kodem PIN.")
    if session.username != str(user.get("username")):
        raise HTTPException(status_code=403, detail="Token PIN należy do innego konta.")
    if session.role != str(user.get("role")):
        raise HTTPException(status_code=403, detail="Uprawnienia konta zmieniły się. Odblokuj ponownie.")
    return user


async def form_dict(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8", errors="ignore")
    return {key: values[0] if values else "" for key, values in parse_qs(raw).items()}
