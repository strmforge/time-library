#Requires -Version 5.1
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\memcore-cloud",
    [string]$RawGatewayUrl = "http://127.0.0.1:9851",
    [switch]$SkipCodex,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$Report = [ordered]@{
    tool = "windows_native_smoke"
    target = "native_windows"
    install_root = $InstallRoot
    raw_gateway_url = $RawGatewayUrl
    ok = $false
    checks = @()
}

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
    if (-not $Json) {
        $mark = if ($Ok) { "ok" } else { "fail" }
        Write-Host ("[{0}] {1} {2}" -f $mark, $Name, $Detail)
    }
}

function Finish-Report {
    param([bool]$Ok)
    $script:Report.ok = $Ok
    if ($Json) {
        $script:Report | ConvertTo-Json -Depth 12
    }
    if (-not $Ok) { exit 1 }
}

function Fail-Smoke {
    param([string]$Name, [string]$Detail)
    Add-Check -Name $Name -Ok $false -Detail $Detail
    Finish-Report -Ok $false
}

function Test-PathRequired {
    param([string]$Name, [string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        Fail-Smoke -Name $Name -Detail "missing: $Path"
    }
    Add-Check -Name $Name -Ok $true -Detail $Path
}

function Read-Version {
    $versionPath = Join-Path $InstallRoot "VERSION"
    Test-PathRequired -Name "install_root" -Path $InstallRoot
    Test-PathRequired -Name "version_file" -Path $versionPath
    $version = (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8).Trim()
    Add-Check -Name "version" -Ok $true -Detail $version
    $script:Report["version"] = $version
}

function Smoke-Http {
    param([string]$Name, [string]$Url)
    try {
        $resp = Invoke-WebRequest -Uri $Url -TimeoutSec 6 -UseBasicParsing
        Add-Check -Name $Name -Ok $true -Detail ("HTTP {0}" -f [int]$resp.StatusCode)
    } catch {
        Fail-Smoke -Name $Name -Detail $_.Exception.Message
    }
}

function Test-ZhiyiModelBinding {
    $consoleUrl = "http://127.0.0.1:9850"
    $bindingPath = Join-Path $InstallRoot "config\zhiyi_model_binding.user.json"
    $bindingStampBefore = $null
    if (Test-Path -LiteralPath $bindingPath) {
        $bindingStampBefore = (Get-Item -LiteralPath $bindingPath).LastWriteTimeUtc.Ticks
    }

    try {
        $resp = Invoke-WebRequest -Uri ($consoleUrl + "/") -TimeoutSec 8 -UseBasicParsing
        $html = [string]$resp.Content
    } catch {
        Fail-Smoke -Name "zhiyi_model_ui" -Detail $_.Exception.Message
    }

    $requiredUi = @(
        "zhiyi.modelTitle",
        "zhiyi-model-provider",
        "zhiyi-model-provider-id",
        "zhiyi-model-name",
        "zhiyi-model-base-url",
        "zhiyi-model-api-key-env",
        "/api/v1/zhiyi/model-options",
        "/api/v1/zhiyi/model-binding/apply"
    )
    $missingUi = @()
    foreach ($needle in $requiredUi) {
        if ($html -notlike ("*" + $needle + "*")) { $missingUi += $needle }
    }
    if ($missingUi.Count -gt 0) {
        Fail-Smoke -Name "zhiyi_model_ui" -Detail ("missing: " + ($missingUi -join ","))
    }

    $forbiddenUi = @("本机工具识别模型", "Local Tool Recognition Model", "recognition-model")
    $leakedUi = @()
    foreach ($needle in $forbiddenUi) {
        if ($html -like ("*" + $needle + "*")) { $leakedUi += $needle }
    }
    if ($leakedUi.Count -gt 0) {
        Fail-Smoke -Name "zhiyi_model_ui" -Detail ("legacy standalone recognition model UI leaked: " + ($leakedUi -join ","))
    }
    Add-Check -Name "zhiyi_model_ui" -Ok $true -Detail "unified Zhiyi model controls present"

    try {
        $options = Invoke-RestMethod -Uri ($consoleUrl + "/api/v1/zhiyi/model-options") -TimeoutSec 10
    } catch {
        Fail-Smoke -Name "zhiyi_model_options" -Detail $_.Exception.Message
    }
    $optionCount = @($options.options).Count
    if ($optionCount -lt 1) {
        Fail-Smoke -Name "zhiyi_model_options" -Detail "no model options returned"
    }
    if (-not $options.user_default) {
        Fail-Smoke -Name "zhiyi_model_options" -Detail "missing user_default state"
    }
    Add-Check -Name "zhiyi_model_options" -Ok $true -Detail ("options=" + [string]$optionCount)

    $body = [ordered]@{
        manual_override = $true
        provider = "Manual"
        provider_id = "manual-openai-compatible"
        model_name = "memcore-smoke-model"
        base_url = "http://127.0.0.1:9/v1"
        api_key_env = "MEMCORE_ZHIYI_API_KEY"
        save_as_user_default = $true
    } | ConvertTo-Json -Depth 10 -Compress
    try {
        $plan = Invoke-RestMethod `
            -Uri ($consoleUrl + "/api/v1/zhiyi/model-binding/dry-run") `
            -Method Post `
            -ContentType "application/json" `
            -Body $body `
            -TimeoutSec 10
    } catch {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail $_.Exception.Message
    }
    if (-not $plan.ok) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "plan not ok"
    }
    if ($plan.dry_run -ne $true) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "dry_run flag is not true"
    }
    if ($plan.write_performed -ne $false -or $plan.config_write_performed -ne $false -or $plan.runtime_binding_write_performed -ne $false) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "dry-run attempted to write"
    }
    $would = $plan.would_write_user_default
    if (-not $would) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "missing would_write_user_default"
    }
    if ($would.model_name -ne "memcore-smoke-model") {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "manual model was not preserved"
    }
    if ($would.api_key_env -ne "MEMCORE_ZHIYI_API_KEY") {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "API key env name was not preserved"
    }
    if ($would.secrets_stored -ne $false) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "dry-run claims a secret would be stored"
    }
    if ($would.model_call_performed -ne $false) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "dry-run claims a model call was performed"
    }
    if ($would.applies_to -notcontains "zhiyi_frontstage" -or $would.applies_to -notcontains "local_tool_identification") {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "unified Zhiyi model does not cover local tool identification"
    }

    $bindingStampAfter = $null
    if (Test-Path -LiteralPath $bindingPath) {
        $bindingStampAfter = (Get-Item -LiteralPath $bindingPath).LastWriteTimeUtc.Ticks
    }
    if ($bindingStampBefore -ne $bindingStampAfter) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "dry-run changed zhiyi_model_binding.user.json"
    }

    $script:Report["zhiyi_model"] = [ordered]@{
        option_count = [int]$optionCount
        user_default_configured = [bool]$options.user_default.configured
        dry_run_write_performed = [bool]$plan.write_performed
        secrets_stored = [bool]$would.secrets_stored
        model_call_performed = [bool]$would.model_call_performed
    }
    Add-Check -Name "zhiyi_model_binding_dry_run" -Ok $true -Detail "no write, no secret, no model call"
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

function Get-AuthorizedP0WatcherProcesses {
    $escapedRoot = [regex]::Escape($InstallRoot)
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $roots = @($processes | Where-Object {
        $cmd = [string]$_.CommandLine
        (-not [string]::IsNullOrWhiteSpace($cmd)) -and
        ($cmd -match $escapedRoot) -and
        ($cmd -match "p0-watcher\.cmd")
    })
    if ($roots.Count -eq 0) { return @() }
    $treeIds = Get-ProcessTree -Processes $processes -RootProcessIds @($roots | ForEach-Object { [int]$_.ProcessId })
    return @($processes | Where-Object { $treeIds.Contains([int]$_.ProcessId) })
}

function Invoke-CapabilityCheck {
    $endpoint = ($RawGatewayUrl.TrimEnd("/") + "/mcp")
    $body = [ordered]@{
        jsonrpc = "2.0"
        id = "windows-native-smoke"
        method = "tools/call"
        params = [ordered]@{
            name = "zhiyi_recall"
            arguments = [ordered]@{
                query = "capability check"
                mode = "capability_check"
                consumer = "windows-native-smoke"
                request_id = "windows-native-smoke-capability"
            }
        }
    } | ConvertTo-Json -Depth 10 -Compress

    try {
        $resp = Invoke-RestMethod -Uri $endpoint -Method Post -ContentType "application/json" -Body $body -TimeoutSec 10
    } catch {
        Fail-Smoke -Name "capability_check" -Detail $_.Exception.Message
    }

    if ($resp.error) {
        Fail-Smoke -Name "capability_check" -Detail ($resp.error | ConvertTo-Json -Compress)
    }
    if (-not $resp.result) {
        Fail-Smoke -Name "capability_check" -Detail "missing JSON-RPC result"
    }

    $payload = $resp.result.structuredContent
    if (-not $payload -and $resp.result.content -and $resp.result.content.Count -gt 0) {
        try {
            $payload = $resp.result.content[0].text | ConvertFrom-Json
        } catch {
            Fail-Smoke -Name "capability_check" -Detail "result content is not JSON"
        }
    }
    if (-not $payload) {
        Fail-Smoke -Name "capability_check" -Detail "missing structuredContent"
    }

    $tools = @($payload.mcp_tools)
    $problems = @()
    if ($payload.mode -ne "capability_check") { $problems += "mode" }
    if ($payload.service -ne "raw_consumption_gateway") { $problems += "service" }
    if ($payload.server -ne "yifanchen-zhiyi") { $problems += "server" }
    if ($payload.read_only -ne $true) { $problems += "read_only" }
    if ($payload.recall_performed -ne $false) { $problems += "recall_performed" }
    if ($payload.raw_excerpt_returned -ne $false) { $problems += "raw_excerpt_returned" }
    if (-not ($tools -contains "zhiyi_recall")) { $problems += "mcp_tools" }

    if ($problems.Count -gt 0) {
        Fail-Smoke -Name "capability_check" -Detail ("unexpected fields: " + ($problems -join ","))
    }

    $script:Report["capability"] = [ordered]@{
        service = [string]$payload.service
        server = [string]$payload.server
        version = [string]$payload.version
        read_only = [bool]$payload.read_only
        recall_performed = [bool]$payload.recall_performed
        raw_excerpt_returned = [bool]$payload.raw_excerpt_returned
        mcp_tools = $tools
    }
    Add-Check -Name "capability_check" -Ok $true -Detail ("version " + [string]$payload.version)
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
        if (-not (Test-Path -LiteralPath $file)) { continue }
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
                if ($candidate -and (Test-Path -LiteralPath $candidate)) {
                    return $candidate
                }
            }
        } catch { }
    }
    return $null
}

function Convert-TomlScalarForSmoke {
    param([string]$Value)
    $text = ([string]$Value).Trim()
    if ($text -match '^"((?:\\"|[^"])*)"') {
        return ($matches[1] -replace '\\"', '"')
    }
    if ($text -match "^'([^']*)'") {
        return $matches[1]
    }
    if ($text -match "^(true|false)\b") {
        return ($matches[1].ToLowerInvariant() -eq "true")
    }
    return (($text -split "\s+#", 2)[0]).Trim()
}

function Read-CodexConfigForSmoke {
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
    $configPath = Join-Path $codexHome "config.toml"
    if (-not (Test-Path -LiteralPath $configPath)) {
        return [ordered]@{
            path = $configPath
            exists = $false
            model = ""
            model_provider = ""
            provider_section_exists = $false
            base_url = ""
            wire_api = ""
        }
    }

    $top = @{}
    $sections = @{}
    $currentSection = ""
    foreach ($line in (Get-Content -LiteralPath $configPath -Encoding UTF8)) {
        $trimmed = ([string]$line).Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) { continue }
        if ($trimmed -match "^\[([^\]]+)\]\s*$") {
            $currentSection = $matches[1].Trim()
            if (-not $sections.ContainsKey($currentSection)) { $sections[$currentSection] = @{} }
            continue
        }
        if ($trimmed -notmatch "^([A-Za-z0-9_.-]+)\s*=\s*(.+)$") { continue }
        $key = $matches[1]
        $value = Convert-TomlScalarForSmoke -Value $matches[2]
        if ([string]::IsNullOrWhiteSpace($currentSection)) {
            $top[$key] = $value
        } elseif ($sections.ContainsKey($currentSection)) {
            $sections[$currentSection][$key] = $value
        }
    }

    $provider = [string]($top["model_provider"])
    $sectionName = if ($provider) { "model_providers." + $provider } else { "" }
    $section = if ($sectionName -and $sections.ContainsKey($sectionName)) { $sections[$sectionName] } else { @{} }
    return [ordered]@{
        path = $configPath
        exists = $true
        model = [string]($top["model"])
        model_provider = $provider
        provider_section = $sectionName
        provider_section_exists = [bool]($sectionName -and $sections.ContainsKey($sectionName))
        base_url = [string]($section["base_url"])
        wire_api = [string]($section["wire_api"])
    }
}

function Get-HttpStatusCodeForSmoke {
    param(
        [string]$Url,
        [string]$Method = "Get",
        [string]$Body = ""
    )
    try {
        if ($Method -eq "Post") {
            $resp = Invoke-WebRequest -Uri $Url -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 15 -UseBasicParsing
        } else {
            $resp = Invoke-WebRequest -Uri $Url -TimeoutSec 8 -UseBasicParsing
        }
        return [int]$resp.StatusCode
    } catch {
        $response = $_.Exception.Response
        if ($response -and $response.StatusCode) {
            return [int]$response.StatusCode
        }
        return 0
    }
}

function Test-CodexProviderBucket {
    if ($SkipCodex) {
        Add-Check -Name "codex_provider_bucket" -Ok $true -Detail "skipped"
        return
    }

    $config = Read-CodexConfigForSmoke
    if (-not $config.exists) {
        Add-Check -Name "codex_provider_bucket" -Ok $true -Detail ("Codex config missing; provider route probe skipped: " + [string]$config.path)
        $script:Report["codex_provider_bucket"] = [ordered]@{
            config_path = [string]$config.path
            exists = $false
            route_probe_required = $false
            reason = "codex_config_missing"
        }
        return
    }
    if ([string]::IsNullOrWhiteSpace($config.model_provider)) {
        Add-Check -Name "codex_provider_bucket" -Ok $true -Detail "no explicit provider bucket; official/default Codex route"
        $script:Report["codex_provider_bucket"] = [ordered]@{
            config_path = [string]$config.path
            exists = $true
            model = [string]$config.model
            model_provider = ""
            provider_bucket_matches_section = $false
            route_probe_required = $false
            reason = "official_or_default_codex_route"
        }
        return
    }
    Add-Check -Name "codex_provider_bucket" -Ok $true -Detail ("model_provider=" + [string]$config.model_provider)

    if (-not $config.provider_section_exists) {
        Fail-Smoke -Name "provider_bucket_matches_section" -Detail ("missing [" + [string]$config.provider_section + "]")
    }
    Add-Check -Name "provider_bucket_matches_section" -Ok $true -Detail ("found [" + [string]$config.provider_section + "]")

    if ([string]::IsNullOrWhiteSpace($config.base_url)) {
        Fail-Smoke -Name "codex_provider_bucket" -Detail "selected provider section is missing base_url"
    }
    if ([string]::IsNullOrWhiteSpace($config.wire_api)) {
        Fail-Smoke -Name "codex_provider_bucket" -Detail "selected provider section is missing wire_api"
    }

    $base = ([string]$config.base_url).TrimEnd("/")
    $usesLocalCcSwitchProxy = (
        $base -eq "http://127.0.0.1:15721/v1" -or
        $base -eq "http://localhost:15721/v1"
    )
    if ($usesLocalCcSwitchProxy -and ([string]$config.model_provider).ToLowerInvariant() -ne "token") {
        Fail-Smoke -Name "codex_provider_bucket_drift" -Detail "127.0.0.1:15721 CC Switch route expects model_provider=token; provider bucket drift breaks Codex even when the relay is healthy"
    }

    $modelsStatus = $null
    $responsesStatus = $null
    $healthStatus = $null
    if ($usesLocalCcSwitchProxy) {
        $proxyRoot = $base.Substring(0, $base.Length - 3)
        $healthStatus = Get-HttpStatusCodeForSmoke -Url ($proxyRoot + "/health")
        if ($healthStatus -ne 200) {
            Fail-Smoke -Name "codex_local_proxy_health" -Detail ("HTTP " + [string]$healthStatus)
        }
        Add-Check -Name "codex_local_proxy_health" -Ok $true -Detail "HTTP 200"

        $modelsStatus = Get-HttpStatusCodeForSmoke -Url ($base + "/models")
        Add-Check -Name "models_404_not_fatal" -Ok $true -Detail ("HTTP " + [string]$modelsStatus + " diagnostic only")

        $probeModel = if ([string]::IsNullOrWhiteSpace($config.model)) { "gpt-5.5" } else { [string]$config.model }
        $body = [ordered]@{
            model = $probeModel
            input = "Say OK only."
            max_output_tokens = 8
        } | ConvertTo-Json -Depth 8 -Compress
        $responsesStatus = Get-HttpStatusCodeForSmoke -Url ($base + "/responses") -Method "Post" -Body $body
        if ($responsesStatus -ne 200) {
            Fail-Smoke -Name "codex_responses_probe" -Detail ("HTTP " + [string]$responsesStatus)
        }
        Add-Check -Name "codex_responses_probe" -Ok $true -Detail "HTTP 200"
    }

    $script:Report["codex_provider_bucket"] = [ordered]@{
        config_path = [string]$config.path
        model = [string]$config.model
        model_provider = [string]$config.model_provider
        provider_bucket_matches_section = [bool]$config.provider_section_exists
        base_url = [string]$config.base_url
        wire_api = [string]$config.wire_api
        local_cc_switch_route = [bool]$usesLocalCcSwitchProxy
        health_status = $healthStatus
        models_status = $modelsStatus
        models_404_not_fatal = $true
        responses_status = $responsesStatus
    }
}

function Test-CodexMcp {
    if ($SkipCodex) {
        Add-Check -Name "codex_mcp" -Ok $true -Detail "skipped"
        return
    }

    $codexExe = Find-CodexCli
    if (-not $codexExe) {
        Fail-Smoke -Name "codex_cli" -Detail "codex.exe not found from PATH or native-host metadata"
    }
    Add-Check -Name "codex_cli" -Ok $true -Detail $codexExe

    $output = & $codexExe mcp list 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String)
    if ($exitCode -ne 0) {
        Fail-Smoke -Name "codex_mcp" -Detail ("codex mcp list failed: " + $text.Trim())
    }
    if ($text -notmatch "yifanchen-zhiyi") {
        Fail-Smoke -Name "codex_mcp" -Detail "yifanchen-zhiyi not found in codex mcp list"
    }
    Add-Check -Name "codex_mcp" -Ok $true -Detail "yifanchen-zhiyi enabled"
}

function Test-P0Watcher {
    $tree = @(Get-AuthorizedP0WatcherProcesses)
    $watchers = @($tree | Where-Object {
        $cmd = [string]$_.CommandLine
        (-not [string]::IsNullOrWhiteSpace($cmd)) -and
        (($cmd -match 'p0-watcher\.cmd') -or (($cmd -match 'memcore-cloud\.py') -and ($cmd -match '--watch')))
    })
    if ($watchers.Count -eq 0) {
        Fail-Smoke -Name "p0_watcher_process" -Detail "p0 watcher is not running; local Codex/OpenClaw/Kiro records will not be captured continuously"
    }
    Add-Check -Name "p0_watcher_process" -Ok $true -Detail ("authorized tree PID " + [string]$watchers[0].ProcessId)
}

function Test-ScheduledTaskPresent {
    param(
        [string]$Name,
        [bool]$Required = $true
    )
    $task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $task) {
        if ($Required) {
            Fail-Smoke -Name ("scheduled_task_" + $Name) -Detail "missing"
        }
        Add-Check -Name ("scheduled_task_" + $Name) -Ok $false -Detail "missing"
        return
    }
    $ok = $task.State -ne "Disabled"
    if (-not $ok -and $Required) {
        Fail-Smoke -Name ("scheduled_task_" + $Name) -Detail ("disabled state=" + [string]$task.State)
    }
    $actionArgs = (@($task.Actions | ForEach-Object { [string]$_.Arguments }) -join " ")
    $actionExe = (@($task.Actions | ForEach-Object { [string]$_.Execute }) -join " ")
    if ($Name -match "^MemcoreCloudGuardian") {
        if ($actionExe -notmatch "wscript\.exe") {
            Fail-Smoke -Name ("scheduled_task_" + $Name) -Detail "guardian task must use wscript hidden launcher; powershell.exe can flash a console window"
        }
        if ($actionArgs -notmatch "windows_hidden_guardian\.vbs") {
            Fail-Smoke -Name ("scheduled_task_" + $Name) -Detail "guardian hidden launcher is missing"
        }
    }
    if (($Name -eq "MemcoreCloudTray") -and ($actionArgs -notmatch "-WindowStyle\s+Hidden")) {
        Fail-Smoke -Name ("scheduled_task_" + $Name) -Detail "tray task action is not hidden; a console window may flash"
    }
    Add-Check -Name ("scheduled_task_" + $Name) -Ok $ok -Detail ("state=" + [string]$task.State)
}

function Test-GuardianAndTray {
    $guardian = Join-Path $InstallRoot "tools\windows_guardian.ps1"
    $hiddenGuardian = Join-Path $InstallRoot "tools\windows_hidden_guardian.vbs"
    $tray = Join-Path $InstallRoot "tools\windows_tray.ps1"
    Test-PathRequired -Name "windows_guardian_script" -Path $guardian
    Test-PathRequired -Name "windows_hidden_guardian_launcher" -Path $hiddenGuardian
    Test-PathRequired -Name "windows_tray_script" -Path $tray

    Test-ScheduledTaskPresent -Name "MemcoreCloudGuardianLogon"
    Test-ScheduledTaskPresent -Name "MemcoreCloudGuardianHealth"
    Test-ScheduledTaskPresent -Name "MemcoreCloudTray" -Required:$false

    $powershellExe = Join-Path $PSHOME "powershell.exe"
    $output = & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $guardian -InstallRoot $InstallRoot -StartWatcher -Backfill -Json 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String)
    if ($exitCode -ne 0) {
        Fail-Smoke -Name "windows_guardian_run" -Detail $text.Trim()
    }
    try {
        $payload = $text | ConvertFrom-Json
    } catch {
        Fail-Smoke -Name "windows_guardian_run" -Detail "guardian returned non-JSON"
    }
    if (-not $payload.ok) {
        Fail-Smoke -Name "windows_guardian_run" -Detail $text.Trim()
    }
    $statusPath = Join-Path $InstallRoot "runtime\guardian-status.json"
    Test-PathRequired -Name "windows_guardian_status" -Path $statusPath
    try {
        $statusPayload = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Fail-Smoke -Name "guardian_status_content" -Detail "guardian-status.json is not valid JSON"
    }
    if (-not $statusPayload.ok) {
        Fail-Smoke -Name "guardian_status_content" -Detail "guardian status file is not ok"
    }
    Add-Check -Name "guardian_status_content" -Ok $true -Detail "ok"
    Add-Check -Name "windows_guardian_run" -Ok $true -Detail "ok"
}

function Test-CodexCaptureStatus {
    if ($SkipCodex) {
        Add-Check -Name "codex_capture_status" -Ok $true -Detail "skipped"
        return
    }

    $python = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    $connector = Join-Path $InstallRoot "src\codex_local_connector.py"
    Test-PathRequired -Name "codex_connector" -Path $connector
    if (-not (Test-Path -LiteralPath $python)) {
        Fail-Smoke -Name "codex_capture_status" -Detail "missing venv python: $python"
    }

    $env:MEMCORE_ROOT = $InstallRoot
    $env:MEMCORE_INSTALL_ROOT = $InstallRoot
    $env:PYTHONPATH = $InstallRoot
    $output = & $python $connector --status 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String)
    if ($exitCode -ne 0) {
        Fail-Smoke -Name "codex_capture_status" -Detail ("codex connector status failed: " + $text.Trim())
    }

    try {
        $payload = $text | ConvertFrom-Json
    } catch {
        Fail-Smoke -Name "codex_capture_status" -Detail "codex connector status returned non-JSON"
    }

    if (-not $payload.capture_independent_of_mcp) {
        Fail-Smoke -Name "codex_capture_status" -Detail "codex capture must be independent of Skill/MCP consumer config"
    }
    if (-not $payload.reachable) {
        Fail-Smoke -Name "codex_capture_status" -Detail "Codex sessions root not reachable"
    }

    $rawSync = $payload.raw_sync
    if (-not $rawSync) {
        Fail-Smoke -Name "codex_capture_status" -Detail "missing raw_sync status"
    }
    if ($rawSync.status -eq "raw_lagging") {
        Fail-Smoke -Name "codex_capture_status" -Detail ("Codex source records are ahead of Yifanchen raw; missing/stale=" + [string]$rawSync.missing_or_stale_count)
    }
    if ($rawSync.status -eq "source_unreachable") {
        Fail-Smoke -Name "codex_capture_status" -Detail "Codex source records are unreachable"
    }

    $script:Report["codex_capture"] = [ordered]@{
        independent_of_mcp = [bool]$payload.capture_independent_of_mcp
        status = [string]$rawSync.status
        latest_source_mtime = [string]$rawSync.latest_source_mtime
        latest_raw_mtime = [string]$rawSync.latest_raw_mtime
        missing_or_stale_count = [int]$rawSync.missing_or_stale_count
    }
    Add-Check -Name "codex_capture_status" -Ok $true -Detail ("raw_sync=" + [string]$rawSync.status)
}

function Test-CodexConsumerMcpOptional {
    if ($SkipCodex) {
        Add-Check -Name "codex_consumer_mcp_optional" -Ok $true -Detail "skipped"
        return
    }

    $codexExe = Find-CodexCli
    if (-not $codexExe) {
        Add-Check -Name "codex_consumer_mcp_optional" -Ok $false -Detail "codex.exe not found; capture status is checked separately"
        return
    }

    $output = & $codexExe mcp list 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String)
    if ($exitCode -ne 0) {
        Add-Check -Name "codex_consumer_mcp_optional" -Ok $false -Detail ("codex mcp list failed: " + $text.Trim())
        return
    }
    if ($text -notmatch "yifanchen-zhiyi") {
        Add-Check -Name "codex_consumer_mcp_optional" -Ok $false -Detail "yifanchen-zhiyi missing from Codex consumer MCP; local capture still uses source files"
        return
    }
    Add-Check -Name "codex_consumer_mcp_optional" -Ok $true -Detail "yifanchen-zhiyi enabled"
}

Read-Version
Test-P0Watcher
Test-GuardianAndTray
Smoke-Http -Name "p3_health" -Url "http://127.0.0.1:9830/health"
Smoke-Http -Name "p4_health" -Url "http://127.0.0.1:9840/health"
Smoke-Http -Name "p6_health" -Url "http://127.0.0.1:9850/api/health"
Smoke-Http -Name "raw_health" -Url ($RawGatewayUrl.TrimEnd("/") + "/health")
Smoke-Http -Name "dialog_health" -Url "http://127.0.0.1:9860/health"
Test-ZhiyiModelBinding
Invoke-CapabilityCheck
Test-CodexProviderBucket
Test-CodexCaptureStatus
Test-CodexConsumerMcpOptional

Finish-Report -Ok $true
