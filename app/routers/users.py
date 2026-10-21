"""Zarządzanie użytkownikami (administrator) i własnym hasłem (każde konto)."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..admin_pages import render_account_page, render_users_page
from ..deps import SESSION_COOKIE, form_dict, require_admin_user, require_login_user, state
from ..users import USERS_PATH, add_user, delete_user, list_users, set_password, verify_user_password

router = APIRouter()


def users_location(**query: str) -> str:
    return "/users?" + urlencode(query)


@router.get("/users", include_in_schema=False)
async def users_page(request: Request, message: str | None = None, error: str | None = None) -> HTMLResponse:
    require_admin_user(request)
    return HTMLResponse(render_users_page(list_users(USERS_PATH), message, error))


@router.post("/users", include_in_schema=False)
async def users_add(request: Request) -> RedirectResponse:
    require_admin_user(request)
    data = await form_dict(request)
    try:
        add_user(data.get("username", ""), data.get("password", ""), data.get("role", "user"), data.get("display_name", ""), USERS_PATH)
        return RedirectResponse(url=users_location(message="Użytkownik dodany"), status_code=303)
    except Exception as exc:
        return RedirectResponse(url=users_location(error=str(exc)), status_code=303)


@router.post("/users/password", include_in_schema=False)
async def users_password(request: Request) -> RedirectResponse:
    require_admin_user(request)
    data = await form_dict(request)
    try:
        set_password(data.get("username", ""), data.get("password", ""), USERS_PATH)
        state.user_sessions.revoke_username(data.get("username", ""))
        state.sessions.revoke_username(data.get("username", ""))
        return RedirectResponse(url=users_location(message="Hasło zmienione"), status_code=303)
    except Exception as exc:
        return RedirectResponse(url=users_location(error=str(exc)), status_code=303)


@router.get("/account", include_in_schema=False)
async def account_page(request: Request, message: str | None = None, error: str | None = None) -> HTMLResponse:
    user = require_login_user(request)
    return HTMLResponse(render_account_page(user, message, error))


@router.post("/account", include_in_schema=False)
async def account_change_password(request: Request) -> RedirectResponse:
    user = require_login_user(request)
    username = str(user.get("username", ""))
    data = await form_dict(request)
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")
    repeat_password = data.get("repeat_password", "")

    def back(**query: str) -> RedirectResponse:
        return RedirectResponse(url="/account?" + urlencode(query), status_code=303)

    if not verify_user_password(username, old_password, USERS_PATH):
        return back(error="Obecne hasło jest nieprawidłowe.")
    if new_password != repeat_password:
        return back(error="Nowe hasła różnią się od siebie.")
    try:
        set_password(username, new_password, USERS_PATH)
    except ValueError as exc:
        return back(error=str(exc))

    # Unieważnij wszystkie dotychczasowe sesje tego konta (w tym ewentualne
    # cudze przeglądarki), ale utrzymaj bieżącą przez wystawienie nowej.
    state.user_sessions.revoke_username(username)
    state.sessions.revoke_username(username)
    token = state.user_sessions.create(user)
    response = back(message="Hasło zmienione.")
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=7 * 24 * 3600)
    return response


@router.post("/users/delete", include_in_schema=False)
async def users_delete(request: Request) -> RedirectResponse:
    require_admin_user(request)
    data = await form_dict(request)
    try:
        delete_user(data.get("username", ""), USERS_PATH)
        state.user_sessions.revoke_username(data.get("username", ""))
        state.sessions.revoke_username(data.get("username", ""))
        return RedirectResponse(url=users_location(message="Użytkownik usunięty"), status_code=303)
    except Exception as exc:
        return RedirectResponse(url=users_location(error=str(exc)), status_code=303)
