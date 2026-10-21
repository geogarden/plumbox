from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

import yaml

USERS_PATH = Path(os.environ.get("PLUMBOX_USERS", "/etc/plumbox/users.yaml"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _last_login_needs_update(value: Any, now: datetime) -> bool:
    try:
        previous = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        return now - previous.astimezone(timezone.utc) >= timedelta(hours=1)
    except (TypeError, ValueError):
        return True


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if len(password or "") < 8:
        raise ValueError("Hasło musi mieć co najmniej 8 znaków.")
    iterations = 260_000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt_text), int(iterations_text))
        return hmac.compare_digest(actual, _unb64(digest_text))
    except Exception:
        return False


def load_users(path: Path = USERS_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"users": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        data = {}
    users = data.setdefault("users", {})
    if not isinstance(users, dict):
        data["users"] = {}
    return data


def save_users(data: dict[str, Any], path: Path = USERS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="plumbox-users-", suffix=".yaml", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
            handle.flush(); os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def public_user(username: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": username,
        "display_name": record.get("display_name") or username,
        "role": record.get("role", "user"),
        "enabled": bool(record.get("enabled", True)),
        "created_at": record.get("created_at"),
        "last_login_at": record.get("last_login_at"),
    }


def ensure_initial_admin(path: Path = USERS_PATH, password: str | None = None) -> str | None:
    data = load_users(path)
    if data.get("users"):
        return None
    initial = password or secrets.token_urlsafe(12)
    data["users"] = {
        "admin": {
            "display_name": "Administrator",
            "role": "admin",
            "enabled": True,
            "password_hash": hash_password(initial),
            "created_at": _now(),
        }
    }
    save_users(data, path)
    return initial


def authenticate(username: str, password: str, path: Path = USERS_PATH) -> dict[str, Any] | None:
    username = (username or "").strip()
    data = load_users(path)
    record = data.get("users", {}).get(username)
    if not isinstance(record, dict) or not bool(record.get("enabled", True)):
        return None
    if not verify_password(password or "", str(record.get("password_hash", ""))):
        return None
    now = datetime.now(timezone.utc)
    if _last_login_needs_update(record.get("last_login_at"), now):
        record["last_login_at"] = now.isoformat()
        try:
            save_users(data, path)
        except OSError:
            # Logowanie nie powinno padać tylko dlatego, że nie udało się zapisać
            # kosmetycznego pola last_login_at. Uprawnienia katalogu naprawia instalator,
            # ale ten fallback chroni przed błędem 500 po ręcznej migracji.
            pass
    return public_user(username, record)


def list_users(path: Path = USERS_PATH) -> list[dict[str, Any]]:
    data = load_users(path)
    return [public_user(username, record) for username, record in sorted(data.get("users", {}).items())]


def _valid_username(username: str) -> bool:
    return bool(username) and len(username) <= 64 and username.replace("_", "").replace("-", "").replace(".", "").isalnum()


def add_user(username: str, password: str, role: str = "user", display_name: str = "", path: Path = USERS_PATH) -> dict[str, Any]:
    username = (username or "").strip()
    if not _valid_username(username):
        raise ValueError("Login może zawierać litery, cyfry, kropkę, myślnik i podkreślenie.")
    if role not in {"admin", "user", "readonly"}:
        raise ValueError("Rola musi być admin, user albo readonly.")
    data = load_users(path)
    if username in data.get("users", {}):
        raise ValueError("Taki użytkownik już istnieje.")
    data.setdefault("users", {})[username] = {
        "display_name": display_name or username,
        "role": role,
        "enabled": True,
        "password_hash": hash_password(password),
        "created_at": _now(),
    }
    save_users(data, path)
    return public_user(username, data["users"][username])


def verify_user_password(username: str, password: str, path: Path = USERS_PATH) -> bool:
    """Sprawdza hasło bez efektów ubocznych logowania (last_login_at)."""
    record = load_users(path).get("users", {}).get((username or "").strip())
    if not isinstance(record, dict) or not bool(record.get("enabled", True)):
        return False
    return verify_password(password or "", str(record.get("password_hash", "")))


def set_password(username: str, new_password: str, path: Path = USERS_PATH) -> None:
    data = load_users(path)
    if username not in data.get("users", {}):
        raise ValueError("Nie znaleziono użytkownika.")
    data["users"][username]["password_hash"] = hash_password(new_password)
    save_users(data, path)


def delete_user(username: str, path: Path = USERS_PATH) -> None:
    data = load_users(path)
    users = data.get("users", {})
    if username not in users:
        raise ValueError("Nie znaleziono użytkownika.")
    active_admins = [u for u, r in users.items() if r.get("role") == "admin" and r.get("enabled", True)]
    if username in active_admins and len(active_admins) <= 1:
        raise ValueError("Nie można usunąć ostatniego aktywnego administratora.")
    users.pop(username, None)
    save_users(data, path)


class UserSessionStore:
    def __init__(self, hours: int = 24) -> None:
        self.hours = max(1, min(int(hours), 168))
        self.sessions: dict[str, dict[str, Any]] = {}

    def create(self, user: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(36)
        self.sessions[token] = {"user": user, "expires": datetime.now(timezone.utc) + timedelta(hours=self.hours)}
        self.cleanup()
        return token

    def get(self, token: str | None) -> dict[str, Any] | None:
        self.cleanup()
        if not token:
            return None
        record = self.sessions.get(token)
        if not record:
            return None
        return record.get("user") if isinstance(record.get("user"), dict) else None

    def revoke(self, token: str | None) -> None:
        if token:
            self.sessions.pop(token, None)

    def revoke_username(self, username: str) -> None:
        for token, record in list(self.sessions.items()):
            user = record.get("user")
            if isinstance(user, dict) and user.get("username") == username:
                self.sessions.pop(token, None)

    def cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        for token, record in list(self.sessions.items()):
            if record.get("expires") <= now:
                self.sessions.pop(token, None)
