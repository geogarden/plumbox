import asyncio
from datetime import datetime, timedelta, timezone
import sqlite3

from app.database import Database


def test_fuel_history_migration_preserves_old_rows_and_records_zero(tmp_path):
    path = tmp_path / 'old.db'
    timestamp = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    with sqlite3.connect(path) as sql:
        sql.execute('''CREATE TABLE samples (ts TEXT PRIMARY KEY, heating_temp REAL,
            return_temp REAL, water_heater_temp REAL, feeder_temp REAL, mixer_temp REAL,
            boiler_power REAL, boiler_load REAL, fan_power REAL, fuel_consumption REAL,
            state INTEGER, connected INTEGER)''')
        sql.execute('INSERT INTO samples(ts,heating_temp,feeder_temp,connected) VALUES(?,67,30,1)', (timestamp,))
    db = Database(str(path))
    asyncio.run(db.initialize())
    asyncio.run(db.initialize())
    asyncio.run(db.add_sample({'timestamp': datetime.now(timezone.utc).isoformat(),
        'connected': True, 'values': {'fuel_level': 0, 'boiler_load': 50, 'fan_power': 33},
        'mixers': {'0': {'values': {'current_temp': 38.6}}}}))
    rows = asyncio.run(db.history(hours=24, limit=3000))
    assert len(rows) == 2
    assert rows[0]['ts'] == timestamp and rows[0]['heating_temp'] == 67
    assert rows[0]['fuel_level'] is None
    assert rows[1]['fuel_level'] == 0
    assert rows[1]['mixer_temp'] == 38.6 and rows[1]['fan_power'] == 33
