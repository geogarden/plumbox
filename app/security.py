"""PIN i krótkotrwałe tokeny sesji."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import math
import os
import secrets
import threading
import time


def create_pin_hash(pin: str) -> str:
    if not pin or len(pin) < 4:
        raise ValueError("PIN musi mieć co najmniej 4 znaki.")

    salt = os.urandom(16)
    digest = hashlib.scrypt(
        pin.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return "scrypt$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_pin(pin: str, plain_pin: str | None, stored_hash: str | None) -> bool:
    if stored_hash:
        try:
            algorithm, encoded_salt, encoded_digest = stored_hash.split("$", 2)
            if algorithm != "scrypt":
                return False
            salt = base64.urlsafe_b64decode(encoded_salt.encode())
            expected = base64.urlsafe_b64decode(encoded_digest.encode())
            actual = hashlib.scrypt(
                pin.encode("utf-8"),
                salt=salt,
                n=2**14,
                r=8,
                p=1,
                dklen=len(expected),
            )
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False

    if plain_pin is None:
        return False

    return hmac.compare_digest(pin, plain_pin)


class AttemptLimiter:
    """Prosty, procesowy limit kolejnych nieudanych prób uwierzytelnienia."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = max(1, int(window_seconds))
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _active(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        active = [stamp for stamp in self._failures.get(key, []) if stamp > cutoff]
        if active:
            self._failures[key] = active
        else:
            self._failures.pop(key, None)
        return active

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            active = self._active(key, now)
            if len(active) < self.max_attempts:
                return 0
            return max(1, math.ceil(active[0] + self.window_seconds - now))

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            active = self._active(key, now)
            active.append(now)
            self._failures[key] = active

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


@dataclass(slots=True)
class Session:
    expires_at: datetime
    username: str
    role: str


class SessionManager:
    def __init__(self, session_hours: int = 12) -> None:
        self._sessions: dict[str, Session] = {}
        self._lifetime = timedelta(hours=max(1, session_hours))

    def create(self, user: dict[str, object]) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + self._lifetime
        self._sessions[token] = Session(
            expires_at=expires_at,
            username=str(user.get("username", "")),
            role=str(user.get("role", "readonly")),
        )
        self.cleanup()
        return token, expires_at

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        session = self._sessions.get(token)
        if not session:
            return None
        if session.expires_at <= datetime.now(timezone.utc):
            self._sessions.pop(token, None)
            return None
        return session

    def is_valid(self, token: str | None) -> bool:
        return self.get(token) is not None

    def revoke(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    def revoke_username(self, username: str) -> None:
        for token, session in list(self._sessions.items()):
            if session.username == username:
                self._sessions.pop(token, None)

    def cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [token for token, session in self._sessions.items() if session.expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)
