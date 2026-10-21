from copy import deepcopy
from datetime import datetime, timedelta, timezone
import asyncio
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest
from app.boiler_monitor import CycleTracker, EventStore, BoilerMonitor, DEFAULT_NOTIFICATIONS
from app.ha_notifications import HomeAssistantNotifications, valid_target

T0 = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def snapshot(phase, seconds=0, connected=True, simulation=False, alerts=None, temperature=40):
    at = T0 + timedelta(seconds=seconds)
    return {
        "timestamp": at.isoformat(), "connected": connected, "simulation": simulation,
        "values": {"state": phase, "feeder_temp": temperature},
        "alerts": alerts or [], "service": {"last_frame_age_seconds": 0},
    }


def feed(tracker, phase, seconds=0, settings=None, **kwargs):
    at = T0 + timedelta(seconds=seconds)
    return tracker.evaluate(snapshot(phase, seconds, **kwargs), settings or DEFAULT_NOTIFICATIONS, at)


def test_full_cycle_includes_extinguishing_and_cleaning():
    tracker = CycleTracker(timezone_name="UTC")
    feed(tracker, 0)
    events, _ = feed(tracker, 2, 1)
    assert [e[0] for e in events] == ["start"]
    feed(tracker, 3, 2)
    events, _ = feed(tracker, 7, 3)
    assert [e[0] for e in events] == ["extinguishing"]
    assert tracker.summary(T0 + timedelta(seconds=3))["current"] is not None
    feed(tracker, 6, 4)
    assert tracker.data["current"] is not None
    events, _ = feed(tracker, 5, 5)
    result = tracker.summary(T0 + timedelta(seconds=5))
    assert result["current"] is None
    assert result["last"]["complete"]
    assert result["last"]["duration_seconds"] == 4
    assert result["last"]["observed_seconds"] == 4
    assert [e[0] for e in events] == ["finished"]


def test_off_state_closes_cycle_without_guessing_from_power_command():
    tracker = CycleTracker(timezone_name="UTC")
    feed(tracker, 0); feed(tracker, 2, 1); feed(tracker, 3, 2)
    feed(tracker, 0, 3)
    assert tracker.data["current"] is None
    assert tracker.data["history"][-1]["reason"] == "Wyłączenie kotła"


def test_first_observation_during_work_does_not_invent_ignition_time():
    tracker = CycleTracker()
    events, _ = feed(tracker, 3)
    assert not events
    assert tracker.data["current"]["started_at"] is None
    feed(tracker, 7, 1); feed(tracker, 5, 2)
    assert tracker.summary(T0 + timedelta(seconds=2))["last"]["duration_seconds"] is None
    assert not tracker.data["history"][-1]["complete"]


def test_repeated_ignition_and_extinguishing_do_not_spam():
    tracker = CycleTracker()
    feed(tracker, 0); feed(tracker, 2, 1)
    assert feed(tracker, 2, 2)[0] == []
    feed(tracker, 7, 3)
    assert feed(tracker, 7, 4)[0] == []
    feed(tracker, 3, 5)
    assert feed(tracker, 7, 6)[0] == []
    assert sum(tracker.data["starts_daily"].values()) == 1


def test_disconnected_time_is_not_counted():
    tracker = CycleTracker()
    feed(tracker, 0); feed(tracker, 2, 1); feed(tracker, 3, 2)
    feed(tracker, 3, 3, connected=False)
    feed(tracker, 3, 3600)
    assert tracker.data["current"]["observed_seconds"] == 1
    assert tracker.data["current"]["has_gap"]
    feed(tracker, 7, 3601); feed(tracker, 0, 3602)
    assert not tracker.data["history"][-1]["complete"]


def test_stale_frame_age_suspends_statistics():
    tracker = CycleTracker()
    feed(tracker, 0); feed(tracker, 2, 1)
    s = snapshot(3, 2); s["service"]["last_frame_age_seconds"] = 60
    tracker.evaluate(s, DEFAULT_NOTIFICATIONS, T0 + timedelta(seconds=2))
    assert tracker.data["last_at"] is None
    assert tracker.data["current"]["has_gap"]


def test_new_ignition_after_gap_does_not_merge_two_cycles():
    tracker = CycleTracker()
    feed(tracker, 0); feed(tracker, 2, 1); feed(tracker, 3, 2)
    feed(tracker, 0, 3, connected=False)
    feed(tracker, 2, 3600)
    assert tracker.data["history"][-1]["ended_at"] is None
    assert tracker.data["current"]["started_at"] is None


def test_daily_duration_is_split_at_midnight():
    tracker = CycleTracker(timezone_name="UTC")
    at = datetime(2026, 10, 31, 23, 59, 57, tzinfo=timezone.utc)
    for offset, phase in [(0,0),(1,2),(2,3),(3,7),(4,7),(5,0)]:
        s = snapshot(phase); s["timestamp"] = (at + timedelta(seconds=offset)).isoformat()
        tracker.evaluate(s, DEFAULT_NOTIFICATIONS, at + timedelta(seconds=offset))
    assert tracker.data["daily"]["2026-10-31"] == 2
    assert tracker.data["daily"]["2026-11-01"] == 2
    summary = tracker.summary(at + timedelta(seconds=5))
    assert summary["observed_month_seconds"] == 2


def test_simulation_never_generates_real_boiler_events():
    tracker = CycleTracker()
    assert feed(tracker, 2, simulation=True)[0] == []
    assert tracker.data["current"] is None
    assert feed(tracker, 8, 1, simulation=True, alerts=[{"code":4,"active":True,"name":"alarm"}])[0] == []


def test_alarm_is_sent_once_then_rearmed_after_clear():
    tracker = CycleTracker()
    alarm = {"code":4,"from":"2026-10-14T12:00:00Z","active":True,"name":"High temperature"}
    assert feed(tracker, 0, alerts=[alarm])[0][0][0] == "alarms"
    assert feed(tracker, 0, 1, alerts=[alarm])[0] == []
    feed(tracker, 0, 2)
    assert feed(tracker, 0, 3, alerts=[alarm])[0][0][0] == "alarms"


def test_alarm_is_available_even_without_a_valid_phase():
    tracker = CycleTracker()
    events, _ = feed(tracker, None, alerts=[{"code":4,"active":True,"name":"alarm"}])
    assert events[0][0] == "alarms"


def test_temperature_threshold_has_hold_and_hysteresis():
    tracker = CycleTracker()
    settings = {**DEFAULT_NOTIFICATIONS,"temperature_threshold":80,"threshold_hold_seconds":2}
    assert feed(tracker,0,0,settings,temperature=85)[0] == []
    assert feed(tracker,0,1,settings,temperature=85)[0] == []
    assert feed(tracker,0,2,settings,temperature=85)[0][0][0] == "temperature"
    assert feed(tracker,0,3,settings,temperature=85)[0] == []
    assert feed(tracker,0,4,settings,temperature=79)[0] == []
    feed(tracker,0,5,settings,temperature=76)
    feed(tracker,0,6,settings,temperature=85)
    assert feed(tracker,0,8,settings,temperature=85)[0][0][0] == "temperature"


def test_unknown_temperature_is_not_an_alarm():
    tracker = CycleTracker()
    settings = {**DEFAULT_NOTIFICATIONS,"temperature_threshold":80,"threshold_hold_seconds":0}
    assert feed(tracker,0,0,settings,temperature=float("nan"))[0] == []


def test_cycles_persist_without_rewriting_the_history_blob(tmp_path):
    tracker = CycleTracker()
    feed(tracker,0);feed(tracker,2,1);feed(tracker,7,2);feed(tracker,0,3)
    store = EventStore(tmp_path/"events.db");store.initialize()
    store.checkpoint(tracker.data)
    restored = EventStore(tmp_path/"events.db").initialize()
    assert restored["history"] == tracker.data["history"]
    with sqlite3.connect(tmp_path/"events.db") as db:
        assert '"history"' not in db.execute("SELECT payload FROM monitor_state").fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM cycles").fetchone()[0] == 1
    store.checkpoint(tracker.data)
    assert len(store.initialize()["history"]) == 1


def test_notification_outbox_deduplicates_and_limits_retries(tmp_path):
    store = EventStore(tmp_path/"events.db");store.initialize()
    notification = ("unique",datetime.now(timezone.utc).isoformat(),"start","msg","mobile_app_phone","pending")
    store.checkpoint({},[notification,notification])
    assert len(store.pending(0)) == 1
    store.result("unique",False,"offline",0)
    assert store.pending(1) == []
    assert len(store.pending(60)) == 1
    store.result("unique",False,"offline",60)
    store.result("unique",False,"offline",180)
    assert store.pending(10000) == []
    assert store.recent()[0]["status"] == "failed"


def test_restart_retains_cycle_but_marks_gap(tmp_path):
    tracker = CycleTracker();feed(tracker,0);feed(tracker,2,1);feed(tracker,3,2)
    store = EventStore(tmp_path/"events.db");store.initialize();store.checkpoint(tracker.data)
    again = CycleTracker(store.initialize());again.disconnect()
    feed(again,3,100)
    assert again.data["current"]["started_at"] == tracker.data["current"]["started_at"]
    assert again.data["current"]["observed_seconds"] == 1
    assert again.data["current"]["has_gap"]


def test_mobile_target_validation_prevents_arbitrary_service_calls():
    assert valid_target("mobile_app_iphone")
    for name in ["persistent_notification.create","light.turn_on","../notify/x","mobile_app_../x",""]:
        assert not valid_target(name)


def test_ha_proxy_uses_runtime_token_and_stable_tag(monkeypatch):
    import urllib.request
    sent = []
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return b"[]"
    def fake(request,timeout):
        sent.append(request)
        assert timeout == 5
        return Response()
    monkeypatch.setenv("SUPERVISOR_TOKEN","fake-token")
    monkeypatch.setattr(urllib.request,"urlopen",fake)
    asyncio.run(HomeAssistantNotifications().send("mobile_app_phone","hello","event"))
    request = sent[0]
    assert request.full_url == "http://supervisor/core/api/services/notify/mobile_app_phone"
    assert request.get_header("Authorization") == "Bearer fake-token"
    assert b"plumbox-event" in request.data


@pytest.fixture
def notifications_client(client, monkeypatch):
    from app.deps import state, CONFIG_PATH
    original = Path(CONFIG_PATH).read_bytes()
    sent = []
    class Client:
        available = True
        async def targets(self):return ["mobile_app_phone"]
        async def send(self,*args):sent.append(args)
    monkeypatch.setattr(state.monitor,"client",Client())
    try:yield client,sent
    finally:Path(CONFIG_PATH).write_bytes(original)


def test_notifications_require_admin(anon_client):
    from app.users import USERS_PATH,load_users,add_user
    if "notifyreader" not in load_users(USERS_PATH)["users"]:
        add_user("notifyreader","testpassword123","readonly",path=USERS_PATH)
    anon_client.post("/login",data={"username":"notifyreader","password":"testpassword123"})
    assert anon_client.get("/api/boiler/cycles").status_code == 200
    assert anon_client.get("/api/boiler/notifications").status_code == 403
    assert anon_client.put("/api/boiler/notifications",json={}).status_code == 403
    assert anon_client.post("/api/boiler/notifications/test").status_code == 403


def test_notification_settings_and_manual_test(notifications_client):
    client,sent = notifications_client
    response = client.put("/api/boiler/notifications",json={"enabled":True,"target":"mobile_app_phone","temperature_threshold":80})
    assert response.status_code == 200
    settings = client.get("/api/boiler/notifications").json()["settings"]
    assert settings["enabled"] and settings["temperature_threshold"] == 80
    assert client.post("/api/boiler/notifications/test").status_code == 200
    assert len(sent) == 1 and sent[0][0] == "mobile_app_phone"
    assert client.post("/api/boiler/notifications/test").status_code == 429
    assert len(sent) == 1


def test_enabling_notifications_requires_a_real_target(notifications_client):
    client,_ = notifications_client
    assert client.put("/api/boiler/notifications",json={"enabled":True}).status_code == 422
    assert client.put("/api/boiler/notifications",json={"enabled":True,"target":"mobile_app_unknown"}).status_code == 422
    assert client.put("/api/boiler/notifications",json={"temperature_threshold":"inf"}).status_code in {400,422}


def test_cycles_endpoint_and_qr_removal(client):
    response = client.get("/api/boiler/cycles")
    assert response.status_code == 200
    assert {"current","last","observed_today_seconds","starts_today","cycles"} <= response.json().keys()
    script = client.get("/assets/app.js").text
    assert 'class="qr-box"' not in script
    assert 'class="card remote-card"' in script
    html = client.get("/").text
    assert 'data-view="statistics"' in html
    assert 'data-view="notifications"' in html
    assert "boiler_views.js" in html


def test_pending_delivery_is_separate_from_snapshot_processing(tmp_path):
    class Client:
        async def send(self,*args):raise RuntimeError("offline")
    s = snapshot(0)
    monitor = BoilerMonitor(lambda:s,tmp_path/"plumbox.db",{**DEFAULT_NOTIFICATIONS,"enabled":True,"target":"mobile_app_phone"},Client())
    monitor.store.initialize()
    store_event=("event",datetime.now(timezone.utc).isoformat(),"alarms","msg","mobile_app_phone","pending")
    monitor.store.checkpoint(monitor.tracker.data,[store_event])
    asyncio.run(monitor.deliver_once())
    assert monitor.store.recent()[0]["status"] == "pending"
    assert monitor.store.recent()[0]["error"] == "offline"


def test_temperature_alert_does_not_depend_on_phase_code():
    tracker = CycleTracker()
    settings = {**DEFAULT_NOTIFICATIONS,"temperature_threshold":80,"threshold_hold_seconds":2}
    assert feed(tracker,None,0,settings,temperature=85)[0] == []
    assert feed(tracker,None,2,settings,temperature=85)[0][0][0] == "temperature"


def test_database_error_does_not_drop_a_notification(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    s = snapshot(2);s["timestamp"] = now.isoformat()
    monitor = BoilerMonitor(lambda:s,tmp_path/"db.db",{**DEFAULT_NOTIFICATIONS,"enabled":True,"target":"mobile_app_phone"},SimpleNamespace())
    monitor.store.initialize()
    monitor.tracker.data["phase"] = 0
    monitor.tracker.data["last_at"] = (now-timedelta(seconds=1)).isoformat()
    real = monitor.store.checkpoint
    calls = []
    def fail_once(*args):
        calls.append(1)
        if len(calls) == 1:raise OSError("temporary failure")
        return real(*args)
    monkeypatch.setattr(monitor.store,"checkpoint",fail_once)
    with pytest.raises(OSError):asyncio.run(monitor.tick())
    assert len(monitor.unsaved_notifications) == 1
    asyncio.run(monitor.tick())
    assert monitor.unsaved_notifications == []
    assert len(monitor.store.pending(0)) == 1


def test_new_alarm_is_not_lost_on_unchanged_snapshot_timestamp():
    tracker = CycleTracker()
    feed(tracker,0)
    events,_ = feed(tracker,0,alerts=[{"code":4,"active":True,"name":"alarm"}])
    assert events[0][0] == "alarms"


def test_backward_clock_marks_cycle_incomplete():
    tracker = CycleTracker()
    feed(tracker,0);feed(tracker,2,1);feed(tracker,3,2)
    feed(tracker,3,1)
    assert tracker.data["current"]["has_gap"]
    assert tracker.data["current"]["observed_seconds"] == 1


def test_multiple_phones_save_deduplicate_and_manual_test(notifications_client, monkeypatch):
    from app.deps import state
    client, sent = notifications_client
    async def targets(): return ["mobile_app_phone", "mobile_app_second"]
    monkeypatch.setattr(state.monitor.client, "targets", targets)
    response = client.put("/api/boiler/notifications", json={"enabled":True,"targets":["mobile_app_phone","mobile_app_second","mobile_app_phone"]})
    assert response.status_code == 200
    assert client.get("/api/boiler/notifications").json()["settings"]["targets"] == ["mobile_app_phone", "mobile_app_second"]
    assert client.post("/api/boiler/notifications/test").status_code == 200
    assert [x[0] for x in sent] == ["mobile_app_phone", "mobile_app_second"]


def test_multiple_phones_reject_invalid_and_unavailable_targets(notifications_client):
    client,_ = notifications_client
    for selected in [["mobile_app_phone", "mobile_app_unknown"], ["mobile_app_phone", "persistent_notification"], ["mobile_app_phone"]*21]:
        assert client.put("/api/boiler/notifications", json={"enabled":True,"targets":selected}).status_code == 422


def test_explicit_empty_targets_remove_legacy_recipient(notifications_client):
    client,_ = notifications_client
    assert client.put("/api/boiler/notifications",json={"enabled":True,"target":"mobile_app_phone"}).status_code == 200
    assert client.put("/api/boiler/notifications",json={"enabled":False,"targets":[]}).status_code == 200
    settings=client.get("/api/boiler/notifications").json()["settings"]
    assert settings["targets"] == [] and settings["target"] == ""
    assert client.post("/api/boiler/notifications/test").status_code == 422


def test_test_failure_on_one_phone_does_not_skip_another(notifications_client, monkeypatch):
    from app.deps import state
    client,_=notifications_client
    attempted=[]
    async def targets():return ["mobile_app_phone","mobile_app_second"]
    async def send(target,*args):
        attempted.append(target)
        if target == "mobile_app_phone":raise RuntimeError("private credential must not escape")
    monkeypatch.setattr(state.monitor.client,"targets",targets)
    monkeypatch.setattr(state.monitor.client,"send",send)
    assert client.put("/api/boiler/notifications",json={"enabled":True,"targets":["mobile_app_phone","mobile_app_second"]}).status_code == 200
    result=client.post("/api/boiler/notifications/test")
    assert result.status_code == 503 and "1 z 2" in result.json()["detail"]
    assert "private credential" not in result.text
    assert attempted == ["mobile_app_phone","mobile_app_second"]


def test_legacy_phone_migrates_and_fanout_retries_only_failed_recipient(tmp_path):
    s=snapshot(0);attempted=[]
    class Client:
        async def send(self,target,*args):
            attempted.append(target)
            if target == "mobile_app_second":raise RuntimeError("offline")
    legacy=BoilerMonitor(lambda:s,tmp_path/"legacy.db",{"target":"mobile_app_phone"},Client())
    assert legacy.settings["targets"] == ["mobile_app_phone"]
    monitor=BoilerMonitor(lambda:s,tmp_path/"multi.db",{"enabled":True,"targets":["mobile_app_phone","mobile_app_second"]},Client())
    monitor.store.initialize()
    monitor.tracker.evaluate=lambda *args:([("start","unique-event","Start")],True)
    async def exercise():
        await monitor.tick()
        queued=monitor.store.pending(10**12)
        assert len(queued)==2 and len({x["id"] for x in queued})==2
        await monitor.deliver_once()
        await monitor.deliver_once()
        assert attempted == ["mobile_app_phone","mobile_app_second"]
        with monitor.store.connect() as db:db.execute("UPDATE notification_log SET next_attempt=0 WHERE status='pending'")
        await monitor.deliver_once()
        assert attempted == ["mobile_app_phone","mobile_app_second","mobile_app_second"]
    # Use current time so delivery-age guard does not discard the fixture.
    s["timestamp"]=datetime.now(timezone.utc).isoformat()
    asyncio.run(exercise())


def test_communication_delay_short_outage_loss_once_and_recovery():
    from app.boiler_monitor import communication_events
    data={};settings={**DEFAULT_NOTIFICATIONS,"enabled":True,"communication_delay_seconds":120}
    assert communication_events(data,snapshot(3),settings,T0)[0] == []
    assert communication_events(data,snapshot(3,1,connected=False),settings,T0+timedelta(seconds=1))[0] == []
    assert communication_events(data,snapshot(3,20),settings,T0+timedelta(seconds=20))[0] == []
    communication_events(data,snapshot(3,21,connected=False),settings,T0+timedelta(seconds=21))
    lost,_=communication_events(data,snapshot(3,141,connected=False),settings,T0+timedelta(seconds=141))
    assert len(lost)==1 and lost[0][1].endswith(":lost")
    assert communication_events(data,snapshot(3,150,connected=False),settings,T0+timedelta(seconds=150))[0] == []
    # Persisted outage continues without repeating the loss after restart.
    data=deepcopy(data)
    recovered,_=communication_events(data,snapshot(3,160),settings,T0+timedelta(seconds=160))
    assert len(recovered)==1 and recovered[0][1].endswith(":restored")
    assert communication_events(data,snapshot(3,161),settings,T0+timedelta(seconds=161))[0] == []


def test_stale_connected_data_is_a_communication_outage():
    from app.boiler_monitor import communication_events
    data={};settings={**DEFAULT_NOTIFICATIONS,"enabled":True,"communication_delay_seconds":30}
    communication_events(data,snapshot(3),settings,T0+timedelta(seconds=20))
    assert len(communication_events(data,snapshot(3),settings,T0+timedelta(seconds=50))[0])==1


def test_simulation_and_disabled_notifications_do_not_alert_connection():
    from app.boiler_monitor import communication_events
    for settings,sim in [({**DEFAULT_NOTIFICATIONS,"enabled":False},False),({**DEFAULT_NOTIFICATIONS,"enabled":True},True)]:
        data={}
        for seconds in [0,1000]:
            assert communication_events(data,snapshot(3,seconds,connected=False,simulation=sim),settings,T0+timedelta(seconds=seconds))[0] == []


@pytest.mark.parametrize("clock,expected",[("21:59",False),("22:00",True),("23:59",True),("00:00",True),("06:59",True),("07:00",False)])
def test_quiet_hours_across_midnight(clock,expected):
    from app.boiler_monitor import quiet_hours
    at=datetime.fromisoformat("2026-10-14T"+clock+":00+00:00")
    settings={"quiet_hours_enabled":True,"quiet_hours_start":"22:00","quiet_hours_end":"07:00"}
    assert quiet_hours(settings,at,timezone.utc) is expected


def test_quiet_hours_local_timezone_and_same_day_window():
    from app.boiler_monitor import quiet_hours
    settings={"quiet_hours_enabled":True,"quiet_hours_start":"10:00","quiet_hours_end":"12:00"}
    assert quiet_hours(settings,T0-timedelta(hours=4),timezone(timedelta(hours=2)))
    assert not quiet_hours(settings,T0,timezone.utc)
    assert not quiet_hours({**settings,"quiet_hours_start":"10:00","quiet_hours_end":"10:00"},T0,timezone.utc)


def test_quiet_hours_skip_cycle_but_keep_alarms_and_communication(tmp_path,monkeypatch):
    from app import boiler_monitor
    now=datetime.now(timezone.utc);s=snapshot(3);s["timestamp"]=now.isoformat()
    monitor=BoilerMonitor(lambda:s,tmp_path/"quiet.db",{"enabled":True,"targets":["mobile_app_phone"],"quiet_hours_enabled":True},SimpleNamespace())
    monitor.store.initialize()
    monitor.tracker.evaluate=lambda *args:([("start","start-id","Start"),("alarms","alarm-id","Alarm"),("temperature","temp-id","Temperature"),("communication","lost-id","Connection")],True)
    monkeypatch.setattr(boiler_monitor,"quiet_hours",lambda *args:True)
    asyncio.run(monitor.tick())
    assert {e["kind"] for e in monitor.store.pending(now.timestamp()+1)} == {"alarms","temperature","communication"}


def test_quiet_hours_settings_validation(notifications_client):
    client,_=notifications_client
    for invalid in [{"quiet_hours_start":"25:00"},{"quiet_hours_end":"7:00"},{"communication_delay_seconds":0}]:
        assert client.put("/api/boiler/notifications",json=invalid).status_code==422
