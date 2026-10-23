"""Smoke testy PlumBox w trybie symulacji.

Sprawdzają, że aplikacja wstaje, bramka logowania działa, dashboard i statyki się
serwują, a API zwraca dane w oczekiwanym kształcie — w tym reguły zapisu
(safe → 200, advanced → 403). Nie wymagają fizycznego kotła.
"""

from __future__ import annotations

PARAM_KEYS = {
    "name", "scope", "index", "label", "section", "risk", "access", "kind", "value",
    "native_value", "min", "max", "step", "unit", "options", "selected_label",
    "on_label", "off_label", "on_action_label", "off_action_label", "writable",
    "special_zero",
}


# --- bramka logowania -------------------------------------------------------

def test_dashboard_redirects_when_anonymous(anon_client):
    resp = anon_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "./login"


def test_api_requires_login(anon_client):
    assert anon_client.get("/api/snapshot").status_code == 401


def test_login_page_public(anon_client):
    assert anon_client.get("/login").status_code == 200


def test_health_is_public(anon_client):
    resp = anon_client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- dashboard i statyki ----------------------------------------------------

def test_dashboard_and_assets_served(client):
    assert client.get("/").status_code == 200
    for path in (
        "/assets/app.js",
        "/assets/styles.css",
        "/assets/icon.svg",
        "/assets/service-worker.js",
        "/manifest.webmanifest",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert len(resp.content) > 0, path


# --- API danych -------------------------------------------------------------

def test_catalog_shape(client):
    data = client.get("/api/catalog").json()
    assert {"sections", "sensors", "parameter_meta"} <= data.keys()
    assert any(s["id"] == "heating" for s in data["sections"])


def test_snapshot_shape(client):
    snap = client.get("/api/snapshot").json()
    assert snap["simulation"] is True
    assert snap["connected"] is True
    assert "heating_temp" in snap["values"]
    # Payload parametru ma pełny, wspólny kształt.
    param = snap["parameters"]["heating_target_temp"]
    assert set(param.keys()) == PARAM_KEYS
    assert param["risk"] == "safe"


def test_profile_fixed_mode(client):
    prof = client.get("/api/profile").json()
    assert prof["mode"] == "fixed_ecomax860p4"
    assert prof["counts"]["defined"] >= prof["counts"]["available"] >= 1


# --- sterowanie: reguły zapisu ---------------------------------------------

def _unlock(client) -> dict[str, str]:
    resp = client.post("/api/auth/unlock", json={"pin": "1234"})
    assert resp.status_code == 200
    return {"X-PlumBox-Token": resp.json()["token"]}


def test_unlock_bad_pin_rejected(client):
    assert client.post("/api/auth/unlock", json={"pin": "0000"}).status_code == 401


def test_set_safe_parameter_succeeds(client):
    hdr = _unlock(client)
    resp = client.post(
        "/api/set",
        json={"scope": "ecomax", "name": "heating_target_temp", "value": 70},
        headers=hdr,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_set_advanced_parameter_blocked(client):
    hdr = _unlock(client)
    resp = client.post(
        "/api/set",
        json={"scope": "ecomax", "name": "boiler_power_100", "value": 12},
        headers=hdr,
    )
    assert resp.status_code == 403


def test_set_requires_unlock(client):
    resp = client.post(
        "/api/set",
        json={"scope": "ecomax", "name": "heating_target_temp", "value": 70},
    )
    assert resp.status_code == 401


# --- strony administracyjne -------------------------------------------------

def test_admin_pages_render(client):
    users = client.get("/users")
    assert users.status_code == 200
    assert "Użytkownicy PlumBox" in users.text
    comm = client.get("/communication")
    assert comm.status_code == 200
    assert "Komunikacja i MQTT" in comm.text
