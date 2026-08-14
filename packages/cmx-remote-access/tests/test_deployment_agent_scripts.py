import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CORE = SCRIPTS / "CmxDeploymentAgentCore.ps1"


def run_pwsh(command: str, **environment: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(environment)
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def ps_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def manifest_for(archive: Path, **updates: object) -> dict[str, object]:
    data: dict[str, object] = {
        "schemaVersion": 1,
        "deploymentId": "deploy-001",
        "package": {"name": "active-cell-pp-api", "version": "1.2.3", "sourceSha": "a" * 40},
        "artifact": {
            "fileName": archive.name,
            "size": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        },
        "service": {"name": "CellMaxActiveCellPpApi", "executablePath": "server.exe"},
        "health": {
            "url": "http://127.0.0.1:8765/health",
            "serviceId": "active-cell-pp-api",
            "expectedVersion": "1.2.3",
        },
        "createdAt": "2026-08-04T12:00:00Z",
    }
    data.update(updates)
    return data


@pytest.mark.parametrize(
    "name",
    [
        "CmxDeploymentAgentCore.ps1",
        "Install-CmxDeploymentAgent.ps1",
        "New-CmxDeploymentAgentBundle.ps1",
        "Run-CmxDeploymentAgent.ps1",
    ],
)
def test_deployment_agent_script_parses(name: str) -> None:
    path = SCRIPTS / name
    command = (
        "$tokens=$null;$errors=$null;"
        f"[void][System.Management.Automation.Language.Parser]::ParseFile({ps_quote(path)},[ref]$tokens,[ref]$errors);"
        "if($errors.Count){$errors|ForEach-Object Message;exit 1}"
    )
    result = run_pwsh(command)
    assert result.returncode == 0, result.stderr + result.stdout


def test_manifest_and_artifact_are_executably_validated(tmp_path: Path) -> None:
    deployment = tmp_path / "deploy-001"
    deployment.mkdir()
    archive = deployment / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("server.exe", b"not-really-an-exe")
    manifest = manifest_for(archive)
    manifest_path = deployment / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    command = (
        f". {ps_quote(CORE)};"
        f"$m=Read-CmxDeploymentManifest {ps_quote(manifest_path)};"
        f"$p=Test-CmxDeploymentArtifact $m {ps_quote(deployment)};"
        "[IO.Path]::GetFileName($p)"
    )
    result = run_pwsh(command)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == "bundle.zip"


def test_manifest_rejects_unknown_fields_and_non_loopback_health(tmp_path: Path) -> None:
    deployment = tmp_path / "deploy-001"
    deployment.mkdir()
    archive = deployment / "bundle.zip"
    archive.write_bytes(b"zip")
    manifest = manifest_for(archive)
    manifest["secret"] = "must-not-be-accepted"
    manifest["health"]["url"] = "https://example.com/health"  # type: ignore[index]
    path = deployment / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    result = run_pwsh(f". {ps_quote(CORE)};Read-CmxDeploymentManifest {ps_quote(path)}")
    assert result.returncode != 0
    assert "must contain exactly" in result.stderr


@pytest.mark.parametrize(
    ("raw_replacement", "replacement", "message"),
    [
        ('"schemaVersion": 1', '"schemaVersion": "1"', "JSON integer"),
        ('"size": 3', '"size": 3.0', "JSON integer"),
        ('"version": "1.2.3"', '"version": "1.2.3-01"', "package.version"),
    ],
)
def test_manifest_rejects_coercive_numbers_and_leading_zero_prerelease(
    tmp_path: Path, raw_replacement: str, replacement: str, message: str
) -> None:
    deployment = tmp_path / "deploy-001"
    deployment.mkdir()
    archive = deployment / "bundle.zip"
    archive.write_bytes(b"zip")
    raw = json.dumps(manifest_for(archive)).replace(raw_replacement, replacement)
    path = deployment / "manifest.json"
    path.write_text(raw, encoding="utf-8")
    result = run_pwsh(f". {ps_quote(CORE)};Read-CmxDeploymentManifest {ps_quote(path)}")
    assert result.returncode != 0
    assert message in result.stderr


def test_manifest_rejects_duplicate_json_key(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
    result = run_pwsh(f". {ps_quote(CORE)};Read-CmxDeploymentManifest {ps_quote(path)}")
    assert result.returncode != 0
    assert "Duplicate JSON property" in result.stderr


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda manifest: manifest["package"].update(sourceSha="a" * 7), "sourceSha"),
        (lambda manifest: manifest["service"].update(executablePath=r"..\server.exe"), "executablePath"),
        (lambda manifest: manifest["health"].update(url="http://localhost/health?secret=value"), "health.url"),
        (lambda manifest: manifest.update(createdAt="2026-08-04T14:00:00+02:00"), "createdAt"),
    ],
)
def test_agent_contract_rejects_values_the_publisher_cannot_emit(
    tmp_path: Path, mutation, message: str
) -> None:
    deployment = tmp_path / "deploy-001"
    deployment.mkdir()
    archive = deployment / "bundle.zip"
    archive.write_bytes(b"zip")
    manifest = manifest_for(archive)
    mutation(manifest)
    path = deployment / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    result = run_pwsh(f". {ps_quote(CORE)};Read-CmxDeploymentManifest {ps_quote(path)}")
    assert result.returncode != 0
    assert message in result.stderr


def test_artifact_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    deployment = tmp_path / "deploy-001"
    deployment.mkdir()
    archive = deployment / "bundle.zip"
    archive.write_bytes(b"one")
    manifest = manifest_for(archive)
    path = deployment / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    archive.write_bytes(b"two")

    command = (
        f". {ps_quote(CORE)};$m=Read-CmxDeploymentManifest {ps_quote(path)};"
        f"Test-CmxDeploymentArtifact $m {ps_quote(deployment)}"
    )
    result = run_pwsh(command)
    assert result.returncode != 0
    assert "SHA-256 does not match" in result.stderr


def test_archive_traversal_is_rejected_and_partial_release_removed(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    destination = tmp_path / "release"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escaped.txt", b"no")
    result = run_pwsh(
        f". {ps_quote(CORE)};Expand-CmxDeploymentArchive {ps_quote(archive)} {ps_quote(destination)}"
    )
    assert result.returncode != 0
    assert "escapes its allowed root" in result.stderr
    assert not destination.exists()
    assert not (tmp_path / "escaped.txt").exists()


def test_per_package_lock_is_exclusive_and_reusable(tmp_path: Path) -> None:
    command = (
        f". {ps_quote(CORE)};$root={ps_quote(tmp_path)};"
        "$first=Enter-CmxDeploymentLock $root 'package';"
        "$blocked=$false;try{$second=Enter-CmxDeploymentLock $root 'package'}catch{$blocked=$true};"
        "Exit-CmxDeploymentLock $first;if(-not $blocked){throw 'second lock was not blocked'};"
        "$third=Enter-CmxDeploymentLock $root 'package';Exit-CmxDeploymentLock $third"
    )
    result = run_pwsh(command)
    assert result.returncode == 0, result.stderr + result.stdout


def test_protected_queue_copies_and_rehashes_only_declared_files(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox" / "deploy-001"
    queue = tmp_path / "protected"
    inbox.mkdir(parents=True)
    archive = inbox / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("server.exe", b"payload")
    (inbox / "manifest.json").write_text(json.dumps(manifest_for(archive)), encoding="utf-8")
    (inbox / "untrusted.env").write_text("SECRET=no", encoding="utf-8")
    (tmp_path / "allowlist.json").write_text(json.dumps({"schemaVersion": 1, "profiles": [{
        "packageName": "active-cell-pp-api", "serviceName": "CellMaxActiveCellPpApi",
        "healthUrl": "http://127.0.0.1:8765/health", "serviceId": "active-cell-pp-api",
        "executablePath": "server.exe",
    }]}), encoding="utf-8")
    result = run_pwsh(
        f". {ps_quote(CORE)};$p=Stage-CmxDeploymentToProtectedQueue {ps_quote(inbox)} {ps_quote(queue)} {ps_quote(tmp_path / 'allowlist.json')};$p"
    )
    assert result.returncode == 0, result.stderr + result.stdout
    protected = queue / "deploy-001"
    protected_hash = hashlib.sha256((protected / "bundle.zip").read_bytes()).hexdigest()
    archive.write_bytes(b"attacker changed the remotely writable source")
    assert {path.name for path in protected.iterdir()} == {"manifest.json", "bundle.zip", "claimed"}
    assert hashlib.sha256((protected / "bundle.zip").read_bytes()).hexdigest() == protected_hash
    assert hashlib.sha256((protected / "bundle.zip").read_bytes()).hexdigest() != hashlib.sha256(archive.read_bytes()).hexdigest()


def test_station_allowlist_requires_one_exact_profile(tmp_path: Path) -> None:
    deployment = tmp_path / "deploy-001"
    deployment.mkdir()
    archive = deployment / "bundle.zip"
    archive.write_bytes(b"zip")
    manifest = manifest_for(archive)
    path = deployment / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(json.dumps({"schemaVersion": 1, "profiles": [{
        "packageName": "active-cell-pp-api", "serviceName": "CellMaxActiveCellPpApi",
        "healthUrl": "http://127.0.0.1:8765/health", "serviceId": "active-cell-pp-api",
        "executablePath": "server.exe",
    }]}), encoding="utf-8")
    command = f". {ps_quote(CORE)};$m=Read-CmxDeploymentManifest {ps_quote(path)};Assert-CmxDeploymentAllowed $m {ps_quote(allowlist)}"
    result = run_pwsh(command)
    assert result.returncode == 0, result.stderr + result.stdout
    manifest["service"]["name"] = "OtherService"  # type: ignore[index]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = run_pwsh(command)
    assert result.returncode != 0
    assert "station-local allowlist" in result.stderr


def test_runner_claims_ready_marker_before_deployment() -> None:
    script = (SCRIPTS / "Run-CmxDeploymentAgent.ps1").read_text(encoding="utf-8")
    assert "Get-ChildItem -LiteralPath $inbox -Filter ready" in script
    assert "if ($ready.Length -ne 0) { continue }" in script
    assert "Move-Item -LiteralPath $ready.FullName -Destination $processing" in script
    assert "Stage-CmxDeploymentToProtectedQueue" in script
    assert "Invoke-CmxDeployment -DeploymentDirectory $ProtectedDirectory" in script
    assert "Protected claimed work is resumed" in script
    assert "Recover a crash between claiming public work" in script
    assert 'Resolve-CmxContainedPath $queue "$deploymentId.partial"' in script
    assert "Move-Item -LiteralPath $publicClaim.FullName" in script
    assert "Stage-CmxDeploymentToProtectedQueue" in script and "-AllowlistPath $allowlist" in script


def test_agent_preserves_service_identity_and_never_accepts_secrets() -> None:
    core = CORE.read_text(encoding="utf-8")
    installer = (SCRIPTS / "Install-CmxDeploymentAgent.ps1").read_text(encoding="utf-8")
    combined = core + installer

    assert "first install is intentionally unsupported" in core
    assert "ObjectName = [string]$service.StartName" in core
    assert "if ($Key -notin @('Application','AppDirectory'))" in core
    assert "Rollback also failed" in core
    assert "Set-CmxDeploymentNssmValue $NssmExe ([string]$manifest.service.name) 'Application' ([string]$previous.Application)" in core
    assert "Set-CmxDeploymentNssmValue $NssmExe ([string]$manifest.service.name) 'AppDirectory' ([string]$previous.AppDirectory)" in core
    assert "ServicePassword" not in combined
    assert "deployment.env" not in combined
    assert "-FullAccess $DeploymentPrincipal" in installer
    assert "-UserId 'SYSTEM'" in installer
    assert "S-1-1-0" in installer
    assert "must be a dedicated account" in installer
    assert "Get-CimInstance Win32_Service" in installer
    assert "GetFileName($candidate) -ieq 'nssm.exe'" in installer
    assert "Reset-CmxDeploymentProtectedTreeDacl" in installer
    assert "Set-CmxDeploymentFileDacl" in installer
    assert "Get-ChildItem -LiteralPath $Path -Recurse -Force" in installer
    assert "Grant-CmxDeploymentReleaseReadExecute $newRelease ([string]$previous.ObjectName)" in core
    assert '"$aclAccount`:(OI)(CI)RX"' in core
    assert '"$aclAccount`:(OI)(CI)M"' not in core
    assert "'LocalSystem' { '*S-1-5-18' }" in core
    assert "Set-Acl -LiteralPath $Path" in installer
    assert "SetAccessRuleProtection($true, $false)" in installer
    assert "icacls" not in installer.lower()
    assert "active-cell-pp-api-server.exe" in installer
    assert "venv/Scripts/python.exe" in installer
    assert "http://127.0.0.1:8765/health" in installer
    assert "http://127.0.0.1:8766/health" in installer
    assert 'Move-Item -LiteralPath $allowlistTemp -Destination $allowlistPath -Force' in installer


def test_installer_restarts_existing_agent_before_registering_upgrade() -> None:
    installer = (SCRIPTS / "Install-CmxDeploymentAgent.ps1").read_text(encoding="utf-8")

    stop = installer.index("Stop-ScheduledTask -TaskName $TaskName")
    register = installer.index("Register-ScheduledTask -TaskName $TaskName")
    start = installer.index("Start-ScheduledTask -TaskName $TaskName")

    assert "$existingTask.State -eq 'Running'" in installer
    assert "did not stop during upgrade" in installer
    assert stop < register < start


def test_release_read_execute_acl_grant_runs_in_windows_powershell(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    (release / "server.exe").write_bytes(b"test")
    command = (
        f". {ps_quote(CORE)};"
        "$localName=(Get-CimInstance Win32_UserAccount -Filter 'LocalAccount=True' | Select-Object -First 1).Name;"
        "$account=\".\\$localName\";"
        f"Grant-CmxDeploymentReleaseReadExecute {ps_quote(release)} $account"
    )

    result = run_pwsh(command)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "^\\.\\\\(.+)$" in CORE.read_text(encoding="utf-8")


def test_agent_persists_restart_safe_release_and_rollback_evidence() -> None:
    core = CORE.read_text(encoding="utf-8")

    assert "Write-CmxDeploymentJournal" in core
    assert "Read-CmxDeploymentJournal" in core
    assert "previousApplication" in core
    assert "previousAppDirectory" in core
    assert ".cmx-release.json" in core
    assert "Immutable release belongs to another deployment" in core
    assert "if (($switched -or $transactionPrepared)" in core
    assert "previousHealthVersion" in core
    assert "Get-CmxDeploymentBaselineHealth" in core
    assert "$rollbackResponse = Wait-CmxDeploymentHealth $rollbackHealth" in core
    assert "phase = 'rollback'; status = 'ok'" in core
    assert "checkedAt = [DateTimeOffset]::UtcNow.ToString('o')" in core
    assert "Rollback did not preserve the Windows service identity" in core
    assert "[System.ServiceProcess.ServiceControllerStatus]" in core
    assert "[ServiceProcess.ServiceControllerStatus]" not in core


def test_deployment_agent_bundle_contains_bootstrap_and_publisher(tmp_path: Path) -> None:
    builder = SCRIPTS / "New-CmxDeploymentAgentBundle.ps1"
    result = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(builder),
            "-OutputDirectory", str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    bundles = list(tmp_path.glob("cmx-deployment-agent-1.1.5.zip"))
    assert len(bundles) == 1
    with zipfile.ZipFile(bundles[0]) as bundle:
        assert set(bundle.namelist()) == {
            "CmxDeploymentAgentCore.ps1",
            "Install-CmxDeploymentAgent.ps1",
            "Publish-CmxServiceRelease.ps1",
            "README.md",
            "Run-CmxDeploymentAgent.ps1",
        }


def test_deployment_agent_bundle_default_output_works_in_windows_powershell() -> None:
    builder = SCRIPTS / "New-CmxDeploymentAgentBundle.ps1"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(builder)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert (ROOT / "dist" / "cmx-deployment-agent-1.1.5.zip").is_file()


def test_result_shape_and_exact_health_identity_are_pinned() -> None:
    core = CORE.read_text(encoding="utf-8")
    assert "$last.service_id -eq [string]$Health.serviceId" in core
    assert "$last.version -eq [string]$Health.expectedVersion" in core
    for field in (
        "schemaVersion", "deploymentId", "status", "updatedAt", "previousRelease",
        "newRelease", "artifactSha256", "health", "error",
    ):
        assert field in core
    assert "status = 'succeeded'" in core
    assert "status = 'failed'" in core
