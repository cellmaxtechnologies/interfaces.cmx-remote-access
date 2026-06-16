# Standardize a Windows station for Cellmax deployment.
#
# Run in an elevated PowerShell console on the station itself.
# The script prepares the Cellmax account, common deployment folders/shares,
# optional SSH readiness, and then renames the computer. A restart is required
# before the new computer name is active.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ComputerName,

    [Parameter(Mandatory = $false)]
    [string] $UserName = "Cellmax",

    [Parameter(Mandatory = $true)]
    [securestring] $Password,

    [Parameter(Mandatory = $false)]
    [string] $ApplicationsRoot = "C:\Cellmax\Applications",

    [Parameter(Mandatory = $false)]
    [string] $DesktopRoot = "C:\Users\Public\Desktop",

    [switch] $InstallOpenSsh,

    [switch] $Restart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Enable-FirewallPort {
    param(
        [string] $DisplayName,
        [string] $Protocol,
        [int] $Port
    )

    $rule = Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction SilentlyContinue
    if ($rule) {
        Set-NetFirewallRule -DisplayName $DisplayName -Enabled True -Profile Any
    } else {
        New-NetFirewallRule `
            -DisplayName $DisplayName `
            -Direction Inbound `
            -Action Allow `
            -Protocol $Protocol `
            -LocalPort $Port `
            -Profile Any | Out-Null
    }
}

if (-not (Test-IsAdministrator)) {
    throw "Run this script from an elevated PowerShell console."
}

if ($ComputerName.Length -gt 15) {
    throw "Windows computer name '$ComputerName' is longer than the 15-character NetBIOS limit."
}

$ip = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -like "10.0.245.*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1

if ($ip) {
    Set-NetConnectionProfile -InterfaceIndex $ip.InterfaceIndex -NetworkCategory Private
}

if (Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue) {
    Set-LocalUser -Name $UserName -Password $Password -PasswordNeverExpires $true
    Enable-LocalUser -Name $UserName
} else {
    New-LocalUser `
        -Name $UserName `
        -Password $Password `
        -FullName $UserName `
        -PasswordNeverExpires | Out-Null
}

$adminGroup = (Get-LocalGroup | Where-Object { $_.SID -like "S-1-5-32-544" } | Select-Object -First 1).Name
if (-not (Get-LocalGroupMember -Group $adminGroup | Where-Object { $_.Name -match "\\$([regex]::Escape($UserName))$" })) {
    Add-LocalGroupMember -Group $adminGroup -Member $UserName
}

Start-Service LanmanServer
Set-Service LanmanServer -StartupType Automatic
Enable-FirewallPort -DisplayName "Cellmax SMB TCP 445" -Protocol TCP -Port 445

if ($InstallOpenSsh) {
    $capability = Get-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
    if ($capability.State -ne "Installed") {
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
    }
}

if (Get-Service sshd -ErrorAction SilentlyContinue) {
    Start-Service sshd
    Set-Service sshd -StartupType Automatic
    Enable-FirewallPort -DisplayName "Cellmax SSH TCP 22" -Protocol TCP -Port 22
}

New-Item -ItemType Directory -Force -Path $ApplicationsRoot | Out-Null
New-Item -ItemType Directory -Force -Path $DesktopRoot | Out-Null

Get-SmbShare -Name "CellmaxApplications" -ErrorAction SilentlyContinue | Remove-SmbShare -Force
Get-SmbShare -Name "CellmaxDesktop" -ErrorAction SilentlyContinue | Remove-SmbShare -Force
New-SmbShare -Name "CellmaxApplications" -Path $ApplicationsRoot -FullAccess $UserName | Out-Null
New-SmbShare -Name "CellmaxDesktop" -Path $DesktopRoot -FullAccess $UserName | Out-Null

if ($env:COMPUTERNAME -ne $ComputerName) {
    Rename-Computer -NewName $ComputerName -Force
}

Write-Host "Station prepared:" -ForegroundColor Green
Write-Host "  Computer name: $ComputerName"
Write-Host "  Station ID:    $ComputerName"
Write-Host "  User:          $UserName"
Write-Host "  Applications:  $ApplicationsRoot"
Write-Host "  Desktop:       $DesktopRoot"
Write-Host "  SMB shares:    CellmaxApplications, CellmaxDesktop"
Write-Host "Restart required before the new computer name is active." -ForegroundColor Yellow

if ($Restart) {
    Restart-Computer -Force
}
