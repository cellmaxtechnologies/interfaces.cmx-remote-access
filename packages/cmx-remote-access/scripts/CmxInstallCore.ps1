<#
.SYNOPSIS
    Shared prerequisites and messaging for CellMax remote-access services (cmx-remote-access).

.DESCRIPTION
    Dot-source this script from a service’s install.ps1. Provides:
    - Monorepo root discovery (for path-based Poetry deps)
    - Python / Poetry / Git checks with optional winget installs
    - Consistent warnings and prompts

    This file is part of the cmx-remote-access package so every API repo can offer the same “feel”.
#>

$script:CmxInstallCoreVersion = '1.1.0'
$script:CmxPythonArgs = @()

function Write-CmxBanner {
    param([string]$Title)
    Write-Host ''
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Find-CellMaxMonorepoRoot {
    <#
    Walk upward from $StartPath looking for interfaces/cmx-remote-access/packages/cmx-remote-access.
    Returns $null if not found (standalone copy).
    #>
    param(
        [string]$StartPath = $PSScriptRoot
    )
    $p = (Resolve-Path $StartPath).Path
    for ($i = 0; $i -le 8; $i++) {
        $candidate = Join-Path $p 'interfaces\cmx-remote-access\packages\cmx-remote-access\pyproject.toml'
        if (Test-Path $candidate) {
            return $p
        }
        $parent = Split-Path $p -Parent
        if ($parent -eq $p) { break }
        $p = $parent
    }
    return $null
}

function Test-CmxPython {
    param(
        [version]$MinimumVersion = '3.10.0',
        [switch]$AllowInstall
    )
    $candidates = @(
        @{ Exe = 'py'; Args = @('-3') },
        @{ Exe = 'py'; Args = @() },
        @{ Exe = 'python'; Args = @() },
        @{ Exe = 'python3'; Args = @() }
    )
    foreach ($c in $candidates) {
        try {
            $argList = $c.Args + @('-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])')
            $verStr = & $c.Exe @argList 2>$null
            if ($LASTEXITCODE -eq 0 -and $verStr) {
                $v = [version]($verStr.Trim() -replace '^(\d+\.\d+\.\d+).*$', '$1')
                if ($v -ge $MinimumVersion) {
                    $script:CmxPythonExe = $c.Exe
                    $script:CmxPythonArgs = $c.Args
                    $script:CmxPythonVersion = $v
                    Write-Host "[OK] Python $v ($($c.Exe) $($c.Args))" -ForegroundColor Green
                    return $true
                }
            }
        } catch { }
    }
    Write-Warning "Python $MinimumVersion+ not found in PATH (tried py, python)."
    if ($AllowInstall) {
        $r = Read-Host "Install Python 3.12 via winget? [y/N]"
        if ($r -eq 'y' -or $r -eq 'Y') {
            winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
            # Refresh PATH in this session is unreliable; user may need new terminal
            Write-Warning "Open a new PowerShell window and run this script again."
            exit 1
        }
    }
    return $false
}

function Test-CmxGit {
    param([switch]$AllowInstall)
    try {
        $v = git --version 2>$null
        if ($v) {
            Write-Host "[OK] $v" -ForegroundColor Green
            return $true
        }
    } catch { }
    Write-Warning "Git not found. Required for Poetry path dependencies from sibling repos."
    if ($AllowInstall) {
        $r = Read-Host "Install Git via winget? [y/N]"
        if ($r -eq 'y' -or $r -eq 'Y') {
            winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
            Write-Warning "Restart PowerShell and run this script again."
            exit 1
        }
    }
    return $false
}

function Test-CmxPoetry {
    param([switch]$AllowInstall)
    try {
        $v = poetry --version 2>$null
        if ($v) {
            Write-Host "[OK] $v" -ForegroundColor Green
            return $true
        }
    } catch { }
    Write-Warning "Poetry not found."
    if ($AllowInstall) {
        $r = Read-Host "Install Poetry (recommended: official installer)? [y/N]"
        if ($r -eq 'y' -or $r -eq 'Y') {
            $py = $script:CmxPythonExe
            if (-not $py) { $py = 'py' }
            $pyArgs = @()
            if ($script:CmxPythonArgs) { $pyArgs = $script:CmxPythonArgs }
            & $py @pyArgs -c "import urllib.request; urllib.request.urlretrieve('https://install.python-poetry.org', 'install-poetry.py')"
            & $py @pyArgs install-poetry.py
            Remove-Item -Force install-poetry.py -ErrorAction SilentlyContinue
            Write-Host "Add Poetry to PATH: $env:APPDATA\Python\Scripts or follow https://python-poetry.org/docs/#installation" -ForegroundColor Yellow
            Write-Warning "Close and reopen PowerShell, then run this script again."
            exit 1
        }
    }
    return $false
}

function Invoke-CmxPoetryInstall {
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory
    )
    Push-Location $ProjectDirectory
    try {
        Write-CmxBanner "poetry install"
        poetry install
        if ($LASTEXITCODE -ne 0) {
            throw "poetry install failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Write-CmxManualDependencyWarning {
    param([string[]]$Items)
    Write-CmxBanner "Manual / vendor prerequisites (cannot be installed by this script)"
    foreach ($x in $Items) {
        Write-Warning $x
    }
}

function Invoke-CmxSourceInstallBootstrap {
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory,
        [Parameter(Mandatory)][string]$Title,
        [version]$MinimumPythonVersion = '3.10.0',
        [switch]$SkipPrompts
    )
    Write-CmxBanner $Title

    $root = Find-CellMaxMonorepoRoot -StartPath $ProjectDirectory
    if (-not $root) {
        throw 'Could not locate CellMax monorepo root (missing interfaces\cmx-remote-access).'
    }
    Write-Host "Monorepo root: $root" -ForegroundColor DarkGray

    $allow = -not $SkipPrompts

    if (-not (Test-CmxPython -MinimumVersion $MinimumPythonVersion -AllowInstall:$allow)) {
        throw "Python $MinimumPythonVersion+ is required."
    }

    if (-not (Test-CmxGit -AllowInstall:$allow)) {
        Write-Warning 'Continuing without Git; poetry install may fail if dependencies need VCS.'
    }

    if (-not (Test-CmxPoetry -AllowInstall:$allow)) {
        throw 'Poetry is required. Install from https://python-poetry.org/docs/#installation'
    }

    Invoke-CmxPoetryInstall -ProjectDirectory $ProjectDirectory
    return $root
}

function Read-CmxRemoteAccessAuthConfig {
    param(
        [string]$DefaultAuthStrict = 'true'
    )
    $svc = Read-Host "SERVICE_API_TOKEN (required if AUTH_STRICT=true)"

    $adm = Read-Host "ADMIN_API_TOKEN (optional; separate elevated token)"
    $strictIn = Read-Host "AUTH_STRICT [$DefaultAuthStrict]"
    if ([string]::IsNullOrWhiteSpace($strictIn)) { $strictIn = $DefaultAuthStrict }

    if ($strictIn -eq 'true' -and [string]::IsNullOrWhiteSpace($svc)) {
        throw "SERVICE_API_TOKEN is required when AUTH_STRICT=true."
    }

    return @{
        SERVICE_API_TOKEN = $svc
        ADMIN_API_TOKEN   = $adm
        AUTH_STRICT       = $strictIn
    }
}

function Escape-CmxDotEnvValue {
    param([AllowEmptyString()][string]$Value)
    if ($null -eq $Value) { return '' }
    if ($Value -eq '') { return '' }
    # Quote if whitespace, #, =, or " appear (dotenv-friendly)
    if ($Value -notmatch '[\s#="]') {
        return $Value
    }
    $escaped = $Value.Replace('\', '\\').Replace('"', '\"')
    return "`"$escaped`""
}

function Export-CmxDotEnvFile {
    <#
    .SYNOPSIS
        Write a UTF-8 (no BOM) .env file for python-dotenv / services.
    #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][hashtable]$Variables
    )
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine('# Generated by CellMax install script (cmx-remote-access CmxInstallCore)')
    [void]$sb.AppendLine("# $(Get-Date -Format 'yyyy-MM-dd HH:mm:ssK')")
    foreach ($key in ($Variables.Keys | Sort-Object)) {
        $raw = $Variables[$key]
        if ($null -eq $raw) { $raw = '' }
        $lineVal = Escape-CmxDotEnvValue -Value ([string]$raw)
        [void]$sb.AppendLine("$key=$lineVal")
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $sb.ToString(), $utf8NoBom)
    Write-Host "[OK] Wrote $Path" -ForegroundColor Green
}

function Invoke-CmxEnvWizard {
    param(
        [Parameter(Mandatory)][string]$EnvPath,
        [switch]$SkipPrompts,
        [switch]$SkipEnvWizard,
        [Parameter(Mandatory)][scriptblock]$BuildVariables,
        [string]$SkipPromptWarning = 'Skipping interactive .env creation (-SkipPrompts). Copy .env.example to .env and edit as needed.',
        [string]$SkipWizardMessage = 'Skipping .env wizard (-SkipEnvWizard).'
    )
    if ($SkipEnvWizard) {
        Write-Host $SkipWizardMessage -ForegroundColor DarkGray
        return
    }

    if ($SkipPrompts) {
        Write-Warning $SkipPromptWarning
        return
    }

    $doWrite = $true
    if (Test-Path $EnvPath) {
        $ow = Read-Host '.env already exists. Overwrite with new values? [y/N]'
        if ($ow -ne 'y' -and $ow -ne 'Y') {
            $doWrite = $false
            Write-Host 'Keeping existing .env' -ForegroundColor DarkGray
        }
    }

    if (-not $doWrite) {
        return
    }

    $vars = & $BuildVariables
    Export-CmxDotEnvFile -Path $EnvPath -Variables $vars
}
