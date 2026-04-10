param(
    [string]$ServiceName = "PdmApiServer",
    [string]$EnvFile = (Join-Path $PSScriptRoot "pdm-api.env")
)

$ErrorActionPreference = "Stop"

function Read-EnvFile($Path) {
    $values = @{}
    if (-not (Test-Path $Path)) { return $values }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        if ($line -notmatch "=") { return }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Trim('"')
        }
        if ($key) { $values[$key] = $value }
    }
    return $values
}

function Vault-Root($vaultName, $vaultRoot) {
    if (-not $vaultRoot) { return (Join-Path 'C:\' $vaultName) }
    return (Join-Path $vaultRoot $vaultName)
}

function Normalize-Dir($vaultName, $vaultRoot, $dir) {
    if (-not $dir) { return $dir }
    $d = $dir.Trim()
    if (-not $d) { return $null }
    $root = Vault-Root $vaultName $vaultRoot
    if ($d.StartsWith('./') -or $d.StartsWith('.\')) {
        $d = $d.Substring(2)
        if (-not $d) { return $root }
    }
    if ($d.StartsWith('/') -or $d.StartsWith('\')) {
        return Join-Path $root ($d.TrimStart('/', '\'))
    }
    if (-not [System.IO.Path]::IsPathRooted($d)) {
        return Join-Path $root $d
    }
    return $d
}

Write-Host "== Service status =="
Get-Service $ServiceName | Format-Table -Auto

$env = Read-EnvFile $EnvFile
Write-Host "`n== Env file =="
if ($env.Count -eq 0) { Write-Host "No env file at $EnvFile"; exit 1 }

$required = @("PDM_API_KEY","PDM_VAULT_NAME","PDM_VAULT_ROOT")
foreach ($k in $required) {
    if (-not $env.ContainsKey($k) -or -not $env[$k]) {
        Write-Host "Missing $k in env file"
    }
}

$apiUrl = $null
if ($env.ContainsKey("PDM_API_URL") -and $env["PDM_API_URL"]) {
    $apiUrl = $env["PDM_API_URL"].Trim().TrimEnd("/")
} else {
    $bindHost = if ($env.ContainsKey("PDM_API_HOST") -and $env["PDM_API_HOST"]) { $env["PDM_API_HOST"] } else { "127.0.0.1" }
    $port = if ($env.ContainsKey("PDM_API_PORT") -and $env["PDM_API_PORT"]) { $env["PDM_API_PORT"] } else { "8000" }
    $probeHost = if ($bindHost -eq "0.0.0.0") { "127.0.0.1" } else { $bindHost }
    $apiUrl = "http://$probeHost`:$port"
}
$vaultName = if ($env.ContainsKey("PDM_VAULT_NAME")) { $env["PDM_VAULT_NAME"] } else { $null }
$vaultRoot = if ($env.ContainsKey("PDM_VAULT_ROOT")) { $env["PDM_VAULT_ROOT"] } else { $null }
$pdmUser = if ($env.ContainsKey("PDM_USERNAME")) { $env["PDM_USERNAME"] } else { $null }
$pdmPass = if ($env.ContainsKey("PDM_PASSWORD")) { $env["PDM_PASSWORD"] } else { $null }
$testFilePath = if ($env.ContainsKey("PDM_TEST_FILEPATH")) { $env["PDM_TEST_FILEPATH"] } else { $null }
$docDirs = @()
if ($env.ContainsKey("PDM_DOC_DIRS") -and $env["PDM_DOC_DIRS"]) {
    $docDirs = $env["PDM_DOC_DIRS"].Split(";") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}

Write-Host "`n== Network check =="
if ($apiUrl) {
    try {
        $health = Invoke-WebRequest "$apiUrl/health" -UseBasicParsing -TimeoutSec 10
        Write-Host "GET /health -> $($health.StatusCode) $($health.Content)"
    } catch {
        Write-Host "GET /health failed: $($_.Exception.Message)"
    }
}

Write-Host "`n== Vault root path =="
if ($vaultName) {
    $root = Vault-Root $vaultName $vaultRoot
    Write-Host "Resolved vault root: $root"
    Write-Host "Exists on disk: $([System.IO.Directory]::Exists($root))"
} else {
    Write-Host "Skipping vault root check (PDM_VAULT_NAME missing)."
}

Write-Host "`n== Doc dirs normalized =="
if (-not $docDirs -or $docDirs.Count -eq 0) {
    Write-Host "No PDM_DOC_DIRS set."
}
foreach ($d in $docDirs) {
    if (-not $vaultName) {
        Write-Host "$d -> (skipped: PDM_VAULT_NAME missing)"
        continue
    }
    $normalized = Normalize-Dir $vaultName $vaultRoot $d
    Write-Host "$d -> $normalized (exists: $([System.IO.Directory]::Exists($normalized)))"
}

Write-Host "`n== API login probe (POST /pdm/search) =="
if ($apiUrl) {
    $userLen = if ($pdmUser) { $pdmUser.Length } else { 0 }
    $passLen = if ($pdmPass) { $pdmPass.Length } else { 0 }
    Write-Host "Loaded PDM_USERNAME length: $userLen"
    Write-Host "Loaded PDM_PASSWORD length: $passLen"
    if (-not $pdmUser -or -not $pdmPass -or -not $vaultName) {
        Write-Host "Skipping login probe (missing PDM_USERNAME/PDM_PASSWORD/PDM_VAULT_NAME)."
        return
    }
    $testPath = if ($env.ContainsKey("PDM_TEST_FILE") -and $env["PDM_TEST_FILE"]) { $env["PDM_TEST_FILE"] } else { $null }
    $searchPattern = if ($testPath) { $testPath } else { "*IM-CA315907_A*.pdf" }
    $headers = @{}
    if ($env["PDM_API_KEY"]) { $headers["X-API-Key"] = $env["PDM_API_KEY"] }

    if ($testFilePath) {
        $payloadObj = @{
            username   = $pdmUser
            password   = $pdmPass
            vault_name = $vaultName
            filepath   = $testFilePath
        }
        $payloadJson = $payloadObj | ConvertTo-Json -Depth 4
        Write-Host "`n== API file-info probe (POST /pdm/file-info) =="
        Write-Host "Payload:"
        Write-Host $payloadJson
        try {
            $resp = Invoke-WebRequest "$apiUrl/pdm/file-info" -Method Post -Body $payloadJson -ContentType "application/json" -Headers $headers -TimeoutSec 20
            Write-Host "POST /pdm/file-info -> $($resp.StatusCode)"
            Write-Host $resp.Content
        } catch {
            if ($_.Exception.Response) {
                $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $body = $reader.ReadToEnd()
                Write-Host "POST /pdm/file-info failed: $($_.Exception.Response.StatusCode)"
                Write-Host $body
            } else {
                Write-Host "POST /pdm/file-info failed: $($_.Exception.Message)"
            }
        }
    }

    $dirsToTry = @()
    if ($docDirs -and $docDirs.Count -gt 0) {
        $dirsToTry = $docDirs
    } else {
        $dirsToTry = @("")
    }

    foreach ($dir in $dirsToTry) {
        $dirToSend = $dir
        if ($dir -and $vaultName) {
            $dirToSend = Normalize-Dir $vaultName $vaultRoot $dir
        }
        $payloadObj = @{
            username   = $pdmUser
            password   = $pdmPass
            vault_name = $vaultName
            filename_pattern = $searchPattern
            directory = $dirToSend
            recursive = $true
        }
        $payloadJson = $payloadObj | ConvertTo-Json -Depth 4
        Write-Host "Payload:"
        Write-Host $payloadJson
        try {
            $resp = Invoke-WebRequest "$apiUrl/pdm/search" -Method Post -Body $payloadJson -ContentType "application/json" -Headers $headers -TimeoutSec 20
            Write-Host "POST /pdm/search -> $($resp.StatusCode)"
            Write-Host $resp.Content
            break
        } catch {
            if ($_.Exception.Response) {
                $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $body = $reader.ReadToEnd()
                Write-Host "POST /pdm/search failed: $($_.Exception.Response.StatusCode)"
                Write-Host $body
            } else {
                Write-Host "POST /pdm/search failed: $($_.Exception.Message)"
            }
        }
    }
}
