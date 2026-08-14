from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "Publish-CmxServiceRelease.ps1"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _powershell() -> str:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell is required for executable publisher checks")
    return executable


def _invoke_with_invalid_value(tmp_path: Path, parameter: str, value: str) -> subprocess.CompletedProcess[str]:
    artifact = tmp_path / "service.zip"
    artifact.write_bytes(b"verified artifact")
    arguments = {
        "ComputerName": "station.example.test",
        "ShareName": "CmxDeploy$",
        "PackageName": "active-cell-pp-api",
        "PackageVersion": "1.2.3",
        "SourceSha": "a" * 40,
        "ArtifactPath": str(artifact),
        "ServiceName": "CellMaxActiveCellPpApi",
        "ExecutablePath": "server/service.exe",
        "HealthUrl": "http://127.0.0.1:8765/health",
        "HealthServiceId": "active-cell-pp-api",
        "HealthExpectedVersion": "1.2.3",
    }
    arguments[parameter] = value
    command = [_powershell(), "-NoProfile", "-NonInteractive", "-File", str(SCRIPT)]
    for name, argument in arguments.items():
        command.extend((f"-{name}", argument))
    return subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)


def test_publisher_is_valid_powershell() -> None:
    command = (
        "$errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}',[ref]$null,[ref]$errors) | Out-Null; "
        "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    completed = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("parameter", "value", "message"),
    [
        ("ComputerName", r"station\..\victim", "ComputerName must be"),
        ("ShareName", r"..\C$", "ShareName must be"),
        ("PackageName", "../victim", "PackageName must be"),
        ("PackageName", "Active-Cell-PP-API", "lowercase deployment package"),
        ("ExecutablePath", "../install-service.ps1", "ExecutablePath segment must be"),
        ("HealthUrl", "http://station.example.test/health", "loopback HTTP URL"),
        ("HealthUrl", "http://localhost/health?secret=value", "loopback HTTP URL"),
    ],
)
def test_publisher_rejects_traversal_before_smb_access(
    tmp_path: Path, parameter: str, value: str, message: str
) -> None:
    completed = _invoke_with_invalid_value(tmp_path, parameter, value)

    assert completed.returncode != 0
    assert message in completed.stderr
    assert "New-PSDrive" not in completed.stderr


def test_publisher_rejects_invalid_numeric_prerelease_before_smb_access(tmp_path: Path) -> None:
    completed = _invoke_with_invalid_value(tmp_path, "PackageVersion", "1.2.3-01")

    assert completed.returncode != 0
    assert "valid SemVer" in completed.stderr


def test_publisher_emits_exact_v1_manifest_shape_and_artifact_proof() -> None:
    script = _script()

    for required_fragment in (
        "schemaVersion = 1",
        "deploymentId = $deploymentId",
        "package = [ordered]@{",
        "name = $PackageName",
        "version = $PackageVersion",
        "sourceSha = $SourceSha.ToLowerInvariant()",
        "artifact = [ordered]@{",
        "fileName = $artifact.Name",
        "size = [int64]$artifact.Length",
        "sha256 = $artifactHash",
        "service = [ordered]@{",
        "executablePath = ($ExecutablePath -replace",
        "health = [ordered]@{",
        "serviceId = $HealthServiceId",
        "expectedVersion = $HealthExpectedVersion",
        "createdAt = $createdAt",
    ):
        assert required_fragment in script

    assert "Get-CmxFileSha256 $artifact.FullName" in script
    assert "Get-CmxFileSha256 $artifactPartial" in script
    assert "(Get-Item -LiteralPath $Path -ErrorAction Stop).FullName" in script
    assert "[Security.Cryptography.SHA256]::Create()" in script
    assert "$stagedArtifact.Length -ne $artifact.Length -or $stagedHash -ne $artifactHash" in script


def test_publisher_stages_partial_files_and_publishes_ready_last() -> None:
    script = _script()

    artifact_publish = script.index("Move-Item -LiteralPath $artifactPartial")
    manifest_publish = script.index("Move-Item -LiteralPath $manifestPartial")
    ready_create = script.index("[System.IO.File]::WriteAllBytes($readyPartial")
    ready_publish = script.index("Move-Item -LiteralPath $readyPartial")
    result_wait = script.index("while ($null -eq $result)")

    assert artifact_publish < manifest_publish < ready_create < ready_publish < result_wait
    assert 'Join-Path $deploymentRoot ($artifact.Name + ".partial")' in script
    assert 'Join-Path $deploymentRoot "manifest.json.partial"' in script
    assert 'Join-Path $deploymentRoot "ready.partial"' in script
    assert '[System.IO.File]::WriteAllBytes($readyPartial, [byte[]]@())' in script


def test_publisher_can_retry_same_immutable_deployment_without_deleting_audit_result() -> None:
    script = _script()

    assert "[string] $DeploymentId = ''" in script
    assert '$DeploymentId = [guid]::NewGuid().ToString("D")' in script
    assert '$candidateUpdatedAt -ge $createdAtValue' in script
    assert 'Remove-Item -LiteralPath $resultPath' not in script


def test_publisher_has_no_service_secret_or_remote_install_surface() -> None:
    script = _script()

    for forbidden_fragment in (
        "$EnvFile",
        "$ServicePassword",
        "deployment.env",
        "Expand-Archive",
        "install-service.ps1",
        "Invoke-Command",
        "Remove-Item",
    ):
        assert forbidden_fragment not in script

    assert "[pscredential] $Credential" in script
    assert "New-PSDrive" in script
    assert '$shareRoot = "${driveName}:\\"' not in script
    assert "Remove-PSDrive" in script
    assert script.index("try {") < script.index("finally {") < script.index("Remove-PSDrive")


def test_publisher_requires_matching_result_and_independent_health_identity() -> None:
    script = _script()

    assert 'Join-Path $resultsRoot ($deploymentId + ".json")' in script
    assert "[DateTime]::UtcNow.AddSeconds($ResultTimeoutSeconds)" in script
    assert 'Name "deploymentId"' in script
    assert '$resultStatus -ne "succeeded"' in script
    assert 'Rollback health proved service' in script
    assert 'Name "artifactSha256"' in script
    assert "Invoke-RestMethod -Uri $remoteHealthUri" in script
    assert 'Name "service_id"' in script
    assert 'Name "version"' in script
    assert 'Name "status"' in script
    assert '$actualStatus -eq "ok"' in script
    assert "$actualServiceId -eq $HealthServiceId -and $actualVersion -eq $HealthExpectedVersion" in script
    assert "Remove-PSDrive -Name $driveName" in script
