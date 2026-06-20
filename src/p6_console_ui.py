#!/usr/bin/env python3
"""P6 console UI surface under the Tiandao console boundary."""

from __future__ import annotations

CONSOLE_UI_CONTRACT = "tiandao_console_surface.v1"


def get_console_ui_contract():
    return {
        "ok": True,
        "contract": CONSOLE_UI_CONTRACT,
        "zh_name": "人间入口界面",
        "en_name": "Console UI Surface",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "console_layer": "human_entry_surface",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "ui_surface_does_not_replace_time_origin",
        "public_ui_policy": "render_product_console_without_exposing_internal_construction_status",
    }


# ─── i18n strings ───────────────────────────────────────────

I18N = {
    "zh-CN": {
        "nav.dashboard": "总览", "nav.rawMemory": "原始记忆",
        "nav.windowRegistry": "窗口归属", "nav.zhiyi": "知意",
        "nav.recall": "召回与注入", "nav.health": "健康检查",
        "nav.sourceSystems": "数据源", "nav.settings": "设置",
        "nav.update": "系统更新", "nav.runtime": "Runtime",
        "runtime.title": "Runtime Profile", "runtime.memcoreTitle": "memcore-cloud", "runtime.ocTitle": "OpenClaw", "runtime.hermesTitle": "Hermes", "runtime.experimental": "实验性", "runtime.selected": "当前选择", "runtime.instances": "实例", "runtime.stale": "过期实例", "runtime.mismatch": "版本不一致", "runtime.hermesInstances": "实例", "runtime.hermesRunning": "运行中", "runtime.hermesConfig": "配置", "runtime.hermesRoot": "安装目录", "runtime.refresh": "刷新",
        "dashboard.title": "总览", "dashboard.serviceStatus": "服务状态",
        "dashboard.watcher": "Watcher", "dashboard.rawMemory": "原始记忆",
        "dashboard.zhiyiObjects": "知意对象", "dashboard.caseMemory": "案例记忆",
        "dashboard.errorMemory": "错误记忆", "dashboard.prefMemory": "偏好记忆",
        "dashboard.recallService": "Recall 服务", "dashboard.providerProxy": "Inject Context",
        "dashboard.phase": "服务状态", "dashboard.sealed": "本机服务就绪",
        "dashboard.sessions": "会话数", "dashboard.windows": "窗口数",
        "dashboard.active": "运行中", "dashboard.inactive": "已停止",
        "dashboard.unknown": "未知",
        "memory.title": "原始记忆", "memory.sourceSystem": "来源系统",
        "memory.computer": "计算机", "memory.window": "窗口",
        "memory.session": "会话", "memory.channel": "频道",
        "memory.timeline": "时间线", "memory.search": "搜索",
        "memory.searchPlaceholder": "输入关键词搜索...",
        "memory.lastUpdated": "最后更新", "memory.msgCount": "消息数",
        "memory.open": "查看",
        "registry.title": "窗口归属", "registry.canonical": "规范窗口ID",
        "registry.observed": "观测名称", "registry.type": "类型",
        "registry.sessionCount": "会话数", "registry.status": "状态",
        "registry.confirmed": "已确认", "registry.pending": "待确认",
        "zhiyi.title": "知意", "zhiyi.objects": "知意对象",
        "zhiyi.preference": "偏好记忆", "zhiyi.case": "案例记忆",
        "zhiyi.error": "错误记忆", "zhiyi.scope": "作用域",
        "zhiyi.summary": "摘要", "zhiyi.sourceRef": "原始引用",
        "zhiyi.createdAt": "创建时间", "zhiyi.score": "置信度",
        "zhiyi.noObjects": "暂无对象", "zhiyi.injected": "已注入",
        "zhiyi.notInjected": "未注入",
        "recall.title": "召回与注入", "recall.query": "查询内容",
        "recall.queryPlaceholder": "输入查询内容...",
        "recall.scope": "作用域过滤", "recall.scopePlaceholder": "如 window/sg，留空则全部",
        "recall.type": "类型过滤", "recall.topK": "返回条数",
        "recall.threshold": "阈值", "recall.test": "测试召回",
        "recall.inject": "测试注入", "recall.result": "召回结果",
        "recall.shouldInject": "建议注入", "recall.confidence": "置信度",
        "recall.memoryCount": "匹配数", "recall.systemPrompt": "System Prompt",
        "recall.userPrompt": "User Prompt", "recall.proxyStatus": "Inject Context 状态",
        "health.title": "健康检查", "health.runAll": "运行全部检查",
        "ss.overview": "数据源总览", "ss.liveSync": "持续同步",
        "ss.liveTracked": "持续跟踪", "ss.visibleOnly": "已识别，待形成记录",
        "ss.watcherRunning": "监视器运行中", "ss.watcherStopped": "监视器未运行",
        "ss.installKeepsWatching": "安装后继续跟踪本地记录", "ss.initialScanOnly": "只完成初次扫描",
        "ss.trackedSources": "持续跟踪来源", "ss.pendingSources": "待形成记录",
        "ss.noPendingSources": "暂无待形成记录的来源", "ss.localFiles": "本地文件连接器",
        "ss.rescan": "重新扫描", "ss.ingest": "摄入",
        "dashboard.sourceSystems": "数据源", "dashboard.runtime": "Runtime", "dashboard.version": "版本",
        "health.lastRun": "上次运行", "health.status": "状态",
        "health.passed": "通过", "health.failed": "失败",
        "health.running": "运行中", "health.check": "检查项",
        "health.detail": "详情", "health.run": "执行",
        "health.p0raw": "Raw 落盘", "health.p0watcher": "Watcher 服务",
        "health.p2zhiyi": "知意对象", "health.p2sourceRef": "Source Refs 回指",
        "health.p3recall": "Recall 服务", "health.p4provider": "Inject Context",
        "settings.title": "设置", "settings.language": "语言",
        "settings.followSystem": "跟随系统",
        "settings.simplifiedChinese": "简体中文",
        "settings.english": "English", "settings.current": "当前语言",
        "settings.save": "保存", "settings.saved": "已保存",
        "settings.about": "关于", "settings.version": "版本",
        "settings.phase": "阶段", "settings.rootPath": "根目录",
        "update.title": "系统更新", "update.currentStatus": "当前状态",
        "update.sourceConfig": "更新源配置", "update.sourceUrl": "更新源 URL",
        "update.sourceType": "源类型", "update.saveSource": "保存更新源",
        "update.packageVerify": "本地包校验", "update.packagePath": "包路径",
        "update.verifyPkg": "校验包", "update.plan": "更新计划",
        "update.genPlan": "生成更新计划", "update.dryRun": "Dry Run",
        "update.doDryRun": "执行 Dry Run", "update.currentVersion": "当前版本",
        "update.latestVersion": "最新版本", "update.status": "状态",
        "update.upToDate": "已是最新", "update.updateAvailable": "有可用更新", "update.noHistory": "暂无更新记录", "update.time": "时间", "update.total": "共", "update.localPkg": "本地更新包", "update.execResults": "执行结果", "update.history": "更新历史", "update.doApply": "执行更新", "update.applyNote": "真实更新需root权限",
        "update.localPkg": "本地包", "update.noPkg": "无",
        "update.action": "操作", "update.target": "目标",
        "update.rollbackPlan": "回滚计划",
        "common.loading": "加载中...", "common.error": "错误",
        "common.retry": "重试", "common.close": "关闭",
        "common.refresh": "刷新", "common.none": "无",
    },
    "en-US": {
        "nav.dashboard": "Overview", "nav.rawMemory": "Raw Memory",
        "nav.windowRegistry": "Window Registry", "nav.zhiyi": "Gets You",
        "nav.recall": "Recall & Provider", "nav.health": "Health Check",
        "nav.settings": "Settings", "nav.update": "System Update",
        "dashboard.title": "Overview", "dashboard.serviceStatus": "Service Status",
        "dashboard.watcher": "Watcher", "dashboard.rawMemory": "Raw Memory",
        "dashboard.zhiyiObjects": "Zhiyi Objects", "dashboard.caseMemory": "Case Memory",
        "dashboard.errorMemory": "Error Memory", "dashboard.prefMemory": "Preference Memory",
        "dashboard.recallService": "Recall Service", "dashboard.providerProxy": "Inject Context",
        "dashboard.phase": "Service Status", "dashboard.sealed": "Local Service Ready",
        "dashboard.sessions": "Sessions", "dashboard.windows": "Windows",
        "dashboard.active": "Active", "dashboard.inactive": "Inactive",
        "dashboard.unknown": "Unknown",
        "memory.title": "Raw Memory", "memory.sourceSystem": "Source System",
        "memory.computer": "Computer", "memory.window": "Window",
        "memory.session": "Session", "memory.channel": "Channel",
        "memory.timeline": "Timeline", "memory.search": "Search",
        "memory.searchPlaceholder": "Search by keyword...",
        "memory.lastUpdated": "Last Updated", "memory.msgCount": "Messages",
        "memory.open": "Open",
        "registry.title": "Window Registry", "registry.canonical": "Canonical Window ID",
        "registry.observed": "Observed Name", "registry.type": "Type",
        "registry.sessionCount": "Session Count", "registry.status": "Status",
        "registry.confirmed": "Confirmed", "registry.pending": "Pending",
        "zhiyi.title": "Gets You", "zhiyi.objects": "Zhiyi Objects",
        "zhiyi.preference": "Preference", "zhiyi.case": "Case",
        "zhiyi.error": "Error", "zhiyi.scope": "Scope",
        "zhiyi.summary": "Summary", "zhiyi.sourceRef": "Source Reference",
        "zhiyi.createdAt": "Created At", "zhiyi.score": "Score",
        "zhiyi.noObjects": "No objects", "zhiyi.injected": "Injected",
        "zhiyi.notInjected": "Not Injected",
        "recall.title": "Recall & Provider", "recall.query": "Query",
        "recall.queryPlaceholder": "Enter query...",
        "recall.scope": "Scope Filter", "recall.scopePlaceholder": "e.g. window/sg, empty for all",
        "recall.type": "Type Filter", "recall.topK": "Top K",
        "recall.threshold": "Threshold", "recall.test": "Test Recall",
        "recall.inject": "Test Inject", "recall.result": "Recall Result",
        "recall.shouldInject": "Should Inject", "recall.confidence": "Confidence",
        "recall.memoryCount": "Matched", "recall.systemPrompt": "System Prompt",
        "recall.userPrompt": "User Prompt", "recall.proxyStatus": "Inject Context Status",
        "health.title": "Health Check", "health.runAll": "Run All Checks",
        "ss.overview": "Source Systems", "ss.liveSync": "Continuous Sync",
        "ss.liveTracked": "Live tracking", "ss.visibleOnly": "Seen, not captured yet",
        "ss.watcherRunning": "Watcher running", "ss.watcherStopped": "Watcher stopped",
        "ss.installKeepsWatching": "Keeps watching local records after install", "ss.initialScanOnly": "Initial scan only",
        "ss.trackedSources": "Live tracked sources", "ss.pendingSources": "Awaiting capture",
        "ss.noPendingSources": "No recognized source is waiting for capture", "ss.localFiles": "Local Files Connector",
        "ss.rescan": "Rescan", "ss.ingest": "Ingest",
        "dashboard.sourceSystems": "Sources", "dashboard.runtime": "Runtime", "dashboard.version": "Version",
        "health.lastRun": "Last Run", "health.status": "Status",
        "health.passed": "Passed", "health.failed": "Failed",
        "health.running": "Running", "health.check": "Check Item",
        "health.detail": "Detail", "health.run": "Run",
        "health.p0raw": "Raw Storage", "health.p0watcher": "Watcher Service",
        "health.p2zhiyi": "Zhiyi Objects", "health.p2sourceRef": "Source Refs",
        "health.p3recall": "Recall Service", "health.p4provider": "Inject Context",
        "settings.title": "Settings", "settings.language": "Language",
        "settings.followSystem": "Follow System",
        "settings.simplifiedChinese": "Simplified Chinese",
        "settings.english": "English", "settings.current": "Current Language",
        "settings.save": "Save", "settings.saved": "Saved",
        "settings.about": "About", "settings.version": "Version",
        "settings.phase": "Phase", "settings.rootPath": "Root Path",
        "update.title": "System Update", "update.currentStatus": "Current Status",
        "update.sourceConfig": "Update Source", "update.sourceUrl": "Source URL",
        "update.sourceType": "Source Type", "update.saveSource": "Save Source",
        "update.packageVerify": "Local Package Verify", "update.packagePath": "Package Path",
        "update.verifyPkg": "Verify Package", "update.plan": "Update Plan",
        "update.genPlan": "Generate Plan", "update.dryRun": "Dry Run",
        "update.doDryRun": "Run Dry Run", "update.currentVersion": "Current Version",
        "update.latestVersion": "Latest Version", "update.status": "Status",
        "update.upToDate": "Up to date", "update.updateAvailable": "Update available", "update.noHistory": "No update history", "update.time": "Time", "update.total": "Total", "update.localPkg": "Local Package", "update.execResults": "Execution Results", "update.history": "Update History", "update.doApply": "Apply Update", "update.applyNote": "Real apply requires root",
        "update.localPkg": "Local Package", "update.noPkg": "None",
        "update.action": "Action", "update.target": "Target",
        "update.rollbackPlan": "Rollback Plan",
        "common.loading": "Loading...", "common.error": "Error",
        "common.retry": "Retry", "common.close": "Close",
        "common.refresh": "Refresh", "common.none": "None",
    }
}

# ─── HTML Template (plain string, no f-string) ───────────────
# All { } in CSS/JS are literal. I18N and PORT use $ placeholder.

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>memcore-cloud Console</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root {
  --bg: #f5f5f7;
  --sidebar-bg: #f0f0f3;
  --card-bg: #ffffff;
  --accent: #007AFF;
  --text: #1d1d1f;
  --text-secondary: #86868b;
  --border: #d2d2d7;
  --radius: 12px;
  --shadow: 0 1px 3px rgba(0,0,0,0.08);
}
html, body { margin:0; height:100%; overflow:hidden; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: var(--bg); color: var(--text); }
.app { display:flex; position:fixed; inset:0; width:100%; height:100%; overflow:hidden; }
.sidebar { width:220px; background:var(--sidebar-bg); border-right:1px solid var(--border);
           display:flex; flex-direction:column; padding:16px 0; height:100%; box-sizing:border-box; overflow-y:auto; flex:0 0 220px; }
.logo { padding:0 20px 20px; font-size:15px; font-weight:600;
         border-bottom:1px solid var(--border); margin-bottom:8px; }
.logo-sub { font-size:11px; color:var(--text-secondary); font-weight:400; }
.nav { flex:1; }
.nav-item { padding:10px 20px; cursor:pointer; border-radius:0;
             transition:background 0.15s; font-size:14px; display:flex;
             align-items:center; gap:8px; }
.nav-item:hover { background:rgba(0,0,0,0.05); }
.nav-item.active { background:var(--accent); color:#fff; }
.nav-item .icon { font-size:16px; }
.nav-footer { padding:12px 20px; border-top:1px solid var(--border); font-size:12px; color:var(--text-secondary); }
.nav-divider { height:1px; background:var(--border); margin:8px 0; }
.nav-section-label { padding:8px 20px 4px; font-size:10px; font-weight:600; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.5px; }
.main { flex:1; height:100%; overflow-y:auto; padding:28px 36px; box-sizing:border-box; }
.page { display:none; color:var(--text); }
.page.active { display:block; }
.page-title { font-size:24px; font-weight:600; margin-bottom:24px; color:var(--text); }
.card { background:var(--card-bg); border-radius:var(--radius); padding:20px;
         box-shadow:var(--shadow); margin-bottom:16px; color:var(--text); }
.card-title { font-size:13px; font-weight:600; color:var(--text-secondary);
               text-transform:uppercase; letter-spacing:0.5px; margin-bottom:12px; }
.card-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(180px, 1fr)); gap:12px; }
.stat { background:var(--bg); border-radius:8px; padding:14px 16px; }
.stat-value { font-size:28px; font-weight:700; }
.stat-label { font-size:12px; color:var(--text-secondary); margin-top:4px; }
.badge { display:inline-block; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:500; }
.badge-green { background:#d1f7c4; color:#1a7f37; }
.badge-red { background:#fee2e2; color:#dc2626; }
.badge-yellow { background:#fef9c3; color:#854d0e; }
.badge-blue { background:#dbeafe; color:#1d4ed8; }
.table-wrap { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { text-align:left; padding:10px 12px; border-bottom:1px solid var(--border);
      color:var(--text-secondary); font-weight:500; font-size:12px; }
td { padding:10px 12px; border-bottom:1px solid var(--border); }
tr:last-child td { border-bottom:none; }
tr:hover td { background:#f9f9fb; }
.form-group { margin-bottom:14px; }
.form-label { font-size:13px; font-weight:500; margin-bottom:6px; display:block; color:var(--text-secondary); }
input, select, textarea { width:100%; padding:8px 12px; border:1px solid var(--border);
                           border-radius:8px; font-size:13px; font-family:inherit;
                           background:#fff; color:var(--text); }
input:focus, select:focus, textarea:focus { outline:none; border-color:var(--accent); }
textarea { resize:vertical; min-height:80px; }
.btn { display:inline-flex; align-items:center; gap:6px; padding:8px 16px;
        border-radius:8px; border:none; cursor:pointer; font-size:13px; font-weight:500;
        transition:opacity 0.15s; }
.btn:hover { opacity:0.85; }
.btn-primary { background:var(--accent); color:#fff; }
.btn-secondary { background:var(--bg); color:var(--text); border:1px solid var(--border); }
.btn-row { display:flex; gap:10px; margin-top:12px; flex-wrap:wrap; }
.form-input, .form-select { width:100%; padding:8px 10px; border:1px solid var(--border); border-radius:6px; background:var(--bg-secondary); color:var(--text-primary); font-size:13px; box-sizing:border-box; }
.form-input:focus, .form-select:focus { outline:1px solid var(--accent); }
.result-box { margin-top:10px; font-size:13px; color:var(--text-secondary); }
.card-title-row { display:flex; justify-content:space-between; align-items:center; }
.card-title-row h3 { margin:0; }
@media (max-width:600px) {
  .btn-row { flex-direction:column; }
  .btn-row .btn { width:100%; box-sizing:border-box; }
  .form-input, .form-select { font-size:14px; }
}
.code-block { background:#1d1d1f; color:#f5f5f7; padding:14px; border-radius:8px;
               font-size:12px; font-family:"SF Mono", Consolas, monospace;
               white-space:pre-wrap; word-break:break-all; max-height:200px; overflow-y:auto; }
.section { margin-top:20px; }
.section-title { font-size:14px; font-weight:600; margin-bottom:12px; }
.tabs { display:flex; gap:4px; margin-bottom:16px; border-bottom:1px solid var(--border); padding-bottom:0; }
.tab { padding:8px 16px; cursor:pointer; font-size:13px; border-bottom:2px solid transparent;
        margin-bottom:-1px; transition:all 0.15s; }
.tab:hover { color:var(--accent); }
.tab.active { border-bottom-color:var(--accent); color:var(--accent); font-weight:500; }
.loading { text-align:center; padding:40px; color:var(--text-secondary); font-size:14px; }
.health-item { display:flex; align-items:center; gap:12px; padding:12px 0;
                border-bottom:1px solid var(--border); }
.health-item:last-child { border-bottom:none; }
.health-name { flex:1; font-size:14px; }
.health-detail { font-size:12px; color:var(--text-secondary); }
.settings-group { margin-bottom:28px; }
.settings-group-title { font-size:16px; font-weight:600; margin-bottom:14px; }
.radio-group { display:flex; flex-direction:column; gap:10px; }
.radio-item { display:flex; align-items:center; gap:10px; cursor:pointer; padding:10px 14px;
                background:var(--bg); border-radius:8px; border:1px solid var(--border); }
.radio-item input { width:auto; }
</style>
</head>
<body>
<div class="app">
  <div class="sidebar">
    <div class="logo">
      <div id="app-name">memcore-cloud</div>
      <div class="logo-sub" id="app-subtitle">M1 Console</div>
    </div>
    <div class="nav">
      <div class="nav-item active" data-page="dashboard" onclick="showPage('dashboard')">
        <span class="icon">&#9710;</span><span data-i18n="nav.dashboard">总览</span>
      </div>
      <div class="nav-item" data-page="memory" onclick="showPage('memory')">
        <span class="icon">&#9673;</span><span data-i18n="nav.rawMemory">原始记忆</span>
      </div>
      <div class="nav-item" data-page="registry" onclick="showPage('registry')">
        <span class="icon">&#9688;</span><span data-i18n="nav.windowRegistry">窗口归属</span>
      </div>
      <div class="nav-item" data-page="zhiyi" onclick="showPage('zhiyi')">
        <span class="icon">&#9648;</span><span data-i18n="nav.zhiyi">知意</span>
      </div>
      <div class="nav-item" data-page="recall" onclick="showPage('recall')">
        <span class="icon">&#9649;</span><span data-i18n="nav.recall">召回与注入</span>
      </div>
      <div class="nav-item" data-page="health" onclick="showPage('health')">
        <span class="icon">&#9687;</span><span data-i18n="nav.health">健康检查</span>
      </div>
      <div class="nav-item" data-page="source-systems" onclick="showPage('source-systems')">
        <span class="icon">&#9632;</span><span data-i18n="nav.sourceSystems">数据源</span>
      </div>
      <div class="nav-item" data-page="settings" onclick="showPage('settings')">
        <span class="icon">&#9685;</span><span data-i18n="nav.settings">设置</span>
      </div>
      <div class="nav-item" data-page="update" onclick="showPage('update')">
        <span class="icon">&#8635;</span><span data-i18n="nav.update">系统更新</span>
      </div>
      <div class="nav-item" data-page="runtime" onclick="showPage('runtime')">
        <span class="icon">&#9675;</span><span data-i18n="nav.runtime">Runtime</span>
      </div>
      <div class="nav-divider"></div>
      <div class="nav-section-label">M4 移动端</div>
      <div class="nav-item" data-page="mobile-overview" onclick="showPage('mobile-overview')">
        <span class="icon">&#9711;</span><span>移动总览</span>
      </div>
      <div class="nav-item" data-page="task-results" onclick="showPage('task-results')">
        <span class="icon">&#9744;</span><span>任务结果</span>
      </div>
      <div class="nav-item" data-page="risk-backlog" onclick="showPage('risk-backlog')">
        <span class="icon">&#9888;</span><span>风险挂账</span>
      </div>
      <div class="nav-item" data-page="copy-center" onclick="showPage('copy-center')">
        <span class="icon">&#9098;</span><span>复制中心</span>
      </div>
    </div>
    <div class="nav-footer" id="phase-badge">
      <span class="badge badge-blue" data-i18n="dashboard.sealed">本机服务就绪</span>
    </div>
  </div>
  <div class="main">
    <div class="page active" id="page-dashboard">
      <div class="page-title" data-i18n="dashboard.title">总览</div>
      <div class="card-grid" id="dashboard-stats"></div>
    </div>
    <div class="page" id="page-memory">
      <div class="page-title" data-i18n="memory.title">原始记忆</div>
      <div class="card">
        <div class="card-grid" id="memory-stats"></div>
      </div>
      <!-- M3-3: Lifecycle Overlay Stats -->
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">Lifecycle Overlay (M3-3)</span>
          <span class="badge badge-purple" id="m3-lifecycle-badge">-</span>
        </div>
        <div id="m3-lifecycle-stats"><div class="loading">loading...</div></div>
      </div>
      <div class="card">
        <div class="table-wrap">
          <table id="memory-table">
            <thead><tr>
              <th data-i18n="memory.window">窗口</th>
              <th data-i18n="memory.session">会话</th>
              <th data-i18n="memory.channel">频道</th>
              <th data-i18n="memory.msgCount">消息数</th>
            </tr></thead>
            <tbody id="memory-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="page" id="page-registry">
      <div class="page-title" data-i18n="registry.title">窗口归属</div>
      <div class="card">
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th data-i18n="registry.canonical">规范窗口ID</th>
              <th data-i18n="registry.observed">观测名称</th>
              <th data-i18n="registry.sessionCount">会话数</th>
              <th data-i18n="registry.status">状态</th>
            </tr></thead>
            <tbody id="registry-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="page" id="page-zhiyi">
      <div class="page-title" data-i18n="zhiyi.title">知意</div>
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">垃圾桶</span>
          <span class="badge badge-red" id="zhiyi-recycle-count">-</span>
        </div>
        <div id="zhiyi-recycle-list" class="result-box">加载中...</div>
      </div>
      <div class="tabs">
        <div class="tab active" data-tab="all" onclick="filterZhiyi('all')" data-i18n="zhiyi.objects">全部</div>
        <div class="tab" data-tab="case_memory" onclick="filterZhiyi('case_memory')" data-i18n="zhiyi.case">案例</div>
        <div class="tab" data-tab="error_memory" onclick="filterZhiyi('error_memory')" data-i18n="zhiyi.error">错误</div>
        <div class="tab" data-tab="preference_memory" onclick="filterZhiyi('preference_memory')" data-i18n="zhiyi.preference">偏好</div>
      </div>
      <div class="card">
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th data-i18n="zhiyi.scope">作用域</th>
              <th data-i18n="zhiyi.summary">摘要</th>
              <th data-i18n="zhiyi.score">置信度</th>
              <th data-i18n="registry.status">状态</th>
            </tr></thead>
            <tbody id="zhiyi-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="page" id="page-recall">
      <div class="page-title" data-i18n="recall.title">召回与注入</div>
      <div class="card">
        <div class="form-group">
          <label class="form-label" data-i18n="recall.query">查询内容</label>
          <input type="text" id="recall-query" data-i18n-placeholder="recall.queryPlaceholder" placeholder="输入查询内容...">
        </div>
        <div class="card-grid" style="grid-template-columns:1fr 1fr 80px 80px">
          <div class="form-group">
            <label class="form-label" data-i18n="recall.scope">作用域过滤</label>
            <input type="text" id="recall-scope" data-i18n-placeholder="recall.scopePlaceholder" placeholder="window/sg">
          </div>
          <div class="form-group">
            <label class="form-label" data-i18n="recall.type">类型过滤</label>
            <select id="recall-type">
              <option value="">全部</option>
              <option value="case_memory">案例</option>
              <option value="error_memory">错误</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label" data-i18n="recall.topK">Top K</label>
            <input type="number" id="recall-topk" value="3" min="1" max="20">
          </div>
          <div class="form-group">
            <label class="form-label" data-i18n="recall.threshold">阈值</label>
            <input type="number" id="recall-threshold" value="0.7" min="0" max="1" step="0.1">
          </div>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" onclick="testRecall()" data-i18n="recall.test">测试召回</button>
          <button class="btn btn-secondary" onclick="testInject()" data-i18n="recall.inject">测试注入</button>
        </div>
      </div>
      <div class="card" id="recall-result-card" style="display:none">
        <div class="card-title" data-i18n="recall.result">召回结果</div>
        <div id="recall-result"></div>
      </div>
      <div class="card" id="recall-inject-card" style="display:none">
        <div class="card-title" data-i18n="recall.systemPrompt">System Prompt</div>
        <div class="code-block" id="inject-system-prompt"></div>
        <div class="section">
          <div class="card-title" data-i18n="recall.userPrompt">User Prompt</div>
          <div class="code-block" id="inject-user-prompt"></div>
        </div>
      </div>
      <!-- M3-5: Recent Recall Runtime Status -->
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">M3 Recent Recall Status</span>
          <span class="badge badge-purple" id="m3-recall-badge">-</span>
        </div>
        <div id="m3-recall-stats"><div class="loading">loading...</div></div>
      </div>
    </div>
    <div class="page" id="page-health">
      <div class="page-title" data-i18n="health.title">健康检查</div>
      <div class="card">
        <div class="btn-row" style="margin-bottom:16px">
          <button class="btn btn-primary" onclick="runHealthCheck()" data-i18n="health.runAll">运行全部检查</button>
        </div>
        <div id="health-results"></div>
      </div>
      <!-- M3-6: AUDIT Risk Status -->
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">AUDIT 风险状态</span>
          <span class="badge badge-purple" id="m3-audit-badge">-</span>
        </div>
        <div id="m3-audit-risks"><div class="loading">loading...</div></div>
      </div>
    </div>
    <div class="page" id="page-source-systems">
      <div class="page-title" data-i18n="nav.sourceSystems">数据源</div>
      <div class="card">
        <div class="card-title-row">
          <h3 data-i18n="ss.liveSync">持续同步</h3>
          <span class="badge badge-blue" id="source-systems-continuous-badge">-</span>
        </div>
        <div id="source-systems-continuous">Loading...</div>
      </div>
      <div class="card">
        <div class="card-title-row"><h3 data-i18n="ss.overview">数据源总览</h3><button class="btn btn-secondary" style="font-size:11px;padding:4px 10px;" onclick="loadSourceSystems()">&#8635;</button></div>
        <div id="source-systems-list">Loading...</div>
      </div>
      <div class="card">
        <h3 data-i18n="ss.localFiles">本地文件连接器</h3>
        <div id="source-systems-local-files">Loading...</div>
      </div>
    </div>
    <div class="page" id="page-settings">
      <div class="page-title" data-i18n="settings.title">设置</div>
      <div class="card">
        <div class="settings-group">
          <div class="settings-group-title" data-i18n="settings.language">语言</div>
          <div class="radio-group">
            <label class="radio-item">
              <input type="radio" name="lang" value="follow" onchange="setLanguage('follow')">
              <span data-i18n="settings.followSystem">跟随系统</span>
            </label>
            <label class="radio-item">
              <input type="radio" name="lang" value="zh-CN" onchange="setLanguage('zh-CN')">
              <span data-i18n="settings.simplifiedChinese">简体中文</span>
            </label>
            <label class="radio-item">
              <input type="radio" name="lang" value="en-US" onchange="setLanguage('en-US')">
              <span data-i18n="settings.english">English</span>
            </label>
          </div>
          <div class="btn-row" style="margin-top:16px">
            <button class="btn btn-primary" onclick="saveLanguage()" data-i18n="settings.save">保存</button>
          </div>
        </div>
        <div class="settings-group">
          <div class="settings-group-title" data-i18n="settings.about">关于</div>
          <table>
            <tr><td data-i18n="settings.version" style="color:var(--text-secondary);width:120px">版本</td><td>2026.6.20</td></tr>
            <tr><td data-i18n="settings.phase" style="color:var(--text-secondary)">状态</td><td><span data-i18n="dashboard.sealed">本机服务就绪</span></td></tr>
            <tr><td data-i18n="settings.rootPath" style="color:var(--text-secondary)">根目录</td><td>MEMCORE_ROOT</td></tr>
          </table>
        </div>
      </div>
    </div>
    <div class="page" id="page-update">
      <div class="page-title" data-i18n="update.title">系统更新</div>

      <!-- Card 1: Current version and running info -->
      <div class="card">
        <div class="card-title-row"><h3 data-i18n="update.currentStatus">当前状态</h3><button class="btn btn-secondary" style="font-size:11px;padding:4px 10px;" onclick="loadUpdateStatus()">&#8635;</button></div>
        <div id="update-status">Loading...</div>
      </div>

      <!-- Card 2: Update source configuration -->
      <div class="card">
        <h3 data-i18n="update.sourceConfig">更新源配置</h3>
        <div class="form-group">
          <label data-i18n="update.sourceUrl">更新源 URL</label>
          <input type="text" id="update-source-url" class="form-input" placeholder="https://github.com/USER/repo/releases/latest.json">
        </div>
        <div class="form-group">
          <label data-i18n="update.sourceType">源类型</label>
          <select id="update-source-type" class="form-select">
            <option value="local">本地包</option>
            <option value="github">GitHub Release</option>
            <option value="custom">自定义 URL</option>
          </select>
        </div>
        <button class="btn btn-primary" onclick="updateSaveSource()" data-i18n="update.saveSource">保存</button>
      </div>

      <!-- Card 3: Local package management -->
      <div class="card">
        <h3 data-i18n="update.localPkg">本地更新包</h3>
        <div class="form-group">
          <label data-i18n="update.packagePath">包路径</label>
          <input type="text" id="update-pkg-path" class="form-input" placeholder="/path/to/memcore-cloud-x.x.x-linux-x86_64.tar.gz">
        </div>
        <div class="btn-row">
          <button class="btn btn-secondary" onclick="updateVerifyPkg()" data-i18n="update.verifyPkg">校验</button>
          <button class="btn btn-secondary" onclick="updateGeneratePlan()" data-i18n="update.genPlan">生成计划</button>
          <button class="btn btn-primary" onclick="updateApply()" data-i18n="update.doApply" id="btn-update-apply">执行更新</button>
        </div>
        <div id="update-apply-warning" style="margin-top:6px;font-size:12px;color:#f59e0b;"></div>
        <div id="update-verify-result" class="result-box"></div>
      </div>

      <!-- Card 4: Update Plan -->
      <div class="card">
        <h3 data-i18n="update.plan">更新计划</h3>
        <div id="update-plan-result" class="result-box">Loading...</div>
      </div>

      <!-- Card 5: Execution results -->
      <div class="card">
        <div class="card-title-row"><h3 data-i18n="update.execResults">执行结果</h3><button class="btn btn-secondary" style="font-size:11px;padding:4px 10px;" onclick="updateDryRun()">&#9654; Dry Run</button></div>
        <div id="update-dryrun-result" class="result-box">Loading...</div>
      </div>

      <!-- Card 6: Update history and rollback -->
      <div class="card">
        <div class="card-title-row"><h3 data-i18n="update.history">更新历史</h3><button class="btn btn-secondary" style="font-size:11px;padding:4px 10px;" onclick="loadUpdateHistory()">&#8635;</button></div>
        <div id="update-history" class="result-box">Loading...</div>
      </div>
    </div>
  </div>
</div>

    <div class="page" id="page-runtime">
      <div class="page-title" data-i18n="runtime.title">Runtime Profile</div>

      <!-- Card 1: memcore-cloud -->
      <div class="card">
        <div class="card-title-row">
          <span class="card-title" data-i18n="runtime.memcoreTitle">memcore-cloud</span>
          <span class="badge badge-blue" id="runtime-memcore-version">-</span>
        </div>
        <div class="info-grid">
          <div class="info-row"><span data-i18n="runtime.selected">Selected</span>: <span id="runtime-memcore-selected">-</span></div>
          <div class="info-row"><span data-i18n="runtime.instances">Instances</span>: <span id="runtime-memcore-instances">-</span></div>
          <div class="info-row"><span data-i18n="runtime.stale">Stale</span>: <span id="runtime-memcore-stale">-</span></div>
          <div class="info-row"><span data-i18n="runtime.mismatch">Mismatch</span>: <span id="runtime-memcore-mismatch">-</span></div>
        </div>
        <div class="btn-row">
          <button class="btn btn-secondary" onclick="loadRuntimeMemcore()" data-i18n="runtime.refresh">刷新</button>
        </div>
      </div>

      <!-- Card 2: OpenClaw -->
      <div class="card">
        <div class="card-title-row">
          <span class="card-title" data-i18n="runtime.ocTitle">OpenClaw</span>
          <span class="badge badge-purple" id="runtime-oc-version">-</span>
        </div>
        <div class="info-grid">
          <div class="info-row"><span data-i18n="runtime.selected">Selected</span>: <span id="runtime-oc-selected">-</span></div>
          <div class="info-row"><span data-i18n="runtime.instances">Instances</span>: <span id="runtime-oc-instances">-</span></div>
          <div class="info-row"><span data-i18n="runtime.stale">Stale</span>: <span id="runtime-oc-stale">-</span></div>
          <div class="info-row"><span data-i18n="runtime.mismatch">Mismatch</span>: <span id="runtime-oc-mismatch">-</span></div>
        </div>
        <div class="btn-row">
          <button class="btn btn-secondary" onclick="loadRuntimeOpenClaw()" data-i18n="runtime.refresh">刷新</button>
        </div>
      </div>

      <!-- Card 3: M3 Runtime Status (J2-J7 / Lifecycle / Gateway) -->
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">M3 Runtime Status</span>
          <span class="badge badge-purple" id="m3-j2-j7-badge">-</span>
        </div>
        <div class="info-grid">
          <div class="info-row"><span>Gateway</span>: <span id="m3-gw-status">-</span></div>
          <div class="info-row"><span>Device Paired</span>: <span id="m3-device-paired">-</span></div>
          <div class="info-row"><span>J2 Deduplication</span>: <span id="m3-j2-dedup">-</span></div>
          <div class="info-row"><span>J3 Superseded Filtered</span>: <span id="m3-j3-filtered">-</span></div>
          <div class="info-row"><span>Lifecycle Overlay</span>: <span id="m3-lifecycle-entries">-</span></div>
          <div class="info-row"><span>Status Dist</span>: <span id="m3-status-dist" style="font-size:11px">-</span></div>
        </div>
        <div class="btn-row">
          <button class="btn btn-secondary" onclick="loadM3Runtime()">&#8635;</button>
        </div>
      </div>

      <!-- Card 4: Hermes (experimental) -->
      <div class="card">
        <div class="card-title-row">
          <span class="card-title" data-i18n="runtime.hermesTitle">Hermes</span>
          <span class="badge badge-yellow" id="runtime-hermes-version">-</span>
          <span class="badge badge-yellow" data-i18n="runtime.experimental">experimental</span>
        </div>
        <div class="info-grid">
          <div class="info-row"><span data-i18n="runtime.hermesInstances">Instances</span>: <span id="runtime-hermes-instances">-</span></div>
          <div class="info-row"><span data-i18n="runtime.hermesRunning">Running</span>: <span id="runtime-hermes-running">-</span></div>
          <div class="info-row"><span data-i18n="runtime.hermesConfig">Config</span>: <span id="runtime-hermes-config">-</span></div>
          <div class="info-row"><span data-i18n="runtime.hermesRoot">Install Root</span>: <span id="runtime-hermes-root">-</span></div>
        </div>
        <div class="btn-row">
          <button class="btn btn-secondary" onclick="loadRuntimeHermes()" data-i18n="runtime.refresh">刷新</button>
        </div>
      </div>

    </div>

    <!-- M4: Mobile Overview -->
    <div class="page" id="page-mobile-overview">
      <div class="page-title">移动总览</div>
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">项目状态</span>
          <span class="badge badge-purple" id="m4-task-count">-</span>
        </div>
        <div id="m4-overview-stats"><div class="loading">loading...</div></div>
      </div>
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">最近完成</span>
        </div>
        <div id="m4-recent-tasks"><div class="loading">loading...</div></div>
      </div>
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">风险告警</span>
          <span class="badge badge-red" id="m4-risk-count">-</span>
        </div>
        <div id="m4-risk-summary"><div class="loading">loading...</div></div>
      </div>
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">下一步决策</span>
        </div>
        <div id="m4-next-decision"><div class="loading">loading...</div></div>
      </div>
    </div>

    <!-- M4: Task Results -->
    <div class="page" id="page-task-results">
      <div class="page-title">任务结果</div>
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">全部任务</span>
          <span class="badge badge-blue" id="m4-total-tasks">-</span>
        </div>
        <div id="m4-task-filters" style="margin-bottom:12px">
          <button class="btn btn-sm" onclick="m4FilterTasks('all')" id="m4-filter-all">全部</button>
          <button class="btn btn-sm" onclick="m4FilterTasks('pass')" id="m4-filter-pass">通过</button>
          <button class="btn btn-sm" onclick="m4FilterTasks('fail')" id="m4-filter-fail">失败</button>
          <button class="btn btn-sm" onclick="m4FilterTasks('unknown')" id="m4-filter-unknown">未知</button>
        </div>
        <div id="m4-task-list"><div class="loading">loading...</div></div>
      </div>
      <div class="card" id="m4-task-detail-card" style="display:none">
        <div class="card-title-row">
          <span class="card-title" id="m4-task-detail-title">任务详情</span>
          <button class="btn btn-sm" onclick="m4CloseTaskDetail()">关闭</button>
        </div>
        <div id="m4-task-detail-content"></div>
      </div>
    </div>

    <!-- M4: Risk Backlog -->
    <div class="page" id="page-risk-backlog">
      <div class="page-title">风险挂账</div>
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">已知风险</span>
          <span class="badge badge-red" id="m4-risk-total">-</span>
        </div>
        <div id="m4-risk-list"><div class="loading">loading...</div></div>
      </div>
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">风险说明</span>
        </div>
        <div style="font-size:13px;color:var(--text-secondary);padding:8px 0">
          <p>以下风险已记录，不阻塞当前使用。风险挂账是预期行为，增量处理进行中。</p>
        </div>
      </div>
    </div>

    <!-- M4: Copy Center -->
    <div class="page" id="page-copy-center">
      <div class="page-title">复制中心</div>
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">一键复制摘要</span>
        </div>
        <div id="m4-copy-task-list"><div class="loading">loading...</div></div>
      </div>
      <div class="card">
        <div class="card-title-row">
          <span class="card-title">下一步决策选项</span>
        </div>
        <div id="m4-copy-next-decision"><div class="loading">loading...</div></div>
      </div>
    </div>
  </div>
</div>

<script>
var I18N_DATA = $I18N_JSON;
var PORT_NUM = $PORT;
var MEMCORE_ROOT = $MEMCORE_ROOT_JSON;

function t(key) {
  var lang = (currentLang === 'follow') ?
    (navigator.language.startsWith('en') ? 'en-US' : 'zh-CN') : currentLang;
  return (I18N_DATA[lang] && I18N_DATA[lang][key]) ? I18N_DATA[lang][key] :
    (I18N_DATA['zh-CN'] && I18N_DATA['zh-CN'][key]) ? I18N_DATA['zh-CN'][key] : key;
}
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function applyI18N() {
  document.querySelectorAll('[data-i18n]').forEach(function(el) {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {
    el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
  });
  document.querySelectorAll('.nav-item span[data-i18n]').forEach(function(el) {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
}

function setLanguage(lang) {
  currentLang = lang;
  var radios = document.querySelectorAll('input[name=lang]');
  for (var i = 0; i < radios.length; i++) { radios[i].checked = radios[i].value === lang; }
  applyI18N();
}

function resetConsoleScroll() {
  window.scrollTo(0, 0);
  if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0;
  ['.app', '.sidebar', '.main'].forEach(function(sel) {
    var el = document.querySelector(sel);
    if (el) {
      el.scrollTop = 0;
      el.scrollLeft = 0;
    }
  });
}

function saveLanguage() {
  localStorage.setItem('console_lang', currentLang);
  alert(currentLang === 'en-US' ? 'Saved' : '已保存');
}

var CONSOLE_CSRF_TOKEN = $CONSOLE_CSRF_TOKEN;
function postHeaders() {
  return {
    'Content-Type': 'application/json',
    'X-Memcore-Console-Token': CONSOLE_CSRF_TOKEN
  };
}

async function loadDashboard() {
  var el = document.getElementById('dashboard-stats');
  el.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  try {
    var dashboardData = await Promise.all([
      fetch('/api/watcher').then(function(r){return r.json();}).catch(function(){return {};}),
      fetch('/api/raw_stats').then(function(r){return r.json();}).catch(function(){return {};}),
      fetch('/api/zhiyi_stats').then(function(r){return r.json();}).catch(function(){return {};}),
      fetch('/api/v1/source-systems').then(function(r){return r.json();}).catch(function(){return {};}),
      fetch('/api/v1/runtime/profile').then(function(r){return r.json();}).catch(function(){return {};}),
      fetch('/api/v1/update/status').then(function(r){return r.json();}).catch(function(){return {};}),
      fetch('/api/m3/status/overview').then(function(r){return r.json();}).catch(function(){return {};}),
      fetch('/api/m3/status/openclaw-runtime').then(function(r){return r.json();}).catch(function(){return {};}),
      fetch('/api/m3/status/audit-risks').then(function(r){return r.json();}).catch(function(){return {};})
    ]);
    var watcher = dashboardData[0];
    var rawStats = dashboardData[1];
    var zhiyiStats = dashboardData[2];
    var ssData = dashboardData[3];
    var rtProfile = dashboardData[4];
    var updStatus = dashboardData[5];
    var m3Overview = dashboardData[6];
    var m3Oc = dashboardData[7];
    var m3Audit = dashboardData[8];
    var wStatus = watcher.active;
    var ssCount = (ssData.all || []).length;
    var ssActive = (ssData.active || []).length;
    var rtMC = rtProfile.memcore_cloud || {};
    var rtOC = rtProfile.openclaw || {};
    var rtSelected = (rtMC.selected_runtime || {}).source || (rtOC.selected_runtime || {}).source || '-';
    var updVersion = updStatus.current_version || '-';
    // Gateway status from M3-2
    var gwUp = m3Oc.gateway_reachable;
    var gwBadge = gwUp ? '<span class="badge badge-green">&#9673; up</span>' : '<span class="badge badge-red">&#9675; down</span>';
    // Audit alert from M3-6
    var auditAlert = '';
    if (m3Audit.total_risks > 0) {
      var severity = m3Audit.risks && m3Audit.risks[0] && m3Audit.risks[0].severity;
      var auditCls = severity === 'CRITICAL' ? 'badge-red' : (severity === 'HIGH' ? 'badge-orange' : 'badge-yellow');
      auditAlert = '<div style="margin-top:8px;padding:8px;background:var(--bg-secondary);border-radius:6px">'+
        '<span class="badge '+auditCls+'">AUDIT '+m3Audit.total_risks+' risk(s)</span> '+
        '<span style="font-size:11px;color:var(--text-secondary)">audit1_pass='+m3Audit.audit1_pass+'</span></div>';
    }
    // Service ports from M3-1
    var ports = m3Overview.service_ports || {};
    var p3Status = ports.p3recall === 'up' ? '<span class="badge badge-green">p3 up</span>' : '<span class="badge badge-red">p3 down</span>';
    el.innerHTML =
      '<div class="stat"><div class="stat-value">'+(wStatus ? '&#9673; '+t('dashboard.active') : '&#9675; '+t('dashboard.inactive'))+'</div><div class="stat-label" data-i18n="dashboard.watcher">Watcher</div></div>'+
      '<div class="stat"><div class="stat-value">'+rawStats.sessions+'</div><div class="stat-label" data-i18n="dashboard.sessions">会话数</div></div>'+
      '<div class="stat"><div class="stat-value">'+rawStats.windows+'</div><div class="stat-label" data-i18n="dashboard.windows">窗口数</div></div>'+
      '<div class="stat"><div class="stat-value">'+rawStats.messages+'</div><div class="stat-label">消息数</div></div>'+
      '<div class="stat"><div class="stat-value">'+(zhiyiStats.case_memory||0)+'</div><div class="stat-label" data-i18n="dashboard.caseMemory">案例记忆</div></div>'+
      '<div class="stat"><div class="stat-value">'+(zhiyiStats.error_memory||0)+'</div><div class="stat-label" data-i18n="dashboard.errorMemory">错误记忆</div></div>'+
      '<div class="stat"><div class="stat-value">'+ssActive+'/'+ssCount+'</div><div class="stat-label" data-i18n="dashboard.sourceSystems">数据源</div></div>'+
      '<div class="stat"><div class="stat-value" style="font-size:14px">'+rtSelected+'</div><div class="stat-label" data-i18n="dashboard.runtime">Runtime</div></div>'+
      '<div class="stat"><div class="stat-value">v'+updVersion+'</div><div class="stat-label" data-i18n="dashboard.version">版本</div></div>'+
      '<div class="stat"><div class="stat-value">'+p3Status+' '+gwBadge+'</div><div class="stat-label">Services / Gateway</div></div>'+
      '<div class="stat"><div class="stat-value"><span class="badge badge-blue">'+t('dashboard.sealed')+'</span></div><div class="stat-label" data-i18n="dashboard.phase">服务状态</div></div>';
    // Append audit alert
    if (auditAlert) el.innerHTML += auditAlert;
  } catch(e) {
    el.innerHTML = '<div class="loading">'+t('common.error')+': '+e.message+'</div>';
  }
}

async function loadMemory() {
  var statsEl = document.getElementById('memory-stats');
  var tbody = document.getElementById('memory-tbody');
  statsEl.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  tbody.innerHTML = '<tr><td colspan=4>'+t('common.loading')+'</td></tr>';
  try {
    var data = await fetch('/api/raw_sessions').then(function(r){return r.json();});
    statsEl.innerHTML =
      '<div class="stat"><div class="stat-value">'+data.sessions+'</div><div class="stat-label" data-i18n="dashboard.sessions">会话数</div></div>'+
      '<div class="stat"><div class="stat-value">'+data.windows+'</div><div class="stat-label" data-i18n="dashboard.windows">窗口数</div></div>'+
      '<div class="stat"><div class="stat-value">'+data.messages+'</div><div class="stat-label">消息数</div></div>';
    tbody.innerHTML = data.sessions_list.map(function(s) {
      return '<tr><td>'+s.window+'</td><td style="font-size:11px;color:var(--text-secondary)">'+s.session_id.substring(0,16)+'...</td>'+
             '<td><span class="badge badge-blue">'+s.channel+'</span></td><td>'+s.msg_count+'</td></tr>';
    }).join('');
    loadM3LifecycleOverlay();
  } catch(e) {
    tbody.innerHTML = '<tr><td colspan=4>'+t('common.error')+'</td></tr>';
  }
}
async function loadM3LifecycleOverlay() {
  var el = document.getElementById('m3-lifecycle-stats');
  var badge = document.getElementById('m3-lifecycle-badge');
  if (!el) return;
  el.innerHTML = '<div class="loading">loading...</div>';
  try {
    var r = await fetch('/api/m3/status/memory-runtime').then(function(res){return res.json();}).catch(function(){return {};});
    var lc = r.lifecycle_overlay || {};
    var total = r.lifecycle_overlay_total || 0;
    badge.textContent = total + ' entries';
    badge.className = total > 0 ? 'badge badge-green' : 'badge badge-gray';
    el.innerHTML =
      '<div class="info-grid">'+
      '<div class="info-row"><span>case_memory overlay</span>: <span>'+(lc.case_memory||0)+' entries</span></div>'+
      '<div class="info-row"><span>error_memory overlay</span>: <span>'+(lc.error_memory||0)+' entries</span></div>'+
      '<div class="info-row"><span>Total overlay</span>: <span>'+total+' entries</span></div>'+
      '<div class="info-row"><span>case_memory zhiyi</span>: <span>'+(r.zhiyi_objects&&r.zhiyi_objects.case_memory||'-')+'</span></div>'+
      '<div class="info-row"><span>error_memory zhiyi</span>: <span>'+(r.zhiyi_objects&&r.zhiyi_objects.error_memory||'-')+'</span></div>'+
      '</div>';
  } catch(e) {
    el.innerHTML = '<div style="color:var(--text-secondary);font-size:13px">Error: '+e.message+'</div>';
  }
}

async function loadRegistry() {
  var tbody = document.getElementById('registry-tbody');
  tbody.innerHTML = '<tr><td colspan=4>'+t('common.loading')+'</td></tr>';
  try {
    var data = await fetch('/api/alias_map').then(function(r){return r.json();});
    var cws = data.canonical_windows || {};
    var html = '';
    for (var cw in cws) {
      var info = cws[cw];
      var names = info.observed_names ? info.observed_names.join(', ') : '-';
      html += '<tr><td><code style="font-size:12px;background:#f0f0f3;padding:2px 6px;border-radius:4px">'+cw+'</code></td>'+
              '<td style="font-size:12px;color:var(--text-secondary)">'+names+'</td>'+
              '<td>'+(info.session_count||0)+'</td>'+
              '<td><span class="badge badge-green">'+t('registry.confirmed')+'</span></td></tr>';
    }
    tbody.innerHTML = html || '<tr><td colspan=4>'+t('common.none')+'</td></tr>';
  } catch(e) {
    tbody.innerHTML = '<tr><td colspan=4>'+t('common.error')+'</td></tr>';
  }
}

var zhiyiAll = [];
var zhiyiRecycleBin = [];
var zhiyiFilter = 'all';

async function loadZhiyi() {
  var tbody = document.getElementById('zhiyi-tbody');
  tbody.innerHTML = '<tr><td colspan=4>'+t('common.loading')+'</td></tr>';
  try {
    zhiyiAll = await fetch('/api/zhiyi_objects').then(function(r){return r.json();});
    zhiyiRecycleBin = await fetch('/api/v1/zhiyi/experience-recycle-bin?limit=50').then(function(r){return r.json();}).catch(function(){return {items:[]};});
    applyZhiyiFilter();
  } catch(e) {
    tbody.innerHTML = '<tr><td colspan=4>'+t('common.error')+'</td></tr>';
  }
}

function filterZhiyi(type) {
  zhiyiFilter = type;
  document.querySelectorAll('.tab').forEach(function(tb){ tb.classList.remove('active'); });
  var activeTab = document.querySelector('.tab[data-tab="'+type+'"]');
  if (activeTab) activeTab.classList.add('active');
  applyZhiyiFilter();
}

function _zhiyi_status_label(o) {
  if (!o) return t('zhiyi.notInjected');
  if (o.deleted_state === 'recycle_bin' || o.status === 'recycled') return '垃圾桶';
  if (o.archive_status === 'restored') return '已恢复';
  if (o.archive_status === 'recycled') return '已回收';
  if (o.status === 'active' || o.status === 'adopted') return '在馆';
  return o.status || t('zhiyi.notInjected');
}

function _zhiyi_status_badge_class(o) {
  if (!o) return 'badge badge-blue';
  if (o.deleted_state === 'recycle_bin' || o.status === 'recycled') return 'badge badge-red';
  if (o.archive_status === 'restored') return 'badge badge-green';
  if (o.status === 'active' || o.status === 'adopted') return 'badge badge-green';
  return 'badge badge-blue';
}

async function _restoreZhiyiExperience(expId) {
  if (!expId) return;
  try {
    var res = await fetch('/api/v1/zhiyi/experiences/' + encodeURIComponent(expId) + '/restore', {
      method: 'POST',
      headers: postHeaders(),
      body: JSON.stringify({reason: 'console_restore'})
    }).then(function(r){return r.json();});
    if (res && res.ok) {
      await loadZhiyi();
      await loadZhiyiRecycleBin();
      m4ShowToast('已恢复');
    } else {
      m4ShowToast((res && res.error) ? res.error : '恢复失败');
    }
  } catch (e) {
    m4ShowToast('恢复失败');
  }
}

function applyZhiyiFilter() {
  var tbody = document.getElementById('zhiyi-tbody');
  var filtered = (zhiyiFilter === 'all') ? zhiyiAll : zhiyiAll.filter(function(o){ return o._type === zhiyiFilter; });
  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan=4>'+t('zhiyi.noObjects')+'</td></tr>';
    return;
  }
  tbody.innerHTML = filtered.map(function(o) {
    var recycleFlag = o.deleted_state === 'recycle_bin' || o.status === 'recycled';
    var statusLabel = _zhiyi_status_label(o);
    var badgeClass = _zhiyi_status_badge_class(o);
    var extra = recycleFlag ? ' <button class="btn btn-secondary" style="padding:4px 8px;font-size:11px" data-restore-exp-id="'+escapeHtml(o.exp_id||'')+'">恢复</button>' : '';
    return '<tr><td><code style="font-size:11px;background:#f0f0f3;padding:2px 6px;border-radius:4px">'+escapeHtml(o.scope||'-')+'</code></td>'+
           '<td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+escapeHtml(o.summary||'')+'">'+escapeHtml(((o.summary||'-')+'').substring(0,80))+'</td>'+
           '<td>'+((o.score||0).toFixed(2))+'</td>'+
           '<td><span class="'+badgeClass+'">'+escapeHtml(statusLabel)+'</span>'+extra+'</td></tr>';
  }).join('');
}

document.addEventListener('click', function(ev) {
  var btn = ev.target && ev.target.closest ? ev.target.closest('button[data-restore-exp-id]') : null;
  if (!btn) return;
  _restoreZhiyiExperience(btn.getAttribute('data-restore-exp-id') || '');
});

async function testRecall() {
  var query = document.getElementById('recall-query').value;
  var scope = document.getElementById('recall-scope').value;
  var type = document.getElementById('recall-type').value;
  var topk = parseInt(document.getElementById('recall-topk').value) || 3;
  var threshold = parseFloat(document.getElementById('recall-threshold').value) || 0.7;
  var body = { query: query, top_k: topk, threshold: threshold };
  if (scope) body.scope_filter = scope;
  if (type) body.type_filter = [type];
  document.getElementById('recall-result-card').style.display = 'block';
  document.getElementById('recall-inject-card').style.display = 'none';
  document.getElementById('recall-result').innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  try {
    var r = await fetch('/api/recall', {
      method: 'POST',
      headers: postHeaders(),
      body: JSON.stringify(body)
    }).then(function(res){return res.json();});
    var mems = r.matched_memories || [];
    var shouldInject = mems.some(function(m){ return m.should_inject; });
    var html = '<div style="margin-bottom:8px"><span data-i18n="recall.memoryCount">匹配数</span>: <b>'+r.total_matched+'</b> | <span data-i18n="recall.shouldInject">建议注入</span>: <b>'+(shouldInject?'YES':'NO')+'</b></div>';
    html += mems.map(function(m) {
      return '<div style="padding:10px;background:#f9f9fb;border-radius:8px;margin-bottom:8px;font-size:13px">'+
             '<div><span class="badge badge-blue">'+escapeHtml(m.type)+'</span> conf='+m.confidence+' scope='+escapeHtml(m.scope||'-')+'</div>'+
             '<div style="margin-top:6px;color:var(--text-secondary)">'+escapeHtml((m.summary||'-')+'...')+'</div></div>';
    }).join('');
    document.getElementById('recall-result').innerHTML = html;
  } catch(e) {
    document.getElementById('recall-result').innerHTML = '<div style="color:var(--text-secondary)">'+t('common.error')+': '+e.message+'</div>';
  }
}

function testInject() {
  document.getElementById('recall-inject-card').style.display = 'block';
  document.getElementById('inject-system-prompt').textContent = 'System Prompt: see Inject Context at :9840 /inject';
  document.getElementById('inject-user-prompt').textContent = 'User Prompt: see Inject Context at :9840 /inject';
}

async function loadZhiyiRecycleBin() {
  var el = document.getElementById('zhiyi-recycle-list');
  var countEl = document.getElementById('zhiyi-recycle-count');
  if (!el || !countEl) return;
  el.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  try {
    var data = zhiyiRecycleBin && zhiyiRecycleBin.items ? zhiyiRecycleBin : await fetch('/api/v1/zhiyi/experience-recycle-bin?limit=50').then(function(r){return r.json();}).catch(function(){return {items:[]};});
    var items = data.items || [];
    countEl.textContent = items.length + ' 条';
    if (!items.length) {
      el.innerHTML = '<div style="color:var(--text-secondary)">'+t('common.none')+'</div>';
      return;
    }
    el.innerHTML = items.map(function(o) {
      var expId = o.exp_id || '';
      var title = escapeHtml(o.title || o.summary || expId || '-');
      var reason = escapeHtml(o.reason || '-');
      var time = escapeHtml(o.created_at || '-');
      return '<div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--border)">'+
        '<div><div style="font-size:13px;font-weight:600">'+title+'</div><div style="font-size:12px;color:var(--text-secondary);margin-top:4px">'+reason+' · '+time+'</div></div>'+
        '<button class="btn btn-secondary" style="padding:4px 10px;font-size:11px;white-space:nowrap" data-restore-exp-id="'+escapeHtml(expId)+'">恢复</button>'+
        '</div>';
    }).join('');
  } catch (e) {
    el.innerHTML = '<div style="color:var(--text-secondary)">'+t('common.error')+'</div>';
  }
}
async function loadM3RecallStats() {
  var el = document.getElementById('m3-recall-stats');
  var badge = document.getElementById('m3-recall-badge');
  if (!el) return;
  el.innerHTML = '<div class="loading">loading...</div>';
  try {
    var r = await fetch('/api/m3/status/recent-recall').then(function(res){return res.json();}).catch(function(){return {};});
    badge.textContent = r.recall_working ? 'OK' : 'FAIL';
    badge.className = r.recall_working ? 'badge badge-green' : 'badge badge-red';
    el.innerHTML = '<div class="info-grid">'+
      '<div class="info-row"><span>total_matched</span>: <span>'+r.total_matched+'</span></div>'+
      '<div class="info-row"><span>returned</span>: <span>'+r.returned+'</span></div>'+
      '<div class="info-row"><span>matched_memories</span>: <span>'+r.matched_memories_count+'</span></div>'+
      '<div class="info-row"><span>_scope_enforced</span>: <span>'+r._scope_enforced+'</span></div>'+
      '</div>';
  } catch(e) {
    el.innerHTML = '<div style="color:var(--text-secondary);font-size:13px">Error: '+e.message+'</div>';
  }
}

async function loadHealth() {
  var el = document.getElementById('health-results');
  el.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  try {
    var results = await fetch('/api/health').then(function(r){return r.json();});
    var checks = [
      ['p0raw', t('health.p0raw')],
      ['p0watcher', t('health.p0watcher')],
      ['p2zhiyi', t('health.p2zhiyi')],
      ['p2sourceRef', t('health.p2sourceRef')],
      ['p3recall', t('health.p3recall')],
      ['p4provider', t('health.p4provider')]
    ];
    var html = '';
    for (var i = 0; i < checks.length; i++) {
      var key = checks[i][0];
      var name = checks[i][1];
      var r = results[key] || {};
      var badge = r.status === 'passed' ? 'badge-green' : 'badge-red';
      var label = r.status === 'passed' ? t('health.passed') : t('health.failed');
      html += '<div class="health-item"><span class="health-name">'+name+'</span>'+
              '<span class="badge '+badge+'">'+label+'</span>'+
              '<span class="health-detail">'+(r.detail||'-')+'</span></div>';
    }
    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = '<div>'+t('common.error')+': '+e.message+'</div>';
  }
}

function runHealthCheck() { loadHealth(); loadM3AuditRisks(); }
async function loadM3AuditRisks() {
  var el = document.getElementById('m3-audit-risks');
  var badge = document.getElementById('m3-audit-badge');
  if (!el) return;
  el.innerHTML = '<div class="loading">loading...</div>';
  try {
    var r = await fetch('/api/m3/status/audit-risks').then(function(res){return res.json();});
    badge.textContent = r.audit1_pass ? 'audit1_pass' : 'audit1_fail';
    badge.className = r.audit1_pass ? 'badge badge-green' : 'badge badge-red';
    if (r.total_risks === 0) {
      el.innerHTML = '<div style="color:var(--text-secondary);font-size:13px">No risks detected</div>';
    } else {
      var html = r.risks.map(function(risk) {
        var cls = risk.severity === 'CRITICAL' ? 'badge-red' : (risk.severity === 'HIGH' ? 'badge-orange' : 'badge-yellow');
        return '<div style="margin-bottom:8px">'+
          '<span class="badge '+cls+'">'+risk.severity+'</span> '+
          '<span style="font-size:13px">'+risk.type+'</span> '+
          '<span style="font-size:12px;color:var(--text-secondary)">'+(risk.mtype||risk.path||'')+'</span></div>';
      }).join('');
      el.innerHTML = html;
    }
  } catch(e) {
    el.innerHTML = '<div style="color:var(--text-secondary);font-size:13px">Error: '+e.message+'</div>';
  }
}

async function loadSourceSystems() {
  var listEl = document.getElementById('source-systems-list');
  var lfEl = document.getElementById('source-systems-local-files');
  var syncEl = document.getElementById('source-systems-continuous');
  var syncBadge = document.getElementById('source-systems-continuous-badge');
  if (syncEl) syncEl.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  if (syncBadge) {
    syncBadge.textContent = '-';
    syncBadge.className = 'badge badge-blue';
  }
  listEl.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  lfEl.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  try {
    var sourcePayloads = await Promise.all([
      fetch('/api/v1/source-systems').then(function(r){return r.json();}),
      fetch('/api/v1/source-systems/continuous-sync/status').then(function(r){return r.json();}).catch(function(){return null;})
    ]);
    var ss = sourcePayloads[0];
    var sync = sourcePayloads[1];
    renderContinuousSourceSync(sync);
    var all = ss.all || [];
    var active = ss.active || [];
    if (all.length === 0) {
      listEl.innerHTML = '<div class="none">'+t('common.none')+'</div>';
    } else {
      listEl.innerHTML = '<table style="width:100%;border-collapse:collapse">'+
        '<thead><tr style="text-align:left;background:var(--bg-secondary);font-size:12px">'+
        '<th style="padding:6px 8px">Source</th><th style="padding:6px 8px">Type</th>'+
        '<th style="padding:6px 8px">Status</th><th style="padding:6px 8px">Details</th></tr></thead><tbody>';
      for (var i = 0; i < all.length; i++) {
        var src = all[i];
        var isActive = active.some(function(a){ return a.source_system === src.source_system; });
        var badge = isActive ? '<span class="badge badge-green">active</span>' : '<span class="badge badge-blue">inactive</span>';
        var details = src.description || src.type || '-';
        listEl.innerHTML += '<tr style="border-bottom:1px solid var(--border)">'+
          '<td style="padding:8px;font-weight:500">'+src.source_system+'</td>'+
          '<td style="padding:8px;color:var(--text-secondary)">'+src.type+'</td>'+
          '<td style="padding:8px">'+badge+'</td>'+
          '<td style="padding:8px;font-size:12px;color:var(--text-secondary)">'+details+'</td></tr>';
      }
      listEl.innerHTML += '</tbody></table>';
    }
    // local_files detail
    var lfSt = await fetch('/api/v1/source-systems/local_files/status').then(function(r){return r.json();});
    var lfScan = await fetch('/api/v1/source-systems/local_files/scan').then(function(r){return r.json();});
    var lfCp = await fetch('/api/v1/source-systems/local_files/checkpoint').then(function(r){return r.json();});
    lfEl.innerHTML = '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">'+
      '<div class="stat"><div class="stat-value">'+(lfSt.total_input_files||0)+'</div><div class="stat-label">输入文件</div></div>'+
      '<div class="stat"><div class="stat-value">'+(lfScan.files||[]).length+'</div><div class="stat-label">已扫描</div></div>'+
      '<div class="stat"><div class="stat-value">'+(lfCp && Object.keys(lfCp).length||0)+'</div><div class="stat-label">已追踪</div></div>'+
      '</div>'+
      '<div style="margin-top:12px">'+
      '<button class="btn btn-secondary" style="margin-right:8px" onclick="sourceSystemsRescan()" data-i18n="ss.rescan">重新扫描</button>'+
      '<button class="btn btn-secondary" onclick="sourceSystemsIngest()" data-i18n="ss.ingest">摄入</button>'+
      '</div>'+
      '<div id="ss-ingest-result" style="margin-top:8px;font-size:13px"></div>';
  } catch(e) {
    listEl.innerHTML = '<div class="error">'+t('common.error')+': '+e.message+'</div>';
    lfEl.innerHTML = '<div class="error">'+e.message+'</div>';
    if (syncEl) syncEl.innerHTML = '<div class="error">'+e.message+'</div>';
  }
}

function publicSourceName(name) {
  var aliases = {
    openclaw: 'OpenClaw',
    codex: 'Codex',
    kiro: 'Kiro',
    claude_desktop: 'Claude Desktop'
  };
  return aliases[name] || String(name || '-').replace(/_/g, ' ');
}

function formatSyncCadence(item) {
  var ms = Number(item && (item.poll_interval_milliseconds || item.target_latency_milliseconds || 0));
  if (ms > 0 && ms < 1000) return ms + 'ms';
  if (ms >= 1000) return (ms / 1000) + 's';
  var seconds = Number(item && item.poll_interval_seconds || 0);
  if (seconds > 0 && seconds < 1) return Math.round(seconds * 1000) + 'ms';
  if (seconds >= 1) return seconds + 's';
  return '-';
}

function renderContinuousSourceSync(sync) {
  var el = document.getElementById('source-systems-continuous');
  var badge = document.getElementById('source-systems-continuous-badge');
  if (!el) return;
  if (!sync || !sync.ok) {
    el.innerHTML = '<div style="color:var(--text-secondary);font-size:13px">'+t('common.error')+'</div>';
    if (badge) {
      badge.textContent = t('dashboard.unknown');
      badge.className = 'badge badge-yellow';
    }
    return;
  }
  var watcher = sync.watcher || {};
  var summary = sync.summary || {};
  var sources = sync.sources || [];
  var pending = sync['collector' + '_pending'] || [];
  var keepsWatching = watcher['install_scan' + '_only'] === false;
  var watcherActive = watcher.active === true;
  var liveSources = sources.filter(function(item) { return item.continuous; });
  var activeLabel = watcherActive ? t('ss.watcherRunning') : t('ss.watcherStopped');
  var keepLabel = keepsWatching ? t('ss.installKeepsWatching') : t('ss.initialScanOnly');
  if (badge) {
    badge.textContent = activeLabel;
    badge.className = watcherActive ? 'badge badge-green' : 'badge badge-yellow';
  }
  var statsHtml = '<div class="card-grid" style="margin-top:12px">'+
    '<div class="stat"><div class="stat-value">'+liveSources.length+'</div><div class="stat-label">'+t('ss.trackedSources')+'</div></div>'+
    '<div class="stat"><div class="stat-value">'+(summary.millisecond_level_source_count || 0)+'</div><div class="stat-label">ms</div></div>'+
    '<div class="stat"><div class="stat-value">'+pending.length+'</div><div class="stat-label">'+t('ss.pendingSources')+'</div></div>'+
    '<div class="stat"><div class="stat-value" style="font-size:14px">'+escapeHtml(keepLabel)+'</div><div class="stat-label">'+t('ss.liveSync')+'</div></div>'+
    '</div>';
  var rows = sources.map(function(item) {
    var cls = item.continuous ? 'badge-green' : (item.enabled_in_p0_watcher ? 'badge-yellow' : 'badge-blue');
    var label = item.continuous ? t('ss.liveTracked') : t('ss.visibleOnly');
    var cadence = formatSyncCadence(item);
    return '<tr style="border-bottom:1px solid var(--border)">'+
      '<td style="padding:8px;font-weight:500">'+escapeHtml(publicSourceName(item.source_system))+'</td>'+
      '<td style="padding:8px"><span class="badge '+cls+'">'+escapeHtml(label)+'</span></td>'+
      '<td style="padding:8px;color:var(--text-secondary)">'+escapeHtml(cadence)+'</td></tr>';
  }).join('');
  var pendingHtml = '';
  if (pending.length) {
    var pendingNames = pending.slice(0, 6).map(function(item) {
      return escapeHtml(item.display_name || publicSourceName(item.source_system));
    }).join(', ');
    pendingHtml = '<div style="margin-top:12px;font-size:13px;color:var(--text-secondary)">'+
      '<span class="badge badge-yellow">'+pending.length+'</span> '+t('ss.visibleOnly')+
      (pendingNames ? ': '+pendingNames : '')+'</div>';
  } else {
    pendingHtml = '<div style="margin-top:12px;font-size:13px;color:var(--text-secondary)">'+t('ss.noPendingSources')+'</div>';
  }
  el.innerHTML = '<div style="font-size:13px;color:var(--text-secondary)">'+escapeHtml(activeLabel)+' · '+escapeHtml(keepLabel)+'</div>'+
    statsHtml+
    '<div class="table-wrap" style="margin-top:14px"><table style="width:100%;border-collapse:collapse">'+
    '<thead><tr style="text-align:left;background:var(--bg-secondary);font-size:12px">'+
    '<th style="padding:6px 8px">Source</th><th style="padding:6px 8px">Status</th><th style="padding:6px 8px">Cadence</th></tr></thead><tbody>'+
    rows+'</tbody></table></div>'+pendingHtml;
}

function sourceSystemsRescan() {
  var el = document.getElementById('ss-ingest-result');
  el.innerHTML = '<span style="color:var(--text-secondary)">Scanning...</span>';
  fetch('/api/v1/source-systems/local_files/scan').then(function(r){return r.json();}).then(function(d){
    el.innerHTML = '<span class="badge badge-green">Found '+(d.files||[]).length+' files</span>';
    loadSourceSystems();
  }).catch(function(e){ el.innerHTML = '<span class="badge badge-red">Error: '+e.message+'</span>'; });
}

function sourceSystemsIngest() {
  var el = document.getElementById('ss-ingest-result');
  el.innerHTML = '<span style="color:var(--text-secondary)">Ingesting...</span>';
  fetch('/api/v1/source-systems/local_files/ingest', {method:'POST', headers:postHeaders(), body:JSON.stringify({dry_run:false})}).then(function(r){return r.json();}).then(function(d){
    var msg = 'Ingested='+d.total_ingested+' Skipped='+d.total_skipped;
    el.innerHTML = '<span class="badge badge-green">'+msg+'</span>';
    loadSourceSystems();
  }).catch(function(e){ el.innerHTML = '<span class="badge badge-red">Error: '+e.message+'</span>'; });
}

async function loadUpdateStatus() {
  var el = document.getElementById('update-status');
  el.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  try {
    var st = await fetch('/api/v1/update/status').then(function(r){return r.json();});
    var source = await fetch('/api/v1/update/source').then(function(r){return r.json();});
    var pkg = st.local_package || {};
    var upToDate = st.up_to_date;
    var badge = upToDate ? 'badge-green' : 'badge-yellow';
    var label = upToDate ? t('update.upToDate') : t('update.updateAvailable');
    // REL6: dry-run banner
    var dryRunBanner = st.dry_run
      ? '<div style="background:#1a3a5c;color:#7dd3fc;padding:8px 12px;border-radius:6px;margin-bottom:12px;font-size:13px;"><b>&#128737; DRY-RUN MODE</b> — This update center is for preview only. No real download, install, or apply is permitted.</div>'
      : '';
    // REL6: safety flags
    var safetyRows = '';
    if (st.download_enabled !== undefined) {
      var deIcon = st.download_enabled ? '&#10060;' : '&#9989;';
      var deColor = st.download_enabled ? 'color:#ef4444' : 'color:#22c55e';
      var ieIcon = st.install_enabled ? '&#10060;' : '&#9989;';
      var ieColor = st.install_enabled ? 'color:#ef4444' : 'color:#22c55e';
      var aaIcon = st.auto_apply ? '&#10060;' : '&#9989;';
      var aaColor = st.auto_apply ? 'color:#ef4444' : 'color:#22c55e';
      safetyRows = '<tr><td style="color:var(--text-secondary);padding:4px 8px;">Download</td><td style="padding:4px 8px;font-size:12px;' + deColor + ';">' + deIcon + ' ' + (st.download_enabled ? 'ENABLED' : 'DISABLED') + '</td></tr>' +
                   '<tr><td style="color:var(--text-secondary);padding:4px 8px;">Install</td><td style="padding:4px 8px;font-size:12px;' + ieColor + ';">' + ieIcon + ' ' + (st.install_enabled ? 'ENABLED' : 'DISABLED') + '</td></tr>' +
                   '<tr><td style="color:var(--text-secondary);padding:4px 8px;">Auto-Apply</td><td style="padding:4px 8px;font-size:12px;' + aaColor + ';">' + aaIcon + ' ' + (st.auto_apply ? 'ENABLED' : 'DISABLED') + '</td></tr>' +
                   '<tr><td style="color:var(--text-secondary);padding:4px 8px;">Release Asset</td><td style="padding:4px 8px;font-size:12px;color:var(--text-secondary);">' + (st.release_asset_available ? '&#10060; Available' : '&#9989; Not published') + '</td></tr>' +
                   '<tr><td style="color:var(--text-secondary);padding:4px 8px;">GitHub Release</td><td style="padding:4px 8px;font-size:12px;color:var(--text-secondary);">' + (st.github_release_created ? '&#10060; Created' : '&#9989; Not created') + '</td></tr>';
    }
    // REL6: update available badge
    var uaBadge = st.update_available ? 'badge-yellow' : 'badge-green';
    var uaLabel = st.update_available ? t('update.updateAvailable') : 'Up to date';
    el.innerHTML = dryRunBanner + '<table style="width:100%;border-collapse:collapse;">' +
      '<tr><td style="color:var(--text-secondary);padding:4px 8px;">Current Version</td><td style="padding:4px 8px;font-weight:bold;">'+escHtml(st.current_version)+'</td></tr>' +
      '<tr><td style="color:var(--text-secondary);padding:4px 8px;">Remote Latest</td><td style="padding:4px 8px;">'+escHtml(st.latest_version||'-')+'</td></tr>' +
      '<tr><td style="color:var(--text-secondary);padding:4px 8px;">Update Available</td><td style="padding:4px 8px;"><span class="badge '+uaBadge+'">'+uaLabel+'</span></td></tr>' +
      '<tr><td style="color:var(--text-secondary);padding:4px 8px;">'+t('update.localPkg')+'</td><td style="padding:4px 8px;">'+(pkg.exists ? escHtml(pkg.size+' bytes / '+pkg.checksum.substring(0,12)+'...') : t('update.noPkg'))+'</td></tr>' +
      '<tr><td style="color:var(--text-secondary);padding:4px 8px;">'+t('update.sourceType')+'</td><td style="padding:4px 8px;">'+(source.type||'local')+'</td></tr>' +
      '<tr><td style="color:var(--text-secondary);padding:4px 8px;">'+t('update.sourceUrl')+'</td><td style="padding:4px 8px;font-size:12px;color:var(--text-secondary);">'+(source.source_url||'-')+'</td></tr>' +
      safetyRows + '</table>';
    document.getElementById('update-source-url').value = source.source_url || '';
    document.getElementById('update-source-type').value = source.type || 'local';
    document.getElementById('update-pkg-path').value = MEMCORE_ROOT+'/release/memcore-cloud-'+st.current_version+'-linux-x86_64.tar.gz';
    // REL6: Disable apply button and show warning when dry_run=true
    var applyBtn = document.getElementById('btn-update-apply');
    var applyWarn = document.getElementById('update-apply-warning');
    if (st.dry_run && applyBtn) {
      applyBtn.disabled = true;
      applyBtn.style.opacity = '0.5';
      applyBtn.style.cursor = 'not-allowed';
      if (applyWarn) applyWarn.textContent = '⛔ Apply disabled — dry-run mode (no real install) | Real apply requires system upgrade with root and甲方授权';
    } else if (applyWarn) {
      applyWarn.textContent = '';
    }
  } catch(e) {
    el.innerHTML = '<div>'+t('common.error')+': '+e.message+'</div>';
  }
}

function escHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function updateSaveSource() {
  var url = document.getElementById('update-source-url').value;
  var type = document.getElementById('update-source-type').value;
  var el = document.getElementById('update-source-msg') || (function(){
    var btn = document.querySelector('#page-update .card:nth-child(2) .btn-primary');
    if (btn) { var div = document.createElement('div'); div.id = 'update-source-msg'; div.style.marginTop='8px'; btn.parentNode.insertBefore(div, btn.nextSibling); }
    return document.getElementById('update-source-msg');
  })();
  try {
    var r = await fetch('/api/v1/update/source', {
      method: 'POST',
      headers: postHeaders(),
      body: JSON.stringify({source_url: url, type: type})
    }).then(function(res){return res.json();});
    if (el) el.innerHTML = '<span class="badge badge-green">OK</span> <span style="color:var(--text-secondary);font-size:12px;">'+escHtml(type)+' / '+escHtml(url||'-')+'</span>';
  } catch(e) { if (el) el.innerHTML = '<span class="badge badge-red">'+t('common.error')+'</span>: '+e.message; }
}

async function updateVerifyPkg() {
  var el = document.getElementById('update-verify-result');
  el.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  var pkg = document.getElementById('update-pkg-path').value;
  try {
    var r = await fetch('/api/v1/update/verify', {
      method: 'POST',
      headers: postHeaders(),
      body: JSON.stringify({package_path: pkg})
    }).then(function(res){return res.json();});
    if (r.valid_tarball) {
      el.innerHTML = '<div class="badge badge-green">OK</div> <span style="color:var(--text-secondary);">'+r.entries+' entries, '+r.size+' bytes, SHA256: '+r.checksum.substring(0,16)+'...</span>';
    } else {
      el.innerHTML = '<div class="badge badge-red">Invalid</div>: '+escHtml(r.tar_error||'');
    }
  } catch(e) { el.innerHTML = '<div class="badge badge-red">'+t('common.error')+'</div>: '+e.message; }
}

async function updateGeneratePlan() {
  var el = document.getElementById('update-plan-result');
  el.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  try {
    var r = await fetch('/api/v1/update/plan', {
      method: 'POST',
      headers: postHeaders(),
      body: JSON.stringify({})
    }).then(function(res){return res.json();});
    var html = '<table style="width:100%;border-collapse:collapse;margin-top:8px;">';
    html += '<tr><th style="text-align:left;padding:4px 8px;">#</th><th style="text-align:left;padding:4px 8px;">'+t('update.action')+'</th><th style="text-align:left;padding:4px 8px;">'+t('update.target')+'</th></tr>';
    for (var i = 0; i < r.steps.length; i++) {
      var s = r.steps[i];
      html += '<tr><td style="padding:4px 8px;">'+(i+1)+'</td><td style="padding:4px 8px;">'+escHtml(s.action)+'</td><td style="padding:4px 8px;color:var(--text-secondary);">'+escHtml(s.target||'')+'</td></tr>';
    }
    html += '</table>';
    html += '<p style="margin-top:8px;color:var(--text-secondary);">'+t('update.rollbackPlan')+': ';
    for (var j = 0; j < r.rollback_plan.length; j++) {
      html += (j>0?', ':'') + r.rollback_plan[j].action;
    }
    html += '</p>';
    el.innerHTML = html;
  } catch(e) { el.innerHTML = '<div class="badge badge-red">'+t('common.error')+'</div>: '+e.message; }
}

async function updateDryRun() {
  var el = document.getElementById('update-dryrun-result');
  el.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  try {
    var r = await fetch('/api/v1/update/apply-dry-run', {
      method: 'POST',
      headers: postHeaders(),
      body: JSON.stringify({})
    }).then(function(res){return res.json();});
    if (r.ok) {
      var html = '<div class="badge badge-green">Dry Run OK</div><ul style="margin-top:8px;padding-left:20px;">';
      for (var i = 0; i < r.steps.length; i++) {
        var s = r.steps[i];
        var badge = s.status === 'pass' ? 'badge-green' : 'badge-yellow';
        html += '<li><span class="badge '+badge+'">'+s.status+'</span> '+escHtml(s.action||s.reason||'')+' — '+escHtml(s.target||'')+'</li>';
      }
      html += '</ul>';
      el.innerHTML = html;
    } else {
      el.innerHTML = '<div class="badge badge-red">Failed</div>: '+escHtml(r.error||'');
    }
  } catch(e) { el.innerHTML = '<div class="badge badge-red">'+t('common.error')+'</div>: '+e.message; }
}

async function updateApply() {
  var el = document.getElementById('update-dryrun-result');
  el.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  var pkg = document.getElementById('update-pkg-path').value;
  try {
    var r = await fetch('/api/v1/update/apply', {
      method: 'POST',
      headers: postHeaders(),
      body: JSON.stringify({package_path: pkg})
    }).then(function(res){return res.json();});
    if (r.ok) {
      var html = '<div class="badge badge-green">OK: '+escHtml(r.version||'')+'</div>';
      html += '<ul style="margin-top:8px;padding-left:20px;">';
      for (var i = 0; i < r.steps.length; i++) {
        var s = r.steps[i];
        var badge = s.status === 'pass' ? 'badge-green' : 'badge-yellow';
        html += '<li><span class="badge '+badge+'">'+escHtml(s.status||'')+'</span> '+escHtml(s.action||'')+'</li>';
      }
      if (r.note) html += '<li style="margin-top:4px;color:var(--text-secondary);font-size:12px;">'+escHtml(r.note)+'</li>';
      html += '</ul>';
      el.innerHTML = html;
      loadUpdateHistory();
    } else {
      el.innerHTML = '<div class="badge badge-red">Failed</div>: '+escHtml(r.error||'');
    }
  } catch(e) { el.innerHTML = '<div class="badge badge-red">'+t('common.error')+'</div>: '+e.message; }
}



async function loadUpdateHistory() {
  var el = document.getElementById('update-history');
  el.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  try {
    var r = await fetch('/api/v1/update/history').then(function(res){return res.json();});
    if (!r.entries || r.entries.length === 0) {
      el.innerHTML = '<span style="color:var(--text-secondary)">'+t('update.noHistory')+'</span>';
      return;
    }
    var html = '<table style="width:100%;border-collapse:collapse;font-size:12px;">';
    html += '<tr style="border-bottom:1px solid var(--border);">';
    html += '<th style="text-align:left;padding:4px 8px;color:var(--text-secondary)">'+t('update.time')+'</th>';
    html += '<th style="text-align:left;padding:4px 8px;color:var(--text-secondary)">'+t('update.version')+'</th>';
    html += '<th style="text-align:left;padding:4px 8px;color:var(--text-secondary)">'+t('update.size')+'</th>';
    html += '<th style="text-align:left;padding:4px 8px;color:var(--text-secondary)">'+t('update.status')+'</th></tr>';
    for (var i = 0; i < r.entries.length; i++) {
      var e = r.entries[i];
      var stepCount = e.steps ? e.steps.length : 0;
      var okCount = e.steps ? e.steps.filter(function(s){return s.status==='pass';}).length : 0;
      var badge = e.dry_run ? 'badge-yellow' : (okCount === stepCount && stepCount > 0 ? 'badge-green' : 'badge-red');
      var date = e.applied_at ? e.applied_at.replace('T',' ').substring(0,19) : '-';
      html += '<tr style="border-bottom:1px solid var(--border);">';
      html += '<td style="padding:4px 8px;color:var(--text-secondary);">'+escHtml(date)+'</td>';
      html += '<td style="padding:4px 8px;font-weight:bold;">'+escHtml(e.version||'-')+'</td>';
      html += '<td style="padding:4px 8px;">'+(e.size ? Math.round(e.size/1024)+'KB' : '-')+'</td>';
      html += '<td style="padding:4px 8px;"><span class="badge '+badge+'">'+(e.dry_run ? 'dry' : (okCount+'/'+stepCount))+'</span></td></tr>';
    }
    html += '</table>';
    html += '<p style="margin-top:8px;font-size:11px;color:var(--text-secondary);">'+t('update.total')+': '+r.total+'</p>';
    el.innerHTML = html;
  } catch(e) { el.innerHTML = '<div class="badge badge-red">'+t('common.error')+'</div>: '+e.message; }
}



var currentLang = localStorage.getItem('console_lang') || 'zh-CN';
setLanguage(currentLang);
resetConsoleScroll();
loadDashboard();

// Runtime profile
function loadRuntimePage() {
  loadRuntimeMemcore();
  loadRuntimeOpenClaw();
  loadRuntimeHermes();
  loadM3Runtime();
}
async function loadM3Runtime() {
  try {
    var m3Oc = await fetch('/api/m3/status/openclaw-runtime').then(function(r){return r.json();}).catch(function(){return {};});
    var m3J = await fetch('/api/m3/status/j2-j7').then(function(r){return r.json();}).catch(function(){return {};});
    document.getElementById('m3-gw-status').textContent = m3Oc.gateway_reachable ? 'reachable' : 'unreachable';
    document.getElementById('m3-device-paired').textContent = m3Oc.device_paired ? 'yes' : 'no';
    var j2ok = m3J.j2_dedup_applied;
    document.getElementById('m3-j2-dedup').textContent = j2ok ? 'active' : 'inactive';
    var j3f = m3J.j3_superseded_filtered_count || 0;
    document.getElementById('m3-j3-filtered').textContent = String(j3f);
    document.getElementById('m3-lifecycle-entries').textContent = m3J.lifecycle_overlay_entries || 0;
    var sd = m3J.status_distribution || {};
    var distStr = Object.keys(sd).map(function(k){return k+'='+sd[k];}).join(', ');
    document.getElementById('m3-status-dist').textContent = distStr || '-';
    document.getElementById('m3-j2-j7-badge').textContent = j2ok ? 'J2-J7 OK' : 'J2-J7 off';
  } catch(e) {
    document.getElementById('m3-j2-j7-badge').textContent = 'error';
  }
}
async function loadRuntimeMemcore() {
  var el = document.getElementById('runtime-memcore-version');
  if (!el) return;
  try {
    var r = await fetch('/api/v1/runtime/profile/memcore-cloud').then(function(res){return res.json();});
    el.textContent = r.version || '-';
    var sel = r.selected_runtime;
    document.getElementById('runtime-memcore-selected').textContent = sel ? sel.source : '-';
    document.getElementById('runtime-memcore-instances').textContent = r.instances ? r.instances.length : '-';
    document.getElementById('runtime-memcore-stale').textContent = r.stale_instances ? r.stale_instances.length : '-';
    document.getElementById('runtime-memcore-mismatch').textContent = r.version_mismatches ? r.version_mismatches.length : '-';
  } catch(e) { el.textContent = 'error'; }
}
async function loadRuntimeOpenClaw() {
  var el = document.getElementById('runtime-oc-version');
  if (!el) return;
  try {
    var r = await fetch('/api/v1/runtime/profile/openclaw').then(function(res){return res.json();});
    el.textContent = r.version ? r.version.substring(0,15) : '-';
    var sel = r.selected_runtime;
    document.getElementById('runtime-oc-selected').textContent = sel ? sel.source : '-';
    document.getElementById('runtime-oc-instances').textContent = r.instances ? r.instances.length : '-';
    document.getElementById('runtime-oc-stale').textContent = r.stale_instances ? r.stale_instances.length : '-';
    document.getElementById('runtime-oc-mismatch').textContent = r.version_mismatches ? r.version_mismatches.length : '-';
  } catch(e) { el.textContent = 'error'; }
}
async function loadRuntimeHermes() {
  var el = document.getElementById('runtime-hermes-version');
  if (!el) return;
  try {
    var r = await fetch('/api/v1/runtime/profile/hermes').then(function(res){return res.json();});
    var v = r.version || '-';
    el.textContent = v.substring ? v.substring(0,12) : v;
    document.getElementById('runtime-hermes-instances').textContent = r.instances ? r.instances.length : '-';
    document.getElementById('runtime-hermes-running').textContent = r.running_instance ? 'PID '+r.running_instance.pid : '-';
    document.getElementById('runtime-hermes-config').textContent = r.config ? 'found' : '-';
    document.getElementById('runtime-hermes-root').textContent = r.install_root || '-';
  } catch(e) { el.textContent = 'error'; }
}

// ─── M4 Mobile Pages ──────────────────────────────────────
var m4TaskData = null;
var m4CurrentFilter = 'all';

function showPage(name) {
  document.querySelectorAll('.page').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.nav-item').forEach(function(n) { n.classList.remove('active'); });
  var pageEl = document.getElementById('page-' + name);
  var mainContainer = document.querySelector('.main');
  if (!pageEl) return;
  pageEl.classList.add('active');
  if (mainContainer) {
    mainContainer.insertBefore(pageEl, mainContainer.firstChild);
  }
  var navItems = document.querySelectorAll('.nav-item');
  for (var i = 0; i < navItems.length; i++) {
    if (navItems[i].getAttribute('data-page') === name) { navItems[i].classList.add('active'); }
  }
  resetConsoleScroll();
  if (name === 'dashboard') loadDashboard();
  if (name === 'memory') { loadMemory(); loadM3LifecycleOverlay(); }
  if (name === 'registry') loadRegistry();
  if (name === 'zhiyi') { loadZhiyi(); loadZhiyiRecycleBin(); applyZhiyiFilter(); }
  if (name === 'health') { loadHealth(); loadM3AuditRisks(); }
  if (name === 'source-systems') loadSourceSystems();
  if (name === 'update') { loadUpdateStatus(); loadUpdateHistory(); }
  if (name === 'runtime') loadRuntimePage();
  if (name === 'recall') loadM3RecallStats();
  if (name === 'mobile-overview') loadMobileOverview();
  if (name === 'task-results') loadTaskResults();
  if (name === 'risk-backlog') loadRiskBacklog();
  if (name === 'copy-center') loadCopyCenter();
}

async function loadMobileOverview() {
  // M4-1: task results overview
  var statsEl = document.getElementById('m4-overview-stats');
  var recentEl = document.getElementById('m4-recent-tasks');
  var riskEl = document.getElementById('m4-risk-summary');
  var decisionEl = document.getElementById('m4-next-decision');
  var countBadge = document.getElementById('m4-task-count');
  try {
    var r = await fetch('/api/v1/tasks/results').then(function(res){return res.json();});
    countBadge.textContent = r.total + ' 任务';
    statsEl.innerHTML = '<div class="stat"><div class="stat-value">'+r.passed+'</div><div class="stat-label">通过</div></div>'+
      '<div class="stat"><div class="stat-value" style="color:var(--red)">'+r.failed+'</div><div class="stat-label">失败</div></div>'+
      '<div class="stat"><div class="stat-value">'+r.limited+'</div><div class="stat-label">有限</div></div>'+
      '<div class="stat"><div class="stat-value" style="color:var(--text-secondary)">'+r.total+'</div><div class="stat-label">总计</div></div>';
    // Recent PASS tasks
    var recentTasks = (r.tasks || []).filter(function(t){return t.status === 'pass';}).slice(0, 5);
    if (recentTasks.length === 0) {
      recentEl.innerHTML = '<div style="color:var(--text-secondary);font-size:13px">暂无通过任务</div>';
    } else {
      recentEl.innerHTML = recentTasks.map(function(t) {
        return '<div style="padding:10px 0;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">'+
          '<span style="font-size:13px">'+t.task_id+'</span><span class="badge badge-green">PASS</span></div>';
      }).join('');
    }
    // Risk summary from risk backlog
    var rb = await fetch('/api/v1/tasks/risk-backlog').then(function(res){return res.json();});
    var riskCountBadge = document.getElementById('m4-risk-count');
    riskCountBadge.textContent = rb.total + ' 项';
    if (rb.total === 0) {
      riskEl.innerHTML = '<div style="color:var(--text-secondary);font-size:13px">无已知风险</div>';
    } else {
      riskEl.innerHTML = rb.risks.map(function(risk) {
        var cls = risk.severity === 'CRITICAL' ? 'badge-red' : (risk.severity === 'HIGH' ? 'badge-orange' : 'badge-yellow');
        return '<div style="padding:8px 0;border-bottom:1px solid var(--border)">'+
          '<span class="badge '+cls+'">'+risk.severity+'</span> '+
          '<span style="font-size:13px">'+risk.id+'</span></div>';
      }).join('');
    }
    // Next decision
    var nd = await fetch('/api/v1/tasks/next-decision-summary').then(function(res){return res.json();});
    var opts = (nd.pending_decisions || [])[0] || {};
    var options = opts.options || [];
    decisionEl.innerHTML = '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:10px">'+opts.basis || ''+'</div>'+
      options.map(function(o) {
        return '<div style="padding:8px 0;border-bottom:1px solid var(--border)">'+
          '<span class="badge badge-purple">'+o.id+'</span> '+
          '<span style="font-size:13px;font-weight:500">'+o.label+'</span><br>'+
          '<span style="font-size:12px;color:var(--text-secondary)">'+o.description+'</span></div>';
      }).join('');
  } catch(e) {
    statsEl.innerHTML = '<div style="color:var(--text-secondary)">Error: '+e.message+'</div>';
  }
}

async function loadTaskResults() {
  var listEl = document.getElementById('m4-task-list');
  var totalBadge = document.getElementById('m4-total-tasks');
  listEl.innerHTML = '<div class="loading">loading...</div>';
  try {
    m4TaskData = await fetch('/api/v1/tasks/results').then(function(res){return res.json();});
    totalBadge.textContent = m4TaskData.total + ' 任务';
    m4RenderTaskList(m4CurrentFilter);
  } catch(e) {
    listEl.innerHTML = '<div style="color:var(--text-secondary)">Error: '+e.message+'</div>';
  }
}

function m4FilterTasks(filter) {
  m4CurrentFilter = filter;
  document.querySelectorAll('#m4-task-filters .btn').forEach(function(b){ b.classList.remove('btn-primary'); b.classList.add('btn-secondary'); });
  document.getElementById('m4-filter-' + filter).classList.remove('btn-secondary');
  document.getElementById('m4-filter-' + filter).classList.add('btn-primary');
  m4RenderTaskList(filter);
}

function m4RenderTaskList(filter) {
  var listEl = document.getElementById('m4-task-list');
  if (!m4TaskData) return;
  var tasks = m4TaskData.tasks || [];
  if (filter !== 'all') {
    tasks = tasks.filter(function(t){ return t.status === filter; });
  }
  if (tasks.length === 0) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);font-size:13px;padding:16px 0">无任务</div>';
    return;
  }
  listEl.innerHTML = tasks.map(function(t) {
    var cls = t.status === 'pass' ? 'badge-green' : (t.status === 'fail' ? 'badge-red' : (t.status === 'limited' ? 'badge-yellow' : 'badge-gray'));
    return '<div style="padding:10px 0;border-bottom:1px solid var(--border);cursor:pointer" onclick="m4ShowTaskDetail(\\''+encodeURIComponent(t.task_id)+'\\')">'+
      '<div style="display:flex;justify-content:space-between;align-items:center">'+
      '<span style="font-size:13px;font-weight:500">'+t.task_id+'</span>'+
      '<span class="badge '+cls+'">'+(t.result || t.status).toUpperCase()+'</span></div></div>';
  }).join('');
}

function m4ShowTaskDetail(encodedId) {
  var taskId = decodeURIComponent(encodedId);
  var detailCard = document.getElementById('m4-task-detail-card');
  var titleEl = document.getElementById('m4-task-detail-title');
  var contentEl = document.getElementById('m4-task-detail-content');
  detailCard.style.display = 'block';
  titleEl.textContent = taskId;
  contentEl.innerHTML = '<div class="loading">loading...</div>';
  fetch('/api/v1/tasks/results/' + encodeURIComponent(taskId))
    .then(function(res){return res.json();})
    .then(function(d) {
      if (d.error) {
        contentEl.innerHTML = '<div style="color:var(--text-secondary)">'+d.error+'</div>';
        return;
      }
      var lines = [];
      lines.push('<div class="info-grid">');
      lines.push('<div class="info-row"><span>结果</span>: <span class="badge '+(d.result==='PASS'?'badge-green':'badge-red')+'">'+d.result+'</span></div>');
      if (d.timestamp) lines.push('<div class="info-row"><span>时间</span>: <span>'+d.timestamp+'</span></div>');
      if (d.scope_check) {
        for (var k in d.scope_check) {
          var icon = d.scope_check[k] ? '&#10004;' : '&#10008;';
          lines.push('<div class="info-row"><span>'+k+'</span>: <span>'+icon+' '+String(d.scope_check[k])+'</span></div>');
        }
      }
      lines.push('</div>');
      if (d.code_files && d.code_files.length > 0) {
        lines.push('<div style="margin-top:12px"><b style="font-size:13px">修改文件:</b>');
        d.code_files.forEach(function(f){ lines.push('<div style="font-size:12px;padding:2px 0;color:var(--text-secondary)">'+f+'</div>'); });
        lines.push('</div>');
      }
      if (d.test_files && d.test_files.length > 0) {
        lines.push('<div style="margin-top:12px"><b style="font-size:13px">测试文件:</b>');
        d.test_files.forEach(function(f){ lines.push('<div style="font-size:12px;padding:2px 0;color:var(--text-secondary)">'+f+'</div>'); });
        lines.push('</div>');
      }
      contentEl.innerHTML = lines.join('');
    })
    .catch(function(e){ contentEl.innerHTML = '<div style="color:var(--text-secondary)">Error: '+e.message+'</div>'; });
}

function m4CloseTaskDetail() {
  document.getElementById('m4-task-detail-card').style.display = 'none';
}

async function loadRiskBacklog() {
  var listEl = document.getElementById('m4-risk-list');
  var totalBadge = document.getElementById('m4-risk-total');
  listEl.innerHTML = '<div class="loading">loading...</div>';
  try {
    var r = await fetch('/api/v1/tasks/risk-backlog').then(function(res){return res.json();});
    totalBadge.textContent = r.total + ' 项';
    if (r.total === 0) {
      listEl.innerHTML = '<div style="color:var(--text-secondary);font-size:13px">无已知风险</div>';
      return;
    }
    listEl.innerHTML = r.risks.map(function(risk) {
      var cls = risk.severity === 'CRITICAL' ? 'badge-red' : (risk.severity === 'HIGH' ? 'badge-orange' : 'badge-yellow');
      return '<div style="padding:12px 0;border-bottom:1px solid var(--border)">'+
        '<div style="margin-bottom:6px"><span class="badge '+cls+'">'+risk.severity+'</span> '+
        '<span style="font-weight:500;font-size:13px">'+risk.id+'</span></div>'+
        '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">'+risk.description+'</div>'+
        '<div style="font-size:11px;color:var(--text-secondary)">任务: '+risk.task+' | 属性: '+risk.property+'</div></div>';
    }).join('');
  } catch(e) {
    listEl.innerHTML = '<div style="color:var(--text-secondary)">Error: '+e.message+'</div>';
  }
}

async function loadCopyCenter() {
  var taskListEl = document.getElementById('m4-copy-task-list');
  var decisionEl = document.getElementById('m4-copy-next-decision');
  taskListEl.innerHTML = '<div class="loading">loading...</div>';
  decisionEl.innerHTML = '<div class="loading">loading...</div>';
  try {
    var r = await fetch('/api/v1/tasks/results').then(function(res){return res.json();});
    var passTasks = (r.tasks || []).filter(function(t){return t.status === 'pass';});
    if (passTasks.length === 0) {
      taskListEl.innerHTML = '<div style="color:var(--text-secondary);font-size:13px">无通过任务可复制</div>';
    } else {
      taskListEl.innerHTML = passTasks.map(function(t) {
        return '<div style="padding:10px 0;border-bottom:1px solid var(--border)">'+
          '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'+
          '<span style="font-size:13px;font-weight:500">'+t.task_id+'</span>'+
          '<button class="btn btn-sm btn-primary" onclick="m4CopyTaskSummary(\\''+encodeURIComponent(t.task_id)+'\\')">&#9098; 复制</button></div></div>';
      }).join('');
    }
    // Next decision copy
    var nd = await fetch('/api/v1/tasks/next-decision-summary').then(function(res){return res.json();});
    var opts = (nd.pending_decisions || [])[0] || {};
    var options = opts.options || [];
    decisionEl.innerHTML = '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:10px">'+opts.basis||''+'</div>'+
      options.map(function(o) {
        return '<div style="padding:8px 0;border-bottom:1px solid var(--border)">'+
          '<span class="badge badge-purple">'+o.id+'</span> '+
          '<span style="font-size:13px;font-weight:500">'+o.label+'</span><br>'+
          '<span style="font-size:12px;color:var(--text-secondary)">'+o.description+'</span><br>'+
          '<button class="btn btn-sm" style="margin-top:4px" onclick="m4CopyOption(\\''+o.id+'\\',\\''+o.label+'\\',\\''+o.description+'\\')">&#9098; 复制</button></div>';
      }).join('');
  } catch(e) {
    taskListEl.innerHTML = '<div style="color:var(--text-secondary)">Error: '+e.message+'</div>';
  }
}

function m4CopyTaskSummary(taskId) {
  fetch('/api/v1/tasks/results/' + encodeURIComponent(taskId) + '/summary')
    .then(function(res){return res.json();})
    .then(function(d) {
      if (d.error) { alert('Error: '+d.error); return; }
      m4CopyText(d.summary_text, taskId + ' 摘要已复制');
    })
    .catch(function(e){ alert('Error: '+e.message); });
}

function m4CopyOption(id, label, desc) {
  var text = '## 下一步决策\\n\\n**选项 ' + id + ': ' + label + '**\\n' + desc + '\\n\\n[复制时间: ' + new Date().toISOString() + ']';
  m4CopyText(text, '选项 ' + id + ' 已复制');
}

function m4CopyText(text, successMsg) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function() {
      m4ShowToast(successMsg || '已复制');
    }).catch(function() { m4FallbackCopy(text); });
  } else {
    m4FallbackCopy(text);
  }
}

function m4FallbackCopy(text) {
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  m4ShowToast('已复制 (fallback)');
}

function m4ShowToast(msg) {
  var existing = document.getElementById('m4-toast');
  if (existing) existing.remove();
  var toast = document.createElement('div');
  toast.id = 'm4-toast';
  toast.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1d1d1f;color:#fff;padding:10px 20px;border-radius:8px;font-size:13px;z-index:9999';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(function(){ toast.remove(); }, 2500);
}
</script>
</body>
</html>"""

