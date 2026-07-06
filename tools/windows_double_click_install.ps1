#Requires -Version 5.1
# Double-click Windows installer for Time Library.

$ErrorActionPreference = "Stop"

function Info($Message) {
    Write-Host "[time-library] $Message"
}

function Select-InstallRoot {
    $defaultRoot = if (-not [string]::IsNullOrWhiteSpace($env:TIME_LIBRARY_INSTALL_DIR)) {
        $env:TIME_LIBRARY_INSTALL_DIR
    } elseif ([string]::IsNullOrWhiteSpace($env:MEMCORE_INSTALL_DIR)) {
        Join-Path $env:LOCALAPPDATA "time-library"
    } else {
        $env:MEMCORE_INSTALL_DIR
    }

    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Choose where Time Library should be installed"
        $dialog.ShowNewFolderButton = $true
        if (-not [string]::IsNullOrWhiteSpace($defaultRoot)) {
            $parent = Split-Path -Parent $defaultRoot
            if ($parent -and (Test-Path -LiteralPath $parent)) {
                $dialog.SelectedPath = $parent
            }
        }
        $result = $dialog.ShowDialog()
        if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
            Info "Install cancelled."
            exit 0
        }
        $selected = $dialog.SelectedPath
        $leaf = Split-Path -Leaf $selected
        if ($leaf -ieq "time-library") {
            return $selected
        }
        return (Join-Path $selected "time-library")
    } catch {
        Info "Folder picker unavailable: $($_.Exception.Message)"
        Info "Using default install path: $defaultRoot"
        return $defaultRoot
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$installWrapper = Join-Path $repoRoot "install.ps1"
if (-not (Test-Path -LiteralPath $installWrapper)) {
    throw "install.ps1 not found next to the Time Library package."
}

$installRoot = Select-InstallRoot
Info "Install path: $installRoot"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installWrapper -Dir $installRoot
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

try {
    Start-Process "http://127.0.0.1:9850" | Out-Null
} catch {
    Info "Open http://127.0.0.1:9850 to view the local console."
}
