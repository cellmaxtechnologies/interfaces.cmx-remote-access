"""Optional dev HTTP reverse proxy (same package as contracts / auth)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def proxy_stamp_version() -> str:
    """Version string stamped on ``X-CMX-Remote-Proxy-Version`` (library distribution version)."""
    try:
        return version("cmx-remote-access")
    except PackageNotFoundError:
        return "0.0.0"
