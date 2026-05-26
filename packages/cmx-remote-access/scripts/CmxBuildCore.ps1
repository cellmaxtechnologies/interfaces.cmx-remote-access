<#
.SYNOPSIS
    Shared build helpers for CellMax remote-access packages.

.DESCRIPTION
    Child CRA repos should keep build.ps1 thin. Put common bundle/build behavior here
    so CRA owns build flow and child repos only provide specifics.
#>

$script:CmxBuildCoreVersion = '1.4.0'

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

function Get-CmxPoetryGitDependencyNames {
    param([Parameter(Mandatory)][string]$ProjectDirectory)
    $pyprojectPath = Join-Path $ProjectDirectory 'pyproject.toml'
    if (-not (Test-Path $pyprojectPath)) {
        return @()
    }

    $names = New-Object System.Collections.Generic.List[string]
    $inDependencies = $false
    foreach ($rawLine in Get-Content $pyprojectPath) {
        $line = $rawLine.Trim()
        if ($line -match '^\[tool\.poetry\.dependencies\]$') {
            $inDependencies = $true
            continue
        }
        if ($inDependencies -and $line -match '^\[') {
            break
        }
        if (-not $inDependencies -or -not $line -or $line.StartsWith('#')) {
            continue
        }
        if ($line -match '^([A-Za-z0-9._-]+)\s*=\s*\{[^}]*\bgit\s*=') {
            $names.Add($matches[1])
        }
    }
    return @($names | Select-Object -Unique)
}

function Invoke-CmxPoetryRefreshGitDependencies {
    param([Parameter(Mandatory)][string]$ProjectDirectory)
    $gitDependencies = Get-CmxPoetryGitDependencyNames -ProjectDirectory $ProjectDirectory
    if (-not $gitDependencies -or $gitDependencies.Count -eq 0) {
        return
    }

    Write-CmxBuildBanner "Refresh git dependencies"
    poetry update @gitDependencies
    if ($LASTEXITCODE -ne 0) {
        throw "poetry update failed for git dependencies: $($gitDependencies -join ', ')"
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
        Invoke-CmxPoetryRefreshGitDependencies -ProjectDirectory $ProjectDirectory
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
    $vendored = Join-Path $PSScriptRoot '..\tools\nssm.exe'
    if (Test-Path $vendored) {
        return (Resolve-Path $vendored).Path
    }
    $candidates = @(
        $env:NSSM_EXE,
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
    $archiveInputs = @()
    if (Test-Path $SourcePath -PathType Container) {
        $archiveInputs = @(Get-ChildItem -LiteralPath $SourcePath -Force | ForEach-Object { $_.FullName })
        if ($archiveInputs.Count -eq 0) {
            throw "Cannot create archive from empty directory: $SourcePath"
        }
    } else {
        $archiveInputs = @($SourcePath)
    }
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Compress-Archive -Path $archiveInputs -DestinationPath $DestinationPath
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

function New-CmxRemoteAccessWheelBundle {
    <#
    .SYNOPSIS
        Build a standard CRA copy-only wheel bundle for a service package.
    #>
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory,
        [Parameter(Mandatory)][string]$PackageName,
        [array]$ExtraRepositories = @(),
        [string]$OutputDirectoryName = 'dist-bundle',
        [string]$WheelsDirectoryName = 'wheels'
    )

    $craRoot = Join-Path $ProjectDirectory '..\..\interfaces\cmx-remote-access\packages\cmx-remote-access'
    if (-not (Test-Path $craRoot)) {
        throw "Missing CRA package root: $craRoot"
    }

    $repositories = @()
    foreach ($repo in $ExtraRepositories) {
        $repositories += $repo
    }
    $repositories += @{ Name = 'cmx-remote-access'; Path = $craRoot }
    $repositories += @{ Name = $PackageName; Path = $ProjectDirectory }

    $bundleFiles = @(
        @{ Source = (Join-Path $ProjectDirectory 'install-portable.ps1'); Destination = 'install-portable.ps1' },
        @{ Source = (Join-Path $ProjectDirectory 'install-service.ps1'); Destination = 'install-service.ps1' },
        @{ Source = (Join-Path $ProjectDirectory '.env.example'); Destination = '.env.example' },
        @{ Source = (Join-Path $craRoot 'scripts\CmxInstallCore.ps1'); Destination = 'scripts\CmxInstallCore.ps1' },
        @{ Source = (Join-Path $craRoot 'scripts\CmxWindowsServiceCore.ps1'); Destination = 'scripts\CmxWindowsServiceCore.ps1' }
    )
    $nssmSource = Get-CmxOptionalNssmSource
    if ($nssmSource) {
        $bundleFiles += @{ Source = $nssmSource; Destination = 'tools\nssm.exe' }
    }

    New-CmxWheelBundle `
        -OutputDirectory (Join-Path $ProjectDirectory $OutputDirectoryName) `
        -WheelsDirectoryName $WheelsDirectoryName `
        -Repositories $repositories `
        -Files $bundleFiles
}

function Invoke-CmxRemoteAccessBundleBuild {
    <#
    .SYNOPSIS
        Bootstrap Poetry, build a standard CRA wheel bundle, and zip it.
    #>
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory,
        [Parameter(Mandatory)][string]$PackageName,
        [array]$ExtraRepositories = @(),
        [string]$OutputDirectoryName = 'dist-bundle',
        [string]$ZipFileName = "$PackageName-bundle.zip"
    )

    Write-Host "Building $PackageName portable bundle with CRA build core..." -ForegroundColor Cyan
    Invoke-CmxPoetryBootstrap -ProjectDirectory $ProjectDirectory

    New-CmxRemoteAccessWheelBundle `
        -ProjectDirectory $ProjectDirectory `
        -PackageName $PackageName `
        -ExtraRepositories $ExtraRepositories `
        -OutputDirectoryName $OutputDirectoryName

    $bundleDir = Join-Path $ProjectDirectory $OutputDirectoryName
    $zipPath = Join-Path (Join-Path $ProjectDirectory 'dist') $ZipFileName
    if (-not (Test-Path $bundleDir)) {
        throw "Bundle directory was not created: $bundleDir"
    }

    Compress-CmxArchiveRobust -SourcePath $bundleDir -DestinationPath $zipPath

    Write-Host "Build complete." -ForegroundColor Green
    Write-Host "Folder to inspect: $OutputDirectoryName"
    Write-Host "Zip to copy: dist\\$ZipFileName"
}
