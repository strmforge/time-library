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
    [switch]$SkipClaudeDesktop,
    [string]$DialogEntryHost = "",
    [string]$DialogEntryEndpointUrl = "",
    [string]$DialogEntryToken = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Dir) -and -not [string]::IsNullOrWhiteSpace($env:MEMCORE_INSTALL_DIR)) {
    $Dir = $env:MEMCORE_INSTALL_DIR
}

$Repo = if ([string]::IsNullOrWhiteSpace($env:MEMCORE_REPO)) { "strmforge/memcore-cloud" } else { $env:MEMCORE_REPO }
$Version = if ([string]::IsNullOrWhiteSpace($env:MEMCORE_VERSION)) { "2026.6.20" } else { $env:MEMCORE_VERSION }
$ReleaseTag = if ([string]::IsNullOrWhiteSpace($env:MEMCORE_RELEASE_TAG)) { "v$Version" } else { $env:MEMCORE_RELEASE_TAG }
$ArchiveUrl = if ([string]::IsNullOrWhiteSpace($env:MEMCORE_ARCHIVE_URL)) {
    "https://github.com/$Repo/releases/download/$ReleaseTag/memcore-cloud-$Version.zip"
} else {
    $env:MEMCORE_ARCHIVE_URL
}
$ArchiveSha256Url = if ([string]::IsNullOrWhiteSpace($env:MEMCORE_ARCHIVE_SHA256_URL)) { "$ArchiveUrl.sha256" } else { $env:MEMCORE_ARCHIVE_SHA256_URL }
$ArchiveSha256 = if ([string]::IsNullOrWhiteSpace($env:MEMCORE_ARCHIVE_SHA256)) { "" } else { $env:MEMCORE_ARCHIVE_SHA256 }
$SkipChecksum = @("1", "true", "yes") -contains ([string]$env:MEMCORE_SKIP_CHECKSUM).ToLowerInvariant()

function Get-ExpectedArchiveSha256 {
    param([string]$ChecksumPath)

    if (-not [string]::IsNullOrWhiteSpace($ArchiveSha256)) {
        return (($ArchiveSha256 -replace "`r", "").Trim() -split "\s+")[0].ToLowerInvariant()
    }

    Write-Host "[memcore-cloud] Downloading archive checksum..."
    Invoke-WebRequest -Uri $ArchiveSha256Url -OutFile $ChecksumPath -UseBasicParsing
    $content = Get-Content -LiteralPath $ChecksumPath -Raw
    return (($content -replace "`r", "").Trim() -split "\s+")[0].ToLowerInvariant()
}

function Test-ArchiveChecksum {
    param([string]$Path)

    if ($SkipChecksum) {
        Write-Host "[memcore-cloud] Skipping archive checksum verification because MEMCORE_SKIP_CHECKSUM=$env:MEMCORE_SKIP_CHECKSUM"
        return
    }

    $expected = Get-ExpectedArchiveSha256 -ChecksumPath "$Path.sha256"
    if (-not ($expected -match "^[0-9a-f]{64}$")) {
        throw "Invalid SHA256 checksum value"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "Archive checksum mismatch: expected $expected, got $actual"
    }
    Write-Host "[memcore-cloud] Archive checksum verified."
}

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
    if (-not [string]::IsNullOrWhiteSpace($DialogEntryHost)) { $installerArgs["DialogEntryHost"] = $DialogEntryHost }
    if (-not [string]::IsNullOrWhiteSpace($DialogEntryEndpointUrl)) { $installerArgs["DialogEntryEndpointUrl"] = $DialogEntryEndpointUrl }
    if (-not [string]::IsNullOrWhiteSpace($DialogEntryToken)) { $installerArgs["DialogEntryToken"] = $DialogEntryToken }

    & $installer @installerArgs
    exit $LASTEXITCODE
}

Invoke-YifanchenInstaller -Root $PSScriptRoot | Out-Null

$tmpRoot = Join-Path $env:TEMP ("yifanchen-install-" + [Guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tmpRoot "memcore-cloud-$Version.zip"
$extractPath = Join-Path $tmpRoot "extracted"

New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null

try {
    Write-Host "[memcore-cloud] Downloading Memcore Cloud $Version from $ArchiveUrl..."
    Invoke-WebRequest -Uri $ArchiveUrl -OutFile $zipPath -UseBasicParsing
    Test-ArchiveChecksum -Path $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractPath -Force

    $inner = Get-ChildItem -LiteralPath $extractPath -Directory | Select-Object -First 1
    if (-not $inner) { throw "Downloaded archive is empty" }

    Invoke-YifanchenInstaller -Root $inner.FullName | Out-Null
    throw "Installer files were not found"
} finally {
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}
