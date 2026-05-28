from __future__ import annotations

import pytest

from cmx_remote_access.live_service_test import resolve_live_service_test_config


def test_resolve_live_service_test_config_requires_exact_url_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_API_URL", raising=False)
    monkeypatch.delenv("SERVICE_API_TOKEN", raising=False)

    with pytest.raises(AssertionError, match="MY_API_URL and SERVICE_API_TOKEN"):
        resolve_live_service_test_config(service_label="my-api", url_key="MY_API_URL")


def test_resolve_live_service_test_config_reads_exact_url_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_API_URL", "http://127.0.0.1:1234/")
    monkeypatch.setenv("SERVICE_API_TOKEN", "abc123")

    config = resolve_live_service_test_config(service_label="my-api", url_key="MY_API_URL")

    assert config.base_url == "http://127.0.0.1:1234"
    assert config.service_token == "abc123"
