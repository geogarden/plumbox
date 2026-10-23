"""Drobne, współdzielone pomocniki bez zależności od reszty aplikacji.

Wydzielone, żeby te same 2-3 linijki nie były kopiowane po modułach
(``_is_scalar`` był wcześniej zduplikowany w ``mqtt`` i ``controller_profile``,
a domyślny tryb profilu odczytywany „na piechotę” w kilku miejscach).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DEFAULT_PROFILE_MODE = "fixed_ecomax860p4"


def is_scalar(value: Any) -> bool:
    """Czy wartość nadaje się do publikacji jako pojedyncze pole (MQTT, encja)."""
    return isinstance(value, (str, int, float, bool)) or value is None


def utc_now_iso() -> str:
    """Znacznik czasu UTC w ISO 8601 — wspólny format dla snapshotów i audytu."""
    return datetime.now(timezone.utc).isoformat()


def profile_mode(config: Any) -> str:
    """Tryb profilu z konfiguracji, z bezpiecznym fallbackiem.

    Przyjmuje cały ``AppConfig`` albo sam ``ProfileConfig`` — dzięki temu wołający
    nie musi pamiętać o ``getattr(..., "mode", DEFAULT_PROFILE_MODE)``.
    """
    profile = getattr(config, "profile", config)
    return str(getattr(profile, "mode", DEFAULT_PROFILE_MODE))
