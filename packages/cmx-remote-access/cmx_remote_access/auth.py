"""Bearer authentication (compatible with ``platform-api`` / ``pyramid-bridge`` patterns)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from cmx_remote_access.config import RemoteAccessSettings, load_remote_access_settings


@dataclass(frozen=True, slots=True)
class AuthContext:
    role: str
    principal: str


def token_role_map_from_env(settings: RemoteAccessSettings) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if settings.service_token:
        mapping[settings.service_token] = "service"
    if settings.admin_token:
        mapping[settings.admin_token] = "admin"
    return mapping


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    alt = request.headers.get("X-App-Token") or request.headers.get("X-API-Key") or ""
    return alt.strip()


def authenticate_request(request: Request, settings: RemoteAccessSettings) -> AuthContext:
    """Resolve role from Bearer (or ``X-App-Token`` / ``X-API-Key``)."""
    token = _extract_bearer(request)
    roles = token_role_map_from_env(settings)
    if token and token in roles:
        r = roles[token]
        return AuthContext(role=r, principal=f"token:{r}")
    if settings.auth_strict:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
        )
    return AuthContext(role="anonymous", principal="anonymous")


def require_roles(settings: RemoteAccessSettings, allowed: frozenset[str]):
    """FastAPI dependency: only listed roles when ``AUTH_STRICT`` is on."""

    def _dep(request: Request) -> AuthContext:
        ctx = authenticate_request(request, settings)
        if settings.auth_strict and ctx.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return ctx

    return Depends(_dep)


def authenticate_bearer(request: Request) -> AuthContext:
    """Convenience using ``load_remote_access_settings()`` (for small apps)."""
    return authenticate_request(request, load_remote_access_settings())
