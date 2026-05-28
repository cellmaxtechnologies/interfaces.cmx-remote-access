from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class LiveServiceTestConfig:
    """Environment-derived target for strict installed-service smoke tests."""

    base_url: str
    service_token: str


def resolve_live_service_test_config(
    *,
    service_label: str,
    url_key: str,
    token_key: str = "SERVICE_API_TOKEN",
) -> LiveServiceTestConfig:
    """Resolve the common CRA live-service test target from exact env keys.

    The helper is intentionally strict: it reads only ``url_key`` and
    ``token_key`` and raises when either is missing. It does not create or edit
    ``.env`` files, and it does not fall back to service-specific aliases.
    """
    base_url = os.environ.get(url_key, "").strip().rstrip("/")
    service_token = os.environ.get(token_key, "").strip()
    if not base_url or not service_token:
        raise AssertionError(
            f"{service_label} installed-service tests require {url_key} and {token_key}."
        )
    return LiveServiceTestConfig(base_url=base_url, service_token=service_token)


def live_service_get_json(
    url: str,
    *,
    service_token: str | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """GET a JSON endpoint for strict installed-service smoke tests."""
    headers = {"Accept": "application/json"}
    if service_token:
        headers["Authorization"] = f"Bearer {service_token}"
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise AssertionError(f"Installed service request failed for {url}: {exc}") from None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Installed service returned non-JSON for {url}: {exc}") from None
    if not isinstance(payload, dict):
        raise AssertionError(f"Installed service returned JSON {type(payload).__name__}, expected object.")
    return payload
