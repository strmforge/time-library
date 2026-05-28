#Requires -Version 5.1
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\memcore-cloud",
    [switch]$Reinstall,
    [switch]$ResetInstall,
    [switch]$NoStart,
    [switch]$NoSmoke,
    [switch]$SkipOpenClaw,
    [switch]$SkipHermes
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

function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($exe) { return $exe.Source }
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
        "/XF", "*.pyc", ".DS_Store", "._*",
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
        "*$InstallRoot\runtime\*.cmd*"
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
        raw_memory_subpath = "openclaw/$NodeName"
    }
    $cfg["services"] = @{
        p0_watcher_enabled = $true
        p3_recall_port = 9830
        p4_provider_port = 9840
        p6_console_port = 9850
        raw_consumption_gateway_port = 9851
        dialog_entry_port = 9860
    }
    $cfg["integrations"] = @{
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
    if (-not (Test-Path $venv)) { & $python -m venv $venv }
    $venvPython = Join-Path $venv "Scripts\python.exe"
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
        "memory_scope": "raw_pool",
        "computer_name": "",
        "limit": 3,
        "excerpt_chars": 500,
        "context_chars": 2400,
        "timeout_seconds": 5,
        "include_session_id": False,
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
    memory_scope: raw_pool
    computer_name: ""
    limit: 3
    excerpt_chars: 500
    context_chars: 2400
    timeout_seconds: 5
    include_session_id: false
"""
    cfg_path.write_text(existing.rstrip() + "\n" + block, encoding="utf-8")
'@
    $tmp = Join-Path $env:TEMP "yifanchen-hermes-config.py"
    Write-Utf8NoBom -Path $tmp -Text $script
    & $py $tmp $cfgPath
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
}

Info "Source: $SourceRoot"
Info "Install root: $InstallRoot"
Install-Files
Write-Config
Install-PythonEnv
Install-OpenClawPlugin
Install-HermesPlugin
if (-not $NoStart) { Start-Services }
if ((-not $NoStart) -and (-not $NoSmoke)) { Run-Smoke }

Write-Host ""
Write-Host "Yifanchen Windows full install complete."
Write-Host "Install root: $InstallRoot"
Write-Host "Console: http://127.0.0.1:9850"
Write-Host "Services: p0 watcher, 9830, 9840, 9850, 9851, 9860"
