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

$DefaultInstallRoot = Join-Path $env:LOCALAPPDATA "time-library"
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    if (-not [string]::IsNullOrWhiteSpace($env:TIME_LIBRARY_INSTALL_DIR)) {
        $InstallRoot = $env:TIME_LIBRARY_INSTALL_DIR
    } elseif (-not [string]::IsNullOrWhiteSpace($env:MEMCORE_INSTALL_DIR)) {
        $InstallRoot = $env:MEMCORE_INSTALL_DIR
    } else {
        $InstallRoot = $DefaultInstallRoot
    }
}

function Normalize-InstallRootPath {
    param([string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    if ($full.Length -gt $root.Length) {
        return $full.TrimEnd('\', '/')
    }
    return $full
}

$InstallRoot = Normalize-InstallRootPath -Path $InstallRoot
$DefaultInstallRoot = Normalize-InstallRootPath -Path $DefaultInstallRoot
$LegacyInstallRoot = Normalize-InstallRootPath -Path (Join-Path $env:LOCALAPPDATA "memcore-cloud")

function Info($msg) { Write-Host "[time-library-windows-install] $msg" }
function Warn($msg) { Write-Host "[time-library-windows-install WARNING] $msg" -ForegroundColor Yellow }
function Die($msg) { throw $msg }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$LogDir = Join-Path $InstallRoot "logs"
$NodeName = if ($env:COMPUTERNAME) { $env:COMPUTERNAME } else { "windows-local" }
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$CodexSkillStatus = "pending"
$CodexMcpStatus = "pending"
$ClaudeCodeMcpStatus = "pending"
$ClaudeCodeHookStatus = "pending"
$ClaudeDesktopStatus = "pending"
$PreparedPython = ""
$PreparedWheelhouse = ""
$PreviousVenvBackup = ""
$ProgramBackup = ""
$TransactionStateBackup = ""
$TransactionStatePresence = @{}
$InstallRootExistedBefore = Test-Path -LiteralPath $InstallRoot
$VenvActivated = $false
$InstallCompleted = $false
$RunningRuntimeRolesBeforeUpgrade = @()
$ScheduledTaskSnapshots = @()
$ScheduledTaskSnapshotCaptured = $false
$InstallTransactionLockStream = $null
$InstallTransactionLockPath = ""
$DialogEntryHost = if ([string]::IsNullOrWhiteSpace($DialogEntryHost)) { "127.0.0.1" } else { $DialogEntryHost.Trim() }
$DialogEntryEndpointUrl = if ([string]::IsNullOrWhiteSpace($DialogEntryEndpointUrl)) { "" } else { $DialogEntryEndpointUrl.Trim() }
$FrontDoorPort = 9850
$InternalP3Port = 19300
$InternalP4Port = 19400
$InternalP6Port = 19500
$InternalRawPort = 19510
$InternalDialogPort = 19600
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

function Get-ProgramMirrorArgs {
    param([string]$From, [string]$To)
    return @(
        $From, $To, "/MIR",
        "/R:2", "/W:1", "/XJ",
        "/XD", ".git", ".venv", "__pycache__", ".pytest_cache", ".playwright-cli", ".codex_nas_pending", "config", "logs", "runtime", "memory", "raw", "zhiyi", "experience_lancedb", "backups", "data", "state", "input", "output", "release", "update_staging",
        "/XF", "*.pyc", ".DS_Store", "._*", ".checkpoint", ".checkpoint_p2.json", "update_history.jsonl",
        "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
    )
}

function Invoke-Robocopy {
    param([string]$From, [string]$To, [string]$RollbackPath = "")
    if (-not (Test-Path $To)) { New-Item -ItemType Directory -Force -Path $To | Out-Null }
    $robocopyArgs = @(Get-ProgramMirrorArgs -From $From -To $To)
    & robocopy @robocopyArgs | Out-Null
    $copyExitCode = $LASTEXITCODE
    if ($copyExitCode -le 7) { return }
    if ((-not [string]::IsNullOrWhiteSpace($RollbackPath)) -and (Test-Path -LiteralPath $RollbackPath)) {
        Warn "Program mirror failed with exit $copyExitCode; restoring the pre-upgrade program backup"
        $rollbackArgs = @(Get-ProgramMirrorArgs -From $RollbackPath -To $To)
        & robocopy @rollbackArgs | Out-Null
        $rollbackExitCode = $LASTEXITCODE
        if ($rollbackExitCode -gt 7) {
            Die "program mirror failed with exit $copyExitCode and rollback failed with exit $rollbackExitCode"
        }
        Die "program mirror failed with exit $copyExitCode; prior program files were restored"
    }
    Die "robocopy failed with exit code $copyExitCode"
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

function Backup-InstallFiles {
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
        Die "install file backup was incomplete (robocopy exit $LASTEXITCODE); production files were not changed"
    }
}

function Backup-TransactionState {
    param([string]$BackupPath)
    $presence = @{}
    Remove-Tree -Path $BackupPath
    New-Item -ItemType Directory -Force -Path $BackupPath | Out-Null
    try {
        foreach ($relative in @("config", ".checkpoint", ".checkpoint_p2.json", "runtime\dialog_entry_token")) {
            $source = Join-Path $InstallRoot $relative
            $present = Test-Path -LiteralPath $source
            $presence[$relative] = $present
            if (-not $present) { continue }
            $target = Join-Path $BackupPath $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
        }
    } catch {
        Remove-Tree -Path $BackupPath
        throw
    }
    $script:TransactionStateBackup = $BackupPath
    $script:TransactionStatePresence = $presence
}

function Restore-TransactionState {
    if ([string]::IsNullOrWhiteSpace($TransactionStateBackup)) { return }
    foreach ($relative in @("config", ".checkpoint", ".checkpoint_p2.json", "runtime\dialog_entry_token")) {
        $target = Join-Path $InstallRoot $relative
        if (Test-Path -LiteralPath $target) { Remove-Tree -Path $target }
        if (-not $TransactionStatePresence[$relative]) { continue }
        $source = Join-Path $TransactionStateBackup $relative
        if (-not (Test-Path -LiteralPath $source)) {
            throw "transaction state backup is missing $relative"
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
    }
}

function Acquire-InstallTransactionLock {
    $parent = Split-Path -Parent $InstallRoot
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $script:InstallTransactionLockPath = "$InstallRoot.time-library-install.lock"
    try {
        $script:InstallTransactionLockStream = New-Object System.IO.FileStream(
            $script:InstallTransactionLockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $script:InstallTransactionLockStream.SetLength(0)
        $bytes = [System.Text.Encoding]::ASCII.GetBytes("pid=$PID`n")
        $script:InstallTransactionLockStream.Write($bytes, 0, $bytes.Length)
        $script:InstallTransactionLockStream.Flush()
    } catch {
        if ($script:InstallTransactionLockStream) {
            $script:InstallTransactionLockStream.Dispose()
            $script:InstallTransactionLockStream = $null
        }
        Die "another Time Library installer is already updating this root"
    }
}

function Release-InstallTransactionLock {
    if ($InstallTransactionLockStream) {
        $InstallTransactionLockStream.Dispose()
        $script:InstallTransactionLockStream = $null
    }
    if ($InstallTransactionLockPath -and (Test-Path -LiteralPath $InstallTransactionLockPath)) {
        Remove-Item -LiteralPath $InstallTransactionLockPath -Force -ErrorAction SilentlyContinue
    }
}

function ConvertFrom-WindowsCommandLine {
    param([string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return @() }
    $tokens = New-Object System.Collections.Generic.List[string]
    foreach ($match in [regex]::Matches($CommandLine, '"[^"]*"|\S+')) {
        $tokens.Add($match.Value.Trim('"'))
    }
    return $tokens.ToArray()
}

function Test-ProcessRunsInstallEntrypoint {
    param($Process, [string[]]$KnownEntrypoints)
    $name = [System.IO.Path]::GetFileNameWithoutExtension([string]$Process.Name).ToLowerInvariant()
    $tokens = @(ConvertFrom-WindowsCommandLine -CommandLine ([string]$Process.CommandLine))
    if ($tokens.Count -lt 2) { return $false }

    if ($name -in @("python", "pythonw", "py")) {
        for ($index = 1; $index -lt $tokens.Count; $index += 1) {
            $token = [string]$tokens[$index]
            if ($token.StartsWith("-")) { continue }
            foreach ($entrypoint in $KnownEntrypoints) {
                if ($token.Equals($entrypoint, [System.StringComparison]::OrdinalIgnoreCase)) {
                    return $true
                }
            }
            return $false
        }
        return $false
    }

    if ($name -in @("powershell", "pwsh")) {
        for ($index = 1; $index -lt ($tokens.Count - 1); $index += 1) {
            if (-not ([string]$tokens[$index]).Equals("-File", [System.StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            $scriptPath = [string]$tokens[$index + 1]
            foreach ($entrypoint in $KnownEntrypoints) {
                if ($scriptPath.Equals($entrypoint, [System.StringComparison]::OrdinalIgnoreCase)) {
                    return $true
                }
            }
            return $false
        }
    }
    return $false
}

function Get-RuntimeRoleDefinitions {
    param([string]$Root = $InstallRoot)
    return @(
        [pscustomobject]@{ Role = "p0-watcher"; Entrypoint = (Join-Path $Root "src\memcore-cloud.py") },
        [pscustomobject]@{ Role = "p3-recall"; Entrypoint = (Join-Path $Root "src\p3_recall.py") },
        [pscustomobject]@{ Role = "p4-provider"; Entrypoint = (Join-Path $Root "src\p4_provider.py") },
        [pscustomobject]@{ Role = "p6-console"; Entrypoint = (Join-Path $Root "src\p6_console.py") },
        [pscustomobject]@{ Role = "raw-gateway"; Entrypoint = (Join-Path $Root "src\raw_consumption_gateway.py") },
        [pscustomobject]@{ Role = "dialog-entry"; Entrypoint = (Join-Path $Root "src\dialog_entry_proxy.py") },
        [pscustomobject]@{ Role = "front-door"; Entrypoint = (Join-Path $Root "src\single_port_runtime.py") },
        [pscustomobject]@{ Role = "guardian"; Entrypoint = (Join-Path $Root "tools\windows_guardian.ps1") },
        [pscustomobject]@{ Role = "tray"; Entrypoint = (Join-Path $Root "tools\windows_tray.ps1") }
    )
}

function Get-KnownInstallEntrypoints {
    param([string]$Root = $InstallRoot)
    return @((Get-RuntimeRoleDefinitions -Root $Root | ForEach-Object { $_.Entrypoint }))
}

function Get-OwnedInstallProcessRecords {
    param([string]$Root = $InstallRoot)
    try {
        $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    } catch {
        throw "cannot verify Time Library process ownership: $($_.Exception.Message)"
    }
    $records = New-Object System.Collections.Generic.List[object]
    foreach ($process in $processes) {
        foreach ($definition in @(Get-RuntimeRoleDefinitions -Root $Root)) {
            if (Test-ProcessRunsInstallEntrypoint -Process $process -KnownEntrypoints @($definition.Entrypoint)) {
                $records.Add([pscustomobject]@{ Role = $definition.Role; Process = $process })
                break
            }
        }
    }
    return $records.ToArray()
}

function Get-OwnedInstallProcesses {
    param([string]$Root = $InstallRoot)
    return @((Get-OwnedInstallProcessRecords -Root $Root | ForEach-Object { $_.Process }))
}

function Test-TaskActionRunsInstallEntrypoint {
    param($Action, [string[]]$KnownEntrypoints)
    $execute = [string]$Action.Execute
    $name = [System.IO.Path]::GetFileNameWithoutExtension($execute).ToLowerInvariant()
    $tokens = @(ConvertFrom-WindowsCommandLine -CommandLine ([string]$Action.Arguments))

    foreach ($entrypoint in $KnownEntrypoints) {
        if ($execute.Equals($entrypoint, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    if ($name -in @("python", "pythonw", "py")) {
        foreach ($tokenValue in $tokens) {
            $token = [string]$tokenValue
            if ($token.StartsWith("-")) { continue }
            foreach ($entrypoint in $KnownEntrypoints) {
                if ($token.Equals($entrypoint, [System.StringComparison]::OrdinalIgnoreCase)) {
                    return $true
                }
            }
            return $false
        }
        return $false
    }
    if ($name -in @("powershell", "pwsh")) {
        for ($index = 0; $index -lt ($tokens.Count - 1); $index += 1) {
            if (-not ([string]$tokens[$index]).Equals("-File", [System.StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            $scriptPath = [string]$tokens[$index + 1]
            foreach ($entrypoint in $KnownEntrypoints) {
                if ($scriptPath.Equals($entrypoint, [System.StringComparison]::OrdinalIgnoreCase)) {
                    return $true
                }
            }
            return $false
        }
        return $false
    }
    if ($name -in @("wscript", "cscript")) {
        foreach ($tokenValue in $tokens) {
            $token = [string]$tokenValue
            if ($token.StartsWith("//")) { continue }
            foreach ($entrypoint in $KnownEntrypoints) {
                if ($token.Equals($entrypoint, [System.StringComparison]::OrdinalIgnoreCase)) {
                    return $true
                }
            }
            return $false
        }
    }
    return $false
}

function Stop-OldProcesses {
    $stoppedProcessIds = New-Object System.Collections.Generic.List[int]
    @(Get-OwnedInstallProcessRecords) | ForEach-Object {
        $processId = [int]$_.Process.ProcessId
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        $stoppedProcessIds.Add($processId)
        Info "Stopping old $($_.Role) process for install root (PID $processId)"
    }
    foreach ($processId in $stoppedProcessIds) {
        Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
    }
    $remaining = @(Get-OwnedInstallProcessRecords)
    if ($remaining.Count -gt 0) {
        $summary = ($remaining | ForEach-Object { "$($_.Role):$($_.Process.ProcessId)" }) -join ","
        Die "Time Library processes are still running after stop request: $summary"
    }
}

function Get-ManagedScheduledTaskNames {
    return @("MemcoreCloudGuardianLogon", "MemcoreCloudGuardianHealth", "MemcoreCloudTray")
}

function Get-ManagedScheduledTasks {
    $names = @(Get-ManagedScheduledTaskNames)
    try {
        return @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -in $names })
    } catch {
        throw "cannot verify Time Library scheduled tasks: $($_.Exception.Message)"
    }
}

function Unregister-MemcoreScheduledTasks {
    foreach ($task in @(Get-ManagedScheduledTasks)) {
        if (-not (Test-ScheduledTaskTargetsInstallRoot -Task $task)) {
            Die "Scheduled task $($task.TaskName) belongs to another Time Library install root"
        }
        Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false -ErrorAction Stop
        Info "Removed old scheduled task: $($task.TaskName)"
    }
}

function Test-ScheduledTaskTargetsInstallRoot {
    param($Task, [string]$Root = $InstallRoot)
    $allowedRoots = @($Root)
    if ($Root -ieq $DefaultInstallRoot) { $allowedRoots += $LegacyInstallRoot }
    $knownEntrypoints = New-Object System.Collections.Generic.List[string]
    foreach ($root in $allowedRoots) {
        if ([string]::IsNullOrWhiteSpace($root)) { continue }
        $knownEntrypoints.Add((Join-Path $root "tools\windows_hidden_guardian.vbs"))
        $knownEntrypoints.Add((Join-Path $root "tools\windows_guardian.ps1"))
        $knownEntrypoints.Add((Join-Path $root "tools\windows_tray.ps1"))
    }
    foreach ($action in @($Task.Actions)) {
        if (Test-TaskActionRunsInstallEntrypoint -Action $action -KnownEntrypoints $knownEntrypoints.ToArray()) {
            return $true
        }
    }
    return $false
}

function Assert-ScheduledTaskOwnershipAvailable {
    foreach ($task in @(Get-ManagedScheduledTasks)) {
        if ($task -and (-not (Test-ScheduledTaskTargetsInstallRoot -Task $task))) {
            Die "Scheduled task $($task.TaskName) belongs to another Time Library install root; stop that installation explicitly"
        }
    }
}

function Assert-NoStartTargetIsOffline {
    if (Test-Path -LiteralPath $InstallRoot) {
        Die "-NoStart requires a new install root; use normal -Reinstall for an existing installation"
    }
    if (($InstallRoot -ieq $DefaultInstallRoot) -and (Test-Path -LiteralPath $LegacyInstallRoot)) {
        Die "-NoStart cannot stage the default root while a legacy installation exists; use an isolated new root"
    }
}

function Assert-NoStartRuntimeAbsent {
    param([string]$Root = $InstallRoot)
    $ownedProcesses = @(Get-OwnedInstallProcessRecords -Root $Root)
    if ($ownedProcesses.Count -gt 0) {
        Die "-NoStart target acquired a running Time Library process during installation: $Root"
    }
    foreach ($task in @(Get-ManagedScheduledTasks)) {
        if (Test-ScheduledTaskTargetsInstallRoot -Task $task -Root $Root) {
            Die "-NoStart target acquired scheduled task $($task.TaskName) during installation: $Root"
        }
    }
}

function Snapshot-And-SuspendScheduledTasks {
    $tasks = @(Get-ManagedScheduledTasks)
    $snapshots = New-Object System.Collections.Generic.List[object]
    foreach ($task in $tasks) {
        if (-not (Test-ScheduledTaskTargetsInstallRoot -Task $task)) {
            Die "Scheduled task $($task.TaskName) belongs to another Time Library install root"
        }
        $xml = Export-ScheduledTask -TaskName $task.TaskName -ErrorAction Stop
        $snapshots.Add([pscustomobject]@{
            TaskName = $task.TaskName
            Xml = $xml
            Enabled = [bool]$task.Settings.Enabled
            State = [string]$task.State
        })
    }
    $script:ScheduledTaskSnapshots = $snapshots.ToArray()
    $script:ScheduledTaskSnapshotCaptured = $true
    foreach ($task in $tasks) {
        Disable-ScheduledTask -TaskName $task.TaskName -ErrorAction Stop | Out-Null
        Stop-ScheduledTask -TaskName $task.TaskName -ErrorAction SilentlyContinue
    }
}

function Restore-ScheduledTaskSnapshots {
    if (-not $ScheduledTaskSnapshotCaptured) { return }
    $snapshotNames = @($ScheduledTaskSnapshots | ForEach-Object { $_.TaskName })
    $apply = {
        foreach ($task in @(Get-ManagedScheduledTasks)) {
            if (-not (Test-ScheduledTaskTargetsInstallRoot -Task $task)) {
                Die "cannot restore scheduled tasks because $($task.TaskName) belongs to another install root"
            }
            if ($task.TaskName -notin $snapshotNames) {
                Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false -ErrorAction Stop
            }
        }
        foreach ($snapshot in $ScheduledTaskSnapshots) {
            Register-ScheduledTask -TaskName $snapshot.TaskName -Xml $snapshot.Xml -Force -ErrorAction Stop | Out-Null
            if (-not $snapshot.Enabled) {
                Disable-ScheduledTask -TaskName $snapshot.TaskName -ErrorAction Stop | Out-Null
            }
        }
    }

    try {
        & $apply
    } catch {
        $firstError = $_.Exception.Message
        try {
            # Scheduled Tasks has no multi-object transaction. Clear our owned
            # task set and replay the complete snapshot once before failing.
            foreach ($task in @(Get-ManagedScheduledTasks)) {
                if (-not (Test-ScheduledTaskTargetsInstallRoot -Task $task)) {
                    Die "cannot retry scheduled task restore because $($task.TaskName) belongs to another install root"
                }
                Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false -ErrorAction Stop
            }
            & $apply
        } catch {
            $retryError = $_.Exception.Message
            $cleanupError = ""
            try {
                # Never leave a mixed task set active after both replay attempts
                # fail. The old XML remains in the transaction backup for a
                # separately observable recovery action.
                foreach ($task in @(Get-ManagedScheduledTasks)) {
                    if (-not (Test-ScheduledTaskTargetsInstallRoot -Task $task)) {
                        Die "cannot clear scheduled tasks because $($task.TaskName) belongs to another install root"
                    }
                    Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false -ErrorAction Stop
                }
            } catch {
                $cleanupError = "; cleanup=$($_.Exception.Message)"
            }
            throw "scheduled task restore failed after retry: first=$firstError; retry=$retryError; owned_tasks_cleared_fail_closed=$([string]::IsNullOrWhiteSpace($cleanupError))$cleanupError"
        }
    }
}

function Install-Files {
    $migratedLegacy = $false
    $backup = ""
    $targetRoot = $InstallRoot
    $stageRoot = ""
    if ($NoStart) {
        if (Test-Path -LiteralPath $targetRoot) {
            Die "-NoStart target appeared after preflight; refusing to replace an existing root"
        }
        Assert-NoStartRuntimeAbsent -Root $targetRoot
        $parent = Split-Path -Parent $targetRoot
        $leaf = Split-Path -Leaf $targetRoot
        $stageRoot = Join-Path $parent ("." + $leaf + ".install-stage." + $PID + "." + [Guid]::NewGuid().ToString("N"))
        $script:InstallRoot = $stageRoot
    }
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
            Die "-ResetInstall target appeared after preflight; refusing destructive replacement"
        } else {
            $backup = "$InstallRoot.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
            Info "Backing up existing install files to $backup"
            Backup-InstallFiles -BackupPath $backup
            Backup-TransactionState -BackupPath ($backup + ".transaction-state")
            $script:ProgramBackup = $backup
        }
    }
    if ($NoStart) {
        Assert-NoStartRuntimeAbsent -Root $stageRoot
        Assert-NoStartRuntimeAbsent -Root $targetRoot
    }
    Invoke-Robocopy -From $SourceRoot -To $InstallRoot -RollbackPath $backup
    if ($NoStart) {
        Assert-NoStartRuntimeAbsent -Root $stageRoot
        Assert-NoStartRuntimeAbsent -Root $targetRoot
    }
    Remove-Tree -Path (Join-Path $InstallRoot ".playwright-cli")
    Merge-PackagedConfig
    Migrate-LegacyStatePaths
    if ($NoStart) {
        if (Test-Path -LiteralPath $targetRoot) {
            Die "-NoStart target appeared during staging; refusing to replace an existing root"
        }
        [System.IO.Directory]::Move($stageRoot, $targetRoot)
        $script:InstallRoot = $targetRoot
        if ((Test-Path -LiteralPath $stageRoot) -or (-not (Test-Path -LiteralPath $targetRoot))) {
            Die "-NoStart atomic stage cutover did not complete"
        }
        foreach ($required in @("VERSION", "src", "tools", "config")) {
            if (-not (Test-Path -LiteralPath (Join-Path $targetRoot $required))) {
                Die "-NoStart cutover target is incomplete: $required"
            }
        }
        Assert-NoStartRuntimeAbsent -Root $targetRoot
    }
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
        front_door_port = $FrontDoorPort
        internal_p3_port = $InternalP3Port
        internal_p4_port = $InternalP4Port
        internal_p6_port = $InternalP6Port
        internal_raw_port = $InternalRawPort
        internal_dialog_port = $InternalDialogPort
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
    $modelCfg = Get-Content -LiteralPath $modelCfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $modelCfg.recall.mode = "substring"
    Write-Utf8NoBom -Path $modelCfgPath -Text (($modelCfg | ConvertTo-Json -Depth 20) + "`n")
}

function Install-PythonEnv {
    $python = Find-Python
    if (-not $python) { Die "Python not found" }
    $parent = Split-Path -Parent $InstallRoot
    $leaf = Split-Path -Leaf $InstallRoot
    $buildVenv = Join-Path $parent ("." + $leaf + ".venv-build." + $PID)
    $wheelhouse = Join-Path $parent ("." + $leaf + ".wheelhouse-stage." + $PID)
    if (Test-Path -LiteralPath $buildVenv) { Remove-Tree -Path $buildVenv }
    if (Test-Path -LiteralPath $wheelhouse) { Remove-Tree -Path $wheelhouse }
    Info "Preparing dependency wheels outside the active runtime"
    & $python -m venv $buildVenv
    if ($LASTEXITCODE -ne 0) {
        Remove-Tree -Path $buildVenv
        Die "failed to create dependency-build venv with $python"
    }
    $buildPython = Join-Path $buildVenv "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $buildPython)) {
        Remove-Tree -Path $buildVenv
        Die "dependency-build Python venv was not created: $buildPython"
    }
    & $buildPython -m pip install --upgrade pip | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Tree -Path $buildVenv
        Die "failed to upgrade pip in dependency-build venv"
    }
    $req = Join-Path $SourceRoot "requirements-core.txt"
    if (Test-Path -LiteralPath $req) {
        New-Item -ItemType Directory -Force -Path $wheelhouse | Out-Null
        & $buildPython -m pip wheel --wheel-dir $wheelhouse -r $req
        if ($LASTEXITCODE -ne 0) {
            Remove-Tree -Path $buildVenv
            Remove-Tree -Path $wheelhouse
            Die "failed to prepare dependency wheels"
        }
    }
    Remove-Tree -Path $buildVenv
    $script:PreparedPython = $python
    $script:PreparedWheelhouse = $wheelhouse
}

function Activate-PythonEnv {
    if ([string]::IsNullOrWhiteSpace($PreparedPython)) { return }
    $venv = Join-Path $InstallRoot ".venv"
    $backup = ""
    if (Test-Path -LiteralPath $venv) {
        # Keep rollback state outside the mirrored install root. /MIR must not be
        # able to delete the old environment while it copies program files.
        $parent = Split-Path -Parent $InstallRoot
        $leaf = Split-Path -Leaf $InstallRoot
        $backup = Join-Path $parent ("." + $leaf + ".venv-backup." + $PID + "." + [Guid]::NewGuid().ToString("N"))
        Move-Item -LiteralPath $venv -Destination $backup
    }
    try {
        & $PreparedPython -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "failed to create Python venv at final install path" }
        $venvPython = Join-Path $venv "Scripts\python.exe"
        $req = Join-Path $SourceRoot "requirements-core.txt"
        if (Test-Path -LiteralPath $req) {
            & $venvPython -m pip install --no-index --find-links $PreparedWheelhouse -r $req
            if ($LASTEXITCODE -ne 0) { throw "failed to install prepared dependencies at final install path" }
        }
    } catch {
        if (Test-Path -LiteralPath $venv) { Remove-Tree -Path $venv }
        if ($backup -and (Test-Path -LiteralPath $backup)) {
            Move-Item -LiteralPath $backup -Destination $venv
        }
        throw
    }
    $script:PreviousVenvBackup = $backup
    $script:VenvActivated = $true
}

function Remove-PreviousVenvBackup {
    if ([string]::IsNullOrWhiteSpace($PreviousVenvBackup)) { return }
    if (Test-Path -LiteralPath $PreviousVenvBackup) {
        Remove-Tree -Path $PreviousVenvBackup
    }
    $script:PreviousVenvBackup = ""
}

function Begin-InstallCutover {
    if ($NoStart) { return }
    if (-not (Test-Path -LiteralPath $InstallRoot)) {
        # A fresh install has no old tasks, but the transaction still needs an
        # explicit empty snapshot so partially created tasks are removed.
        $script:ScheduledTaskSnapshots = @()
        $script:ScheduledTaskSnapshotCaptured = $true
        return
    }
    $roles = New-Object System.Collections.Generic.List[string]
    foreach ($record in @(Get-OwnedInstallProcessRecords)) { $roles.Add([string]$record.Role) }
    Snapshot-And-SuspendScheduledTasks
    foreach ($snapshot in $ScheduledTaskSnapshots) {
        if ($snapshot.State -ne "Running") { continue }
        if ($snapshot.TaskName -eq "MemcoreCloudTray") { $roles.Add("task:MemcoreCloudTray") }
        if ($snapshot.TaskName -in @("MemcoreCloudGuardianLogon", "MemcoreCloudGuardianHealth")) {
            $roles.Add("task:$($snapshot.TaskName)")
        }
    }
    $script:RunningRuntimeRolesBeforeUpgrade = @($roles | Select-Object -Unique)
    Stop-OldProcesses
}

function Restore-InstallTransaction {
    $rollbackErrors = New-Object System.Collections.Generic.List[string]
    try { Stop-OldProcesses } catch { $rollbackErrors.Add("stop_partial_runtime: $($_.Exception.Message)") }

    $programRestored = $true
    $stateRestored = $true
    $venvRestored = $true
    $tasksRestored = $true
    if (-not $InstallRootExistedBefore) {
        try { Restore-ScheduledTaskSnapshots } catch {
            $tasksRestored = $false
            $rollbackErrors.Add("restore_scheduled_tasks: $($_.Exception.Message)")
        }
        try { Remove-Tree -Path $InstallRoot } catch { $rollbackErrors.Add("remove_fresh_install: $($_.Exception.Message)") }
    } else {
        if (-not [string]::IsNullOrWhiteSpace($ProgramBackup)) {
            try {
                Invoke-Robocopy -From $ProgramBackup -To $InstallRoot
            } catch {
                $programRestored = $false
                $rollbackErrors.Add("restore_program: $($_.Exception.Message)")
            }
        }
        try { Restore-TransactionState } catch {
            $stateRestored = $false
            $rollbackErrors.Add("restore_state: $($_.Exception.Message)")
        }
        if ($VenvActivated) {
            $venv = Join-Path $InstallRoot ".venv"
            try {
                if (Test-Path -LiteralPath $venv) { Remove-Tree -Path $venv }
                if (-not [string]::IsNullOrWhiteSpace($PreviousVenvBackup)) {
                    if (-not (Test-Path -LiteralPath $PreviousVenvBackup)) {
                        throw "previous venv backup is missing"
                    }
                    Move-Item -LiteralPath $PreviousVenvBackup -Destination $venv
                }
            } catch {
                $venvRestored = $false
                $rollbackErrors.Add("restore_venv: $($_.Exception.Message)")
            }
        }
        try { Restore-ScheduledTaskSnapshots } catch {
            $tasksRestored = $false
            $rollbackErrors.Add("restore_scheduled_tasks: $($_.Exception.Message)")
        }
        if ((-not $NoStart) -and $programRestored -and $stateRestored -and $venvRestored -and $tasksRestored -and $RunningRuntimeRolesBeforeUpgrade.Count -gt 0) {
            try { Start-RuntimeRoles -Roles $RunningRuntimeRolesBeforeUpgrade } catch { $rollbackErrors.Add("restart_previous_runtime: $($_.Exception.Message)") }
        }
    }
    if ($rollbackErrors.Count -gt 0) {
        throw ("rollback incomplete: " + ($rollbackErrors -join "; "))
    }
}

function Remove-PreparedPythonAssets {
    if (-not [string]::IsNullOrWhiteSpace($PreparedWheelhouse)) {
        Remove-Tree -Path $PreparedWheelhouse
    }
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
endpoint_url = sys.argv[3] if len(sys.argv) > 3 else ""
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
        "provider_url": "",
        "memory_scope": "window",
        "computer_name": "",
        "limit": 3,
        "excerpt_chars": 500,
        "context_chars": 2400,
        "timeout_seconds": 5,
        "include_session_id": True,
        "receipt_url": "",
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
    provider_url: ""
    memory_scope: window
    computer_name: ""
    limit: 3
    excerpt_chars: 500
    context_chars: 2400
    timeout_seconds: 5
    include_session_id: true
    receipt_url: ""
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
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
    $bridge = Join-Path $InstallRoot "tools\codex_mcp_bridge.py"
    $policyHelper = Join-Path $InstallRoot "tools\configure_codex_mcp_policy.py"
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
                --timeout "30" `
                --window-binding-registry $registryPath `
                --binding-key "codex" *> $null
        if ($LASTEXITCODE -eq 0) {
            $codexConfig = Join-Path $codexHome "config.toml"
            if (Test-Path $policyHelper) {
                & $python $policyHelper --config $codexConfig *> $null
            }
            if ((Test-Path $policyHelper) -and ($LASTEXITCODE -eq 0)) {
                Info "Codex MCP registered with scoped recall/ack approval: time-library via $bridge"
                $script:CodexMcpStatus = "time-library"
            } else {
                Warn "Codex MCP registered, but scoped recall/ack approval policy could not be applied"
                $script:CodexMcpStatus = "time-library (approval policy warning)"
            }
        } else {
            Warn "Codex MCP registration failed; Codex users can run: codex mcp add time-library -- python $bridge"
            $script:CodexMcpStatus = "registration failed"
        }
    } catch {
        Warn "Codex MCP registration failed; Codex users can run: codex mcp add time-library -- python $bridge"
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

function Install-ClaudeCodeMcp {
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if (-not $claude) {
        $script:ClaudeCodeMcpStatus = "Claude Code CLI not found"
        return
    }
    $python = Get-RuntimePython
    $bridge = Join-Path $InstallRoot "tools\claude_desktop_mcp_bridge.py"
    $registryPath = Join-Path $InstallRoot "config\window_binding_registry.json"
    if ((-not $python) -or (-not (Test-Path $bridge))) {
        Warn "Claude Code MCP bridge or runtime Python not found"
        $script:ClaudeCodeMcpStatus = "bridge or runtime missing"
        return
    }
    $claudeConfig = if ($env:CLAUDE_CONFIG_PATH) { $env:CLAUDE_CONFIG_PATH } else { Join-Path $env:USERPROFILE ".claude.json" }
    if (Test-Path $claudeConfig) {
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
        Copy-Item -LiteralPath $claudeConfig -Destination ($claudeConfig + ".bak-time_library-port-discovery-" + $stamp) -Force
    }
    try { & $claude.Source mcp remove time-library -s user *> $null } catch { }
    $claudeArgs = @(
        "mcp", "add", "-s", "user", "time-library",
        "-e", "PYTHONIOENCODING=utf-8",
        "-e", "PYTHONUTF8=1",
        "-e", "MEMCORE_ROOT=$InstallRoot",
        "-e", "MEMCORE_WINDOW_BINDING_REGISTRY=$registryPath",
        "--", $python, $bridge,
        "--consumer", "claude_code_cli",
        "--timeout", "30",
        "--window-binding-registry", $registryPath,
        "--binding-key", "claude_code_cli"
    )
    try {
        & $claude.Source @claudeArgs *> $null
        if ($LASTEXITCODE -eq 0) {
            Info "Claude Code MCP migrated to per-request front-door discovery"
            $script:ClaudeCodeMcpStatus = "time-library (stdio discovery)"
        } else {
            Warn "Claude Code MCP migration failed"
            $script:ClaudeCodeMcpStatus = "registration failed"
        }
    } catch {
        Warn "Claude Code MCP migration failed: $($_.Exception.Message)"
        $script:ClaudeCodeMcpStatus = "registration failed"
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
        $refreshHelper = Join-Path $InstallRoot "tools\refresh_claude_desktop_mcp_bridges.py"
        if (Test-Path $refreshHelper) {
            try {
                & $python $refreshHelper --install-root $InstallRoot --install-root $LegacyInstallRoot *> $null
            } catch { }
        }
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
    if ($Name -eq "p0-watcher") {
        $lines += @(
            "set `"MEMCORE_WATCHER_RESOURCE_PROFILE=light`"",
            "set `"MEMCORE_WATCHER_SOURCE_DEFAULT=all`"",
            "set `"MEMCORE_WATCHER_INTERVAL_MS=5000`""
        )
    }
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

function Start-RestoredScheduledTask {
    param([string]$TaskName)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if (-not $task) { Die "restored scheduled task is missing: $TaskName" }
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
}

function Start-RuntimeRole {
    param([string]$Role)
    switch ($Role) {
        "p0-watcher" { Start-MemcoreService -Name "p0-watcher" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\memcore-cloud.py')`" --watch --source all" }
        "p3-recall" { Start-MemcoreService -Name "p3-recall" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\p3_recall.py')`" serve --port $InternalP3Port" }
        "p4-provider" { Start-MemcoreService -Name "p4-provider" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\p4_provider.py')`" --port $InternalP4Port" }
        "p6-console" { Start-MemcoreService -Name "p6-console" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\p6_console.py')`" --host 127.0.0.1 --port $InternalP6Port" }
        "raw-gateway" { Start-MemcoreService -Name "raw-gateway" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\raw_consumption_gateway.py')`" --port $InternalRawPort" }
        "dialog-entry" {
            Start-MemcoreService `
                -Name "dialog-entry" `
                -ArgLine "-u `"$(Join-Path $InstallRoot 'src\dialog_entry_proxy.py')`" --host 127.0.0.1 --port $InternalDialogPort" `
                -IncludeDialogEntryToken
        }
        "front-door" { Start-MemcoreService -Name "front-door" -ArgLine "-u `"$(Join-Path $InstallRoot 'src\single_port_runtime.py')`" --host 127.0.0.1 --preferred-port $FrontDoorPort" }
        "task:MemcoreCloudGuardianLogon" { Start-RestoredScheduledTask -TaskName "MemcoreCloudGuardianLogon" }
        "task:MemcoreCloudGuardianHealth" { Start-RestoredScheduledTask -TaskName "MemcoreCloudGuardianHealth" }
        "task:MemcoreCloudTray" { Start-RestoredScheduledTask -TaskName "MemcoreCloudTray" }
        "guardian" { Start-RestoredScheduledTask -TaskName "MemcoreCloudGuardianHealth" }
        "tray" { Start-RestoredScheduledTask -TaskName "MemcoreCloudTray" }
        default { Die "unknown runtime role: $Role" }
    }
}

function Start-RuntimeRoles {
    param([string[]]$Roles)
    $env:TIME_LIBRARY_ROOT = $InstallRoot
    $env:TIME_LIBRARY_INSTALL_ROOT = $InstallRoot
    $env:MEMCORE_ROOT = $InstallRoot
    $env:MEMCORE_INSTALL_ROOT = $InstallRoot
    $env:PYTHONPATH = $InstallRoot
    $env:PYTHONIOENCODING = "utf-8"
    $hermes = Get-Command hermes -ErrorAction SilentlyContinue
    if ($hermes) { $env:MEMCORE_HERMES_CLI = $hermes.Source }

    Stop-OldProcesses
    $requested = @($Roles | Select-Object -Unique)
    foreach ($role in @(
        "p0-watcher", "p3-recall", "p4-provider", "p6-console",
        "raw-gateway", "dialog-entry", "front-door",
        "task:MemcoreCloudGuardianLogon", "task:MemcoreCloudGuardianHealth", "task:MemcoreCloudTray",
        "guardian", "tray"
    )) {
        if ($role -in $requested) { Start-RuntimeRole -Role $role }
    }
}

function Start-Services {
    Start-RuntimeRoles -Roles @(
        "p0-watcher", "p3-recall", "p4-provider", "p6-console",
        "raw-gateway", "dialog-entry", "front-door"
    )
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
        Die "Windows guardian script not found: $guardian"
    }
    if (-not (Test-Path -LiteralPath $hiddenGuardian)) {
        Die "Windows hidden guardian launcher not found: $hiddenGuardian"
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
        Die "Windows tray script not found: $tray"
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
    $python = Get-RuntimePython
    $port = (& $python (Join-Path $InstallRoot "src\port_discovery.py") --root $InstallRoot --port-only).Trim()
    Smoke-One -Name "front-door" -Url "http://127.0.0.1:$port/api/health" -MaxWaitSeconds 90
    Run-NativeSmoke
}

function Run-NativeSmoke {
    $nativeSmoke = Join-Path $InstallRoot "tools\windows_native_smoke.ps1"
    if (-not (Test-Path -LiteralPath $nativeSmoke)) {
        Warn "Native Windows smoke script not found: $nativeSmoke"
        return
    }

    $powershellExe = Join-Path $PSHOME "powershell.exe"
    $nativeArgs = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$nativeSmoke`" -InstallRoot `"$InstallRoot`" -Json"
    if ($SkipCodex) { $nativeArgs += " -SkipCodex" }

    $maxAttempts = 4
    $lastExitCode = 1
    $lastOutput = @()
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt += 1) {
        $stdoutPath = Join-Path $env:TEMP ("time-library-native-smoke-" + $PID + "-" + $attempt + ".stdout.log")
        $stderrPath = Join-Path $env:TEMP ("time-library-native-smoke-" + $PID + "-" + $attempt + ".stderr.log")
        try {
            $process = Start-Process -FilePath $powershellExe -ArgumentList $nativeArgs `
                -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
            $lastExitCode = [int]$process.ExitCode
            [string]$stdout = if (Test-Path -LiteralPath $stdoutPath) {
                Get-Content -LiteralPath $stdoutPath -Raw -Encoding UTF8
            } else { "" }
            [string]$stderr = if (Test-Path -LiteralPath $stderrPath) {
                Get-Content -LiteralPath $stderrPath -Raw -Encoding UTF8
            } else { "" }
            $lastOutput = @()
            if (-not [string]::IsNullOrWhiteSpace($stdout)) { $lastOutput += $stdout.Trim() }
            if (-not [string]::IsNullOrWhiteSpace($stderr)) { $lastOutput += $stderr.Trim() }
        } catch {
            $lastExitCode = 1
            $lastOutput = @($_.Exception.Message)
        } finally {
            Remove-Item -LiteralPath $stdoutPath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
        }
        if ($lastExitCode -eq 0) {
            Info "Native Windows smoke passed after $attempt attempt(s)"
            return
        }
        foreach ($line in $lastOutput) { Write-Host ([string]$line) }
        if ($attempt -lt $maxAttempts) {
            Warn "Native Windows smoke attempt $attempt failed; waiting for services to settle"
            Start-Sleep -Seconds 3
        }
    }
    $detail = ($lastOutput | Out-String).Trim()
    Die "Native Windows smoke failed after $maxAttempts attempts with exit code ${lastExitCode}: $detail"
}

Info "Source: $SourceRoot"
Info "Install root: $InstallRoot"
$transactionStarted = $false
try {
    Acquire-InstallTransactionLock
    if ($ResetInstall -and (Test-Path -LiteralPath $InstallRoot)) {
        Die "-ResetInstall refuses to delete an existing root; back it up and remove it explicitly before a fresh install"
    }
    if ((Test-Path -LiteralPath $InstallRoot) -and (-not $Reinstall) -and (-not $ResetInstall)) {
        Die "existing install root requires -Reinstall or -ResetInstall"
    }
    if ($NoStart) {
        Assert-NoStartTargetIsOffline
    } else {
        Assert-ScheduledTaskOwnershipAvailable
    }
    Install-PythonEnv
    if ($NoStart) { Assert-NoStartTargetIsOffline }
    $transactionStarted = $true
    Begin-InstallCutover
    Install-Files
    Ensure-DialogEntryToken
    Write-Config
    Activate-PythonEnv
    if ($NoStart) { Assert-NoStartRuntimeAbsent -Root $InstallRoot }
    if (-not $NoStart) {
        Start-Services
        Register-WindowsAutostart
        if (-not $NoSmoke) { Run-Smoke }
        if ($NoAutostart) { Restore-ScheduledTaskSnapshots }
        try { Install-OpenClawPlugin } catch { Warn "OpenClaw integration failed: $($_.Exception.Message)" }
        try { Install-HermesPlugin } catch { Warn "Hermes integration failed: $($_.Exception.Message)" }
        try { Install-CodexSkill } catch { Warn "Codex skill integration failed: $($_.Exception.Message)" }
        try { Install-CodexMcp } catch { Warn "Codex MCP integration failed: $($_.Exception.Message)" }
        try { Install-ClaudeCodeMcp } catch { Warn "Claude Code MCP integration failed: $($_.Exception.Message)" }
        try { Install-ClaudeCodePreflightHook } catch { Warn "Claude Code hook integration failed: $($_.Exception.Message)" }
        try { Install-ClaudeDesktopMcp } catch { Warn "Claude Desktop integration failed: $($_.Exception.Message)" }
    } else {
        Info "Host integrations and scheduled tasks preserved by -NoStart staging mode"
        $CodexSkillStatus = "skipped (-NoStart)"
        $CodexMcpStatus = "skipped (-NoStart)"
        $ClaudeCodeMcpStatus = "skipped (-NoStart)"
        $ClaudeCodeHookStatus = "skipped (-NoStart)"
        $ClaudeDesktopStatus = "skipped (-NoStart)"
    }
    $script:InstallCompleted = $true
} catch {
    $failure = $_.Exception.Message
    $rollbackFailure = ""
    if ($transactionStarted) {
        try {
            Restore-InstallTransaction
        } catch {
            $rollbackFailure = $_.Exception.Message
        }
    }
    if (-not $transactionStarted) {
        Write-Host "[time-library-windows-install ERROR] $failure; production files were not changed" -ForegroundColor Red
    } elseif ($rollbackFailure) {
        Write-Host "[time-library-windows-install ERROR] $failure; $rollbackFailure" -ForegroundColor Red
    } else {
        Write-Host "[time-library-windows-install ERROR] $failure; prior installation state restored" -ForegroundColor Red
    }
    exit 1
} finally {
    if ($InstallCompleted) {
        try { Remove-PreviousVenvBackup } catch { Warn "temporary venv backup cleanup failed: $($_.Exception.Message)" }
    }
    try { Remove-PreparedPythonAssets } catch { Warn "temporary dependency cleanup failed: $($_.Exception.Message)" }
    try { Release-InstallTransactionLock } catch { Warn "install transaction lock cleanup failed: $($_.Exception.Message)" }
}

Write-Host ""
Write-Host "Time Library Windows full install complete."
Write-Host "Install root: $InstallRoot"
Write-Host "Console: front-door discovery file (preferred port $FrontDoorPort)"
Write-Host "Internal services: private loopback components; clients must read runtime/front_door_port"
if ((-not $NoStart) -and (-not $NoAutostart)) { Write-Host "Guardian: MemcoreCloudGuardianLogon, MemcoreCloudGuardianHealth" }
if ((-not $NoStart) -and (-not $NoAutostart) -and (-not $NoTray)) { Write-Host "Tray: MemcoreCloudTray" }
Write-Host "Native smoke: powershell -ExecutionPolicy Bypass -File `"$InstallRoot\tools\windows_native_smoke.ps1`" -InstallRoot `"$InstallRoot`""
Write-Host "Codex skill: $CodexSkillStatus"
Write-Host "Codex MCP: $CodexMcpStatus"
Write-Host "Claude Code MCP: $ClaudeCodeMcpStatus"
Write-Host "Claude Code preflight hook: $ClaudeCodeHookStatus"
Write-Host "Claude Desktop MCP: $ClaudeDesktopStatus"
Write-Host "Hermes skill: $(if ($NoStart -or $SkipHermes) { 'skipped' } else { 'time-library' })"
