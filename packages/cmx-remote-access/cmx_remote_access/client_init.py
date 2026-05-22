from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Optional

from cmx_remote_access.client_env import upsert_client_env_values


REMOTE_TARGETS = (
    {
        "module": "pdm_api",
        "service_label": "pdm-api remote client",
        "host_key": "PDM_REMOTE_HOST",
        "port_key": "PDM_REMOTE_PORT",
        "force_key": "PDM_FORCE_HTTP",
        "default_host": "127.0.0.1",
        "default_port": "37710",
    },
    {
        "module": "active_cell_api",
        "service_label": "active-cell-pp-api remote client",
        "host_key": "PP_REMOTE_HOST",
        "port_key": "PP_REMOTE_PORT",
        "force_key": "PP_FORCE_HTTP",
        "default_host": "127.0.0.1",
        "default_port": "8765",
    },
)


def _read_env_value(env_path: Path, key: str) -> str:
    if not env_path.exists():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() == key:
            return value.strip()
    return ""


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
    target = Path(env_path) if env_path is not None else (Path.cwd() / ".env")
    current_host = _read_env_value(target, host_key) or default_host
    current_port = _read_env_value(target, port_key) or default_port
    current_token = _read_env_value(target, token_key)

    host = input(f"{host_key} [{current_host}]: ").strip() or current_host
    port_prompt = f"{port_key}"
    if current_port:
        port_prompt += f" [{current_port}]"
    port = input(f"{port_prompt}: ").strip() or current_port
    token_prompt = token_key
    if current_token:
        token_prompt += " [keep existing]"
    token = input(f"{token_prompt}: ").strip()

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


def main() -> None:
    detected = [cfg for cfg in REMOTE_TARGETS if importlib.util.find_spec(cfg["module"]) is not None]
    if not detected:
        raise SystemExit("No supported CRA consumer package detected in this environment.")

    for cfg in detected:
        print(f"\n=== {cfg['service_label']} ===")
        init_remote_access(
            service_label=cfg["service_label"],
            host_key=cfg["host_key"],
            port_key=cfg["port_key"],
            force_key=cfg["force_key"],
            default_host=cfg["default_host"],
            default_port=cfg["default_port"],
        )
