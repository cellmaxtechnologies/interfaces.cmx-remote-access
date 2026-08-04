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
from cmx_remote_access.client_adapter import RemoteClientConfig, resolve_remote_client_config
from cmx_remote_access.live_service_test import (
    LiveServiceTestConfig,
    live_service_get_json,
    resolve_live_service_test_config,
)
from cmx_remote_access.contracts import (
    REMOTE_ACCESS_PROXY_VERSION_HEADER,
    RemoteCommand,
    RemoteResult,
    health_payload,
)
from cmx_remote_access.deployment import (
    DeploymentEndpoint,
    DeploymentSettingsIdentity,
    DeploymentStation,
    deployment_settings_identity,
    find_station,
    load_station_inventory,
)
from cmx_remote_access.deployment_manifest import (
    ArtifactHash,
    ArtifactSpec,
    ContractValidationError,
    DeploymentManifest,
    DeploymentResult,
    HealthCheckSpec,
    PackageSpec,
    ServiceSpec,
    hash_artifact,
)

__all__ = [
    "AuthContext",
    "RemoteAccessSettings",
    "RemoteCommand",
    "LiveServiceTestConfig",
    "RemoteResult",
    "REMOTE_ACCESS_PROXY_VERSION_HEADER",
    "DeploymentEndpoint",
    "DeploymentSettingsIdentity",
    "DeploymentStation",
    "DeploymentManifest",
    "DeploymentResult",
    "ArtifactHash",
    "ArtifactSpec",
    "ContractValidationError",
    "HealthCheckSpec",
    "PackageSpec",
    "ServiceSpec",
    "deployment_settings_identity",
    "find_station",
    "authenticate_bearer",
    "authenticate_request",
    "ensure_client_env_file",
    "init_remote_access",
    "RemoteClientConfig",
    "live_service_get_json",
    "resolve_remote_client_config",
    "resolve_live_service_test_config",
    "load_station_inventory",
    "health_payload",
    "hash_artifact",
    "load_remote_access_settings",
    "require_roles",
    "token_role_map_from_env",
]
