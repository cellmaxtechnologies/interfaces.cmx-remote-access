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

$script:CmxInstallCoreVersion = '1.3.0'
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

    Write-CmxBanner "poetry update (git deps)"
    poetry update @gitDependencies
    if ($LASTEXITCODE -ne 0) {
        throw "poetry update failed for git dependencies: $($gitDependencies -join ', ')"
    }
}

function Invoke-CmxPoetryInstall {
    param(
        [Parameter(Mandatory)][string]$ProjectDirectory
    )
    Push-Location $ProjectDirectory
    try {
        Invoke-CmxPoetryRefreshGitDependencies -ProjectDirectory $ProjectDirectory
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

function Read-CmxEnvFile {
    param([Parameter(Mandatory)][string]$Path)
    $values = [ordered]@{}
    if (-not (Test-Path $Path)) {
        return $values
    }
    Get-Content -Path $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") {
            return
        }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = if ($parts.Length -gt 1) { $parts[1].Trim() } else { "" }
        if ($value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Trim('"')
        }
        if ($key) {
            $values[$key] = $value
        }
    }
    return $values
}

function Prompt-CmxValue {
    param(
        [Parameter(Mandatory)][string]$Label,
        [string]$CurrentValue = "",
        [switch]$Required,
        [switch]$Secret
    )
    while ($true) {
        $prompt = if ($CurrentValue) { "$Label [$CurrentValue]" } else { $Label }
        if ($Secret) {
            $secure = Read-Host -Prompt $prompt -AsSecureString
            $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
            try {
                $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
            } finally {
                if ($bstr -ne [IntPtr]::Zero) {
                    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
                }
            }
        } else {
            $value = Read-Host -Prompt $prompt
        }

        if (-not $value -and $CurrentValue) {
            $value = $CurrentValue
        }

        if (-not $Required -or $value) {
            return $value
        }

        Write-Host "Value required."
    }
}

function Get-CmxServerIPv4 {
    $ipConfigs = @(Get-NetIPConfiguration -ErrorAction SilentlyContinue)
    $adapters = @(Get-NetAdapter -ErrorAction SilentlyContinue)
    $virtualAliasPattern = "Loopback|vEthernet|Default Switch|VMware|VirtualBox|Hyper-V|Bluetooth|Tailscale|ZeroTier"

    $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -and
            $_.IPAddress -ne "127.0.0.1" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown" -and
            $_.InterfaceAlias -notmatch $virtualAliasPattern
        } |
        ForEach-Object {
            $address = $_
            $config = $ipConfigs | Where-Object { $_.InterfaceIndex -eq $address.InterfaceIndex } | Select-Object -First 1
            $adapter = $adapters | Where-Object { $_.InterfaceIndex -eq $address.InterfaceIndex } | Select-Object -First 1
            [pscustomobject]@{
                IPAddress       = $address.IPAddress
                InterfaceAlias  = $address.InterfaceAlias
                InterfaceMetric = $address.InterfaceMetric
                SkipAsSource    = $address.SkipAsSource
                HasGateway      = [bool]($config -and $config.IPv4DefaultGateway)
                AdapterUp       = [bool]($adapter -and $adapter.Status -eq "Up")
                PhysicalAdapter = [bool]($adapter -and $adapter.HardwareInterface)
            }
        } |
        Sort-Object `
            @{ Expression = { if ($_.HasGateway) { 0 } else { 1 } } }, `
            @{ Expression = { if ($_.AdapterUp) { 0 } else { 1 } } }, `
            @{ Expression = { if ($_.PhysicalAdapter) { 0 } else { 1 } } }, `
            SkipAsSource, `
            InterfaceMetric

    $selected = $candidates | Select-Object -First 1
    if ($selected -and $selected.IPAddress) {
        return $selected.IPAddress
    }

    try {
        $fallback = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
            Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and $_.IPAddressToString -ne "127.0.0.1" } |
            Select-Object -First 1
        if ($fallback) {
            return $fallback.IPAddressToString
        }
    } catch {
    }

    throw "Could not determine a non-loopback IPv4 address for this server."
}

function Get-CmxFreeTcpPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    } finally {
        $listener.Stop()
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

function Assert-CmxEnvFileHasKeys {
    param(
        [Parameter(Mandatory)][string]$EnvPath,
        [string[]]$RequiredKeys = @(),
        [string]$ServiceLabel = 'service'
    )
    if (-not $RequiredKeys -or $RequiredKeys.Count -eq 0) {
        return
    }

    if (-not (Test-Path $EnvPath)) {
        throw "Missing .env for ${ServiceLabel}: $EnvPath. Run the installer wizard or copy .env.example to .env and fill the required values."
    }

    $values = Read-CmxEnvFile -Path $EnvPath
    $missing = @()
    foreach ($key in $RequiredKeys) {
        if (-not $values.Contains($key) -or [string]::IsNullOrWhiteSpace([string]$values[$key])) {
            $missing += $key
        }
    }

    if ($missing.Count -gt 0) {
        $joined = $missing -join ', '
        throw "Missing required .env values for ${ServiceLabel}: $joined. Update $EnvPath or rerun the installer."
    }
}

function Invoke-CmxEnvWizard {
    param(
        [Parameter(Mandatory)][string]$EnvPath,
        [switch]$SkipPrompts,
        [switch]$SkipEnvWizard,
        [Parameter(Mandatory)][scriptblock]$BuildVariables,
        [string[]]$RequiredKeys = @(),
        [string]$ServiceLabel = 'service',
        [string]$SkipPromptWarning = 'Skipping interactive .env creation (-SkipPrompts). Copy .env.example to .env and edit as needed.',
        [string]$SkipWizardMessage = 'Skipping .env wizard (-SkipEnvWizard).'
    )
    if ($SkipEnvWizard) {
        Write-Host $SkipWizardMessage -ForegroundColor DarkGray
        Assert-CmxEnvFileHasKeys -EnvPath $EnvPath -RequiredKeys $RequiredKeys -ServiceLabel $ServiceLabel
        return
    }

    if ($SkipPrompts) {
        Write-Warning $SkipPromptWarning
        Assert-CmxEnvFileHasKeys -EnvPath $EnvPath -RequiredKeys $RequiredKeys -ServiceLabel $ServiceLabel
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
        Assert-CmxEnvFileHasKeys -EnvPath $EnvPath -RequiredKeys $RequiredKeys -ServiceLabel $ServiceLabel
        return
    }

    $vars = & $BuildVariables
    Export-CmxDotEnvFile -Path $EnvPath -Variables $vars
    Assert-CmxEnvFileHasKeys -EnvPath $EnvPath -RequiredKeys $RequiredKeys -ServiceLabel $ServiceLabel
}

function Invoke-CmxPortableWheelInstall {
    <#
    .SYNOPSIS
        Install a CRA service from a portable wheel bundle into Program Files.
    #>
    param(
        [Parameter(Mandatory)][string]$BundleDirectory,
        [Parameter(Mandatory)][string]$InstallRoot,
        [Parameter(Mandatory)][string]$ConfigDir,
        [Parameter(Mandatory)][string]$ServiceLabel,
        [switch]$SkipEnvWizard,
        [switch]$SkipPrompts,
        [scriptblock]$BuildVariables
    )

    $wheelsDir = Join-Path $BundleDirectory 'wheels'
    if (-not (Test-Path $wheelsDir)) {
        throw "Missing wheels folder: $wheelsDir"
    }

    $wheels = @(Get-ChildItem -Path $wheelsDir -Filter '*.whl' -File)
    if ($wheels.Count -eq 0) {
        throw "No .whl files in $wheelsDir"
    }

    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        throw "Run elevated (Administrator) so the app can be installed under Program Files."
    }

    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd) {
        throw "Python 3.10+ must be on PATH to create the venv."
    }
    $versionText = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($versionText)) {
        throw "Could not determine Python version from PATH."
    }
    $pythonVersion = [version]$versionText
    if ($pythonVersion -lt [version]'3.10.0' -or $pythonVersion -ge [version]'3.14.0') {
        throw "Python 3.10 through 3.13 is required; found $pythonVersion."
    }

    Write-CmxBanner "Install $ServiceLabel server"
    Write-Host "Install root:  $InstallRoot" -ForegroundColor DarkGray
    Write-Host "Config (.env): $ConfigDir\.env" -ForegroundColor DarkGray

    if (-not (Test-Path $InstallRoot)) {
        New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    }

    $venv = Join-Path $InstallRoot 'venv'
    if (-not (Test-Path $venv)) {
        & python -m venv $venv
    }

    $pip = Join-Path $venv 'Scripts\pip.exe'
    $py = Join-Path $venv 'Scripts\python.exe'

    & $py -m pip install --upgrade pip | Out-Null
    foreach ($wheel in $wheels) {
        $output = & $pip install --no-index --find-links $wheelsDir --no-deps $wheel.FullName 2>&1
        if ($LASTEXITCODE -ne 0) {
            $text = ($output | Out-String)
            if ($text -match 'not a supported wheel on this platform') {
                Write-Host "Skipping incompatible wheel: $($wheel.Name)" -ForegroundColor DarkGray
                continue
            }
            Write-Host $text
            throw "pip install failed."
        }
    }

    if (-not (Test-Path $ConfigDir)) {
        New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    }
    $example = Join-Path $BundleDirectory '.env.example'
    if (Test-Path $example) {
        Copy-Item $example (Join-Path $ConfigDir '.env.example') -Force
    }

    $envPath = Join-Path $ConfigDir '.env'
    if ($BuildVariables) {
        Invoke-CmxEnvWizard `
            -EnvPath $envPath `
            -SkipPrompts:$SkipPrompts `
            -SkipEnvWizard:$SkipEnvWizard `
            -ServiceLabel $ServiceLabel `
            -BuildVariables $BuildVariables `
            -SkipPromptWarning "Skipping interactive .env creation (-SkipPrompts). Create ${envPath} manually (see .env.example)." `
            -SkipWizardMessage 'Skipping .env wizard (-SkipEnvWizard).'
    }
    elseif ($SkipEnvWizard -or $SkipPrompts) {
        Write-Host "Skipping .env wizard. Create ${envPath} manually if needed." -ForegroundColor DarkGray
    }

    return @{
        PythonExe    = $py
        InstallRoot  = $InstallRoot
        ConfigDir    = $ConfigDir
        EnvPath      = $envPath
    }
}
