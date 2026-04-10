import os

import pytest
import requests


def _load_root_env() -> None:
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


_load_root_env()


def _api_url() -> str:
    return os.environ.get("PDM_API_URL", "").strip().rstrip("/")


@pytest.mark.http
def test_health_endpoint_reachable():
    base_url = _api_url()
    if not base_url:
        pytest.skip("PDM_API_URL not set; skipping HTTP API health check.")
    response = requests.get(f"{base_url}/health", timeout=10)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    assert payload.get("status") == "ok"


@pytest.mark.http
def test_api_key_required_when_configured():
    base_url = _api_url()
    api_key = os.environ.get("PDM_API_KEY", "").strip()
    if not base_url:
        pytest.skip("PDM_API_URL not set; skipping HTTP API auth check.")
    if not api_key:
        pytest.skip("PDM_API_KEY not set; server may not require API key.")
    response = requests.post(f"{base_url}/pdm/search", json={}, timeout=10)
    assert response.status_code == 401
