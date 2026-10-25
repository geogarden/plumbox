"""Controller-owned boiler_work plan (index 3), through PyPlumIO 0.6.8.

UI/semantics adapted from geogarden/ecomax-esp32-gateway, main a21f66a.
Monday first in the API; PyPlumIO's wire order remains Sunday first.
Never mutate its cached Schedule: only a new schedules response confirms a write.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
NAME = "boiler_work"


class ScheduleConflict(ValueError):
    """The controller plan changed since the editor was opened."""


def validate_week(week: Any) -> list[list[bool]]:
    if (not isinstance(week, list) or len(week) != 7
            or any(not isinstance(day, list) or len(day) != 48
                   or any(type(slot) is not bool for slot in day) for day in week)):
        raise ValueError("Plan musi zawierać 7 dni po 48 pól logicznych (co 30 minut).")
    return [day[:] for day in week]


def serialize_week(schedule: Any) -> list[list[bool]]:
    week = []
    for name in DAY_NAMES:
        day = getattr(schedule, name)
        # ScheduleDay.schedule contains bools; __getitem__ returns 'on'/'off'.
        week.append([day.schedule[f"{slot // 2:02d}:{30 * (slot % 2):02d}"] for slot in range(48)])
    return validate_week(week)


def revision(plan: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        {key: plan[key] for key in ("week", "enabled", "parameter", "parameter_min", "parameter_max")},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


class WorkSchedule:
    READ_TIMEOUT = 6.0
    CACHE_SECONDS = 10.0

    def __init__(self, service: Any) -> None:
        self.service = service
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._cached_device: Any = None

    def _device(self) -> Any:
        service = self.service
        if service._simulator:
            raise RuntimeError("Harmonogram sterownika nie jest dostępny w symulacji.")
        if (not service._device or not service._connection
                or not service._is_connected(service._connection)):
            raise RuntimeError("Brak połączenia ze sterownikiem.")
        return service._device

    async def _read_fresh(self) -> dict[str, Any]:
        from pyplumio.const import FrameType
        from pyplumio.frames import Request

        device = self._device()
        loop = asyncio.get_running_loop()
        week_reply, metadata_reply = loop.create_future(), loop.create_future()
        metadata_parts: dict[str, Any] = {}

        async def on_week(schedules: Any) -> None:
            if week_reply.done():
                return
            try:
                schedule = schedules.get(NAME) if isinstance(schedules, dict) else None
                if schedule is None:
                    raise RuntimeError("Sterownik nie udostępnia harmonogramu pracy kotła.")
                week_reply.set_result(serialize_week(schedule))
            except Exception as exc:
                week_reply.set_exception(exc)

        async def on_metadata(key: str, item: Any) -> None:
            if metadata_reply.done():
                return
            try:
                # Individual events establish freshness even when a new reply
                # omits one parameter still present in PyPlumIO's old cache.
                metadata_parts[key] = getattr(item, "values", None)
                if len(metadata_parts) != 2:
                    return
                switch_values, values = metadata_parts["switch"], metadata_parts["parameter"]
                enabled = getattr(switch_values, "value", None)
                value = getattr(values, "value", None)
                low, high = getattr(values, "min_value", None), getattr(values, "max_value", None)
                if (type(enabled) is not int or enabled not in (0, 1) or type(value) is not int
                        or type(low) is not int or type(high) is not int
                        or not 0 <= low <= value <= high <= 100):
                    raise RuntimeError("Brak poprawnych metadanych harmonogramu; zapis jest niedostępny.")
                metadata_reply.set_result({"enabled": bool(enabled), "parameter": value,
                                           "parameter_min": low, "parameter_max": high})
            except Exception as exc:
                metadata_reply.set_exception(exc)

        async def on_switch(item: Any) -> None:
            await on_metadata("switch", item)

        async def on_parameter(item: Any) -> None:
            await on_metadata("parameter", item)

        device.subscribe("schedules", on_week)
        device.subscribe(f"{NAME}_schedule_switch", on_switch)
        device.subscribe(f"{NAME}_schedule_parameter", on_parameter)
        try:
            # device.request/get can immediately return cached data, so wait for
            # NEW schedule and metadata events instead of a generic frame counter.
            device.queue_send(await Request.create(FrameType.REQUEST_SCHEDULES, recipient=device.address))
            week, metadata = await asyncio.wait_for(
                asyncio.gather(week_reply, metadata_reply), timeout=self.READ_TIMEOUT,
            )
            if self._device() is not device:
                raise RuntimeError("Połączenie ze sterownikiem zmieniło się podczas odczytu.")
            plan = {"available": True, "week": week, **metadata,
                    "read_at": time.time(), "source": "Sterownik / PyPlumIO", "message": ""}
            plan["revision"] = revision(plan)
            self._cached, self._cached_at, self._cached_device = plan, time.monotonic(), device
            return plan
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Sterownik nie odpowiedział na odczyt harmonogramu. Spróbuj odczytać ponownie.") from exc
        finally:
            device.unsubscribe("schedules", on_week)
            device.unsubscribe(f"{NAME}_schedule_switch", on_switch)
            device.unsubscribe(f"{NAME}_schedule_parameter", on_parameter)
            for future in (week_reply, metadata_reply):
                if not future.done():
                    future.cancel()

    async def read(self, *, force: bool = False) -> dict[str, Any]:
        async with self.service._write_lock:
            try:
                device = self._device()
                if (not force and device is self._cached_device and self._cached
                        and time.monotonic() - self._cached_at < self.CACHE_SECONDS):
                    return self._cached
                return await self._read_fresh()
            except (RuntimeError, ValueError, KeyError, AttributeError) as exc:
                self._cached = None
                return {"available": False, "message": str(exc), "week": None}

    async def write(self, week: Any, enabled: bool, expected_revision: str) -> dict[str, Any]:
        from pyplumio.const import FrameType
        from pyplumio.frames import Request

        week = validate_week(week)
        if type(enabled) is not bool:
            raise ValueError("Nieprawidłowy stan harmonogramu.")
        async with self.service._write_lock:
            before = await self._read_fresh()
            if before["revision"] != expected_revision:
                raise ScheduleConflict("Plan zmieniono poza formularzem. Odczytaj go ponownie przed zapisem.")
            desired = {**before, "week": week, "enabled": enabled}
            unchanged = revision(desired) == before["revision"]
            confirmed, observed = unchanged, before
            message = "Plan był już ustawiony; nie wysłano zapisu."
            if not unchanged:
                device = self._device()
                # Native encoder, exactly one write. Preserve the schedule's
                # associated parameter and reorder Monday-first to wire order.
                request = await Request.create(
                    FrameType.REQUEST_SET_SCHEDULE, recipient=device.address,
                    data={"type": NAME, "switch": int(enabled), "parameter": before["parameter"],
                          "schedule": [week[6], *week[:6]]},
                )
                device.queue_send(request)
                self._cached = None
                try:
                    observed = await self._read_fresh()
                    confirmed = revision(observed) == revision(desired)
                except (RuntimeError, ValueError, KeyError, AttributeError):
                    observed = None
                message = ("Harmonogram potwierdzono świeżym odczytem ze sterownika." if confirmed else
                           "Zapis harmonogramu niepotwierdzony. Odczytaj plan ponownie; polecenia nie ponowiono.")
            audited = await self.service._safe_add_audit(
                "ecomax", 0, "boiler_work_schedule", before, desired, confirmed, message,
            )
            return {"success": confirmed, "status": "confirmed" if confirmed else "unconfirmed",
                    "message": message, "readback_confirmed": confirmed, "audit_saved": audited,
                    "schedule": observed}
