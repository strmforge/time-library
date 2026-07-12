#Requires -Version 5.1
param(
    [string]$InstallRoot = "",
    [switch]$Reinstall,
    [switch]$ResetInstall,
    [switch]$NoStart,
    [switch]$NoSmoke,
    [switch]$NoAutostart,
    [switch]$NoTray,
    [switch]$SkipOpenClaw,
    [switch]$SkipHermes,
    [switch]$SkipCodex,
    [switch]$SkipClaudeDesktop,
    [string]$DialogEntryHost = "127.0.0.1",
    [string]$DialogEntryEndpointUrl = "",
    [string]$DialogEntryToken = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    if (-not [string]::IsNullOrWhiteSpace($env:TIME_LIBRARY_INSTALL_DIR)) {
        $InstallRoot = $env:TIME_LIBRARY_INSTALL_DIR
    } elseif (-not [string]::IsNullOrWhiteSpace($env:MEMCORE_INSTALL_DIR)) {
        $InstallRoot = $env:MEMCORE_INSTALL_DIR
    } else {
        $InstallRoot = Join-Path $env:LOCALAPPDATA "time-library"
    }
}
$LegacyInstallRoot = Join-Path $env:LOCALAPPDATA "memcore-cloud"

function Info($msg) { Write-Host "[time-library-windows-install] $msg" }
function Warn($msg) { Write-Host "[time-library-windows-install WARNING] $msg" -ForegroundColor Yellow }
function Die($msg) { Write-Error "[time-library-windows-install ERROR] $msg"; exit 1 }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$LogDir = Join-Path $InstallRoot "logs"
$NodeName = if ($env:COMPUTERNAME) { $env:COMPUTERNAME } else { "windows-local" }
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$CodexSkillStatus = "pending"
$CodexMcpStatus = "pending"
$ClaudeCodeHookStatus = "pending"
$ClaudeDesktopStatus = "pending"
$DialogEntryHost = if ([string]::IsNullOrWhiteSpace($DialogEntryHost)) { "127.0.0.1" } else { $DialogEntryHost.Trim() }
$DialogEntryEndpointUrl = if ([string]::IsNullOrWhiteSpace($DialogEntryEndpointUrl)) { "http://$DialogEntryHost`:9860/entry/openclaw-before-dispatch" } else { $DialogEntryEndpointUrl.Trim() }
$DialogEntryToken = if ($DialogEntryToken) { $DialogEntryToken.Trim() } else { "" }

function Test-PythonCandidate {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    try {
        $out = & $Path -c "import sys; print(sys.executable); print(sys.version.split()[0])" 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        if (-not $out -or $out.Count -lt 2) { return $false }
        return $true
    } catch {
        return $false
    }
}

function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($exe -and ($exe.Source -notmatch "\\WindowsApps\\") -and (Test-PythonCandidate -Path $exe.Source)) {
            return $exe.Source
        }
    }
    $candidateRoots = @()
    if ($env:LOCALAPPDATA) {
        $candidateRoots += (Join-Path $env:LOCALAPPDATA "Programs\Python")
    }
    $candidateRoots += @(
        "C:\Program Files",
        "C:\Program Files (x86)"
    )
    foreach ($root in $candidateRoots) {
        if (-not (Test-Path $root)) { continue }
        $candidates = Get-ChildItem $root -Recurse -Filter python.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notmatch "\\WindowsApps\\" } |
            Sort-Object FullName
        foreach ($candidate in $candidates) {
            if (Test-PythonCandidate -Path $candidate.FullName) { return $candidate.FullName }
        }
    }
    return $null
}

function Get-RuntimePython {
    $venvPython = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    if (Test-PythonCandidate -Path $venvPython) {
        return $venvPython
    }
    return Find-Python
}

function Find-CodexCli {
    $cmd = Get-Command codex -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
    $candidateFiles = New-Object System.Collections.Generic.List[string]
    foreach ($base in @($codexHome, (Join-Path $env:USERPROFILE ".codex"))) {
        if ($base) {
            $candidateFiles.Add((Join-Path $base "chrome-native-hosts-v2.json"))
            $candidateFiles.Add((Join-Path $base "chrome-native-hosts.json"))
        }
    }
    if ($env:LOCALAPPDATA) {
        $candidateFiles.Add((Join-Path $env:LOCALAPPDATA "OpenAI\Codex\chrome-native-hosts-v2.json"))
        $candidateFiles.Add((Join-Path $env:LOCALAPPDATA "OpenAI\Codex\chrome-native-hosts.json"))
    }
    if ($env:APPDATA) {
        $candidateFiles.Add((Join-Path $env:APPDATA "OpenAI\Codex\chrome-native-hosts-v2.json"))
        $candidateFiles.Add((Join-Path $env:APPDATA "OpenAI\Codex\chrome-native-hosts.json"))
    }

    foreach ($file in ($candidateFiles | Select-Object -Unique)) {
        if (-not (Test-Path $file)) { continue }
        try {
            $data = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
            $entries = @()
            if ($data.entries) {
                $entries = @($data.entries)
            } elseif ($data.chromeNativeHosts) {
                $entries = @($data.chromeNativeHosts)
            } elseif ($data.paths -or $data.path -or $data.codexCliPath) {
                $entries = @($data)
            }
            foreach ($entry in $entries) {
                $candidate = $null
                if ($entry.paths -and $entry.paths.codexCliPath) {
                    $candidate = [string]$entry.paths.codexCliPath
                } elseif ($entry.codexCliPath) {
                    $candidate = [string]$entry.codexCliPath
                } elseif ($entry.path) {
                    $candidate = [string]$entry.path
                }
                if ($candidate -and (Test-Path $candidate)) {
                    return $candidate
                }
            }
        } catch { }
    }
    return $null
}

function Invoke-Robocopy {
    param([string]$From, [string]$To)
    if (-not (Test-Path $To)) { New-Item -ItemType Directory -Force -Path $To | Out-Null }
    $args = @(
        $From, $To, "/MIR",
        "/R:2", "/W:1", "/XJ",
        "/XD", ".git", ".venv", "__pycache__", ".pytest_cache", ".playwright-cli", ".codex_nas_pending", "config", "logs", "runtime", "memory", "raw", "zhiyi", "experience_lancedb", "backups", "data", "state", "input", "output", "release", "update_staging",
        "/XF", "*.pyc", ".DS_Store", "._*", ".checkpoint", ".checkpoint_p2.json", "update_history.jsonl",
        "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
    )
    & robocopy @args | Out-Null
    if ($LASTEXITCODE -gt 7) { Die "robocopy failed with exit code $LASTEXITCODE" }
}

function Merge-PackagedConfig {
    $python = Find-Python
    if (-not $python) { Die "Python is required to merge packaged configuration" }
    $helper = Join-Path $SourceRoot "tools\install_config_merge.py"
    & $python $helper (Join-Path $SourceRoot "config") (Join-Path $InstallRoot "config") | Out-Null
    if ($LASTEXITCODE -ne 0) { Die "packaged configuration merge failed" }
}

function Migrate-LegacyStatePaths {
    $python = Find-Python
    if (-not $python) { Die "Python is required to migrate local state paths" }
    $helper = Join-Path $SourceRoot "tools\install_state_migrate.py"
    & $python $helper $InstallRoot $LegacyInstallRoot | Out-Null
    if ($LASTEXITCODE -ne 0) { Die "local state path migration failed" }
}

function Backup-InstallFilesBestEffort {
    param([string]$BackupPath)
    if (-not (Test-Path $BackupPath)) { New-Item -ItemType Directory -Force -Path $BackupPath | Out-Null }
    $args = @(
        $InstallRoot, $BackupPath, "/E",
        "/R:1", "/W:1", "/XJ",
        "/XD", ".git", ".venv", "__pycache__", ".pytest_cache", ".playwright-cli", ".codex_nas_pending", "logs", "runtime", "memory", "raw", "zhiyi", "experience_lancedb", "backups", "data", "state", "input", "output", "release", "update_staging",
        "/XF", "*.pyc", ".DS_Store", "._*", ".checkpoint", ".checkpoint_p2.json", "update_history.jsonl",
        "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
    )
    & robocopy @args | Out-Null
    if ($LASTEXITCODE -gt 7) {
        Warn "Install file backup was incomplete (robocopy exit $LASTEXITCODE); live data remains in place"
    }
}

function Stop-Port {
    param([int]$Port)
    $lines = netstat -ano | Select-String ":$Port " | Select-String "LISTENING"
    foreach ($line in $lines) {
        $parts = $line.ToString().Trim().Split() | Where-Object { $_ }
        if ($parts.Count -lt 5) { continue }
        $pidText = $parts[-1]
        if ($pidText -match '^\d+$') {
            try {
                Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
                Info "Stopped old listener on port $Port (PID $pidText)"
            } catch { }
        }
    }
}

function Stop-OldProcesses {
    foreach ($port in @(9830, 9840, 9850, 9851, 9860)) { Stop-Port -Port $port }
    $pidDir = Join-Path $InstallRoot "runtime"
    if (Test-Path $pidDir) {
        Get-ChildItem $pidDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
            $pidText = (Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue).Trim()
            if ($pidText -match '^\d+$') {
                Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
            }
        }
    }
    $patterns = @(
        "*$InstallRoot\.venv\Scripts\python.exe*",
        "*$InstallRoot\src\*.py*",
        "*$InstallRoot\runtime\*.cmd*",
        "*$InstallRoot\tools\windows_guardian.ps1*",
        "*$InstallRoot\tools\windows_tray.ps1*"
    )
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $cmd = [string]$_.CommandLine
        foreach ($pattern in $patterns) {
            if ($cmd -like $pattern) {
                Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue
                Info "Stopped old process for install root (PID $($_.ProcessId))"
                break
            }
        }
    }
}

function Unregister-MemcoreScheduledTasks {
    foreach ($taskName in @(
        "MemcoreCloudGuardianLogon",
        "MemcoreCloudGuardianHealth",
        "MemcoreCloudTray"
    )) {
        try {
            $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            if ($task) {
                Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
                Info "Removed old scheduled task: $taskName"
            }
        } catch { }
    }
}

function Install-Files {
    if (Test-Path $InstallRoot) { Stop-OldProcesses }
    $migratedLegacy = $false
    if ((-not (Test-Path $InstallRoot)) -and (Test-Path $LegacyInstallRoot) -and ($InstallRoot -ieq (Join-Path $env:LOCALAPPDATA "time-library"))) {
        Info "Migrating existing legacy install data from $LegacyInstallRoot to $InstallRoot"
        New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
        foreach ($name in @("memory", "raw", "zhiyi", "experience_lancedb", "logs", "backups", "data", "state", "input", "output", "config", "runtime", "update_staging", "release", ".codex_nas_pending", ".checkpoint", ".checkpoint_p2.json", "update_history.jsonl")) {
            $from = Join-Path $LegacyInstallRoot $name
            if (Test-Path $from) {
                Copy-Item -LiteralPath $from -Destination $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        $migratedLegacy = $true
    }
    if ((Test-Path $InstallRoot) -and ($Reinstall -or $ResetInstall) -and (-not $migratedLegacy)) {
        if ($ResetInstall) {
            Info "Removing existing install root"
            Remove-Tree -Path $InstallRoot
        } else {
            $backup = "$InstallRoot.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
            Info "Backing up existing install files to $backup"
            Backup-InstallFilesBestEffort -BackupPath $backup
        }
    }
    Invoke-Robocopy -From $SourceRoot -To $InstallRoot
    Remove-Tree -Path (Join-Path $InstallRoot ".playwright-cli")
    Merge-PackagedConfig
    Migrate-LegacyStatePaths
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

function Test-DialogEntryNeedsToken {
    if (($DialogEntryHost -ne "127.0.0.1") -and ($DialogEntryHost -ne "localhost") -and ($DialogEntryHost -ne "::1")) {
        return $true
    }
    return ($DialogEntryEndpointUrl -notmatch "127\.0\.0\.1|localhost|\[::1\]")
}

function New-DialogEntryTokenValue {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 32
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return ([Convert]::ToBase64String($bytes).TrimEnd("=") -replace "\+", "-" -replace "/", "_")
}

function Ensure-DialogEntryToken {
    if (-not (Test-DialogEntryNeedsToken)) { return }
    $runtime = Join-Path $InstallRoot "runtime"
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $tokenPath = Join-Path $runtime "dialog_entry_token"
    if ([string]::IsNullOrWhiteSpace($script:DialogEntryToken) -and (Test-Path -LiteralPath $tokenPath)) {
        $script:DialogEntryToken = (Get-Content -LiteralPath $tokenPath -Raw -Encoding UTF8).Trim()
    }
    if ([string]::IsNullOrWhiteSpace($script:DialogEntryToken)) {
        $script:DialogEntryToken = New-DialogEntryTokenValue
    }
    Write-Utf8NoBom -Path $tokenPath -Text ($script:DialogEntryToken + "`n")
}

function Remove-Tree {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $Path) {
        & $env:ComSpec /c "rmdir /s /q `"$Path`"" | Out-Null
    }
    if (Test-Path $Path) { Die "failed to remove $Path" }
}

function Copy-ConfigTemplate {
    param([string]$Name, [string]$Target)
    $src = Join-Path $InstallRoot "config\$Name"
    $dst = Join-Path $InstallRoot "config\$Target"
    if ((Test-Path $src) -and -not (Test-Path $dst)) {
        Copy-Item $src $dst -Force
    }
}

function Write-Config {
    foreach ($dir in @(
        "config", "logs", "runtime", "memory",
        "zhiyi\case_memory", "zhiyi\error_memory", "zhiyi\preference_memory",
        "experience_lancedb", "backups", "output"
    )) {
        New-Item -ItemType Directory -Force -Path (Join-Path $InstallRoot $dir) | Out-Null
    }

    Copy-ConfigTemplate -Name "default_model_config.json" -Target "model_config.json"
    Copy-ConfigTemplate -Name "default_feature_flags.json" -Target "feature_flags.json"
    Copy-ConfigTemplate -Name "default_alias_map.json" -Target "alias_map.json"

    $cfgPath = Join-Path $InstallRoot "config\memcore.json"
    $cfg = [ordered]@{}
    $cfg["_comment"] = "Time Library user-level Windows config"
    $cfg["_base_dir"] = $InstallRoot
    $cfg["version"] = "1.0.0"
    $cfg["paths"] = @{
        memory = "memory"
        openclaw_agents = (Join-Path $env:USERPROFILE ".openclaw\agents")
        openclaw_workspace = (Join-Path $env:USERPROFILE ".openclaw\workspace")
        zhiyi = "zhiyi"
        config_dir = "config"
        experience_lancedb = "experience_lancedb"
        checkpoint = ".checkpoint"
        alias_map = "config\alias_map.json"
        model_config = "config\model_config.json"
        lancedb_v2_metadata = "config\lancedb_v2_metadata.json"
        logs = "logs"
    }
    $cfg["nodes"] = @{
        current = $NodeName
        raw_memory_subpath = "$NodeName/openclaw/openclaw_session_jsonl"
    }
    $cfg["services"] = @{
        p0_watcher_enabled = $true
        p0_watcher_resource_profile = "light"
        p0_watcher_source_default = "all"
        p0_watcher_interval_milliseconds = 5000
        p3_recall_port = 9830
        p4_provider_port = 9840
        p6_console_port = 9850
        raw_consumption_gateway_port = 9851
        dialog_entry_port = 9860
        dialog_entry_host = $DialogEntryHost
        dialog_entry_endpoint_url = $DialogEntryEndpointUrl
        dialog_entry_lan_requires_token = $true
    }
    $cfg["integrations"] = @{
        claude_desktop = @{
            raw_ingest = @{
                enabled = $true
                authorization = "user_authorized_local_claude_desktop_parser_to_time_library_raw_only"
                write_target = "memcore_raw_only"
                platform_write_allowed = $false
                interval_milliseconds = 5000
                limit = 20
            }
        }
        hermes = @{
            model_call = @{
                hermes_provider = "minimax"
                hermes_model = "MiniMax-M2.7"
                source = "memcore-time_library"
            }
        }
    }
    Write-Utf8NoBom -Path $cfgPath -Text (($cfg | ConvertTo-Json -Depth 20) + "`n")

    $flagsPath = Join-Path $InstallRoot "config\feature_flags.json"
    $flags = [ordered]@{}
    if (Test-Path $flagsPath) {
        try {
            $existingFlags = Get-Content -LiteralPath $flagsPath -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($prop in $existingFlags.PSObject.Properties) {
                $flags[$prop.Name] = $prop.Value
            }
        } catch {
            $flags = [ordered]@{}
        }
    }
    $passiveFlags = [ordered]@{
        zhiyi_direct = $false
        zhiyi_inject = $false
        openclaw_passive_auto_inject = $false
        openclaw_rpc = $false
        passthrough = $true
        audit_log = $true
    }
    $changedKeys = New-Object System.Collections.Generic.List[string]
    foreach ($key in $passiveFlags.Keys) {
        if ((-not $flags.Contains($key)) -or ($flags[$key] -ne $passiveFlags[$key])) {
            [void]$changedKeys.Add($key)
        }
    }
    $backupPath = $null
    if (($changedKeys.Count -gt 0) -and (Test-Path $flagsPath)) {
        $backupPath = "$flagsPath.time_library-passive-migration.$(Get-Date -Format 'yyyyMMddHHmmss')"
        Copy-Item -LiteralPath $flagsPath -Destination $backupPath -Force
    }
    foreach ($key in $passiveFlags.Keys) { $flags[$key] = $passiveFlags[$key] }
    Write-Utf8NoBom -Path $flagsPath -Text (($flags | ConvertTo-Json -Depth 20) + "`n")
    if ($changedKeys.Count -gt 0) {
        $receiptPath = Join-Path $InstallRoot "logs\passive_delivery_migration.jsonl"
        $receipt = [ordered]@{
            action = "passive_delivery_migration"
            source = "windows_full_install"
            changed_keys = @($changedKeys)
            feature_flags_path = $flagsPath
            backup_path = $backupPath
            note = "Safety migration after OpenClaw direct-answer boundary fix; explicit opt-in must be re-enabled intentionally after install."
            created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        }
        $enc = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::AppendAllText($receiptPath, (($receipt | ConvertTo-Json -Depth 20 -Compress) + "`n"), $enc)
    }

    $modelCfgPath = Join-Path $InstallRoot "config\model_config.json"
    $modelCfg = Get-Content -LiteralPath $modelCfgPath -Raw | ConvertFrom-Json
    $modelCfg.recall.mode = "substring"
    Write-Utf8NoBom -Path $modelCfgPath -Text (($modelCfg | ConvertTo-Json -Depth 20) + "`n")
}

function Install-PythonEnv {
    $python = Find-Python
    if (-not $python) { Die "Python not found" }
    $venv = Join-Path $InstallRoot ".venv"
    if (-not (Test-Path $venv)) {
        & $python -m venv $venv
        if ($LASTEXITCODE -ne 0) { Die "failed to create Python venv with $python" }
    }
    $venvPython = Join-Path $venv "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) { Die "Python venv was not created: $venvPython" }
    & $venvPython -m pip install --upgrade pip | Out-Null
    $req = Join-Path $InstallRoot "requirements-core.txt"
    if (Test-Path $req) { & $venvPython -m pip install -r $req }
}

function Install-OpenClawPlugin {
    if ($SkipOpenClaw) { return }
    $pluginSrc = Join-Path $InstallRoot "system\openclaw\plugins\time-library-native"
    if (-not (Test-Path $pluginSrc)) { Warn "OpenClaw plugin source not found"; return }
    $openclaw = Get-Command openclaw -ErrorAction SilentlyContinue
    if ($openclaw) {
        & openclaw plugins install --link $pluginSrc | Out-Null
        & openclaw plugins registry --refresh | Out-Null
    }

    $cfgPath = Join-Path $env:USERPROFILE ".openclaw\openclaw.json"
    if (-not (Test-Path $cfgPath)) { Warn "OpenClaw config not found: $cfgPath"; return }
    $py = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    $script = @'
import json, shutil, sys, time
from pathlib import Path
cfg_path = Path(sys.argv[1])
plugin_src = sys.argv[2]
endpoint_url = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:9860/entry/openclaw-before-dispatch"
dialog_entry_token = sys.argv[4] if len(sys.argv) > 4 else ""
cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
backup = cfg_path.with_name(cfg_path.name + ".time_library-bak." + time.strftime("%Y%m%d%H%M%S"))
shutil.copy2(cfg_path, backup)
plugins = cfg.setdefault("plugins", {})
entries = plugins.setdefault("entries", {})
entry = entries.setdefault("time-library-native", {})
entry["enabled"] = False
base = entry.get("config") if isinstance(entry.get("config"), dict) else {}
base.update({
    "enabled": False,
    "endpointUrl": endpoint_url,
    "dialogEntryToken": dialog_entry_token,
    "allowedChannels": ["webchat"],
    "enableModelCall": False,
    "forceZhiyiDirect": False,
    "timeoutMs": 120000,
})
entry["config"] = base
load = plugins.setdefault("load", {})
paths = load.setdefault("paths", [])
if isinstance(paths, list) and plugin_src not in paths:
    paths.append(plugin_src)
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
'@
    $tmp = Join-Path $env:TEMP "time_library-openclaw-config.py"
    Write-Utf8NoBom -Path $tmp -Text $script
    & $py $tmp $cfgPath $pluginSrc $DialogEntryEndpointUrl $DialogEntryToken
}

function Install-HermesPlugin {
    if ($SkipHermes) { return }
    $src = Join-Path $InstallRoot "system\hermes\plugins\time_library"
    if (-not (Test-Path $src)) { Warn "Hermes plugin source not found"; return }
    $hermesHome = $HermesHome
    New-Item -ItemType Directory -Force -Path (Join-Path $hermesHome "plugins") | Out-Null
    $dst = Join-Path $hermesHome "plugins\time_library"
    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
    Copy-Item $src $dst -Recurse -Force
    $skillSrc = Join-Path $InstallRoot "system\skills\time-library"
    $skillDst = Join-Path $hermesHome "skills\time-library"
    if (Test-Path $skillSrc) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $skillDst) | Out-Null
        if (Test-Path $skillDst) { Remove-Tree -Path $skillDst }
        Copy-Item -Path $skillSrc -Destination $skillDst -Recurse -Force
        Info "Hermes skill installed: $skillDst"
    } else {
        Warn "Hermes skill source not found: $skillSrc"
    }

    $profileCfg = Join-Path $hermesHome "profiles\default\config.yaml"
    $rootCfg = Join-Path $hermesHome "config.yaml"
    $cfgPath = if (Test-Path $profileCfg) { $profileCfg } elseif (Test-Path $rootCfg) { $rootCfg } elseif (Test-Path (Join-Path $hermesHome "profiles")) { $profileCfg } else { $rootCfg }
    $agentPython = Join-Path $hermesHome "hermes-agent\venv\Scripts\python.exe"
    $py = if (Test-Path $agentPython) { $agentPython } else { Join-Path $InstallRoot ".venv\Scripts\python.exe" }
    $script = @'
import shutil, sys, time
from pathlib import Path
cfg_path = Path(sys.argv[1])
cfg_path.parent.mkdir(parents=True, exist_ok=True)
backup = cfg_path.with_name(cfg_path.name + ".time_library-bak." + time.strftime("%Y%m%d%H%M%S"))
if cfg_path.exists():
    shutil.copy2(cfg_path, backup)
try:
    import yaml
except Exception:
    yaml = None
if yaml:
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8-sig")) if cfg_path.exists() else {}
    if not isinstance(cfg, dict):
        cfg = {}
    memory = cfg.setdefault("memory", {})
    memory["provider"] = "time_library"
    plugins = cfg.setdefault("plugins", {})
    enabled = plugins.setdefault("enabled", [])
    if isinstance(enabled, list) and "time_library" not in enabled:
        enabled.append("time_library")
    plugins["time_library"] = {
        **(plugins.get("time_library") if isinstance(plugins.get("time_library"), dict) else {}),
        "provider_url": "http://127.0.0.1:9851/api/v1/raw/query",
        "memory_scope": "window",
        "computer_name": "",
        "limit": 3,
        "excerpt_chars": 500,
        "context_chars": 2400,
        "timeout_seconds": 5,
        "include_session_id": True,
        "receipt_url": "http://127.0.0.1:9850/api/v1/hermes/consumption-receipts",
        "enable_receipts": True,
        "enable_queue_prefetch": True,
    }
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
else:
    existing = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    block = """
memory:
  provider: time_library
plugins:
  enabled:
    - time_library
  time_library:
    provider_url: http://127.0.0.1:9851/api/v1/raw/query
    memory_scope: window
    computer_name: ""
    limit: 3
    excerpt_chars: 500
    context_chars: 2400
    timeout_seconds: 5
    include_session_id: true
    receipt_url: http://127.0.0.1:9850/api/v1/hermes/consumption-receipts
    enable_receipts: true
    enable_queue_prefetch: true
"""
    cfg_path.write_text(existing.rstrip() + "\n" + block, encoding="utf-8")
'@
    $tmp = Join-Path $env:TEMP "time_library-hermes-config.py"
    Write-Utf8NoBom -Path $tmp -Text $script
    & $py $tmp $cfgPath
}

function Install-CodexSkill {
    if ($SkipCodex) {
        $script:CodexSkillStatus = "skipped"
        return
    }
    $src = Join-Path $InstallRoot "system\skills\time-library"
    if (-not (Test-Path $src)) {
        Warn "Codex skill source not found: $src"
        $script:CodexSkillStatus = "source not found"
        return
    }
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
    $dst = Join-Path $codexHome "skills\time-library"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    $skillsRoot = Join-Path $codexHome "skills"
    $backupRoot = Join-Path $codexHome ("skills-backups\time-library-" + (Get-Date -Format "yyyyMMddHHmmss"))
    if (Test-Path $skillsRoot) {
        @("time-library.backup*", "time-library.backup*") | ForEach-Object {
            $filter = $_
            Get-ChildItem -LiteralPath $skillsRoot -Directory -Filter $filter -ErrorAction SilentlyContinue | ForEach-Object {
            New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
            Move-Item -LiteralPath $_.FullName -Destination $backupRoot -Force
            Info "Moved stale Codex Time Library skill backup out of active skills: $($_.FullName)"
            }
        }
    }
    if (Test-Path $dst) { Remove-Tree -Path $dst }
    Copy-Item -Path $src -Destination $dst -Recurse -Force
    Info "Codex skill installed: $dst"
    $script:CodexSkillStatus = "time-library"
}

function Install-CodexMcp {
    if ($SkipCodex) {
        $script:CodexMcpStatus = "skipped"
        return
    }
    $codexExe = Find-CodexCli
    if (-not $codexExe) {
        Warn "Codex CLI not found; skipping Codex MCP registration"
        $script:CodexMcpStatus = "codex CLI not found"
        return
    }
    $python = Get-RuntimePython
    if (-not $python) {
        Warn "Runtime Python not found; skipping Codex MCP registration"
        $script:CodexMcpStatus = "runtime python not found"
        return
    }
    $bridge = Join-Path $InstallRoot "tools\codex_mcp_bridge.py"
    $registryPath = Join-Path $InstallRoot "config\window_binding_registry.json"
    if (-not (Test-Path $bridge)) {
        Warn "Codex MCP bridge not found: $bridge"
        $script:CodexMcpStatus = "bridge not found"
        return
    }
    try {
        & $codexExe mcp remove time-library *> $null
    } catch { }
    try {
        & $codexExe mcp add time-library `
            --env "PYTHONIOENCODING=utf-8" `
            --env "PYTHONUTF8=1" `
            --env "MEMCORE_ROOT=$InstallRoot" `
            --env "MEMCORE_WINDOW_BINDING_REGISTRY=$registryPath" `
            -- $python $bridge `
                --endpoint "http://127.0.0.1:9851/mcp" `
                --timeout "30" `
                --window-binding-registry $registryPath `
                --binding-key "codex" *> $null
        if ($LASTEXITCODE -eq 0) {
            Info "Codex MCP registered: time-library via $bridge"
            $script:CodexMcpStatus = "time-library"
        } else {
            Warn "Codex MCP registration failed; Codex users can run: codex mcp add time-library -- python $bridge --endpoint http://127.0.0.1:9851/mcp"
            $script:CodexMcpStatus = "registration failed"
        }
    } catch {
        Warn "Codex MCP registration failed; Codex users can run: codex mcp add time-library -- python $bridge --endpoint http://127.0.0.1:9851/mcp"
        $script:CodexMcpStatus = "registration failed"
    }
}

function Install-ClaudeCodePreflightHook {
    $python = Get-RuntimePython
    if (-not $python) {
        Warn "Runtime Python not found; skipping Claude Code preflight hook"
        $script:ClaudeCodeHookStatus = "runtime python not found"
        return
    }
    $hookHelper = Join-Path $InstallRoot "tools\install_claude_code_preflight_hook.py"
    $hookScript = Join-Path $InstallRoot "tools\claude_code_preflight_hook.py"
    if ((-not (Test-Path $hookHelper)) -or (-not (Test-Path $hookScript))) {
        Warn "Claude Code preflight hook helper not found; skipping"
        $script:ClaudeCodeHookStatus = "helper not found"
        return
    }
    $settingsPath = if ($env:CLAUDE_CODE_SETTINGS) { $env:CLAUDE_CODE_SETTINGS } else { Join-Path $env:USERPROFILE ".claude\settings.json" }
    if ((-not $env:CLAUDE_CODE_SETTINGS) -and (-not (Test-Path (Split-Path -Parent $settingsPath)))) {
        $script:ClaudeCodeHookStatus = "Claude Code settings not found"
        return
    }
    try {
        $resultText = & $python $hookHelper `
            --settings-path $settingsPath `
            --hook-script $hookScript `
            --python $python `
            --json 2>$null
        $data = $null
        try {
            $data = $resultText | ConvertFrom-Json
        } catch { }
        if ($data -and $data.ok) {
            Info "Claude Code preflight hook installed: $($data.reason)"
            $script:ClaudeCodeHookStatus = $data.reason
        } else {
            $reason = if ($data -and $data.reason) { $data.reason } else { "unavailable" }
            Warn "Claude Code preflight hook not installed: $reason"
            $script:ClaudeCodeHookStatus = $reason
        }
    } catch {
        Warn "Claude Code preflight hook install failed: $($_.Exception.Message)"
        $script:ClaudeCodeHookStatus = "install failed"
    }
}

function Install-ClaudeDesktopMcp {
    if ($SkipClaudeDesktop) {
        $script:ClaudeDesktopStatus = "skipped"
        return
    }
    $claudeCandidates = New-Object System.Collections.Generic.List[string]
    if ($env:CLAUDE_DESKTOP_HOME) { $claudeCandidates.Add($env:CLAUDE_DESKTOP_HOME) }
    if ($env:APPDATA) { $claudeCandidates.Add((Join-Path $env:APPDATA "Claude")) }
    if ($env:LOCALAPPDATA) {
        $claudeCandidates.Add((Join-Path $env:LOCALAPPDATA "Claude"))
        Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "Claude-*" } |
            ForEach-Object { $claudeCandidates.Add($_.FullName) }
        $packagesRoot = Join-Path $env:LOCALAPPDATA "Packages"
        $claudeCandidates.Add((Join-Path $packagesRoot "Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude"))
        if (Test-Path $packagesRoot) {
            Get-ChildItem -LiteralPath $packagesRoot -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -like "Claude_*" } |
                ForEach-Object { $claudeCandidates.Add((Join-Path $_.FullName "LocalCache\Roaming\Claude")) }
        }
    }
    if ($env:USERPROFILE) {
        $claudeCandidates.Add((Join-Path $env:USERPROFILE "AppData\Roaming\Claude"))
        $claudeCandidates.Add((Join-Path $env:USERPROFILE "AppData\Local\Claude"))
    }
    $candidateHomes = @()
    foreach ($candidate in ($claudeCandidates | Select-Object -Unique)) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        if (Test-Path $candidate) { $candidateHomes += $candidate }
    }
    if (-not $candidateHomes) {
        Warn "Claude Desktop home not found; skipping Claude Desktop MCP registration"
        $script:ClaudeDesktopStatus = "Claude Desktop not found"
        return
    }
    $bridge = Join-Path $InstallRoot "tools\claude_desktop_mcp_bridge.py"
    if (-not (Test-Path $bridge)) {
        Warn "Claude Desktop MCP bridge not found: $bridge"
        $script:ClaudeDesktopStatus = "bridge not found"
        return
    }
    $skillSrc = Join-Path $InstallRoot "system\skills\time-library"
    $skillHelper = Join-Path $InstallRoot "tools\install_claude_desktop_skill.py"
    $python = Get-RuntimePython
    if (-not $python) {
        Warn "Runtime Python not found; skipping Claude Desktop MCP registration"
        $script:ClaudeDesktopStatus = "runtime python not found"
        return
    }
    $script = @'
import json
import os
import sys
from pathlib import Path

home = Path(sys.argv[1])
bridge = Path(sys.argv[2])
install_root = Path(sys.argv[3])
registry_path = install_root / "config" / "window_binding_registry.json"
cfg_path = home / "claude_desktop_config.json"
cfg = {}
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        backup = cfg_path.with_suffix(cfg_path.suffix + ".invalid-time_library-bak")
        try:
            backup.write_text(cfg_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        except Exception:
            pass
        cfg = {}
servers = cfg.setdefault("mcpServers", {})
servers["time-library"] = {
    "type": "stdio",
    "command": sys.executable,
    "args": [
        str(bridge),
        "--endpoint", "http://127.0.0.1:9851/mcp",
        "--timeout", "30",
        "--window-binding-registry", str(registry_path),
        "--binding-key", "claude_desktop",
    ],
    "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "MEMCORE_ROOT": str(install_root),
        "MEMCORE_WINDOW_BINDING_REGISTRY": str(registry_path),
        "MEMCORE_CLAUDE_DESKTOP_CANONICAL_WINDOW_ID": "",
        "MEMCORE_CLAUDE_DESKTOP_SESSION_ID": "",
    },
}
home.mkdir(parents=True, exist_ok=True)
if cfg_path.exists():
    backup = cfg_path.with_suffix(cfg_path.suffix + ".bak-time_library")
    if not backup.exists():
        backup.write_text(cfg_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, cfg_path)
print(str(cfg_path))
'@
    $tmp = Join-Path $env:TEMP "time_library-claude-desktop-mcp.py"
    Write-Utf8NoBom -Path $tmp -Text $script
    $registered = @()
    foreach ($claudeHome in $candidateHomes) {
        try {
            & $python $tmp $claudeHome $bridge $InstallRoot | Out-Null
            if ((Test-Path $skillHelper) -and (Test-Path $skillSrc)) {
                $skillResult = & $python $skillHelper $claudeHome $skillSrc --create --json 2>$null
                $skillData = $null
                try {
                    $skillData = $skillResult | ConvertFrom-Json
                } catch { }
                if ($skillData -and ([int]$skillData.installed_count -gt 0)) {
                    Info "Claude Desktop skill updated: time-library"
                } else {
                    $reason = if ($skillData -and $skillData.reason) { $skillData.reason } else { "unavailable" }
                    Info "Claude Desktop skill not updated for ${claudeHome}: $reason"
                }
            }
            $registered += $claudeHome
        } catch {
            Warn "Claude Desktop MCP registration failed for ${claudeHome}: $($_.Exception.Message)"
        }
    }
    if ($registered.Count -gt 0) {
        Info "Claude Desktop MCP registered: time-library via $bridge"
        $script:ClaudeDesktopStatus = "time-library ($($registered.Count) config path(s))"
    } else {
        Warn "Claude Desktop MCP registration failed for all detected config paths"
        $script:ClaudeDesktopStatus = "registration failed"
    }
}

function Start-MemcoreService {
    param(
        [string]$Name,
        [string]$ArgLine,
        [switch]$IncludeDialogEntryToken
    )
    $python = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    $runtime = Join-Path $InstallRoot "runtime"
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $out = Join-Path $LogDir "$Name.out.log"
    $err = Join-Path $LogDir "$Name.err.log"
    Remove-Item -LiteralPath $out, $err -Force -ErrorAction SilentlyContinue

    $cmdPath = Join-Path $runtime "$Name.cmd"
    $lines = @(
        "@echo off",
        "cd /d `"$InstallRoot`"",
        "set `"TIME_LIBRARY_ROOT=$InstallRoot`"",
        "set `"TIME_LIBRARY_INSTALL_ROOT=$InstallRoot`"",
        "set `"MEMCORE_ROOT=$InstallRoot`"",
        "set `"MEMCORE_INSTALL_ROOT=$InstallRoot`"",
        "set `"PYTHONPATH=$InstallRoot`"",
        "set `"PYTHONIOENCODING=utf-8`"",
        "set `"HERMES_HOME=$HermesHome`""
    )
    if ($IncludeDialogEntryToken -and $DialogEntryToken) {
        $lines += "set `"MEMCORE_DIALOG_ENTRY_TOKEN=$DialogEntryToken`""
    }
    if ($env:MEMCORE_HERMES_CLI) {
        $lines += "set `"MEMCORE_HERMES_CLI=$env:MEMCORE_HERMES_CLI`""
    }
    $lines += "`"$python`" $ArgLine 1>>`"$out`" 2>>`"$err`""
    Write-Utf8NoBom -Path $cmdPath -Text (($lines -join "`r`n") + "`r`n")

    $startup = ([WMIClass]"Win32_ProcessStartup").CreateInstance()
    $startup.ShowWindow = 0
    $command = "$env:ComSpec /c `"`"$cmdPath`"`""
    $result = ([WMIClass]"Win32_Process").Create($command, $InstallRoot, $startup)
    if ($result.ReturnValue -ne 0) { Die "failed to start $Name via WMI, code $($result.ReturnValue)" }
    Set-Content -Path (Join-Path $runtime "$Name.pid") -Value $result.ProcessId -Encoding ASCII
    Info "Started $Name (PID $($result.ProcessId))"
}

function Start-Services {
    $env:TIME_LIBRARY_ROOT = $InstallRoot
    $env:TIME_LIBRARY_INSTALL_ROOT = $InstallRoot
    $env:MEMCORE_ROOT = $InstallRoot
    $env:MEMCORE_INSTALL_ROOT = $InstallRoot
    $env:PYTHONPATH = $InstallRoot
    $env:PYTHONIOENCODING = "utf-8"
    $hermes = Get-Command hermes -ErrorAction SilentlyContinue
    if ($hermes) { $env:MEMCORE_HERMES_CLI = $hermes.Source }

    Stop-OldProcesses
    Start-MemcoreService -Name "p0-watcher" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\memcore-cloud.py')`" --watch --source all"
    Start-MemcoreService -Name "p3-recall" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\p3_recall.py')`" serve --port 9830"
    Start-MemcoreService -Name "p4-provider" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\p4_provider.py')`" --port 9840"
    Start-MemcoreService -Name "p6-console" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\p6_console.py')`" --host 127.0.0.1 --port 9850"
    Start-MemcoreService -Name "raw-gateway" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\raw_consumption_gateway.py')`""
    Start-MemcoreService `
        -Name "dialog-entry" `
        -ArgLine "-u `"$(Join-Path $InstallRoot 'src\dialog_entry_proxy.py')`" --host $DialogEntryHost --port 9860" `
        -IncludeDialogEntryToken
}

function Register-WindowsAutostart {
    if ($NoAutostart) {
        Info "Autostart registration skipped"
        return
    }

    $powershellExe = Join-Path $PSHOME "powershell.exe"
    $guardian = Join-Path $InstallRoot "tools\windows_guardian.ps1"
    $hiddenGuardian = Join-Path $InstallRoot "tools\windows_hidden_guardian.vbs"
    $tray = Join-Path $InstallRoot "tools\windows_tray.ps1"
    if (-not (Test-Path -LiteralPath $guardian)) {
        Warn "Windows guardian script not found: $guardian"
        return
    }
    if (-not (Test-Path -LiteralPath $hiddenGuardian)) {
        Warn "Windows hidden guardian launcher not found: $hiddenGuardian"
        return
    }

    Unregister-MemcoreScheduledTasks

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $guardianSettings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

    $wscriptExe = Join-Path $env:SystemRoot "System32\wscript.exe"
    $guardianArgs = "`"$hiddenGuardian`" `"$InstallRoot`""
    $guardianAction = New-ScheduledTaskAction -Execute $wscriptExe -Argument $guardianArgs
    $logonTrigger = New-ScheduledTaskTrigger -AtLogOn
    Register-ScheduledTask `
        -TaskName "MemcoreCloudGuardianLogon" `
        -Description "Time Library starts the local memory watcher at user logon." `
        -Action $guardianAction `
        -Trigger $logonTrigger `
        -Principal $principal `
        -Settings $guardianSettings `
        -Force | Out-Null

    $healthTrigger = New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    Register-ScheduledTask `
        -TaskName "MemcoreCloudGuardianHealth" `
        -Description "Time Library periodically checks local service health and keeps the watcher running." `
        -Action $guardianAction `
        -Trigger $healthTrigger `
        -Principal $principal `
        -Settings $guardianSettings `
        -Force | Out-Null
    Info "Registered guardian scheduled tasks"

    & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $guardian -InstallRoot $InstallRoot -StartWatcher -Backfill -Quiet
    if ($LASTEXITCODE -ne 0) {
        Warn "Guardian immediate check failed; scheduled task remains registered"
    }

    if ($NoTray) {
        Info "Tray registration skipped"
        return
    }
    if (-not (Test-Path -LiteralPath $tray)) {
        Warn "Windows tray script not found: $tray"
        return
    }
    $traySettings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero)
    $trayArgs = "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$tray`" -InstallRoot `"$InstallRoot`""
    $trayAction = New-ScheduledTaskAction -Execute $powershellExe -Argument $trayArgs
    Register-ScheduledTask `
        -TaskName "MemcoreCloudTray" `
        -Description "Time Library tray icon for status and console access." `
        -Action $trayAction `
        -Trigger (New-ScheduledTaskTrigger -AtLogOn) `
        -Principal $principal `
        -Settings $traySettings `
        -Force | Out-Null
    Info "Registered tray scheduled task"
    try {
        Start-ScheduledTask -TaskName "MemcoreCloudTray" -ErrorAction SilentlyContinue
    } catch { }
}

function Smoke-One {
    param(
        [string]$Name,
        [string]$Url,
        [int]$MaxWaitSeconds = 75
    )
    $deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
    $attempt = 0
    $lastError = $null
    while ($true) {
        $attempt += 1
        try {
            $resp = Invoke-WebRequest -Uri $Url -TimeoutSec 6 -UseBasicParsing
            Write-Host "$Name`: ok after $attempt attempt(s) $($resp.Content.Substring(0, [Math]::Min(160, $resp.Content.Length)))"
            return
        } catch {
            $lastError = $_.Exception.Message
            if ((Get-Date) -ge $deadline) {
                Die "$Name smoke failed after $attempt attempt(s) over ${MaxWaitSeconds}s: $lastError"
            }
            Start-Sleep -Seconds 2
        }
    }
}

function Run-Smoke {
    Smoke-One -Name "p3" -Url "http://127.0.0.1:9830/health" -MaxWaitSeconds 90
    Smoke-One -Name "p4" -Url "http://127.0.0.1:9840/health" -MaxWaitSeconds 45
    Smoke-One -Name "p6" -Url "http://127.0.0.1:9850/api/health" -MaxWaitSeconds 60
    Smoke-One -Name "raw" -Url "http://127.0.0.1:9851/health" -MaxWaitSeconds 45
    Smoke-One -Name "dialog" -Url "http://127.0.0.1:9860/health" -MaxWaitSeconds 45
    Run-NativeSmoke
}

function Run-NativeSmoke {
    $nativeSmoke = Join-Path $InstallRoot "tools\windows_native_smoke.ps1"
    if (-not (Test-Path -LiteralPath $nativeSmoke)) {
        Warn "Native Windows smoke script not found: $nativeSmoke"
        return
    }

    $powershellExe = Join-Path $PSHOME "powershell.exe"
    $nativeArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", $nativeSmoke,
        "-InstallRoot", $InstallRoot
    )
    if ($SkipCodex) { $nativeArgs += "-SkipCodex" }

    & $powershellExe @nativeArgs
    if ($LASTEXITCODE -ne 0) {
        Die "Native Windows smoke failed with exit code $LASTEXITCODE"
    }
}

Info "Source: $SourceRoot"
Info "Install root: $InstallRoot"
Install-Files
Ensure-DialogEntryToken
Write-Config
Install-PythonEnv
Install-OpenClawPlugin
Install-HermesPlugin
Install-CodexSkill
Install-CodexMcp
Install-ClaudeCodePreflightHook
Install-ClaudeDesktopMcp
if (-not $NoStart) { Start-Services }
if (-not $NoStart) { Register-WindowsAutostart }
if ((-not $NoStart) -and (-not $NoSmoke)) { Run-Smoke }

Write-Host ""
Write-Host "Time Library Windows full install complete."
Write-Host "Install root: $InstallRoot"
Write-Host "Console: http://127.0.0.1:9850"
Write-Host "Services: p0 watcher, 9830, 9840, 9850, 9851, 9860"
if (-not $NoAutostart) { Write-Host "Guardian: MemcoreCloudGuardianLogon, MemcoreCloudGuardianHealth" }
if ((-not $NoAutostart) -and (-not $NoTray)) { Write-Host "Tray: MemcoreCloudTray" }
Write-Host "Native smoke: powershell -ExecutionPolicy Bypass -File `"$InstallRoot\tools\windows_native_smoke.ps1`" -InstallRoot `"$InstallRoot`""
Write-Host "Codex skill: $CodexSkillStatus"
Write-Host "Codex MCP: $CodexMcpStatus"
Write-Host "Claude Code preflight hook: $ClaudeCodeHookStatus"
Write-Host "Claude Desktop MCP: $ClaudeDesktopStatus"
Write-Host "Hermes skill: $(if ($SkipHermes) { 'skipped' } else { 'time-library' })"
