"""Strict, transport-neutral contracts for unattended service deployment."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
DeploymentStatus = Literal["succeeded", "failed"]

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE_DEPLOYMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_ZIP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.zip$")
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_SHA1 = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_RELATIVE_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_ARCHIVE_BYTES = 10 * 1024 * 1024 * 1024


class ContractValidationError(ValueError):
    """Raised when deployment JSON does not exactly match schema v1."""


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{field} must be a JSON object")
    return value


def _keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unknown:
            details.append(f"unknown {unknown}")
        raise ContractValidationError(f"{field} has {'; '.join(details)}")


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field} must be a string")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field} must be an integer")
    return value


def _safe_name(value: str, field: str, pattern: re.Pattern[str] = _SAFE_NAME) -> str:
    if not pattern.fullmatch(value) or ".." in value:
        raise ContractValidationError(f"{field} contains unsafe characters")
    return value


def _semver(value: str, field: str) -> str:
    if not _SEMVER.fullmatch(value):
        raise ContractValidationError(f"{field} must be SemVer")
    return value


def _sha(value: str, pattern: re.Pattern[str], field: str) -> str:
    if not pattern.fullmatch(value):
        raise ContractValidationError(f"{field} is malformed")
    return value.lower()


def _timestamp(value: str, field: str) -> datetime:
    if "T" not in value or not (value.endswith("Z") or value.endswith("+00:00")):
        raise ContractValidationError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ContractValidationError(f"{field} is malformed") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContractValidationError(f"{field} must be UTC")
    return parsed


def _timestamp_text(value: datetime, field: str) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ContractValidationError(f"{field} must be timezone-aware UTC")
    utc = value.astimezone(timezone.utc)
    timespec = "microseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def _relative_executable(value: str) -> str:
    if not value or value.startswith(("/", "\\")) or "\\" in value or ":" in value:
        raise ContractValidationError("service.executablePath must be a portable relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or not _RELATIVE_PART.fullmatch(part) for part in parts):
        raise ContractValidationError("service.executablePath contains an unsafe path segment")
    return value


def _health_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ContractValidationError("health.url is malformed") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise ContractValidationError(
            "health.url must be an unauthenticated loopback HTTP URL without a query or fragment"
        )
    return value


def _json_loads(raw: str | bytes | bytearray) -> Mapping[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractValidationError(f"duplicate JSON field {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=strict_object,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ContractValidationError(f"invalid JSON constant {constant}")
            ),
        )
    except json.JSONDecodeError as exc:
        raise ContractValidationError("malformed JSON") from exc
    return _object(value, "document")


def _json_dumps(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, slots=True)
class PackageSpec:
    name: str
    version: str
    source_sha: str

    def __post_init__(self) -> None:
        _safe_name(self.name, "package.name", _SAFE_PACKAGE_NAME)
        _semver(self.version, "package.version")
        object.__setattr__(self, "source_sha", _sha(self.source_sha, _SHA1, "package.sourceSha"))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "sourceSha": self.source_sha}

    @classmethod
    def from_dict(cls, value: Any) -> PackageSpec:
        item = _object(value, "package")
        _keys(item, {"name", "version", "sourceSha"}, "package")
        return cls(
            name=_string(item["name"], "package.name"),
            version=_string(item["version"], "package.version"),
            source_sha=_string(item["sourceSha"], "package.sourceSha"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    file_name: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if (
            not _SAFE_ZIP_NAME.fullmatch(self.file_name)
            or self.file_name in {".", ".."}
            or ".." in self.file_name
        ):
            raise ContractValidationError("artifact.fileName must be a safe ZIP basename")
        if not 1 <= self.size <= _MAX_ARCHIVE_BYTES:
            raise ContractValidationError("artifact.size must be between 1 byte and 10 GiB")
        object.__setattr__(self, "sha256", _sha(self.sha256, _SHA256, "artifact.sha256"))

    def to_dict(self) -> dict[str, Any]:
        return {"fileName": self.file_name, "size": self.size, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, value: Any) -> ArtifactSpec:
        item = _object(value, "artifact")
        _keys(item, {"fileName", "size", "sha256"}, "artifact")
        return cls(
            file_name=_string(item["fileName"], "artifact.fileName"),
            size=_integer(item["size"], "artifact.size"),
            sha256=_string(item["sha256"], "artifact.sha256"),
        )


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    name: str
    executable_path: str

    def __post_init__(self) -> None:
        _safe_name(self.name, "service.name")
        _relative_executable(self.executable_path)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "executablePath": self.executable_path}

    @classmethod
    def from_dict(cls, value: Any) -> ServiceSpec:
        item = _object(value, "service")
        _keys(item, {"name", "executablePath"}, "service")
        return cls(
            name=_string(item["name"], "service.name"),
            executable_path=_string(item["executablePath"], "service.executablePath"),
        )


@dataclass(frozen=True, slots=True)
class HealthCheckSpec:
    url: str
    service_id: str
    expected_version: str

    def __post_init__(self) -> None:
        _health_url(self.url)
        _safe_name(self.service_id, "health.serviceId")
        _semver(self.expected_version, "health.expectedVersion")

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "serviceId": self.service_id, "expectedVersion": self.expected_version}

    @classmethod
    def from_dict(cls, value: Any) -> HealthCheckSpec:
        item = _object(value, "health")
        _keys(item, {"url", "serviceId", "expectedVersion"}, "health")
        return cls(
            url=_string(item["url"], "health.url"),
            service_id=_string(item["serviceId"], "health.serviceId"),
            expected_version=_string(item["expectedVersion"], "health.expectedVersion"),
        )


@dataclass(frozen=True, slots=True)
class DeploymentManifest:
    deployment_id: str
    package: PackageSpec
    artifact: ArtifactSpec
    service: ServiceSpec
    health: HealthCheckSpec
    created_at: datetime
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContractValidationError(f"schemaVersion must be {SCHEMA_VERSION}")
        _safe_name(self.deployment_id, "deploymentId", _SAFE_DEPLOYMENT_ID)
        _timestamp_text(self.created_at, "createdAt")
        if self.health.expected_version != self.package.version:
            raise ContractValidationError("health.expectedVersion must equal package.version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "deploymentId": self.deployment_id,
            "package": self.package.to_dict(),
            "artifact": self.artifact.to_dict(),
            "service": self.service.to_dict(),
            "health": self.health.to_dict(),
            "createdAt": _timestamp_text(self.created_at, "createdAt"),
        }

    def to_json(self) -> str:
        """Serialize with stable key ordering and no insignificant whitespace."""

        return _json_dumps(self.to_dict())

    @classmethod
    def from_dict(cls, value: Any) -> DeploymentManifest:
        item = _object(value, "manifest")
        _keys(
            item,
            {"schemaVersion", "deploymentId", "package", "artifact", "service", "health", "createdAt"},
            "manifest",
        )
        return cls(
            schema_version=_integer(item["schemaVersion"], "schemaVersion"),
            deployment_id=_string(item["deploymentId"], "deploymentId"),
            package=PackageSpec.from_dict(item["package"]),
            artifact=ArtifactSpec.from_dict(item["artifact"]),
            service=ServiceSpec.from_dict(item["service"]),
            health=HealthCheckSpec.from_dict(item["health"]),
            created_at=_timestamp(_string(item["createdAt"], "createdAt"), "createdAt"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes | bytearray) -> DeploymentManifest:
        return cls.from_dict(_json_loads(raw))


@dataclass(frozen=True, slots=True)
class ArtifactHash:
    size: int
    sha256: str


def hash_artifact(path: str | Path, chunk_size: int = 1024 * 1024) -> ArtifactHash:
    """Return artifact byte size and SHA-256 without loading it into memory."""

    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(chunk_size), b""):
            size += len(chunk)
            digest.update(chunk)
    return ArtifactHash(size=size, sha256=digest.hexdigest())


def _json_value(value: Any, field: str) -> Any:
    """Validate a direct-construction value as finite, JSON-compatible data."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError(f"{field} contains a non-finite number")
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{field}[]") for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractValidationError(f"{field} keys must be strings")
            result[key] = _json_value(item, f"{field}.{key}")
        return result
    raise ContractValidationError(f"{field} contains a non-JSON value")


def _release_path(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not value.strip() or len(value) > 32767 or any(ord(character) < 32 for character in value):
        raise ContractValidationError(f"{field} must be a non-blank station path")
    # Results are evidence only, but accepting relative paths would make their
    # meaning depend on whichever process reads them.
    if not re.match(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+)", value):
        raise ContractValidationError(f"{field} must be an absolute Windows path")
    return value


@dataclass(frozen=True, slots=True)
class DeploymentResult:
    deployment_id: str
    status: DeploymentStatus
    updated_at: datetime
    previous_release: str | None
    new_release: str | None
    artifact_sha256: str | None
    health: Mapping[str, Any] | None = None
    error: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContractValidationError(f"schemaVersion must be {SCHEMA_VERSION}")
        _safe_name(self.deployment_id, "deploymentId", _SAFE_DEPLOYMENT_ID)
        if self.status not in {"succeeded", "failed"}:
            raise ContractValidationError("status is unsupported")
        _timestamp_text(self.updated_at, "updatedAt")
        _release_path(self.previous_release, "previousRelease")
        _release_path(self.new_release, "newRelease")
        if self.artifact_sha256 is not None:
            object.__setattr__(
                self, "artifact_sha256", _sha(self.artifact_sha256, _SHA256, "artifactSha256")
            )
        if self.health is not None:
            if not isinstance(self.health, Mapping):
                raise ContractValidationError("health must be a JSON object or null")
            object.__setattr__(self, "health", _json_value(dict(self.health), "health"))
        if self.error is not None and (not self.error.strip() or len(self.error) > 4096):
            raise ContractValidationError("error must be non-blank and at most 4096 characters")
        if self.status == "succeeded" and (
            self.new_release is None or self.artifact_sha256 is None or self.health is None or self.error is not None
        ):
            raise ContractValidationError("succeeded result requires new release, artifact SHA, health, and no error")
        if self.status == "succeeded" and self.health is not None:
            if self.health.get("status") != "ok":
                raise ContractValidationError("succeeded result health.status must be ok")
            service_id = self.health.get("service_id")
            version = self.health.get("version")
            if not isinstance(service_id, str) or not isinstance(version, str):
                raise ContractValidationError("succeeded result health requires service_id and version strings")
            _safe_name(service_id, "health.service_id")
            _semver(version, "health.version")
        if self.status == "failed" and self.error is None:
            raise ContractValidationError("failed result requires error")
        if self.status == "failed" and self.health is not None:
            if self.health.get("phase") != "rollback" or self.health.get("status") != "ok":
                raise ContractValidationError("failed result health must be successful rollback evidence")
            service_id = self.health.get("service_id")
            version = self.health.get("version")
            checked_at = self.health.get("checkedAt")
            if not isinstance(service_id, str) or not isinstance(version, str) or not isinstance(checked_at, str):
                raise ContractValidationError("rollback evidence requires service_id, version, and checkedAt strings")
            _safe_name(service_id, "health.service_id")
            _semver(version, "health.version")
            _timestamp(checked_at, "health.checkedAt")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "deploymentId": self.deployment_id,
            "status": self.status,
            "updatedAt": _timestamp_text(self.updated_at, "updatedAt"),
            "previousRelease": self.previous_release,
            "newRelease": self.new_release,
            "artifactSha256": self.artifact_sha256,
            "health": None if self.health is None else dict(self.health),
            "error": self.error,
        }

    def to_json(self) -> str:
        return _json_dumps(self.to_dict())

    @classmethod
    def from_dict(cls, value: Any) -> DeploymentResult:
        item = _object(value, "result")
        _keys(
            item,
            {
                "schemaVersion", "deploymentId", "status", "updatedAt",
                "previousRelease", "newRelease", "artifactSha256", "health", "error",
            },
            "result",
        )
        status = _string(item["status"], "status")
        health = item["health"]
        artifact_sha = item["artifactSha256"]
        return cls(
            schema_version=_integer(item["schemaVersion"], "schemaVersion"),
            deployment_id=_string(item["deploymentId"], "deploymentId"),
            status=status,  # type: ignore[arg-type]
            updated_at=_timestamp(_string(item["updatedAt"], "updatedAt"), "updatedAt"),
            previous_release=_optional_string(item["previousRelease"], "previousRelease"),
            new_release=_optional_string(item["newRelease"], "newRelease"),
            artifact_sha256=None if artifact_sha is None else _string(artifact_sha, "artifactSha256"),
            health=None if health is None else _object(health, "health"),
            error=_optional_string(item["error"], "error"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes | bytearray) -> DeploymentResult:
        return cls.from_dict(_json_loads(raw))
