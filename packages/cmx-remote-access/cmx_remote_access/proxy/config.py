"""Environment for the dev proxy."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ProxySettings:
    """Runtime settings for the optional CRA development proxy."""

    upstream_base_url: str
    host: str
    port: int


def load_proxy_settings() -> ProxySettings:
    """Load proxy upstream and bind settings from environment."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    raw = (os.environ.get("CMX_PROXY_UPSTREAM_URL") or "").strip()
    if not raw:
        raise RuntimeError(
            "Set CMX_PROXY_UPSTREAM_URL (e.g. http://127.0.0.1:8765) to the station API base URL."
        )
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError(f"CMX_PROXY_UPSTREAM_URL must be an http(s) URL with host: {raw!r}")

    host = (os.environ.get("CMX_PROXY_HOST") or "127.0.0.1").strip()
    port_s = (os.environ.get("CMX_PROXY_PORT") or "8780").strip()
    port = int(port_s)

    base = raw.rstrip("/")
    return ProxySettings(upstream_base_url=base, host=host, port=port)
