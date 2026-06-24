<#
.SYNOPSIS
    Stage a CellMax Windows service bundle on a station over SMB.

.DESCRIPTION
    This follows the production application deployment shape:
    - copy the built zip to C:\Cellmax\Applications\<service>\installers
    - expand the zip to C:\Cellmax\Applications\<service>\staged\<bundle>
    - place a desktop launcher that runs the bundled install-service.ps1

    The service install itself still runs on the target station because it needs
    elevation, local service control, and the Windows service account password.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ComputerName,

    [Parameter(Mandatory = $true)]
    [string] $PackageName,

    [Parameter(Mandatory = $false)]
    [string] $ProjectDirectory = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string] $ZipPath,

    [Parameter(Mandatory = $false)]
    [pscredential] $Credential,

    [Parameter(Mandatory = $false)]
    [string] $ApplicationsShare = "CellmaxApplications",

    [Parameter(Mandatory = $false)]
    [string] $ApplicationsSubdir = "",

    [Parameter(Mandatory = $false)]
    [string] $DesktopShare = "CellmaxDesktop",

    [Parameter(Mandatory = $false)]
    [string] $DesktopSubdir = "",

    [Parameter(Mandatory = $false)]
    [string] $HostApplicationsRoot = "C:\Cellmax\Applications",

    [Parameter(Mandatory = $false)]
    [string] $EnvFile,

    [Parameter(Mandatory = $false)]
    [string] $ServiceUsername = "",

    [Parameter(Mandatory = $false)]
    [string] $ServicePassword = "",

    [switch] $Build
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Join-CmxUncSubdir {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Root,

        [string] $Subdir
    )

    if ([string]::IsNullOrWhiteSpace($Subdir)) {
        return $Root
    }
    return Join-Path $Root $Subdir
}

function Invoke-CmxServiceBuild {
    param([Parameter(Mandatory = $true)][string] $Directory)

    $buildScript = Join-Path $Directory "build.ps1"
    if (-not (Test-Path -LiteralPath $buildScript)) {
        throw "Cannot build bundle because build.ps1 was not found: $buildScript"
    }

    Push-Location $Directory
    try {
        & $buildScript
        if ($LASTEXITCODE -ne 0) {
            throw "Build failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Resolve-CmxServiceZip {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Directory,

        [string] $ExplicitZip
    )

    if ($ExplicitZip) {
        return (Resolve-Path -LiteralPath $ExplicitZip).Path
    }

    $dist = Join-Path $Directory "dist"
    $zip = Get-ChildItem -LiteralPath $dist -Filter "*.zip" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $zip) {
        throw "No service zip found in $dist. Run .\build.ps1 or pass -Build."
    }
    return $zip.FullName
}

function New-CmxLocalInstallLauncher {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [string] $PackageName,

        [Parameter(Mandatory = $true)]
        [string] $BundleRoot,

        [string] $ServiceUsername = "",

        [string] $ServicePassword = "",

        [switch] $HasDeploymentEnv
    )

    $escapedUsername = $ServiceUsername.Replace("'", "''")
    $escapedPassword = $ServicePassword.Replace("'", "''")
    $content = @"
param()

Set-StrictMode -Version Latest
`$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    `$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    `$principal = New-Object Security.Principal.WindowsPrincipal(`$identity)
    return `$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    `$self = `$PSCommandPath
    if (-not `$self) {
        `$self = `$MyInvocation.MyCommand.Path
    }
    Start-Process powershell.exe -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"`$self`"") -Verb RunAs
    exit
}

`$bundleRoot = "$BundleRoot"
`$installer = Join-Path `$bundleRoot "install-service.ps1"
if (-not (Test-Path -LiteralPath `$installer)) {
    throw "Missing install-service.ps1 in staged bundle: `$bundleRoot"
}

`$configDir = Join-Path `$env:ProgramData "CellMax\$PackageName"
`$deploymentEnv = Join-Path `$bundleRoot "deployment.env"
if ("$HasDeploymentEnv" -eq "True") {
    if (-not (Test-Path -LiteralPath `$deploymentEnv)) {
        throw "Missing deployment.env in staged bundle: `$deploymentEnv"
    }
    New-Item -ItemType Directory -Force -Path `$configDir | Out-Null
    Copy-Item -LiteralPath `$deploymentEnv -Destination (Join-Path `$configDir ".env") -Force
}

`$installArgs = @("-SkipEnvWizard", "-SkipPrompts")
if ('$escapedUsername') {
    `$installArgs += @("-ServiceUsername", '$escapedUsername')
}
if ('$escapedPassword') {
    `$installArgs += @("-ServicePassword", '$escapedPassword')
}

Write-Host "Installing $PackageName from `$bundleRoot" -ForegroundColor Cyan
& `$installer @installArgs
"@

    Set-Content -LiteralPath $Path -Value $content -Encoding UTF8
}

function New-CmxDesktopCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [string] $LauncherPath
    )

    $content = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$LauncherPath"
pause
"@

    Set-Content -LiteralPath $Path -Value $content -Encoding ASCII
}

function New-CmxDesktopShortcut {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [string] $LauncherPath,

        [Parameter(Mandatory = $true)]
        [string] $PackageName
    )

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$LauncherPath`""
    $shortcut.Description = "Install $PackageName"
    $shortcut.Save()
}

$projectRoot = (Resolve-Path -LiteralPath $ProjectDirectory).Path
$envFullPath = $null
if ($EnvFile) {
    $envFullPath = (Resolve-Path -LiteralPath $EnvFile).Path
}
if ($Build) {
    Invoke-CmxServiceBuild -Directory $projectRoot
}

$zipFullPath = Resolve-CmxServiceZip -Directory $projectRoot -ExplicitZip $ZipPath
$zipItem = Get-Item -LiteralPath $zipFullPath
$bundleName = [System.IO.Path]::GetFileNameWithoutExtension($zipItem.Name)

$appShareRoot = Join-CmxUncSubdir -Root "\\$ComputerName\$ApplicationsShare" -Subdir $ApplicationsSubdir
$desktopShareRoot = Join-CmxUncSubdir -Root "\\$ComputerName\$DesktopShare" -Subdir $DesktopSubdir

$mappedShares = @()
if ($Credential) {
    $username = $Credential.UserName
    $password = $Credential.GetNetworkCredential().Password
    foreach ($share in @($appShareRoot, $desktopShareRoot) | Select-Object -Unique) {
        cmd /c "net use `"$share`" /delete /y 2>nul" | Out-Null
        cmd /c "net use `"$share`" `"$password`" /user:`"$username`"" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not authenticate to $share as $username"
        }
        $mappedShares += $share
    }
}

try {
    $serviceRoot = Join-Path $appShareRoot $PackageName
    $installerRoot = Join-Path $serviceRoot "installers"
    $stagedRoot = Join-Path $serviceRoot "staged"
    $stagedBundle = Join-Path $stagedRoot $bundleName
    New-Item -ItemType Directory -Force -Path $installerRoot, $stagedRoot | Out-Null

    $remoteZip = Join-Path $installerRoot $zipItem.Name
    Copy-Item -LiteralPath $zipFullPath -Destination $remoteZip -Force
    Write-Host "Copied zip: $remoteZip" -ForegroundColor Green

    if (Test-Path -LiteralPath $stagedBundle) {
        Remove-Item -LiteralPath $stagedBundle -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $stagedBundle | Out-Null
    Expand-Archive -LiteralPath $remoteZip -DestinationPath $stagedBundle -Force
    Write-Host "Expanded staged bundle: $stagedBundle" -ForegroundColor Green

    if ($envFullPath) {
        Copy-Item -LiteralPath $envFullPath -Destination (Join-Path $stagedBundle "deployment.env") -Force
        Write-Host "Copied deployment .env into staged bundle." -ForegroundColor Green
    }

    $hostBundleRoot = Join-Path $HostApplicationsRoot "$PackageName\staged\$bundleName"
    $hostLauncherPath = Join-Path $hostBundleRoot "Install-$PackageName.ps1"
    $remoteLauncherPath = Join-Path $stagedBundle "Install-$PackageName.ps1"
    New-CmxLocalInstallLauncher `
        -Path $remoteLauncherPath `
        -PackageName $PackageName `
        -BundleRoot $hostBundleRoot `
        -ServiceUsername $ServiceUsername `
        -ServicePassword $ServicePassword `
        -HasDeploymentEnv:([bool]$envFullPath)

    $desktopCommand = Join-Path $desktopShareRoot "Install $PackageName.cmd"
    New-CmxDesktopCommand -Path $desktopCommand -LauncherPath $hostLauncherPath
    $desktopShortcut = Join-Path $desktopShareRoot "Install $PackageName.lnk"
    New-CmxDesktopShortcut -Path $desktopShortcut -LauncherPath $hostLauncherPath -PackageName $PackageName
    Write-Host "Desktop installer launcher: $desktopCommand" -ForegroundColor Green
    Write-Host "Desktop installer shortcut: $desktopShortcut" -ForegroundColor Green

    Write-Host "Distribution complete. On $ComputerName, run the desktop launcher as Administrator to install or update the service." -ForegroundColor Green
} finally {
    foreach ($share in $mappedShares) {
        cmd /c "net use `"$share`" /delete /y 2>nul" | Out-Null
    }
}
