"""Połączenie z ecoMAX, odczyt danych i bezpieczny zapis."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from dataclasses import replace
from typing import Any, Awaitable, Callable

from .common import profile_mode, utc_now_iso
from .config import AppConfig
from .controller_profile import build_controller_profile
from .database import Database
from .mappings import fan_rpm_profile_state, meta_for, model_parameter_range, native_value
from .serializer import (
    alert_to_dict,
    is_parameter,
    parameter_to_dict,
    simple_value,
    state_label,
)
from .simulator import Simulator
from .work_schedule import WorkSchedule

_LOGGER = logging.getLogger(__name__)

SnapshotCallback = Callable[[dict[str, Any]], Awaitable[None]]


class TransportPhaseError(ConnectionError):
    """Awaria transportu przypisana do jawnej fazy sesji."""

    def __init__(self, phase: str, message: str) -> None:
        super().__init__(message)
        self.phase = phase


class TransportPhaseTimeout(asyncio.TimeoutError):
    """Przekroczenie limitu czasu konkretnej fazy transportu."""

    def __init__(
        self,
        phase: str,
        timeout_seconds: float,
        detail: str | None = None,
    ) -> None:
        self.phase = phase
        self.timeout_seconds = timeout_seconds
        message = f"Faza transportu '{phase}' przekroczyla limit {timeout_seconds:.1f} s."
        if detail:
            message += f" {detail}"
        super().__init__(message)


class PlumService:
    WRITE_READBACK_TIMEOUT_SECONDS = 8.0
    WRITE_READBACK_INTERVAL_SECONDS = 0.25
    PARAMETER_GROUP_RETRY_INTERVAL_SECONDS = 60.0
    KEEPALIVE_IDLE_SECONDS = 20
    KEEPALIVE_INTERVAL_SECONDS = 5
    KEEPALIVE_FAILED_PROBES = 3
    STALLED_HANDSHAKE_HINT_AFTER = 3
    SESSION_CLEANUP_TIMEOUT_SECONDS = 5.0
    TRANSPORT_HEARTBEAT_SECONDS = 300.0

    def __init__(
        self,
        config: AppConfig,
        database: Database,
        on_snapshot: SnapshotCallback | None = None,
    ) -> None:
        self.config = config
        self.database = database
        self.on_snapshot = on_snapshot
        self.snapshot: dict[str, Any] = self._empty_snapshot()
        self._task: asyncio.Task[None] | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._device: Any = None
        self._connection: Any = None
        self._last_sample = 0.0
        self._known_alarm_signatures: set[str] = set()
        self._write_lock = asyncio.Lock()
        self._parameter_group_retry_task: asyncio.Task[None] | None = None
        self._last_parameter_group_retry = 0.0
        self._last_received_frames: int | None = None
        self._last_frame_progress_at: float | None = None
        self._consecutive_connection_failures = 0
        self._session_sequence = 0
        self._active_session_id: int | None = None
        self._service_restarts = 0
        self._last_task_exit_reason: str | None = None
        self._last_task_exit_at: str | None = None
        self._last_transport_heartbeat = 0.0
        self._transport_phase = "idle"
        self._transport_phase_started_at = time.monotonic()
        self._transport_phase_session_id: int | None = None
        self._last_failure_phase: str | None = None
        self._last_failure_at: str | None = None
        self._simulator = Simulator() if config.connection.type.lower() == "simulation" else None
        self.work_schedule = WorkSchedule(self)

    def _set_transport_phase(self, phase: str, session_id: int | None = None) -> None:
        self._transport_phase = phase
        self._transport_phase_started_at = time.monotonic()
        self._transport_phase_session_id = session_id

    @staticmethod
    def _is_connected(connection: Any) -> bool:
        """Zwraca realny stan połączenia PyPlumIO.

        W PyPlumIO `connection.connected` jest `asyncio.Event`, a nie zwykłym bool.
        Samo `bool(connection.connected)` byłoby zawsze prawdziwe i dashboard
        pokazywałby połączenie nawet po zerwaniu TCP/serial.
        """
        connected = getattr(connection, "connected", True)
        if hasattr(connected, "is_set"):
            return bool(connected.is_set())
        return bool(connected)

    @staticmethod
    def _empty_snapshot(error: str | None = None) -> dict[str, Any]:
        return {
            "timestamp": utc_now_iso(),
            "connected": False,
            "simulation": False,
            "connection_error": error,
            "values": {},
            "parameters": {},
            "mixers": {},
            "alerts": [],
            "statistics": {},
            "profile": {},
            "hardware_profile": {
                "enabled": False,
                "status": "offline",
                "source": "none",
                "product_id": None,
                "product_model": None,
                "label": "Brak połączenia ze sterownikiem",
                "warning": None,
            },
        }

    async def start(self) -> None:
        self._stop.clear()
        self._set_transport_phase("starting")
        if not self._supervisor_task or self._supervisor_task.done():
            self._supervisor_task = asyncio.create_task(
                self._supervise_transport(),
                name="plumbox-transport-supervisor",
            )

    async def stop(self) -> None:
        self._stop.set()
        supervisor = self._supervisor_task
        if supervisor:
            supervisor.cancel()
            try:
                await supervisor
            except asyncio.CancelledError:
                pass
        elif self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._supervisor_task = None
        self._task = None
        self._set_transport_phase("stopped")

    async def _supervise_transport(self) -> None:
        """Pilnuj zadania komunikacji bez zmiany jego semantyki anulowania."""
        try:
            while not self._stop.is_set():
                worker = asyncio.create_task(self._run(), name="plumbox-connection")
                self._task = worker
                try:
                    # asyncio.wait nie propaguje CancelledError zakończonego workera.
                    # Dzięki temu nadzorca może odróżnić awarię od własnego stop().
                    await asyncio.wait({worker}, return_when=asyncio.ALL_COMPLETED)
                except asyncio.CancelledError:
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
                    raise

                if self._stop.is_set():
                    break

                if worker.cancelled():
                    reason = "zadanie transportu zostało niespodziewanie anulowane"
                else:
                    error = worker.exception()
                    reason = (
                        f"zadanie transportu zakończyło się wyjątkiem: {error!r}"
                        if error is not None
                        else "zadanie transportu zakończyło się niespodziewanie"
                    )

                self._service_restarts += 1
                self._last_task_exit_reason = reason
                self._last_task_exit_at = utc_now_iso()
                _LOGGER.error(
                    "%s; nadzorca uruchamia komunikację ponownie (restart nr %d).",
                    reason,
                    self._service_restarts,
                )
                self.snapshot = self._empty_snapshot(reason)
                await self._emit()

                try:
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=self.config.connection.reconnect_delay_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self._task = None

    def transport_health(self) -> dict[str, Any]:
        """Zwróć diagnostykę nadzorcy i bieżącej sesji transportowej."""
        frame_age = None
        if self._last_frame_progress_at is not None:
            frame_age = max(0.0, time.monotonic() - self._last_frame_progress_at)
        phase_age = max(0.0, time.monotonic() - self._transport_phase_started_at)
        return {
            "supervisor_alive": bool(
                self._supervisor_task and not self._supervisor_task.done()
            ),
            "task_alive": bool(self._task and not self._task.done()),
            "session_id": self._active_session_id,
            "last_frame_age_seconds": (
                round(frame_age, 3) if frame_age is not None else None
            ),
            "consecutive_failures": self._consecutive_connection_failures,
            "service_restarts": self._service_restarts,
            "last_task_exit_reason": self._last_task_exit_reason,
            "last_task_exit_at": self._last_task_exit_at,
            "phase": self._transport_phase,
            "phase_age_seconds": round(phase_age, 3),
            "phase_session_id": self._transport_phase_session_id,
            "last_failure_phase": self._last_failure_phase,
            "last_failure_at": self._last_failure_at,
        }

    async def _run(self) -> None:
        if self._simulator:
            await self._run_simulator()
            return

        while not self._stop.is_set():
            try:
                await self._connection_session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._consecutive_connection_failures += 1
                self._last_failure_phase = getattr(exc, "phase", self._transport_phase)
                self._last_failure_at = utc_now_iso()
                message = self._connection_error_message(
                    exc,
                    self._consecutive_connection_failures,
                )
                _LOGGER.exception(
                    "Połączenie z ecoMAX zostało przerwane: %s",
                    message,
                )
                self.snapshot = self._empty_snapshot(message)
                await self._emit()
                self._set_transport_phase("backoff")
                await asyncio.sleep(self.config.connection.reconnect_delay_seconds)

    async def _run_simulator(self) -> None:
        while not self._stop.is_set():
            self.snapshot = self._apply_write_policy(self._simulator.snapshot())
            self.snapshot["profile"] = build_controller_profile(self.snapshot, profile_mode(self.config))
            self.snapshot["hardware_profile"] = {
                "enabled": False,
                "status": "simulation",
                "source": "simulation",
                "product_id": None,
                "product_model": "Symulator",
                "label": "Tryb symulacji",
                "warning": None,
            }
            await self._after_snapshot()
            await asyncio.sleep(self.config.web.poll_interval_seconds)

    async def _connection_session(self) -> None:
        """Jedna ograniczona czasowo sesja transportu i negocjacji ecoMAX."""
        import pyplumio

        self._session_sequence += 1
        session_id = self._session_sequence
        self._active_session_id = session_id
        connection_type = self.config.connection.type.lower()
        if connection_type == "tcp":
            connection = pyplumio.open_tcp_connection(
                self.config.connection.host,
                self.config.connection.port,
                reconnect_on_failure=False,
            )
        elif connection_type == "serial":
            connection = pyplumio.open_serial_connection(
                self.config.connection.serial_device,
                baudrate=self.config.connection.baudrate,
                reconnect_on_failure=False,
            )
        else:
            raise ValueError(f"Nieobslugiwany typ polaczenia: {connection_type}")

        transport: Any = None
        active_connection: Any = None
        entered = False
        session_error: BaseException | None = None
        try:
            opening_phase = "opening_tcp" if connection_type == "tcp" else "opening_serial"
            self._set_transport_phase(opening_phase, session_id)
            connect_timeout = max(
                0.01,
                float(getattr(self.config.connection, "connect_timeout_seconds", 10.0)),
            )
            try:
                active_connection = await asyncio.wait_for(
                    connection.__aenter__(), timeout=connect_timeout
                )
                entered = True
            except asyncio.TimeoutError as exc:
                raise TransportPhaseTimeout(opening_phase, connect_timeout) from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise TransportPhaseError(
                    opening_phase,
                    f"Nie udalo sie otworzyc transportu ecoMAX: {exc or exc.__class__.__name__}",
                ) from exc

            self._connection = active_connection
            transport = self._connection_transport(active_connection)
            if connection_type == "tcp":
                self._enable_tcp_keepalive(transport)
            _LOGGER.info(
                "Sesja ecoMAX %s: transport otwarty, rozpoczynam negocjacje.",
                session_id,
            )

            self._set_transport_phase("waiting_ecomax", session_id)
            device_timeout = max(
                0.01, float(self.config.connection.device_timeout_seconds)
            )
            try:
                device = await asyncio.wait_for(
                    active_connection.get("ecomax", timeout=device_timeout),
                    timeout=device_timeout + 1.0,
                )
            except asyncio.TimeoutError as exc:
                raise TransportPhaseTimeout(
                    "waiting_ecomax", device_timeout, str(exc) or None
                ) from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise TransportPhaseError(
                    "waiting_ecomax",
                    f"Sterownik ecoMAX nie odpowiedzial: {exc or exc.__class__.__name__}",
                ) from exc

            self._device = device
            self._consecutive_connection_failures = 0
            self._last_parameter_group_retry = 0.0
            self._reset_frame_watchdog(active_connection)
            self._set_transport_phase("online", session_id)
            _LOGGER.info("Sesja ecoMAX %s: polaczono z regulatorem.", session_id)
            while not self._stop.is_set() and self._is_connected(active_connection):
                if self._connection_frames_stalled(active_connection):
                    timeout = max(
                        15.0,
                        float(getattr(self.config.connection, "stale_frame_timeout_seconds", 45.0)),
                    )
                    raise TransportPhaseError(
                        "online",
                        f"Brak nowych ramek ecoMAX przez {timeout:.0f} s mimo aktywnego TCP. "
                        "Wymuszam ponowne polaczenie.",
                    )
                self.snapshot = self._build_snapshot(active_connection, device)
                await self._after_snapshot()
                self._schedule_parameter_group_retry(device)
                await asyncio.sleep(self.config.web.poll_interval_seconds)
            if not self._stop.is_set():
                raise TransportPhaseError("online", "Polaczenie z ecoMAX zostalo przerwane.")
        except BaseException as exc:
            session_error = exc
            raise
        finally:
            await self._cancel_parameter_group_retry()
            if entered and active_connection is not None:
                diagnostics = self._session_diagnostics(active_connection)
                _LOGGER.info(
                    "Sesja ecoMAX %s: sprzatanie; poprawne_ramki=%s, "
                    "odrzucone_ramki=%s, wyslane_ramki=%s, bufor_tcp=%s B.",
                    session_id,
                    diagnostics["received_frames"],
                    diagnostics["failed_frames"],
                    diagnostics["sent_frames"],
                    diagnostics["buffered_bytes"],
                )
                self._set_transport_phase("cleanup", session_id)
                await self._quiesce_pyplumio_session(
                    active_connection, transport, session_id
                )
                cleanup_timeout = max(
                    0.01,
                    float(getattr(self.config.connection, "cleanup_timeout_seconds", 12.0)),
                )
                exit_type = type(session_error) if session_error is not None else None
                exit_traceback = session_error.__traceback__ if session_error is not None else None
                try:
                    await asyncio.wait_for(
                        connection.__aexit__(exit_type, session_error, exit_traceback),
                        timeout=cleanup_timeout,
                    )
                except asyncio.TimeoutError as exc:
                    self._abort_transport(transport)
                    if session_error is None:
                        self._device = None
                        self._connection = None
                        self._last_received_frames = None
                        self._last_frame_progress_at = None
                        self._active_session_id = None
                        self._set_transport_phase("idle")
                        raise TransportPhaseTimeout("cleanup", cleanup_timeout) from exc
                    _LOGGER.warning(
                        "Sesja ecoMAX %s: cleanup przekroczyl %.1f s; transport przerwany.",
                        session_id,
                        cleanup_timeout,
                    )
                except asyncio.CancelledError:
                    self._abort_transport(transport)
                    raise
                except Exception:
                    self._abort_transport(transport)
                    if session_error is None:
                        self._device = None
                        self._connection = None
                        self._last_received_frames = None
                        self._last_frame_progress_at = None
                        self._active_session_id = None
                        self._set_transport_phase("idle")
                        raise
                    _LOGGER.warning(
                        "Sesja ecoMAX %s: blad cleanup; zachowuje pierwotna awarie.",
                        session_id,
                        exc_info=True,
                    )
            self._abort_transport(transport)
            self._device = None
            self._connection = None
            self._last_received_frames = None
            self._last_frame_progress_at = None
            self._active_session_id = None
            self._set_transport_phase("idle")

    @staticmethod
    def _session_diagnostics(connection: Any) -> dict[str, int]:
        """Zbierz bezpiecznie liczniki sesji bez uzależniania pracy od prywatnego API."""
        protocol = getattr(connection, "protocol", None)
        statistics = getattr(protocol, "statistics", None)
        reader = getattr(protocol, "reader", None)
        buffered_reader = getattr(reader, "_reader", None)
        buffer_value = getattr(buffered_reader, "buffer", b"")

        def number(name: str) -> int:
            try:
                return int(getattr(statistics, name, 0) or 0)
            except (TypeError, ValueError):
                return 0

        try:
            buffered_bytes = len(buffer_value)
        except TypeError:
            buffered_bytes = 0
        return {
            "received_frames": number("received_frames"),
            "failed_frames": number("failed_frames"),
            "sent_frames": number("sent_frames"),
            "buffered_bytes": buffered_bytes,
        }

    async def _quiesce_pyplumio_session(
        self,
        connection: Any,
        transport: Any,
        session_id: int,
    ) -> None:
        """Przerwij transport i zaczekaj na zadania bieżącej sesji PyPlumIO."""
        self._abort_transport(transport)
        protocol = getattr(connection, "protocol", None)
        owners = tuple(owner for owner in (protocol, connection) if owner is not None)
        tasks_before = sum(len(getattr(owner, "tasks", ()) or ()) for owner in owners)

        # Abort budzi frame_handler z oczekiwania na read(). Oddajemy mu jeden obrót
        # pętli, po czym anulujemy również zadania utworzone w reakcji na utratę TCP.
        await asyncio.sleep(0)
        for owner in owners:
            cancel_tasks = getattr(owner, "cancel_tasks", None)
            if callable(cancel_tasks):
                cancel_tasks()
        await asyncio.sleep(0)
        for owner in owners:
            cancel_tasks = getattr(owner, "cancel_tasks", None)
            if callable(cancel_tasks):
                cancel_tasks()

        waiters = []
        for owner in owners:
            wait_until_done = getattr(owner, "wait_until_done", None)
            if callable(wait_until_done):
                waiters.append(wait_until_done())
        if waiters:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*waiters, return_exceptions=True),
                    timeout=self.SESSION_CLEANUP_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Sesja ecoMAX %s: przekroczono %.1f s podczas kończenia "
                    "zadań PyPlumIO; kontynuuję pełne zamknięcie kontekstu.",
                    session_id,
                    self.SESSION_CLEANUP_TIMEOUT_SECONDS,
                )

        tasks_after = sum(
            sum(1 for task in (getattr(owner, "tasks", ()) or ()) if not task.done())
            for owner in owners
        )
        _LOGGER.info(
            "Sesja ecoMAX %s: transport przerwany, zadania przed=%s, żywe po=%s.",
            session_id,
            tasks_before,
            tasks_after,
        )

    @staticmethod
    def _connection_transport(connection: Any) -> Any:
        """Zwróć transport TCP PyPlumIO defensywnie, bez zależności od API publicznego."""
        try:
            writer = getattr(getattr(connection, "protocol", None), "writer", None)
            stream_writer = getattr(writer, "_writer", None)
            return getattr(stream_writer, "transport", None)
        except Exception:
            return None

    def _enable_tcp_keepalive(self, transport: Any) -> None:
        """Włącz keepalive od razu po otwarciu TCP, także przed pierwszą ramką."""
        if transport is None:
            _LOGGER.debug("Nie udało się sięgnąć transportu TCP; keepalive pominięty.")
            return
        try:
            sock = transport.get_extra_info("socket")
            if sock is None:
                _LOGGER.debug("Transport TCP nie udostępnił gniazda; keepalive pominięty.")
                return
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for option, value in (
                ("TCP_KEEPIDLE", self.KEEPALIVE_IDLE_SECONDS),
                ("TCP_KEEPINTVL", self.KEEPALIVE_INTERVAL_SECONDS),
                ("TCP_KEEPCNT", self.KEEPALIVE_FAILED_PROBES),
            ):
                if hasattr(socket, option):
                    sock.setsockopt(
                        socket.IPPROTO_TCP,
                        getattr(socket, option),
                        value,
                    )
        except Exception:
            # Prywatne wnętrze PyPlumIO może się zmienić. Brak keepalive nie może
            # zablokować zwykłego połączenia ani trybu szeregowego.
            _LOGGER.warning(
                "Nie udało się ustawić keepalive na gnieździe TCP.",
                exc_info=True,
            )

    @staticmethod
    def _abort_transport(transport: Any) -> None:
        """Natychmiast zwolnij przechwycony transport po zakończeniu sesji."""
        if transport is None:
            return
        try:
            transport.abort()
        except Exception:
            _LOGGER.debug(
                "Nie udało się wymusić zamknięcia transportu.",
                exc_info=True,
            )

    def _connection_error_message(self, exc: Exception, failures: int) -> str:
        """Czytelny opis awarii; pusty TimeoutError nie może dawać „Brak”."""
        if isinstance(exc, TransportPhaseTimeout):
            message = str(exc)
        elif isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            timeout = float(self.config.connection.device_timeout_seconds)
            message = (
                "Połączenie TCP zostało zestawione, ale sterownik nie przysłał "
                f"żadnej ramki przez {timeout:.0f} s."
            )
        else:
            message = str(exc) or exc.__class__.__name__
        if failures >= self.STALLED_HANDSHAKE_HINT_AFTER:
            message += (
                f" Nieudane próby: {failures}. Mostek może utrzymywać sesję "
                "sprzed zerwania sieci — sprawdź połączenie mostka albo uruchom "
                "ponownie PlumBridge."
            )
        return message

    @staticmethod
    def _received_frame_count(connection: Any) -> int | None:
        statistics = getattr(connection, "statistics", None)
        raw = getattr(statistics, "received_frames", None)
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _reset_frame_watchdog(self, connection: Any) -> None:
        self._last_received_frames = self._received_frame_count(connection)
        self._last_frame_progress_at = asyncio.get_running_loop().time()

    def _connection_frames_stalled(self, connection: Any, *, now: float | None = None) -> bool:
        """Wykrywa półotwarte TCP: Event nadal ONLINE, ale nie przychodzą ramki."""
        count = self._received_frame_count(connection)
        if count is None:
            return False
        moment = asyncio.get_running_loop().time() if now is None else float(now)
        if self._last_received_frames is None or self._last_frame_progress_at is None:
            self._last_received_frames = count
            self._last_frame_progress_at = moment
            return False
        if count != self._last_received_frames:
            self._last_received_frames = count
            self._last_frame_progress_at = moment
            return False
        timeout = max(
            15.0,
            float(getattr(self.config.connection, "stale_frame_timeout_seconds", 45.0)),
        )
        return moment - self._last_frame_progress_at >= timeout

    @staticmethod
    def _frame_error_codes(device: Any) -> set[int]:
        codes: set[int] = set()
        for item in (getattr(device, "data", {}) or {}).get("frame_errors", []):
            raw = getattr(item, "value", item)
            try:
                codes.add(int(raw))
            except (TypeError, ValueError):
                continue
        return codes

    def _missing_parameter_groups(self, device: Any) -> list[tuple[str, int]]:
        """Grupy, których PyPlumIO nie dostało podczas jednorazowego setupu.

        Kody pochodzą z publicznego ``FrameType`` PyPlumIO: 57 to product/UID,
        49 to parametry ecoMAX, a 50 parametry mieszaczy. Mieszacz ponawiamy
        tylko wtedy, gdy sterownik faktycznie udostępnił jego obiekt.
        """
        data = getattr(device, "data", {}) or {}
        errors = self._frame_error_codes(device)
        missing: list[tuple[str, int]] = []
        if 57 in errors and not data.get("product"):
            missing.append(("product", 57))
        if 49 in errors and not data.get("ecomax_parameters"):
            missing.append(("ecomax_parameters", 49))
        if 50 in errors and data.get("mixers") and not data.get("mixer_parameters"):
            missing.append(("mixer_parameters", 50))
        return missing

    def _schedule_parameter_group_retry(self, device: Any) -> None:
        missing = self._missing_parameter_groups(device)
        if not missing:
            return
        if self._parameter_group_retry_task and not self._parameter_group_retry_task.done():
            return
        now = asyncio.get_running_loop().time()
        if now - self._last_parameter_group_retry < self.PARAMETER_GROUP_RETRY_INTERVAL_SECONDS:
            return
        self._last_parameter_group_retry = now
        self._parameter_group_retry_task = asyncio.create_task(
            self._retry_parameter_groups(device, missing),
            name="plumbox-parameter-group-retry",
        )

    async def _retry_parameter_groups(
        self,
        device: Any,
        missing: list[tuple[str, int]],
    ) -> None:
        from pyplumio.const import FrameType

        for name, frame_code in missing:
            if device is not self._device or not self._is_connected(self._connection):
                return
            frame_type = FrameType(frame_code)
            _LOGGER.warning(
                "Brak grupy '%s' po setupie PyPlumIO (frame error %s). Ponawiam żądanie.",
                name,
                frame_code,
            )
            try:
                await device.request(name, frame_type, retries=3, timeout=3.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.warning(
                    "Ponowne żądanie grupy '%s' nie powiodło się; kolejna próba najwcześniej za %.0f s.",
                    name,
                    self.PARAMETER_GROUP_RETRY_INTERVAL_SECONDS,
                    exc_info=True,
                )
            else:
                _LOGGER.info("Odzyskano grupę parametrów '%s' bez restartu dodatku.", name)

    async def _cancel_parameter_group_retry(self) -> None:
        task = self._parameter_group_retry_task
        self._parameter_group_retry_task = None
        if not task or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _build_snapshot(self, connection: Any, device: Any) -> dict[str, Any]:
        values: dict[str, Any] = {}
        parameters: dict[str, Any] = {}
        mixers: dict[str, Any] = {}
        alerts: list[dict[str, Any]] = []

        device_data = dict(device.data)
        product = simple_value(device_data.get("product"))
        if not isinstance(product, dict):
            product = (self.snapshot.get("values") or {}).get("product")
        hardware_profile = self._hardware_profile(product)
        fan_rpm_enabled = bool(hardware_profile["enabled"])
        airflow_correction_enabled = bool(hardware_profile["enabled"])

        for name, item in device_data.items():
            if name == "mixers" and isinstance(item, dict):
                for index, mixer in item.items():
                    mixer_values: dict[str, Any] = {}
                    mixer_parameters: dict[str, Any] = {}
                    for mixer_name, mixer_item in dict(mixer.data).items():
                        if is_parameter(mixer_item):
                            mixer_parameters[mixer_name] = parameter_to_dict(
                                mixer_name,
                                mixer_item,
                                scope="mixer",
                                index=int(index),
                            )
                        elif isinstance(mixer_item, (str, int, float, bool)) or mixer_item is None:
                            mixer_values[mixer_name] = simple_value(mixer_item)
                    mixers[str(index)] = {
                        "values": mixer_values,
                        "parameters": mixer_parameters,
                    }
            elif name == "alerts" and isinstance(item, (list, tuple)):
                alerts = [alert_to_dict(alert) for alert in item]
            elif is_parameter(item):
                parameters[name] = parameter_to_dict(
                    name,
                    item,
                    scope="ecomax",
                    index=0,
                    fan_rpm_enabled=fan_rpm_enabled,
                    airflow_correction_enabled=airflow_correction_enabled,
                    range_override=model_parameter_range(name, "ecomax", self._product_id(product)),
                )
            elif isinstance(item, (str, int, float, bool)) or item is None:
                values[name] = simple_value(item)
            elif name in {"modules", "product", "frame_errors"}:
                values[name] = simple_value(item)

        state = values.get("state")
        if state is not None:
            values["state_label"] = state_label(
                state,
                ecomax860p4_profile_enabled=bool(hardware_profile["enabled"]),
            )

        statistics = simple_value(getattr(connection, "statistics", {}))

        snapshot = {
            "timestamp": utc_now_iso(),
            "connected": self._is_connected(connection),
            "simulation": False,
            "connection_error": None,
            "values": values,
            "parameters": parameters,
            "mixers": mixers,
            "alerts": alerts,
            "statistics": statistics,
            "hardware_profile": hardware_profile,
        }
        snapshot = self._merge_live_snapshot(self.snapshot, snapshot)
        self._apply_write_policy(snapshot)
        snapshot["profile"] = build_controller_profile(snapshot, profile_mode(self.config))
        return snapshot

    @staticmethod
    def _product_id(product: Any) -> Any:
        """Wyciąga product ID ze zserializowanego obiektu PyPlumIO."""
        if isinstance(product, dict):
            return product.get("id")
        return getattr(product, "id", None)

    def _hardware_profile(self, product: Any) -> dict[str, Any]:
        state = fan_rpm_profile_state(
            profile_mode(self.config),
            self._product_id(product),
        )
        state["profile_mode"] = profile_mode(self.config)
        state["product_model"] = (
            product.get("model") if isinstance(product, dict) else getattr(product, "model", None)
        )
        return state

    def _fan_rpm_enabled(self) -> bool:
        product = (self.snapshot.get("values") or {}).get("product")
        return bool(self._hardware_profile(product)["enabled"])

    @staticmethod
    def _merge_live_snapshot(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        """Nie kasuj danych, których zabrakło tylko w pojedynczej ramce PyPlumIO.

        PyPlumIO może w trakcie aktywnego połączenia opublikować przejściowo
        niepełny słownik urządzenia. Panel odświeża teraz otwartą sekcję na żywo,
        więc zastąpienie pełnego snapshotu taką ramką usuwało z ekranu m.in.
        parametry mieszacza. Po rozłączeniu cache nie jest używany, ponieważ
        ``_run`` publikuje świeży, pusty snapshot offline.
        """
        if not previous.get("connected") or not current.get("connected"):
            return current

        current["values"] = {
            **(previous.get("values") or {}),
            **(current.get("values") or {}),
        }
        current["parameters"] = {
            **(previous.get("parameters") or {}),
            **(current.get("parameters") or {}),
        }
        current["statistics"] = {
            **(previous.get("statistics") or {}),
            **(current.get("statistics") or {}),
        }

        merged_mixers: dict[str, Any] = {
            str(index): dict(mixer)
            for index, mixer in (previous.get("mixers") or {}).items()
            if isinstance(mixer, dict)
        }
        for index, mixer in (current.get("mixers") or {}).items():
            key = str(index)
            if not isinstance(mixer, dict):
                continue
            old_mixer = merged_mixers.get(key, {})
            merged_mixers[key] = {
                **old_mixer,
                **mixer,
                "values": {
                    **(old_mixer.get("values") or {}),
                    **(mixer.get("values") or {}),
                },
                "parameters": {
                    **(old_mixer.get("parameters") or {}),
                    **(mixer.get("parameters") or {}),
                },
            }
        current["mixers"] = merged_mixers
        return current

    def _apply_write_policy(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Uzgadnia pole ``writable`` parametrów z konfiguracją zapisu.

        Serializer domyślnie oznacza jako zapisywalne tylko ``risk=safe``.
        Przy ``security.safe_writes_only=false`` (decyzja użytkownika) advanced
        i critical też są zapisywalne — UI, profil i MQTT mają to widzieć.
        """
        if getattr(self.config.security, "safe_writes_only", True):
            return snapshot
        for parameter in (snapshot.get("parameters") or {}).values():
            if isinstance(parameter, dict):
                parameter["writable"] = True
        for mixer in (snapshot.get("mixers") or {}).values():
            if isinstance(mixer, dict):
                for parameter in (mixer.get("parameters") or {}).values():
                    if isinstance(parameter, dict):
                        parameter["writable"] = True
        return snapshot

    async def _after_snapshot(self) -> None:
        await self._store_alerts()
        loop_time = asyncio.get_running_loop().time()
        if loop_time - self._last_transport_heartbeat >= self.TRANSPORT_HEARTBEAT_SECONDS:
            self._last_transport_heartbeat = loop_time
            health = self.transport_health()
            _LOGGER.info(
                "Transport ecoMAX: connected=%s session=%s task=%s phase=%s "
                "phase_age=%s frame_age=%s restarts=%s.",
                self.snapshot.get("connected", False),
                health["session_id"],
                health["task_alive"],
                health["phase"],
                health["phase_age_seconds"],
                health["last_frame_age_seconds"],
                health["service_restarts"],
            )
        if (
            self.config.history.enabled
            and loop_time - self._last_sample >= self.config.history.sample_interval_seconds
        ):
            self._last_sample = loop_time
            await self.database.add_sample(self.snapshot)
        await self._emit()

    async def _store_alerts(self) -> None:
        for alert in self.snapshot.get("alerts", []):
            # Sygnatura pamięciowa celowo zawiera też `to`, inaczej niż klucz
            # UNIQUE w bazie (`code|from`): gdy alarm się kończy i `to` się
            # zmienia, wpis przechodzi tu ponownie i upsert w add_alarm
            # uzupełnia ended_at/active dla tego samego rekordu.
            signature = f"{alert.get('code')}|{alert.get('from')}|{alert.get('to')}"
            if signature not in self._known_alarm_signatures:
                self._known_alarm_signatures.add(signature)
                await self.database.add_alarm(alert)

    async def _emit(self) -> None:
        self.snapshot["service"] = self.transport_health()
        if self.on_snapshot:
            try:
                await self.on_snapshot(self.snapshot)
            except Exception:
                _LOGGER.exception("Błąd wysyłania aktualizacji dashboardu.")

    async def set_parameter(
        self,
        scope: str,
        index: int,
        name: str,
        shown_value: Any,
    ) -> dict[str, Any]:
        async with self._write_lock:
            old_value = self._current_parameter(scope, index, name)
            success = False
            message = ""
            transport_accepted: bool | None = None
            readback_confirmed: bool | None = None

            try:
                if self._simulator:
                    success = self._simulator.set_parameter(scope, index, name, shown_value)
                    self.snapshot = self._apply_write_policy(self._simulator.snapshot())
                    self.snapshot["profile"] = build_controller_profile(
                        self.snapshot,
                        profile_mode(self.config),
                    )
                    self.snapshot["hardware_profile"] = {
                        "enabled": False,
                        "status": "simulation",
                        "source": "simulation",
                        "product_id": None,
                        "product_model": "Symulator",
                        "label": "Tryb symulacji",
                        "warning": None,
                    }
                    message = "Zapis symulowany."
                else:
                    meta = meta_for(name, scope)
                    risk = str(meta.get("risk", "advanced"))
                    if risk != "safe" and getattr(self.config.security, "safe_writes_only", True):
                        raise PermissionError(
                            f"Parametr '{name}' ma poziom ryzyka '{risk}' i jest tylko do odczytu "
                            "(security.safe_writes_only)."
                        )
                    device = self._resolve_device(scope, index)
                    native = native_value(
                        name,
                        shown_value,
                        scope,
                        fan_rpm_enabled=self._fan_rpm_enabled(),
                        airflow_correction_enabled=self._fan_rpm_enabled(),
                    )
                    current_item = getattr(device, "data", {}).get(name)
                    self._prepare_model_parameter_range(current_item, scope, name)
                    current_native = getattr(current_item, "value", current_item)
                    if self._same_parameter_value(current_native, native):
                        message = "Wartość była już ustawiona; nie wysłano ponownego zapisu."
                        success = True
                        transport_accepted = None
                        readback_confirmed = True
                    else:
                        frames_before = self._received_frame_count(self._connection)
                    # Zapis przez publiczne API PyPlumIO wartością natywną;
                    # potwierdzone modelowe skale UI odwraca native_value().
                    # Blokadę advanced/critical zdjęto decyzją użytkownika (2026-07-17);
                    # security.safe_writes_only=true przywraca dawne zachowanie.
                    # Wynik True z PyPlumIO potwierdza transport/odpowiedź ramki,
                    # ale nie dowodzi, że regulator zachował nową wartość.
                    # Zielony status wolno pokazać dopiero po zgodnym readbacku.
                        transport_accepted = bool(await device.set(name, native))
                        readback_confirmed = await self._wait_for_parameter_value(
                            device,
                            name,
                            native,
                            frames_before=frames_before,
                        )
                        success = readback_confirmed
                        if readback_confirmed:
                            message = "Zapis potwierdzony zgodną wartością po odebraniu nowej ramki."
                        elif transport_accepted:
                            message = (
                                "Polecenie zostało przyjęte przez warstwę komunikacji, "
                                "ale nie otrzymano świeżego potwierdzenia zgodnej wartości."
                            )
                        else:
                            message = "Nie otrzymano potwierdzenia przyjęcia ani zgodnej wartości."

                audit_saved = await self._safe_add_audit(
                    scope,
                    index,
                    name,
                    old_value,
                    shown_value,
                    success,
                    message,
                )
                return {
                    "success": success,
                    "status": "confirmed" if success else "unconfirmed",
                    "message": message,
                    "requested_value": shown_value,
                    "transport_accepted": transport_accepted,
                    "readback_confirmed": readback_confirmed,
                    "audit_saved": audit_saved,
                }
            except Exception as exc:
                message = str(exc)
                await self._safe_add_audit(
                    scope,
                    index,
                    name,
                    old_value,
                    shown_value,
                    False,
                    message,
                )
                raise

    def _prepare_model_parameter_range(self, parameter: Any, scope: str, name: str) -> None:
        product = (self.snapshot.get("values") or {}).get("product")
        bounds = model_parameter_range(name, scope, self._product_id(product))
        if not bounds or parameter is None:
            return
        # PyPlumIO 0.6.8 validates against ParameterValues. Correct only these
        # limits, preserving its value, parameter index, encoding and set/readback
        # path. The next controller response can still replace the metadata.
        parameter.update(replace(
            parameter.values,
            min_value=parameter._pack_value(bounds[0]),
            max_value=parameter._pack_value(bounds[1]),
        ))

    async def set_controller_power(self, enabled: bool) -> dict[str, Any]:
        if self._simulator:
            return await self.set_parameter("ecomax", 0, "ecomax_control", enabled)

        if not self._device:
            raise RuntimeError("Brak połączenia ze sterownikiem.")
        if not self._connection or not self._is_connected(self._connection):
            raise RuntimeError("Połączenie ze sterownikiem nie jest aktywne.")

        async with self._write_lock:
            item = getattr(self._device, "data", {}).get("ecomax_control")
            current_native = getattr(item, "value", item)
            old_value = self.snapshot.get("parameters", {}).get("ecomax_control", {}).get("value")
            if self._same_parameter_value(current_native, enabled):
                result = None
                confirmed = True
                message = "Stan regulatora był już ustawiony; nie wysłano ponownego polecenia."
            else:
                frames_before = self._received_frame_count(self._connection)
                result = await (self._device.turn_on() if enabled else self._device.turn_off())
                confirmed = await self._wait_for_parameter_value(
                    self._device,
                    "ecomax_control",
                    enabled,
                    frames_before=frames_before,
                )
                message = (
                    "Zmiana zasilania potwierdzona zgodnym stanem po odebraniu nowej ramki."
                    if confirmed
                    else "Polecenie wysłano, ale nie otrzymano świeżego potwierdzenia stanu regulatora."
                )
            audit_saved = await self._safe_add_audit(
                "ecomax",
                0,
                "ecomax_control",
                old_value,
                enabled,
                confirmed,
                message,
            )
            return {
                "success": confirmed,
                "status": "confirmed" if confirmed else "unconfirmed",
                "message": message,
                "transport_accepted": None if result is None else bool(result),
                "readback_confirmed": confirmed,
                "audit_saved": audit_saved,
            }

    def _resolve_device(self, scope: str, index: int) -> Any:
        if not self._device:
            raise RuntimeError("Brak połączenia ze sterownikiem.")
        if not self._connection or not self._is_connected(self._connection):
            raise RuntimeError("Połączenie ze sterownikiem nie jest aktywne.")

        if scope == "ecomax":
            return self._device

        if scope == "mixer":
            mixers = getattr(self._device, "data", {}).get("mixers", {})
            if index not in mixers and str(index) in mixers:
                index = str(index)  # type: ignore[assignment]
            if index not in mixers:
                raise KeyError(f"Nie znaleziono mieszacza {index}.")
            return mixers[index]

        raise ValueError(f"Nieobsługiwany zakres: {scope}")

    @staticmethod
    def _same_parameter_value(actual: Any, expected: Any) -> bool:
        """Porównaj odczyt sterownika z wartością wysłaną bez zgadywania skali."""
        if actual is None or expected is None:
            return actual is expected
        if isinstance(actual, bool) or isinstance(expected, bool):
            def boolean_value(value: Any) -> bool | None:
                if isinstance(value, bool):
                    return value
                if value in (0, 1):
                    return bool(value)
                normalized = str(value).lower()
                if normalized in {"true", "on", "1"}:
                    return True
                if normalized in {"false", "off", "0"}:
                    return False
                return None

            return boolean_value(actual) is boolean_value(expected) is not None
        if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
            tolerance = max(1e-6, abs(float(expected)) * 1e-6)
            return abs(float(actual) - float(expected)) <= tolerance
        return actual == expected

    async def _wait_for_parameter_value(
        self,
        device: Any,
        name: str,
        expected: Any,
        *,
        frames_before: int | None,
    ) -> bool:
        """Czekaj na zgodną wartość dopiero po postępie licznika odebranych ramek.

        Licznik jest globalny dla połączenia: dowodzi świeżości komunikacji, lecz
        sam nie dowodzi, że odświeżono dokładnie ramkę danego parametru. Dlatego
        wynik jest potwierdzeniem zgodności po nowej ramce, a nie deklaracją
        protokołowego readbacku konkretnego rejestru.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.WRITE_READBACK_TIMEOUT_SECONDS
        while True:
            item = getattr(device, "data", {}).get(name)
            actual = getattr(item, "value", item)
            frames_now = self._received_frame_count(self._connection)
            fresh_frame = (
                frames_before is not None
                and frames_now is not None
                and frames_now > frames_before
            )
            if fresh_frame and self._same_parameter_value(actual, expected):
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(self.WRITE_READBACK_INTERVAL_SECONDS)

    async def _safe_add_audit(
        self,
        scope: str,
        index: int,
        name: str,
        old_value: Any,
        requested_value: Any,
        success: bool,
        message: str,
    ) -> bool:
        """Audyt nie może zamienić wykonanego zapisu w pozornie nieudaną operację."""
        try:
            await self.database.add_audit(
                scope,
                index,
                name,
                old_value,
                requested_value,
                success,
                message,
            )
            return True
        except Exception:
            _LOGGER.exception("Nie udało się zapisać audytu operacji %s.", name)
            return False

    def _current_parameter(self, scope: str, index: int, name: str) -> Any:
        if scope == "ecomax":
            return self.snapshot.get("parameters", {}).get(name, {}).get("value")
        return (
            self.snapshot.get("mixers", {})
            .get(str(index), {})
            .get("parameters", {})
            .get(name, {})
            .get("value")
        )


