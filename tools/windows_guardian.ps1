#Requires -Version 5.1
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\time-library",
    [switch]$StartWatcher,
    [switch]$Backfill,
    [switch]$Json,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$RuntimeDir = Join-Path $InstallRoot "runtime"
$LogDir = Join-Path $InstallRoot "logs"
$StatusPath = Join-Path $RuntimeDir "guardian-status.json"
$GuardianLog = Join-Path $LogDir "guardian.out.log"
$GuardianErr = Join-Path $LogDir "guardian.err.log"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$DialogEntryToken = if ($env:MEMCORE_DIALOG_ENTRY_TOKEN) { $env:MEMCORE_DIALOG_ENTRY_TOKEN } else { "" }

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Now-Iso {
    return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function New-Report {
    return [ordered]@{
        ok = $true
        tool = "windows_guardian"
        install_root = $InstallRoot
        generated_at = Now-Iso
        start_watcher_requested = [bool]$StartWatcher
        backfill_requested = [bool]$Backfill
        checks = @()
    }
}

$Report = New-Report

function Add-Check {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Detail = "",
        [object]$Data = $null
    )
    $entry = [ordered]@{
        name = $Name
        ok = $Ok
        detail = $Detail
    }
    if ($null -ne $Data) { $entry["data"] = $Data }
    $script:Report.checks += $entry
    if (-not $Ok) { $script:Report.ok = $false }
    if (-not $Quiet -and -not $Json) {
        $mark = if ($Ok) { "ok" } else { "fail" }
        Write-Host ("[{0}] {1} {2}" -f $mark, $Name, $Detail)
    }
}

function ConvertFrom-JsonOutput {
    param([string]$Text)
    $trimmed = $Text.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        throw "empty JSON output"
    }
    try {
        return $trimmed | ConvertFrom-Json
    } catch { }

    $start = -1
    $depth = 0
    $inString = $false
    $escaped = $false
    for ($i = 0; $i -lt $Text.Length; $i++) {
        $ch = $Text[$i]
        if ($start -lt 0) {
            if ($ch -eq "{") {
                $start = $i
                $depth = 1
            }
            continue
        }
        if ($inString) {
            if ($escaped) {
                $escaped = $false
            } elseif ($ch -eq "\") {
                $escaped = $true
            } elseif ($ch -eq '"') {
                $inString = $false
            }
            continue
        }
        if ($ch -eq '"') {
            $inString = $true
        } elseif ($ch -eq "{") {
            $depth += 1
        } elseif ($ch -eq "}") {
            $depth -= 1
            if ($depth -eq 0) {
                $candidate = $Text.Substring($start, $i - $start + 1)
                return ($candidate | ConvertFrom-Json)
            }
        }
    }
    throw "no balanced JSON object found"
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

function Get-FileSha256 {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    try {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    } catch {
        return ""
    }
}

function Get-ServiceHashPath {
    param([string]$Name)
    return (Join-Path $RuntimeDir "$Name.source.sha256")
}

function Get-StoredServiceHash {
    param([string]$Name)
    $path = Get-ServiceHashPath -Name $Name
    if (-not (Test-Path -LiteralPath $path)) { return "" }
    try {
        return (Get-Content -LiteralPath $path -Raw -Encoding UTF8).Trim().ToLowerInvariant()
    } catch {
        return ""
    }
}

function Set-StoredServiceHash {
    param([string]$Name, [string]$Hash)
    if ([string]::IsNullOrWhiteSpace($Hash)) { return }
    Write-Utf8NoBom -Path (Get-ServiceHashPath -Name $Name) -Text ($Hash + "`n")
}

function Get-DialogEntryHost {
    $cfgPath = Join-Path $InstallRoot "config\memcore.json"
    if (-not (Test-Path -LiteralPath $cfgPath)) { return "127.0.0.1" }
    try {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.services -and $cfg.services.dialog_entry_host) {
            $dialogHost = [string]$cfg.services.dialog_entry_host
            if (-not [string]::IsNullOrWhiteSpace($dialogHost)) { return $dialogHost.Trim() }
        }
    } catch { }
    return "127.0.0.1"
}

function Get-DialogEntryEndpointUrl {
    $cfgPath = Join-Path $InstallRoot "config\memcore.json"
    if (-not (Test-Path -LiteralPath $cfgPath)) { return "" }
    try {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.services -and $cfg.services.dialog_entry_endpoint_url) {
            $url = [string]$cfg.services.dialog_entry_endpoint_url
            if (-not [string]::IsNullOrWhiteSpace($url)) { return $url.Trim() }
        }
    } catch { }
    return ""
}

function Test-DialogEntryNeedsToken {
    $dialogHost = Get-DialogEntryHost
    if (($dialogHost -ne "127.0.0.1") -and ($dialogHost -ne "localhost") -and ($dialogHost -ne "::1")) {
        return $true
    }
    $endpoint = Get-DialogEntryEndpointUrl
    if ([string]::IsNullOrWhiteSpace($endpoint)) { return $false }
    return ($endpoint -notmatch "127\.0\.0\.1|localhost|\[::1\]")
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
    if (-not (Test-DialogEntryNeedsToken)) { return $script:DialogEntryToken }
    $tokenPath = Join-Path $RuntimeDir "dialog_entry_token"
    if ([string]::IsNullOrWhiteSpace($script:DialogEntryToken) -and (Test-Path -LiteralPath $tokenPath)) {
        $script:DialogEntryToken = (Get-Content -LiteralPath $tokenPath -Raw -Encoding UTF8).Trim()
    }
    if ([string]::IsNullOrWhiteSpace($script:DialogEntryToken)) {
        $script:DialogEntryToken = New-DialogEntryTokenValue
    }
    Write-Utf8NoBom -Path $tokenPath -Text ($script:DialogEntryToken + "`n")
    Add-Check -Name "dialog_entry_token_file" -Ok $true -Detail "present"
    return $script:DialogEntryToken
}

function Test-ServiceSourceChanged {
    param([string]$Name, [string]$Path)
    $current = Get-FileSha256 -Path $Path
    if ([string]::IsNullOrWhiteSpace($current)) { return $false }
    $stored = Get-StoredServiceHash -Name $Name
    if ([string]::IsNullOrWhiteSpace($stored)) { return $true }
    return ($stored -ne $current)
}

function Write-GuardianStatus {
    $jsonText = $script:Report | ConvertTo-Json -Depth 12
    $shouldWriteStatus = $true
    if (Test-Path -LiteralPath $StatusPath) {
        try {
            $existing = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($existing.generated_at -and ([string]$existing.generated_at -gt [string]$script:Report.generated_at)) {
                $shouldWriteStatus = $false
            }
        } catch { }
    }
    if ($shouldWriteStatus) {
        Set-Content -LiteralPath $StatusPath -Value ($jsonText + "`n") -Encoding UTF8
    }
    Add-Content -LiteralPath $GuardianLog -Value ((Now-Iso) + " " + ($script:Report | ConvertTo-Json -Depth 12 -Compress)) -Encoding UTF8
    if ($Json) { Write-Output $jsonText }
}

function Fail-Guardian {
    param([string]$Name, [string]$Detail)
    Add-Check -Name $Name -Ok $false -Detail $Detail
    Write-GuardianStatus
    exit 1
}

function Get-VenvPython {
    $python = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        Fail-Guardian -Name "venv_python" -Detail "missing: $python"
    }
    return $python
}

function Get-ProcessTree {
    param([object[]]$Processes, [int[]]$RootProcessIds)
    $ids = New-Object "System.Collections.Generic.HashSet[int]"
    $queue = New-Object "System.Collections.Generic.Queue[int]"
    foreach ($rootPid in $RootProcessIds) {
        if ($ids.Add([int]$rootPid)) { $queue.Enqueue([int]$rootPid) }
    }
    while ($queue.Count -gt 0) {
        $parent = $queue.Dequeue()
        foreach ($proc in $Processes) {
            if ([int]$proc.ParentProcessId -eq $parent) {
                if ($ids.Add([int]$proc.ProcessId)) {
                    $queue.Enqueue([int]$proc.ProcessId)
                }
            }
        }
    }
    return $ids
}

function Get-ProcessStartTimeUtc {
    param([object]$Process)
    try {
        return [System.Management.ManagementDateTimeConverter]::ToDateTime([string]$Process.CreationDate).ToUniversalTime()
    } catch {
        return $null
    }
}

function Stop-ProcessTreeByRoots {
    param([object[]]$RootProcesses)
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $rootIds = @($RootProcesses | ForEach-Object { [int]$_.ProcessId })
    if ($rootIds.Count -eq 0) { return }
    $treeIds = Get-ProcessTree -Processes $processes -RootProcessIds $rootIds
    $ordered = @($processes | Where-Object { $treeIds.Contains([int]$_.ProcessId) } | Sort-Object ProcessId -Descending)
    foreach ($proc in $ordered) {
        try {
            Stop-Process -Id ([int]$proc.ProcessId) -Force -ErrorAction SilentlyContinue
        } catch { }
    }
}

function Format-ProcessIdList {
    param([int[]]$ProcessIds)
    $ids = @($ProcessIds | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
    if ($ids.Count -eq 0) { return "" }
    return ($ids -join ",")
}

function Get-ValidPidFileProcessIds {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return @() }
    try {
        $raw = (Get-Content -LiteralPath $Path -Raw -Encoding UTF8).Trim()
        $parsedPid = 0
        if ([int]::TryParse($raw, [ref]$parsedPid) -and $parsedPid -gt 0) {
            $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = " + [string]$parsedPid) -ErrorAction SilentlyContinue
            if ($null -ne $proc) { return @([int]$parsedPid) }
        }
    } catch { }
    return @()
}

function Get-PortListenerProcessIds {
    param([int]$Port)
    if ($Port -le 0) { return @() }
    $ids = @()
    try {
        $ids += @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | ForEach-Object {
            [int]$_.OwningProcess
        })
    } catch {
        try {
            $lines = @(netstat -ano | Select-String ":$Port " | Select-String "LISTENING")
            foreach ($line in $lines) {
                $parts = @(([string]$line).Trim() -split "\s+")
                if ($parts.Count -gt 0) {
                    $parsedPid = 0
                    if ([int]::TryParse($parts[$parts.Count - 1], [ref]$parsedPid)) {
                        $ids += [int]$parsedPid
                    }
                }
            }
        } catch { }
    }
    return @($ids | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
}

function Get-PortListenerProcessSummaries {
    param([int]$Port)
    $ids = @(Get-PortListenerProcessIds -Port $Port)
    if ($ids.Count -eq 0) { return @() }
    $summaries = @()
    foreach ($listenerPid in @($ids)) {
        $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = " + [string]$listenerPid) -ErrorAction SilentlyContinue
        if ($null -eq $proc) {
            $summaries += [ordered]@{
                pid = [int]$listenerPid
                name = "unknown"
                parent_pid = 0
                command_has_install_root = $false
                is_wslrelay = $false
            }
            continue
        }
        $cmd = [string]$proc.CommandLine
        $summaries += [ordered]@{
            pid = [int]$proc.ProcessId
            name = [string]$proc.Name
            parent_pid = [int]$proc.ParentProcessId
            command_has_install_root = (Test-CommandLineHasInstallRoot -CommandLine $cmd)
            is_wslrelay = ([string]$proc.Name -ieq "wslrelay.exe")
        }
    }
    return @($summaries)
}

function Add-PortOwnerDiagnostic {
    param(
        [string]$Name,
        [int]$Port
    )
    if ($Port -le 0) { return }
    $owners = @(Get-PortListenerProcessSummaries -Port $Port)
    if ($owners.Count -eq 0) {
        Add-Check `
            -Name ($Name + "_port_owner") `
            -Ok $true `
            -Detail ("no listener owner found for " + [string]$Port)
        return
    }
    $summary = @($owners | ForEach-Object {
        ([string]$_.name) + "#" + ([string]$_.pid)
    }) -join ", "
    Add-Check `
        -Name ($Name + "_port_owner") `
        -Ok $true `
        -Detail ("listener owner(s) for " + [string]$Port + ": " + $summary) `
        -Data ([ordered]@{
            port = $Port
            owners = @($owners)
            any_install_root_owner = @($owners | Where-Object { $_.command_has_install_root }).Count -gt 0
            any_wslrelay_owner = @($owners | Where-Object { $_.is_wslrelay }).Count -gt 0
        })
}

function Test-ProcessTreeContainsAny {
    param(
        [object]$TreeIds,
        [int[]]$ProcessIds
    )
    foreach ($candidatePid in @($ProcessIds)) {
        if ($candidatePid -gt 0 -and $TreeIds.Contains([int]$candidatePid)) { return $true }
    }
    return $false
}

function Get-RootProcessesForMatches {
    param(
        [object[]]$AllProcesses,
        [object[]]$MatchingProcesses
    )
    $matchIds = @{}
    foreach ($proc in @($MatchingProcesses)) {
        $matchIds[[int]$proc.ProcessId] = $true
    }
    $roots = @()
    foreach ($proc in @($MatchingProcesses)) {
        $parentId = 0
        try { $parentId = [int]$proc.ParentProcessId } catch { $parentId = 0 }
        if (-not $matchIds.ContainsKey($parentId)) {
            $roots += $proc
        }
    }
    return @($roots | Sort-Object ProcessId -Unique)
}

function Select-CanonicalServiceRoot {
    param(
        [object[]]$AllProcesses,
        [object[]]$RootProcesses,
        [int[]]$PreferredProcessIds = @(),
        [int[]]$PidFileProcessIds = @()
    )
    if ($RootProcesses.Count -eq 0) { return $null }
    $venvPython = Normalize-PathText -Text (Join-Path $InstallRoot ".venv\Scripts\python.exe")
    $ranked = @()
    foreach ($root in @($RootProcesses)) {
        $treeIds = Get-ProcessTree -Processes $AllProcesses -RootProcessIds @([int]$root.ProcessId)
        $treeProcesses = @($AllProcesses | Where-Object { $treeIds.Contains([int]$_.ProcessId) })
        $score = 0
        if (Test-ProcessTreeContainsAny -TreeIds $treeIds -ProcessIds $PreferredProcessIds) {
            $score += 10000
        }
        if (Test-ProcessTreeContainsAny -TreeIds $treeIds -ProcessIds $PidFileProcessIds) {
            $score += 5000
        }
        foreach ($proc in $treeProcesses) {
            $cmd = Normalize-PathText -Text ([string]$proc.CommandLine)
            if (-not [string]::IsNullOrWhiteSpace($cmd) -and $cmd.Contains($venvPython)) {
                $score += 1000
                break
            }
        }
        foreach ($proc in $treeProcesses) {
            $cmd = [string]$proc.CommandLine
            if ($cmd -match "\.cmd") {
                $score += 100
                break
            }
        }
        $start = Get-ProcessStartTimeUtc -Process $root
        if ($null -eq $start) { $start = [DateTime]::MinValue }
        $ranked += [pscustomobject]@{
            Root = $root
            Score = $score
            Start = $start
        }
    }
    $selected = @($ranked | Sort-Object `
        @{Expression = { $_.Score }; Descending = $true}, `
        @{Expression = { $_.Start }; Descending = $true}, `
        @{Expression = { [int]$_.Root.ProcessId }; Descending = $false} |
        Select-Object -First 1)
    if ($selected.Count -eq 0) { return $null }
    return $selected[0].Root
}

function Stop-DuplicateServiceProcessRoots {
    param(
        [string]$Name,
        [object[]]$MatchingProcesses,
        [int[]]$PreferredProcessIds = @(),
        [string]$PidPath = ""
    )
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $roots = @(Get-RootProcessesForMatches -AllProcesses $processes -MatchingProcesses $MatchingProcesses)
    if ($roots.Count -le 1) { return @($MatchingProcesses) }
    $pidFileIds = @()
    if (-not [string]::IsNullOrWhiteSpace($PidPath)) {
        $pidFileIds = @(Get-ValidPidFileProcessIds -Path $PidPath)
    }
    $keep = Select-CanonicalServiceRoot `
        -AllProcesses $processes `
        -RootProcesses $roots `
        -PreferredProcessIds $PreferredProcessIds `
        -PidFileProcessIds $pidFileIds
    if ($null -eq $keep) { return @($MatchingProcesses) }

    $keepId = [int]$keep.ProcessId
    $dropRoots = @($roots | Where-Object { [int]$_.ProcessId -ne $keepId })
    $dropIds = @($dropRoots | ForEach-Object { [int]$_.ProcessId })
    if ($dropRoots.Count -gt 0) {
        Stop-ProcessTreeByRoots -RootProcesses $dropRoots
    }
    Add-Check `
        -Name ($Name + "_duplicate_processes") `
        -Ok $true `
        -Detail ("kept root PID " + [string]$keepId + "; stopped roots " + (Format-ProcessIdList -ProcessIds $dropIds)) `
        -Data ([ordered]@{
            kept_root_pid = $keepId
            stopped_root_pids = @($dropIds)
            preferred_pids = @($PreferredProcessIds)
            pid_file_pids = @($pidFileIds)
        })
    Start-Sleep -Milliseconds 500
    return @()
}

function Normalize-PathText {
    param([string]$Text)
    $normalized = ([string]$Text).Replace("\", "/").ToLowerInvariant()
    return [regex]::Replace($normalized, "/+", "/")
}

function Test-CommandLineHasInstallRoot {
    param([string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    $normalizedCommand = Normalize-PathText -Text $CommandLine
    $normalizedRoot = Normalize-PathText -Text $InstallRoot
    return $normalizedCommand.Contains($normalizedRoot)
}

function Test-P0WatcherCommandLine {
    param([string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    if (-not (Test-CommandLineHasInstallRoot -CommandLine $CommandLine)) { return $false }
    if ($CommandLine -match "p0-watcher\.cmd") { return $true }
    return (($CommandLine -match "memcore-cloud\.py") -and ($CommandLine -match "--watch"))
}

function Test-PortListening {
    param([int]$Port)
    if ($Port -le 0) { return $true }
    try {
        $conn = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
        return ($conn.Count -gt 0)
    } catch {
        $lines = @(netstat -ano | Select-String ":$Port " | Select-String "LISTENING")
        return ($lines.Count -gt 0)
    }
}

function Test-MemcoreServicePortReady {
    param(
        [string]$Name,
        [int]$Port
    )
    if (-not (Test-PortListening -Port $Port)) { return $false }
    if (($Name -ne "raw-gateway") -or ($Port -le 0)) { return $true }
    try {
        $health = Invoke-RestMethod -Uri ("http://127.0.0.1:" + [string]$Port + "/health") -TimeoutSec 5
        return (
            ($health.ok -eq $true) -and
            ([string]$health.service -eq "raw_consumption_gateway") -and
            ($health.preflight -eq $true) -and
            (Test-RawGatewayHealthVersion -Health $health) -and
            (Test-RawGatewayHealthIdentity -Health $health)
        )
    } catch {
        return $false
    }
}

function Get-InstallVersion {
    $versionPath = Join-Path $InstallRoot "VERSION"
    if (-not (Test-Path -LiteralPath $versionPath)) { return "" }
    try {
        return (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8).Trim()
    } catch {
        return ""
    }
}

function Test-RawGatewayHealthVersion {
    param([object]$Health)
    if ($null -eq $Health) { return $false }
    $expectedVersion = Get-InstallVersion
    $actualVersion = [string]$Health.version
    if ([string]::IsNullOrWhiteSpace($expectedVersion)) { return $false }
    if ([string]::IsNullOrWhiteSpace($actualVersion)) { return $false }
    return ($actualVersion.Trim() -eq $expectedVersion)
}

function Test-RawGatewayHealthIdentity {
    param([object]$Health)
    if ($null -eq $Health) { return $false }
    $scriptPath = Join-Path $InstallRoot "src\raw_consumption_gateway.py"
    $expectedHash = Get-FileSha256 -Path $scriptPath
    $sourcePath = [string]$Health.source_path
    $sourceHash = ([string]$Health.source_sha256).ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($sourcePath)) { return $false }
    if ([string]::IsNullOrWhiteSpace($sourceHash)) { return $false }
    if ([string]::IsNullOrWhiteSpace($expectedHash)) { return $false }
    if ((Normalize-PathText -Text $sourcePath) -ne (Normalize-PathText -Text $scriptPath)) { return $false }
    return ($sourceHash -eq $expectedHash)
}

function Test-MemcoreServiceCommandLine {
    param(
        [string]$CommandLine,
        [string]$Name,
        [string]$ScriptName
    )
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    if (-not (Test-CommandLineHasInstallRoot -CommandLine $CommandLine)) { return $false }
    if ($CommandLine -match ([regex]::Escape("$Name.cmd"))) { return $true }
    if ($CommandLine -match ([regex]::Escape($ScriptName))) { return $true }
    return $false
}

function Get-MemcoreServiceProcesses {
    param(
        [string]$Name,
        [string]$ScriptName
    )
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    return @($processes | Where-Object {
        Test-MemcoreServiceCommandLine `
            -CommandLine ([string]$_.CommandLine) `
            -Name $Name `
            -ScriptName $ScriptName
    })
}

function Get-P0WatcherTree {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $roots = @($processes | Where-Object {
        Test-P0WatcherCommandLine -CommandLine ([string]$_.CommandLine)
    })
    if ($roots.Count -eq 0) { return @() }
    $treeIds = Get-ProcessTree -Processes $processes -RootProcessIds @($roots | ForEach-Object { [int]$_.ProcessId })
    return @($processes | Where-Object { $treeIds.Contains([int]$_.ProcessId) })
}

function Get-P0WatcherProcesses {
    $tree = @(Get-P0WatcherTree)
    return @($tree | Where-Object {
        Test-P0WatcherCommandLine -CommandLine ([string]$_.CommandLine)
    })
}

function Test-ProcessesOlderThanFile {
    param(
        [object[]]$Processes,
        [string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    if ($Processes.Count -eq 0) { return $false }
    $mtime = (Get-Item -LiteralPath $Path).LastWriteTimeUtc
    foreach ($proc in $Processes) {
        $start = Get-ProcessStartTimeUtc -Process $proc
        if ($null -ne $start -and $start -lt $mtime) {
            return $true
        }
    }
    return $false
}

function Ensure-P0WatcherCommand {
    $cmdPath = Join-Path $RuntimeDir "p0-watcher.cmd"
    $python = Get-VenvPython
    $watcher = Join-Path $InstallRoot "src\memcore-cloud.py"
    if (-not (Test-Path -LiteralPath $watcher)) {
        Fail-Guardian -Name "watcher_script" -Detail "missing: $watcher"
    }
    $out = Join-Path $LogDir "p0-watcher.out.log"
    $err = Join-Path $LogDir "p0-watcher.err.log"
    $lines = @(
        "@echo off",
        "cd /d `"$InstallRoot`"",
        "set `"MEMCORE_ROOT=$InstallRoot`"",
        "set `"MEMCORE_INSTALL_ROOT=$InstallRoot`"",
        "set `"PYTHONPATH=$InstallRoot`"",
        "set `"PYTHONIOENCODING=utf-8`"",
        "set `"MEMCORE_WATCHER_RESOURCE_PROFILE=light`"",
        "set `"MEMCORE_WATCHER_SOURCE_DEFAULT=codex`"",
        "set `"MEMCORE_WATCHER_INTERVAL_MS=5000`"",
        "`"$python`" -u `"$watcher`" --watch 1>>`"$out`" 2>>`"$err`""
    )
    Write-Utf8NoBom -Path $cmdPath -Text (($lines -join "`r`n") + "`r`n")
    Add-Check -Name "p0_watcher_cmd_refreshed" -Ok $true -Detail $cmdPath
    return $cmdPath
}

function Ensure-MemcoreServiceCommand {
    param(
        [string]$Name,
        [string]$ArgLine,
        [switch]$IncludeDialogEntryToken
    )
    $cmdPath = Join-Path $RuntimeDir "$Name.cmd"
    $python = Get-VenvPython
    $out = Join-Path $LogDir "$Name.out.log"
    $err = Join-Path $LogDir "$Name.err.log"
    $lines = @(
        "@echo off",
        "cd /d `"$InstallRoot`"",
        "set `"MEMCORE_ROOT=$InstallRoot`"",
        "set `"MEMCORE_INSTALL_ROOT=$InstallRoot`"",
        "set `"PYTHONPATH=$InstallRoot`"",
        "set `"PYTHONIOENCODING=utf-8`"",
        "set `"HERMES_HOME=$HermesHome`""
    )
    if ($IncludeDialogEntryToken -and $DialogEntryToken) {
        $lines += "set `"MEMCORE_DIALOG_ENTRY_TOKEN=$DialogEntryToken`""
    }
    $lines += "`"$python`" $ArgLine 1>>`"$out`" 2>>`"$err`""
    Write-Utf8NoBom -Path $cmdPath -Text (($lines -join "`r`n") + "`r`n")
    Add-Check -Name ($Name + "_cmd_refreshed") -Ok $true -Detail $cmdPath
    return $cmdPath
}

function Start-HiddenCommandProcess {
    param([string]$CmdPath)
    $command = "$env:ComSpec /c `"`"$CmdPath`"`""
    $startup = ([WMIClass]"Win32_ProcessStartup").CreateInstance()
    $startup.ShowWindow = 0
    $result = ([WMIClass]"Win32_Process").Create($command, $InstallRoot, $startup)
    if ($result.ReturnValue -ne 0) {
        Fail-Guardian -Name "process_start" -Detail ("WMI create failed for " + $CmdPath + " return=" + [string]$result.ReturnValue)
    }
    return [int]$result.ProcessId
}

function Start-P0WatcherIfMissing {
    $running = Get-P0WatcherProcesses
    $watcher = Join-Path $InstallRoot "src\memcore-cloud.py"
    if ($running.Count -gt 1) {
        Stop-DuplicateServiceProcessRoots `
            -Name "p0_watcher" `
            -MatchingProcesses $running `
            -PidPath (Join-Path $RuntimeDir "p0-watcher.pid") | Out-Null
        $running = Get-P0WatcherProcesses
    }
    if (
        (Test-ProcessesOlderThanFile -Processes $running -Path $watcher) -or
        (($running.Count -gt 0) -and (Test-ServiceSourceChanged -Name "p0-watcher" -Path $watcher))
    ) {
        Stop-ProcessTreeByRoots -RootProcesses $running
        Add-Check -Name "p0_watcher_restart" -Ok $true -Detail "source file newer than running process or source hash changed"
        $running = @()
    }
    if ($running.Count -gt 0) {
        Set-StoredServiceHash -Name "p0-watcher" -Hash (Get-FileSha256 -Path $watcher)
        Add-Check -Name "p0_watcher_process" -Ok $true -Detail ("already running PID " + [string]$running[0].ProcessId)
        return
    }
    $cmdPath = Ensure-P0WatcherCommand
    $rootPid = Start-HiddenCommandProcess -CmdPath $cmdPath
    Set-Content -LiteralPath (Join-Path $RuntimeDir "p0-watcher.pid") -Value ([string]$rootPid) -Encoding ASCII
    $after = @()
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Seconds 1
        $after = @(Get-P0WatcherProcesses)
        if ($after.Count -gt 0) { break }
    }
    if ($after.Count -eq 0) {
        Fail-Guardian -Name "p0_watcher_start" -Detail "start attempted but watcher process was not found"
    }
    Set-StoredServiceHash -Name "p0-watcher" -Hash (Get-FileSha256 -Path $watcher)
    Add-Check -Name "p0_watcher_start" -Ok $true -Detail ("started PID " + [string]$after[0].ProcessId)
}

function Start-MemcoreServiceIfMissing {
    param(
        [string]$Name,
        [string]$ScriptName,
        [string]$ArgLine,
        [int]$Port = 0,
        [switch]$IncludeDialogEntryToken
    )
    $scriptPath = Join-Path $InstallRoot ("src\" + $ScriptName)
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Fail-Guardian -Name ($Name + "_script") -Detail "missing: $scriptPath"
    }

    $cmdPath = Ensure-MemcoreServiceCommand `
        -Name $Name `
        -ArgLine $ArgLine `
        -IncludeDialogEntryToken:$IncludeDialogEntryToken
    $running = @(Get-MemcoreServiceProcesses -Name $Name -ScriptName $ScriptName)
    if ($running.Count -gt 1) {
        Stop-DuplicateServiceProcessRoots `
            -Name $Name `
            -MatchingProcesses $running `
            -PreferredProcessIds @(Get-PortListenerProcessIds -Port $Port) `
            -PidPath (Join-Path $RuntimeDir "$Name.pid") | Out-Null
        $running = @(Get-MemcoreServiceProcesses -Name $Name -ScriptName $ScriptName)
    }
    if (
        (Test-ProcessesOlderThanFile -Processes $running -Path $scriptPath) -or
        (($running.Count -gt 0) -and (Test-ServiceSourceChanged -Name $Name -Path $scriptPath))
    ) {
        Stop-ProcessTreeByRoots -RootProcesses $running
        Add-Check -Name ($Name + "_restart") -Ok $true -Detail "source file newer than running process or source hash changed"
        $running = @()
    }
    $portReady = Test-MemcoreServicePortReady -Name $Name -Port $Port
    if (($running.Count -gt 0) -and (-not $portReady) -and ($Port -gt 0)) {
        Add-PortOwnerDiagnostic -Name $Name -Port $Port
        Stop-ProcessTreeByRoots -RootProcesses $running
        Add-Check -Name ($Name + "_restart") -Ok $true -Detail ("port health check failed or wrong owner: " + [string]$Port)
        $running = @()
    }
    if (($running.Count -gt 0) -and $portReady) {
        Set-StoredServiceHash -Name $Name -Hash (Get-FileSha256 -Path $scriptPath)
        Add-Check -Name ($Name + "_process") -Ok $true -Detail ("already running PID " + [string]$running[0].ProcessId)
        if ($Port -gt 0) {
            Add-Check -Name ($Name + "_port") -Ok $true -Detail ("listening " + [string]$Port)
        }
        return
    }

    $rootPid = Start-HiddenCommandProcess -CmdPath $cmdPath
    Set-Content -LiteralPath (Join-Path $RuntimeDir "$Name.pid") -Value ([string]$rootPid) -Encoding ASCII
    $after = @()
    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        $after = @(Get-MemcoreServiceProcesses -Name $Name -ScriptName $ScriptName)
        $ready = Test-MemcoreServicePortReady -Name $Name -Port $Port
        if (($after.Count -gt 0) -and $ready) { break }
    }
    if ($after.Count -eq 0) {
        Fail-Guardian -Name ($Name + "_start") -Detail "start attempted but process was not found"
    }
    if (-not $ready) {
        Add-PortOwnerDiagnostic -Name $Name -Port $Port
        Fail-Guardian -Name ($Name + "_port") -Detail ("start attempted but port is not listening: " + [string]$Port)
    }
    Set-StoredServiceHash -Name $Name -Hash (Get-FileSha256 -Path $scriptPath)
    Add-Check -Name ($Name + "_start") -Ok $true -Detail ("started PID " + [string]$after[0].ProcessId)
    if ($Port -gt 0) {
        Add-Check -Name ($Name + "_port") -Ok $true -Detail ("listening " + [string]$Port)
    }
}

function Start-RuntimeServicesIfMissing {
    $env:MEMCORE_ROOT = $InstallRoot
    $env:MEMCORE_INSTALL_ROOT = $InstallRoot
    $env:PYTHONPATH = $InstallRoot
    $env:PYTHONIOENCODING = "utf-8"
    $env:HERMES_HOME = $HermesHome
    $script:DialogEntryToken = Ensure-DialogEntryToken
    $dialogEntryHost = Get-DialogEntryHost

    Start-MemcoreServiceIfMissing `
        -Name "p3-recall" `
        -ScriptName "p3_recall.py" `
        -ArgLine "-u `"$InstallRoot\src\p3_recall.py`" serve --port 9830" `
        -Port 9830
    Start-MemcoreServiceIfMissing `
        -Name "p4-provider" `
        -ScriptName "p4_provider.py" `
        -ArgLine "-u `"$InstallRoot\src\p4_provider.py`" --port 9840" `
        -Port 9840
    Start-MemcoreServiceIfMissing `
        -Name "p6-console" `
        -ScriptName "p6_console.py" `
        -ArgLine "-u `"$InstallRoot\src\p6_console.py`" --host 127.0.0.1 --port 9850" `
        -Port 9850
    Start-MemcoreServiceIfMissing `
        -Name "raw-gateway" `
        -ScriptName "raw_consumption_gateway.py" `
        -ArgLine "-u `"$InstallRoot\src\raw_consumption_gateway.py`"" `
        -Port 9851
    Start-MemcoreServiceIfMissing `
        -Name "dialog-entry" `
        -ScriptName "dialog_entry_proxy.py" `
        -ArgLine "-u `"$InstallRoot\src\dialog_entry_proxy.py`" --host $dialogEntryHost --port 9860" `
        -Port 9860 `
        -IncludeDialogEntryToken
}

function Invoke-RecordGuardianApi {
    param(
        [string]$Path,
        [string]$Method = "Get",
        [string]$Body = ""
    )
    $uri = "http://127.0.0.1:9850" + $Path
    if ($Method -eq "Post") {
        $tokenPath = Join-Path $RuntimeDir "console_token"
        $headers = @{}
        if (Test-Path -LiteralPath $tokenPath) {
            $token = (Get-Content -LiteralPath $tokenPath -Raw -Encoding UTF8).Trim()
            if (-not [string]::IsNullOrWhiteSpace($token)) {
                $headers["X-Memcore-Console-Token"] = $token
                $headers["Origin"] = "http://127.0.0.1:9850"
            }
        }
        return Invoke-RestMethod `
            -Method Post `
            -Uri $uri `
            -Body $Body `
            -Headers $headers `
            -ContentType "application/json" `
            -TimeoutSec 10
    }
    return Invoke-RestMethod -Uri $uri -TimeoutSec 10
}

function Invoke-RecordGuardianBackfillIfNeeded {
    try {
        $status = Invoke-RecordGuardianApi -Path "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1"
    } catch {
        Add-Check -Name "record_guardian_status" -Ok $true -Detail ("P6 guardian API unavailable; fallback to connector: " + $_.Exception.Message)
        return $false
    }

    if (-not $status.ok -or -not $status.summary) {
        Add-Check -Name "record_guardian_status" -Ok $true -Detail "P6 guardian API returned incomplete status; fallback to connector"
        return $false
    }

    $summary = $status.summary
    $missing = 0
    $catchingUp = 0
    $backfillNeeded = 0
    if ($null -ne $summary.raw_lagging_or_missing_count) { $missing = [int]$summary.raw_lagging_or_missing_count }
    if ($null -ne $summary.raw_catching_up_count) { $catchingUp = [int]$summary.raw_catching_up_count }
    if ($null -ne $summary.backfill_recommended_count) { $backfillNeeded = [int]$summary.backfill_recommended_count }

    if (($backfillNeeded -le 0) -and ($missing -le 0)) {
        Add-Check `
            -Name "record_guardian_backfill" `
            -Ok $true `
            -Detail ("not needed guarded=" + [string]$summary.record_guarded_count + "/" + [string]$summary.record_count + " catching_up=" + [string]$catchingUp)
        return $true
    }

    try {
        $body = @{ limit = 80 } | ConvertTo-Json -Depth 4 -Compress
        $result = Invoke-RecordGuardianApi -Path "/api/v1/records/guardian/backfill" -Method "Post" -Body $body
    } catch {
        Add-Check -Name "record_guardian_backfill" -Ok $false -Detail ("P6 guardian backfill failed: " + $_.Exception.Message)
        return $true
    }
    if (-not $result.ok) {
        Add-Check -Name "record_guardian_backfill" -Ok $false -Detail "P6 guardian backfill returned not ok"
        return $true
    }
    Add-Check -Name "record_guardian_backfill" -Ok $true -Detail ("ran changed=" + [string]($result.results | Measure-Object).Count + " recommended=" + [string]$backfillNeeded)
    return $true
}

function Invoke-CodexRawBackfillIfNeeded {
    if (Invoke-RecordGuardianBackfillIfNeeded) {
        return
    }

    $python = Get-VenvPython
    $connector = Join-Path $InstallRoot "src\codex_local_connector.py"
    $p0 = Join-Path $InstallRoot "src\memcore-cloud.py"
    if (-not (Test-Path -LiteralPath $connector)) {
        Add-Check -Name "codex_backfill" -Ok $true -Detail "codex connector missing; skipped"
        return
    }
    if (-not (Test-Path -LiteralPath $p0)) {
        Fail-Guardian -Name "p0_script" -Detail "missing: $p0"
    }

    $env:MEMCORE_ROOT = $InstallRoot
    $env:MEMCORE_INSTALL_ROOT = $InstallRoot
    $env:PYTHONPATH = $InstallRoot
    $env:PYTHONIOENCODING = "utf-8"

    $statusText = (& $python $connector --status 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        Add-Check -Name "codex_backfill_status" -Ok $false -Detail ("status failed: " + $statusText.Trim())
        return
    }
    $payload = $null
    try {
        $payload = ConvertFrom-JsonOutput -Text $statusText
    } catch {
        Add-Check -Name "codex_backfill_status" -Ok $false -Detail ("status returned non-JSON: " + $_.Exception.Message)
        return
    }
    $rawSync = $payload.raw_sync
    $rawStatus = if ($rawSync -and $rawSync.status) { [string]$rawSync.status } else { "unknown" }
    if ($rawStatus -notin @("raw_missing", "raw_lagging_sla_breach")) {
        Add-Check -Name "codex_backfill" -Ok $true -Detail ("not needed raw_sync=" + $rawStatus)
        return
    }

    $missing = if ($rawSync.missing_or_stale_count) { [string]$rawSync.missing_or_stale_count } else { "unknown" }
    $scanText = (& $python $p0 --scan --source codex 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        Add-Check -Name "codex_backfill" -Ok $false -Detail ("scan failed missing/stale=" + $missing + " " + $scanText.Trim())
        return
    }
    Add-Check -Name "codex_backfill" -Ok $true -Detail ("ran because " + $rawStatus + " missing/stale=" + $missing)
}

try {
    if (-not (Test-Path -LiteralPath $InstallRoot)) {
        Fail-Guardian -Name "install_root" -Detail "missing: $InstallRoot"
    }
    Add-Check -Name "install_root" -Ok $true -Detail $InstallRoot
    if ($StartWatcher) {
        Start-P0WatcherIfMissing
        Start-RuntimeServicesIfMissing
    }
    if ($Backfill) { Invoke-CodexRawBackfillIfNeeded }
} catch {
    Add-Check -Name "guardian_exception" -Ok $false -Detail ($_.Exception.Message)
    Add-Content -LiteralPath $GuardianErr -Value ((Now-Iso) + " " + $_.Exception.ToString()) -Encoding UTF8
    Write-GuardianStatus
    exit 1
}

Write-GuardianStatus
if (-not $Report.ok) { exit 1 }
