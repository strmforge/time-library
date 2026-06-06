#Requires -Version 5.1
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\memcore-cloud",
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

function Normalize-PathText {
    param([string]$Text)
    return ([string]$Text).Replace("\", "/").ToLowerInvariant()
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
        "`"$python`" -u `"$watcher`" --watch --source all 1>>`"$out`" 2>>`"$err`""
    )
    Write-Utf8NoBom -Path $cmdPath -Text (($lines -join "`r`n") + "`r`n")
    Add-Check -Name "p0_watcher_cmd_refreshed" -Ok $true -Detail $cmdPath
    return $cmdPath
}

function Ensure-MemcoreServiceCommand {
    param(
        [string]$Name,
        [string]$ArgLine
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
        "set `"HERMES_HOME=$HermesHome`"",
        "`"$python`" $ArgLine 1>>`"$out`" 2>>`"$err`""
    )
    Write-Utf8NoBom -Path $cmdPath -Text (($lines -join "`r`n") + "`r`n")
    Add-Check -Name ($Name + "_cmd_refreshed") -Ok $true -Detail $cmdPath
    return $cmdPath
}

function Start-P0WatcherIfMissing {
    $running = Get-P0WatcherProcesses
    $watcher = Join-Path $InstallRoot "src\memcore-cloud.py"
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
    $proc = Start-Process -FilePath $env:ComSpec -ArgumentList @("/c", "`"$cmdPath`"") -WorkingDirectory $InstallRoot -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath (Join-Path $RuntimeDir "p0-watcher.pid") -Value ([string]$proc.Id) -Encoding ASCII
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
        [int]$Port = 0
    )
    $scriptPath = Join-Path $InstallRoot ("src\" + $ScriptName)
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Fail-Guardian -Name ($Name + "_script") -Detail "missing: $scriptPath"
    }

    $cmdPath = Ensure-MemcoreServiceCommand -Name $Name -ArgLine $ArgLine
    $running = @(Get-MemcoreServiceProcesses -Name $Name -ScriptName $ScriptName)
    if (
        (Test-ProcessesOlderThanFile -Processes $running -Path $scriptPath) -or
        (($running.Count -gt 0) -and (Test-ServiceSourceChanged -Name $Name -Path $scriptPath))
    ) {
        Stop-ProcessTreeByRoots -RootProcesses $running
        Add-Check -Name ($Name + "_restart") -Ok $true -Detail "source file newer than running process or source hash changed"
        $running = @()
    }
    $portReady = Test-PortListening -Port $Port
    if (($running.Count -gt 0) -and $portReady) {
        Set-StoredServiceHash -Name $Name -Hash (Get-FileSha256 -Path $scriptPath)
        Add-Check -Name ($Name + "_process") -Ok $true -Detail ("already running PID " + [string]$running[0].ProcessId)
        if ($Port -gt 0) {
            Add-Check -Name ($Name + "_port") -Ok $true -Detail ("listening " + [string]$Port)
        }
        return
    }

    $proc = Start-Process -FilePath $env:ComSpec -ArgumentList @("/c", "`"$cmdPath`"") -WorkingDirectory $InstallRoot -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath (Join-Path $RuntimeDir "$Name.pid") -Value ([string]$proc.Id) -Encoding ASCII
    $after = @()
    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        $after = @(Get-MemcoreServiceProcesses -Name $Name -ScriptName $ScriptName)
        $ready = Test-PortListening -Port $Port
        if (($after.Count -gt 0) -and $ready) { break }
    }
    if ($after.Count -eq 0) {
        Fail-Guardian -Name ($Name + "_start") -Detail "start attempted but process was not found"
    }
    if (-not $ready) {
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
        -ArgLine "-u `"$InstallRoot\src\dialog_entry_proxy.py`" --port 9860" `
        -Port 9860
}

function Invoke-CodexRawBackfillIfNeeded {
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
    if ($rawStatus -ne "raw_lagging") {
        Add-Check -Name "codex_backfill" -Ok $true -Detail ("not needed raw_sync=" + $rawStatus)
        return
    }

    $missing = if ($rawSync.missing_or_stale_count) { [string]$rawSync.missing_or_stale_count } else { "unknown" }
    $scanText = (& $python $p0 --scan --source codex 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        Add-Check -Name "codex_backfill" -Ok $false -Detail ("scan failed missing/stale=" + $missing + " " + $scanText.Trim())
        return
    }
    Add-Check -Name "codex_backfill" -Ok $true -Detail ("ran because raw_lagging missing/stale=" + $missing)
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
