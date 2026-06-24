from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_service_bundle_deploy_uses_cellmax_application_layout() -> None:
    script = (ROOT / "scripts" / "Deploy-CmxServiceBundle.ps1").read_text(encoding="utf-8")

    assert 'C:\\Cellmax\\Applications' in script
    assert 'CellmaxApplications' in script
    assert 'CellmaxDesktop' in script
    assert '$installerRoot = Join-Path $serviceRoot "installers"' in script
    assert '$stagedRoot = Join-Path $serviceRoot "staged"' in script
    assert 'Expand-Archive -LiteralPath $remoteZip -DestinationPath $stagedBundle -Force' in script


def test_service_bundle_deploy_creates_target_side_installer_launcher() -> None:
    script = (ROOT / "scripts" / "Deploy-CmxServiceBundle.ps1").read_text(encoding="utf-8")

    assert 'install-service.ps1' in script
    assert 'Start-Process powershell.exe' in script
    assert '-Verb RunAs' in script
    assert 'Install $PackageName.cmd' in script
    assert 'Install $PackageName.lnk' in script
    assert 'run the desktop launcher as Administrator' in script


def test_service_bundle_deploy_can_ship_no_input_install_data() -> None:
    script = (ROOT / "scripts" / "Deploy-CmxServiceBundle.ps1").read_text(encoding="utf-8")

    assert '[string] $EnvFile' in script
    assert '[string] $ServiceUsername = ""' in script
    assert '[string] $ServicePassword = ""' in script
    assert 'deployment.env' in script
    assert 'Copy-Item -LiteralPath `$deploymentEnv -Destination (Join-Path `$configDir ".env") -Force' in script
    assert '$installArgs = @("-SkipEnvWizard", "-SkipPrompts")' in script
    assert '$installArgs += @("-ServiceUsername"' in script
    assert '$installArgs += @("-ServicePassword"' in script
