"""cmx-remote-access: shared remote service contracts and FastAPI security."""

from cmx_remote_access.auth import (
    AuthContext,
    authenticate_bearer,
    authenticate_request,
    require_roles,
    token_role_map_from_env,
)
from cmx_remote_access.config import RemoteAccessSettings, load_remote_access_settings
from cmx_remote_access.client_env import ensure_client_env_file
from cmx_remote_access.client_init import init_remote_access
from cmx_remote_access.contracts import (
    REMOTE_ACCESS_PROXY_VERSION_HEADER,
    RemoteCommand,
    RemoteResult,
    health_payload,
)

__all__ = [
    "AuthContext",
    "RemoteAccessSettings",
    "RemoteCommand",
    "RemoteResult",
    "REMOTE_ACCESS_PROXY_VERSION_HEADER",
    "authenticate_bearer",
    "authenticate_request",
    "ensure_client_env_file",
    "init_remote_access",
    "health_payload",
    "load_remote_access_settings",
    "require_roles",
    "token_role_map_from_env",
]
