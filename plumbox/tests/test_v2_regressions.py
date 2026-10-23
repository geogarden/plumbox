from datetime import datetime, timedelta, timezone
import asyncio
import sqlite3

from app.database import Database
from app.deps import SESSION_COOKIE, state
from app.users import USERS_PATH, add_user, load_users


def test_v2_expired_login_is_distinct_from_pin(client):
    token = client.cookies.get(SESSION_COOKIE)
    state.user_sessions.sessions[token]["expires"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    response = client.get("/api/auth/status")
    assert response.status_code == 401
    assert response.json()["code"] == "auth_required"


def test_v2_status_checks_pin_identity(client):
    from app.security import Session
    state.sessions._sessions["other-account"] = Session(datetime.now(timezone.utc) + timedelta(hours=1), "other", "admin")
    result = client.get("/api/auth/status", headers={"X-Plumbox-Token": "other-account"}).json()
    assert result["role"] == "admin"
    assert result["unlocked"] is False
    assert result["expires_at"] is None


def test_v2_status_reports_expired_pin_without_expiring_login(client):
    token = client.post("/api/auth/unlock", json={"pin": "1234"}).json()["token"]
    state.sessions._sessions[token].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    response = client.get("/api/auth/status", headers={"X-Plumbox-Token": token})
    assert response.status_code == 200
    assert response.json()["unlocked"] is False


def test_v2_operator_cannot_bypass_power_permission(anon_client):
    if "v2operator" not in load_users(USERS_PATH)["users"]:
        add_user("v2operator", "testpassword123", "user", path=USERS_PATH)
    anon_client.post("/login", data={"username": "v2operator", "password": "testpassword123"})
    token = anon_client.post("/api/auth/unlock", json={"pin": "1234"}).json()["token"]
    response = anon_client.post("/api/set", headers={"X-Plumbox-Token": token}, json={"name": "ecomax_control", "value": False, "confirmed": True})
    assert response.status_code == 403


def test_v2_audit_records_actor(client):
    token = client.post("/api/auth/unlock", json={"pin": "1234"}).json()["token"]
    response = client.post("/api/set", headers={"X-Plumbox-Token": token}, json={"name": "heating_target_temp", "value": 69})
    assert response.status_code == 200
    audit = client.get("/api/audit").json()["rows"]
    assert audit[0]["actor"] == "admin"
    assert audit[0]["source"] == "api"


def test_v2_history_spans_requested_period(tmp_path):
    db = Database(str(tmp_path / "history.db"))
    db._initialize_sync()
    now = datetime.now(timezone.utc)
    times = [(now - timedelta(seconds=(20160-i)*30)).isoformat() for i in range(20160)]
    with db._connect() as connection:
        connection.executemany("INSERT INTO samples(ts,heating_temp,connected) VALUES (?,60,1)", [(t,) for t in times])
    for limit in [1,2,400,10000,20000]:
        rows = db._history_sync(168, limit)
        assert len(rows) <= limit
        assert rows[-1]["ts"] == times[-1]
        if limit > 1:
            assert (datetime.fromisoformat(rows[0]["ts"]) - datetime.fromisoformat(times[0])).total_seconds() <= 30
        assert "sample_rank" not in rows[0]


def test_v2_audit_migration_preserves_legacy_records(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE audit(id INTEGER PRIMARY KEY, ts TEXT, scope TEXT, device_index INTEGER, parameter TEXT, old_value TEXT, requested_value TEXT, success INTEGER, message TEXT)")
        connection.execute("INSERT INTO audit VALUES(1,'2026-09-01','ecomax',0,'test','1','2',1,'legacy')")
    db = Database(str(path))
    db._initialize_sync()
    db._initialize_sync()
    rows = db._audit_sync(100)
    assert len(rows) == 1 and rows[0]["message"] == "legacy"
    assert rows[0]["actor"] is None


def test_v2_top_lock_and_session_dialog_are_served(client):
    html = client.get("/").text
    assert 'id="topLockButton"' in html
    assert 'id="sessionExpiredDialog"' in html
