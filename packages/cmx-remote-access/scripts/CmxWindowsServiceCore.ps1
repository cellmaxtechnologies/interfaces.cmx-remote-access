<#
.SYNOPSIS
    Shared Windows service helpers for CRA packages.
#>

$script:CmxWindowsServiceCoreVersion = '1.1.0'

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
            Reset-CmxNssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Key "AppParameters"
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

function Wait-CmxHttpHealth {
    param(
        [Parameter(Mandatory)][string]$Url,
        [int]$Attempts = 30,
        [int]$DelaySeconds = 2
    )
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 10
            if ($response.status -eq "ok") {
                return $true
            }
        } catch {
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
