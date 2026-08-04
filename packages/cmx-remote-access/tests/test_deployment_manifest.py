import json
from datetime import datetime, timezone

import pytest

import cmx_remote_access

from cmx_remote_access.deployment_manifest import (
    ArtifactSpec,
    ContractValidationError,
    DeploymentManifest,
    DeploymentResult,
    HealthCheckSpec,
    PackageSpec,
    ServiceSpec,
    hash_artifact,
)

SHA1 = "0123456789abcdef0123456789abcdef01234567"
SHA256 = "0123456789abcdef" * 4
NOW = datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc)


def manifest_dict() -> dict:
    return {
        "schemaVersion": 1,
        "deploymentId": "pp-api-0.3.23-20260804T123000Z",
        "package": {"name": "active-cell-pp-api", "version": "0.3.23", "sourceSha": SHA1},
        "artifact": {"fileName": "active-cell-pp-api-server-0.3.23.zip", "size": 123, "sha256": SHA256},
        "service": {"name": "CellMaxActiveCellPpApi", "executablePath": "server/active-cell-pp-api.exe"},
        "health": {
            "url": "http://127.0.0.1:8765/health",
            "serviceId": "active-cell-pp-api",
            "expectedVersion": "0.3.23",
        },
        "createdAt": "2026-08-04T12:30:00Z",
    }


def test_manifest_round_trip_uses_deterministic_camel_case_json() -> None:
    first = DeploymentManifest.from_dict(manifest_dict())
    second = DeploymentManifest.from_json(first.to_json())

    assert second == first
    assert first.to_json() == DeploymentManifest.from_dict(manifest_dict()).to_json()
    assert first.to_json() == json.dumps(first.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert "deploymentId" in first.to_json()
    assert "deployment_id" not in first.to_json()


def test_deployment_contract_is_part_of_the_public_package_api() -> None:
    assert cmx_remote_access.DeploymentManifest is DeploymentManifest
    assert cmx_remote_access.DeploymentResult is DeploymentResult
    assert cmx_remote_access.hash_artifact is hash_artifact


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(extra=True), "unknown"),
        (lambda value: value.pop("health"), "missing"),
        (lambda value: value.update(schemaVersion=2), "schemaVersion"),
        (lambda value: value.update(deploymentId="../escape"), "unsafe"),
        (lambda value: value["package"].update(name="bad package"), "unsafe"),
        (lambda value: value["service"].update(name="bad/service"), "unsafe"),
        (lambda value: value["package"].update(version="01.2.3"), "SemVer"),
        (lambda value: value["package"].update(sourceSha="a" * 39), "malformed"),
        (lambda value: value["artifact"].update(fileName="../thing.zip"), "basename"),
        (lambda value: value["artifact"].update(size=0), "between 1 byte"),
        (lambda value: value["artifact"].update(size=10 * 1024**3 + 1), "10 GiB"),
        (lambda value: value["artifact"].update(sha256="z" * 64), "malformed"),
        (lambda value: value["service"].update(executablePath="../service.exe"), "unsafe path"),
        (lambda value: value["service"].update(executablePath="C:/service.exe"), "portable relative"),
        (lambda value: value["artifact"].update(fileName="bundle.exe"), "ZIP basename"),
        (lambda value: value["health"].update(url="file:///service/health"), "loopback HTTP"),
        (lambda value: value["health"].update(url="http://user:secret@localhost/health"), "loopback HTTP"),
        (lambda value: value["health"].update(url="http://localhost/health?token=secret"), "query or fragment"),
        (lambda value: value["health"].update(url="http://10.0.0.10/health"), "loopback HTTP"),
        (lambda value: value["health"].update(expectedVersion="0.3.24"), "must equal"),
        (lambda value: value.update(createdAt="2026-08-04T14:30:00+02:00"), "UTC timestamp"),
    ],
)
def test_manifest_rejects_invalid_or_unsafe_values(mutate, message: str) -> None:
    value = manifest_dict()
    mutate(value)

    with pytest.raises(ContractValidationError, match=r"" + message.replace("(", r"\(").replace(")", r"\)")):
        DeploymentManifest.from_dict(value)


def test_manifest_rejects_unknown_nested_field_and_duplicate_json_key() -> None:
    value = manifest_dict()
    value["artifact"]["path"] = "elsewhere.zip"
    with pytest.raises(ContractValidationError, match="unknown"):
        DeploymentManifest.from_dict(value)

    raw = '{"schemaVersion":1,"schemaVersion":1}'
    with pytest.raises(ContractValidationError, match="duplicate"):
        DeploymentManifest.from_json(raw)


def test_direct_manifest_construction_validates_fields() -> None:
    with pytest.raises(ContractValidationError, match="unsafe"):
        DeploymentManifest(
            deployment_id="bad/id",
            package=PackageSpec("pkg", "1.0.0", SHA1),
            artifact=ArtifactSpec("pkg.zip", 1, SHA256),
            service=ServiceSpec("Service", "service.exe"),
            health=HealthCheckSpec("http://localhost/health", "pkg", "1.0.0"),
            created_at=NOW,
        )


def test_hash_artifact_returns_size_and_sha256(tmp_path) -> None:
    artifact = tmp_path / "bundle.zip"
    artifact.write_bytes(b"CellMax deployment artifact\n")

    hashed = hash_artifact(artifact, chunk_size=3)

    assert hashed.size == 28
    assert hashed.sha256 == "094637853187926c1aeff11a70097745c1c50a16a0bb091c529162f27b1dc26c"


def test_success_result_round_trip_includes_health_evidence() -> None:
    result = DeploymentResult(
        deployment_id="pp-api-0.3.23-20260804T123000Z",
        status="succeeded",
        updated_at=NOW,
        previous_release=r"C:\ProgramData\CellMax\releases\active-cell-pp-api\0.3.22",
        new_release=r"C:\ProgramData\CellMax\releases\active-cell-pp-api\0.3.23",
        artifact_sha256=SHA256.upper(),
        health={"status": "ok", "service_id": "active-cell-pp-api", "version": "0.3.23"},
    )

    parsed = DeploymentResult.from_json(result.to_json())

    assert parsed == result
    assert parsed.artifact_sha256 == SHA256
    assert parsed.to_dict()["health"]["status"] == "ok"
    assert set(parsed.to_dict()) == {
        "schemaVersion", "deploymentId", "status", "updatedAt", "previousRelease",
        "newRelease", "artifactSha256", "health", "error",
    }


def test_failed_result_allows_unknown_release_and_artifact() -> None:
    result = DeploymentResult(
        deployment_id="deployment-1",
        status="failed",
        updated_at=NOW,
        previous_release=None,
        new_release=None,
        artifact_sha256=None,
        error="manifest rejected before artifact validation",
    )
    assert DeploymentResult.from_json(result.to_json()) == result


def test_failed_result_requires_error() -> None:
    result = DeploymentResult(
        deployment_id="deployment-1",
        status="failed",
        updated_at=NOW,
        previous_release=r"C:\ProgramData\CellMax\releases\pkg\0.3.22",
        new_release=r"C:\ProgramData\CellMax\releases\pkg\0.3.23",
        artifact_sha256=SHA256,
        error="health check returned wrong version",
    )
    assert DeploymentResult.from_json(result.to_json()) == result

    with pytest.raises(ContractValidationError, match="requires error"):
        DeploymentResult(
            deployment_id="deployment-1",
            status="failed",
            updated_at=NOW,
            previous_release=r"C:\ProgramData\CellMax\releases\pkg\0.3.22",
            new_release=r"C:\ProgramData\CellMax\releases\pkg\0.3.23",
            artifact_sha256=SHA256,
        )


def test_failed_result_can_prove_successful_rollback() -> None:
    evidence = {
        "phase": "rollback",
        "status": "ok",
        "service_id": "active-cell-pp-api",
        "version": "0.3.22",
        "checkedAt": "2026-08-04T12:31:00Z",
    }
    result = DeploymentResult(
        deployment_id="deployment-1",
        status="failed",
        updated_at=NOW,
        previous_release=r"C:\ProgramData\CellMax\releases\pkg\0.3.22",
        new_release=r"C:\ProgramData\CellMax\releases\pkg\0.3.23",
        artifact_sha256=SHA256,
        health=evidence,
        error="new release health check failed",
    )
    assert DeploymentResult.from_json(result.to_json()) == result

    evidence["status"] = "failed"
    with pytest.raises(ContractValidationError, match="rollback evidence"):
        DeploymentResult(
            deployment_id="deployment-1",
            status="failed",
            updated_at=NOW,
            previous_release=None,
            new_release=None,
            artifact_sha256=None,
            health=evidence,
            error="rollback failed",
        )


def test_success_result_requires_positive_health_evidence() -> None:
    with pytest.raises(ContractValidationError, match="health.status"):
        DeploymentResult(
            deployment_id="deployment-1",
            status="succeeded",
            updated_at=NOW,
            previous_release=r"C:\ProgramData\CellMax\releases\pkg\0.3.22",
            new_release=r"C:\ProgramData\CellMax\releases\pkg\0.3.23",
            artifact_sha256=SHA256,
            health={"status": "degraded", "service_id": "pkg", "version": "0.3.23"},
        )


def test_result_rejects_unknown_status_and_fields() -> None:
    result = {
        "schemaVersion": 1,
        "deploymentId": "deployment-1",
        "status": "pending",
        "updatedAt": "2026-08-04T12:30:00.0000000+00:00",
        "previousRelease": None,
        "newRelease": None,
        "artifactSha256": SHA256,
        "health": None,
        "error": None,
    }
    with pytest.raises(ContractValidationError, match="unsupported"):
        DeploymentResult.from_dict(result)

    result["extra"] = True
    with pytest.raises(ContractValidationError, match="unknown"):
        DeploymentResult.from_dict(result)
