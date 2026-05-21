<#
.SYNOPSIS
    Shared build helpers for CellMax remote-access packages.

.DESCRIPTION
    Child CRA repos should keep build.ps1 thin. Put common bundle/build behavior here
    so CRA owns build flow and child repos only provide specifics.
#>

$script:CmxBuildCoreVersion = '1.2.1'

function Write-CmxBuildBanner {
    param([string]$Title)
    Write-Host ''
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Reset-CmxBuildPath {
    param([Parameter(Mandatory)][string]$Path)
    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Ensure-CmxBuildDirectory {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Invoke-CmxPoetryBootstrap {
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory,
        [switch]$SkipLock
    )
    Push-Location $ProjectDirectory
    try {
        Write-CmxBuildBanner "Poetry bootstrap"
        if (-not $SkipLock) {
            poetry lock
            if ($LASTEXITCODE -ne 0) {
                throw "poetry lock failed with exit code $LASTEXITCODE"
            }
        }
        poetry install
        if ($LASTEXITCODE -ne 0) {
            throw "poetry install failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Install-CmxPyInstallerDependencies {
    param([Parameter(Mandatory)][string]$ProjectDirectory)
    Push-Location $ProjectDirectory
    try {
        Write-CmxBuildBanner "PyInstaller dependencies"
        poetry run python -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) {
            throw "pip upgrade failed with exit code $LASTEXITCODE"
        }
        poetry run python -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib cffi
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller dependency install failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Copy-CmxBuildFiles {
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory,
        [Parameter(Mandatory)][string]$DestinationDirectory,
        [Parameter(Mandatory)][array]$Files
    )
    foreach ($item in $Files) {
        if ($item -is [string]) {
            if ([System.IO.Path]::IsPathRooted($item)) {
                $source = $item
            } else {
                $source = Join-Path $ProjectDirectory $item
            }
            $target = Join-Path $DestinationDirectory (Split-Path $item -Leaf)
        } else {
            if ([System.IO.Path]::IsPathRooted($item.Source)) {
                $source = $item.Source
            } else {
                $source = Join-Path $ProjectDirectory $item.Source
            }
            $target = Join-Path $DestinationDirectory $item.Destination
        }

        $targetDir = Split-Path -Parent $target
        if ($targetDir) {
            Ensure-CmxBuildDirectory -Path $targetDir
        }
        Copy-Item $source $target -Force
    }
}

function Get-CmxOptionalNssmSource {
    $candidates = @(
        $env:NSSM_EXE,
        "C:\ProgramData\chocolatey\bin\nssm.exe",
        "C:\nssm\win64\nssm.exe",
        "C:\nssm\nssm.exe",
        "C:\Program Files\nssm\nssm.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }
    return $null
}

function Compress-CmxArchiveRobust {
    param(
        [Parameter(Mandatory)][string]$SourcePath,
        [Parameter(Mandatory)][string]$DestinationPath,
        [int]$MaxAttempts = 10,
        [int]$RetrySeconds = 2
    )
    $destinationDir = Split-Path -Parent $DestinationPath
    if ($destinationDir) {
        Ensure-CmxBuildDirectory -Path $destinationDir
    }
    if (Test-Path $DestinationPath) {
        Remove-Item -LiteralPath $DestinationPath -Force
    }
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Compress-Archive -Path $SourcePath -DestinationPath $DestinationPath
            return
        } catch {
            if ($attempt -eq $MaxAttempts) {
                throw
            }
            Start-Sleep -Seconds $RetrySeconds
        }
    }
}

function Invoke-CmxPyInstallerBundleBuild {
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory,
        [Parameter(Mandatory)][string]$SpecPath,
        [Parameter(Mandatory)][string]$BundleDirectoryName,
        [Parameter(Mandatory)][string]$ZipPath,
        [array]$BundleFiles = @(),
        [switch]$SkipLock,
        [switch]$KeepBundleDirectory
    )
    $distBundlePath = Join-Path $ProjectDirectory "dist\$BundleDirectoryName"
    $buildPath = Join-Path $ProjectDirectory 'build'

    Write-CmxBuildBanner "Build PyInstaller bundle"
    Reset-CmxBuildPath -Path $distBundlePath
    Reset-CmxBuildPath -Path $buildPath

    Invoke-CmxPoetryBootstrap -ProjectDirectory $ProjectDirectory -SkipLock:$SkipLock
    Install-CmxPyInstallerDependencies -ProjectDirectory $ProjectDirectory

    Push-Location $ProjectDirectory
    try {
        poetry run python -m PyInstaller --clean --noconfirm $SpecPath
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }

    if ($BundleFiles.Count -gt 0) {
        Copy-CmxBuildFiles -ProjectDirectory $ProjectDirectory -DestinationDirectory $distBundlePath -Files $BundleFiles
    }

    Compress-CmxArchiveRobust -SourcePath $distBundlePath -DestinationPath $ZipPath

    if (-not $KeepBundleDirectory) {
        Reset-CmxBuildPath -Path $distBundlePath
    }
}

function New-CmxWheelBundle {
    param(
        [Parameter(Mandatory)][string]$OutputDirectory,
        [Parameter(Mandatory)][string]$WheelsDirectoryName,
        [Parameter(Mandatory)][array]$Repositories,
        [array]$Files = @()
    )
    $wheelsDirectory = Join-Path $OutputDirectory $WheelsDirectoryName

    Reset-CmxBuildPath -Path $OutputDirectory
    Ensure-CmxBuildDirectory -Path $wheelsDirectory

    foreach ($repo in $Repositories) {
        $repoPath = $repo.Path
        if (-not (Test-Path $repoPath)) {
            throw "Missing repository path: $repoPath"
        }
        Push-Location $repoPath
        try {
            Write-CmxBuildBanner "poetry build $($repo.Name)"
            $repoDist = Join-Path $repoPath 'dist'
            if (Test-Path $repoDist) {
                Remove-Item -LiteralPath $repoDist -Recurse -Force
            }
            poetry build
            if ($LASTEXITCODE -ne 0) {
                throw "poetry build failed for $($repo.Name)"
            }
            Get-ChildItem -Path $repoDist -Filter '*.whl' -File | ForEach-Object {
                Copy-Item $_.FullName -Destination $wheelsDirectory -Force
            }
        } finally {
            Pop-Location
        }
    }

    foreach ($file in $Files) {
        $source = $file.Source
        $target = Join-Path $OutputDirectory $file.Destination
        $targetDir = Split-Path -Parent $target
        if ($targetDir) {
            Ensure-CmxBuildDirectory -Path $targetDir
        }
        Copy-Item $source $target -Force
    }
}
