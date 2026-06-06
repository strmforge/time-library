#Requires -Version 5.1
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\memcore-cloud",
    [switch]$Reinstall,
    [switch]$ResetInstall,
    [switch]$NoStart,
    [switch]$NoSmoke,
    [switch]$NoAutostart,
    [switch]$NoTray,
    [switch]$SkipOpenClaw,
    [switch]$SkipHermes,
    [switch]$SkipCodex,
    [switch]$SkipClaudeDesktop
)

$ErrorActionPreference = "Stop"

function Info($msg) { Write-Host "[yifanchen-windows-install] $msg" }
function Warn($msg) { Write-Host "[yifanchen-windows-install WARNING] $msg" -ForegroundColor Yellow }
function Die($msg) { Write-Error "[yifanchen-windows-install ERROR] $msg"; exit 1 }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$LogDir = Join-Path $InstallRoot "logs"
$NodeName = if ($env:COMPUTERNAME) { $env:COMPUTERNAME } else { "windows-local" }
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$CodexSkillStatus = "pending"
$CodexMcpStatus = "pending"
$ClaudeDesktopStatus = "pending"

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
        "/XD", ".git", ".venv", "__pycache__", ".pytest_cache", "logs", "memory", "zhiyi", "experience_lancedb", "backups", "output",
        "/XF", "*.pyc", ".DS_Store", "._*", ".checkpoint", ".checkpoint_p2.json", "update_history.jsonl",
        "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
    )
    & robocopy @args | Out-Null
    if ($LASTEXITCODE -gt 7) { Die "robocopy failed with exit code $LASTEXITCODE" }
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
    if ((Test-Path $InstallRoot) -and ($Reinstall -or $ResetInstall)) {
        if ($ResetInstall) {
            Info "Removing existing install root"
            Remove-Tree -Path $InstallRoot
        } else {
            $backup = "$InstallRoot.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
            Info "Backing up existing install to $backup"
            Copy-Item -Path $InstallRoot -Destination $backup -Recurse -Force
        }
    }
    Invoke-Robocopy -From $SourceRoot -To $InstallRoot
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
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
    $cfg["_comment"] = "Yifanchen user-level Windows config"
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
        p0_watcher_interval_milliseconds = 250
        p3_recall_port = 9830
        p4_provider_port = 9840
        p6_console_port = 9850
        raw_consumption_gateway_port = 9851
        dialog_entry_port = 9860
    }
    $cfg["integrations"] = @{
        claude_desktop = @{
            raw_ingest = @{
                enabled = $true
                authorization = "user_authorized_local_claude_desktop_parser_to_yifanchen_raw_only"
                write_target = "memcore_raw_only"
                platform_write_allowed = $false
                interval_milliseconds = 250
                limit = 20
            }
        }
        hermes = @{
            model_call = @{
                hermes_provider = "minimax"
                hermes_model = "MiniMax-M2.7"
                source = "memcore-yifanchen"
            }
        }
    }
    Write-Utf8NoBom -Path $cfgPath -Text (($cfg | ConvertTo-Json -Depth 20) + "`n")

    $flagsPath = Join-Path $InstallRoot "config\feature_flags.json"
    $flags = [ordered]@{}
    foreach ($key in @("zhiyi_direct", "zhiyi_inject", "openclaw_rpc", "passthrough", "audit_log")) { $flags[$key] = $true }
    Write-Utf8NoBom -Path $flagsPath -Text (($flags | ConvertTo-Json -Depth 20) + "`n")

    $modelCfgPath = Join-Path $InstallRoot "config\model_config.json"
    $modelCfg = [ordered]@{}
    $modelCfg["version"] = "1.0"
    $modelCfg["recall"] = @{ mode = "off"; substring = @{ table = "experiences" } }
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
    $pluginSrc = Join-Path $InstallRoot "system\openclaw\plugins\memcore-zhiyi-native"
    if (-not (Test-Path $pluginSrc)) { Warn "OpenClaw plugin source not found"; return }
    $openclaw = Get-Command openclaw -ErrorAction SilentlyContinue
    if ($openclaw) {
        & openclaw plugins install --link $pluginSrc | Out-Null
        & openclaw plugins enable memcore-zhiyi-native | Out-Null
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
cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
backup = cfg_path.with_name(cfg_path.name + ".yifanchen-bak." + time.strftime("%Y%m%d%H%M%S"))
shutil.copy2(cfg_path, backup)
plugins = cfg.setdefault("plugins", {})
entries = plugins.setdefault("entries", {})
entry = entries.setdefault("memcore-zhiyi-native", {})
entry["enabled"] = True
base = entry.get("config") if isinstance(entry.get("config"), dict) else {}
base.update({
    "enabled": True,
    "endpointUrl": "http://127.0.0.1:9860/entry/openclaw-before-dispatch",
    "allowedChannels": ["webchat"],
    "enableModelCall": True,
    "forceZhiyiDirect": True,
    "timeoutMs": 120000,
})
entry["config"] = base
load = plugins.setdefault("load", {})
paths = load.setdefault("paths", [])
if isinstance(paths, list) and plugin_src not in paths:
    paths.append(plugin_src)
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
'@
    $tmp = Join-Path $env:TEMP "yifanchen-openclaw-config.py"
    Write-Utf8NoBom -Path $tmp -Text $script
    & $py $tmp $cfgPath $pluginSrc
}

function Install-HermesPlugin {
    if ($SkipHermes) { return }
    $src = Join-Path $InstallRoot "system\hermes\plugins\memcore_yifanchen"
    if (-not (Test-Path $src)) { Warn "Hermes plugin source not found"; return }
    $hermesHome = $HermesHome
    New-Item -ItemType Directory -Force -Path (Join-Path $hermesHome "plugins") | Out-Null
    $dst = Join-Path $hermesHome "plugins\memcore_yifanchen"
    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
    Copy-Item $src $dst -Recurse -Force

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
backup = cfg_path.with_name(cfg_path.name + ".yifanchen-bak." + time.strftime("%Y%m%d%H%M%S"))
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
    memory["provider"] = "memcore_yifanchen"
    plugins = cfg.setdefault("plugins", {})
    enabled = plugins.setdefault("enabled", [])
    if isinstance(enabled, list) and "memcore_yifanchen" not in enabled:
        enabled.append("memcore_yifanchen")
    plugins["memcore_yifanchen"] = {
        **(plugins.get("memcore_yifanchen") if isinstance(plugins.get("memcore_yifanchen"), dict) else {}),
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
  provider: memcore_yifanchen
plugins:
  enabled:
    - memcore_yifanchen
  memcore_yifanchen:
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
    $tmp = Join-Path $env:TEMP "yifanchen-hermes-config.py"
    Write-Utf8NoBom -Path $tmp -Text $script
    & $py $tmp $cfgPath
}

function Install-CodexSkill {
    if ($SkipCodex) {
        $script:CodexSkillStatus = "skipped"
        return
    }
    $src = Join-Path $InstallRoot "system\skills\yifanchen-zhiyi"
    if (-not (Test-Path $src)) {
        Warn "Codex skill source not found: $src"
        $script:CodexSkillStatus = "source not found"
        return
    }
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
    $dst = Join-Path $codexHome "skills\yifanchen-zhiyi"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    if (Test-Path $dst) { Remove-Tree -Path $dst }
    Copy-Item -Path $src -Destination $dst -Recurse -Force
    Info "Codex skill installed: $dst"
    $script:CodexSkillStatus = "yifanchen-zhiyi"
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
    $python = Find-Python
    if (-not $python) {
        Warn "Python not found; skipping Codex MCP registration"
        $script:CodexMcpStatus = "python not found"
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
        & $codexExe mcp remove yifanchen-zhiyi *> $null
    } catch { }
    try {
        & $codexExe mcp add yifanchen-zhiyi `
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
            Info "Codex MCP registered: yifanchen-zhiyi via $bridge"
            $script:CodexMcpStatus = "yifanchen-zhiyi"
        } else {
            Warn "Codex MCP registration failed; Codex users can run: codex mcp add yifanchen-zhiyi -- python $bridge --endpoint http://127.0.0.1:9851/mcp"
            $script:CodexMcpStatus = "registration failed"
        }
    } catch {
        Warn "Codex MCP registration failed; Codex users can run: codex mcp add yifanchen-zhiyi -- python $bridge --endpoint http://127.0.0.1:9851/mcp"
        $script:CodexMcpStatus = "registration failed"
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
    $skillSrc = Join-Path $InstallRoot "system\skills\yifanchen-zhiyi"
    $skillHelper = Join-Path $InstallRoot "tools\install_claude_desktop_skill.py"
    $python = Find-Python
    if (-not $python) {
        Warn "Python not found; skipping Claude Desktop MCP registration"
        $script:ClaudeDesktopStatus = "python not found"
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
        backup = cfg_path.with_suffix(cfg_path.suffix + ".invalid-yifanchen-bak")
        try:
            backup.write_text(cfg_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        except Exception:
            pass
        cfg = {}
servers = cfg.setdefault("mcpServers", {})
servers["yifanchen-zhiyi"] = {
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
    backup = cfg_path.with_suffix(cfg_path.suffix + ".bak-yifanchen")
    if not backup.exists():
        backup.write_text(cfg_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, cfg_path)
print(str(cfg_path))
'@
    $tmp = Join-Path $env:TEMP "yifanchen-claude-desktop-mcp.py"
    Write-Utf8NoBom -Path $tmp -Text $script
    $registered = @()
    foreach ($claudeHome in $candidateHomes) {
        try {
            & $python $tmp $claudeHome $bridge $InstallRoot | Out-Null
            if ((Test-Path $skillHelper) -and (Test-Path $skillSrc)) {
                $skillResult = & $python $skillHelper $claudeHome $skillSrc --json 2>$null
                $skillData = $null
                try {
                    $skillData = $skillResult | ConvertFrom-Json
                } catch { }
                if ($skillData -and ([int]$skillData.installed_count -gt 0)) {
                    Info "Claude Desktop skill updated: yifanchen-zhiyi"
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
        Info "Claude Desktop MCP registered: yifanchen-zhiyi via $bridge"
        $script:ClaudeDesktopStatus = "yifanchen-zhiyi ($($registered.Count) config path(s))"
    } else {
        Warn "Claude Desktop MCP registration failed for all detected config paths"
        $script:ClaudeDesktopStatus = "registration failed"
    }
}

function Start-MemcoreService {
    param([string]$Name, [string]$ArgLine)
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
        "set `"MEMCORE_ROOT=$InstallRoot`"",
        "set `"MEMCORE_INSTALL_ROOT=$InstallRoot`"",
        "set `"PYTHONPATH=$InstallRoot`"",
        "set `"PYTHONIOENCODING=utf-8`"",
        "set `"HERMES_HOME=$HermesHome`""
    )
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
    Start-MemcoreService -Name "dialog-entry" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\dialog_entry_proxy.py')`" --port 9860"
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
        -Description "Memcore Cloud starts the P0 local memory watcher at user logon." `
        -Action $guardianAction `
        -Trigger $logonTrigger `
        -Principal $principal `
        -Settings $guardianSettings `
        -Force | Out-Null

    $healthTrigger = New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 1) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    Register-ScheduledTask `
        -TaskName "MemcoreCloudGuardianHealth" `
        -Description "Memcore Cloud periodically checks watcher health and backfills missed local records." `
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
        -Description "Memcore Cloud tray icon for status and console access." `
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
    param([string]$Name, [string]$Url)
    try {
        $resp = Invoke-WebRequest -Uri $Url -TimeoutSec 6 -UseBasicParsing
        Write-Host "$Name`: ok $($resp.Content.Substring(0, [Math]::Min(160, $resp.Content.Length)))"
    } catch {
        Die "$Name smoke failed: $($_.Exception.Message)"
    }
}

function Run-Smoke {
    Start-Sleep -Seconds 5
    Smoke-One -Name "p3" -Url "http://127.0.0.1:9830/health"
    Smoke-One -Name "p4" -Url "http://127.0.0.1:9840/health"
    Smoke-One -Name "p6" -Url "http://127.0.0.1:9850/api/health"
    Smoke-One -Name "raw" -Url "http://127.0.0.1:9851/health"
    Smoke-One -Name "dialog" -Url "http://127.0.0.1:9860/health"
    Run-NativeSmoke
}

function Run-NativeSmoke {
    $nativeSmoke = Join-Path $InstallRoot "tools\windows_native_smoke.ps1"
    if (-not (Test-Path -LiteralPath $nativeSmoke)) {
        Warn "Native Windows smoke script not found: $nativeSmoke"
        return
    }

    $powershellExe = Join-Path $PSHOME "powershell.exe"
    $nativeArgs = @("-ExecutionPolicy", "Bypass", "-File", $nativeSmoke)
    if ($SkipCodex) { $nativeArgs += "-SkipCodex" }

    & $powershellExe @nativeArgs
    if ($LASTEXITCODE -ne 0) {
        Die "Native Windows smoke failed with exit code $LASTEXITCODE"
    }
}

Info "Source: $SourceRoot"
Info "Install root: $InstallRoot"
Install-Files
Write-Config
Install-PythonEnv
Install-OpenClawPlugin
Install-HermesPlugin
Install-CodexSkill
Install-CodexMcp
Install-ClaudeDesktopMcp
if (-not $NoStart) { Start-Services }
if (-not $NoStart) { Register-WindowsAutostart }
if ((-not $NoStart) -and (-not $NoSmoke)) { Run-Smoke }

Write-Host ""
Write-Host "Yifanchen Windows full install complete."
Write-Host "Install root: $InstallRoot"
Write-Host "Console: http://127.0.0.1:9850"
Write-Host "Services: p0 watcher, 9830, 9840, 9850, 9851, 9860"
if (-not $NoAutostart) { Write-Host "Guardian: MemcoreCloudGuardianLogon, MemcoreCloudGuardianHealth" }
if ((-not $NoAutostart) -and (-not $NoTray)) { Write-Host "Tray: MemcoreCloudTray" }
Write-Host "Native smoke: powershell -ExecutionPolicy Bypass -File `"$InstallRoot\tools\windows_native_smoke.ps1`""
Write-Host "Codex skill: $CodexSkillStatus"
Write-Host "Codex MCP: $CodexMcpStatus"
Write-Host "Claude Desktop MCP: $ClaudeDesktopStatus"
