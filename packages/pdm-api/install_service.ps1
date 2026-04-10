param(
    [string]$EnvPath = (Join-Path $PSScriptRoot "pdm-api.env"),
    [string]$ServiceName = "PdmApiServer"
)

$ErrorActionPreference = "Stop"

function New-EnvTemplate([string]$Path) {
    $lines = @(
        "# Fill in values, then re-run install_service.ps1",
        "APP_DIR=",
        "NSSM_PATH=",
        "PDM_VAULT_ROOT=",
        "PDM_API_KEY=",
        "PDM_DLL_PATH=",
        "PDM_DLL_DIR=",
        "PDM_API_HOST=0.0.0.0",
        "PDM_API_PORT=8000",
        "# Run service as this user (same account as when exe works manually); use .\Username for local account",
        "RUN_AS_USER=",
        "RUN_AS_PASSWORD="
    )
    $lines | Set-Content -Path $Path -Encoding UTF8
}

function Read-EnvFile([string]$Path) {
    $values = @{}
    Get-Content -Path $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = ""
        if ($parts.Length -gt 1) { $value = $parts[1].Trim() }
        if ($key) { $values[$key] = $value }
    }
    return $values
}

function Require-Value([string]$Key, [string]$Value) {
    if (-not $Value) { throw "Missing $Key in env file: $EnvPath" }
}

if (-not (Test-Path $EnvPath)) {
    New-EnvTemplate -Path $EnvPath
    Write-Host "Created env template at $EnvPath. Fill it in and re-run."
    exit 1
}

$envValues = Read-EnvFile -Path $EnvPath

$AppFolder = $envValues["APP_DIR"]
$NssmPath = $envValues["NSSM_PATH"]
$ApiKey = $envValues["PDM_API_KEY"]
$VaultRoot = $envValues["PDM_VAULT_ROOT"]
$BindHost = if ($envValues.ContainsKey("PDM_API_HOST") -and $envValues["PDM_API_HOST"]) { $envValues["PDM_API_HOST"] } else { "0.0.0.0" }
$Port = if ($envValues.ContainsKey("PDM_API_PORT") -and $envValues["PDM_API_PORT"]) { $envValues["PDM_API_PORT"] } else { "8000" }

Require-Value -Key "APP_DIR" -Value $AppFolder
Require-Value -Key "NSSM_PATH" -Value $NssmPath
Require-Value -Key "PDM_API_KEY" -Value $ApiKey
Require-Value -Key "PDM_VAULT_ROOT" -Value $VaultRoot

if (-not (Test-Path $NssmPath)) { throw "NSSM not found at $NssmPath" }
if (-not (Test-Path $AppFolder)) { throw "App folder not found at $AppFolder" }

$exe = Join-Path $AppFolder "pdm-api-server.exe"
if (-not (Test-Path $exe)) { throw "Executable not found at $exe" }

& $NssmPath install $ServiceName $exe
& $NssmPath set $ServiceName AppDirectory $AppFolder

$envKeys = @(
    "PDM_DLL_PATH",
    "PDM_DLL_DIR",
    "PDM_API_HOST",
    "PDM_API_PORT",
    "PDM_API_KEY",
    "PDM_VAULT_ROOT"
)
$envLines = foreach ($key in $envKeys) {
    if ($envValues.ContainsKey($key) -and $envValues[$key]) {
        "$key=$($envValues[$key])"
    }
}
$envBlock = ($envLines -join "`n")
& $NssmPath set $ServiceName AppEnvironmentExtra $envBlock
& $NssmPath set $ServiceName Start SERVICE_AUTO_START

# Run as user account (same as when exe works manually) so PDM DLL/session works
$runAsUser = $envValues["RUN_AS_USER"]
$runAsPassword = $envValues["RUN_AS_PASSWORD"]
if ($runAsUser -and $runAsPassword) {
    & $NssmPath set $ServiceName ObjectName $runAsUser $runAsPassword
    Write-Host "Service configured to run as: $runAsUser"
} else {
    Write-Host "Tip: If the service starts but does not respond (hangs), add RUN_AS_USER and RUN_AS_PASSWORD to $EnvPath and re-run this script."
}

& $NssmPath start $ServiceName

Write-Host "Service '$ServiceName' installed and started."
