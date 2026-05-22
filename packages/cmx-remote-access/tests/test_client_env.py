from __future__ import annotations

from pathlib import Path

from cmx_remote_access.client_env import ensure_client_env_file


def test_ensure_client_env_file_writes_missing_keys_only(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("SERVICE_API_TOKEN=abc123\n", encoding="utf-8")

    written = ensure_client_env_file(
        defaults={
            "API_HOST": "127.0.0.1",
            "API_PORT": "37710",
            "SERVICE_API_TOKEN": "",
            "FORCE_HTTP": "1",
        },
        env_path=env_path,
        service_label="remote client",
    )

    assert written == env_path
    text = env_path.read_text(encoding="utf-8")
    assert "SERVICE_API_TOKEN=abc123" in text
    assert "API_HOST=127.0.0.1" in text
    assert "API_PORT=37710" in text
    assert "FORCE_HTTP=1" in text
