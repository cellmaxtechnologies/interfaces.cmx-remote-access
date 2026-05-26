"""Command/result envelopes aligned with ``hardware-gateway`` / production-system style."""

from __future__ import annotations

# Optional dev edge proxy (``cmx_remote_access.proxy``) stamps this on every proxied response.
REMOTE_ACCESS_PROXY_VERSION_HEADER = "X-CMX-Remote-Proxy-Version"

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class RemoteCommand:
    """What a client asks a station service to do."""

    operation: str
    params: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 300_000
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteResult:
    """Normalized outcome (maps easily to HTTP and to dashboard tooling)."""

    ok: bool
    operation: str
    duration_ms: int
    payload: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    correlation_id: str | None = None

    @staticmethod
    def now_timestamp() -> str:
        """Return the current UTC timestamp in ISO-8601 form."""
        return datetime.now(timezone.utc).isoformat()


def health_payload(
    *,
    service_id: str,
    version: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Standard ``GET /health`` body fragment for remote-access services."""
    body: dict[str, Any] = {
        "status": "ok",
        "service_id": service_id,
        "version": version,
        "timestamp_utc": RemoteResult.now_timestamp(),
    }
    if extra:
        body["extra"] = extra
    return body
