import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cmx_remote_access.auth import require_roles
from cmx_remote_access.config import RemoteAccessSettings


def test_require_roles_strict_blocks_anonymous(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_API_TOKEN", "svc-secret")
    monkeypatch.setenv("AUTH_STRICT", "true")
    from cmx_remote_access.config import load_remote_access_settings

    settings = load_remote_access_settings()
    app = FastAPI()

    @app.get("/x")
    def x(_=require_roles(settings, frozenset({"service", "admin"}))):
        return {"ok": True}

    c = TestClient(app)
    r = c.get("/x")
    assert r.status_code == 401
    r2 = c.get("/x", headers={"Authorization": "Bearer svc-secret"})
    assert r2.status_code == 200
