"""Lokalna historia SQLite."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
from .audit_context import current_audit_actor
from typing import Any


def integer_or_none(value: Any) -> int | None:
    """Normalizuje kod stanu do SQLite bez zgadywania znaczenia kodu."""
    if isinstance(value, dict):
        value = value.get("value")
    elif hasattr(value, "value"):
        value = getattr(value, "value")
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


class Database:
    def __init__(self, path: str, retention_days: int = 365) -> None:
        self.path = Path(path)
        self.retention_days = max(1, retention_days)

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize_sync(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS samples (
                    ts TEXT PRIMARY KEY,
                    heating_temp REAL,
                    return_temp REAL,
                    water_heater_temp REAL,
                    feeder_temp REAL,
                    mixer_temp REAL,
                    boiler_power REAL,
                    boiler_load REAL,
                    fan_power REAL,
                    fuel_consumption REAL,
                    state INTEGER,
                    connected INTEGER
                );

                CREATE TABLE IF NOT EXISTS alarms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signature TEXT UNIQUE,
                    code INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    active INTEGER NOT NULL,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    device_index INTEGER NOT NULL,
                    parameter TEXT NOT NULL,
                    old_value TEXT,
                    requested_value TEXT,
                    success INTEGER NOT NULL,
                    message TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);
                CREATE INDEX IF NOT EXISTS idx_alarms_started ON alarms(started_at);
                CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
                """
            )

            # Migracja zachowuje dotychczasowe wpisy audytu.
            columns = {row[1] for row in db.execute("PRAGMA table_info(audit)")}
            if "actor" not in columns:
                db.execute("ALTER TABLE audit ADD COLUMN actor TEXT")
            if "source" not in columns:
                db.execute("ALTER TABLE audit ADD COLUMN source TEXT")

    async def add_sample(self, snapshot: dict[str, Any]) -> None:
        await asyncio.to_thread(self._add_sample_sync, snapshot)

    def _add_sample_sync(self, snapshot: dict[str, Any]) -> None:
        values = snapshot.get("values", {})
        mixer = snapshot.get("mixers", {}).get("0", {})
        mixer_values = mixer.get("values", {})
        ts = snapshot.get("timestamp") or datetime.now(timezone.utc).isoformat()

        with self._connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO samples (
                    ts, heating_temp, return_temp, water_heater_temp,
                    feeder_temp, mixer_temp, boiler_power, boiler_load,
                    fan_power, fuel_consumption, state, connected
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    values.get("heating_temp"),
                    values.get("return_temp"),
                    values.get("water_heater_temp"),
                    values.get("feeder_temp"),
                    mixer_values.get("current_temp"),
                    values.get("boiler_power"),
                    values.get("boiler_load"),
                    values.get("fan_power"),
                    values.get("fuel_consumption"),
                    integer_or_none(values.get("state")),
                    int(bool(snapshot.get("connected"))),
                ),
            )

    async def add_alarm(self, alarm: dict[str, Any]) -> None:
        await asyncio.to_thread(self._add_alarm_sync, alarm)

    def _add_alarm_sync(self, alarm: dict[str, Any]) -> None:
        # `code|from` identyfikuje wystąpienie alarmu; bez `to`, żeby zakończenie
        # alarmu aktualizowało istniejący rekord (upsert niżej), a nie tworzyło
        # duplikatu. Ponowne wywołanie wyzwala pamięciowa sygnatura w PlumService.
        signature = f"{alarm.get('code')}|{alarm.get('from')}"
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO alarms (
                    signature, code, name, started_at, ended_at, active, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signature) DO UPDATE SET
                    ended_at=excluded.ended_at,
                    active=excluded.active,
                    raw_json=excluded.raw_json
                """,
                (
                    signature,
                    int(alarm.get("code", 255)),
                    str(alarm.get("name", "Nieznany alarm")),
                    alarm.get("from"),
                    alarm.get("to"),
                    int(bool(alarm.get("active"))),
                    json.dumps(alarm, ensure_ascii=False),
                ),
            )

    async def add_audit(
        self,
        scope: str,
        device_index: int,
        parameter: str,
        old_value: Any,
        requested_value: Any,
        success: bool,
        message: str,
    ) -> None:
        await asyncio.to_thread(
            self._add_audit_sync,
            scope,
            device_index,
            parameter,
            old_value,
            requested_value,
            success,
            message,
        )

    def _add_audit_sync(
        self,
        scope: str,
        device_index: int,
        parameter: str,
        old_value: Any,
        requested_value: Any,
        success: bool,
        message: str,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO audit (
                    ts, scope, device_index, parameter, old_value,
                    requested_value, success, message, actor, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    scope,
                    device_index,
                    parameter,
                    json.dumps(old_value, ensure_ascii=False),
                    json.dumps(requested_value, ensure_ascii=False),
                    int(success),
                    message,
                    *current_audit_actor(),
                ),
            )

    async def history(self, hours: int = 24, limit: int = 5000) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._history_sync, hours, limit)

    def _history_sync(self, hours: int, limit: int) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(hours=max(1, hours))).isoformat()
        budget = min(max(limit, 1), 20000)
        with self._connect() as db:
            if budget == 1:
                rows = db.execute("SELECT * FROM samples WHERE ts >= ? ORDER BY ts DESC LIMIT 1", (since,)).fetchall()
            else:
                rows = db.execute(
                    """
                    WITH ranked AS (
                        SELECT *, ROW_NUMBER() OVER (ORDER BY ts) AS sample_rank,
                               COUNT(*) OVER () AS sample_count
                        FROM samples WHERE ts >= ?
                    )
                    SELECT * FROM ranked
                    WHERE sample_rank = 1 OR sample_rank = sample_count OR
                        CAST((sample_rank - 1) * (? - 1) / MAX(sample_count - 1, 1) AS INTEGER) >
                        CAST((sample_rank - 2) * (? - 1) / MAX(sample_count - 1, 1) AS INTEGER)
                    ORDER BY ts ASC
                    """,
                    (since, budget, budget),
                ).fetchall()
        return [{key: row[key] for key in row.keys() if key not in {"sample_rank", "sample_count"}} for row in rows]

    async def fuel_consumption_between(self, since: datetime, until: datetime) -> float | None:
        """Całkuje potwierdzony odczyt kg/h bez uzupełniania luk w historii.

        Pojedynczy odczyt jest uznawany za aktualny najwyżej przez 300 sekund.
        Dłuższa przerwa w danych nie jest liczona jako ciągłe spalanie.
        """
        return await asyncio.to_thread(self._fuel_consumption_between_sync, since, until)

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_sample_time(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return Database._aware_utc(parsed)

    def _fuel_consumption_between_sync(self, since: datetime, until: datetime) -> float | None:
        since_utc = self._aware_utc(since)
        until_utc = self._aware_utc(until)
        if until_utc <= since_utc:
            return None

        query_since = (since_utc - timedelta(seconds=300)).isoformat()
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT ts, fuel_consumption FROM samples
                WHERE ts >= ? AND ts <= ?
                ORDER BY ts ASC
                """,
                (query_since, until_utc.isoformat()),
            ).fetchall()

        samples: list[tuple[datetime, float]] = []
        for row in rows:
            timestamp = self._parse_sample_time(row["ts"])
            try:
                rate = float(row["fuel_consumption"])
            except (TypeError, ValueError):
                continue
            if timestamp is None or not math.isfinite(rate) or rate < 0:
                continue
            samples.append((timestamp, rate))

        total_kg = 0.0
        measured_seconds = 0.0
        for index, (timestamp, rate) in enumerate(samples):
            next_timestamp = samples[index + 1][0] if index + 1 < len(samples) else until_utc
            segment_start = max(timestamp, since_utc)
            segment_end = min(next_timestamp, timestamp + timedelta(seconds=300), until_utc)
            seconds = (segment_end - segment_start).total_seconds()
            if seconds <= 0:
                continue
            total_kg += rate * seconds / 3600.0
            measured_seconds += seconds

        return total_kg if measured_seconds > 0 else None

    async def alarms(self, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._alarms_sync, limit)

    def _alarms_sync(self, limit: int) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT code, name, started_at, ended_at, active
                FROM alarms
                ORDER BY COALESCE(started_at, '') DESC
                LIMIT ?
                """,
                (min(max(limit, 1), 1000),),
            ).fetchall()
        return [dict(row) for row in rows]

    async def audit(self, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._audit_sync, limit)

    def _audit_sync(self, limit: int) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM audit
                ORDER BY ts DESC
                LIMIT ?
                """,
                (min(max(limit, 1), 1000),),
            ).fetchall()
        return [dict(row) for row in rows]

    async def cleanup(self) -> None:
        await asyncio.to_thread(self._cleanup_sync)

    def _cleanup_sync(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()
        with self._connect() as db:
            db.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
            db.execute("DELETE FROM audit WHERE ts < ?", (cutoff,))
            # Active and undated alarms are never purged.
            db.execute("DELETE FROM alarms WHERE active = 0 AND COALESCE(ended_at, started_at) < ?", (cutoff,))
