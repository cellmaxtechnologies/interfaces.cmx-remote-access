$ErrorActionPreference = "Continue"

Write-Host "=== .NET Framework 4.x Release Key ==="
try {
    $netKey = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" -Name Release -ErrorAction Stop
    $release = $netKey.Release
    Write-Host "Release key: $release"
    if ($release -ge 528040) {
        Write-Host ".NET Framework 4.8 is installed."
    } elseif ($release -ge 461808) {
        Write-Host ".NET Framework 4.7.2 is installed (4.8 recommended)."
    } else {
        Write-Host ".NET Framework 4.x is too old or missing."
    }
} catch {
    Write-Host ".NET Framework 4.x not found in registry."
}
