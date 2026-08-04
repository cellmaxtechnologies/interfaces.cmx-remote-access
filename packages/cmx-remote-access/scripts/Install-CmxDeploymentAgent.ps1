[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DeploymentPrincipal,
    [string]$AgentRoot = 'C:\ProgramData\CellMax\deployment-agent',
    [string]$TransferRoot = 'C:\Cellmax\Deploy',
    [string]$ShareName = 'CellmaxDeploy$',
    [string]$TaskName = 'CellMax Deployment Agent',
    [string]$NssmExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this bootstrap once from an elevated PowerShell console.' }
try {
    $deploymentSid = ([Security.Principal.NTAccount]$DeploymentPrincipal).Translate([Security.Principal.SecurityIdentifier]).Value
} catch {
    throw "DeploymentPrincipal '$DeploymentPrincipal' could not be resolved to a Windows account."
}
if ($deploymentSid -in @('S-1-1-0','S-1-5-7','S-1-5-11','S-1-5-32-545','S-1-5-32-546')) {
    throw 'DeploymentPrincipal must be a dedicated account, not a broad built-in principal.'
}
if (-not $NssmExe) {
    $command = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($command) { $NssmExe = $command.Source }
}
if (-not $NssmExe) {
    $nssmCandidates = @(@(
        foreach ($service in Get-CimInstance Win32_Service) {
            $commandLine = [string]$service.PathName
            $candidate = if ($commandLine -match '^\s*"([^"]+)"') {
                $Matches[1]
            } elseif ($commandLine -match '^\s*([^\s]+)') {
                $Matches[1]
            }
            if ($candidate -and [IO.Path]::GetFileName($candidate) -ieq 'nssm.exe' -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                [IO.Path]::GetFullPath($candidate)
            }
        }
    ) | Sort-Object -Unique)
    if ($nssmCandidates.Count -eq 1) { $NssmExe = $nssmCandidates[0] }
}
if (-not $NssmExe -or -not (Test-Path -LiteralPath $NssmExe -PathType Leaf)) { throw 'Pass -NssmExe with the station NSSM executable path.' }

function Set-CmxDeploymentDirectoryDacl {
    param(
        [Parameter(Mandatory)][string]$Path,
        [string]$RemoteAccount = '',
        [System.Security.AccessControl.FileSystemRights]$RemoteRights = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
        [System.Security.AccessControl.InheritanceFlags]$RemoteInheritance = [System.Security.AccessControl.InheritanceFlags]::None
    )
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($account in @('SYSTEM','BUILTIN\Administrators')) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $account, [System.Security.AccessControl.FileSystemRights]::FullControl, $inherit,
            [System.Security.AccessControl.PropagationFlags]::None, [System.Security.AccessControl.AccessControlType]::Allow
        )
        [void]$acl.AddAccessRule($rule)
    }
    if ($RemoteAccount) {
        $remoteRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $RemoteAccount, $RemoteRights, $RemoteInheritance,
            [System.Security.AccessControl.PropagationFlags]::None, [System.Security.AccessControl.AccessControlType]::Allow
        )
        [void]$acl.AddAccessRule($remoteRule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Set-CmxDeploymentFileDacl {
    param([Parameter(Mandatory)][string]$Path)
    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($account in @('SYSTEM','BUILTIN\Administrators')) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $account, [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        [void]$acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Reset-CmxDeploymentProtectedTreeDacl {
    param([Parameter(Mandatory)][string]$Path)
    Set-CmxDeploymentDirectoryDacl -Path $Path
    foreach ($item in @(Get-ChildItem -LiteralPath $Path -Recurse -Force)) {
        if ($item.PSIsContainer) {
            Set-CmxDeploymentDirectoryDacl -Path $item.FullName
        } else {
            Set-CmxDeploymentFileDacl -Path $item.FullName
        }
    }
}

$scripts = Join-Path $AgentRoot 'scripts'
$queue = Join-Path $AgentRoot 'queue'
$releases = Join-Path $AgentRoot 'releases'
$locks = Join-Path $AgentRoot 'locks'
$inbox = Join-Path $TransferRoot 'inbox'
$results = Join-Path $TransferRoot 'results'
foreach ($path in @($AgentRoot,$scripts,$releases,$locks,$queue,$TransferRoot,$inbox,$results)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'CmxDeploymentAgentCore.ps1') -Destination $scripts -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Run-CmxDeploymentAgent.ps1') -Destination $scripts -Force

# Replace protected code/state DACLs recursively so stale file-level ACEs cannot survive bootstrap.
Set-CmxDeploymentDirectoryDacl -Path $AgentRoot
foreach ($protectedPath in @($scripts,$locks,$queue)) { Reset-CmxDeploymentProtectedTreeDacl -Path $protectedPath }
# Release children retain their exact service-account read/execute ACEs; the root remains Admin/SYSTEM-only.
Set-CmxDeploymentDirectoryDacl -Path $releases
Set-CmxDeploymentDirectoryDacl -Path $TransferRoot -RemoteAccount $DeploymentPrincipal
$childInheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
Set-CmxDeploymentDirectoryDacl -Path $inbox -RemoteAccount $DeploymentPrincipal -RemoteRights Modify -RemoteInheritance $childInheritance
Set-CmxDeploymentDirectoryDacl -Path $results -RemoteAccount $DeploymentPrincipal -RemoteRights ReadAndExecute -RemoteInheritance $childInheritance

$allowlistPath = Join-Path $AgentRoot 'allowlist.json'
$allowlist = [ordered]@{
    schemaVersion = 1
    profiles = @(
        [ordered]@{
            packageName = 'active-cell-pp-api'; serviceName = 'CellMaxActiveCellPpApi'
            healthUrl = 'http://127.0.0.1:8765/health'; serviceId = 'active-cell-pp-api'
            executablePath = 'active-cell-pp-api-server.exe'
        },
        [ordered]@{
            packageName = 'active-cell-ac-api'; serviceName = 'CellMaxActiveCellAcApi'
            healthUrl = 'http://127.0.0.1:8766/health'; serviceId = 'active-cell-ac-api'
            executablePath = 'venv/Scripts/python.exe'
        }
    )
}
$allowlistTemp = "$allowlistPath.$PID.tmp"
$allowlist | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $allowlistTemp -Encoding UTF8
Move-Item -LiteralPath $allowlistTemp -Destination $allowlistPath -Force

$existing = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue
if ($existing -and [IO.Path]::GetFullPath($existing.Path) -ne [IO.Path]::GetFullPath($TransferRoot)) { throw "SMB share '$ShareName' already points elsewhere." }
if ($existing) { Remove-SmbShare -Name $ShareName -Force }
New-SmbShare -Name $ShareName -Path $TransferRoot -FullAccess $DeploymentPrincipal -FolderEnumerationMode AccessBased | Out-Null

$runner = Join-Path $scripts 'Run-CmxDeploymentAgent.ps1'
$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -AgentRoot `"$AgentRoot`" -TransferRoot `"$TransferRoot`" -NssmExe `"$NssmExe`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$taskPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $taskPrincipal -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host 'Cellmax deployment agent installed.' -ForegroundColor Green
Write-Host "  SMB path: \\$env:COMPUTERNAME\$ShareName"
Write-Host "  Task:     $TaskName (LocalSystem, starts at boot)"
Write-Host '  Secrets:  none accepted or copied; service identity and ProgramData configuration remain unchanged.'
