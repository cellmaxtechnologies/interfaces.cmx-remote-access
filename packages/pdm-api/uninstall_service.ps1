param(
    [string]$EnvPath = (Join-Path $PSScriptRoot "pdm-api.env"),
    [string]$NssmPath,
    [string]$ServiceName = "PdmApiServer"
)

$ErrorActionPreference = "Stop"

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

if (-not $NssmPath) {
    if (-not (Test-Path $EnvPath)) {
        throw "NSSM path not provided and env file not found: $EnvPath"
    }
    $envValues = Read-EnvFile -Path $EnvPath
    $NssmPath = $envValues["NSSM_PATH"]
}

if (-not $NssmPath) { throw "Missing NSSM_PATH in env file: $EnvPath" }

if (-not (Test-Path $NssmPath)) {
    throw "NSSM not found at $NssmPath"
}

Write-Host "Stopping service '$ServiceName'..."
& $NssmPath stop $ServiceName | Out-Null

Write-Host "Removing service '$ServiceName'..."
& $NssmPath remove $ServiceName confirm

Write-Host "Service '$ServiceName' removed."
