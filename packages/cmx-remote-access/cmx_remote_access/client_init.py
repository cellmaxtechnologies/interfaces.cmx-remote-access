from __future__ import annotations

from pathlib import Path
from typing import Optional

from cmx_remote_access.client_env import upsert_client_env_values


def init_remote_access(
    *,
    service_label: str,
    host_key: str,
    port_key: str,
    force_key: str,
    token_key: str = "SERVICE_API_TOKEN",
    default_host: str = "127.0.0.1",
    default_port: str = "",
    env_path: str | Path | None = None,
) -> Path:
    host = input(f"{host_key} [{default_host}]: ").strip() or default_host
    port_prompt = f"{port_key}"
    if default_port:
        port_prompt += f" [{default_port}]"
    port = input(f"{port_prompt}: ").strip() or default_port
    token = input(f"{token_key}: ").strip()

    values = {
        host_key: host,
        token_key: token,
        force_key: "1",
    }
    if port:
        values[port_key] = port

    written = upsert_client_env_values(
        values=values,
        env_path=env_path,
        service_label=service_label,
    )
    print(f"Wrote {written}")
    return written
