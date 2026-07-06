#Requires -Version 5.1
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\time-library",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

function Add-CandidatePath {
    param(
        [System.Collections.Generic.List[string]]$Candidates,
        [string]$Path
    )
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    $Candidates.Add($Path)
}

function Get-ClaudeDesktopCandidateHomes {
    $candidates = New-Object System.Collections.Generic.List[string]
    Add-CandidatePath -Candidates $candidates -Path $env:CLAUDE_DESKTOP_HOME
    if ($env:APPDATA) {
        Add-CandidatePath -Candidates $candidates -Path (Join-Path $env:APPDATA "Claude")
    }
    if ($env:LOCALAPPDATA) {
        Add-CandidatePath -Candidates $candidates -Path (Join-Path $env:LOCALAPPDATA "Claude")
        Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "Claude-*" } |
            ForEach-Object { Add-CandidatePath -Candidates $candidates -Path $_.FullName }
        $packagesRoot = Join-Path $env:LOCALAPPDATA "Packages"
        Add-CandidatePath -Candidates $candidates -Path (Join-Path $packagesRoot "Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude")
        if (Test-Path -LiteralPath $packagesRoot) {
            Get-ChildItem -LiteralPath $packagesRoot -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -like "Claude_*" } |
                ForEach-Object {
                    Add-CandidatePath -Candidates $candidates -Path (Join-Path $_.FullName "LocalCache\Roaming\Claude")
                }
        }
    }
    if ($env:USERPROFILE) {
        Add-CandidatePath -Candidates $candidates -Path (Join-Path $env:USERPROFILE "AppData\Roaming\Claude")
        Add-CandidatePath -Candidates $candidates -Path (Join-Path $env:USERPROFILE "AppData\Local\Claude")
    }
    return @($candidates | Select-Object -Unique)
}

function Get-JsonProperty {
    param(
        [object]$Object,
        [string]$Name
    )
    if ($null -eq $Object) { return $null }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Redact-SecretValue {
    param([object]$Value)
    if ($null -eq $Value) { return $null }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return $text }
    return "[redacted]"
}

function Test-ArgContains {
    param(
        [object[]]$Values,
        [string]$Needle
    )
    foreach ($value in @($Values)) {
        if (([string]$value).Contains($Needle)) { return $true }
    }
    return $false
}

function Get-ArgAfter {
    param(
        [object[]]$Values,
        [string]$Flag
    )
    $items = @($Values)
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ([string]$items[$i] -eq $Flag) {
            if (($i + 1) -lt $items.Count) { return [string]$items[$i + 1] }
            return ""
        }
    }
    return ""
}

function Inspect-ClaudeHome {
    param([string]$ClaudeHome)
    $cfgPath = Join-Path $ClaudeHome "claude_desktop_config.json"
    $entry = [ordered]@{
        home = $ClaudeHome
        exists = [bool](Test-Path -LiteralPath $ClaudeHome)
        config_path = $cfgPath
        config_exists = [bool](Test-Path -LiteralPath $cfgPath)
        parse_ok = $false
        parse_error = ""
        has_yifanchen = $false
        command = ""
        command_exists = $false
        args = @()
        bridge_arg_present = $false
        endpoint = ""
        registry_arg_present = $false
        binding_key = ""
        env_memcore_root = ""
        env_registry = ""
        env_window_id_set = $false
        env_session_id_set = $false
        secret_fields_redacted = @()
    }
    if (-not $entry.config_exists) { return $entry }
    try {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $entry.parse_ok = $true
    } catch {
        $entry.parse_error = $_.Exception.Message
        return $entry
    }
    $servers = Get-JsonProperty -Object $cfg -Name "mcpServers"
    $server = Get-JsonProperty -Object $servers -Name "yifanchen-zhiyi"
    if ($null -eq $server) { return $entry }
    $entry.has_yifanchen = $true
    $command = [string](Get-JsonProperty -Object $server -Name "command")
    $serverArgs = @((Get-JsonProperty -Object $server -Name "args"))
    $envObj = Get-JsonProperty -Object $server -Name "env"
    $entry.command = $command
    $entry.command_exists = [bool]($command -and (Test-Path -LiteralPath $command))
    $entry.args = @($serverArgs)
    $entry.bridge_arg_present = Test-ArgContains -Values $serverArgs -Needle "claude_desktop_mcp_bridge.py"
    $entry.endpoint = Get-ArgAfter -Values $serverArgs -Flag "--endpoint"
    $entry.registry_flag_present = Test-ArgContains -Values $serverArgs -Needle "--window-binding-registry"
    $entry.registry_arg_present = Test-ArgContains -Values $serverArgs -Needle "window_binding_registry.json"
    $entry.binding_key = Get-ArgAfter -Values $serverArgs -Flag "--binding-key"
    $entry.env_memcore_root = [string](Get-JsonProperty -Object $envObj -Name "MEMCORE_ROOT")
    $entry.env_registry = [string](Get-JsonProperty -Object $envObj -Name "MEMCORE_WINDOW_BINDING_REGISTRY")
    $entry.env_window_id_set = -not [string]::IsNullOrWhiteSpace([string](Get-JsonProperty -Object $envObj -Name "MEMCORE_CLAUDE_DESKTOP_CANONICAL_WINDOW_ID"))
    $entry.env_session_id_set = -not [string]::IsNullOrWhiteSpace([string](Get-JsonProperty -Object $envObj -Name "MEMCORE_CLAUDE_DESKTOP_SESSION_ID"))

    $secretNames = @("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MEMCORE_DIALOG_ENTRY_TOKEN", "MEMCORE_ZHIYI_API_KEY")
    $redacted = @()
    foreach ($name in $secretNames) {
        $value = Get-JsonProperty -Object $envObj -Name $name
        if ($null -ne $value) {
            [void](Redact-SecretValue -Value $value)
            $redacted += $name
        }
    }
    $entry.secret_fields_redacted = $redacted
    return $entry
}

$homes = Get-ClaudeDesktopCandidateHomes
$candidateReports = @()
foreach ($candidateHome in $homes) {
    $candidateReports += (Inspect-ClaudeHome -ClaudeHome $candidateHome)
}

$foundConfigCount = @($candidateReports | Where-Object { $_.config_exists }).Count
$mcpPresentCount = @($candidateReports | Where-Object { $_.has_yifanchen }).Count
$healthyCount = @($candidateReports | Where-Object {
    $_.has_yifanchen -and $_.parse_ok -and $_.command_exists -and $_.bridge_arg_present -and
    ($_.endpoint -eq "http://127.0.0.1:9851/mcp") -and
    ($_.binding_key -eq "claude_desktop") -and
    ($_.env_memcore_root -eq $InstallRoot)
}).Count

$report = [ordered]@{
    ok = ($healthyCount -gt 0)
    tool = "windows_claude_mcp_status"
    install_root = $InstallRoot
    found_config_count = $foundConfigCount
    mcp_present_count = $mcpPresentCount
    healthy_config_count = $healthyCount
    candidates = $candidateReports
}

$jsonText = $report | ConvertTo-Json -Depth 10
if ($Json) {
    Write-Output $jsonText
} else {
    Write-Output $jsonText
}
