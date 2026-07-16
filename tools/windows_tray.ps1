#Requires -Version 5.1
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\time-library",
    [string]$ConsoleUrl = ""
)

$ErrorActionPreference = "Continue"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$RuntimeDir = Join-Path $InstallRoot "runtime"
$LogDir = Join-Path $InstallRoot "logs"
$Guardian = Join-Path $InstallRoot "tools\windows_guardian.ps1"
$GuardianStatus = Join-Path $RuntimeDir "guardian-status.json"
$TrayLog = Join-Path $LogDir "tray.out.log"
$TaskNames = @(
    "MemcoreCloudGuardianLogon",
    "MemcoreCloudGuardianHealth"
)
$AppIcon = $null

if ([string]::IsNullOrWhiteSpace($ConsoleUrl)) {
    $portFile = Join-Path $RuntimeDir "front_door_port"
    if (Test-Path -LiteralPath $portFile) {
        $port = (Get-Content -LiteralPath $portFile -Raw -Encoding ASCII).Trim()
        if ($port -match '^\d{1,5}$') { $ConsoleUrl = "http://127.0.0.1:$port" }
    }
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function U {
    param([string]$Codepoints)
    $chars = @()
    foreach ($part in ($Codepoints -split " ")) {
        if ([string]::IsNullOrWhiteSpace($part)) { continue }
        $chars += [char]([Convert]::ToInt32($part, 16))
    }
    return -join $chars
}

function Get-TrayTexts {
    $culture = [System.Globalization.CultureInfo]::CurrentUICulture.Name
    if ($culture -match "^zh") {
        return @{
            starting = "Time Library: " + (U "542F 52A8 4E2D")
            status_unavailable = (U "72B6 6001 6682 4E0D 53EF 7528 3002")
            running = "Time Library: " + (U "8FD0 884C 4E2D")
            watcher_attention = "Time Library: " + (U "5B88 62A4 9700 8981 5904 7406")
            raw_backfill_pending = "Time Library: " + (U "7B49 5F85 8865 626B")
            check_status_tip = "Time Library: " + (U "8BF7 67E5 770B 72B6 6001")
            console_offline = "Time Library: " + (U "63A7 5236 53F0 79BB 7EBF")
            console_not_responding = (U "63A7 5236 53F0 6682 672A 54CD 5E94 3002 5B88 62A4 4EFB 52A1 53EF 4EE5 5C1D 8BD5 6062 590D 0020 0077 0061 0074 0063 0068 0065 0072 3002")
            console_label = (U "63A7 5236 53F0 FF1A")
            watcher_label = (U "76D1 542C FF1A")
            watcher_running = (U "8FD0 884C 4E2D")
            watcher_not_running = (U "672A 8FD0 884C")
            raw_lagging_label = (U "5F85 8865 626B 6765 6E90 FF1A")
            record_guard_label = (U "8BB0 5F55 5B88 62A4 FF1A")
            record_catching_up_label = (U "6B63 5728 8FFD 5C3E FF1A")
            record_backfill_needed_label = (U "5EFA 8BAE 56DE 586B FF1A")
            unavailable = (U "4E0D 53EF 7528")
            local_capture_label = (U "672C 5730 91C7 96C6 FF1A")
            local_capture_ok = (U "6B63 5E38")
            local_capture_attention = (U "9700 5904 7406")
            guardian_missing = (U "5B88 62A4 811A 672C 7F3A 5931 FF1A")
            guardian_status_missing = (U "5B88 62A4 72B6 6001 8FD8 6CA1 6709 5199 5165 3002")
            open_console = (U "6253 5F00 63A7 5236 53F0")
            check_status = (U "67E5 770B 72B6 6001")
            run_guardian_now = (U "7ACB 5373 5B88 62A4 8865 626B")
            open_guardian_status = (U "6253 5F00 5B88 62A4 72B6 6001")
            open_logs = (U "6253 5F00 65E5 5FD7")
            pause_guardian = (U "6682 505C 5B88 62A4 4EFB 52A1")
            resume_guardian = (U "6062 590D 5B88 62A4 4EFB 52A1")
            exit_tray = (U "9000 51FA 6258 76D8 56FE 6807")
        }
    }
    return @{
        starting = "Time Library: starting"
        status_unavailable = "Status is not available yet."
        running = "Time Library: running"
        watcher_attention = "Time Library: watcher needs attention"
        raw_backfill_pending = "Time Library: raw backfill pending"
        check_status_tip = "Time Library: check status"
        console_offline = "Time Library: console offline"
        console_not_responding = "Console is not responding. Guardian can try to restart the watcher."
        console_label = "Console: "
        watcher_label = "Watcher: "
        watcher_running = "running"
        watcher_not_running = "not running"
        raw_lagging_label = "Raw lagging sources: "
        record_guard_label = "Record Guard: "
        record_catching_up_label = "Catching up: "
        record_backfill_needed_label = "Backfill needed: "
        unavailable = "unavailable"
        local_capture_label = "Local capture: "
        local_capture_ok = "ok"
        local_capture_attention = "needs attention"
        guardian_missing = "Guardian script is missing:"
        guardian_status_missing = "Guardian status has not been written yet."
        open_console = "Open Console"
        check_status = "Check Status"
        run_guardian_now = "Run Guardian Now"
        open_guardian_status = "Open Guardian Status"
        open_logs = "Open Logs"
        pause_guardian = "Pause Guardian Tasks"
        resume_guardian = "Resume Guardian Tasks"
        exit_tray = "Exit Tray Icon"
    }
}

function T {
    param([string]$Key)
    return [string]$script:TrayTexts[$Key]
}

function New-FallbackTimeLibraryIcon {
    $bitmap = New-Object System.Drawing.Bitmap(32, 32)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(13, 38, 66))
        $graphics.FillEllipse($brush, 2, 4, 28, 24)
        $brush.Dispose()
        $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(214, 174, 103), 2)
        $graphics.DrawArc($pen, 4, 5, 24, 21, 20, 300)
        $graphics.DrawLine($pen, 16, 9, 16, 19)
        $graphics.DrawLine($pen, 16, 19, 22, 19)
        $graphics.DrawRectangle($pen, 11, 10, 10, 10)
        $pen.Dispose()
        return [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
    } finally {
        $graphics.Dispose()
    }
}

function New-TimeLibraryTrayIcon {
    $candidates = @(
        (Join-Path $InstallRoot "assets\brand\time-library-emblem.ico"),
        (Join-Path $InstallRoot "assets\brand\time-library-emblem.png"),
        (Join-Path $InstallRoot "web\assets\time_library_emblem.ico"),
        (Join-Path $InstallRoot "web\assets\time_library_emblem.png")
    )
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        try {
            if ([System.IO.Path]::GetExtension($candidate).ToLowerInvariant() -eq ".ico") {
                return New-Object System.Drawing.Icon($candidate)
            }
            $source = New-Object System.Drawing.Bitmap($candidate)
            $small = New-Object System.Drawing.Bitmap($source, 32, 32)
            $handle = $small.GetHicon()
            return [System.Drawing.Icon]::FromHandle($handle)
        } catch {
            Write-TrayLog ("icon load failed: " + $candidate + " " + $_.Exception.Message)
        }
    }
    return New-FallbackTimeLibraryIcon
}

function Now-Iso {
    return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function Write-TrayLog {
    param([string]$Message)
    Add-Content -LiteralPath $TrayLog -Value ((Now-Iso) + " " + $Message) -Encoding UTF8
}

function Get-HealthSummary {
    $summary = [ordered]@{
        ok = $false
        tooltip = (T "starting")
        detail = (T "status_unavailable")
    }
    try {
        $health = Invoke-RestMethod -Uri ($ConsoleUrl.TrimEnd("/") + "/api/health") -TimeoutSec 3
        $watcher = $null
        try {
            $watcher = Invoke-RestMethod -Uri ($ConsoleUrl.TrimEnd("/") + "/api/watcher") -TimeoutSec 3
        } catch { }
        $sync = $null
        try {
            $sync = Invoke-RestMethod -Uri ($ConsoleUrl.TrimEnd("/") + "/api/v1/source-systems/continuous-sync/status") -TimeoutSec 5
        } catch { }
        $recordGuardian = $null
        try {
            $recordGuardian = Invoke-RestMethod -Uri ($ConsoleUrl.TrimEnd("/") + "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1") -TimeoutSec 5
        } catch { }

        $watcherActive = $false
        if ($watcher -and $watcher.active -eq $true) { $watcherActive = $true }
        if ($sync -and $sync.watcher -and $sync.watcher.active -eq $true) { $watcherActive = $true }

        $lagging = 0
        if ($sync -and $sync.summary -and $null -ne $sync.summary.raw_lagging_source_count) {
            $lagging = [int]$sync.summary.raw_lagging_source_count
        }
        $localOk = $true
        if ($sync -and $sync.summary -and $sync.summary.local_capture_ok -eq $false) {
            $localOk = $false
        }
        $recordSummary = $null
        if ($recordGuardian -and $recordGuardian.summary) {
            $recordSummary = $recordGuardian.summary
        }
        $recordGuardAvailable = ($recordSummary -ne $null)
        $recordCount = 0
        $recordGuarded = 0
        $recordCatchingUp = 0
        $recordBackfillNeeded = 0
        if ($recordGuardAvailable) {
            if ($null -ne $recordSummary.record_count) { $recordCount = [int]$recordSummary.record_count }
            if ($null -ne $recordSummary.record_guarded_count) { $recordGuarded = [int]$recordSummary.record_guarded_count }
            if ($null -ne $recordSummary.raw_catching_up_count) { $recordCatchingUp = [int]$recordSummary.raw_catching_up_count }
            if ($null -ne $recordSummary.backfill_recommended_count) { $recordBackfillNeeded = [int]$recordSummary.backfill_recommended_count }
        }
        $ok = ($health -ne $null) -and $watcherActive -and ($lagging -eq 0) -and $localOk -and $recordGuardAvailable -and ($recordBackfillNeeded -eq 0)
        $summary.ok = $ok
        $summary.tooltip = if ($ok) {
            (T "running")
        } elseif (-not $watcherActive) {
            (T "watcher_attention")
        } elseif ($lagging -gt 0 -or $recordBackfillNeeded -gt 0) {
            (T "raw_backfill_pending")
        } else {
            (T "check_status_tip")
        }
        $recordGuardText = if ($recordGuardAvailable) {
            ([string]$recordGuarded) + "/" + ([string]$recordCount)
        } else {
            (T "unavailable")
        }
        $summary.detail = @(
            (T "console_label") + $ConsoleUrl
            (T "watcher_label") + ($(if ($watcherActive) { (T "watcher_running") } else { (T "watcher_not_running") }))
            (T "record_guard_label") + $recordGuardText
            (T "record_catching_up_label") + [string]$recordCatchingUp
            (T "record_backfill_needed_label") + [string]$recordBackfillNeeded
            (T "raw_lagging_label") + [string]$lagging
            (T "local_capture_label") + ($(if ($localOk) { (T "local_capture_ok") } else { (T "local_capture_attention") }))
        ) -join "`n"
    } catch {
        $summary.ok = $false
        $summary.tooltip = (T "console_offline")
        $summary.detail = (T "console_not_responding") + "`n" + $_.Exception.Message
    }
    return $summary
}

function Invoke-RecordGuardianBackfill {
    try {
        $body = @{ limit = 80 } | ConvertTo-Json -Depth 3
        $tokenPath = Join-Path $RuntimeDir "console_token"
        $headers = @{}
        if (Test-Path -LiteralPath $tokenPath) {
            $token = (Get-Content -LiteralPath $tokenPath -Raw -Encoding UTF8).Trim()
            if (-not [string]::IsNullOrWhiteSpace($token)) {
                $headers["X-Memcore-Console-Token"] = $token
                $headers["Origin"] = $ConsoleUrl
            }
        }
        Invoke-RestMethod `
            -Method Post `
            -Uri ($ConsoleUrl.TrimEnd("/") + "/api/v1/records/guardian/backfill") `
            -Body $body `
            -Headers $headers `
            -ContentType "application/json" `
            -TimeoutSec 10 | Out-Null
        Write-TrayLog "record guardian backfill invoked"
    } catch {
        Write-TrayLog ("record guardian backfill failed: " + $_.Exception.Message)
    }
}

function Invoke-Guardian {
    $powershellExe = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path -LiteralPath $Guardian)) {
        [System.Windows.Forms.MessageBox]::Show(
            (T "guardian_missing") + "`n$Guardian",
            "Time Library",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
        return
    }
    Invoke-RecordGuardianBackfill
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $Guardian,
        "-InstallRoot", $InstallRoot,
        "-StartWatcher",
        "-Backfill",
        "-Quiet"
    )
    Start-Process -FilePath $powershellExe -ArgumentList $args -WindowStyle Hidden | Out-Null
    Write-TrayLog "guardian invoked"
}

function Set-GuardianTasksEnabled {
    param([bool]$Enabled)
    foreach ($taskName in $TaskNames) {
        try {
            if ($Enabled) {
                Enable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
            } else {
                Disable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
            }
        } catch { }
    }
    Write-TrayLog ("guardian tasks enabled=" + [string]$Enabled)
}

function Get-GuardianTasksEnabled {
    foreach ($taskName in $TaskNames) {
        try {
            $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            if ($task -and $task.State -ne "Disabled") { return $true }
        } catch { }
    }
    return $false
}

function Show-StatusBalloon {
    param($NotifyIcon)
    $summary = Get-HealthSummary
    $NotifyIcon.Icon = $script:AppIcon
    $NotifyIcon.Text = $summary.tooltip.Substring(0, [Math]::Min(63, $summary.tooltip.Length))
    $NotifyIcon.BalloonTipTitle = "Time Library"
    $NotifyIcon.BalloonTipText = $summary.detail
    $NotifyIcon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
    $NotifyIcon.ShowBalloonTip(5000)
}

function Open-Console {
    Start-Process $ConsoleUrl | Out-Null
    Write-TrayLog "console opened"
}

function Open-Logs {
    if (Test-Path -LiteralPath $LogDir) {
        Start-Process explorer.exe $LogDir | Out-Null
    }
}

function Open-GuardianStatus {
    if (Test-Path -LiteralPath $GuardianStatus) {
        Start-Process notepad.exe $GuardianStatus | Out-Null
    } else {
        [System.Windows.Forms.MessageBox]::Show(
            (T "guardian_status_missing"),
            "Time Library",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    }
}

$context = New-Object System.Windows.Forms.ApplicationContext
$notify = New-Object System.Windows.Forms.NotifyIcon
$script:TrayTexts = Get-TrayTexts
$AppIcon = New-TimeLibraryTrayIcon
$notify.Icon = $AppIcon
$notify.Text = "Time Library"
$notify.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip

$openItem = $menu.Items.Add((T "open_console"))
$openItem.add_Click({ Open-Console })

$statusItem = $menu.Items.Add((T "check_status"))
$statusItem.add_Click({ Show-StatusBalloon $notify })

$guardianItem = $menu.Items.Add((T "run_guardian_now"))
$guardianItem.add_Click({
    Invoke-Guardian
    Start-Sleep -Milliseconds 600
    Show-StatusBalloon $notify
})

$statusFileItem = $menu.Items.Add((T "open_guardian_status"))
$statusFileItem.add_Click({ Open-GuardianStatus })

$logsItem = $menu.Items.Add((T "open_logs"))
$logsItem.add_Click({ Open-Logs })

$menu.Items.Add("-") | Out-Null

$pauseItem = $menu.Items.Add((T "pause_guardian"))
$pauseItem.add_Click({
    Set-GuardianTasksEnabled -Enabled $false
    Show-StatusBalloon $notify
})

$resumeItem = $menu.Items.Add((T "resume_guardian"))
$resumeItem.add_Click({
    Set-GuardianTasksEnabled -Enabled $true
    Invoke-Guardian
    Show-StatusBalloon $notify
})

$menu.Items.Add("-") | Out-Null

$exitItem = $menu.Items.Add((T "exit_tray"))
$exitItem.add_Click({
    Write-TrayLog "tray exited by user"
    $notify.Visible = $false
    $notify.Dispose()
    $context.ExitThread()
})

$menu.add_Opening({
    $enabled = Get-GuardianTasksEnabled
    $pauseItem.Enabled = $enabled
    $resumeItem.Enabled = -not $enabled
})

$notify.ContextMenuStrip = $menu
$notify.add_DoubleClick({ Open-Console })

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 30000
$timer.add_Tick({
    $summary = Get-HealthSummary
    $notify.Icon = $script:AppIcon
    $notify.Text = $summary.tooltip.Substring(0, [Math]::Min(63, $summary.tooltip.Length))
})
$timer.Start()

Write-TrayLog "tray started"
Invoke-Guardian
Show-StatusBalloon $notify
[System.Windows.Forms.Application]::Run($context)
