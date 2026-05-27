#Requires -Version 5.1
# ============================================================
# memcore-cloud Uninstaller (Windows)
# Usage:
#   .\uninstall.ps1
#   .\uninstall.ps1 -InstallDir "D:\Apps\memcore-cloud"
# ============================================================
# This removes ONLY the software installation.
# User data (memory/, raw/, zhiyi/, output/) is preserved.

param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $InstallDir) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "MemcoreCloud"
}

function info($msg) { Write-Host "[memcore-cloud] $msg" }
function warn($msg) { Write-Host "[memcore-cloud WARNING] $msg" }
function error_exit($msg) { Write-Host "[memcore-cloud ERROR] $msg" >&2; exit 1 }

if (-not (Test-Path $InstallDir)) {
    error_exit "Installation directory does not exist: $InstallDir"
}

Write-Host ""
Write-Host "=============================================="
Write-Host " memcore-cloud Uninstaller (Windows)"
Write-Host "=============================================="
Write-Host ""
info "Install directory: $InstallDir"
Write-Host ""
Write-Host "This will remove the software at $InstallDir."
Write-Host ""
Write-Host "The following user data will be PRESERVED (not deleted):"
Write-Host "  - memory/"
Write-Host "  - raw/"
Write-Host "  - zhiyi/"
Write-Host "  - xingce/"
Write-Host "  - output/"
Write-Host "  - config/"
Write-Host "  - any backup directories"
Write-Host ""
Write-Host "Remove software only? [Y/n]"
$confirm = Read-Host
if ($confirm -eq "n") { Write-Host "Aborted."; exit 0 }

# Unregister user-mode autostart
$TaskName = "MemcoreCloudConsole"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    info "Removing Scheduled Task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    info "Scheduled Task removed."
}

# Stop running UI process
info "Stopping memcore-cloud UI if running..."
Get-Process | Where-Object { $_.ProcessName -match 'python' -and ($_.CommandLine -match 'p6_console' -or $_.CommandLine -match '9850') } | Stop-Process -Force -ErrorAction SilentlyContinue

# Also try netstat-based fallback (find process on 9850 port)
try {
    $connections = netstat -ano | Select-String ":9850 " | Select-String "LISTENING"
    if ($connections) {
        foreach ($c in $connections) {
            $parts = $c.ToString().Trim().Split() -ne ''
            $pid = $parts[-1]
            if ($pid) { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue }
        }
    }
} catch { }

# Remove installation directory
info "Removing software from $InstallDir..."
Remove-Item -Path $InstallDir -Recurse -Force

Write-Host ""
Write-Host "=============================================="
Write-Host " Uninstallation complete!"
Write-Host "=============================================="
Write-Host ""
Write-Host "Software removed. Your data has been preserved."
Write-Host ""
Write-Host "To reinstall, run:"
Write-Host "  irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex"
Write-Host ""
