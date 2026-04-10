import json
import os
import sys
from typing import Optional, Tuple

import requests
from requests import exceptions as req_exc


def load_root_env() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    env_path = os.path.join(repo_root, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


def env(key: str) -> Optional[str]:
    return os.environ.get(key, "").strip() or None


def _parse_timeout() -> Tuple[float, float]:
    raw = env("PDM_API_TIMEOUT")
    if not raw:
        return 5.0, 15.0
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    try:
        if len(parts) == 1:
            value = float(parts[0])
            return value, value
        return float(parts[0]), float(parts[1])
    except ValueError:
        return 5.0, 15.0


def main() -> int:
    load_root_env()

    base_url = env("PDM_API_URL")
    api_key = env("PDM_API_KEY")
    username = env("PDM_USERNAME")
    password = env("PDM_PASSWORD")
    vault_name = env("PDM_VAULT_NAME")
    connect_timeout, read_timeout = _parse_timeout()
    if not base_url:
        print("PDM_API_URL is not set.")
        return 2
    base_url = base_url.rstrip("/")

    print(f"Using PDM_API_URL={base_url}")
    print(f"Timeouts: connect={connect_timeout}s read={read_timeout}s")

    try:
        health = requests.get(f"{base_url}/health", timeout=(connect_timeout, read_timeout))
        print(f"GET /health -> {health.status_code}")
        try:
            print(json.dumps(health.json(), indent=2))
        except Exception:
            print(health.text)
    except req_exc.RequestException as exc:
        print(f"GET /health failed: {exc}")
        return 3

    if api_key:
        headers = {"X-API-Key": api_key}
        if not (username and password and vault_name):
            print("Missing PDM_USERNAME/PDM_PASSWORD/PDM_VAULT_NAME in .env; skipping authenticated search.")
            return 0
        payload = {"username": username, "password": password, "vault_name": vault_name}
        try:
            response = requests.post(
                f"{base_url}/pdm/search",
                json=payload,
                headers=headers,
                timeout=(connect_timeout, read_timeout),
            )
            print(f"POST /pdm/search (with API key) -> {response.status_code}")
            try:
                print(json.dumps(response.json(), indent=2))
            except Exception:
                print(response.text)
        except req_exc.ReadTimeout as exc:
            print(f"POST /pdm/search timed out (read). {exc}")
            return 4
        except req_exc.RequestException as exc:
            print(f"POST /pdm/search failed: {exc}")
            return 4
    else:
        try:
            response = requests.post(
                f"{base_url}/pdm/search",
                json={},
                timeout=(connect_timeout, read_timeout),
            )
            print(f"POST /pdm/search (no API key) -> {response.status_code}")
            try:
                print(json.dumps(response.json(), indent=2))
            except Exception:
                print(response.text)
        except req_exc.RequestException as exc:
            print(f"POST /pdm/search failed: {exc}")
            return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
