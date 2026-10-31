import pytest

from app.config import SecurityConfig
from app.deps import state


@pytest.fixture
def open_panel(anon_client, monkeypatch):
    monkeypatch.setattr(state.config.security, "login_required", False)
    monkeypatch.setattr(state.config.security, "pin", "1234")
    monkeypatch.setattr(state.config.security, "pin_hash", None)
    # No configuration can silently bypass PIN for passwordless access.
    monkeypatch.setattr(state.config.security, "require_pin_for_all_writes", False)
    return anon_client


def test_panel_opens_without_password_and_keeps_pin_status(open_panel):
    assert SecurityConfig().login_required is False
    assert open_panel.get("/", follow_redirects=False).status_code == 200
    assert open_panel.get("/api/snapshot").status_code == 200
    assert open_panel.get("/api/boiler/cycles").status_code == 200
    public = open_panel.get("/api/config/public").json()
    assert public["login_required"] is False
    assert public["pin_required"] is True
    assert open_panel.get("/api/auth/status").json()["unlocked"] is False
    assert open_panel.get("/login", follow_redirects=False).status_code == 303


def test_writes_and_admin_still_need_valid_pin(open_panel):
    payload = {"name": "heating_target_temp", "value": 70}
    assert open_panel.post("/api/set", json=payload).status_code == 401
    assert open_panel.get("/api/native-admin/communication").status_code == 401
    assert open_panel.post("/api/auth/unlock", json={"pin": "9999"}).status_code == 401
    result = open_panel.post("/api/auth/unlock", json={"pin": "1234"})
    assert result.status_code == 200
    headers = {"X-Plumbox-Token": result.json()["token"]}
    assert open_panel.get("/api/auth/status", headers=headers).json()["unlocked"] is True
    assert open_panel.post("/api/set", json=payload, headers=headers).status_code == 200
    assert open_panel.get("/api/native-admin/communication", headers=headers).status_code == 200
    assert open_panel.post("/api/controller/power", json={"enabled": True, "confirmed": False}, headers=headers).status_code == 409
    open_panel.post("/api/auth/lock", headers=headers)
    assert open_panel.post("/api/set", json=payload, headers=headers).status_code == 401


def test_live_websocket_works_without_login_cookie(open_panel):
    with open_panel.websocket_connect("/ws") as socket:
        assert "connected" in socket.receive_json()
        open_panel.portal.call(state.hub.broadcast, {"connected": True, "probe": "passwordless"})
        assert socket.receive_json()["probe"] == "passwordless"
