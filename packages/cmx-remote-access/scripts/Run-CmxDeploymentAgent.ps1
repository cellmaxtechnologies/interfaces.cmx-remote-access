[CmdletBinding()]
param(
    [string]$AgentRoot = 'C:\ProgramData\CellMax\deployment-agent',
    [string]$TransferRoot = 'C:\Cellmax\Deploy',
    [Parameter(Mandatory)][string]$NssmExe,
    [int]$PollSeconds = 5,
    [switch]$Once
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CmxDeploymentAgentCore.ps1')

$inbox = Join-Path $TransferRoot 'inbox'
$results = Join-Path $TransferRoot 'results'
$releases = Join-Path $AgentRoot 'releases'
$locks = Join-Path $AgentRoot 'locks'
$queue = Join-Path $AgentRoot 'queue'
$allowlist = Join-Path $AgentRoot 'allowlist.json'
foreach ($path in @($inbox,$results,$releases,$locks,$queue)) { New-Item -ItemType Directory -Force -Path $path | Out-Null }
if (-not (Test-Path -LiteralPath $allowlist -PathType Leaf)) { throw "Station-local deployment allowlist is missing: $allowlist" }

function Invoke-CmxProtectedQueueDeployment {
    param([Parameter(Mandatory)][string]$ProtectedDirectory)
    $deploymentId = Split-Path -Leaf $ProtectedDirectory
    $publicDirectory = Join-Path $inbox $deploymentId
    $publicProcessing = Join-Path $publicDirectory 'processing'
    try {
        Invoke-CmxDeployment -DeploymentDirectory $ProtectedDirectory -ReleasesRoot $releases -LocksDirectory $locks -ResultsDirectory $results -AllowlistPath $allowlist -NssmExe $NssmExe | Out-Null
        if (Test-Path -LiteralPath $publicProcessing) { Move-Item -LiteralPath $publicProcessing -Destination (Join-Path $publicDirectory 'succeeded') -Force }
    } catch {
        if (Test-Path -LiteralPath $publicProcessing) { Move-Item -LiteralPath $publicProcessing -Destination (Join-Path $publicDirectory 'failed') -Force -ErrorAction SilentlyContinue }
    } finally {
        Remove-Item -LiteralPath $ProtectedDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}

do {
    # Recover a crash between claiming public work and completing the protected copy.
    foreach ($publicClaim in @(Get-ChildItem -LiteralPath $inbox -Filter processing -File -Depth 1 -ErrorAction SilentlyContinue)) {
        $deploymentId = $publicClaim.Directory.Name
        if ($deploymentId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' -or $deploymentId -match '\.\.') {
            Move-Item -LiteralPath $publicClaim.FullName -Destination (Join-Path $publicClaim.Directory.FullName 'failed') -Force
            continue
        }
        $protectedDirectory = Resolve-CmxContainedPath $queue $deploymentId
        if (Test-Path -LiteralPath (Join-Path $protectedDirectory 'claimed') -PathType Leaf) { continue }
        $partialDirectory = Resolve-CmxContainedPath $queue "$deploymentId.partial"
        if (Test-Path -LiteralPath $partialDirectory) { Remove-Item -LiteralPath $partialDirectory -Recurse -Force }
        Move-Item -LiteralPath $publicClaim.FullName -Destination (Join-Path $publicClaim.Directory.FullName 'ready') -Force
    }
    # Protected claimed work is resumed before inspecting the remotely writable inbox.
    foreach ($protectedDirectory in @(Get-ChildItem -LiteralPath $queue -Directory -ErrorAction SilentlyContinue | Sort-Object FullName)) {
        if (Test-Path -LiteralPath (Join-Path $protectedDirectory.FullName 'claimed') -PathType Leaf) {
            Invoke-CmxProtectedQueueDeployment $protectedDirectory.FullName
        }
    }
    foreach ($ready in @(Get-ChildItem -LiteralPath $inbox -Filter ready -File -Depth 1 -ErrorAction SilentlyContinue | Sort-Object FullName)) {
        if ($ready.Length -ne 0) { continue }
        if ($ready.Directory.Name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' -or $ready.Directory.Name -match '\.\.') {
            Move-Item -LiteralPath $ready.FullName -Destination (Join-Path $ready.Directory.FullName 'failed') -Force
            continue
        }
        $deploymentDirectory = $ready.Directory.FullName
        $processing = Join-Path $deploymentDirectory 'processing'
        try {
            Move-Item -LiteralPath $ready.FullName -Destination $processing -ErrorAction Stop
        } catch { continue }
        try {
            $protectedDirectory = Stage-CmxDeploymentToProtectedQueue -InboxDeploymentDirectory $deploymentDirectory -QueueRoot $queue -AllowlistPath $allowlist
            Invoke-CmxProtectedQueueDeployment $protectedDirectory
        } catch {
            $failureResult = [ordered]@{
                schemaVersion = 1; deploymentId = $ready.Directory.Name; status = 'failed'
                updatedAt = [DateTimeOffset]::UtcNow.ToString('o'); previousRelease = $null
                newRelease = $null; artifactSha256 = $null; health = $null; error = $_.Exception.Message
            }
            [void](Write-CmxDeploymentResult $results $ready.Directory.Name $failureResult)
            Move-Item -LiteralPath $processing -Destination (Join-Path $deploymentDirectory 'failed') -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not $Once) { Start-Sleep -Seconds $PollSeconds }
} while (-not $Once)
