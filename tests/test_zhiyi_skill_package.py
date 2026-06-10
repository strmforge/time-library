import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "system" / "skills" / "yifanchen-zhiyi"
CLAUDE_SKILL_HELPER = ROOT / "tools" / "install_claude_desktop_skill.py"


def _load_claude_skill_helper():
    sys.modules.pop("install_claude_desktop_skill_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "install_claude_desktop_skill_under_test",
        CLAUDE_SKILL_HELPER,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_zhiyi_skill_package_is_platform_neutral():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    lowered = skill.lower()

    assert "version: 2026.6.11" in skill
    assert "prompt_version: 5" in skill
    assert "local memory library" in skill
    assert "active memory routing" in skill
    assert "standing active memory rule" in skill
    assert "one-time setup note" in skill
    assert "Identity Signal" in skill
    assert "Default Invocation Contract" in skill
    assert "Zhixing Preflight" in skill
    assert '"mode":"preflight"' in skill
    assert "decision" in skill
    assert "prompt_class" in skill
    assert "confidence" in skill
    assert "silence_reason" in skill
    assert "should_surface" in skill
    assert "must_surface" in skill
    assert "do_not_repeat" in skill
    assert "acceptance_checks" in skill
    assert "proactive_resurfacing_required" in skill
    assert "auto_entry_state=enter" in skill
    assert "auto_entry_state=retreat" in skill
    assert "auto_entry_state=bind_required" in skill
    assert "next_action" in skill
    assert "Do not expose preflight as a user-facing feature" in skill
    assert "Call `zhiyi_recall` first" in skill
    assert "If `zhiyi_recall` is not available" in skill
    assert "MCP/tool connection is missing" in skill
    assert "active layered" in skill
    assert "current window/session first" in skill
    assert "same project/workspace" in skill
    assert "same workstream/task" in skill
    assert "stable user preferences/tool facts" in skill
    assert "raw-pool/global only" in skill
    assert "when explicitly requested" in skill
    assert "scope_missing=true" in skill
    assert "recall_status=window_identity_required" in skill
    assert "explicit `memory_scope=window`" in skill
    assert "Do not say there is no memory" in skill
    assert "install, upgrade, or test status questions" in skill
    assert "定论" in skill
    assert "下一步" in skill
    assert "接下来呢" in skill
    assert "还有吗" in skill
    assert "然后呢" in skill
    assert "next step" in skill
    assert "what else" in skill
    assert "then what" in skill
    assert "Short follow-up phrases" in skill
    assert "raw records, Zhiyi, Xingce, toolbooks, and errata" in skill
    assert "Ambient Recall Discipline" in skill
    assert "Before making a product or engineering judgment" in skill
    assert "不是第一次" in skill
    assert "你忘了" in skill
    assert "之前纠正过" in skill
    assert "another idea" in skill
    assert "written to the knowledge base" in skill
    assert "Correction Entry" in skill
    assert "zhiyi_errata_candidate" in skill
    assert "Platform Capability Notes" in skill
    assert "When Hermes native review is triggered" in skill
    assert "Hermes can consume raw/source-ref pointers" in skill
    assert "Hermes normal recall remains a strict current-window/current-session surface" in skill
    assert "Hermes raw-pool recall is only for explicit skill/toolbook generation or self-review workflows" in skill
    assert "project-level review workflows" not in skill
    assert "Memcore Cloud emits the self-review signal" in skill
    assert "Claude can use this skill as an instruction signal" in skill
    assert "source_collection=claude_all" in skill
    assert "reader/UI aggregation group" in skill
    assert "Desktop-managed local-agent Claude Code records" in skill
    assert "metadata is not the conversation body" in skill
    assert "not a user-installed PATH CLI" in skill
    assert "attribution_mode=dual" in skill
    assert "lineage evidence, not as platform interoperability" in skill
    assert "capability_check" in skill
    assert "Zhixing Library" in skill
    assert "library_id" in skill
    assert "rank_reason" in skill
    assert "codex only" not in lowered
    assert "only supports codex" not in lowered
    assert "openclaw" in lowered
    assert "hermes" in lowered
    assert "codex" in lowered
    assert "claude" in lowered
    assert "mcp" in lowered


def test_zhiyi_skill_declares_mcp_as_connection_layer():
    metadata = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    metadata_lowered = metadata.lower()

    assert "yifanchen-zhiyi" in metadata
    assert "Memcore Cloud Zhiyi" in metadata
    assert "local memory library" in metadata
    assert "before answering about previous decisions" in metadata_lowered
    assert "call zhiyi_recall first" in metadata_lowered
    assert "standing active memory routing rule" in metadata
    assert "one-time setup note" in metadata
    assert "capability check" in metadata
    assert "capability_check" in metadata
    assert "MCP/tool connection is missing" in metadata
    assert "active layered" in metadata
    assert "same project/workspace" in metadata
    assert "same workstream/task" in metadata
    assert "stable user preferences/tool facts" in metadata
    assert "raw-pool/global only when explicitly requested" in metadata
    assert "explicit memory_scope=window" in metadata
    assert "install/test/release status" in metadata
    assert "type: \"mcp\"" in metadata
    assert "http://127.0.0.1:9851/mcp" in metadata


def test_readme_install_prompts_teach_agents_to_install_and_call_recall():
    for relative in ["README.md", "README.en.md"]:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "You are installing Memcore Cloud for me on this machine." in text
        assert "Repository: https://github.com/strmforge/memcore-cloud" in text
        assert "standing memory rule" in text
        assert "not just a one-time setup note" in text
        assert "register the MCP tool named yifanchen-zhiyi" in text
        assert '{"query":"capability check","mode":"capability_check"}' in text
        assert "Keep this rule active from now on" in text
        assert "call zhiyi_recall before answering" in text
        assert "next step" in text
        assert "what else" in text
        assert "then what" in text
        assert "MCP/tool connection is missing" in text
        assert "guessing from memory" in text
        assert "current window/session first" in text
        assert "same project/workspace" in text
        assert "same workstream/task" in text
        assert "stable preferences/tool facts" in text
        assert "raw-pool/global" in text
        assert "do not claim there is no memory" in text

    zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    root = (ROOT / "README.md").read_text(encoding="utf-8")
    for text in (zh, root):
        assert "你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）" in text
        assert "仓库：https://github.com/strmforge/memcore-cloud" in text
        assert "长期记忆规则" in text
        assert "注册名为 yifanchen-zhiyi 的 MCP 工具" in text
        assert '{"query":"capability check","mode":"capability_check"}' in text
        assert "请持续遵守这条规则" in text
        assert "请先调用 zhiyi_recall" in text
        assert "下一步/接下来呢/还有吗/然后呢" in text
        assert "当前窗口/session 优先" in text
        assert "同项目/同工作区" in text
        assert "同工作流/同任务" in text
        assert "稳定偏好/工具事实" in text
        assert "raw-pool/global" in text
        assert "不要说没有记忆" in text
        assert "不要凭印象猜" in text


def test_full_installers_install_codex_skill_and_register_mcp_when_available():
    for relative in [
        "tools/macos_full_install.sh",
        "tools/linux_full_install.sh",
        "tools/windows_full_install.ps1",
    ]:
        text = (ROOT / relative).read_text(encoding="utf-8")
        normalized = text.replace("\\", "/")
        assert "yifanchen-zhiyi" in text
        assert "system/skills/yifanchen-zhiyi" in normalized
        assert "Codex skill installed" in text
        assert "Codex skill:" in text
        assert "http://127.0.0.1:9851/mcp" in text
        assert "codex mcp add yifanchen-zhiyi" in text
        assert "Codex MCP registered" in text
        assert "codex_mcp_bridge.py" in text
        assert "receipt_url" in text
        assert "enable_receipts" in text
        assert "enable_queue_prefetch" in text
        assert "Claude Desktop MCP" in text
        assert "claude_desktop_mcp_bridge.py" in text
        assert "install_claude_desktop_skill.py" in text
        assert "claude_desktop_config.json" in text
        assert "install_claude_code_preflight_hook.py" in text
        assert "claude_code_preflight_hook.py" in text
        assert "UserPromptSubmit" in text or "Claude Code preflight hook" in text
        assert "Claude Code preflight hook:" in text
        assert '"type": "stdio"' in text
        assert '"PYTHONIOENCODING": "utf-8"' in text
        assert '"PYTHONUTF8": "1"' in text
        assert "MEMCORE_ROOT" in text
        assert "MEMCORE_WINDOW_BINDING_REGISTRY" in text
        assert "MEMCORE_CLAUDE_DESKTOP_CANONICAL_WINDOW_ID" in text
        assert "MEMCORE_CLAUDE_DESKTOP_SESSION_ID" in text
        assert "--window-binding-registry" in text
        assert "--binding-key" in text
        assert "chrome-native-hosts-v2.json" in text
        assert "chrome-native-hosts.json" in text
        assert "claude_desktop" in text
        assert "--create" not in text
        if relative.endswith(".ps1"):
            assert "Find-CodexCli" in text
            assert "$codexExe" in text
            assert "Install-ClaudeCodePreflightHook" in text
            assert "Get-RuntimePython" in text
            assert "p0_watcher_interval_milliseconds = 250" in text
            assert "interval_milliseconds = 250" in text
            assert "interval_seconds = 1" not in text
        else:
            assert "find_codex_cli" in text
            assert "codex_exe" in text
            assert "install_claude_code_preflight_hook" in text
            assert '"p0_watcher_interval_milliseconds": int(' in text
            assert '"interval_milliseconds": int(raw_ingest.get("interval_milliseconds") or 250)' in text
            assert '"interval_seconds": int(raw_ingest.get("interval_seconds") or 1)' not in text
            assert "capability_smoke" in text
            assert '"method": "tools/call"' in text
            assert '"name": "zhiyi_recall"' in text
            assert '"mode": "capability_check"' in text
            assert '"consumer": "unix-install-smoke"' in text
            assert "recall_performed" in text
            assert "raw_excerpt_returned" in text
            assert "capability_check: ok version" in text


def test_windows_installer_ignores_windowsapps_python_placeholder():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert "$exe.Source -notmatch \"\\\\WindowsApps\\\\\"" in windows
    assert 'Join-Path $env:LOCALAPPDATA "Programs\\Python"' in windows
    assert '"C:\\Program Files"' in windows
    assert '"C:\\Program Files (x86)"' in windows
    assert "Get-ChildItem $root -Recurse -Filter python.exe" in windows
    assert 'Where-Object { $_.FullName -notmatch "\\\\WindowsApps\\\\" }' in windows
    assert "Test-PythonCandidate -Path $candidate.FullName" in windows


def test_windows_installer_registers_mcp_with_runtime_venv_python():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert "function Get-RuntimePython" in windows
    assert 'Join-Path $InstallRoot ".venv\\Scripts\\python.exe"' in windows
    assert "Test-PythonCandidate -Path $venvPython" in windows

    codex_section = windows.split("function Install-CodexMcp", 1)[1].split(
        "function Install-ClaudeDesktopMcp",
        1,
    )[0]
    claude_section = windows.split("function Install-ClaudeDesktopMcp", 1)[1].split(
        "function Start-MemcoreService",
        1,
    )[0]

    assert "$python = Get-RuntimePython" in codex_section
    assert "$python = Find-Python" not in codex_section
    assert "runtime python not found" in codex_section

    assert "$python = Get-RuntimePython" in claude_section
    assert "$python = Find-Python" not in claude_section
    assert "runtime python not found" in claude_section
    assert '"command": sys.executable' in claude_section


def test_windows_native_smoke_is_repeatable_no_recall_and_not_vm_based():
    smoke = (ROOT / "tools" / "windows_native_smoke.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    guardian = (ROOT / "tools" / "windows_guardian.ps1").read_text(encoding="utf-8")
    hidden_guardian = (ROOT / "tools" / "windows_hidden_guardian.vbs").read_text(encoding="utf-8")
    tray = (ROOT / "tools" / "windows_tray.ps1").read_text(encoding="utf-8")
    uninstaller = (ROOT / "uninstall.ps1").read_text(encoding="utf-8")
    wiki = (ROOT / "docs" / "wiki" / "Native-Windows-Codex.md").read_text(encoding="utf-8")

    assert 'tool = "windows_native_smoke"' in smoke
    assert 'target = "native_windows"' in smoke
    assert 'method = "tools/call"' in smoke
    assert 'name = "zhiyi_recall"' in smoke
    assert 'mode = "capability_check"' in smoke
    assert 'consumer = "windows-native-smoke"' in smoke
    assert "recall_performed" in smoke
    assert "raw_excerpt_returned" in smoke
    assert "read_only" in smoke
    assert "Find-CodexCli" in smoke
    assert "chrome-native-hosts-v2.json" in smoke
    assert "chrome-native-hosts.json" in smoke
    assert "codex mcp list" in smoke
    assert '"-InstallRoot", $InstallRoot' in installer
    assert 'windows_native_smoke.ps1`" -InstallRoot `"$InstallRoot`"' in installer
    assert "p0_watcher_process" in smoke
    assert "Get-AuthorizedP0WatcherProcesses" in smoke
    assert "Test-P0WatcherCommandLine" in smoke
    assert "Test-CommandLineHasInstallRoot" in smoke
    assert "authorized tree PID" in smoke
    assert "codex_capture_status" in smoke
    assert "Test-CodexCaptureStatus" in smoke
    assert "capture_independent_of_mcp" in smoke
    assert "raw_sync" in smoke
    assert "Codex source records are ahead of Yifanchen raw" in smoke
    assert "codex_consumer_mcp_optional" in smoke
    assert "local capture still uses source files" in smoke
    assert "Test-CodexProviderBucket" in smoke
    assert "codex_provider_bucket" in smoke
    assert "provider_bucket_matches_section" in smoke
    assert "codex_provider_bucket_drift" in smoke
    assert "127.0.0.1:15721" in smoke
    assert "codex_local_proxy_health" in smoke
    assert "models_404_not_fatal" in smoke
    assert "diagnostic only" in smoke
    assert "codex_responses_probe" in smoke
    assert "provider bucket drift breaks Codex even when the relay is healthy" in smoke
    assert "Read-CodexConfigForSmoke" in smoke
    assert "Convert-TomlScalarForSmoke" in smoke
    assert "Get-HttpStatusCodeForSmoke" in smoke
    assert "Test-ZhiyiModelBinding" in smoke
    assert "zhiyi_model_ui" in smoke
    assert "/api/v1/zhiyi/model-options" in smoke
    assert "/api/v1/zhiyi/model-binding/dry-run" in smoke
    assert "zhiyi_model_binding.user.json" in smoke
    assert "MEMCORE_ZHIYI_API_KEY" in smoke
    assert "secrets_stored" in smoke
    assert "model_call_performed" in smoke
    assert "本机工具识别模型" in smoke
    assert "Local Tool Recognition Model" in smoke
    assert "windows_guardian_script" in smoke
    assert "windows_hidden_guardian_launcher" in smoke
    assert "windows_tray_script" in smoke
    assert "MemcoreCloudGuardianLogon" in smoke
    assert "MemcoreCloudGuardianHealth" in smoke
    assert "MemcoreCloudTray" in smoke
    assert "guardian task must use wscript hidden launcher" in smoke
    assert "guardian hidden launcher is missing" in smoke
    assert "tray task action is not hidden; a console window may flash" in smoke
    assert "windows_guardian_run" in smoke
    assert "guardian-status.json" in smoke
    assert "guardian_status_content" in smoke
    assert "guardian status file is not ok" in smoke
    assert "windows_guardian.ps1" in installer
    assert "windows_hidden_guardian.vbs" in installer
    assert "windows_tray.ps1" in installer
    assert "Register-WindowsAutostart" in installer
    assert "New-ScheduledTaskTrigger -AtLogOn" in installer
    assert "RepetitionInterval (New-TimeSpan -Minutes 1)" in installer
    assert "MemcoreCloudGuardianLogon" in installer
    assert "MemcoreCloudGuardianHealth" in installer
    assert "MemcoreCloudTray" in installer
    assert "System32\\wscript.exe" in installer
    assert 'New-ScheduledTaskAction -Execute $wscriptExe -Argument $guardianArgs' in installer
    assert "-STA -ExecutionPolicy Bypass -WindowStyle Hidden" in installer
    assert "Start-ScheduledTask -TaskName \"MemcoreCloudTray\"" in installer
    assert "MemcoreCloudGuardianLogon" in uninstaller
    assert "MemcoreCloudGuardianHealth" in uninstaller
    assert "MemcoreCloudTray" in uninstaller
    assert "windows_tray.ps1" in uninstaller
    assert "windows_guardian.ps1" in uninstaller
    assert "windows_guardian" in guardian
    assert "windows_guardian.ps1" in hidden_guardian
    assert "shell.Run commandLine, 0, False" in hidden_guardian
    assert "shouldWriteStatus" in guardian
    assert "existing.generated_at" in guardian
    assert "p0-watcher.cmd" in guardian
    assert "Get-P0WatcherTree" in guardian
    assert "Test-P0WatcherCommandLine" in guardian
    assert "Normalize-PathText" in guardian
    assert "Test-CommandLineHasInstallRoot" in guardian
    assert "Test-ProcessesOlderThanFile" in guardian
    assert "Stop-ProcessTreeByRoots" in guardian
    assert "Get-FileSha256" in guardian
    assert "Test-ServiceSourceChanged" in guardian
    assert ".source.sha256" in guardian
    assert "source file newer than running process or source hash changed" in guardian
    assert "Get-PortListenerProcessIds" in guardian
    assert "Get-PortListenerProcessSummaries" in guardian
    assert "Add-PortOwnerDiagnostic" in guardian
    assert "any_wslrelay_owner" in guardian
    assert "is_wslrelay" in guardian
    assert "Test-MemcoreServicePortReady" in guardian
    assert "Test-RawGatewayHealthIdentity" in guardian
    assert '([string]$health.service -eq "raw_consumption_gateway")' in guardian
    assert "$health.preflight -eq $true" in guardian
    assert "$Health.source_path" in guardian
    assert "$Health.source_sha256" in guardian
    assert 'Join-Path $InstallRoot "src\\raw_consumption_gateway.py"' in guardian
    assert "Select-CanonicalServiceRoot" in guardian
    assert "Stop-DuplicateServiceProcessRoots" in guardian
    assert "_duplicate_processes" in guardian
    assert "kept root PID" in guardian
    assert "p0_watcher_cmd_refreshed" in guardian
    assert "Start-RuntimeServicesIfMissing" in guardian
    assert "Start-MemcoreServiceIfMissing" in guardian
    assert "Start-HiddenCommandProcess" in guardian
    assert '([WMIClass]"Win32_Process").Create' in guardian
    assert "Start-Process -FilePath $env:ComSpec" not in guardian
    assert 'Name "p3-recall"' in guardian
    assert 'ScriptName "p3_recall.py"' in guardian
    assert 'Name "p4-provider"' in guardian
    assert 'ScriptName "p4_provider.py"' in guardian
    assert 'Name "p6-console"' in guardian
    assert 'ScriptName "p6_console.py"' in guardian
    assert 'Name "raw-gateway"' in guardian
    assert 'ScriptName "raw_consumption_gateway.py"' in guardian
    assert 'Name "dialog-entry"' in guardian
    assert 'ScriptName "dialog_entry_proxy.py"' in guardian
    assert "Test-PortListening" in guardian
    assert "9830" in guardian
    assert "9840" in guardian
    assert "9850" in guardian
    assert "9851" in guardian
    assert "9860" in guardian
    assert "--scan --source codex" in guardian
    assert "guardian-status.json" in guardian
    assert "NotifyIcon" in tray
    assert "yifanchen-logo.jpg" in tray
    assert "yifanchen_logo.png" in tray
    assert "CurrentUICulture" in tray
    assert "function U" in tray
    assert 'open_console = (U "6253 5F00 63A7 5236 53F0")' in tray
    assert 'run_guardian_now = (U "7ACB 5373 5B88 62A4 8865 626B")' in tray
    assert 'record_guard_label = (U "8BB0 5F55 5B88 62A4 FF1A")' in tray
    assert 'record_catching_up_label = (U "6B63 5728 8FFD 5C3E FF1A")' in tray
    assert 'record_backfill_needed_label = (U "5EFA 8BAE 56DE 586B FF1A")' in tray
    assert 'pause_guardian = (U "6682 505C 5B88 62A4 4EFB 52A1")' in tray
    assert 'exit_tray = (U "9000 51FA 6258 76D8 56FE 6807")' in tray
    assert 'open_console = "Open Console"' in tray
    assert 'run_guardian_now = "Run Guardian Now"' in tray
    assert 'record_guard_label = "Record Guard: "' in tray
    assert "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1" in tray
    assert "/api/v1/records/guardian/backfill" in tray
    assert "Invoke-RecordGuardianBackfill" in tray
    assert "New-FallbackMemcoreIcon" in tray
    assert "SystemIcons]::Shield" not in tray
    assert "SystemIcons]::Warning" not in tray
    assert "SystemIcons" not in tray
    assert "ConvertFrom-JsonOutput" in guardian
    assert "no balanced JSON object found" in guardian
    assert "Invoke-RecordGuardianBackfillIfNeeded" in guardian
    assert "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1" in guardian
    assert "/api/v1/records/guardian/backfill" in guardian
    assert "console_token" in guardian
    assert "X-Memcore-Console-Token" in guardian
    assert "Write-Utf8NoBom" in guardian
    assert "[System.IO.File]::WriteAllText" in guardian
    forbidden = [
        "Invoke-Command " + "-VMName",
        "Get-" + "VM",
        "Hyper" + "-V",
        ".".join(["172", "22"]),
        ".".join(["172", "18"]),
        ".".join(["192", "168"]),
        "C:" + "\\Users\\" + "Example",
    ]
    for fragment in forbidden:
        assert fragment not in smoke
    assert "windows_native_smoke.ps1" in installer
    assert "Run-NativeSmoke" in installer
    assert 'if ($SkipCodex) { $nativeArgs += "-SkipCodex" }' in installer
    assert 'Die "Native Windows smoke failed with exit code $LASTEXITCODE"' in installer
    assert "windows_native_smoke.ps1" in wiki
    assert "does not run real recall" in wiki


def test_macos_installer_adds_menu_bar_status_icon():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    menu_bar = (ROOT / "tools" / "macos_menu_bar.swift").read_text(encoding="utf-8")
    uninstaller = (ROOT / "uninstall.sh").read_text(encoding="utf-8")

    assert "macos_menu_bar.swift" in mac
    assert "build_menu_bar_helper" in mac
    assert "swiftc" in mac
    assert "runtime/memcore-menu-bar" in mac
    assert "com.memcorecloud.menu-bar" in mac
    assert '"ProcessType": "Interactive"' in mac
    assert "write_menu_bar_launch_agent" in mac
    assert 'MENU_BAR_STATUS="installed"' in mac
    assert 'MENU_BAR_STATUS="not_installed"' in mac
    assert "Menu bar: ${MENU_BAR_STATUS}" in mac
    assert "menu-bar-build.err.log" in mac

    assert "NSStatusBar.system.statusItem" in menu_bar
    assert "NSApp.setActivationPolicy(.accessory)" in menu_bar
    assert "http://127.0.0.1:9850" in menu_bar
    assert "Run Catch-up Now" in menu_bar
    assert "打开控制台" in menu_bar
    assert "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1" in menu_bar
    assert "/api/v1/records/guardian/backfill" in menu_bar
    assert "consoleToken()" in menu_bar
    assert "X-Memcore-Console-Token" in menu_bar
    assert '"recordGuard": "记录守护"' in menu_bar
    assert '"recordGuard": "Record Guard"' in menu_bar
    assert "backfill_recommend_after_milliseconds" not in menu_bar

    assert "Application Support/memcore-cloud" in uninstaller
    assert "com.memcorecloud.menu-bar" in uninstaller
    assert "Remove memcore-cloud LaunchAgents" in uninstaller
    assert "runtime" in uninstaller


def test_codex_mcp_bridge_is_installed_for_current_window_routing():
    bridge = (ROOT / "tools" / "codex_mcp_bridge.py").read_text(encoding="utf-8")
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert "stdio bridge for Codex" in bridge
    assert "CODEX_THREAD_ID" in bridge
    assert "MEMCORE_CODEX_SESSION_ID" in bridge
    assert "MEMCORE_CODEX_CANONICAL_WINDOW_ID" in bridge
    assert "consumer\", \"codex\"" in bridge
    assert 'args["memory_scope"] = "window" if mode == "preflight"' in bridge
    assert "codex_compact" in bridge
    for text in (mac, linux, windows):
        assert "codex_mcp_bridge.py" in text
        assert "codex mcp add yifanchen-zhiyi" in text
        assert "--endpoint" in text
        assert "http://127.0.0.1:9851/mcp" in text
        assert "--window-binding-registry" in text
        assert "--binding-key" in text
        assert "codex" in text
        assert "MEMCORE_WINDOW_BINDING_REGISTRY" in text
        assert "chrome-native-hosts-v2.json" in text
        assert "chrome-native-hosts.json" in text
        assert "--url http://127.0.0.1:9851/mcp" not in text
        assert '--url "http://127.0.0.1:9851/mcp"' not in text


def test_codex_mcp_bridge_adds_thread_id_as_session_without_guessing():
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 27,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "Codex 当前窗口"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 27,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {
                "ok": True,
                "consumer": "codex",
                "memory_scope": "active",
                "tiandao_context_package_valid": True,
                "tiandao_context_package": {
                    "schema": "tiandao_context_package.v1",
                    "query_hash": "codex-query-hash",
                    "source_system": "codex",
                    "canonical_window_id": "codex-thread-27",
                    "session_id": "codex-thread-27",
                    "intent_mode": "evidence",
                    "memory_context_mode": "mode_a",
                    "scope_enforced": True,
                    "memory_write": False,
                    "contract_role": "memory_context_candidate",
                    "consumer": "codex",
                    "memory_scope": "active",
                    "memory_base_scope": "active_layered",
                    "active_layers_used": ["current_session"],
                    "permission_boundary": {"memory_write_enabled": False, "read_only": True},
                    "validation": {"valid": True, "violations": []},
                    "matched_memories": [{"raw_excerpt_returned": True}],
                    "raw_projection": {"raw_items_count": 1},
                },
                "matched_count": 0,
                "items": [],
            },
            "isError": False,
        },
    }

    with patch.dict(os.environ, {"CODEX_THREAD_ID": "codex-thread-27"}, clear=False):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "codex"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["session_id"] == "codex-thread-27"
    assert "canonical_window_id" not in forwarded_args
    assert forwarded_args["limit"] == 3
    assert forwarded_args["excerpt_chars"] == 240
    structured = result["result"]["structuredContent"]
    assert structured["response_budget"]["mode"] == "codex_compact"
    assert structured["tiandao_context_package_valid"] is True
    assert structured["tiandao_context_package"]["schema"] == "tiandao_context_package.v1"
    assert structured["tiandao_context_package"]["memory_context_mode"] == "mode_a"
    assert structured["tiandao_context_package"]["validation"]["valid"] is True
    assert "matched_memories" not in structured["tiandao_context_package"]
    assert "raw_projection" not in structured["tiandao_context_package"]


def test_codex_mcp_bridge_adds_registry_current_window_binding(tmp_path):
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "codex": {
                        "canonical_window_id": "codex-project-1",
                        "session_id": "codex-session-1",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 28,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "Codex registry"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 28,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            bridge._forward(
                "http://127.0.0.1:9851/mcp",
                request,
                30,
                True,
                registry_path=str(registry_path),
            )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "codex"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["canonical_window_id"] == "codex-project-1"
    assert forwarded_args["session_id"] == "codex-session-1"


def test_codex_mcp_bridge_defaults_preflight_to_window_scope_when_bound(tmp_path):
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "codex": {
                        "canonical_window_id": "codex-window-fast",
                        "session_id": "codex-session-fast",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 29,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "继续发布前检查", "mode": "preflight"},
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 29,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "mode": "preflight", "decision": "silent"},
            "isError": False,
        },
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            bridge._forward(
                "http://127.0.0.1:9851/mcp",
                request,
                30,
                True,
                registry_path=str(registry_path),
            )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["mode"] == "preflight"
    assert forwarded_args["consumer"] == "codex"
    assert forwarded_args["memory_scope"] == "window"
    assert forwarded_args["canonical_window_id"] == "codex-window-fast"
    assert forwarded_args["session_id"] == "codex-session-fast"


def test_codex_mcp_bridge_compacts_preflight_payload():
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 71,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "继续平台配置", "mode": "preflight"},
        },
    }
    payload = {
        "ok": True,
        "mode": "preflight",
        "version": "2026.6.11",
        "contract": "zhixing_preflight.v2026.6.11",
        "auto_entry_contract": "zhixing_auto_entry.v2026.6.11",
        "auto_entry_state": "enter",
        "auto_entry_allowed": True,
        "auto_retreat_allowed": False,
        "auto_entry_reason": "proactive_resurfacing_required",
        "auto_entry_triggered_by": ["prompt:continuation", "shelf:xingce"],
        "auto_retreat_reason": "",
        "context_delivery_mode": "compact_source_anchors",
        "next_action": "apply_must_surface_before_answer",
        "agent_instruction": "Use must_surface, do_not_repeat, and acceptance_checks before answering; do not expose raw excerpts.",
        "consumer": "codex",
        "query": "继续平台配置",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "recall_performed": True,
        "raw_excerpt_returned": False,
        "decision": "surface",
        "prompt_class": "continuation",
        "confidence": 0.85,
        "min_surface_score": 45,
        "top_score": 85,
        "silence_reason": "",
        "should_recall": True,
        "should_surface": True,
        "proactive_resurfacing_required": True,
        "xingce_focus": ["action_strategy"],
        "must_surface": [{"library_id": "ZX-XINGCE-2", "library_shelf": "xingce"}],
        "do_not_repeat": ["不要重复旧坑"],
        "acceptance_checks": ["跑 smoke"],
        "matched_count": 1,
        "source_refs_count": 1,
        "raw_items_count": 1,
        "fast_window_preflight": True,
        "fast_recall_path": "canonical_window_index",
        "fast_window_index_status": "hit_recent_context",
        "zhiyi_layer_skipped_for_fast_preflight": True,
        "consumer_receipt": {
            "consumer": "codex",
            "read_only": True,
            "write_performed": False,
            "receipt_scope": "zhixing_preflight_read_only",
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 71,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    structured = result["result"]["structuredContent"]
    assert structured["response_budget"]["mode"] == "codex_preflight_compact"
    assert structured["decision"] == "surface"
    assert structured["auto_entry_contract"] == "zhixing_auto_entry.v2026.6.11"
    assert structured["auto_entry_state"] == "enter"
    assert structured["auto_entry_allowed"] is True
    assert structured["auto_retreat_allowed"] is False
    assert structured["auto_entry_reason"] == "proactive_resurfacing_required"
    assert structured["auto_entry_triggered_by"] == ["prompt:continuation", "shelf:xingce"]
    assert structured["context_delivery_mode"] == "compact_source_anchors"
    assert structured["next_action"] == "apply_must_surface_before_answer"
    assert structured["prompt_class"] == "continuation"
    assert structured["confidence"] == 0.85
    assert structured["should_surface"] is True
    assert structured["must_surface"][0]["library_id"] == "ZX-XINGCE-2"
    assert structured["fast_window_preflight"] is True
    assert structured["fast_recall_path"] == "canonical_window_index"
    assert structured["fast_window_index_status"] == "hit_recent_context"
    assert structured["zhiyi_layer_skipped_for_fast_preflight"] is True


def test_installers_allow_skipping_codex_mcp_without_user_learning_mcp():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    wrapper = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "--skip-codex" in mac
    assert "--skip-codex" in linux
    assert "[switch]$SkipCodex" in windows
    assert "[switch]$SkipCodex" in wrapper
    assert "$env:MEMCORE_INSTALL_DIR" in wrapper
    assert "$installerArgs = @{}" in wrapper
    assert '$installerArgs["InstallRoot"] = $Dir' in wrapper
    assert '$installerArgs["SkipCodex"] = $true' in wrapper
    assert "$args +=" not in wrapper


def test_claude_desktop_bridge_and_skip_option_are_installed():
    bridge = (ROOT / "tools" / "claude_desktop_mcp_bridge.py").read_text(encoding="utf-8")
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    wrapper = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "stdio bridge for Claude Desktop" in bridge
    assert "http://127.0.0.1:9851/mcp" in bridge
    assert "Content-Length:" in bridge
    assert 'encode("utf-8")' in bridge
    assert "sys.stdout.buffer" in bridge or 'getattr(sys.stdout, "buffer", None)' in bridge
    assert "DEFAULT_TIMEOUT_SECONDS = 30.0" in bridge
    assert "--full-recall-response" in bridge
    assert "--window-binding-registry" in bridge
    assert "MEMCORE_WINDOW_BINDING_REGISTRY" in bridge
    assert "current_windows" in bridge
    assert "--skip-claude-desktop" in mac
    assert "--skip-claude-desktop" in linux
    assert "[switch]$SkipClaudeDesktop" in windows
    assert "[switch]$SkipClaudeDesktop" in wrapper
    assert '$installerArgs["SkipClaudeDesktop"] = $true' in wrapper
    assert '& $installer @installerArgs' in wrapper
    assert 'Where-Object { $_.Name -like "Claude-*" }' in windows
    for text in (mac, linux, windows):
        assert '"--timeout", "30"' in text
        assert '"--window-binding-registry"' in text
        assert '"--binding-key", "claude_desktop"' in text
        assert '"PYTHONIOENCODING": "utf-8"' in text
        assert '"PYTHONUTF8": "1"' in text
        assert '"MEMCORE_ROOT": str(install_root)' in text
        assert '"MEMCORE_WINDOW_BINDING_REGISTRY": str(registry_path)' in text


def test_claude_desktop_bridge_writes_utf8_json_lines():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    class FakeStdout:
        def __init__(self):
            self.buffer = io.BytesIO()

        def flush(self):
            pass

    fake_stdout = FakeStdout()
    with patch.object(bridge.sys, "stdout", fake_stdout):
        bridge._write_message({"jsonrpc": "2.0", "id": 1, "result": {"text": "中文召回正常"}})

    payload = fake_stdout.buffer.getvalue()
    assert payload.endswith(b"\n")
    assert not payload.startswith(b"Content-Length:")
    decoded = json.loads(payload.decode("utf-8"))
    assert decoded["result"]["text"] == "中文召回正常"
    assert b"\\u4e2d\\u6587" not in payload


def test_claude_desktop_bridge_compacts_recall_payload_for_stdio(tmp_path):
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "忆凡尘"}},
    }
    payload = {
        "ok": True,
        "consumer": "claude_desktop_windows",
        "query": "忆凡尘",
        "zhixing_library": {"large": "x" * 5000},
        "hybrid_recall": {"large": "y" * 5000},
        "matched_count": 1,
        "source_refs_count": 1,
        "raw_items_count": 1,
        "current_window_binding_applied": True,
        "current_window_binding_key": "claude_desktop",
        "current_window_binding_fields": ["canonical_window_id", "session_id", "project_id"],
        "tiandao_context_package_valid": True,
        "tiandao_context_package": {
            "schema": "tiandao_context_package.v1",
            "query_hash": "claude-query-hash",
            "source_system": "claude_desktop",
            "canonical_window_id": "claude-window-1",
            "session_id": "claude-session-1",
            "intent_mode": "evidence",
            "memory_context_mode": "mode_b",
            "scope_enforced": True,
            "memory_write": False,
            "contract_role": "memory_context_candidate",
            "consumer": "claude_desktop",
            "memory_scope": "active",
            "memory_base_scope": "active_layered",
            "active_layers_used": ["same_project_workspace"],
            "current_window_binding_applied": True,
            "current_window_binding_key": "claude_desktop",
            "current_window_binding_fields": ["canonical_window_id", "session_id", "project_id"],
            "source_refs": [
                {
                    "ref_id": "ref-1",
                    "source_system": "claude_desktop",
                    "artifact_type": "claude_desktop_session_jsonl",
                    "ref_path": "memory/claude_desktop/local/claude_desktop/s1.jsonl",
                    "evidence_hash": "hash-1",
                    "raw_evidence_status": "raw",
                }
            ],
            "permission_boundary": {"memory_write_enabled": False, "read_only": True},
            "capability_profile": {"adapter": "RawConsumptionGateway", "can_write_memory": False},
            "adapter_verdict": {"adapter_verdict": "READY_FOR_MEMORY_CONTEXT_CANDIDATE"},
            "validation": {"valid": True, "violations": []},
            "matched_memories": [{"raw_excerpt_returned": True}],
            "raw_projection": {"raw_items_count": 1},
        },
        "items": [
            {
                "library_id": "ZX-1",
                "library_shelf": "raw",
                "memory_type": "case_memory",
                "source_system": "claude_desktop",
                "source_path": "memory/claude_desktop/local/claude_desktop/s1.jsonl",
                "msg_ids": ["m1"],
                "summary": "s" * 2000,
                "raw_excerpt": "r" * 2000,
                "library_card": {"large": "z" * 5000},
                "typed_graph": {"large": "g" * 5000},
            }
        ],
        "consumer_receipt": {
            "consumer": "claude_desktop_windows",
            "request_id": "r1",
            "read_only": True,
            "write_performed": False,
            "used_source_refs": [{"source_path": "too-large-for-stdio"}],
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            registry_path=str(tmp_path / "empty-window-binding-registry.json"),
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert "canonical_window_id" not in forwarded_args
    assert "session_id" not in forwarded_args
    assert forwarded_args["limit"] == 3
    assert forwarded_args["excerpt_chars"] == 240
    structured = result["result"]["structuredContent"]
    text_payload = json.loads(result["result"]["content"][0]["text"])
    assert structured == text_payload
    assert "zhixing_library" not in structured
    assert "hybrid_recall" not in structured
    assert "library_card" not in structured["items"][0]
    assert "typed_graph" not in structured["items"][0]
    assert structured["current_window_binding_applied"] is True
    assert structured["current_window_binding_key"] == "claude_desktop"
    assert structured["current_window_binding_fields"] == ["canonical_window_id", "session_id", "project_id"]
    assert structured["tiandao_context_package_valid"] is True
    tiandao_pkg = structured["tiandao_context_package"]
    assert tiandao_pkg["schema"] == "tiandao_context_package.v1"
    assert tiandao_pkg["memory_context_mode"] == "mode_b"
    assert tiandao_pkg["source_refs"][0]["ref_id"] == "ref-1"
    assert tiandao_pkg["permission_boundary"]["memory_write_enabled"] is False
    assert tiandao_pkg["adapter_verdict"]["adapter_verdict"] == "READY_FOR_MEMORY_CONTEXT_CANDIDATE"
    assert "matched_memories" not in tiandao_pkg
    assert "raw_projection" not in tiandao_pkg
    assert structured["items"][0]["raw_excerpt"].endswith("[truncated]")
    assert structured["response_budget"]["mode"] == "claude_desktop_compact"
    assert "used_source_refs" not in structured["consumer_receipt"]


def test_claude_desktop_bridge_compacts_preflight_payload_for_stdio(tmp_path):
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 70,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "继续平台配置", "mode": "preflight"},
        },
    }
    payload = {
        "ok": True,
        "mode": "preflight",
        "version": "2026.6.11",
        "contract": "zhixing_preflight.v2026.6.11",
        "auto_entry_contract": "zhixing_auto_entry.v2026.6.11",
        "auto_entry_state": "enter",
        "auto_entry_allowed": True,
        "auto_retreat_allowed": False,
        "auto_entry_reason": "proactive_resurfacing_required",
        "auto_entry_triggered_by": ["prompt:continuation", "shelf:xingce"],
        "auto_retreat_reason": "",
        "context_delivery_mode": "compact_source_anchors",
        "next_action": "apply_must_surface_before_answer",
        "agent_instruction": "Use must_surface, do_not_repeat, and acceptance_checks before answering; do not expose raw excerpts.",
        "consumer": "claude_desktop",
        "query": "继续平台配置",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "recall_performed": True,
        "raw_excerpt_returned": False,
        "decision": "surface",
        "prompt_class": "continuation",
        "confidence": 0.87,
        "min_surface_score": 45,
        "top_score": 87,
        "silence_reason": "",
        "should_recall": True,
        "should_surface": True,
        "source_refs_required": True,
        "proactive_resurfacing_required": True,
        "zhiyi_focus": ["source_backed_intent"],
        "xingce_focus": ["action_strategy", "acceptance_checks"],
        "must_surface": [
            {
                "library_id": "ZX-XINGCE-1",
                "library_shelf": "xingce",
                "title": "Hermes profile config",
                "summary": "先查 profile config",
                "source_system": "codex",
                "source_path": "raw/probe_logs/hermes.jsonl",
                "raw_evidence_status": "raw_offset",
                "rank_reason": "source_refs available; shelf=xingce",
                "raw_excerpt": "this must be omitted",
                "library_card": {"large": "x" * 1000},
                "typed_graph": {"large": "y" * 1000},
            }
        ],
        "do_not_repeat": ["不要改 root config 当默认继承"],
        "acceptance_checks": ["hermes profile show"],
        "recall_status": "preflight_surface_required",
        "reason": "matched source-backed Zhiyi/Xingce evidence should be surfaced before answering",
        "memory_scope": "active",
        "memory_base_scope": "active_layered",
        "matched_count": 1,
        "source_refs_count": 1,
        "raw_items_count": 1,
        "fast_window_preflight": True,
        "fast_recall_path": "canonical_window_index",
        "fast_window_index_status": "hit_recent_context",
        "zhiyi_layer_skipped_for_fast_preflight": True,
        "zhixing_library": {"large": "z" * 1000},
        "hybrid_recall": {"large": "h" * 1000},
        "consumer_receipt": {
            "consumer": "claude_desktop",
            "request_id": "preflight-1",
            "read_only": True,
            "write_performed": False,
            "items_count": 1,
            "source_refs_count": 1,
            "raw_items_count": 1,
            "receipt_scope": "zhixing_preflight_read_only",
            "used_library_ids": ["ZX-XINGCE-1"],
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 70,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            registry_path=str(tmp_path / "empty-window-binding-registry.json"),
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["mode"] == "preflight"
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    structured = result["result"]["structuredContent"]
    text_payload = json.loads(result["result"]["content"][0]["text"])
    assert structured == text_payload
    assert structured["mode"] == "preflight"
    assert structured["decision"] == "surface"
    assert structured["auto_entry_contract"] == "zhixing_auto_entry.v2026.6.11"
    assert structured["auto_entry_state"] == "enter"
    assert structured["auto_entry_allowed"] is True
    assert structured["auto_retreat_allowed"] is False
    assert structured["auto_entry_reason"] == "proactive_resurfacing_required"
    assert structured["auto_entry_triggered_by"] == ["prompt:continuation", "shelf:xingce"]
    assert structured["context_delivery_mode"] == "compact_source_anchors"
    assert structured["next_action"] == "apply_must_surface_before_answer"
    assert structured["prompt_class"] == "continuation"
    assert structured["confidence"] == 0.87
    assert structured["should_surface"] is True
    assert structured["proactive_resurfacing_required"] is True
    assert structured["do_not_repeat"] == ["不要改 root config 当默认继承"]
    assert structured["acceptance_checks"] == ["hermes profile show"]
    assert structured["must_surface"][0]["library_id"] == "ZX-XINGCE-1"
    assert "raw_excerpt" not in structured["must_surface"][0]
    assert "library_card" not in structured["must_surface"][0]
    assert "typed_graph" not in structured["must_surface"][0]
    assert "zhixing_library" not in structured
    assert "hybrid_recall" not in structured
    assert structured["fast_window_preflight"] is True
    assert structured["fast_recall_path"] == "canonical_window_index"
    assert structured["fast_window_index_status"] == "hit_recent_context"
    assert structured["zhiyi_layer_skipped_for_fast_preflight"] is True
    assert structured["response_budget"]["mode"] == "claude_desktop_preflight_compact"
    assert structured["consumer_receipt"]["receipt_scope"] == "zhixing_preflight_read_only"


def test_claude_desktop_bridge_preserves_window_identity_hint():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 17,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "Claude 新窗口"}},
    }
    payload = {
        "ok": True,
        "consumer": "claude_desktop_windows",
        "query": "Claude 新窗口",
        "memory_scope": "window",
        "memory_base_scope": "window",
        "scope_missing": True,
        "recall_status": "window_identity_required",
        "window_binding_hint": (
            "Current-window recall is the default, but this client did not provide "
            "a canonical_window_id or session_id. This is not proof that memory is empty."
        ),
        "missing_scope_fields": ["canonical_window_id", "session_id"],
        "agent_boundary": "active_window_first_explicit_broad_scope",
        "injection_boundary": "window_scope_required_for_default_recall",
        "recall_performed": False,
        "raw_excerpt_returned": False,
        "matched_count": 0,
        "source_refs_count": 0,
        "raw_items_count": 0,
        "items": [],
        "zhixing_library": {"large": "x" * 5000},
        "hybrid_recall": {"large": "y" * 5000},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 17,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    structured = result["result"]["structuredContent"]
    text_payload = json.loads(result["result"]["content"][0]["text"])
    assert structured == text_payload
    assert structured["scope_missing"] is True
    assert structured["recall_status"] == "window_identity_required"
    assert "not proof that memory is empty" in structured["window_binding_hint"]
    assert structured["missing_scope_fields"] == ["canonical_window_id", "session_id"]
    assert structured["recall_performed"] is False
    assert structured["raw_excerpt_returned"] is False
    assert "zhixing_library" not in structured
    assert "hybrid_recall" not in structured


def test_claude_desktop_bridge_preserves_explicit_recall_budget():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "test",
                "limit": 1,
                "excerpt_chars": 40,
            },
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 8,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["limit"] == 1
    assert forwarded_args["excerpt_chars"] == 40


def test_claude_desktop_bridge_adds_explicit_window_binding_without_guessing():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 18,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 18,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            canonical_window_id="claude-official-1",
            session_id="claude-official-1",
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["canonical_window_id"] == "claude-official-1"
    assert forwarded_args["session_id"] == "claude-official-1"


def test_claude_desktop_bridge_adds_registry_current_window_binding(tmp_path):
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_desktop": {
                        "canonical_window_id": "claude-official-2",
                        "session_id": "claude-session-2",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 19,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 19,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            registry_path=str(registry_path),
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["canonical_window_id"] == "claude-official-2"
    assert forwarded_args["session_id"] == "claude-session-2"


def test_claude_desktop_bridge_defaults_preflight_to_window_scope_when_bound(tmp_path):
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_desktop": {
                        "canonical_window_id": "claude-window-fast",
                        "session_id": "claude-session-fast",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "继续发布前检查", "mode": "preflight"},
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 20,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "mode": "preflight", "decision": "silent"},
            "isError": False,
        },
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            bridge._forward(
                "http://127.0.0.1:9851/mcp",
                request,
                30,
                True,
                registry_path=str(registry_path),
            )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["mode"] == "preflight"
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "window"
    assert forwarded_args["canonical_window_id"] == "claude-window-fast"
    assert forwarded_args["session_id"] == "claude-session-fast"


def test_claude_desktop_bridge_normalizes_bare_gateway_error_to_jsonrpc():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    bare_gateway_error = {"ok": False, "error": "simulated gateway failure"}

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            bare_gateway_error,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    assert result == {
        "jsonrpc": "2.0",
        "id": 9,
        "error": {"code": -32603, "message": "simulated gateway failure"},
    }
    assert "ok" not in result


def test_claude_desktop_bridge_normalizes_invalid_jsonrpc_error_id():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    invalid_gateway_error = {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32603, "message": "bad upstream id"},
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            invalid_gateway_error,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    assert result == {
        "jsonrpc": "2.0",
        "id": 10,
        "error": {"code": -32603, "message": "bad upstream id"},
    }


def test_installers_report_claude_skill_update_only_when_installed_count_positive():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    for text in (mac, linux):
        assert "installed_count" in text
        assert "SKILL_RESULT=" in text
        assert "Claude Desktop skill not updated:" in text
        assert 'if [[ "$skill_status" == 0:* ]]' in text

    assert "ConvertFrom-Json" in windows
    assert "installed_count -gt 0" in windows
    assert "Claude Desktop skill not updated for" in windows


def test_windows_installer_preserves_runtime_state_files_on_mirror_update():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert '".checkpoint"' in windows
    assert '".checkpoint_p2.json"' in windows
    assert '"update_history.jsonl"' in windows


def test_claude_desktop_skill_helper_updates_existing_skill_only(tmp_path):
    helper = _load_claude_skill_helper()
    claude_home = tmp_path / "Claude"
    plugin_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text(
        json.dumps(
            {
                "skills": [
                    {"skillId": "other-skill", "name": "Other", "enabled": True},
                    {
                        "skillId": "yifanchen-zhiyi",
                        "name": "Old Yifanchen",
                        "description": "old",
                        "enabled": False,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    skill_src = tmp_path / "skill-src"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text("prompt_version: 2\n", encoding="utf-8")

    result = helper.install_skill(claude_home, skill_src)
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))
    skills = {item["skillId"]: item for item in manifest["skills"]}

    assert result["ok"] is True
    assert result["reason"] == "installed"
    assert result["created_if_missing"] is False
    assert result["installed_count"] == 1
    assert skills["other-skill"]["name"] == "Other"
    assert skills["yifanchen-zhiyi"]["name"] == "Memcore Cloud Zhiyi"
    assert skills["yifanchen-zhiyi"]["enabled"] is True
    assert "previous decisions" in skills["yifanchen-zhiyi"]["description"]
    assert "install/test/release status" in skills["yifanchen-zhiyi"]["description"]
    assert "Standing active memory rule" in skills["yifanchen-zhiyi"]["description"]
    assert "call the yifanchen-zhiyi MCP tool" in skills["yifanchen-zhiyi"]["description"]
    assert "skill is installed but recall cannot run yet" in skills["yifanchen-zhiyi"]["description"]
    assert "Preserve Claude Desktop" in skills["yifanchen-zhiyi"]["description"]
    assert (plugin_root / "skills" / "yifanchen-zhiyi" / "SKILL.md").exists()


def test_claude_desktop_skill_helper_does_not_create_missing_skill_by_default(tmp_path):
    helper = _load_claude_skill_helper()
    claude_home = tmp_path / "Claude"
    plugin_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text(
        '{"skills":[{"skillId":"other-skill","name":"Other","enabled":true}]}',
        encoding="utf-8",
    )
    skill_src = tmp_path / "skill-src"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text("prompt_version: 2\n", encoding="utf-8")

    result = helper.install_skill(claude_home, skill_src)
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["reason"] == "skill_not_found"
    assert result["installed_count"] == 0
    assert [item["skillId"] for item in manifest["skills"]] == ["other-skill"]
    assert not (plugin_root / "skills" / "yifanchen-zhiyi").exists()


def test_claude_desktop_skill_helper_create_flag_creates_missing_skill(tmp_path):
    helper = _load_claude_skill_helper()
    claude_home = tmp_path / "Claude"
    plugin_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text('{"skills":[]}', encoding="utf-8")
    skill_src = tmp_path / "skill-src"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text("prompt_version: 2\n", encoding="utf-8")

    result = helper.install_skill(claude_home, skill_src, create=True)
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["reason"] == "installed"
    assert result["created_if_missing"] is True
    assert result["installed_count"] == 1
    assert manifest["skills"][0]["skillId"] == "yifanchen-zhiyi"
    assert (plugin_root / "skills" / "yifanchen-zhiyi" / "SKILL.md").exists()
