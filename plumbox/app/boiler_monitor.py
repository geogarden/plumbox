"""Niezależny od transportu obserwator cykli i zdarzeń kotła."""
from __future__ import annotations

import hashlib
import asyncio
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, time, timezone
import json
import logging
import math
from pathlib import Path
import sqlite3
import threading
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_LOG = logging.getLogger(__name__)


def parse_time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def zone(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone.utc


DEFAULT_NOTIFICATIONS = {
    "enabled": False,
    "target": "",
    "start": True,
    "extinguishing": True,
    "finished": True,
    "alarms": True,
    "communication": True,
    "communication_delay_seconds": 120,
    "quiet_hours_enabled": False,
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
    "temperature_threshold": None,
    "threshold_hold_seconds": 10,
    "temperature_hysteresis": 3.0,
}


def fresh_snapshot(snapshot, now):
    at = parse_time(snapshot.get("timestamp"))
    age = number(snapshot.get("service", {}).get("last_frame_age_seconds"))
    return bool(snapshot.get("connected") and not snapshot.get("simulation") and at is not None
                and -5 <= (now - at).total_seconds() <= 15 and (age is None or age <= 15))


def quiet_hours(settings, at, tz):
    if not settings.get("quiet_hours_enabled"):
        return False
    start = settings.get("quiet_hours_start", "22:00")
    end = settings.get("quiet_hours_end", "07:00")
    clock = at.astimezone(tz).strftime("%H:%M")
    return start <= clock < end if start < end else (clock >= start or clock < end) if start > end else False


def communication_events(data, snapshot, settings, now):
    previous = deepcopy(data.get("communication"))
    status = data.setdefault("communication", {"since": None, "notified": False, "id": None})
    events = []
    if snapshot.get("simulation") or not settings.get("enabled") or not settings.get("communication", True):
        status.update(since=None, notified=False, id=None)
    elif fresh_snapshot(snapshot, now):
        if status["notified"]:
            events.append(("communication", status["id"] + ":restored", "Odzyskano łączność z kotłem — odczyty są aktualne."))
        status.update(since=None, notified=False, id=None)
    else:
        since = parse_time(status["since"])
        if since is None or since > now:
            status.update(since=now.isoformat(), notified=False, id=uuid.uuid4().hex)
            since = now
        if not status["notified"] and (now - since).total_seconds() >= settings.get("communication_delay_seconds", 120):
            status["notified"] = True
            events.append(("communication", status["id"] + ":lost", "Utracono łączność z kotłem — brak aktualnych odczytów. Sprawdź połączenie PlumBox i mostu."))
    return events, previous != status


class CycleTracker:
    """Liczy wyłącznie obserwowane cykle; luki i brak początku są jawne."""

    def __init__(self, data=None, timezone_name="Europe/Warsaw"):
        self.data = deepcopy(data) if data else {}
        for key, value in {
            "phase": None, "last_at": None, "current": None, "history": [],
            "daily": {}, "starts_daily": {}, "active_alerts": [],
            "threshold_since": None, "threshold_notified": False,
        }.items():
            self.data.setdefault(key, deepcopy(value))
        self.zone = zone(timezone_name)

    def day(self, at):
        return at.astimezone(self.zone).date().isoformat()

    def add_observed(self, start, end):
        while start < end:
            local = start.astimezone(self.zone)
            midnight = datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=self.zone).astimezone(timezone.utc)
            stop = min(end, midnight)
            key = self.day(start)
            self.data["daily"][key] = self.data["daily"].get(key, 0) + (stop - start).total_seconds()
            start = stop

    def disconnect(self):
        changed = self.data["last_at"] is not None
        self.data["last_at"] = None
        self.data["threshold_since"] = None
        if self.data["current"]:
            self.data["current"]["has_gap"] = True
        return [], changed

    def evaluate(self, snapshot, settings, now=None):
        now = now or datetime.now(timezone.utc)
        at = parse_time(snapshot.get("timestamp"))
        if not fresh_snapshot(snapshot, now):
            return self.disconnect()
        alert_events, alert_changed = self.evaluate_alerts(snapshot, settings, at)
        phase = number(snapshot.get("values", {}).get("state"))
        if phase is None or not phase.is_integer():
            disconnected = self.data["last_at"] is not None
            self.data["last_at"] = None
            if self.data["current"]:
                self.data["current"]["has_gap"] = True
            return alert_events, alert_changed or disconnected
        phase = int(phase)
        previous = self.data["phase"]
        last = parse_time(self.data["last_at"])
        if last and at < last:
            _, gap = self.disconnect()
            return alert_events, alert_changed or gap
        if last and at == last:
            return alert_events, alert_changed
        events = alert_events
        changed = phase != previous or alert_changed
        current = self.data["current"]
        continuity = last is not None and 0 < (at - last).total_seconds() <= 5
        if current and last:
            if continuity:
                seconds = (at - last).total_seconds()
                current["observed_seconds"] += seconds
                self.add_observed(last, at)
            else:
                current["has_gap"] = True
                changed = True

        if current and phase == 2 and previous != 2 and not continuity:
            current["ended_at"] = None
            current["reason"] = "Nieznany koniec podczas przerwy w odczytach"
            current["complete"] = False
            self.data["history"].append(deepcopy(current))
            self.data["current"] = current = None

        if current is None and phase in {1, 2, 3, 4, 7}:
            known_start = phase == 2 and previous in {0, 5, 6} and continuity
            current = {
                "id": uuid.uuid4().hex,
                "started_at": at.isoformat() if known_start else None,
                "observed_since": at.isoformat(),
                "last_at": at.isoformat(),
                "ended_at": None,
                "observed_seconds": 0.0,
                "has_gap": not known_start,
                "complete": False,
                "stop_seen": phase == 7,
                "extinguishing_notified": phase == 7,
            }
            self.data["current"] = current
            changed = True
            if known_start:
                day = self.day(at)
                self.data["starts_daily"][day] = self.data["starts_daily"].get(day, 0) + 1
                events.append(("start", current["id"] + ":start", "Kocioł rozpoczyna rozpalanie."))
        if current:
            current["last_at"] = at.isoformat()
            if phase == 7:
                current["stop_seen"] = True
                if previous is not None and continuity and not current["extinguishing_notified"]:
                    events.append(("extinguishing", current["id"] + ":extinguishing", "Kocioł rozpoczął wygaszanie. Cykl jest nadal liczony."))
                    current["extinguishing_notified"] = True
                    changed = True
            # Samo wejście w wygaszanie lub czyszczenie nie kończy cyklu.
            if phase == 0 or (phase == 5 and current["stop_seen"]):
                current["ended_at"] = at.isoformat()
                current["complete"] = bool(current["started_at"]) and not current["has_gap"]
                current["reason"] = "Wyłączenie kotła" if phase == 0 else "Zakończenie wygaszania"
                self.data["history"].append(deepcopy(current))
                if previous is not None and continuity:
                    duration = (at - parse_time(current["started_at"])).total_seconds() if current["started_at"] else None
                    text = "Cykl kotła zakończony."
                    if current["complete"] and duration is not None:
                        text += f" Czas od rozpalania: {int(duration // 3600)} h {int(duration % 3600 // 60)} min."
                    else:
                        text += " Czas jest niepełny: brak początku lub przerwa w odczytach."
                    events.append(("finished", current["id"] + ":finished", text))
                self.data["current"] = None
                changed = True

        self.data["phase"] = phase
        self.data["last_at"] = at.isoformat()
        self.data["history"] = self.data["history"][-2000:]
        cutoff = self.day(at - timedelta(days=400))
        for field in ("daily", "starts_daily"):
            self.data[field] = {k: v for k, v in self.data[field].items() if k >= cutoff}
        return events, changed

    def evaluate_alerts(self, snapshot, settings, at):
        events = []
        changed = False
        active = set()
        for alert in snapshot.get("alerts", []):
            if not isinstance(alert, dict) or not alert.get("active"):
                continue
            key = f"{alert.get('code')}|{alert.get('from') or ''}"
            active.add(key)
            if key not in self.data["active_alerts"]:
                events.append(("alarms", f"alarm:{key}:{at.isoformat()}", "Alarm kotła: " + str(alert.get("name") or f"kod {alert.get('code')}")))
                changed = True
        if active != set(self.data["active_alerts"]):
            changed = True
        self.data["active_alerts"] = sorted(active)

        threshold = settings.get("temperature_threshold")
        temperature = number(snapshot.get("values", {}).get("feeder_temp"))
        if threshold is None or temperature is None:
            self.data["threshold_since"] = None
        elif temperature >= threshold:
            since = parse_time(self.data["threshold_since"])
            if since is None:
                self.data["threshold_since"] = at.isoformat()
                since = at
            if not self.data["threshold_notified"] and (at - since).total_seconds() >= settings["threshold_hold_seconds"]:
                events.append(("temperature", "temperature:" + at.isoformat(), f"Temperatura podajnika: {temperature:g}°C. Próg ostrzegawczy: {threshold:g}°C."))
                self.data["threshold_notified"] = True
                changed = True
        else:
            # Hold time requires continuous readings at or above threshold.
            self.data["threshold_since"] = None
            if temperature <= threshold - settings["temperature_hysteresis"]:
                if self.data["threshold_notified"]:
                    changed = True
                self.data["threshold_notified"] = False

        return events, changed

    def summary(self, now=None):
        now = now or datetime.now(timezone.utc)
        today = self.day(now)
        month = today[:7]
        def public(cycle):
            if cycle is None:
                return None
            result = deepcopy(cycle)
            start = parse_time(result.get("started_at"))
            end = parse_time(result.get("ended_at")) or parse_time(result.get("last_at"))
            result["duration_seconds"] = (end - start).total_seconds() if start and end else None
            return result
        history = self.data["history"]
        last = parse_time(self.data["last_at"])
        return {
            "current": public(self.data["current"]),
            "last": public(history[-1]) if history else None,
            "cycles": [public(c) for c in reversed(history[-100:])],
            "observed_today_seconds": self.data["daily"].get(today, 0),
            "observed_month_seconds": sum(v for k, v in self.data["daily"].items() if k.startswith(month)),
            "starts_today": self.data["starts_daily"].get(today, 0),
            "starts_month": sum(v for k, v in self.data["starts_daily"].items() if k.startswith(month)),
            "fresh": bool(last and 0 <= (now - last).total_seconds() <= 15),
            "timezone": getattr(self.zone, "key", "UTC"),
            "precision_seconds": 1,
        }


class EventStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.saved_cycle_ids = set()

    @contextmanager
    def connect(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=3)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            try:
                with db:
                    yield db
            finally:
                db.close()

    def initialize(self):
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS monitor_state(id INTEGER PRIMARY KEY, payload TEXT);
                CREATE TABLE IF NOT EXISTS cycles(id TEXT PRIMARY KEY, payload TEXT);
                CREATE TABLE IF NOT EXISTS notification_log(
                    id TEXT PRIMARY KEY, ts TEXT, kind TEXT, message TEXT, target TEXT,
                    status TEXT, attempts INTEGER DEFAULT 0, next_attempt REAL DEFAULT 0, error TEXT);
            """)
            row = db.execute("SELECT payload FROM monitor_state WHERE id=1").fetchone()
            history = [json.loads(r["payload"]) for r in db.execute("SELECT payload FROM cycles ORDER BY rowid DESC LIMIT 2000")]
        data = json.loads(row["payload"]) if row else None
        self.saved_cycle_ids = {item["id"] for item in history}
        if data is not None:
            data["history"] = list(reversed(history))
        return data

    def checkpoint(self, state, notifications=()):
        metadata = {k: v for k, v in state.items() if k != "history"}
        with self.lock:
            new_cycles = [c for c in state.get("history", []) if c["id"] not in self.saved_cycle_ids]
            with self.connect() as db:
                db.execute("INSERT OR REPLACE INTO monitor_state VALUES(1,?)", (json.dumps(metadata),))
                for cycle in new_cycles:
                    db.execute("INSERT OR IGNORE INTO cycles VALUES(?,?)", (cycle["id"], json.dumps(cycle)))
                if new_cycles:
                    db.execute("DELETE FROM cycles WHERE rowid NOT IN (SELECT rowid FROM cycles ORDER BY rowid DESC LIMIT 2000)")
                for n in notifications:
                    db.execute("INSERT OR IGNORE INTO notification_log(id,ts,kind,message,target,status) VALUES(?,?,?,?,?,?)", n)
                db.execute("DELETE FROM notification_log WHERE ts < ?", ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),))
            self.saved_cycle_ids = {c["id"] for c in state.get("history", [])}

    def pending(self, now):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM notification_log WHERE status='pending' AND next_attempt <= ? ORDER BY ts LIMIT 20", (now,))]

    def result(self, identifier, success, error="", now=0):
        with self.connect() as db:
            row = db.execute("SELECT attempts FROM notification_log WHERE id=?", (identifier,)).fetchone()
            attempts = int(row["attempts"]) + 1 if row else 1
            status = "sent" if success else "failed" if attempts >= 3 else "pending"
            db.execute("UPDATE notification_log SET status=?,attempts=?,next_attempt=?,error=? WHERE id=?", (status, attempts, now + 60 * attempts, error[:200], identifier))

    def cancel_event(self, identifier, reason):
        with self.connect() as db:
            db.execute("UPDATE notification_log SET status='cancelled',error=? WHERE id=?", (reason, identifier))

    def cancel_pending(self):
        with self.connect() as db:
            db.execute("UPDATE notification_log SET status='cancelled' WHERE status='pending'")

    def recent(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT ts,kind,message,status,error FROM notification_log ORDER BY ts DESC LIMIT 20")]


def notification_targets(settings):
    """Migrate legacy single-phone settings without losing the saved recipient."""
    selected = settings.get("targets")
    if selected is None:
        selected = [settings["target"]] if settings.get("target") else []
    return list(dict.fromkeys(selected))


class BoilerMonitor:
    def __init__(self, snapshot, database_path, settings, client, timezone_name="Europe/Warsaw"):
        self.snapshot = snapshot
        self.store = EventStore(Path(database_path).with_suffix(".events.db"))
        self.settings = {**DEFAULT_NOTIFICATIONS, **settings}
        self.settings["targets"] = notification_targets(settings)
        self.client = client
        self.timezone_name = timezone_name
        self.tracker = CycleTracker(timezone_name=timezone_name)
        self.task = None
        self.delivery_task = None
        self.initialization_error = ""
        self.last_checkpoint = 0.0
        self.unsaved_notifications = []
        self.dirty = False

    async def start(self):
        saved = await asyncio.to_thread(self.store.initialize)
        self.tracker = CycleTracker(saved, self.timezone_name)
        # Restart procesu nie jest ciągłą obserwacją, więc luki nie są liczone.
        self.tracker.disconnect()
        if not self.settings["enabled"]:
            await asyncio.to_thread(self.store.cancel_pending)
        self.task = asyncio.create_task(self.run(), name="plumbox-cycle-monitor")
        self.delivery_task = asyncio.create_task(self.deliver_loop(), name="plumbox-notification-delivery")

    async def stop(self):
        tasks = [t for t in (self.task, self.delivery_task) if t]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.to_thread(self.store.checkpoint, deepcopy(self.tracker.data), list(self.unsaved_notifications))

    async def tick(self):
        loop = asyncio.get_running_loop()
        snapshot = self.snapshot()
        now = datetime.now(timezone.utc)
        events, changed = self.tracker.evaluate(snapshot, self.settings, now)
        connection_events, connection_changed = communication_events(self.tracker.data, snapshot, self.settings, now)
        events.extend(connection_events)
        changed = changed or connection_changed
        pending = []
        for kind, key, message in events:
            allowed = self.settings["enabled"] and notification_targets(self.settings) and (
                kind == "temperature" or self.settings.get(kind, False))
            if allowed and kind in {"start", "extinguishing", "finished"} and quiet_hours(self.settings, now, self.tracker.zone):
                continue
            if allowed:
                when = now if kind == "communication" else parse_time(snapshot.get("timestamp")) or now
                message += "\nZdarzenie: " + when.astimezone(self.tracker.zone).strftime("%d.%m.%Y %H:%M:%S")
                for target in notification_targets(self.settings):
                    delivery_id = key + "-" + hashlib.sha256(target.encode()).hexdigest()[:16]
                    pending.append((delivery_id, when.isoformat(), kind, message, target, "pending"))
        self.unsaved_notifications.extend(pending)
        self.dirty = self.dirty or changed or bool(pending)
        if self.dirty or loop.time() - self.last_checkpoint >= 30:
            # Nie utracimy zdarzenia po przejściowym błędzie SQLite.
            await asyncio.to_thread(self.store.checkpoint, deepcopy(self.tracker.data), list(self.unsaved_notifications))
            self.unsaved_notifications.clear()
            self.dirty = False
            self.last_checkpoint = loop.time()

    async def deliver_once(self):
        if not self.settings["enabled"]:
            return
        for event in await asyncio.to_thread(self.store.pending, datetime.now(timezone.utc).timestamp()):
            try:
                if event["target"] not in notification_targets(self.settings):
                    await asyncio.to_thread(self.store.cancel_pending)
                    return
                if event["kind"] in {"start", "extinguishing", "finished"} and quiet_hours(self.settings, datetime.now(timezone.utc), self.tracker.zone):
                    await asyncio.to_thread(self.store.cancel_event, event["id"], "Godziny ciszy — informacja o cyklu pominięta.")
                    continue
                if self.snapshot().get("simulation"):
                    raise RuntimeError("Powiadomienia o kotle są wyłączone w symulacji.")
                if (datetime.now(timezone.utc) - parse_time(event["ts"])).total_seconds() > 600:
                    await asyncio.to_thread(self.store.result, event["id"], False, "Zdarzenie jest zbyt stare.", datetime.now(timezone.utc).timestamp())
                    continue
                await self.client.send(event["target"], event["message"], event["id"])
                await asyncio.to_thread(self.store.result, event["id"], True)
            except Exception as exc:
                await asyncio.to_thread(self.store.result, event["id"], False, str(exc), datetime.now(timezone.utc).timestamp())

    async def deliver_loop(self):
        while True:
            try:
                await self.deliver_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOG.exception("Błąd kolejki powiadomień.")
            await asyncio.sleep(2)

    async def run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOG.exception("Błąd niezależnego modułu cykli/powiadomień.")
            await asyncio.sleep(1)
