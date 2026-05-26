from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from cmx_remote_access.client_env import ensure_client_env_file
from cmx_remote_access.config import load_remote_access_settings


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class RemoteClientConfig:
    """Resolved client transport settings for a CRA-backed package."""

    use_http: bool
    base_url: str
    service_token: str


def resolve_remote_client_config(
    *,
    service_label: str,
    host_key: str,
    port_key: str,
    force_key: str,
    defaults: Mapping[str, str],
    explicit_url_key: str | None = None,
) -> RemoteClientConfig:
    """Resolve direct-Python versus HTTP mode from shared remote-access env vars."""
    base_url = ""
    if explicit_url_key:
        base_url = os.environ.get(explicit_url_key, "").strip().rstrip("/")
    if not base_url:
        host = os.environ.get(host_key, "").strip()
        port = os.environ.get(port_key, "").strip()
        if host and port:
            probe_host = "127.0.0.1" if host == "0.0.0.0" else host
            base_url = f"http://{probe_host}:{port}"

    use_http = _env_flag(force_key) or bool(base_url)
    service_token = load_remote_access_settings().service_token

    if use_http and (not base_url or not service_token):
        env_path = ensure_client_env_file(defaults=defaults, service_label=service_label)
        raise RuntimeError(
            f"Remote mode for {service_label} requires {host_key}/{port_key} and SERVICE_API_TOKEN. "
            f"Created/updated {env_path} with the needed keys."
        )

    return RemoteClientConfig(
        use_http=use_http,
        base_url=base_url,
        service_token=service_token,
    )
