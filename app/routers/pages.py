"""Strony i WebSocket: dashboard, logowanie, manifest, kanał live."""

from __future__ import annotations

import html
from urllib.parse import urlencode

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from ..deps import (
    SESSION_COOKIE,
    STATIC_DIR,
    INITIAL_ADMIN_PASSWORD_FILE,
    current_user_from_websocket,
    form_dict,
    state,
)
from ..users import USERS_PATH, authenticate

router = APIRouter()


def login_response(error: str | None = None, *, status_code: int = 200, headers: dict[str, str] | None = None) -> HTMLResponse:
    page = (STATIC_DIR / "login.html").read_text(encoding="utf-8")
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    return HTMLResponse(page.replace("{ERROR}", error_html), status_code=status_code, headers=headers)


def client_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}|{username.strip().lower()}"


@router.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/manifest.webmanifest", include_in_schema=False)
async def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest")


@router.get("/service-worker.js", include_in_schema=False)
async def service_worker() -> FileResponse:
    return FileResponse(STATIC_DIR / "service-worker.js", media_type="application/javascript")


@router.get("/login", include_in_schema=False)
async def login_page(error: str | None = None) -> HTMLResponse:
    return login_response(error)


@router.post("/login", include_in_schema=False)
async def login_submit(request: Request) -> Response:
    data = await form_dict(request)
    username = data.get("username", "")
    key = client_key(request, username)
    retry_after = state.login_attempts.retry_after(key)
    if retry_after:
        return login_response(
            f"Za dużo nieudanych prób. Spróbuj ponownie za {retry_after} s.",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    user = authenticate(username, data.get("password", ""), USERS_PATH)
    if not user:
        state.login_attempts.record_failure(key)
        return RedirectResponse(url="/login?" + urlencode({"error": "Nieprawidłowy login albo hasło"}), status_code=303)
    state.login_attempts.reset(key)
    token = state.user_sessions.create(user)
    if user.get("role") == "admin":
        try:
            INITIAL_ADMIN_PASSWORD_FILE.unlink(missing_ok=True)
        except OSError:
            pass
    response = RedirectResponse(url="./", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=7 * 24 * 3600)
    return response


@router.get("/logout", include_in_schema=False)
async def logout(request: Request) -> RedirectResponse:
    session_token = request.cookies.get(SESSION_COOKIE)
    user = state.user_sessions.get(session_token)
    state.user_sessions.revoke(session_token)
    if user:
        state.sessions.revoke_username(str(user.get("username", "")))
    response = RedirectResponse(url="login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    session_token = websocket.cookies.get(SESSION_COOKIE)
    if not session_token or not current_user_from_websocket(websocket):
        await websocket.close(code=1008)
        return
    await state.hub.connect(websocket, session_token)
    try:
        await websocket.send_json(state.service.snapshot)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await state.hub.disconnect(websocket)
