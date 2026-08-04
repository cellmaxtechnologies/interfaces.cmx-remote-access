<#
.SYNOPSIS
    Fail-closed deployment primitives used by the Cellmax station agent.

.DESCRIPTION
    The agent accepts artifacts only. Configuration and Windows service credentials
    remain station-local and are never represented in the deployment manifest.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:CmxDeploymentSchemaVersion = 1
$script:CmxDeploymentMaxArchiveBytes = 10GB
$script:CmxDeploymentMaxExpandedBytes = 20GB

function Assert-CmxExactProperties {
    param(
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string[]]$Names,
        [Parameter(Mandatory)][string]$Context
    )
    if ($null -eq $Value) { throw "$Context must be an object." }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($Names | Sort-Object)
    if (($actual -join "`n") -ne ($expected -join "`n")) {
        throw "$Context must contain exactly: $($Names -join ', ')."
    }
}

function Assert-CmxNoDuplicateJsonKeys {
    param([Parameter(Mandatory)][string]$Json)
    $stack = New-Object System.Collections.ArrayList
    for ($i = 0; $i -lt $Json.Length; $i++) {
        $character = $Json[$i]
        if ($character -eq '"') {
            $start = $i
            $i++
            while ($i -lt $Json.Length) {
                if ($Json[$i] -eq '\') { $i += 2; continue }
                if ($Json[$i] -eq '"') { break }
                $i++
            }
            if ($i -ge $Json.Length) { throw 'Invalid unterminated JSON string.' }
            if ($stack.Count -gt 0 -and $stack[$stack.Count - 1].Type -eq 'object' -and $stack[$stack.Count - 1].ExpectKey) {
                $next = $i + 1
                while ($next -lt $Json.Length -and [char]::IsWhiteSpace($Json[$next])) { $next++ }
                if ($next -lt $Json.Length -and $Json[$next] -eq ':') {
                    $token = $Json.Substring($start, $i - $start + 1)
                    $key = [string](("{`"value`":$token}" | ConvertFrom-Json).value)
                    $frame = $stack[$stack.Count - 1]
                    if (-not $frame.Keys.Add($key)) { throw "Duplicate JSON property is not allowed: $key" }
                    $frame.ExpectKey = $false
                }
            }
            continue
        }
        if ($character -eq '{') {
            [void]$stack.Add([pscustomobject]@{ Type = 'object'; ExpectKey = $true; Keys = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase) })
        } elseif ($character -eq '[') {
            [void]$stack.Add([pscustomobject]@{ Type = 'array'; ExpectKey = $false; Keys = $null })
        } elseif ($character -eq '}' -or $character -eq ']') {
            if ($stack.Count -gt 0) { $stack.RemoveAt($stack.Count - 1) }
        } elseif ($character -eq ',' -and $stack.Count -gt 0 -and $stack[$stack.Count - 1].Type -eq 'object') {
            $stack[$stack.Count - 1].ExpectKey = $true
        }
    }
}

function Resolve-CmxContainedPath {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$RelativePath
    )
    if ([IO.Path]::IsPathRooted($RelativePath)) { throw "Absolute paths are not allowed: $RelativePath" }
    if ([string]::IsNullOrWhiteSpace($RelativePath)) { throw 'Relative path must not be empty.' }
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $candidate = [IO.Path]::GetFullPath((Join-Path $rootFull $RelativePath))
    $prefix = $rootFull + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes its allowed root: $RelativePath"
    }
    return $candidate
}

function Get-CmxFileSha256 {
    param([Parameter(Mandatory)][string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

function Read-CmxDeploymentManifest {
    param([Parameter(Mandatory)][string]$Path)

    $rawManifest = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    Assert-CmxNoDuplicateJsonKeys $rawManifest
    $manifest = $rawManifest | ConvertFrom-Json
    Assert-CmxExactProperties $manifest @('schemaVersion','deploymentId','package','artifact','service','health','createdAt') 'manifest'
    Assert-CmxExactProperties $manifest.package @('name','version','sourceSha') 'manifest.package'
    Assert-CmxExactProperties $manifest.artifact @('fileName','size','sha256') 'manifest.artifact'
    Assert-CmxExactProperties $manifest.service @('name','executablePath') 'manifest.service'
    Assert-CmxExactProperties $manifest.health @('url','serviceId','expectedVersion') 'manifest.health'

    if ($manifest.schemaVersion -isnot [int] -and $manifest.schemaVersion -isnot [long]) { throw 'manifest.schemaVersion must be a JSON integer.' }
    if ([long]$manifest.schemaVersion -ne $script:CmxDeploymentSchemaVersion) { throw 'Unsupported manifest schemaVersion.' }
    if ([string]$manifest.deploymentId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' -or [string]$manifest.deploymentId -match '\.\.') { throw 'Invalid deploymentId.' }
    if ([string]$manifest.package.name -cnotmatch '^[a-z0-9][a-z0-9._-]{0,63}$' -or [string]$manifest.package.name -match '\.\.') { throw 'Invalid package.name.' }
    $semverIdentifier = '(?:(?:0|[1-9][0-9]*)|(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))'
    $semverPattern = "^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-$semverIdentifier(?:\.$semverIdentifier)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
    if ([string]$manifest.package.version -cnotmatch $semverPattern) { throw 'Invalid package.version.' }
    if ([string]$manifest.package.sourceSha -notmatch '^[0-9a-fA-F]{40}$') { throw 'Invalid package.sourceSha.' }
    if ([string]$manifest.artifact.fileName -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.zip$') { throw 'Invalid artifact.fileName.' }
    if ($manifest.artifact.size -isnot [int] -and $manifest.artifact.size -isnot [long]) { throw 'artifact.size must be a JSON integer.' }
    $size = [long]$manifest.artifact.size
    if ($size -lt 1 -or $size -gt $script:CmxDeploymentMaxArchiveBytes) { throw 'Invalid artifact.size.' }
    if ([string]$manifest.artifact.sha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'Invalid artifact.sha256.' }
    if ([string]$manifest.service.name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' -or [string]$manifest.service.name -match '\.\.') { throw 'Invalid service.name.' }
    $executablePath = [string]$manifest.service.executablePath
    if (-not $executablePath -or $executablePath.Contains('\') -or $executablePath.Contains(':')) { throw 'Invalid service.executablePath.' }
    foreach ($segment in $executablePath.Split('/')) {
        if ($segment -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' -or $segment -match '\.\.') { throw 'Invalid service.executablePath.' }
    }
    [void](Resolve-CmxContainedPath -Root ([IO.Path]::GetTempPath()) -RelativePath $executablePath)
    if ([string]$manifest.health.serviceId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' -or [string]$manifest.health.serviceId -match '\.\.') { throw 'Invalid health.serviceId.' }
    if ([string]$manifest.health.expectedVersion -ne [string]$manifest.package.version) { throw 'health.expectedVersion must equal package.version.' }
    $healthUri = $null
    if (-not [Uri]::TryCreate([string]$manifest.health.url, [UriKind]::Absolute, [ref]$healthUri)) { throw 'Invalid health.url.' }
    if ($healthUri.Scheme -ne 'http' -or $healthUri.Host -notin @('127.0.0.1','localhost','::1') -or $healthUri.UserInfo -or $healthUri.Query -or $healthUri.Fragment) {
        throw 'health.url must be an unauthenticated loopback HTTP URL without a query or fragment.'
    }
    # PowerShell 7 converts ISO JSON strings to local DateTime values. Validate
    # the original JSON token so UTC offset information is not lost.
    $createdMatch = [regex]::Match($rawManifest, '"createdAt"\s*:\s*"([^"]+)"')
    $created = [DateTimeOffset]::MinValue
    if (-not $createdMatch.Success -or -not [DateTimeOffset]::TryParse($createdMatch.Groups[1].Value, [ref]$created) -or $created.Offset -ne [TimeSpan]::Zero) { throw 'Invalid createdAt.' }
    return $manifest
}

function Read-CmxDeploymentAllowlist {
    param([Parameter(Mandatory)][string]$Path)
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    Assert-CmxNoDuplicateJsonKeys $raw
    $allowlist = $raw | ConvertFrom-Json
    Assert-CmxExactProperties $allowlist @('schemaVersion','profiles') 'deployment allowlist'
    if (($allowlist.schemaVersion -isnot [int] -and $allowlist.schemaVersion -isnot [long]) -or [long]$allowlist.schemaVersion -ne 1) { throw 'Invalid deployment allowlist schemaVersion.' }
    foreach ($profile in @($allowlist.profiles)) {
        Assert-CmxExactProperties $profile @('packageName','serviceName','healthUrl','serviceId','executablePath') 'deployment allowlist profile'
    }
    return $allowlist
}

function Assert-CmxDeploymentAllowed {
    param([Parameter(Mandatory)]$Manifest, [Parameter(Mandatory)][string]$AllowlistPath)
    $allowlist = Read-CmxDeploymentAllowlist $AllowlistPath
    $matches = @($allowlist.profiles | Where-Object {
        [string]$_.packageName -ceq [string]$Manifest.package.name -and
        [string]$_.serviceName -ceq [string]$Manifest.service.name -and
        [string]$_.healthUrl -ceq [string]$Manifest.health.url -and
        [string]$_.serviceId -ceq [string]$Manifest.health.serviceId -and
        [string]$_.executablePath -ceq [string]$Manifest.service.executablePath
    })
    if ($matches.Count -ne 1) { throw 'Deployment manifest does not match one exact station-local allowlist profile.' }
}

function Stage-CmxDeploymentToProtectedQueue {
    param(
        [Parameter(Mandatory)][string]$InboxDeploymentDirectory,
        [Parameter(Mandatory)][string]$QueueRoot,
        [Parameter(Mandatory)][string]$AllowlistPath
    )
    $folderId = Split-Path -Leaf $InboxDeploymentDirectory
    if ($folderId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' -or $folderId -match '\.\.') { throw 'Invalid inbox deployment directory name.' }
    New-Item -ItemType Directory -Force -Path $QueueRoot | Out-Null
    $protected = Resolve-CmxContainedPath $QueueRoot $folderId
    if (Test-Path -LiteralPath (Join-Path $protected 'claimed') -PathType Leaf) { return $protected }
    if (Test-Path -LiteralPath $protected) { Remove-Item -LiteralPath $protected -Recurse -Force }
    $partial = Resolve-CmxContainedPath $QueueRoot "$folderId.partial"
    if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Recurse -Force }
    New-Item -ItemType Directory -Path $partial | Out-Null
    try {
        Copy-Item -LiteralPath (Join-Path $InboxDeploymentDirectory 'manifest.json') -Destination (Join-Path $partial 'manifest.json')
        $manifest = Read-CmxDeploymentManifest (Join-Path $partial 'manifest.json')
        if ([string]$manifest.deploymentId -ne $folderId) { throw 'Deployment directory name must equal manifest deploymentId.' }
        Assert-CmxDeploymentAllowed $manifest $AllowlistPath
        $sourceArtifact = Resolve-CmxContainedPath $InboxDeploymentDirectory ([string]$manifest.artifact.fileName)
        $protectedArtifact = Resolve-CmxContainedPath $partial ([string]$manifest.artifact.fileName)
        Copy-Item -LiteralPath $sourceArtifact -Destination $protectedArtifact
        [void](Test-CmxDeploymentArtifact $manifest $partial)
        New-Item -ItemType File -Path (Join-Path $partial 'claimed') | Out-Null
        Move-Item -LiteralPath $partial -Destination $protected
        return $protected
    } catch {
        Remove-Item -LiteralPath $partial -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Test-CmxDeploymentArtifact {
    param(
        [Parameter(Mandatory)]$Manifest,
        [Parameter(Mandatory)][string]$DeploymentDirectory
    )
    $path = Resolve-CmxContainedPath -Root $DeploymentDirectory -RelativePath ([string]$Manifest.artifact.fileName)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Artifact is missing: $path" }
    $item = Get-Item -LiteralPath $path
    if ($item.Length -ne [long]$Manifest.artifact.size) { throw 'Artifact size does not match manifest.' }
    $hash = Get-CmxFileSha256 $path
    if ($hash -ne ([string]$Manifest.artifact.sha256).ToLowerInvariant()) { throw 'Artifact SHA-256 does not match manifest.' }
    return $path
}

function Expand-CmxDeploymentArchive {
    param(
        [Parameter(Mandatory)][string]$ArchivePath,
        [Parameter(Mandatory)][string]$Destination
    )
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $Destination) { throw "Release already exists: $Destination" }
    New-Item -ItemType Directory -Path $Destination | Out-Null
    try {
        $archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
        try {
            $expandedBytes = 0L
            foreach ($entry in $archive.Entries) {
                $expandedBytes += [long]$entry.Length
                if ($expandedBytes -gt $script:CmxDeploymentMaxExpandedBytes) { throw 'Archive expands beyond the configured safety limit.' }
                if ([string]::IsNullOrEmpty($entry.FullName)) { throw 'Archive contains an unnamed entry.' }
                $target = Resolve-CmxContainedPath -Root $Destination -RelativePath $entry.FullName
                $unixMode = ([int64]$entry.ExternalAttributes -shr 16) -band 0xF000
                if ($unixMode -eq 0xA000 -or (($entry.ExternalAttributes -band 0x400) -ne 0)) { throw "Archive links are not allowed: $($entry.FullName)" }
                if ($entry.FullName.EndsWith('/') -or $entry.FullName.EndsWith('\')) {
                    New-Item -ItemType Directory -Force -Path $target | Out-Null
                    continue
                }
                $parent = Split-Path -Parent $target
                New-Item -ItemType Directory -Force -Path $parent | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $false)
            }
        } finally {
            $archive.Dispose()
        }
    } catch {
        Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Enter-CmxDeploymentLock {
    param(
        [Parameter(Mandatory)][string]$LockDirectory,
        [Parameter(Mandatory)][string]$PackageName
    )
    New-Item -ItemType Directory -Force -Path $LockDirectory | Out-Null
    $lockPath = Resolve-CmxContainedPath -Root $LockDirectory -RelativePath "$PackageName.lock"
    try {
        # OpenOrCreate makes a harmless stale lock file recoverable after a process
        # crash; FileShare.None is the actual live-process exclusion boundary.
        $stream = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $stream.SetLength(0)
        $bytes = [Text.Encoding]::UTF8.GetBytes("$PID`n")
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        return [pscustomobject]@{ Path = $lockPath; Stream = $stream }
    } catch [IO.IOException] {
        throw "Deployment lock is already held for package '$PackageName'."
    }
}

function Exit-CmxDeploymentLock {
    param($Lock)
    if ($null -eq $Lock) { return }
    $Lock.Stream.Dispose()
    Remove-Item -LiteralPath $Lock.Path -Force -ErrorAction SilentlyContinue
}

function Get-CmxNssmValue {
    param([string]$NssmExe, [string]$ServiceName, [string]$Key)
    $output = & $NssmExe get $ServiceName $Key 2>&1
    if ($LASTEXITCODE -ne 0) { throw "NSSM could not read $Key for service '$ServiceName'." }
    return (($output | ForEach-Object { [string]$_ }) -join "`n").Trim()
}

function Set-CmxDeploymentNssmValue {
    param([string]$NssmExe, [string]$ServiceName, [string]$Key, [string]$Value)
    if ($Key -notin @('Application','AppDirectory')) { throw "Deployment agent may not modify NSSM key '$Key'." }
    & $NssmExe set $ServiceName $Key $Value | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "NSSM could not set $Key for service '$ServiceName'." }
}

function Get-CmxDeploymentServiceState {
    param([string]$ServiceName, [string]$NssmExe)
    $service = Get-CimInstance Win32_Service -Filter "Name='$($ServiceName.Replace("'", "''"))'" -ErrorAction SilentlyContinue
    if (-not $service) { throw "Existing Windows service '$ServiceName' was not found; first install is intentionally unsupported." }
    return [pscustomobject]@{
        ObjectName = [string]$service.StartName
        Application = Get-CmxNssmValue $NssmExe $ServiceName 'Application'
        AppDirectory = Get-CmxNssmValue $NssmExe $ServiceName 'AppDirectory'
    }
}

function Stop-CmxDeploymentService {
    param([string]$ServiceName)
    Stop-Service -Name $ServiceName -Force -ErrorAction Stop
    $service = Get-Service -Name $ServiceName
    $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))
}

function Start-CmxDeploymentService {
    param([string]$ServiceName)
    Start-Service -Name $ServiceName -ErrorAction Stop
}

function Grant-CmxDeploymentReleaseReadExecute {
    param(
        [Parameter(Mandatory)][string]$ReleasePath,
        [Parameter(Mandatory)][string]$ServiceAccount
    )
    if (-not (Test-Path -LiteralPath $ReleasePath -PathType Container)) { throw 'Prepared release directory is missing.' }
    $normalizedServiceAccount = if ($ServiceAccount -match '^\.\\(.+)$') {
        "$env:COMPUTERNAME\$($Matches[1])"
    } else {
        $ServiceAccount
    }
    $aclAccount = switch ($normalizedServiceAccount) {
        'LocalSystem' { '*S-1-5-18' }
        'NT AUTHORITY\SYSTEM' { '*S-1-5-18' }
        'NT AUTHORITY\LocalService' { '*S-1-5-19' }
        'NT AUTHORITY\LOCAL SERVICE' { '*S-1-5-19' }
        'NT AUTHORITY\NetworkService' { '*S-1-5-20' }
        'NT AUTHORITY\NETWORK SERVICE' { '*S-1-5-20' }
        default { $normalizedServiceAccount }
    }
    & icacls.exe $ReleasePath '/grant:r' "$aclAccount`:(OI)(CI)RX" '/T' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not grant release read/execute access to service identity '$ServiceAccount'." }
}

function Wait-CmxDeploymentHealth {
    param($Health, [int]$Attempts = 30, [int]$DelaySeconds = 2)
    $last = $null
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $last = Invoke-RestMethod -Uri ([string]$Health.url) -Method Get -TimeoutSec 3
            if ($last.status -eq 'ok' -and $last.service_id -eq [string]$Health.serviceId -and $last.version -eq [string]$Health.expectedVersion) {
                return $last
            }
        } catch { $last = [pscustomobject]@{ error = $_.Exception.Message } }
        Start-Sleep -Seconds $DelaySeconds
    }
    throw "Health did not report exact service_id '$($Health.serviceId)' and version '$($Health.expectedVersion)'. Last response: $($last | ConvertTo-Json -Compress -Depth 10)"
}

function Get-CmxDeploymentBaselineHealth {
    param($Health)
    $response = Invoke-RestMethod -Uri ([string]$Health.url) -Method Get -TimeoutSec 3
    if ($response.status -ne 'ok' -or $response.service_id -ne [string]$Health.serviceId -or [string]$response.version -notmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') {
        throw 'Existing service did not provide a valid baseline health identity/version.'
    }
    return $response
}

function Write-CmxDeploymentResult {
    param([string]$ResultsDirectory, [string]$DeploymentId, $Result)
    New-Item -ItemType Directory -Force -Path $ResultsDirectory | Out-Null
    $resultPath = Resolve-CmxContainedPath -Root $ResultsDirectory -RelativePath "$DeploymentId.json"
    $tempPath = "$resultPath.$PID.tmp"
    $Result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tempPath -Encoding UTF8
    Move-Item -LiteralPath $tempPath -Destination $resultPath -Force
    return $resultPath
}

function Write-CmxDeploymentJournal {
    param([string]$Path, $Journal)
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $tempPath = "$Path.$PID.tmp"
    $Journal | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $tempPath -Encoding UTF8
    Move-Item -LiteralPath $tempPath -Destination $Path -Force
}

function Read-CmxDeploymentJournal {
    param([string]$Path, $Manifest, [string]$NewRelease, [string]$NewApplication)
    $journal = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-CmxExactProperties $journal @(
        'schemaVersion','deploymentId','serviceName','artifactSha256','objectName',
        'previousApplication','previousAppDirectory','previousHealthVersion','previousHealthServiceId',
        'newApplication','newRelease','preparedAt'
    ) 'deployment journal'
    if ([int]$journal.schemaVersion -ne 1 -or
        [string]$journal.deploymentId -ne [string]$Manifest.deploymentId -or
        [string]$journal.serviceName -ne [string]$Manifest.service.name -or
        [string]$journal.artifactSha256 -ne ([string]$Manifest.artifact.sha256).ToLowerInvariant() -or
        [string]$journal.previousHealthServiceId -ne [string]$Manifest.health.serviceId -or
        [string]$journal.newApplication -ne $NewApplication -or
        [string]$journal.newRelease -ne $NewRelease) {
        throw 'Station-local deployment journal does not match the requested deployment.'
    }
    return $journal
}

function Invoke-CmxDeployment {
    param(
        [Parameter(Mandatory)][string]$DeploymentDirectory,
        [Parameter(Mandatory)][string]$ReleasesRoot,
        [Parameter(Mandatory)][string]$LocksDirectory,
        [Parameter(Mandatory)][string]$ResultsDirectory,
        [Parameter(Mandatory)][string]$AllowlistPath,
        [Parameter(Mandatory)][string]$NssmExe
    )
    $folderId = Split-Path -Leaf $DeploymentDirectory
    $manifest = $null
    $lock = $null
    $previous = $null
    $newRelease = $null
    $artifactSha = $null
    $healthResult = $null
    $switched = $false
    $transactionPrepared = $false
    try {
        $manifest = Read-CmxDeploymentManifest (Join-Path $DeploymentDirectory 'manifest.json')
        if ([string]$manifest.deploymentId -ne $folderId) { throw 'Deployment directory name must equal manifest deploymentId.' }
        Assert-CmxDeploymentAllowed $manifest $AllowlistPath
        $lock = Enter-CmxDeploymentLock $LocksDirectory ([string]$manifest.package.name)
        $archive = Test-CmxDeploymentArtifact $manifest $DeploymentDirectory
        $artifactSha = ([string]$manifest.artifact.sha256).ToLowerInvariant()
        $packageRoot = Resolve-CmxContainedPath $ReleasesRoot ([string]$manifest.package.name)
        New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
        $newRelease = Resolve-CmxContainedPath $packageRoot ([string]$manifest.package.version)
        $newApplication = Resolve-CmxContainedPath $newRelease ([string]$manifest.service.executablePath)
        $journalPath = Resolve-CmxContainedPath $LocksDirectory "$($manifest.deploymentId).journal.json"
        if (Test-Path -LiteralPath $journalPath -PathType Leaf) {
            $journal = Read-CmxDeploymentJournal $journalPath $manifest $newRelease $newApplication
            $previous = [pscustomobject]@{
                ObjectName = [string]$journal.objectName
                Application = [string]$journal.previousApplication
                AppDirectory = [string]$journal.previousAppDirectory
                HealthVersion = [string]$journal.previousHealthVersion
                HealthServiceId = [string]$journal.previousHealthServiceId
            }
            if (-not (Test-Path -LiteralPath $newApplication -PathType Leaf)) { throw 'Prepared release executable is missing.' }
        } else {
            $releaseMarkerPath = Resolve-CmxContainedPath $newRelease '.cmx-release.json'
            if (Test-Path -LiteralPath $newRelease) {
                if (-not (Test-Path -LiteralPath $releaseMarkerPath -PathType Leaf)) { throw "Immutable release already exists: $newRelease" }
                $releaseMarker = Get-Content -LiteralPath $releaseMarkerPath -Raw -Encoding UTF8 | ConvertFrom-Json
                Assert-CmxExactProperties $releaseMarker @('schemaVersion','deploymentId','serviceName','artifactSha256') 'release marker'
                if ([int]$releaseMarker.schemaVersion -ne 1 -or
                    [string]$releaseMarker.deploymentId -ne [string]$manifest.deploymentId -or
                    [string]$releaseMarker.serviceName -ne [string]$manifest.service.name -or
                    [string]$releaseMarker.artifactSha256 -ne $artifactSha) {
                    throw "Immutable release belongs to another deployment: $newRelease"
                }
                if (-not (Test-Path -LiteralPath $newApplication -PathType Leaf)) { throw 'Prepared release executable is missing.' }
            } else {
                $partialRelease = "$newRelease.$($manifest.deploymentId).partial"
                if (Test-Path -LiteralPath $partialRelease) { Remove-Item -LiteralPath $partialRelease -Recurse -Force }
                Expand-CmxDeploymentArchive $archive $partialRelease
                $partialApplication = Resolve-CmxContainedPath $partialRelease ([string]$manifest.service.executablePath)
                if (-not (Test-Path -LiteralPath $partialApplication -PathType Leaf)) { throw 'Manifest service executablePath does not exist in the artifact.' }
                $partialMarkerPath = Resolve-CmxContainedPath $partialRelease '.cmx-release.json'
                $releaseMarker = [ordered]@{
                    schemaVersion = 1; deploymentId = [string]$manifest.deploymentId
                    serviceName = [string]$manifest.service.name; artifactSha256 = $artifactSha
                }
                $releaseMarker | ConvertTo-Json | Set-Content -LiteralPath $partialMarkerPath -Encoding UTF8
                Move-Item -LiteralPath $partialRelease -Destination $newRelease
            }
            $previous = Get-CmxDeploymentServiceState ([string]$manifest.service.name) $NssmExe
            $baselineHealth = Get-CmxDeploymentBaselineHealth $manifest.health
            $previous | Add-Member -NotePropertyName HealthVersion -NotePropertyValue ([string]$baselineHealth.version)
            $previous | Add-Member -NotePropertyName HealthServiceId -NotePropertyValue ([string]$baselineHealth.service_id)
            $journal = [ordered]@{
                schemaVersion = 1; deploymentId = [string]$manifest.deploymentId
                serviceName = [string]$manifest.service.name; artifactSha256 = $artifactSha
                objectName = [string]$previous.ObjectName; previousApplication = [string]$previous.Application
                previousAppDirectory = [string]$previous.AppDirectory
                previousHealthVersion = [string]$previous.HealthVersion; previousHealthServiceId = [string]$previous.HealthServiceId
                newApplication = $newApplication
                newRelease = $newRelease; preparedAt = [DateTimeOffset]::UtcNow.ToString('o')
            }
            Write-CmxDeploymentJournal $journalPath $journal
        }
        Grant-CmxDeploymentReleaseReadExecute $newRelease ([string]$previous.ObjectName)
        $transactionPrepared = $true
        $current = Get-CmxDeploymentServiceState ([string]$manifest.service.name) $NssmExe
        if ([string]$current.ObjectName -ne [string]$previous.ObjectName) { throw 'Windows service identity changed before deployment.' }
        if ([string]$current.Application -ne $newApplication -or [string]$current.AppDirectory -ne $newRelease) {
            Stop-CmxDeploymentService ([string]$manifest.service.name)
            Set-CmxDeploymentNssmValue $NssmExe ([string]$manifest.service.name) 'Application' $newApplication
            Set-CmxDeploymentNssmValue $NssmExe ([string]$manifest.service.name) 'AppDirectory' $newRelease
            Start-CmxDeploymentService ([string]$manifest.service.name)
        } elseif ((Get-Service -Name ([string]$manifest.service.name)).Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running) {
            Start-CmxDeploymentService ([string]$manifest.service.name)
        }
        $switched = $true
        $healthResult = Wait-CmxDeploymentHealth $manifest.health
        $after = Get-CimInstance Win32_Service -Filter "Name='$(([string]$manifest.service.name).Replace("'", "''"))'"
        if ([string]$after.StartName -ne [string]$previous.ObjectName) { throw 'Windows service identity changed unexpectedly.' }

        $result = [ordered]@{
            schemaVersion = 1; deploymentId = [string]$manifest.deploymentId; status = 'succeeded'
            updatedAt = [DateTimeOffset]::UtcNow.ToString('o'); previousRelease = [string]$previous.AppDirectory
            newRelease = $newRelease; artifactSha256 = $artifactSha; health = $healthResult; error = $null
        }
        return Write-CmxDeploymentResult $ResultsDirectory ([string]$manifest.deploymentId) $result
    } catch {
        $failure = $_.Exception.Message
        if (($switched -or $transactionPrepared) -and $manifest -and $previous) {
            try {
                Stop-Service -Name ([string]$manifest.service.name) -Force -ErrorAction SilentlyContinue
                Set-CmxDeploymentNssmValue $NssmExe ([string]$manifest.service.name) 'Application' ([string]$previous.Application)
                Set-CmxDeploymentNssmValue $NssmExe ([string]$manifest.service.name) 'AppDirectory' ([string]$previous.AppDirectory)
                Start-CmxDeploymentService ([string]$manifest.service.name)
                $rollbackService = Get-CimInstance Win32_Service -Filter "Name='$(([string]$manifest.service.name).Replace("'", "''"))'"
                if ([string]$rollbackService.StartName -ne [string]$previous.ObjectName) { throw 'Rollback did not preserve the Windows service identity.' }
                $rollbackHealth = [pscustomobject]@{
                    url = [string]$manifest.health.url
                    serviceId = [string]$previous.HealthServiceId
                    expectedVersion = [string]$previous.HealthVersion
                }
                $rollbackResponse = Wait-CmxDeploymentHealth $rollbackHealth
                $healthResult = [ordered]@{
                    phase = 'rollback'; status = 'ok'
                    service_id = [string]$rollbackResponse.service_id
                    version = [string]$rollbackResponse.version
                    checkedAt = [DateTimeOffset]::UtcNow.ToString('o')
                }
            } catch { $failure = "$failure Rollback also failed: $($_.Exception.Message)" }
        }
        $deploymentId = if ($manifest) { [string]$manifest.deploymentId } else { $folderId }
        $result = [ordered]@{
            schemaVersion = 1; deploymentId = $deploymentId; status = 'failed'
            updatedAt = [DateTimeOffset]::UtcNow.ToString('o'); previousRelease = if ($previous) { [string]$previous.AppDirectory } else { $null }
            newRelease = $newRelease; artifactSha256 = $artifactSha; health = $healthResult; error = $failure
        }
        [void](Write-CmxDeploymentResult $ResultsDirectory $deploymentId $result)
        throw
    } finally {
        Exit-CmxDeploymentLock $lock
    }
}
