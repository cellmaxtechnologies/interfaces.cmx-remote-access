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

function Get-CmxProjectVersion {
    param([Parameter(Mandatory)][string]$ProjectDirectory)
    $pyproject = Join-Path $ProjectDirectory 'pyproject.toml'
    foreach ($line in Get-Content $pyproject) {
        if ($line.Trim() -match '^version\s*=\s*"([^"]+)"') {
            return $matches[1]
        }
    }
    throw "Could not read version from $pyproject"
}

function Invoke-CmxReadmeDocumentationBuild {
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory,
        [string]$OutputRelativePath = 'documentation\documentation.tex'
    )
    $craRoot = Join-Path $ProjectDirectory '..\..\interfaces\cmx-remote-access\packages\cmx-remote-access'
    $scriptPath = Join-Path $craRoot 'cmx_remote_access\docs.py'
    if (-not (Test-Path $scriptPath)) {
        throw "Missing CRA documentation generator: $scriptPath"
    }
    $outputPath = Join-Path $ProjectDirectory $OutputRelativePath
    & python $scriptPath --project-dir $ProjectDirectory --output $outputPath | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Documentation generation failed."
    }
    return $outputPath
}

function Invoke-CmxDocumentationPdfBuild {
    param([Parameter(Mandatory)][string]$TexPath)
    $pdflatex = Get-Command pdflatex -ErrorAction SilentlyContinue
    if (-not $pdflatex) {
        throw "pdflatex is required to compile API documentation PDF, but it was not found on PATH."
    }

    $texItem = Get-Item $TexPath
    $docDir = $texItem.Directory.FullName
    $texFile = $texItem.Name
    $pdfPath = Join-Path $docDir ([System.IO.Path]::GetFileNameWithoutExtension($texFile) + '.pdf')

    Push-Location $docDir
    try {
        Write-CmxBuildBanner "Compile documentation PDF"
        & $pdflatex.Source -interaction=nonstopmode -halt-on-error $texFile | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "pdflatex failed for $TexPath"
        }
        & $pdflatex.Source -interaction=nonstopmode -halt-on-error $texFile | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "pdflatex failed for $TexPath"
        }
    } finally {
        Pop-Location
    }

    if (-not (Test-Path $pdfPath)) {
        throw "pdflatex did not create expected PDF: $pdfPath"
    }

    $stem = [System.IO.Path]::GetFileNameWithoutExtension($texFile)
    foreach ($extension in @('.aux', '.log', '.out', '.toc')) {
        $sidecar = Join-Path $docDir "$stem$extension"
        if (Test-Path $sidecar) {
            Remove-Item -LiteralPath $sidecar -Force
        }
    }
    return $pdfPath
}

function Invoke-CmxDocumentationBuild {
    param([Parameter(Mandatory)][string]$ProjectDirectory)
    $texPath = Invoke-CmxReadmeDocumentationBuild -ProjectDirectory $ProjectDirectory
    $pdfPath = Invoke-CmxDocumentationPdfBuild -TexPath $texPath
    return @{
        Tex = $texPath
        Pdf = $pdfPath
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
    $previousBundleName = $env:CMX_PYINSTALLER_BUNDLE_NAME
    try {
        $env:CMX_PYINSTALLER_BUNDLE_NAME = $BundleDirectoryName
        poetry run python -m PyInstaller --clean --noconfirm $SpecPath
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE"
        }
    } finally {
        if ($null -eq $previousBundleName) {
            Remove-Item Env:\CMX_PYINSTALLER_BUNDLE_NAME -ErrorAction SilentlyContinue
        } else {
            $env:CMX_PYINSTALLER_BUNDLE_NAME = $previousBundleName
        }
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
        Build a standard CRA copy-only server bundle for a service package.
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

    $documentation = Invoke-CmxDocumentationBuild -ProjectDirectory $ProjectDirectory

    $bundleFiles = @(
        @{ Source = (Join-Path $ProjectDirectory 'install-service.ps1'); Destination = 'install-service.ps1' },
        @{ Source = (Join-Path $ProjectDirectory '.env.example'); Destination = '.env.example' },
        @{ Source = $documentation.Pdf; Destination = 'documentation\documentation.pdf' },
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
        Bootstrap Poetry, build a standard CRA server wheel bundle, and zip it.
    #>
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory,
        [Parameter(Mandatory)][string]$PackageName,
        [array]$ExtraRepositories = @(),
        [string]$OutputDirectoryName = 'dist-bundle',
        [string]$ZipFileName = ""
    )

    $version = Get-CmxProjectVersion -ProjectDirectory $ProjectDirectory
    if (-not $ZipFileName) {
        $ZipFileName = "$PackageName-$version-bundle.zip"
    }

    Write-Host "Building $PackageName server bundle with CRA build core..." -ForegroundColor Cyan
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

function Invoke-CmxRemoteAccessPyInstallerBundleBuild {
    <#
    .SYNOPSIS
        Build a PyInstaller service bundle with the standard CRA install/service scripts included.
    #>
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory,
        [Parameter(Mandatory)][string]$SpecPath,
        [Parameter(Mandatory)][string]$BundleDirectoryName,
        [Parameter(Mandatory)][string]$ZipPath,
        [array]$AdditionalBundleFiles = @(),
        [switch]$KeepOnlyZipInBuildDirectory
    )

    $craRoot = Join-Path $ProjectDirectory '..\..\interfaces\cmx-remote-access\packages\cmx-remote-access'
    if (-not (Test-Path $craRoot)) {
        throw "Missing CRA package root: $craRoot"
    }

    $documentation = Invoke-CmxDocumentationBuild -ProjectDirectory $ProjectDirectory

    $bundleFiles = @()
    foreach ($file in $AdditionalBundleFiles) {
        $bundleFiles += $file
    }
    $bundleFiles += @(
        @{ Source = $documentation.Pdf; Destination = 'documentation\documentation.pdf' },
        @{ Source = (Join-Path $craRoot 'scripts\CmxInstallCore.ps1'); Destination = 'scripts\CmxInstallCore.ps1' },
        @{ Source = (Join-Path $craRoot 'scripts\CmxWindowsServiceCore.ps1'); Destination = 'scripts\CmxWindowsServiceCore.ps1' }
    )
    $nssmSource = Get-CmxOptionalNssmSource
    if ($nssmSource) {
        $bundleFiles += @{ Source = $nssmSource; Destination = 'tools\nssm.exe' }
    }

    Invoke-CmxPyInstallerBundleBuild `
        -ProjectDirectory $ProjectDirectory `
        -SpecPath $SpecPath `
        -BundleDirectoryName $BundleDirectoryName `
        -ZipPath $ZipPath `
        -BundleFiles $bundleFiles

    if ($KeepOnlyZipInBuildDirectory) {
        $buildDir = Split-Path -Parent $ZipPath
        $zipFullPath = (Get-Item $ZipPath).FullName
        Get-ChildItem $buildDir -Force | Where-Object { $_.FullName -ne $zipFullPath } | Remove-Item -Recurse -Force
    }
}
