<#
.SYNOPSIS
    Shared Windows service helpers for CRA packages.
#>

$script:CmxWindowsServiceCoreVersion = '1.3.1'

function Write-CmxServiceStep {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host ""
    Write-Host "== $Message =="
}

function Assert-CmxAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "This script must be run from an elevated PowerShell window (Run as Administrator)."
    }
}

function Find-CmxNssm {
    $vendored = Join-Path $PSScriptRoot '..\tools\nssm.exe'
    if (Test-Path $vendored) { return (Resolve-Path $vendored).Path }
    if ($env:NSSM_EXE -and (Test-Path $env:NSSM_EXE)) { return $env:NSSM_EXE }
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "C:\nssm\win64\nssm.exe",
        "C:\nssm\nssm.exe",
        "C:\Program Files\nssm\nssm.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Resolve-CmxNssmPath {
    param(
        [string]$ExplicitPath = "",
        [string]$EnvPath = "",
        [System.Collections.IDictionary]$EnvValues,
        [string[]]$BundleRoots = @()
    )
    if ($ExplicitPath) {
        if (-not (Test-Path $ExplicitPath)) {
            throw "NSSM was not found at: $ExplicitPath"
        }
        return (Resolve-Path $ExplicitPath).Path
    }
    foreach ($root in $BundleRoots) {
        if (-not $root) { continue }
        $candidates = @(
            (Join-Path $root 'tools\nssm.exe'),
            (Join-Path $root 'scripts\tools\nssm.exe'),
            (Join-Path $root 'nssm.exe')
        )
        foreach ($candidate in $candidates) {
            if (Test-Path $candidate) {
                return (Resolve-Path $candidate).Path
            }
        }
    }
    $found = Find-CmxNssm
    if ($found) {
        return $found
    }
    if ($EnvValues -and $EnvValues.Contains("NSSM_PATH")) {
        $nssmPath = [string]$EnvValues["NSSM_PATH"]
        if (-not $nssmPath) {
            throw "NSSM_PATH is missing in $EnvPath."
        }
        if (-not (Test-Path $nssmPath)) {
            throw "NSSM was not found at NSSM_PATH: $nssmPath"
        }
        return (Resolve-Path $nssmPath).Path
    }
    throw "NSSM not found. Install from https://nssm.cc/download or set NSSM_EXE / NSSM_PATH."
}

function Test-CmxServiceExists {
    param([Parameter(Mandatory)][string]$Name)
    return [bool](Get-Service -Name $Name -ErrorAction SilentlyContinue)
}

function Set-CmxNssmValue {
    param(
        [Parameter(Mandatory)][string]$NssmExe,
        [Parameter(Mandatory)][string]$ServiceName,
        [Parameter(Mandatory)][string]$Key,
        [AllowEmptyString()][string]$Value
    )
    & $NssmExe set $ServiceName $Key $Value | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed setting NSSM value '$Key'."
    }
}

function Reset-CmxNssmValue {
    param(
        [Parameter(Mandatory)][string]$NssmExe,
        [Parameter(Mandatory)][string]$ServiceName,
        [Parameter(Mandatory)][string]$Key
    )
    & $NssmExe reset $ServiceName $Key | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed resetting NSSM value '$Key'."
    }
}

function Clear-CmxNssmValue {
    param(
        [Parameter(Mandatory)][string]$NssmExe,
        [Parameter(Mandatory)][string]$ServiceName,
        [Parameter(Mandatory)][string]$Key
    )
    & $NssmExe set $ServiceName $Key "" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed clearing NSSM value '$Key'."
    }
}

function Install-OrUpdate-CmxNssmService {
    param(
        [Parameter(Mandatory)][string]$NssmExe,
        [Parameter(Mandatory)][string]$ServiceName,
        [Parameter(Mandatory)][string]$ApplicationPath,
        [AllowEmptyString()][string]$ApplicationArgs = "",
        [Parameter(Mandatory)][string]$AppDirectory,
        [Parameter(Mandatory)][string]$DisplayName,
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][string]$LogsDirectory,
        [hashtable]$Environment = @{},
        [string]$ServiceUsername = "",
        [string]$ServicePassword = ""
    )
    New-Item -ItemType Directory -Path $LogsDirectory -Force | Out-Null
    $stdoutPath = Join-Path $LogsDirectory "stdout.log"
    $stderrPath = Join-Path $LogsDirectory "stderr.log"

    if (-not (Test-CmxServiceExists -Name $ServiceName)) {
        Write-CmxServiceStep "Creating Windows service"
        if ([string]::IsNullOrWhiteSpace($ApplicationArgs)) {
            $installOutput = & $NssmExe install $ServiceName $ApplicationPath 2>&1
        } else {
            $installOutput = & $NssmExe install $ServiceName $ApplicationPath $ApplicationArgs 2>&1
        }
        if ($LASTEXITCODE -ne 0) {
            $details = (($installOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine).Trim()
            if ($details) {
                throw "Failed to create service '$ServiceName'. NSSM said: $details"
            }
            throw "Failed to create service '$ServiceName'."
        }
    } else {
        Write-CmxServiceStep "Updating existing Windows service"
        try {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        } catch {
        }
        & $NssmExe set $ServiceName Application $ApplicationPath | Out-Null
        if ([string]::IsNullOrWhiteSpace($ApplicationArgs)) {
            Clear-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "AppParameters"
        } else {
            & $NssmExe set $ServiceName AppParameters $ApplicationArgs | Out-Null
        }
    }

    Set-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "AppDirectory" -Value $AppDirectory
    Set-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "DisplayName" -Value $DisplayName
    Set-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "Description" -Value $Description
    Set-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "Start" -Value "SERVICE_AUTO_START"
    Set-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "AppStdout" -Value $stdoutPath
    Set-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "AppStderr" -Value $stderrPath
    Set-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "AppRotateFiles" -Value "1"
    Set-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "AppRotateOnline" -Value "1"
    Set-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "AppRotateBytes" -Value "10485760"
    & $NssmExe set $ServiceName AppExit Default Restart | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed setting NSSM AppExit policy."
    }

    if ($Environment.Count -gt 0) {
        $envBlock = (
            $Environment.GetEnumerator() |
            Where-Object { $_.Value -ne $null -and [string]$_.Value -ne "" } |
            Sort-Object Name |
            ForEach-Object { "$($_.Name)=$($_.Value)" }
        ) -join "`n"
        if ($envBlock) {
            Set-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "AppEnvironmentExtra" -Value $envBlock
        }
    }

    if ($ServiceUsername) {
        if (-not $ServicePassword) {
            throw "Service username was set but password is empty."
        }
        Write-CmxServiceStep "Configuring service account"
        & $NssmExe set $ServiceName ObjectName $ServiceUsername $ServicePassword | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to configure service account '$ServiceUsername'."
        }
    }
}

function Start-CmxService {
    param(
        [Parameter(Mandatory)][string]$ServiceName,
        [string]$NssmExe = ""
    )
    Write-CmxServiceStep "Starting service"
    try {
        Start-Service -Name $ServiceName -ErrorAction Stop
    } catch {
        if ($NssmExe) {
            & $NssmExe start $ServiceName | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw
            }
        } else {
            throw
        }
    }
}

function Ensure-CmxFirewallRule {
    param(
        [Parameter(Mandatory)][string]$DisplayName,
        [Parameter(Mandatory)][int]$Port
    )
    Write-CmxServiceStep "Ensuring Windows Firewall rule"
    $existing = Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule -DisplayName $DisplayName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
    }
}

function Test-CmxCommandExists {
    param([Parameter(Mandatory)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-CmxLoggedInWindowsUsername {
    try {
        $whoami = (& whoami 2>$null).Trim()
        if ($whoami) {
            return $whoami
        }
    } catch {
    }
    return ""
}

function Get-CmxPythonExecutable {
    param(
        [version]$MinimumVersion = '3.10',
        [version]$MaximumExclusiveVersion = '3.14',
        [string]$PreferredVenvDir = ''
    )

    $candidates = New-Object System.Collections.Generic.List[string]
    if ($PreferredVenvDir) {
        $venvPython = Join-Path $PreferredVenvDir 'Scripts\python.exe'
        if (Test-Path $venvPython) {
            $candidates.Add($venvPython)
        }
    }

    if (Test-CmxCommandExists 'py') {
        foreach ($candidateVersion in @('3.12', '3.11', '3.10', '3.9')) {
            try {
                $exe = (& py "-$candidateVersion" -c "import sys; print(sys.executable)" 2>$null).Trim()
                if ($exe) { $candidates.Add($exe) }
            } catch {
            }
        }
    }

    foreach ($cmd in @('python', 'python3')) {
        if (Test-CmxCommandExists $cmd) {
            try {
                $exe = (& $cmd -c "import sys; print(sys.executable)" 2>$null).Trim()
                if ($exe) { $candidates.Add($exe) }
            } catch {
            }
        }
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        try {
            $versionText = (& $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null).Trim()
            if (-not $versionText) { continue }
            $version = [version]$versionText
            if ($version -ge $MinimumVersion -and $version -lt $MaximumExclusiveVersion) {
                return $candidate
            }
        } catch {
        }
    }

    return $null
}

function Install-CmxPythonWithWinget {
    param([string]$PackageId = 'Python.Python.3.11')
    if (-not (Test-CmxCommandExists 'winget')) {
        throw "Python was not found and winget is not available to install it automatically."
    }
    Write-CmxServiceStep "Installing Python with winget"
    & winget install --id $PackageId --exact --silent --accept-package-agreements --accept-source-agreements
}

function Ensure-CmxVenv {
    param(
        [Parameter(Mandatory)][string]$PythonExe,
        [Parameter(Mandatory)][string]$VenvDir
    )
    if (-not (Test-Path (Join-Path $VenvDir 'Scripts\python.exe'))) {
        Write-CmxServiceStep "Creating service virtual environment"
        & $PythonExe -m venv $VenvDir
    }
    return (Join-Path $VenvDir 'Scripts\python.exe')
}

function Invoke-CmxPython {
    param(
        [Parameter(Mandatory)][string]$PythonExe,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )
    Push-Location $WorkingDirectory
    try {
        & $PythonExe @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Python command failed: $PythonExe $($Arguments -join ' ')"
        }
    } finally {
        Pop-Location
    }
}

function Install-CmxEditablePythonPackage {
    param(
        [Parameter(Mandatory)][string]$PythonExe,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [switch]$RunPywin32PostInstall
    )
    Write-CmxServiceStep "Installing Python dependencies"
    Invoke-CmxPython -PythonExe $PythonExe -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel') -WorkingDirectory $WorkingDirectory
    Invoke-CmxPython -PythonExe $PythonExe -Arguments @('-m', 'pip', 'install', '-e', '.') -WorkingDirectory $WorkingDirectory

    if ($RunPywin32PostInstall) {
        $postInstall = Join-Path (Split-Path $PythonExe -Parent) 'pywin32_postinstall.py'
        if (Test-Path $postInstall) {
            Write-CmxServiceStep "Running pywin32 post-install"
            Invoke-CmxPython -PythonExe $PythonExe -Arguments @($postInstall, '-install') -WorkingDirectory $WorkingDirectory
        }
    }
}

function Wait-CmxHttpHealth {
    param(
        [Parameter(Mandatory)][string]$Url,
        [int]$Attempts = 30,
        [int]$DelaySeconds = 2,
        [int]$TimeoutSeconds = 3
    )
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            Write-Host "Health check attempt $i/$Attempts`: $Url" -ForegroundColor DarkGray
            $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec $TimeoutSeconds
            if ($response.status -eq "ok") {
                return $true
            }
        } catch {
            Write-Host "  Not ready: $($_.Exception.Message)" -ForegroundColor DarkGray
        }
        Start-Sleep -Seconds $DelaySeconds
    }
    return $false
}

function Remove-CmxNssmService {
    param(
        [Parameter(Mandatory)][string]$NssmExe,
        [Parameter(Mandatory)][string]$ServiceName
    )
    Write-Host "Stopping service '$ServiceName'..."
    & $NssmExe stop $ServiceName | Out-Null

    Write-Host "Removing service '$ServiceName'..."
    & $NssmExe remove $ServiceName confirm

    Write-Host "Service '$ServiceName' removed."
}

function Remove-CmxFirewallRules {
    param([Parameter(Mandatory)][string]$DisplayNamePattern)
    $rules = @(Get-NetFirewallRule -DisplayName $DisplayNamePattern -ErrorAction SilentlyContinue)
    if ($rules.Count -eq 0) {
        return
    }
    Write-CmxServiceStep "Removing Windows Firewall rule"
    $rules | Remove-NetFirewallRule
}

function Uninstall-CmxServicePackage {
    param(
        [Parameter(Mandatory)][string]$ServiceName,
        [Parameter(Mandatory)][string]$InstallRoot,
        [Parameter(Mandatory)][string]$ConfigDir,
        [string]$FirewallDisplayNamePattern = "",
        [switch]$RemoveInstallRoot,
        [switch]$RemoveConfig
    )

    Assert-CmxAdmin
    $nssm = Resolve-CmxNssmPath -BundleRoots @($PSScriptRoot, (Split-Path -Parent $PSScriptRoot), $InstallRoot)

    if (Test-CmxServiceExists -Name $ServiceName) {
        Write-CmxServiceStep "Removing Windows service"
        Remove-CmxNssmService -NssmExe $nssm -ServiceName $ServiceName
    } else {
        Write-Host "Service '$ServiceName' is not installed."
    }

    $rulePattern = if ($FirewallDisplayNamePattern) { $FirewallDisplayNamePattern } else { "$ServiceName*" }
    Remove-CmxFirewallRules -DisplayNamePattern $rulePattern

    if ($RemoveInstallRoot -and (Test-Path $InstallRoot)) {
        Write-CmxServiceStep "Removing installed application files"
        Remove-Item -LiteralPath $InstallRoot -Recurse -Force
    } elseif (Test-Path $InstallRoot) {
        Write-Host "Kept installed application files in: $InstallRoot"
    }

    if ($RemoveConfig -and (Test-Path $ConfigDir)) {
        Write-CmxServiceStep "Removing configuration"
        Remove-Item -LiteralPath $ConfigDir -Recurse -Force
    } elseif (Test-Path $ConfigDir) {
        Write-Host "Kept configuration in: $ConfigDir"
        Write-Host "Run with -RemoveConfig to delete saved tokens/configuration."
    }

    Write-Host ""
    Write-Host "Uninstall complete for '$ServiceName'."
}

function Install-CmxPythonModuleNssmService {
    <#
    .SYNOPSIS
        Resolve Python/NSSM and register a Python module as a Windows service.
    #>
    param(
        [Parameter(Mandatory)][string]$ScriptDirectory,
        [Parameter(Mandatory)][string]$ServiceName,
        [Parameter(Mandatory)][string]$ModuleName,
        [Parameter(Mandatory)][string]$DisplayName,
        [Parameter(Mandatory)][string]$Description,
        [string]$PythonExe,
        [string]$AppDirectory,
        [switch]$RequireServiceAccount,
        [string]$ServiceUsername = "",
        [string]$ServicePassword = ""
    )

    $nssm = Resolve-CmxNssmPath -BundleRoots @($ScriptDirectory)

    try {
        Assert-CmxAdmin
    } catch {
        Write-Warning "NSSM service install usually requires Administrator. If this fails, re-run elevated."
    }

    $appDir = if ($AppDirectory) { $AppDirectory } else { $ScriptDirectory }

    if ($PythonExe) {
        $py = $PythonExe
        if (-not (Test-Path $py)) {
            throw "Python not found: $py"
        }
    }
    else {
        Push-Location $ScriptDirectory
        try {
            $py = poetry run python -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $py) {
                throw "Could not resolve Poetry Python. Run install.ps1 first, or pass -PythonExe and -AppDirectory for a portable install."
            }
            $py = $py.Trim()
        } finally {
            Pop-Location
        }
    }

    if ($RequireServiceAccount) {
        Write-CmxServiceStep "Configuring service account"
        $defaultServiceUsername = if ($ServiceUsername) { $ServiceUsername } else { Get-CmxLoggedInWindowsUsername }
        $ServiceUsername = Prompt-CmxValue -Label "Windows service username" -CurrentValue $defaultServiceUsername -Required
        $ServicePassword = Prompt-CmxValue -Label "Windows service password" -Required -Secret
    }

    $logs = Join-Path $appDir 'logs'
    Install-OrUpdate-CmxNssmService `
        -NssmExe $nssm `
        -ServiceName $ServiceName `
        -ApplicationPath $py `
        -ApplicationArgs "-m $ModuleName" `
        -AppDirectory $appDir `
        -DisplayName $DisplayName `
        -Description $Description `
        -LogsDirectory $logs `
        -ServiceUsername $ServiceUsername `
        -ServicePassword $ServicePassword

    Write-Host "[OK] Service installed. Starting..." -ForegroundColor Green
    Start-CmxService -ServiceName $ServiceName -NssmExe $nssm
}
