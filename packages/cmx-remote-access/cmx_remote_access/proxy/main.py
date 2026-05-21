"""CLI entry: ``poetry run cmx-remote-proxy``."""

from __future__ import annotations


def run() -> None:
    import uvicorn

    from cmx_remote_access.proxy.app import create_app
    from cmx_remote_access.proxy.config import load_proxy_settings

    s = load_proxy_settings()
    app = create_app(s.upstream_base_url)
    uvicorn.run(app, host=s.host, port=s.port, log_level="info")


if __name__ == "__main__":
    run()
