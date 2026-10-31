"""Wspólna konfiguracja testów: PlumBox w trybie symulacji, bez kotła.

Zmienne środowiskowe muszą być ustawione ZANIM zaimportujemy pakiet ``app`` —
``app.deps`` i ``app.users`` czytają ścieżki z env w czasie importu.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_WORK = Path(tempfile.mkdtemp(prefix="plumbox-tests-"))
_CFG = _WORK / "config.yaml"
_USERS = _WORK / "users.yaml"
_DB = _WORK / "plumbox.db"

_CFG.write_text(
    "connection:\n"
    "  type: simulation\n"
    "web:\n"
    "  title: PlumBox TEST\n"
    "security:\n"
    "  login_required: true\n"
    '  pin: "1234"\n'
    "history:\n"
    f"  database_path: {str(_DB).replace(os.sep, '/')}\n"
    "profile:\n"
    "  mode: fixed_ecomax860p4\n"
    "mqtt:\n"
    "  enabled: false\n",
    encoding="utf-8",
)

os.environ["PLUMBOX_CONFIG"] = str(_CFG)
os.environ["PLUMBOX_USERS"] = str(_USERS)
os.environ["PLUMBOX_INITIAL_ADMIN_PASSWORD_FILE"] = str(_WORK / "pw.txt")

ADMIN_PASSWORD = "testpass123"


@pytest.fixture(scope="session")
def _admin() -> None:
    from app.users import ensure_initial_admin

    ensure_initial_admin(_USERS, password=ADMIN_PASSWORD)


@pytest.fixture()
def anon_client(_admin):
    """Klient bez zalogowania (uruchamia lifespan → symulator startuje)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture()
def client(anon_client):
    """Klient zalogowany jako admin."""
    resp = anon_client.post(
        "/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return anon_client
