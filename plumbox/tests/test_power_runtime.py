from datetime import datetime, timedelta, timezone
import asyncio

from app.database import Database


def test_power_runtime_uses_recorded_load_and_state_and_survives_restart(tmp_path):
    db = Database(str(tmp_path / "history.db"))
    asyncio.run(db.initialize())
    since = datetime(2026, 10, 24, tzinfo=timezone.utc)
    # One interval per recorded level, plus off, unknown, disconnected and a gap.
    for offset, load, state, connected in [
        (-30, 100, 3, True), (30, 50, 3, True), (90, 30, 3, True),
        (150, 100, 5, True), (210, 77, 3, True), (270, 100, 3, False),
        (330, 100, 3, True), (900, 50, 3, True),
    ]:
        asyncio.run(db.add_sample({"timestamp": (since + timedelta(seconds=offset)).isoformat(),
            "connected": connected, "values": {"boiler_load": load, "state": state}}))
    restarted = Database(str(db.path))
    result = asyncio.run(restarted.power_runtime(since, since + timedelta(seconds=930), max_age=60))
    assert result["seconds"] == {"100": 90, "50": 90, "30": 60}
    assert result["unknown_work_seconds"] == 60
    assert result["covered_seconds"] == 360


def test_empty_or_disconnected_history_does_not_invent_runtime(tmp_path):
    db = Database(str(tmp_path / "history.db"))
    asyncio.run(db.initialize())
    start = datetime(2026, 10, 24, tzinfo=timezone.utc)
    assert asyncio.run(db.power_runtime(start, start + timedelta(hours=48)))["seconds"] is None
    asyncio.run(db.add_sample({"timestamp": start.isoformat(), "connected": False,
                              "values": {"state": 3, "boiler_load": 100}}))
    assert asyncio.run(db.power_runtime(start, start + timedelta(hours=48)))["seconds"] is None


def test_runtime_covers_full_48_hours_without_chart_downsampling_limit(tmp_path):
    db = Database(str(tmp_path / "history.db"))
    asyncio.run(db.initialize())
    start = datetime(2026, 10, 24, tzinfo=timezone.utc)
    with db._connect() as sql:
        sql.executemany("INSERT INTO samples(ts,boiler_load,state,connected) VALUES(?,100,3,1)",
                        [((start + timedelta(seconds=i)).isoformat(),) for i in range(0, 48*3600, 5)])
    result = asyncio.run(db.power_runtime(start, start + timedelta(hours=48), max_age=10))
    assert result["seconds"] == {"100": 48*3600, "50": 0, "30": 0}
    assert result["covered_seconds"] == 48*3600
