"""Environment-driven settings (same env names as ``cmx-production-system`` platform-api where possible)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class RemoteAccessSettings:
    """Bearer-token auth for service-to-service and operator clients."""

    service_token: str
    admin_token: str
    auth_strict: bool


def load_remote_access_settings() -> RemoteAccessSettings:
    """
    - ``SERVICE_API_TOKEN`` — primary service token (Bearer).
    - ``ADMIN_API_TOKEN`` — optional elevated token (same header; role resolved in auth).
    - ``AUTH_STRICT`` — if true, missing/invalid Bearer returns 401 (recommended on LAN).
    """
    return RemoteAccessSettings(
        service_token=(os.getenv("SERVICE_API_TOKEN") or "").strip(),
        admin_token=(os.getenv("ADMIN_API_TOKEN") or "").strip(),
        auth_strict=_truthy(os.getenv("AUTH_STRICT"), default=False),
    )
