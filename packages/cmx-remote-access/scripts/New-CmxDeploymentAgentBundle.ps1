<#
.SYNOPSIS
    Build the portable Cellmax deployment-agent bootstrap ZIP.
#>

[CmdletBinding()]
param(
    [string]$OutputDirectory = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-CmxFileSha256 {
    param([Parameter(Mandatory)][string]$Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        return (($algorithm.ComputeHash($stream) | ForEach-Object { $_.ToString('x2') }) -join '')
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

$packageRoot = Split-Path -Parent $PSScriptRoot
$OutputDirectory = if ($OutputDirectory) { $OutputDirectory } else { Join-Path $packageRoot 'dist' }
$projectFile = Join-Path $packageRoot 'pyproject.toml'
$versionMatch = Select-String -LiteralPath $projectFile -Pattern '^version\s*=\s*"([^"]+)"\s*$' | Select-Object -First 1
if (-not $versionMatch) { throw "Could not read the deployment-agent version from $projectFile." }
$version = $versionMatch.Matches[0].Groups[1].Value
$bundleName = "cmx-deployment-agent-$version"

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$outputPath = Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) "$bundleName.zip"
$stagingRoot = Join-Path ([IO.Path]::GetTempPath()) ("$bundleName-" + [guid]::NewGuid().ToString('N'))

try {
    New-Item -ItemType Directory -Path $stagingRoot | Out-Null
    foreach ($name in @(
        'CmxDeploymentAgentCore.ps1',
        'Install-CmxDeploymentAgent.ps1',
        'Run-CmxDeploymentAgent.ps1',
        'Publish-CmxServiceRelease.ps1'
    )) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $stagingRoot
    }
    Copy-Item -LiteralPath (Join-Path $packageRoot 'README.md') -Destination (Join-Path $stagingRoot 'README.md')

    if (Test-Path -LiteralPath $outputPath) { Remove-Item -LiteralPath $outputPath -Force }
    Compress-Archive -Path (Join-Path $stagingRoot '*') -DestinationPath $outputPath -CompressionLevel Optimal
    $artifact = Get-Item -LiteralPath $outputPath
    [pscustomobject]@{
        path = $artifact.FullName
        version = $version
        size = $artifact.Length
        sha256 = Get-CmxFileSha256 $artifact.FullName
    }
} finally {
    if (Test-Path -LiteralPath $stagingRoot) { Remove-Item -LiteralPath $stagingRoot -Recurse -Force }
}
