#Requires -Version 5.1
# Memcore Cloud one-command installer for Windows.

param(
    [string]$Dir = "",
    [switch]$Reinstall,
    [switch]$Force,
    [switch]$NoStart,
    [switch]$SkipOpenClaw,
    [switch]$SkipHermes,
    [switch]$SkipCodex,
    [switch]$SkipClaudeDesktop
)

$ErrorActionPreference = "Stop"

$Repo = "strmforge/memcore-cloud"
$Version = "2026.6.3"
$ArchiveUrl = "https://github.com/$Repo/archive/refs/heads/main.zip"

function Invoke-YifanchenInstaller {
    param([string]$Root)

    if ([string]::IsNullOrWhiteSpace($Root)) { return $false }
    $installer = Join-Path $Root "tools\windows_full_install.ps1"
    if (-not (Test-Path $installer)) { return $false }

    $installerArgs = @{}
    if ($Dir) { $installerArgs["InstallRoot"] = $Dir }
    if ($Reinstall -or $Force) { $installerArgs["Reinstall"] = $true }
    if ($NoStart) { $installerArgs["NoStart"] = $true }
    if ($SkipOpenClaw) { $installerArgs["SkipOpenClaw"] = $true }
    if ($SkipHermes) { $installerArgs["SkipHermes"] = $true }
    if ($SkipCodex) { $installerArgs["SkipCodex"] = $true }
    if ($SkipClaudeDesktop) { $installerArgs["SkipClaudeDesktop"] = $true }

    & $installer @installerArgs
    exit $LASTEXITCODE
}

Invoke-YifanchenInstaller -Root $PSScriptRoot | Out-Null

$tmpRoot = Join-Path $env:TEMP ("yifanchen-install-" + [Guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tmpRoot "memcore-cloud-main.zip"
$extractPath = Join-Path $tmpRoot "extracted"

New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null

try {
    Write-Host "[memcore-cloud] Downloading Memcore Cloud $Version..."
    Invoke-WebRequest -Uri $ArchiveUrl -OutFile $zipPath -UseBasicParsing
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractPath -Force

    $inner = Get-ChildItem -LiteralPath $extractPath -Directory | Select-Object -First 1
    if (-not $inner) { throw "Downloaded archive is empty" }

    Invoke-YifanchenInstaller -Root $inner.FullName | Out-Null
    throw "Installer files were not found"
} finally {
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}
