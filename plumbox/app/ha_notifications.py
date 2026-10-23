"""Powiadomienia HA przez lokalny proxy Supervisor; token nigdy nie trafia do UI."""
from __future__ import annotations
import asyncio
import json
import os
import re
import urllib.error
import urllib.request


def valid_target(target):
    return bool(re.fullmatch(r"mobile_app_[a-z0-9_]+", target or ""))


class HomeAssistantNotifications:
    @property
    def available(self):
        return bool(os.environ.get("SUPERVISOR_TOKEN"))

    def request(self, path, payload=None):
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            raise RuntimeError("Brak dostępu do Home Assistant. Funkcja wymaga dodatku HA z homeassistant_api: true.")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            "http://supervisor/core/api/" + path, data=body,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Home Assistant odrzucił żądanie (HTTP {exc.code}).") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError("Nie można połączyć się z Home Assistant.") from None

    async def targets(self):
        groups = await asyncio.to_thread(self.request, "services")
        return sorted(name for g in groups if g.get("domain") == "notify" for name in g.get("services", {}) if valid_target(name))

    async def send(self, target, message, event_id):
        if not valid_target(target):
            raise ValueError("Wybierz telefon z listy usług mobile_app.")
        await asyncio.to_thread(self.request, "services/notify/" + target, {
            "title": "PlumBox", "message": message,
            "data": {"tag": "plumbox-" + event_id, "group": "plumbox"},
        })
