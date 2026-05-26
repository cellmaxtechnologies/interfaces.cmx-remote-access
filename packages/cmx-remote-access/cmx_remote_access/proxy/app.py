"""ASGI app: forward everything to ``CMX_PROXY_UPSTREAM_URL``."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Iterable
from urllib.parse import urlparse

import httpx
from cmx_remote_access.contracts import REMOTE_ACCESS_PROXY_VERSION_HEADER
from fastapi import FastAPI, Request, Response

from cmx_remote_access.proxy import proxy_stamp_version

logger = logging.getLogger(__name__)

_HOP: frozenset[str] = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
    }
)


def _filter_request_headers(items: Iterable[tuple[str, str]], upstream_netloc: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in items:
        if k.lower() in _HOP:
            continue
        out[k] = v
    out["Host"] = upstream_netloc
    return out


def _filter_response_headers(items: Iterable[tuple[str, str]], stamp: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in items:
        if k.lower() in _HOP:
            continue
        out[k] = v
    out[REMOTE_ACCESS_PROXY_VERSION_HEADER] = stamp
    return out


def _join_upstream(base: str, path: str, query: str) -> str:
    p = path.lstrip("/")
    url = f"{base}/{p}" if p else base
    if query:
        url = f"{url}?{query}"
    return url


def create_app(upstream_base_url: str) -> FastAPI:
    """Create a lightweight reverse proxy for forwarding to a station API."""
    parsed = urlparse(upstream_base_url)
    upstream_netloc = parsed.netloc
    stamp = proxy_stamp_version()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
            app.state.http = client
            yield

    app = FastAPI(
        title="cmx-remote-proxy",
        version=stamp,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/proxy/health")
    async def proxy_health() -> dict[str, str]:
        """Proxy process only (does not call upstream)."""
        return {"status": "ok", "role": "cmx-remote-proxy", "version": stamp}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def forward(path: str, request: Request) -> Response:
        """Forward one incoming HTTP request to the configured upstream service."""
        client: httpx.AsyncClient = request.app.state.http
        url = _join_upstream(upstream_base_url, path, request.url.query)
        body = await request.body()
        req_headers = _filter_request_headers(request.headers.items(), upstream_netloc)

        try:
            upstream = await client.request(
                request.method,
                url,
                headers=req_headers,
                content=body if body else None,
            )
        except httpx.RequestError as e:
            logger.warning("upstream error: %s", e)
            return Response(
                content=f"Upstream request failed: {e}".encode(),
                status_code=502,
                headers={REMOTE_ACCESS_PROXY_VERSION_HEADER: stamp},
            )

        resp_headers = _filter_response_headers(upstream.headers.items(), stamp)
        return Response(content=upstream.content, status_code=upstream.status_code, headers=resp_headers)

    return app
