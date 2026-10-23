from __future__ import annotations

import re
from pathlib import Path

import yaml


def _login(client, username: str, password: str) -> None:
    response = client.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    assert response.status_code == 303


def communication_payload(**overrides):
    payload = {
        "connection_type": "simulation",
        "host": "192.168.1.50",
        "port": 8899,
        "serial_device": "/dev/ttyUSB0",
        "baudrate": 115200,
        "profile_mode": "fixed_ecomax860p4",
        "mqtt_enabled": False,
        "mqtt_host": "127.0.0.1",
        "mqtt_port": 1883,
        "mqtt_username": "plum",
        "mqtt_password": "",
        "mqtt_base_topic": "plumbox",
        "mqtt_discovery": True,
        "mqtt_commands_enabled": True,
        "mqtt_allow_advanced_commands": True,
        "mqtt_allow_critical_commands": False,
        "mqtt_allow_power_commands": True,
    }
    payload.update(overrides)
    return payload


def test_native_admin_requires_login(anon_client):
    assert anon_client.get("/api/native-admin/communication").status_code == 401
    assert anon_client.get("/api/native-admin/users").status_code == 401
    assert anon_client.get("/api/native-admin/account").status_code == 401


def test_native_communication_is_sanitized_and_preserves_password(client):
    from app.deps import CONFIG_PATH

    first = client.put(
        "/api/native-admin/communication",
        json=communication_payload(mqtt_password="sekret-native-v3"),
    )
    assert first.status_code == 200
    page = client.get("/api/native-admin/communication")
    assert page.status_code == 200
    assert "sekret-native-v3" not in page.text
    assert page.json()["mqtt_password_configured"] is True

    second = client.put(
        "/api/native-admin/communication",
        json=communication_payload(mqtt_password=""),
    )
    assert second.status_code == 200
    cfg = yaml.safe_load(Path(CONFIG_PATH).read_text(encoding="utf-8"))
    assert cfg["mqtt"]["password"] == "sekret-native-v3"
    assert cfg["mqtt"]["commands_enabled"] is True
    assert cfg["mqtt"]["allow_advanced_commands"] is True
    assert cfg["mqtt"]["allow_critical_commands"] is False
    assert cfg["mqtt"]["allow_power_commands"] is True


def test_native_communication_validates_profile_and_topic(client):
    bad_profile = client.put(
        "/api/native-admin/communication",
        json=communication_payload(profile_mode="invented"),
    )
    assert bad_profile.status_code == 422
    bad_topic = client.put(
        "/api/native-admin/communication",
        json=communication_payload(mqtt_base_topic="plumbox/#"),
    )
    assert bad_topic.status_code == 422


def test_native_communication_repairs_null_yaml_sections(client):
    from app.deps import CONFIG_PATH

    config_path = Path(CONFIG_PATH)
    original = config_path.read_text(encoding="utf-8")
    try:
        config_path.write_text("connection:\nprofile:\nmqtt:\n", encoding="utf-8")
        response = client.put(
            "/api/native-admin/communication",
            json=communication_payload(host="192.168.0.195", mqtt_password="sekret-null"),
        )
        assert response.status_code == 200
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg["connection"]["host"] == "192.168.0.195"
        assert cfg["profile"]["mode"] == "fixed_ecomax860p4"
        assert cfg["mqtt"]["password"] == "sekret-null"
    finally:
        config_path.write_text(original, encoding="utf-8")


def test_legacy_communication_repairs_null_yaml_sections(client):
    from app.deps import CONFIG_PATH

    config_path = Path(CONFIG_PATH)
    original = config_path.read_text(encoding="utf-8")
    try:
        config_path.write_text("connection:\nprofile:\nmqtt:\n", encoding="utf-8")
        response = client.post(
            "/communication",
            data={
                "connection_type": "tcp",
                "host": "192.168.0.196",
                "port": "8899",
                "serial_device": "/dev/ttyUSB0",
                "baudrate": "115200",
                "profile_mode": "fixed_ecomax860p4",
                "mqtt_enabled": "1",
                "mqtt_host": "core-mosquitto",
                "mqtt_port": "1883",
                "mqtt_username": "plum",
                "mqtt_password": "sekret-legacy",
                "mqtt_base_topic": "plumbox",
                "mqtt_discovery": "1",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "message=" in response.headers["location"]
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg["connection"]["host"] == "192.168.0.196"
        assert cfg["profile"]["mode"] == "fixed_ecomax860p4"
        assert cfg["mqtt"]["password"] == "sekret-legacy"
    finally:
        config_path.write_text(original, encoding="utf-8")


def test_native_users_lifecycle(client):
    username = "native_v3_user"
    existing = client.get("/api/native-admin/users").json()["users"]
    if any(user["username"] == username for user in existing):
        assert client.delete(f"/api/native-admin/users/{username}").status_code == 200

    created = client.post(
        "/api/native-admin/users",
        json={"username": username, "display_name": "Native V3", "password": "nativepass123", "role": "user"},
    )
    assert created.status_code == 200
    assert any(user["username"] == username for user in client.get("/api/native-admin/users").json()["users"])
    changed = client.put(f"/api/native-admin/users/{username}/password", json={"password": "nativepass456"})
    assert changed.status_code == 200
    deleted = client.delete(f"/api/native-admin/users/{username}")
    assert deleted.status_code == 200


def test_native_account_password_keeps_current_session(anon_client):
    from app.users import USERS_PATH, add_user, delete_user, load_users

    username = "native_account_v3"
    if username in load_users(USERS_PATH)["users"]:
        delete_user(username, USERS_PATH)
    add_user(username, "oldnative123", "user", "Native Account", USERS_PATH)
    _login(anon_client, username, "oldnative123")
    assert anon_client.get("/api/native-admin/account").json()["user"]["username"] == username
    wrong = anon_client.put(
        "/api/native-admin/account/password",
        json={"old_password": "wrong", "new_password": "newnative123", "repeat_password": "newnative123"},
    )
    assert wrong.status_code == 422
    changed = anon_client.put(
        "/api/native-admin/account/password",
        json={"old_password": "oldnative123", "new_password": "newnative123", "repeat_password": "newnative123"},
    )
    assert changed.status_code == 200
    assert anon_client.get("/api/native-admin/account").status_code == 200
    delete_user(username, USERS_PATH)


def test_v3_frontend_uses_native_views_and_keeps_iframe_fallback():
    root = Path(__file__).parents[1]
    app_js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert "const USE_NATIVE_SYSTEM_V3 = true" in app_js
    assert "loadNativeSystemView(state.activeView)" in app_js
    assert "iframe class=\"embed-frame\"" in app_js
    assert index.index("plumbox_theme") < index.index("assets/styles.css")
    assert "V3 Native" in index
    assert "V3 TEST NATIVE" not in index


def test_v3_frontend_delegates_events_for_morphed_cards():
    app_js = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'content.dataset.eventsBound === "true"' in app_js
    assert 'content.addEventListener("click"' in app_js
    assert 'content.addEventListener("input"' in app_js
    assert 'content.addEventListener("change"' in app_js
    assert 'target.closest("[data-save-parameter]")' in app_js
    assert 'document.querySelectorAll("[data-save-parameter]").forEach' not in app_js
    assert "morphChildren(content, html)" in app_js


def test_every_parameter_data_trigger_is_handled_by_delegation():
    app_js = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    names = "step-parameter|save-parameter|switch-parameter|quick-parameter|open-view|history-hours|series-toggle"
    emitted = set(re.findall(rf"data-({names})=", app_js))
    handled = set(re.findall(r'closest\("\[data-([a-z-]+)\]"\)', app_js))
    assert emitted
    assert emitted <= handled, f"kontrolki bez obsługi: {sorted(emitted - handled)}"


def test_unlock_form_uses_enter_safe_submit_path():
    root = Path(__file__).parents[1]
    app_js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'type="button" id="unlockCancelButton"' in index
    assert '$("unlockCancelButton").addEventListener("click"' in app_js
    unlock_submit = app_js.split('$("unlockForm").addEventListener("submit"', 1)[1].split('$("confirmCheckbox")', 1)[0]
    assert "event.preventDefault()" in unlock_submit
    assert "event.submitter?.value" not in unlock_submit


def test_confirm_form_uses_symmetric_enter_safe_submit_path():
    root = Path(__file__).parents[1]
    app_js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'type="button" id="confirmCancelButton"' in index
    assert '$("confirmCancelButton").addEventListener("click"' in app_js
    confirm_submit = app_js.split('$("confirmForm").addEventListener("submit"', 1)[1].split('window.addEventListener("resize"', 1)[0]
    assert "event.preventDefault()" in confirm_submit
    assert "event.submitter?.value" not in confirm_submit
    assert '!$("confirmCheckbox").checked || !state.pendingWrite' in confirm_submit


def test_confirm_dialog_clears_pending_write_on_every_close_path():
    app_js = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "const resetConfirmState = () =>" in app_js
    assert "state.pendingWrite = null" in app_js
    assert '$("confirmCheckbox").checked = false' in app_js
    assert '$("confirmButton").disabled = true' in app_js
    assert '$("confirmDialog").addEventListener("close", resetConfirmState)' in app_js
    cancel_handler = app_js.split('$("confirmCancelButton").addEventListener("click"', 1)[1].split(
        '$("confirmDialog").addEventListener("close"', 1
    )[0]
    assert "resetConfirmState()" in cancel_handler


def test_mobile_sidebar_dismisses_on_pointer_outside():
    app_js = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'document.addEventListener("pointerdown"' in app_js
    assert 'sidebar.classList.contains("open")' in app_js
    assert "sidebar.contains(target)" in app_js
    assert 'sidebar.classList.remove("open")' in app_js
