<#
.SYNOPSIS
    Publish a service release to a station deployment agent over SMB.

.DESCRIPTION
    Copies one verified artifact and a v1 deployment manifest into a unique
    inbox directory. Files are staged with .partial names and atomically
    renamed. The zero-byte ready marker is published last. The command waits
    for the matching result, then independently verifies the remote service's
    service_id and version through its health endpoint.

    This command never transfers environment files or service credentials and
    never invokes an installer on the station.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ComputerName,

    [Parameter(Mandatory = $true)]
    [string] $ShareName,

    [Parameter(Mandatory = $true)]
    [string] $PackageName,

    [Parameter(Mandatory = $true)]
    [string] $PackageVersion,

    [Parameter(Mandatory = $true)]
    [string] $SourceSha,

    [Parameter(Mandatory = $true)]
    [string] $ArtifactPath,

    [Parameter(Mandatory = $true)]
    [string] $ServiceName,

    [Parameter(Mandatory = $true)]
    [string] $ExecutablePath,

    [Parameter(Mandatory = $true)]
    [string] $HealthUrl,

    [Parameter(Mandatory = $true)]
    [string] $HealthServiceId,

    [Parameter(Mandatory = $true)]
    [string] $HealthExpectedVersion,

    [Parameter(Mandatory = $false)]
    [pscredential] $Credential,

    [Parameter(Mandatory = $false)]
    [hashtable] $HealthHeaders = @{},

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 86400)]
    [int] $ResultTimeoutSeconds = 600,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 300)]
    [int] $HealthProbeTimeoutSeconds = 30,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 60)]
    [int] $PollIntervalSeconds = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-CmxFileSha256 {
    param([Parameter(Mandatory = $true)][string] $Path)

    $fileSystemPath = (Get-Item -LiteralPath $Path -ErrorAction Stop).FullName
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::Open($fileSystemPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        return (($algorithm.ComputeHash($stream) | ForEach-Object { $_.ToString("x2") }) -join "")
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

function Assert-CmxSafeLeaf {
    param(
        [Parameter(Mandatory = $true)][string] $Value,
        [Parameter(Mandatory = $true)][string] $Label
    )

    if ([string]::IsNullOrWhiteSpace($Value) -or
        $Value -in @(".", "..") -or
        $Value.Contains("..") -or
        $Value.IndexOfAny([char[]]"/\:") -ge 0 -or
        $Value.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        throw "$Label must be a traversal-safe path segment."
    }
}

function Assert-CmxRelativeExecutablePath {
    param([Parameter(Mandatory = $true)][string] $Value)

    if ([string]::IsNullOrWhiteSpace($Value) -or [System.IO.Path]::IsPathRooted($Value)) {
        throw "ExecutablePath must be a non-empty relative path inside the artifact."
    }
    $segments = $Value -split '[\\/]'
    if ($segments.Count -eq 0) {
        throw "ExecutablePath must contain at least one path segment."
    }
    foreach ($segment in $segments) {
        Assert-CmxSafeLeaf -Value $segment -Label "ExecutablePath segment"
    }
}

function Get-CmxRequiredProperty {
    param(
        [Parameter(Mandatory = $true)] $Object,
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][string] $Context
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        throw "$Context is missing required property '$Name'."
    }
    return $property.Value
}

function Assert-CmxExactPropertyNames {
    param(
        [Parameter(Mandatory = $true)] $Object,
        [Parameter(Mandatory = $true)][string[]] $Names,
        [Parameter(Mandatory = $true)][string] $Context
    )

    $actual = @($Object.PSObject.Properties.Name | Sort-Object)
    $expected = @($Names | Sort-Object)
    if (($actual -join "`n") -ne ($expected -join "`n")) {
        throw "$Context has unknown or missing properties."
    }
}

function Get-CmxRemoteHealthUri {
    param(
        [Parameter(Mandatory = $true)][uri] $ConfiguredUri,
        [Parameter(Mandatory = $true)][string] $Station
    )

    if ($ConfiguredUri.Host -notin @("localhost", "127.0.0.1", "::1")) {
        return $ConfiguredUri
    }

    $builder = New-Object System.UriBuilder($ConfiguredUri)
    $builder.Host = $Station
    return $builder.Uri
}

Assert-CmxSafeLeaf -Value $ShareName -Label "ShareName"
Assert-CmxSafeLeaf -Value $PackageName -Label "PackageName"
Assert-CmxSafeLeaf -Value $ServiceName -Label "ServiceName"
Assert-CmxSafeLeaf -Value $HealthServiceId -Label "HealthServiceId"

if ($ComputerName -notmatch '^[A-Za-z0-9][A-Za-z0-9.:-]{0,253}$' -or $ComputerName.Contains("..")) {
    throw "ComputerName must be a DNS name or IP address without path characters."
}
$semverPattern = '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$'
if ($PackageVersion -notmatch $semverPattern) {
    throw "PackageVersion must be a valid SemVer value."
}
if ($PackageName -cnotmatch '^[a-z0-9][a-z0-9._-]{0,63}$') {
    throw "PackageName must be a lowercase deployment package name of at most 64 characters."
}
if ($HealthExpectedVersion -ne $PackageVersion) {
    throw "HealthExpectedVersion must exactly match PackageVersion."
}
if ($SourceSha -notmatch '^[0-9a-fA-F]{40}$') {
    throw "SourceSha must be a full 40-character Git SHA."
}
Assert-CmxRelativeExecutablePath -Value $ExecutablePath

$healthUri = $null
if (-not [uri]::TryCreate($HealthUrl, [System.UriKind]::Absolute, [ref]$healthUri) -or
    $healthUri.Scheme -ne "http" -or
    $healthUri.Host -notin @("localhost", "127.0.0.1", "::1") -or
    $healthUri.UserInfo -or $healthUri.Query -or $healthUri.Fragment) {
    throw "HealthUrl must be an unauthenticated loopback HTTP URL without a query or fragment."
}

$artifact = Get-Item -LiteralPath $ArtifactPath -ErrorAction Stop
if ($artifact.PSIsContainer) {
    throw "ArtifactPath must identify a file."
}
if ($artifact.Length -le 0) {
    throw "ArtifactPath must identify a non-empty file."
}
if ($artifact.Length -gt 10GB) {
    throw "ArtifactPath exceeds the 10 GiB deployment limit."
}
Assert-CmxSafeLeaf -Value $artifact.Name -Label "Artifact file name"
if ($artifact.Extension -cne ".zip") {
    throw "ArtifactPath must identify a .zip deployment bundle."
}

$artifactHash = Get-CmxFileSha256 $artifact.FullName
$deploymentId = [guid]::NewGuid().ToString("D")
$createdAt = [DateTime]::UtcNow.ToString("o")

$manifest = [ordered]@{
    schemaVersion = 1
    deploymentId = $deploymentId
    package = [ordered]@{
        name = $PackageName
        version = $PackageVersion
        sourceSha = $SourceSha.ToLowerInvariant()
    }
    artifact = [ordered]@{
        fileName = $artifact.Name
        size = [int64]$artifact.Length
        sha256 = $artifactHash
    }
    service = [ordered]@{
        name = $ServiceName
        executablePath = ($ExecutablePath -replace '\\', '/')
    }
    health = [ordered]@{
        url = $healthUri.AbsoluteUri
        serviceId = $HealthServiceId
        expectedVersion = $HealthExpectedVersion
    }
    createdAt = $createdAt
}

$driveName = $null
$shareRoot = "\\$ComputerName\$ShareName"
try {
    if ($Credential) {
        $driveName = "CMX" + [guid]::NewGuid().ToString("N").Substring(0, 8)
        New-PSDrive -Name $driveName -PSProvider FileSystem -Root $shareRoot -Credential $Credential -Scope Script | Out-Null
        $shareRoot = "${driveName}:\"
    }

    $inboxRoot = Join-Path $shareRoot "inbox"
    $resultsRoot = Join-Path $shareRoot "results"
    New-Item -ItemType Directory -Force -Path $inboxRoot, $resultsRoot | Out-Null

    $deploymentRoot = Join-Path $inboxRoot $deploymentId
    if (Test-Path -LiteralPath $deploymentRoot) {
        throw "Deployment directory already exists: $deploymentRoot"
    }
    New-Item -ItemType Directory -Path $deploymentRoot | Out-Null

    $artifactPartial = Join-Path $deploymentRoot ($artifact.Name + ".partial")
    $artifactPublished = Join-Path $deploymentRoot $artifact.Name
    Copy-Item -LiteralPath $artifact.FullName -Destination $artifactPartial
    $stagedArtifact = Get-Item -LiteralPath $artifactPartial
    $stagedHash = Get-CmxFileSha256 $artifactPartial
    if ($stagedArtifact.Length -ne $artifact.Length -or $stagedHash -ne $artifactHash) {
        throw "Staged artifact size or SHA-256 does not match the local artifact."
    }
    Move-Item -LiteralPath $artifactPartial -Destination $artifactPublished

    $manifestPartial = Join-Path $deploymentRoot "manifest.json.partial"
    $manifestPublished = Join-Path $deploymentRoot "manifest.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPartial -Encoding UTF8
    Get-Content -LiteralPath $manifestPartial -Raw | ConvertFrom-Json | Out-Null
    Move-Item -LiteralPath $manifestPartial -Destination $manifestPublished

    # The agent's only activation signal. It must remain the final published file.
    $readyPartial = Join-Path $deploymentRoot "ready.partial"
    $readyPublished = Join-Path $deploymentRoot "ready"
    [System.IO.File]::WriteAllBytes($readyPartial, [byte[]]@())
    Move-Item -LiteralPath $readyPartial -Destination $readyPublished

    $resultPath = Join-Path $resultsRoot ($deploymentId + ".json")
    $resultDeadline = [DateTime]::UtcNow.AddSeconds($ResultTimeoutSeconds)
    while (-not (Test-Path -LiteralPath $resultPath)) {
        if ([DateTime]::UtcNow -ge $resultDeadline) {
            throw "Timed out waiting for deployment result $deploymentId after $ResultTimeoutSeconds seconds."
        }
        Start-Sleep -Seconds $PollIntervalSeconds
    }

    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    Assert-CmxExactPropertyNames -Object $result -Names @(
        "schemaVersion", "deploymentId", "status", "updatedAt", "previousRelease",
        "newRelease", "artifactSha256", "health", "error"
    ) -Context "Deployment result"
    $resultSchemaVersion = Get-CmxRequiredProperty -Object $result -Name "schemaVersion" -Context "Deployment result"
    if (($resultSchemaVersion -isnot [int] -and $resultSchemaVersion -isnot [long]) -or $resultSchemaVersion -ne 1) {
        throw "Deployment result schemaVersion is not 1."
    }
    if ((Get-CmxRequiredProperty -Object $result -Name "deploymentId" -Context "Deployment result") -ne $deploymentId) {
        throw "Deployment result deploymentId does not match $deploymentId."
    }
    $resultStatus = Get-CmxRequiredProperty -Object $result -Name "status" -Context "Deployment result"
    if ($resultStatus -eq "failed") {
        $resultError = Get-CmxRequiredProperty -Object $result -Name "error" -Context "Failed deployment result"
        $rollbackSummary = ""
        if ($result.health -and $result.health.phase -eq "rollback" -and $result.health.status -eq "ok") {
            $rollbackSummary = " Rollback health proved service '$($result.health.service_id)' version '$($result.health.version)'."
        }
        throw "Station deployment failed: $resultError$rollbackSummary"
    }
    if ($resultStatus -ne "succeeded") {
        throw "Deployment result has unsupported status '$resultStatus'."
    }
    if ((Get-CmxRequiredProperty -Object $result -Name "artifactSha256" -Context "Successful deployment result") -ne $artifactHash) {
        throw "Deployment result artifactSha256 does not match the published artifact."
    }

    $remoteHealthUri = Get-CmxRemoteHealthUri -ConfiguredUri $healthUri -Station $ComputerName
    $healthDeadline = [DateTime]::UtcNow.AddSeconds($HealthProbeTimeoutSeconds)
    $healthResponse = $null
    $lastHealthError = $null
    while ([DateTime]::UtcNow -lt $healthDeadline) {
        try {
            $healthResponse = Invoke-RestMethod -Uri $remoteHealthUri -Method Get -Headers $HealthHeaders -TimeoutSec ([Math]::Min(10, $HealthProbeTimeoutSeconds))
            $actualStatus = Get-CmxRequiredProperty -Object $healthResponse -Name "status" -Context "Remote health response"
            $actualServiceId = Get-CmxRequiredProperty -Object $healthResponse -Name "service_id" -Context "Remote health response"
            $actualVersion = Get-CmxRequiredProperty -Object $healthResponse -Name "version" -Context "Remote health response"
            if ($actualStatus -eq "ok" -and $actualServiceId -eq $HealthServiceId -and $actualVersion -eq $HealthExpectedVersion) {
                $lastHealthError = $null
                break
            }
            $lastHealthError = "Remote health status was '$actualStatus', identity '$actualServiceId', version '$actualVersion'."
        } catch {
            $lastHealthError = $_.Exception.Message
        }
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    if ($lastHealthError) {
        throw "Deployment succeeded, but independent health verification failed: $lastHealthError"
    }

    [pscustomobject]@{
        deploymentId = $deploymentId
        status = "succeeded"
        package = $PackageName
        version = $PackageVersion
        sourceSha = $SourceSha.ToLowerInvariant()
        artifactSha256 = $artifactHash
        resultPath = $resultPath
        healthUrl = $remoteHealthUri.AbsoluteUri
    }
} finally {
    if ($driveName) {
        Remove-PSDrive -Name $driveName -Force -ErrorAction SilentlyContinue
    }
}
