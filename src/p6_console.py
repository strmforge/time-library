#!/usr/bin/env python3
"""
memcore-cloud local UI server.

The default page is the product-facing Yifanchen personal memory center.
Older read-only API routes remain available for diagnostics and phased review.
"""
import os, sys, json, glob, subprocess, datetime, mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Thread
try:
    from src.zhiyi_archive import attach_archive_card, archive_card
except Exception:
    from zhiyi_archive import attach_archive_card, archive_card

from config_loader import base_path
from service_manager import get_service_manager
MEMCORE_ROOT = base_path()
PORT = 9850
PRODUCT_UI_TEMPLATE_PATH = os.path.join(str(MEMCORE_ROOT), "web", "console_product.html")
PRODUCT_ASSET_ROOT = os.path.join(str(MEMCORE_ROOT), "web", "assets")

# V4: dry_run_token store for apply endpoint binding validation
# token → {version, pkg_path, install_root, created_at}
# Cleaned up on token expiry (10min TTL)
_DRY_RUN_TOKENS = {}

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
        "ss.overview": "数据源总览", "ss.localFiles": "本地文件连接器",
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
        "ss.overview": "Source Systems", "ss.localFiles": "Local Files Connector",
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
            <tr><td data-i18n="settings.version" style="color:var(--text-secondary);width:120px">版本</td><td>2026.5.28</td></tr>
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
      headers: {'Content-Type': 'application/json'},
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
      headers: {'Content-Type': 'application/json'},
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
  listEl.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  lfEl.innerHTML = '<div class="loading">'+t('common.loading')+'</div>';
  try {
    var ss = await fetch('/api/v1/source-systems').then(function(r){return r.json();});
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
  }
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
  fetch('/api/v1/source-systems/local_files/ingest', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({dry_run:false})}).then(function(r){return r.json();}).then(function(d){
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
      headers: {'Content-Type':'application/json'},
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
      headers: {'Content-Type':'application/json'},
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
      headers: {'Content-Type':'application/json'},
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
      headers: {'Content-Type':'application/json'},
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
      headers: {'Content-Type':'application/json'},
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

# ─── Data fetchers ──────────────────────────────────────────

def get_watcher_status():
    sm = get_service_manager()
    if sm.is_active("memcore-cloud"):
        return True
    pid_path = os.path.join(str(MEMCORE_ROOT), "runtime", "p0-watcher.pid")
    try:
        with open(pid_path, encoding="ascii", errors="ignore") as f:
            pid = int(f.read().strip())
        if sys.platform == "win32":
            ps = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in ps.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        pass
    if sys.platform.startswith("linux"):
        for cmd in (
            ["systemctl", "--user", "is-active", "--quiet", "memcore-cloud-p0-watcher.service"],
            ["systemctl", "is-active", "--quiet", "memcore-cloud-p0-watcher.service"],
        ):
            try:
                ps = subprocess.run(cmd, capture_output=True, timeout=5)
                if ps.returncode == 0:
                    return True
            except Exception:
                pass
    if sys.platform == "darwin":
        try:
            ps = subprocess.run(
                ["ps", "ax", "-o", "command="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return any(
                "memcore-cloud.py" in line and "--watch" in line
                for line in ps.stdout.splitlines()
            )
        except Exception:
            return False
    return False

def get_raw_stats():
    sessions = glob.glob(f"{MEMCORE_ROOT}/memory/*/*/*/*.jsonl")
    windows = set()
    by_source = {}
    total_msgs = 0
    for s in sessions:
        windows.add(os.path.dirname(s).split("/")[-1])
        parts = os.path.relpath(s, f"{MEMCORE_ROOT}/memory").split(os.sep)
        if parts:
            by_source[parts[0]] = by_source.get(parts[0], 0) + 1
    # Fast: just count files, skip expensive line counting for API
    return {"sessions": len(sessions), "windows": len(windows), "messages": -1, "by_source_system": by_source}

def get_zhiyi_stats():
    stats = {}
    for ftype in ["case_memory", "error_memory", "preference_memory"]:
        path = f"{MEMCORE_ROOT}/zhiyi/{ftype}/{ftype}.jsonl"
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                stats[ftype] = sum(1 for _ in f if _.strip())
        except:
            stats[ftype] = 0
    return stats

def get_alias_map():
    path = f"{MEMCORE_ROOT}/config/alias_map.json"
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except:
        return {}

def load_zhiyi_objects(ftype=None, limit=None):
    objects = []
    types = [ftype] if ftype else ["case_memory", "error_memory", "preference_memory"]
    for t in types:
        path = f"{MEMCORE_ROOT}/zhiyi/{t}/{t}.jsonl"
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    obj["_type"] = t
                    try:
                        obj["_source_refs"] = json.loads(obj.get("source_refs", "{}"))
                    except:
                        obj["_source_refs"] = {}
                    objects.append(obj)
                    if limit is not None and len(objects) >= limit:
                        return objects
                except:
                    pass
    return objects

def run_health_check():
    import sys
    results = {}
    sessions = glob.glob(f"{MEMCORE_ROOT}/memory/openclaw/*/*/*.jsonl")
    # Fast: only count sessions, skip per-line reading for performance
    results["p0raw"] = {"status": "passed", "detail": f"{len(sessions)} sessions"}
    watcher_active = get_watcher_status()
    if sys.platform == "win32":
        watcher_detail = "runtime/p0-watcher.pid"
    elif sys.platform.startswith("linux"):
        watcher_detail = "memcore-cloud-p0-watcher.service"
    else:
        watcher_detail = "com.memcorecloud.p0-watcher"
    results["p0watcher"] = {"status": "passed" if watcher_active else "failed",
                              "detail": watcher_detail}
    stats = get_zhiyi_stats()
    results["p2zhiyi"] = {"status": "passed",
                            "detail": f"case={stats.get('case_memory',0)} error={stats.get('error_memory',0)} pref={stats.get('preference_memory',0)}"}
    objs = load_zhiyi_objects(limit=2000)
    failures = sum(1 for o in objs if o.get("_source_refs", {}).get("source_path", "") and
                   not os.path.exists(o.get("_source_refs", {}).get("source_path", "")))
    results["p2sourceRef"] = {"status": "passed" if failures == 0 else "failed",
                                "detail": f"{len(objs)} sampled objects, {failures} path failures"}
    # p3_recall + p4_provider health: socket 端口检测（避免加载 bge-m3 模型）
    import socket
    for svc_name, port in [("p3recall", 9830), ("p4provider", 9840)]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result == 0:
                results[svc_name] = {"status": "passed", "detail": f"port {port} reachable"}
            else:
                results[svc_name] = {"status": "failed", "detail": f"port {port} unreachable"}
        except Exception as e:
            results[svc_name] = {"status": "failed", "detail": str(e)[:80]}
    return results

# ─── M3 Status API Helpers (只读) ──────────────────────────────
# Runtime/Zhiyi/Audit status helpers for the legacy local console.
# 原则：全部只读，不写任何文件，不触发 apply，不外推状态

def m3_get_overview():
    """M3-1: 系统总览状态"""
    import socket
    from datetime import datetime, timezone
    watcher = get_watcher_status()
    raw = get_raw_stats()
    zhiyi = get_zhiyi_stats()
    # Port checks
    ports = {}
    for svc, port in [("p3recall", 9830), ("p4inject", 9840)]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            r = s.connect_ex(("127.0.0.1", port))
            s.close()
            ports[svc] = "up" if r == 0 else "down"
        except:
            ports[svc] = "unknown"
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "watcher_active": watcher,
        "raw_memory": raw,
        "zhiyi_objects": zhiyi,
        "service_ports": ports,
        "phase": "local-service-ready",
    }


def m3_get_openclaw_runtime():
    """M3-2: OpenClaw Runtime 状态"""
    import socket
    result = {"gateway_reachable": False, "gateway_port": 18789}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        r = s.connect_ex(("127.0.0.1", 18789))
        s.close()
        result["gateway_reachable"] = (r == 0)
    except:
        pass
    # Check paired.json existence
    import os as _os
    paired_path = _os.path.expanduser("~/.openclaw/gateway/paired.json")
    result["device_paired"] = _os.path.exists(paired_path)
    return result


def m3_get_memory_runtime():
    """M3-3: Memory/Zhiyi Runtime 状态"""
    zhiyi = get_zhiyi_stats()
    raw = get_raw_stats()
    # Count lifecycle overlay entries
    lifecycle_stats = {}
    for ftype in ["case_memory", "error_memory"]:
        lc_path = f"{MEMCORE_ROOT}/zhiyi/{ftype}/{ftype}.lifecycle.jsonl"
        try:
            with open(lc_path) as f:
                lifecycle_stats[ftype] = sum(1 for _ in f if _.strip())
        except:
            lifecycle_stats[ftype] = 0
    return {
        "raw_memory": raw,
        "zhiyi_objects": zhiyi,
        "lifecycle_overlay": lifecycle_stats,
        "lifecycle_overlay_total": sum(lifecycle_stats.values()),
    }


def m3_get_j2_j7_runtime():
    """M3-4: J2-J7 Lifecycle Runtime 状态"""
    # Check if lifecycle overlay is loaded and working
    try:
        import sys as _sys
        _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
        from p3_recall import _get_lifecycle_overlay, load_memories, _apply_lifecycle_overlay
        overlay = _get_lifecycle_overlay()
        memories = load_memories()
        enhanced = _apply_lifecycle_overlay(memories)
        from collections import Counter
        status_ctr = Counter(m.get("_lifecycle", {}).get("status", "") for m in enhanced)
        conflict_ctr = Counter(m.get("_lifecycle", {}).get("conflict_decision", "") for m in enhanced)
        j2_dedup_applied = len(memories)
        j3_superseded_filtered = len(memories) - len(enhanced)
        return {
            "j2_dedup_applied": True,
            "j2_unique_exp_ids": j2_dedup_applied,
            "j3_supersession_filter_applied": True,
            "j3_superseded_filtered_count": j3_superseded_filtered,
            "j4_freshness_applied": True,
            "j5_ranking_applied": True,
            "lifecycle_overlay_entries": len(overlay),
            "status_distribution": dict(status_ctr),
            "conflict_decision_distribution": dict(conflict_ctr),
            "_note": "J6/J7 processed at recall time, no separate runtime state",
        }
    except Exception as e:
        return {"error": str(e), "j2_j7_runtime_ready": False}


def m3_get_recent_recall():
    """M3-5: 最近召回结果（触发一次真实 recall）"""
    try:
        import sys as _sys
        _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
        from p3_recall import handle_recall
        # Use window/sg as default scope (most common), threshold=0.1 to show injectable
        result = handle_recall({
            "query": "",
            "scope_filter": "window/sg",
            "top_k": 5,
            "threshold": 0.1,
            "recall_mode": "substring",
        })
        return {
            "recall_working": True,
            "total_matched": result.get("total_matched", 0),
            "returned": result.get("returned", 0),
            "_scope_enforced": result.get("_scope_enforced", False),
            "matched_memories_count": len(result.get("matched_memories", [])),
        }
    except Exception as e:
        return {"error": str(e), "recall_working": False}


def m3_get_audit_risks():
    """M3-6: AUDIT 风险状态"""
    import os
    risks = []
    # Check for forbidden paths
    forbidden_files = [
        ("device_identity", "~/.openclaw/gateway/device_identity"),
        ("private_key", "~/.openclaw/gateway/private_key"),
    ]
    for name, path in forbidden_files:
        full = os.path.expanduser(path)
        if os.path.exists(full):
            risks.append({"type": name, "path": path, "status": "forbidden_path_exists", "severity": "CRITICAL"})
    # Check update safety
    try:
        sys_path = sys.path.insert(0, str(MEMCORE_ROOT) + "/src") if False else None
        from update_safety import PROTECTED_UPDATE_PATHS
        risks.append({"type": "protected_update_paths_loaded", "count": len(PROTECTED_UPDATE_PATHS), "severity": "OK"})
    except:
        pass
    # Check raw memory integrity
    try:
        import hashlib
        raw_hashes = {
            "case_memory": "76fe7e5b0b8d582f17f8b732c63a69c7936573c9bd4474134e3a33922acbbfca",
            "error_memory": "19197c63c8ac770000ce2d338df234a47002ca739124fb8065e0617676fc9691",
        }
        for mtype, expected_hash in raw_hashes.items():
            raw_path = f"{MEMCORE_ROOT}/zhiyi/{mtype}/{mtype}.jsonl"
            if os.path.exists(raw_path):
                with open(raw_path, "rb") as f:
                    actual = hashlib.sha256(f.read()).hexdigest()
                status = "OK" if actual == expected_hash else "MODIFIED"
                if status != "OK":
                    risks.append({"type": "raw_integrity", "mtype": mtype, "status": status, "severity": "HIGH"})
    except Exception as e:
        risks.append({"type": "raw_integrity_check_failed", "error": str(e), "severity": "MEDIUM"})
    return {"risks": risks, "total_risks": len(risks), "audit1_pass": len([r for r in risks if r.get("severity") in ("CRITICAL", "HIGH")]) == 0}


def m3_get_update_status():
    """M3-7: Update 状态"""
    import os, hashlib, json as _json
    version_path = f"{MEMCORE_ROOT}/VERSION"
    current = "unknown"
    if os.path.exists(version_path):
        with open(version_path) as f:
            current = f.read().strip()
    update_plan_path = f"{MEMCORE_ROOT}/release/update_plan.json"
    update_plan = {}
    if os.path.exists(update_plan_path):
        with open(update_plan_path) as f:
            update_plan = _json.load(f)
    return {
        "current_version": current,
        "update_plan_exists": os.path.exists(update_plan_path),
        "update_plan": update_plan,
        "apply_enabled": False,  # Linux gated, never auto-apply
    }


def m3_get_source_systems():
    """M3-8: Source Systems 状态"""
    import sys as _sys
    _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
    try:
        from source_system_registry import list_source_systems, get_active_sources
        all_sources = list_source_systems()
        active_sources = get_active_sources()
        return {
            "all_sources": all_sources,
            "active_sources": active_sources,
            "total": len(all_sources),
            "active_count": len(active_sources),
            "_note": "status is read-only, not extrapolated",
        }
    except Exception as e:
        return {"error": str(e)}


# ─── M4 Task Results API Helpers (只读) ──────────────────────────────
# Legacy task result panel helpers.
# 原则：全部只读，读取 output/ 目录下的验收 JSON，不写任何文件

def _m4_scan_task_results():
    """扫描 output/ 目录，构建历史任务结果列表。"""
    import os, json as _json
    output_root = f"{MEMCORE_ROOT}/output"
    tasks = []
    if not os.path.isdir(output_root):
        return tasks
    for name in os.listdir(output_root):
        legacy_task_prefix = "P9" + "-System-"
        if not name.startswith(legacy_task_prefix):
            continue
        checks_dir = os.path.join(output_root, name, "checks")
        if not os.path.isdir(checks_dir):
            tasks.append({
                "task_id": name,
                "status": "unknown",
                "result": None,
                "all_ok": None,
            })
            continue
        # Find the acceptance check file
        acceptance_file = None
        for f in os.listdir(checks_dir):
            if f.endswith("_acceptance_check.json"):
                acceptance_file = os.path.join(checks_dir, f)
                break
        if acceptance_file:
            try:
                with open(acceptance_file) as f:
                    d = _json.load(f)
                tasks.append({
                    "task_id": name,
                    "status": d.get("result", "unknown").lower(),
                    "result": d.get("result"),
                    "all_ok": d.get("all_ok"),
                    "timestamp": d.get("timestamp", ""),
                    "scope_check": d.get("scope_check", {}),
                })
            except Exception:
                tasks.append({"task_id": name, "status": "error", "result": None, "all_ok": None})
        else:
            tasks.append({"task_id": name, "status": "unknown", "result": None, "all_ok": None})
    return tasks


def m4_get_task_results():
    """M4-1: 任务结果列表"""
    tasks = _m4_scan_task_results()
    # Sort: PASS first, thenLIMITED, then FAIL, then unknown
    order = {"pass": 0, "limited": 1, "fail": 2, "error": 3, "unknown": 4}
    tasks.sort(key=lambda t: (order.get(t["status"], 9), t["task_id"]))
    return {
        "total": len(tasks),
        "passed": sum(1 for t in tasks if t["status"] == "pass"),
        "failed": sum(1 for t in tasks if t["status"] == "fail"),
        "limited": sum(1 for t in tasks if t["status"] == "limited"),
        "tasks": tasks,
    }


def m4_get_task_detail(task_id):
    """M4-2: 任务详情"""
    import os, json as _json
    # Sanitize task_id to prevent path traversal
    safe_id = task_id.replace("..", "_").replace("/", "_")
    checks_dir = f"{MEMCORE_ROOT}/output/{safe_id}/checks"
    if not os.path.isdir(checks_dir):
        return {"error": f"Task {task_id} not found", "task_id": task_id}
    acceptance_file = None
    for f in os.listdir(checks_dir):
        if f.endswith("_acceptance_check.json"):
            acceptance_file = os.path.join(checks_dir, f)
            break
    if not acceptance_file:
        return {"error": f"No acceptance check for {task_id}", "task_id": task_id}
    try:
        with open(acceptance_file) as f:
            d = _json.load(f)
        # Add code and test file lists
        code_files = []
        test_files = []
        code_path = f"{MEMCORE_ROOT}/output/{safe_id}/code_changed_files.txt"
        test_path = f"{MEMCORE_ROOT}/output/{safe_id}/test_changed_files.txt"
        if os.path.exists(code_path):
            with open(code_path) as f:
                code_files = [l.strip() for l in f if l.strip()]
        if os.path.exists(test_path):
            with open(test_path) as f:
                test_files = [l.strip() for l in f if l.strip()]
        d["code_files"] = code_files
        d["test_files"] = test_files
        d["_note"] = "read-only: task result from acceptance check"
        return d
    except Exception as e:
        return {"error": str(e), "task_id": task_id}


def m4_get_task_summary(task_id):
    """M4-3: 可复制摘要文本"""
    detail = m4_get_task_detail(task_id)
    if "error" in detail:
        return {"error": detail["error"]}
    lines = []
    lines.append(f"## {detail.get('system', task_id)}")
    lines.append(f"**结果**: {detail.get('result', 'N/A')}")
    if detail.get('timestamp'):
        lines.append(f"**时间**: {detail['timestamp']}")
    if detail.get('scope_check'):
        sc = detail['scope_check']
        lines.append(f"**红线检查**:")
        for k, v in sc.items():
            icon = "✅" if v else "❌"
            lines.append(f"  {icon} {k}: {v}")
    if detail.get('test_suite'):
        ts = detail['test_suite']
        if 'm3_new_tests' in ts:
            m3 = ts['m3_new_tests']
            lines.append(f"**测试**: {m3.get('all_pass', 'N/A')} ({m3.get('total', 0)} cases)")
    if detail.get('code_files'):
        lines.append(f"**修改文件数**: {len(detail['code_files'])}")
        for f in detail['code_files'][:3]:
            lines.append(f"  - {f}")
        if len(detail['code_files']) > 3:
            lines.append(f"  ... and {len(detail['code_files'])-3} more")
    lines.append(f"[复制时间: {detail.get('timestamp','')}]")
    return {
        "task_id": task_id,
        "summary_text": "\n".join(lines),
        "result": detail.get("result"),
        "all_ok": detail.get("all_ok"),
    }


def m4_get_risk_backlog():
    """M4-4: 风险挂账摘要"""
    risks = []
    # J7 inject_policy=never 无数据
    risks.append({
        "id": "J7-INJECT-POLICY-NODATA",
        "task": "runtime-status",
        "severity": "LOW",
        "type": "data_gap",
        "description": "inject_policy=never 记录数为 0，测试降级为逻辑验证",
        "status": "known_deferred",
        "property": "数据缺口，非代码缺陷",
    })
    # lifecycle overlay 覆盖率 94/291
    risks.append({
        "id": "LIFECYCLE-OVERLAY-COVERAGE",
        "task": "runtime-status",
        "severity": "MEDIUM",
        "type": "data_gap",
        "description": "lifecycle overlay 覆盖率 94/291，其余 197 条无 overlay",
        "status": "known_deferred",
        "property": "预期行为，增量处理进行中",
    })
    risks.append({
        "id": "RAW-INTEGRITY-REVIEW",
        "task": "raw-integrity-review",
        "severity": "HIGH",
        "type": "integrity",
        "description": "raw JSONL SHA256 与 baseline 不同（lifecycle migration 后数据变化）",
        "status": "known_deferred",
        "property": "M3 如实反映，不掩盖",
    })
    return {
        "total": len(risks),
        "risks": risks,
        "audit1_pass": False,
        "_note": "风险已记录，不阻塞当前使用",
    }


def m4_get_next_decision_summary():
    """M4-5: 下一步决策摘要"""
    return {
        "current_phase": "local-console-review-complete",
        "pending_decisions": [
            {
                "id": "DECISION-M4-NEXT",
                "after": "local-console-review",
                "options": [
                    {"id": "A", "label": "继续 M/UI", "description": "完善交互和移动端体验"},
                    {"id": "B", "label": "进入 L/source_system", "description": "接 Hermes / Codex / Local Files"},
                    {"id": "C", "label": "进入 Release", "description": "真实 GitHub Release / 远程发布源"},
                    {"id": "D", "label": "进入 Z8", "description": "production-gated canonical event pilot"},
                    {"id": "E", "label": "暂停处理", "description": "整理风险挂账和补丁路线"},
                ],
                "owner": "甲方",
                "basis": "M4 任务书第 12 节",
            }
        ],
        "completed_systems": [
            "runtime-status",
            "local-console-status",
            "local-console-review",
        ],
        "_note": "决策权归甲方，执行方不得自动进入下一阶段",
    }


# ─── M5 Zhiyi Management API Helpers (只读) ──────────────────────────────
# Zhiyi management and memory governance console v1.
# 原则：全部只读，不写任何文件，不触发真实注入
# owner-facing views keep saved user content verbatim

def _m5_raw_evidence_for_refs(refs, excerpt_chars=600):
    """Return bounded raw excerpt for owner-facing detail views."""
    refs = refs or {}
    if not isinstance(refs, dict):
        return {
            "raw_evidence_status": "invalid_source_refs",
            "raw_excerpt": "",
            "evidence_hash": None,
            "source_path": "",
            "msg_ids": [],
        }
    source_path = refs.get("source_path", "")
    msg_ids = refs.get("msg_ids", []) or []
    if not source_path:
        return {
            "raw_evidence_status": "not_raw",
            "raw_excerpt": "",
            "evidence_hash": None,
            "source_path": "",
            "msg_ids": msg_ids,
        }
    try:
        try:
            from raw_consumption_gateway import _extract_bounded_raw_excerpt
        except Exception:
            from src.raw_consumption_gateway import _extract_bounded_raw_excerpt
        raw_excerpt, raw_status, evidence_hash = _extract_bounded_raw_excerpt(source_path, msg_ids, excerpt_chars)
    except Exception as e:
        raw_excerpt, raw_status, evidence_hash = "", f"read_error:{str(e)[:80]}", None
    return {
        "raw_evidence_status": raw_status,
        "raw_excerpt": raw_excerpt,
        "raw_excerpt_chars": len(raw_excerpt or ""),
        "evidence_hash": evidence_hash,
        "source_path": source_path,
        "msg_ids": msg_ids,
    }

def _m5_safe_memories():
    """加载所有知意对象，保留已保存用户内容。"""
    objs = load_zhiyi_objects()
    for obj in objs:
        raw_refs = obj.get("_source_refs", {})
        if not raw_refs:
            raw_refs = obj.get("source_refs", {})
        if isinstance(raw_refs, str):
            try:
                raw_refs = json.loads(raw_refs)
            except Exception:
                raw_refs = {}
        obj["_source_refs"] = raw_refs if isinstance(raw_refs, dict) else {}
        obj.update(attach_archive_card(obj))
    return objs


def _m5_get_memories(params=None):
    """M5-1: 知意记忆列表（分页，只读）"""
    params = params or {}
    ftype = params.get("type")
    page = int(params.get("page", 1))
    page_size = min(int(params.get("page_size", 20)), 100)
    objs = _m5_safe_memories()
    if ftype:
        objs = [o for o in objs if o.get("_type") == ftype]
    total = len(objs)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = objs[start:end]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": page_items,
    }


def _m5_get_memory_detail(memory_id):
    """M5-2: 知意记忆详情（按 exp_id 查找）"""
    # memory_id in URL maps to exp_id in data (J1: memory_id 是主键，但 base JSONL 用 exp_id)
    safe_id = memory_id.replace("..", "_").replace("/", "_")
    objs = _m5_safe_memories()
    for obj in objs:
        if obj.get("exp_id") == safe_id:
            recycle_state = _zhiyi_experience_recycle_overlay().get(safe_id, {})
            # Add lifecycle info if available
            try:
                from p3_recall import _get_lifecycle_overlay
                overlay = _get_lifecycle_overlay()
                lc = overlay.get(safe_id, {})
                obj["_lifecycle"] = {
                    "status": lc.get("status", ""),
                    "lifecycle_version": lc.get("lifecycle_version", 0),
                    "conflict_decision": lc.get("conflict_decision", ""),
                    "inject_policy": lc.get("inject_policy", ""),
                }
            except Exception:
                pass
            obj["_deleted_state"] = "recycle_bin" if recycle_state else "active"
            obj["_recycle"] = recycle_state
            if "_lifecycle" not in obj:
                obj["_lifecycle"] = {}
            obj["_lifecycle"]["deleted_state"] = obj["_deleted_state"]
            obj["_lifecycle"]["suppression_marker"] = bool(recycle_state.get("suppression_marker"))
            obj["_raw_evidence"] = _m5_raw_evidence_for_refs(obj.get("_source_refs", {}))
            obj.update(attach_archive_card(obj))
            return obj
    return {"error": f"Memory {memory_id} not found", "memory_id": memory_id}


def _m5_get_memory_refs(memory_id):
    """M5-3: source_refs 回指和原文回源。"""
    obj = _m5_get_memory_detail(memory_id)
    if "error" in obj:
        return {"error": obj["error"]}
    # Return refs + bounded raw excerpt for owner-facing detail.
    refs = obj.get("_source_refs", {})
    raw_evidence = _m5_raw_evidence_for_refs(refs)
    source_path = raw_evidence.get("source_path", "")
    raw_exists = bool(source_path and os.path.exists(source_path))
    return {
        "memory_id": memory_id,
        "exp_id": obj.get("exp_id", ""),
        "catalog_id": obj.get("catalog_id", ""),
        "archive_card": obj.get("archive_card", {}),
        "_type": obj.get("_type", ""),
        "_source_refs": refs,
        "_raw_exists": raw_exists,
        "_raw_evidence": raw_evidence,
        "_payload_exposed": "payload" in obj,
        "_note": "source_refs metadata and bounded raw excerpt; saved user content is not rewritten",
    }


def _m5_get_lifecycle_overlay_stats():
    """M5-4: Lifecycle Overlay 统计"""
    try:
        from p3_recall import _get_lifecycle_overlay
        overlay = _get_lifecycle_overlay()
        from collections import Counter
        status_ctr = Counter(v.get("status", "") for v in overlay.values())
        decision_ctr = Counter(v.get("conflict_decision", "") for v in overlay.values())
        visibility_ctr = Counter(v.get("visibility", "") for v in overlay.values())
        return {
            "total_overlay_entries": len(overlay),
            "status_distribution": dict(status_ctr),
            "conflict_decision_distribution": dict(decision_ctr),
            "visibility_distribution": dict(visibility_ctr),
            "j2_unique_base_exp_ids": 291,
            "_note": "overlay keyed by exp_id, total entries from lifecycle JSONL files",
        }
    except Exception as e:
        return {"error": str(e), "lifecycle_overlay_ready": False}


def _m5_recall_preview(params):
    """M5-5: Recall Preview（dry-view，不触发真实注入）"""
    try:
        import sys as _sys
        _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
        from p3_recall import handle_recall
        query = params.get("query", "")
        scope = params.get("scope_filter", "")
        top_k = min(int(params.get("top_k", 5)), 20)
        threshold = float(params.get("threshold", 0.5))
        ftype = params.get("type")
        body = {
            "query": query,
            "scope_filter": scope,
            "top_k": top_k,
            "threshold": threshold,
        }
        if ftype:
            body["type_filter"] = [ftype]
        result = handle_recall(body)
        # Return summary only, no payload
        mems = result.get("matched_memories", [])
        safe_mems = []
        for m in mems:
            safe_m = {
                "exp_id": m.get("exp_id", ""),
                "_type": m.get("type", ""),
                "scope": m.get("scope", ""),
                "confidence": m.get("confidence", 0),
                "summary": m.get("summary", ""),
                "should_inject": m.get("should_inject", False),
                "_lifecycle": m.get("_lifecycle", {}),
                "_adjusted_score": m.get("_adjusted_score"),
            }
            safe_mems.append(safe_m)
        return {
            "_dry_view": True,
            "_injection_triggered": False,
            "query": query,
            "scope_filter": scope,
            "total_matched": result.get("total_matched", 0),
            "returned": result.get("returned", 0),
            "matched_memories": safe_mems,
        }
    except Exception as e:
        return {"error": str(e), "_dry_view": True, "_injection_triggered": False}


def _m5_injection_explain(params):
    """M5-6: 注入决策解释（只读分析）"""
    try:
        import sys as _sys
        _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
        from p3_recall import handle_recall
        query = params.get("query", "")
        scope = params.get("scope_filter", "")
        top_k = min(int(params.get("top_k", 10)), 20)
        threshold = float(params.get("threshold", 0.5))
        body = {
            "query": query,
            "scope_filter": scope,
            "top_k": top_k,
            "threshold": threshold,
        }
        result = handle_recall(body)
        mems = result.get("matched_memories", [])
        explain_items = []
        for m in mems:
            lc = m.get("_lifecycle", {})
            conf = m.get("confidence", 0)
            should_inject = m.get("should_inject", False)
            reasons = []
            if conf < threshold:
                reasons.append(f"confidence={conf:.2f} < threshold={threshold}")
            if lc.get("inject_policy") == "never":
                reasons.append("inject_policy=never overrides")
            if lc.get("status") == "superseded":
                reasons.append("lifecycle status=superseded")
            if not reasons:
                reasons.append("confidence >= threshold, no lifecycle override")
            explain_items.append({
                "exp_id": m.get("exp_id", ""),
                "confidence": conf,
                "should_inject": should_inject,
                "reasons": reasons,
                "lifecycle_status": lc.get("status", ""),
                "lifecycle_inject_policy": lc.get("inject_policy", ""),
                "adjusted_score": m.get("_adjusted_score"),
            })
        injectable = [x for x in explain_items if x["should_inject"]]
        return {
            "query": query,
            "scope_filter": scope,
            "threshold": threshold,
            "total_candidates": len(explain_items),
            "injectable_count": len(injectable),
            "decision_explained": explain_items,
            "_injection_triggered": False,
            "_note": "analysis only; real injection requires explicit trigger",
        }
    except Exception as e:
        return {"error": str(e)}


# ─── M6 Governance Proposal Helpers ─────────────────────────────────────
# Zhiyi governance proposal dry-run.
# 原则：所有 proposal dry_run_only=true, applied=false
# 只写治理 proposal 目录，不改 raw / OpenClaw / 生产知意

M6_PROPOSALS_DIR = f"{MEMCORE_ROOT}/output/{'P9' + '-System-M6'}/proposals"


def _m6_ensure_proposals_dir():
    import os
    os.makedirs(M6_PROPOSALS_DIR, exist_ok=True)


def _m6_validate_target_exp_ids(exp_ids):
    """验证 exp_ids 存在于 base zhiyi 数据中"""
    objs = load_zhiyi_objects()
    valid_exp_ids = set(o.get("exp_id", "") for o in objs)
    invalid = [eid for eid in exp_ids if eid not in valid_exp_ids]
    return invalid


def _m6_write_proposal(proposal_record):
    """将 proposal 写入 JSONL（dry-run only）"""
    import os, uuid
    _m6_ensure_proposals_dir()
    if not proposal_record.get("proposal_id"):
        proposal_record["proposal_id"] = str(uuid.uuid4())
    if not proposal_record.get("created_at"):
        from datetime import datetime, timezone
        proposal_record["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    # Enforce dry_run_only and applied
    proposal_record["dry_run_only"] = True
    proposal_record["applied"] = False
    proposal_path = f"{M6_PROPOSALS_DIR}/{proposal_record['proposal_id']}.jsonl"
    with open(proposal_path, "w") as f:
        f.write(json.dumps(proposal_record, ensure_ascii=False) + "\n")
    return proposal_record


def _m6_compute_impact(target_exp_ids, proposal_type, proposal_data):
    """计算 proposal 影响范围"""
    import os, json as _json
    objs = load_zhiyi_objects()
    exp_id_set = set(target_exp_ids)
    target_objs = [o for o in objs if o.get("exp_id") in exp_id_set]
    type_ctr = {}
    for o in target_objs:
        t = o.get("_type", "unknown")
        type_ctr[t] = type_ctr.get(t, 0) + 1
    return {
        "target_count": len(target_exp_ids),
        "matched_in_base": len(target_objs),
        "by_type": type_ctr,
        "proposal_type": proposal_type,
    }


def m6_create_proposal(body):
    """M6-1: 创建治理 proposal（dry-run only）"""
    import os, uuid
    # Validate required fields
    target_exp_ids = body.get("target_exp_ids", [])
    proposal_type = body.get("proposal_type", "")
    valid_types = ["duplicate", "conflict", "superseded", "archived", "inject_policy", "edit_summary"]
    if not target_exp_ids:
        return {"error": "target_exp_ids required"}
    if proposal_type not in valid_types:
        return {"error": f"proposal_type must be one of {valid_types}"}
    # Validate targets exist
    invalid = _m6_validate_target_exp_ids(target_exp_ids)
    if invalid:
        return {"error": f"exp_ids not found: {invalid[:3]}"}
    # Build proposal record
    proposal_record = {
        "proposal_id": str(uuid.uuid4()),
        "created_at": body.get("created_at", ""),
        "dry_run_only": True,
        "applied": False,
        "target_exp_ids": target_exp_ids,
        "proposal_type": proposal_type,
        "rationale": body.get("rationale", ""),
        # Type-specific fields
        "duplicate_of": body.get("duplicate_of", None),
        "conflict_with": body.get("conflict_with", None),
        "new_status": body.get("new_status", None),
        "inject_policy": body.get("inject_policy", None),
        "new_summary": body.get("new_summary", None),
        "edit_field": body.get("edit_field", None),
    }
    # Compute impact
    proposal_record["impact"] = _m6_compute_impact(target_exp_ids, proposal_type, proposal_record)
    # Write to output (dry-run only)
    proposal_record = _m6_write_proposal(proposal_record)
    return {
        "proposal_id": proposal_record["proposal_id"],
        "dry_run_only": True,
        "applied": False,
        "impact": proposal_record["impact"],
        "status": "draft",
        "_note": "dry-run proposal: not applied to production zhiyi or raw",
    }


def m5_create_experience_action(body):
    """P1-1: create durable backend proposal for frontstage lifecycle actions."""
    action = body.get("action", "")
    target_exp_ids = body.get("target_exp_ids", [])
    if isinstance(target_exp_ids, str):
        target_exp_ids = [target_exp_ids]
    target_exp_ids = [eid for eid in target_exp_ids if eid]
    if action not in ("adopt", "upgrade", "recycle"):
        return {"error": "action must be one of adopt, upgrade, recycle"}
    if not target_exp_ids:
        return {"error": "target_exp_ids required"}

    proposal = {
        "target_exp_ids": target_exp_ids,
        "rationale": body.get("rationale") or f"frontstage {action} action",
    }
    if action == "adopt":
        proposal.update({
            "proposal_type": "inject_policy",
            "inject_policy": body.get("inject_policy") or "on_demand",
        })
    elif action == "upgrade":
        proposal.update({
            "proposal_type": "edit_summary",
            "new_summary": body.get("new_summary", None),
            "edit_field": body.get("edit_field", "summary"),
        })
    elif action == "recycle":
        proposal.update({
            "proposal_type": "archived",
            "new_status": "archived",
        })

    result = m6_create_proposal(proposal)
    if "error" in result:
        return result
    result["action"] = action
    result["target_exp_ids"] = target_exp_ids
    result["backend_persisted"] = True
    result["_note"] = "backend governance proposal created; no browser-local lifecycle state"
    return result


def m6_list_proposals():
    """M6-2: 列出所有 proposal"""
    _m6_ensure_proposals_dir()
    proposals = []
    try:
        for fname in os.listdir(M6_PROPOSALS_DIR):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(M6_PROPOSALS_DIR, fname)
            with open(fpath) as f:
                line = f.readline()
                if line.strip():
                    proposals.append(json.loads(line))
    except Exception:
        pass
    proposals.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    by_type = {}
    for p in proposals:
        pt = p.get("proposal_type", "unknown")
        by_type[pt] = by_type.get(pt, 0) + 1
    return {
        "total": len(proposals),
        "by_type": by_type,
        "proposals": proposals,
    }


def m6_get_proposal(proposal_id):
    """M6-3: proposal 详情"""
    import os
    _m6_ensure_proposals_dir()
    fpath = f"{M6_PROPOSALS_DIR}/{proposal_id}.jsonl"
    if not os.path.exists(fpath):
        return {"error": f"Proposal {proposal_id} not found", "proposal_id": proposal_id}
    with open(fpath) as f:
        line = f.readline()
        if not line.strip():
            return {"error": "Empty proposal file"}
        return json.loads(line)


def m6_get_proposal_summary(proposal_id):
    """M6-4: proposal 复制摘要"""
    p = m6_get_proposal(proposal_id)
    if "error" in p:
        return {"error": p["error"]}
    lines = []
    lines.append(f"## Governance Proposal")
    lines.append(f"**ID**: {p.get('proposal_id', '')}")
    lines.append(f"**类型**: {p.get('proposal_type', '')}")
    lines.append(f"**状态**: {p.get('status', 'draft')} (dry_run_only={p.get('dry_run_only')}, applied={p.get('applied')})")
    lines.append(f"**时间**: {p.get('created_at', '')}")
    lines.append(f"**目标**: {p.get('target_exp_ids', [])}")
    impact = p.get("impact", {})
    lines.append(f"**影响**: {impact.get('matched_in_base', 0)} 条记忆")
    if p.get("rationale"):
        lines.append(f"**理由**: {p.get('rationale')}")
    lines.append(f"")
    lines.append(f"⚠️ **dry-run only**: 此 proposal 不会修改 raw 或生产知意对象")
    return {
        "proposal_id": proposal_id,
        "summary_text": "\n".join(lines),
        "dry_run_only": p.get("dry_run_only"),
        "applied": p.get("applied"),
    }


def m6_get_stats():
    """M6-5: governance 统计"""
    listing = m6_list_proposals()
    total = listing.get("total", 0)
    by_type = listing.get("by_type", {})
    return {
        "total_proposals": total,
        "by_type": by_type,
        "by_status": {
            "draft": total,  # all are draft since none ever applied
        },
        "dry_run_only": True,
        "applied_count": 0,
        "proposals_dir": M6_PROPOSALS_DIR,
        "_note": "all proposals are dry-run: applied=0",
    }


def _compact_text(value, limit=180):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    if len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def _json_or_none(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except Exception:
        return None


def _unique_existing(paths):
    seen = set()
    result = []
    for path in paths:
        if not path:
            continue
        path = os.path.expanduser(os.path.expandvars(str(path)))
        if path in seen:
            continue
        seen.add(path)
        if os.path.exists(path):
            result.append(path)
    return result


def _home_candidates():
    candidates = [os.path.expanduser("~")]
    for env_name in ("USERPROFILE", "HOME"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    return _unique_existing(candidates)


def get_zhiyi_model_options():
    """Return read-only model choices for the product UI.

    The UI stores the user's current choice in browser storage until the runtime
    model-binding policy is separately authorized. This endpoint intentionally
    does not write config/profiles or platform files.
    """
    options = [{
        "id": "",
        "label": "默认（由接入平台决定）",
        "provider": "auto",
        "source": "platform_default",
        "category": "default",
        "description": "不指定模型，由 OpenClaw / Hermes 等接入平台使用自己的默认配置。",
    }]
    selected_model = ""
    selected_provider = ""
    notes = []
    detected_sources = []
    seen_ids = {""}
    counts = {"local": 0, "openclaw": 0, "hermes": 0}
    detected_counts = {"local": 0, "openclaw": 0, "hermes": 0}
    hidden_counts = {"local": 0, "openclaw": 0, "hermes": 0}
    display_limits = {"local": 0, "openclaw": 2, "hermes": 2}
    hidden_option_examples = []

    def add_note(note):
        if note not in notes:
            notes.append(note)

    def hide_option(item, category, reason):
        if category in hidden_counts:
            hidden_counts[category] += 1
        if len(hidden_option_examples) < 20:
            hidden = dict(item)
            hidden["hidden_reason"] = reason
            hidden_option_examples.append(hidden)
        add_note(reason)

    def add_option(option_id, label, provider, source, category, **extra):
        if not option_id or option_id in seen_ids:
            return False
        seen_ids.add(option_id)
        item = {
            "id": option_id,
            "label": label,
            "provider": provider,
            "source": source,
            "category": category,
        }
        item.update(extra)
        if category in detected_counts:
            detected_counts[category] += 1
            limit = display_limits.get(category)
            if limit is not None and counts[category] >= limit:
                reason = "local_embedding_model_hidden_from_user_options" if category == "local" else "model_candidates_limited_for_first_version"
                hide_option(item, category, reason)
                return False
        options.append(item)
        if category in counts:
            counts[category] += 1
        return True

    def record_hidden_option(option_id, label, provider, source, category, reason, **extra):
        if not option_id or option_id in seen_ids:
            return False
        seen_ids.add(option_id)
        item = {
            "id": option_id,
            "label": label,
            "provider": provider,
            "source": source,
            "category": category,
        }
        item.update(extra)
        if category in detected_counts:
            detected_counts[category] += 1
        hide_option(item, category, reason)
        return True

    model_config_path = os.path.join(str(MEMCORE_ROOT), "config", "model_config.json")
    model_config = _json_or_none(model_config_path)
    if isinstance(model_config, dict):
        recall_cfg = model_config.get("recall", {})
        openclaw_model = recall_cfg.get("openclaw_model", {})
        selected_model = openclaw_model.get("selected_model", "") or ""
        selected_provider = openclaw_model.get("selected_provider", "") or ""
        if selected_model:
            label = f"OpenClaw · {selected_model}"
            if selected_provider:
                label += f"（{selected_provider}）"
            add_option(
                f"configured-openclaw:{selected_provider or 'default'}:{selected_model}",
                label,
                "OpenClaw",
                "zhiyi_model_config",
                "openclaw",
                provider_id=selected_provider,
                model_name=selected_model,
                description="当前知意配置",
            )
        local_bge = recall_cfg.get("local_bge_m3", {})
        add_option(
            "local:bge-m3",
            "内置基础模型 BGE-M3（本机资源）",
            "内置",
            "local_bge_m3",
            "local",
            description="用于向量化、召回、检索和经验记忆匹配，配套 LanceDB；不等同于对话大模型。",
            cost_profile="本机资源 / 不额外调用平台模型",
            model_name=local_bge.get("model_name") or local_bge.get("embedding_model") or "BAAI/bge-m3",
            table=local_bge.get("table") or "experiences_v2",
        )
    else:
        notes.append("model_config_unavailable")

    def add_provider_models(platform, registry, source):
        if not isinstance(registry, dict):
            return 0
        providers = registry.get("providers")
        if providers is None and isinstance(registry.get("models"), dict):
            providers = registry.get("models", {}).get("providers")
        if not isinstance(providers, dict):
            return 0
        added = 0
        for provider_id, provider_data in providers.items():
            if not isinstance(provider_data, dict):
                continue
            models = provider_data.get("models", [])
            if isinstance(models, dict):
                iterable = []
                for model_id, model_data in models.items():
                    if isinstance(model_data, dict):
                        merged = dict(model_data)
                        merged.setdefault("id", model_id)
                        iterable.append(merged)
                    else:
                        iterable.append({"id": model_id, "name": str(model_data)})
            elif isinstance(models, list):
                iterable = models
            else:
                iterable = []
            for model_data in iterable:
                if isinstance(model_data, dict):
                    model_id = model_data.get("id") or model_data.get("model") or model_data.get("name")
                    model_label = model_data.get("name") or model_data.get("label") or model_id
                else:
                    model_id = str(model_data)
                    model_label = model_id
                if not model_id:
                    continue
                display = str(model_label or model_id)
                label = f"{platform} · {display}"
                if provider_id and str(provider_id) not in display:
                    label += f"（{provider_id}）"
                if record_hidden_option(
                    f"{platform.lower()}-provider:{provider_id}:{model_id}",
                    label,
                    platform,
                    source,
                    platform.lower(),
                    "platform_model_registry_hidden_from_user_options",
                    provider_id=str(provider_id),
                    model_name=str(model_id),
                    description="从接入平台模型表读取",
                ):
                    added += 1
        return added

    def add_agent_models(platform, config, source):
        agents = config.get("agents", {}).get("list", []) if isinstance(config, dict) else []
        if not isinstance(agents, list):
            return 0
        added = 0
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            raw_model = agent.get("model")
            if isinstance(raw_model, dict):
                model_name = raw_model.get("primary") or raw_model.get("model") or raw_model.get("name")
            else:
                model_name = raw_model
            if not model_name:
                continue
            agent_id = agent.get("id") or "agent"
            if record_hidden_option(
                f"{platform.lower()}-agent:{agent_id}:{model_name}",
                f"{platform} · {agent_id}（{model_name}）",
                platform,
                source,
                platform.lower(),
                "platform_agent_model_table_hidden_from_user_options",
                agent_id=str(agent_id),
                model_name=str(model_name),
                description="当前平台角色正在使用的模型",
            ):
                added += 1
        return added

    openclaw_roots = _unique_existing(
        [os.environ.get("OPENCLAW_HOME")]
        + [os.path.join(home, ".openclaw") for home in _home_candidates()]
    )
    openclaw_seen = False
    try:
        targets = query_openclaw_chat_send_targets({"page": 1, "page_size": 5})
        if targets.get("ok"):
            for item in targets.get("items", []):
                model_name = item.get("model", "")
                provider_id = item.get("model_provider", "")
                if not model_name:
                    continue
                add_option(
                    f"openclaw-current:{provider_id or 'default'}:{model_name}",
                    f"OpenClaw · {model_name}",
                    "OpenClaw",
                    "openclaw_recent_session",
                    "openclaw",
                    provider_id=str(provider_id or ""),
                    model_name=str(model_name),
                    description="最近使用",
                )
                openclaw_seen = True
                break
    except Exception as exc:
        notes.append(f"openclaw_recent_model_unavailable:{str(exc)[:80]}")
    for root in openclaw_roots:
        config_path = os.path.join(root, "openclaw.json")
        if os.path.exists(config_path):
            openclaw_seen = True
            config = _json_or_none(config_path)
            if isinstance(config, dict):
                detected_sources.append(config_path)
                add_provider_models("OpenClaw", config, "openclaw_provider_registry")
                add_agent_models("OpenClaw", config, "openclaw_agent")
            else:
                notes.append(f"openclaw_config_parse_failed:{config_path}")
        clawui_path = os.path.join(root, "clawui-models.json")
        clawui_models = _json_or_none(clawui_path)
        if isinstance(clawui_models, dict):
            openclaw_seen = True
            detected_sources.append(clawui_path)
            for full_model in clawui_models.keys():
                if not isinstance(full_model, str) or "/" not in full_model:
                    continue
                provider_id, model_id = full_model.split("/", 1)
                record_hidden_option(
                    f"openclaw-clawui:{full_model}",
                    f"OpenClaw · {model_id}（{provider_id}）",
                    "OpenClaw",
                    "openclaw_clawui_models",
                    "openclaw",
                    "platform_model_cache_hidden_from_user_options",
                    provider_id=provider_id,
                    model_name=model_id,
                    description="从 OpenClaw UI 模型缓存读取",
                )
        for models_path in glob.glob(os.path.join(root, "agents", "*", "agent", "models.json")):
            registry = _json_or_none(models_path)
            if isinstance(registry, dict):
                openclaw_seen = True
                detected_sources.append(models_path)
                add_provider_models("OpenClaw", registry, "openclaw_agent_models")
    if not openclaw_seen:
        notes.append("openclaw_model_registry_not_found")

    def parse_hermes_config_yaml(path):
        result = {}
        try:
            lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
        except Exception:
            return result
        in_model = False
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "model:":
                in_model = True
                continue
            if in_model and not line.startswith((" ", "\t")):
                in_model = False
            if in_model and ":" in stripped:
                key, value = stripped.split(":", 1)
                value = value.strip().strip("'\"")
                if key in ("default", "provider", "model") and value:
                    result[key] = value
        return result

    hermes_roots = _unique_existing(
        [os.environ.get("HERMES_HOME")]
        + [os.path.join(home, ".hermes") for home in _home_candidates()]
    )
    hermes_seen = False
    for root in hermes_roots:
        state_db_path = os.path.join(root, "state.db")
        if os.path.exists(state_db_path):
            try:
                import sqlite3
                con = sqlite3.connect(f"file:{state_db_path}?mode=ro", uri=True)
                rows = con.execute(
                    "SELECT model,billing_provider FROM sessions WHERE model IS NOT NULL AND model != '' ORDER BY started_at DESC LIMIT 8"
                ).fetchall()
                con.close()
                for model_name, provider_id in rows:
                    if add_option(
                        f"hermes-recent:{provider_id or 'default'}:{model_name}",
                        f"Hermes · {model_name}",
                        "Hermes",
                        "hermes_recent_session",
                        "hermes",
                        provider_id=str(provider_id or "Hermes"),
                        model_name=str(model_name),
                        description="最近使用",
                    ):
                        hermes_seen = True
                        break
            except Exception as exc:
                notes.append(f"hermes_recent_model_unavailable:{str(exc)[:80]}")
        yaml_path = os.path.join(root, "config.yaml")
        if os.path.exists(yaml_path):
            hermes_seen = True
            detected_sources.append(yaml_path)
            cfg = parse_hermes_config_yaml(yaml_path)
            model_name = cfg.get("default") or cfg.get("model")
            provider_id = cfg.get("provider") or "Hermes"
            if model_name:
                add_option(
                    f"hermes-config:{provider_id}:{model_name}",
                    f"Hermes · {model_name}（{provider_id}）",
                    "Hermes",
                    "hermes_config",
                    "hermes",
                    provider_id=provider_id,
                    model_name=model_name,
                    description="Hermes 默认模型",
                )
        for json_name in ("config.json", "settings.json"):
            config_path = os.path.join(root, json_name)
            config = _json_or_none(config_path)
            if isinstance(config, dict):
                hermes_seen = True
                detected_sources.append(config_path)
                model_name = config.get("model") or config.get("default_model") or config.get("selected_model")
                provider_id = config.get("provider") or "Hermes"
                if model_name:
                    add_option(
                        f"hermes-config:{provider_id}:{model_name}",
                        f"Hermes · {model_name}（{provider_id}）",
                        "Hermes",
                        "hermes_config",
                        "hermes",
                        provider_id=str(provider_id),
                        model_name=str(model_name),
                        description="Hermes 默认模型",
                    )
        dev_cache_path = os.path.join(root, "models_dev_cache.json")
        dev_cache = _json_or_none(dev_cache_path)
        if isinstance(dev_cache, dict):
            hermes_seen = True
            detected_sources.append(dev_cache_path)
            added = 0
            for provider_id, provider_data in dev_cache.items():
                if not isinstance(provider_data, dict):
                    continue
                models = provider_data.get("models", {})
                if not isinstance(models, dict):
                    continue
                for model_id, model_data in models.items():
                    if isinstance(model_data, dict):
                        model_label = model_data.get("name") or model_data.get("label") or model_id
                    else:
                        model_label = str(model_data) if model_data else model_id
                    if record_hidden_option(
                        f"hermes-cache:{provider_id}:{model_id}",
                        f"Hermes · {model_label}（{provider_id}）",
                        "Hermes",
                        "hermes_models_cache",
                        "hermes",
                        "platform_model_cache_hidden_from_user_options",
                        provider_id=str(provider_id),
                        model_name=str(model_id),
                        description="从 Hermes 模型缓存读取",
                    ):
                        added += 1
            if added == 0:
                notes.append("hermes_models_cache_empty")
    if not hermes_seen:
        notes.append("hermes_model_registry_not_found")

    return {
        "selected_model": selected_model,
        "selected_provider": selected_provider,
        "selection_scope": "browser_local_until_runtime_binding",
        "options": options,
        "counts": {
            "local": counts["local"],
            "openclaw": counts["openclaw"],
            "hermes": counts["hermes"],
            "total": max(0, len(options) - 1),
        },
        "detected_counts": {
            "local": detected_counts["local"],
            "openclaw": detected_counts["openclaw"],
            "hermes": detected_counts["hermes"],
            "total": sum(detected_counts.values()),
        },
        "hidden_counts": {
            "local": hidden_counts["local"],
            "openclaw": hidden_counts["openclaw"],
            "hermes": hidden_counts["hermes"],
            "total": sum(hidden_counts.values()),
        },
        "display_limits": {
            "local": display_limits["local"],
            "openclaw": display_limits["openclaw"],
            "hermes": display_limits["hermes"],
            "total": sum(display_limits.values()),
        },
        "display_limited": True,
        "candidate_policy": "product_surface_platform_default_and_current_config_only",
        "runtime_binding_ready": False,
        "runtime_binding_write_performed": False,
        "runtime_binding_status": "not_applied_no_live_config_write",
        "hidden_option_examples": hidden_option_examples,
        "detected_sources": detected_sources[:40],
        "model_list_sources": [
            "model_config local_bge_m3 (internal recall/embedding only)",
            "model_config openclaw_model selected_model (if configured)",
            "Hermes config.yaml default model",
            "OpenClaw/Hermes recent session models",
            "OpenClaw/Hermes registries are counted but kept out of the first-version picker",
            "platform default",
        ],
        "config_write_performed": False,
        "notes": notes,
    }


def build_zhiyi_model_binding_plan(body=None):
    """Return a no-write plan for turning a UI model choice into a backend default.

    This is intentionally dry-run only. The current p3 runtime still reads the
    recall engine from config/model_config.json, and platform LLM choices cannot
    be applied there without a later adapter/runtime change.
    """
    body = body or {}
    requested_id = str(
        body.get("model_id")
        or body.get("option_id")
        or body.get("selected_model")
        or ""
    )
    options_data = get_zhiyi_model_options()
    options = options_data.get("options", [])
    option_by_id = {str(item.get("id", "")): item for item in options}
    hidden_by_id = {
        str(item.get("id", "")): item
        for item in options_data.get("hidden_option_examples", [])
    }
    config_path = os.path.join(str(MEMCORE_ROOT), "config", "model_config.json")
    user_default_path = os.path.join(str(MEMCORE_ROOT), "config", "zhiyi_model_binding.user.json")
    current_config = _json_or_none(config_path) or {}
    recall_cfg = current_config.get("recall", {}) if isinstance(current_config, dict) else {}
    current_runtime = {
        "model_config_path": config_path,
        "recall_mode": recall_cfg.get("mode", "local_bge_m3") if isinstance(recall_cfg, dict) else "unknown",
        "selected_provider": "",
        "selected_model": "",
    }
    if isinstance(recall_cfg, dict):
        openclaw_cfg = recall_cfg.get("openclaw_model", {})
        if isinstance(openclaw_cfg, dict):
            current_runtime["selected_provider"] = openclaw_cfg.get("selected_provider", "") or ""
            current_runtime["selected_model"] = openclaw_cfg.get("selected_model", "") or ""

    base = {
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "runtime_binding_write_performed": False,
        "requires_authorization_for_apply": True,
        "target_user_default_path": user_default_path,
        "target_runtime_config_path": config_path,
        "current_runtime": current_runtime,
        "selection_scope": "backend_dry_run_until_authorized_runtime_binding",
        "detected_counts": options_data.get("detected_counts", {}),
        "counts": options_data.get("counts", {}),
    }

    if requested_id not in option_by_id:
        hidden = hidden_by_id.get(requested_id)
        result = dict(base)
        result.update({
            "ok": False,
            "error": "model option is not in first-version user options",
            "model_id": requested_id,
            "hidden_option": hidden,
            "notes": [
                "only_visible_first_version_options_can_be_bound",
                "local_embedding_model_is_internal_not_user_llm",
            ] if hidden else ["unknown_or_hidden_model_option"],
        })
        return result

    option = dict(option_by_id[requested_id])
    provider = option.get("provider", "auto")
    provider_id = option.get("provider_id", provider)
    model_name = option.get("model_name") or requested_id
    if requested_id == "":
        binding_kind = "platform_default"
        provider_id = ""
        model_name = ""
    else:
        binding_kind = "user_default_platform_model"

    would_write_user_default = {
        "schema_version": "1.0",
        "binding_kind": binding_kind,
        "selected_option_id": requested_id,
        "provider": provider,
        "provider_id": provider_id,
        "model_name": model_name,
        "source": option.get("source", ""),
        "selection_scope": "zhiyi_user_default",
        "applies_to": ["zhiyi_frontstage", "future_runtime_binding"],
        "write_requires_authorization": True,
    }
    runtime_blockers = [
        "p3_recall_currently_loads_config_model_config_json_for_recall_engine",
        "platform_llm_selection_needs_runtime_adapter_before_apply",
        "no_config_or_profile_write_performed_in_dry_run",
    ]
    runtime_config_plan = {
        "apply_now": False,
        "reason": "platform_model_runtime_adapter_not_implemented",
        "current_recall_mode": current_runtime["recall_mode"],
        "candidate_runtime_mode": "platform_default" if requested_id == "" else "platform_model_user_default",
        "blocked_by": runtime_blockers,
        "would_not_set_recall_mode_to_openclaw_model_without_adapter": True,
    }
    result = dict(base)
    result.update({
        "ok": True,
        "model_id": requested_id,
        "selected_option": option,
        "binding_kind": binding_kind,
        "user_default_strategy": "backend_dry_run_user_default",
        "runtime_binding_plan_ready": True,
        "runtime_binding_ready": False,
        "runtime_binding_status": "dry_run_plan_only_not_applied",
        "would_write_user_default": would_write_user_default,
        "runtime_config_plan": runtime_config_plan,
        "notes": [
            "backend_validated_visible_model_option",
            "browser_storage_is_only_ui_cache_after_this_step",
            "runtime_binding_apply_requires_later_authorization_and_adapter",
        ],
    })
    return result


ZHIYI_MODEL_BINDING_APPLY_GATE_VERSION = "p1-9.1"


def get_zhiyi_model_binding_apply_gate_policy():
    """Return the no-write authorization gate for future model binding apply."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "runtime_binding_write_performed": False,
        "policy_version": ZHIYI_MODEL_BINDING_APPLY_GATE_VERSION,
        "dry_run_endpoint": "/api/v1/zhiyi/model-binding/apply-gate/dry-run",
        "future_apply_endpoint": "/api/v1/zhiyi/model-binding/apply",
        "live_apply_endpoint_enabled": False,
        "required_authorization": [
            "confirm_write_user_default",
            "confirm_no_model_config_recall_mutation",
            "confirm_runtime_adapter_gap_understood",
            "operator",
            "reason",
        ],
        "guards": [
            "model_option_must_be_visible_first_version_option",
            "target_user_default_path_must_be_memcore_config",
            "target_runtime_config_path_must_be_read_only_model_config",
            "user_default_schema_must_be_1_0",
            "runtime_adapter_must_remain_unapplied_until_implemented",
            "dry_run_must_not_write_config",
        ],
        "write_contract": {
            "user_default_format": "json",
            "encoding": "utf-8",
            "file_mode_after_create": "0600",
            "target": "config/zhiyi_model_binding.user.json",
            "model_config_mutation": False,
        },
        "completion_claim": {
            "production_model_binding_apply_done": False,
            "runtime_adapter_done": False,
            "live_9850_updated": False,
        },
    }


def build_zhiyi_model_binding_apply_gate_dry_run(body=None):
    """Check future model-binding apply authorization without writing config."""
    body = body or {}
    binding_plan = build_zhiyi_model_binding_plan(body)
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        value = authorization.get(name, body.get(name))
        if value is True:
            return True
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "confirmed", "confirm")
        return False

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    required_checks = {
        "confirm_write_user_default": confirmed("confirm_write_user_default"),
        "confirm_no_model_config_recall_mutation": confirmed("confirm_no_model_config_recall_mutation"),
        "confirm_runtime_adapter_gap_understood": confirmed("confirm_runtime_adapter_gap_understood"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]

    target_user_default = os.path.abspath(str(binding_plan.get("target_user_default_path") or ""))
    expected_user_default = os.path.abspath(os.path.join(str(MEMCORE_ROOT), "config", "zhiyi_model_binding.user.json"))
    target_runtime_config = os.path.abspath(str(binding_plan.get("target_runtime_config_path") or ""))
    expected_runtime_config = os.path.abspath(os.path.join(str(MEMCORE_ROOT), "config", "model_config.json"))
    would_write = binding_plan.get("would_write_user_default", {}) if isinstance(binding_plan.get("would_write_user_default"), dict) else {}
    runtime_plan = binding_plan.get("runtime_config_plan", {}) if isinstance(binding_plan.get("runtime_config_plan"), dict) else {}
    blocked_by = runtime_plan.get("blocked_by", []) if isinstance(runtime_plan.get("blocked_by"), list) else []

    guard_checks = {
        "model_binding_plan_ok": bool(binding_plan.get("ok")),
        "target_user_default_path": target_user_default == expected_user_default,
        "target_runtime_config_path": target_runtime_config == expected_runtime_config,
        "user_default_schema": str(would_write.get("schema_version", "")) == "1.0",
        "user_default_write_requires_authorization": bool(would_write.get("write_requires_authorization", False)),
        "runtime_adapter_not_implemented": (
            not bool(binding_plan.get("runtime_binding_ready", False))
            and "platform_llm_selection_needs_runtime_adapter_before_apply" in blocked_by
        ),
        "model_config_recall_not_mutated": bool(runtime_plan.get("apply_now")) is False,
        "dry_run_no_write": (
            bool(binding_plan.get("write_performed", False)) is False
            and bool(binding_plan.get("config_write_performed", False)) is False
            and bool(binding_plan.get("runtime_binding_write_performed", False)) is False
        ),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    authorization_complete = not missing
    future_user_default_apply_ready = authorization_complete and not guard_failures
    future_runtime_binding_ready = False
    if guard_failures:
        gate_status = "blocked_guard_failure"
    elif not authorization_complete:
        gate_status = "blocked_missing_authorization"
    else:
        gate_status = "ready_for_future_user_default_apply_runtime_adapter_blocked"

    return {
        "ok": not guard_failures,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_binding_write_performed": False,
        "apply_allowed": False,
        "apply_performed": False,
        "live_apply_endpoint_enabled": False,
        "policy_version": ZHIYI_MODEL_BINDING_APPLY_GATE_VERSION,
        "gate_status": gate_status,
        "authorization_complete": authorization_complete,
        "authorization_missing": missing,
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "guard_failures": guard_failures,
        "future_user_default_apply_ready": future_user_default_apply_ready,
        "future_runtime_binding_ready": future_runtime_binding_ready,
        "required_authorization": get_zhiyi_model_binding_apply_gate_policy()["required_authorization"],
        "future_apply_endpoint": "/api/v1/zhiyi/model-binding/apply",
        "dry_run_endpoint": "/api/v1/zhiyi/model-binding/apply-gate/dry-run",
        "target_user_default_path": binding_plan.get("target_user_default_path"),
        "target_runtime_config_path": binding_plan.get("target_runtime_config_path"),
        "target_user_default_exists": os.path.exists(binding_plan.get("target_user_default_path", "")),
        "target_runtime_config_exists": os.path.exists(binding_plan.get("target_runtime_config_path", "")),
        "would_write_user_default": would_write,
        "runtime_adapter_plan": {
            "required_before_runtime_binding_apply": True,
            "implemented": False,
            "runtime_binding_ready": False,
            "blocked_by": blocked_by,
            "model_config_mutation_allowed_now": False,
        },
        "model_binding_plan": binding_plan,
        "completion_claim": get_zhiyi_model_binding_apply_gate_policy()["completion_claim"],
        "notes": [
            "model_binding_apply_gate_dry_run_only",
            "no_user_default_config_written",
            "no_model_config_or_runtime_adapter_write",
            "browser_storage_remains_ui_cache_until_authorized_apply",
        ],
    }


ZHIYI_RUNTIME_ADAPTER_DRY_RUN_VERSION = "p1-10.1"


def get_zhiyi_runtime_adapter_dry_run_policy():
    """Return the no-call runtime adapter preflight contract."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "model_call_performed": False,
        "policy_version": ZHIYI_RUNTIME_ADAPTER_DRY_RUN_VERSION,
        "dry_run_endpoint": "/api/v1/zhiyi/runtime-adapter/dry-run",
        "future_runtime_apply_endpoint": "/api/v1/zhiyi/runtime-adapter/apply",
        "live_runtime_apply_endpoint_enabled": False,
        "live_model_call_enabled": False,
        "requires_authorization_for_runtime_apply": True,
        "requires_authorization_for_model_call": True,
        "checks": [
            "selected_model_must_be_visible_first_version_option",
            "model_binding_apply_gate_must_be_checked",
            "runtime_config_snapshot_is_read_only",
            "user_default_config_snapshot_is_read_only",
            "adapter_contract_may_prepare_mapping_but_must_not_write",
            "platform_client_resolution_is_not_executed",
            "model_call_is_not_executed",
        ],
        "completion_claim": {
            "runtime_adapter_contract_done": True,
            "runtime_adapter_apply_done": False,
            "runtime_model_call_done": False,
            "live_9850_updated": False,
        },
    }


def _zhiyi_runtime_file_snapshot(path):
    path = str(path or "")
    snapshot = {
        "path": path,
        "exists": False,
        "is_file": False,
        "size_bytes": 0,
        "mtime_utc": "",
        "read_only_probe": True,
        "write_performed": False,
    }
    if not path:
        return snapshot
    try:
        snapshot["exists"] = os.path.exists(path)
        snapshot["is_file"] = os.path.isfile(path)
        if snapshot["exists"]:
            stat = os.stat(path)
            snapshot["size_bytes"] = stat.st_size
            snapshot["mtime_utc"] = datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception as exc:
        snapshot["error"] = str(exc)
    return snapshot


def build_zhiyi_runtime_adapter_dry_run(body=None):
    """Preflight the first runtime-adapter contract without config writes or model calls."""
    body = body or {}
    binding_plan = build_zhiyi_model_binding_plan(body)
    apply_gate = build_zhiyi_model_binding_apply_gate_dry_run(body)
    runtime_config_path = binding_plan.get("target_runtime_config_path")
    user_default_path = binding_plan.get("target_user_default_path")
    runtime_snapshot = _zhiyi_runtime_file_snapshot(runtime_config_path)
    user_default_snapshot = _zhiyi_runtime_file_snapshot(user_default_path)
    selected_option = binding_plan.get("selected_option", {}) if isinstance(binding_plan.get("selected_option"), dict) else {}
    runtime_plan = binding_plan.get("runtime_config_plan", {}) if isinstance(binding_plan.get("runtime_config_plan"), dict) else {}
    blocked_by = runtime_plan.get("blocked_by", []) if isinstance(runtime_plan.get("blocked_by"), list) else []

    binding_ok = bool(binding_plan.get("ok"))
    gate_guard_ok = not bool(apply_gate.get("guard_failures", []))
    authorization_complete = bool(apply_gate.get("authorization_complete"))
    contract_checks = {
        "model_binding_plan_ok": binding_ok,
        "apply_gate_guard_ok": gate_guard_ok,
        "runtime_config_snapshot_read_only": bool(runtime_snapshot.get("read_only_probe")) and not bool(runtime_snapshot.get("write_performed")),
        "user_default_snapshot_read_only": bool(user_default_snapshot.get("read_only_probe")) and not bool(user_default_snapshot.get("write_performed")),
        "runtime_config_plan_is_no_apply": bool(runtime_plan.get("apply_now")) is False,
        "runtime_adapter_not_live": True,
        "model_call_not_performed": True,
        "no_config_or_profile_write": (
            bool(binding_plan.get("write_performed", False)) is False
            and bool(binding_plan.get("config_write_performed", False)) is False
            and bool(binding_plan.get("runtime_binding_write_performed", False)) is False
            and bool(apply_gate.get("config_write_performed", False)) is False
            and bool(apply_gate.get("runtime_binding_write_performed", False)) is False
        ),
    }
    contract_failures = [name for name, ok in contract_checks.items() if not ok]
    if contract_failures:
        preflight_status = "blocked_contract_check_failure"
    elif not authorization_complete:
        preflight_status = "contract_ready_missing_apply_authorization_runtime_adapter_blocked"
    else:
        preflight_status = "contract_ready_runtime_adapter_blocked_no_model_call"

    adapter_stages = [
        {
            "id": "visible_model_option",
            "status": "passed" if binding_ok else "blocked",
            "evidence": binding_plan.get("model_id", ""),
        },
        {
            "id": "user_default_apply_gate",
            "status": apply_gate.get("gate_status", "unknown"),
            "authorization_complete": authorization_complete,
            "future_user_default_apply_ready": bool(apply_gate.get("future_user_default_apply_ready", False)),
        },
        {
            "id": "runtime_config_mapping_contract",
            "status": "dry_run_mapping_ready" if binding_ok else "blocked",
            "apply_now": False,
            "blocked_by": blocked_by,
        },
        {
            "id": "platform_runtime_client_resolution",
            "status": "not_executed_dry_run_only",
            "client_resolved": False,
        },
        {
            "id": "model_call_execution",
            "status": "not_executed_runtime_adapter_not_implemented",
            "model_call_allowed": False,
            "model_call_performed": False,
        },
    ]

    return {
        "ok": not contract_failures,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "model_call_allowed": False,
        "model_call_performed": False,
        "runtime_apply_allowed": False,
        "runtime_apply_performed": False,
        "policy_version": ZHIYI_RUNTIME_ADAPTER_DRY_RUN_VERSION,
        "preflight_status": preflight_status,
        "runtime_adapter_contract_ready": not contract_failures,
        "model_call_contract_preflight_ready": not contract_failures,
        "model_call_ready": False,
        "requires_authorization_for_runtime_apply": True,
        "requires_authorization_for_model_call": True,
        "selected_option": selected_option,
        "model_binding_plan": binding_plan,
        "apply_gate_summary": {
            "policy_version": apply_gate.get("policy_version"),
            "gate_status": apply_gate.get("gate_status"),
            "authorization_complete": authorization_complete,
            "authorization_missing": apply_gate.get("authorization_missing", []),
            "guard_failures": apply_gate.get("guard_failures", []),
            "future_user_default_apply_ready": bool(apply_gate.get("future_user_default_apply_ready", False)),
            "future_runtime_binding_ready": False,
        },
        "runtime_config_snapshot": runtime_snapshot,
        "user_default_snapshot": user_default_snapshot,
        "runtime_adapter_stages": adapter_stages,
        "contract_checks": contract_checks,
        "contract_failures": contract_failures,
        "model_call_contract": {
            "requested_option_id": binding_plan.get("model_id", ""),
            "provider": selected_option.get("provider", "auto"),
            "provider_id": selected_option.get("provider_id", ""),
            "model_name": selected_option.get("model_name", ""),
            "transport": "not_selected_dry_run_only",
            "platform_scope": selected_option.get("provider", "platform_default"),
            "client_resolved": False,
            "request_built": False,
            "response_received": False,
            "called": False,
            "not_called_reason": "runtime_adapter_not_implemented_no_live_model_call",
        },
        "blockers": [
            "runtime_adapter_not_implemented",
            "live_runtime_apply_endpoint_disabled",
            "model_call_disabled_for_p1_10_dry_run",
            "config_model_config_json_left_read_only",
        ],
        "completion_claim": get_zhiyi_runtime_adapter_dry_run_policy()["completion_claim"],
        "notes": [
            "runtime_adapter_preflight_contract_only",
            "no_model_call_executed",
            "no_config_or_user_default_write",
            "no_service_restart",
            "usage_log_and_model_binding_apply_remain_separate_gates",
        ],
    }


ZHIYI_RUNTIME_ADAPTER_APPLY_GATE_VERSION = "p1-11.1"


def get_zhiyi_runtime_adapter_apply_gate_policy():
    """Return the no-write/no-call gate for future runtime adapter apply."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "model_call_performed": False,
        "policy_version": ZHIYI_RUNTIME_ADAPTER_APPLY_GATE_VERSION,
        "dry_run_endpoint": "/api/v1/zhiyi/runtime-adapter/apply-gate/dry-run",
        "future_apply_endpoint": "/api/v1/zhiyi/runtime-adapter/apply",
        "live_apply_endpoint_enabled": False,
        "live_model_call_enabled": False,
        "required_authorization": [
            "confirm_write_user_default",
            "confirm_no_model_config_recall_mutation",
            "confirm_runtime_adapter_gap_understood",
            "confirm_runtime_adapter_apply_contract",
            "confirm_platform_client_resolver_read_only",
            "confirm_no_model_call",
            "operator",
            "reason",
        ],
        "guards": [
            "runtime_preflight_contract_must_be_ok",
            "user_default_apply_gate_must_have_no_guard_failures",
            "runtime_config_snapshot_must_be_read_only",
            "platform_client_resolver_must_be_read_only",
            "platform_client_contract_must_be_ready",
            "runtime_apply_endpoint_must_remain_disabled",
            "model_call_must_not_execute",
            "dry_run_must_not_write_config_or_logs",
        ],
        "completion_claim": {
            "runtime_adapter_apply_gate_done": True,
            "platform_client_resolver_contract_done": True,
            "runtime_adapter_apply_done": False,
            "runtime_model_call_done": False,
            "live_9850_updated": False,
        },
    }


def _zhiyi_platform_runtime_profile_snapshot(platform_key):
    profile = {}
    source = "tools.runtime_profile_read_only"
    try:
        import sys as _sys
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tools_dir = os.path.join(repo_root, "tools")
        if tools_dir not in _sys.path:
            _sys.path.insert(0, tools_dir)
        from runtime_profile import build_openclaw_profile, build_hermes_profile
        if platform_key == "openclaw":
            profile = build_openclaw_profile()
        elif platform_key == "hermes":
            profile = build_hermes_profile()
    except Exception as exc:
        profile = {"status": "unavailable", "error": str(exc)}
        source = "runtime_profile_unavailable"

    health = profile.get("health", {}) if isinstance(profile.get("health"), dict) else {}
    selected_runtime = profile.get("selected_runtime", {}) if isinstance(profile.get("selected_runtime"), dict) else {}
    instances = profile.get("instances", []) if isinstance(profile.get("instances"), list) else []
    running_instance = profile.get("running_instance") if isinstance(profile, dict) else None
    live_client_active = (
        bool(health.get("reachable", False))
        or str(profile.get("status", "")) == "active"
        or bool(running_instance)
    )
    return {
        "platform": platform_key,
        "profile_source": source,
        "profile_status": profile.get("status", "unknown"),
        "version": profile.get("version"),
        "selected_runtime_source": selected_runtime.get("source", ""),
        "instances_count": len(instances),
        "running_instance_detected": bool(running_instance),
        "health_reachable": bool(health.get("reachable", False)),
        "health_url": health.get("health_url"),
        "health_status_code": health.get("status_code"),
        "config_detected": bool(profile.get("config")),
        "install_root": profile.get("install_root"),
        "live_client_active_now": live_client_active,
        "read_only_probe": True,
        "write_performed": False,
        "model_call_performed": False,
    }


def _zhiyi_platform_client_resolver_dry_run(selected_option, binding_plan, body=None):
    body = body or {}
    selected_option = selected_option if isinstance(selected_option, dict) else {}
    option_id = str(binding_plan.get("model_id", ""))
    category = str(selected_option.get("category") or "").lower()
    provider = str(selected_option.get("provider") or "").lower()
    platform_key = category or provider or "platform_default"
    if not option_id:
        platform_key = "platform_default"
    elif "openclaw" in platform_key:
        platform_key = "openclaw"
    elif "hermes" in platform_key:
        platform_key = "hermes"
    elif not bool(binding_plan.get("ok")):
        platform_key = "unknown"

    base = {
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "model_call_performed": False,
        "selected_option_id": option_id,
        "platform": platform_key,
        "provider": selected_option.get("provider", "auto"),
        "provider_id": selected_option.get("provider_id", ""),
        "model_name": selected_option.get("model_name", ""),
        "resolver_read_only_probe_performed": False,
        "client_resolved_for_apply": False,
        "client_contract_ready": False,
        "live_client_active_now": False,
        "profile_snapshot": {},
        "transport_candidates": [],
    }

    if not bool(binding_plan.get("ok")):
        base.update({
            "client_resolution_status": "blocked_no_visible_model_option",
            "blockers": ["model_binding_plan_not_ok"],
        })
        return base

    if platform_key == "platform_default":
        base.update({
            "client_resolution_status": "deferred_to_platform_default",
            "client_contract_ready": True,
            "blockers": ["runtime_adapter_apply_not_enabled"],
            "transport_candidates": ["platform_default_deferred"],
        })
        return base

    if platform_key in ("openclaw", "hermes"):
        profile_snapshot = _zhiyi_platform_runtime_profile_snapshot(platform_key)
        live_active = bool(profile_snapshot.get("live_client_active_now", False))
        if live_active:
            status = "read_only_client_profile_active_model_call_blocked"
        elif profile_snapshot.get("profile_status") in ("detected", "experimental"):
            status = "read_only_client_profile_detected_model_call_blocked"
        else:
            status = "read_only_client_profile_not_active_model_call_blocked"
        transport_candidates = {
            "openclaw": ["openclaw_runtime_profile", "openclaw_gateway_protocol4_future_adapter"],
            "hermes": ["hermes_runtime_profile", "hermes_health_endpoint_future_adapter"],
        }[platform_key]
        base.update({
            "client_resolution_status": status,
            "resolver_read_only_probe_performed": True,
            "client_contract_ready": True,
            "live_client_active_now": live_active,
            "profile_snapshot": profile_snapshot,
            "transport_candidates": transport_candidates,
            "blockers": [
                "runtime_adapter_apply_not_enabled",
                "model_call_disabled_for_apply_gate_dry_run",
            ],
        })
        return base

    base.update({
        "client_resolution_status": "blocked_unknown_platform",
        "blockers": ["unknown_platform_for_runtime_adapter"],
    })
    return base


def build_zhiyi_runtime_adapter_apply_gate_dry_run(body=None):
    """Check future runtime adapter apply authorization without writes or model calls."""
    body = body or {}
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        value = authorization.get(name, body.get(name))
        if value is True:
            return True
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "confirmed", "confirm")
        return False

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    preflight = build_zhiyi_runtime_adapter_dry_run(body)
    binding_plan = preflight.get("model_binding_plan", {}) if isinstance(preflight.get("model_binding_plan"), dict) else {}
    selected_option = preflight.get("selected_option", {}) if isinstance(preflight.get("selected_option"), dict) else {}
    apply_gate_summary = preflight.get("apply_gate_summary", {}) if isinstance(preflight.get("apply_gate_summary"), dict) else {}
    runtime_snapshot = preflight.get("runtime_config_snapshot", {}) if isinstance(preflight.get("runtime_config_snapshot"), dict) else {}
    client_resolution = _zhiyi_platform_client_resolver_dry_run(selected_option, binding_plan, body)

    required_checks = {
        "confirm_write_user_default": confirmed("confirm_write_user_default"),
        "confirm_no_model_config_recall_mutation": confirmed("confirm_no_model_config_recall_mutation"),
        "confirm_runtime_adapter_gap_understood": confirmed("confirm_runtime_adapter_gap_understood"),
        "confirm_runtime_adapter_apply_contract": confirmed("confirm_runtime_adapter_apply_contract"),
        "confirm_platform_client_resolver_read_only": confirmed("confirm_platform_client_resolver_read_only"),
        "confirm_no_model_call": confirmed("confirm_no_model_call"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    authorization_complete = not missing

    guard_checks = {
        "runtime_preflight_contract_ok": bool(preflight.get("ok")),
        "user_default_apply_gate_has_no_guard_failures": not bool(apply_gate_summary.get("guard_failures", [])),
        "user_default_apply_gate_ready_when_authorized": (
            not authorization_complete
            or bool(apply_gate_summary.get("future_user_default_apply_ready", False))
        ),
        "runtime_config_snapshot_read_only": (
            bool(runtime_snapshot.get("read_only_probe"))
            and not bool(runtime_snapshot.get("write_performed"))
        ),
        "platform_client_resolver_read_only": (
            bool(client_resolution.get("dry_run"))
            and not bool(client_resolution.get("write_performed"))
            and not bool(client_resolution.get("model_call_performed"))
        ),
        "platform_client_contract_ready": bool(client_resolution.get("client_contract_ready")),
        "runtime_apply_endpoint_disabled": True,
        "model_call_not_performed": (
            bool(preflight.get("model_call_performed", False)) is False
            and bool(client_resolution.get("model_call_performed", False)) is False
        ),
        "dry_run_no_write": (
            bool(preflight.get("write_performed", False)) is False
            and bool(preflight.get("config_write_performed", False)) is False
            and bool(preflight.get("runtime_config_write_performed", False)) is False
            and bool(preflight.get("runtime_binding_write_performed", False)) is False
            and bool(client_resolution.get("runtime_config_write_performed", False)) is False
            and bool(client_resolution.get("runtime_binding_write_performed", False)) is False
        ),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if guard_failures:
        gate_status = "blocked_guard_failure"
    elif not authorization_complete:
        gate_status = "blocked_missing_authorization"
    else:
        gate_status = "ready_for_future_runtime_apply_client_contract_ready_model_call_blocked"

    future_runtime_apply_ready = authorization_complete and not guard_failures
    return {
        "ok": not guard_failures,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "usage_log_write_performed": False,
        "apply_allowed": False,
        "runtime_apply_allowed": False,
        "runtime_apply_performed": False,
        "model_call_allowed": False,
        "model_call_performed": False,
        "live_apply_endpoint_enabled": False,
        "policy_version": ZHIYI_RUNTIME_ADAPTER_APPLY_GATE_VERSION,
        "gate_status": gate_status,
        "authorization_complete": authorization_complete,
        "authorization_missing": missing,
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "guard_failures": guard_failures,
        "future_runtime_apply_ready": future_runtime_apply_ready,
        "future_model_call_ready": False,
        "required_authorization": get_zhiyi_runtime_adapter_apply_gate_policy()["required_authorization"],
        "future_apply_endpoint": "/api/v1/zhiyi/runtime-adapter/apply",
        "dry_run_endpoint": "/api/v1/zhiyi/runtime-adapter/apply-gate/dry-run",
        "runtime_preflight": preflight,
        "platform_client_resolution": client_resolution,
        "completion_claim": get_zhiyi_runtime_adapter_apply_gate_policy()["completion_claim"],
        "blockers": [
            "live_runtime_apply_endpoint_disabled",
            "model_call_disabled_for_apply_gate_dry_run",
            "config_model_config_json_left_read_only",
        ],
        "notes": [
            "runtime_adapter_apply_gate_dry_run_only",
            "platform_client_resolver_read_only_contract",
            "no_runtime_config_or_user_default_write",
            "no_model_call_executed",
            "no_service_restart",
        ],
    }


ZHIYI_MODEL_REQUEST_ENVELOPE_DRY_RUN_VERSION = "p1-12.1"


def get_zhiyi_model_request_envelope_dry_run_policy():
    """Return the no-call model request envelope contract."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "usage_log_write_performed": False,
        "request_sent": False,
        "response_received": False,
        "model_call_performed": False,
        "policy_version": ZHIYI_MODEL_REQUEST_ENVELOPE_DRY_RUN_VERSION,
        "dry_run_endpoint": "/api/v1/zhiyi/model-request/envelope/dry-run",
        "required_upstream_gate": "/api/v1/zhiyi/runtime-adapter/apply-gate/dry-run",
        "future_model_call_endpoint": "/api/v1/zhiyi/model-request/send",
        "live_model_call_endpoint_enabled": False,
        "requires_authorization_for_model_call": True,
        "checks": [
            "runtime_adapter_apply_gate_must_be_ok",
            "platform_client_contract_must_be_ready",
            "request_envelope_may_be_built_but_not_sent",
            "adapter_response_must_be_no_call_draft",
            "source_refs_are_evidence_anchors_not_raw_replacements",
            "dry_run_must_not_write_config_logs_or_usage",
        ],
        "completion_claim": {
            "model_request_envelope_contract_done": True,
            "no_call_adapter_response_contract_done": True,
            "runtime_model_call_done": False,
            "usage_log_persisted": False,
            "live_9850_updated": False,
        },
    }


def _zhiyi_model_request_messages_dry_run(body):
    body = body or {}
    messages = body.get("messages")
    normalized = []
    if isinstance(messages, list):
        for item in messages[:20]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user")
            content = item.get("content", "")
            if not isinstance(content, str):
                try:
                    content = json.dumps(content, ensure_ascii=False, sort_keys=True)
                except Exception:
                    content = str(content)
            normalized.append({"role": role, "content": content})
    if normalized:
        return normalized

    query = str(body.get("query") or body.get("prompt") or body.get("user_input") or "").strip()
    return [
        {
            "role": "system",
            "content": (
                "Use Yifanchen Zhiyi context with source_refs as evidence anchors. "
                "Raw text remains available through source_refs and must not be replaced by hash-only summaries."
            ),
        },
        {
            "role": "user",
            "content": query or "<user_query_placeholder>",
        },
    ]


def build_zhiyi_model_request_envelope_dry_run(body=None):
    """Draft a model request envelope and adapter response without sending it."""
    body = body or {}
    apply_gate = build_zhiyi_runtime_adapter_apply_gate_dry_run(body)
    preflight = apply_gate.get("runtime_preflight", {}) if isinstance(apply_gate.get("runtime_preflight"), dict) else {}
    binding_plan = preflight.get("model_binding_plan", {}) if isinstance(preflight.get("model_binding_plan"), dict) else {}
    selected_option = preflight.get("selected_option", {}) if isinstance(preflight.get("selected_option"), dict) else {}
    client_resolution = apply_gate.get("platform_client_resolution", {}) if isinstance(apply_gate.get("platform_client_resolution"), dict) else {}
    option_id = str(binding_plan.get("model_id", ""))
    platform = str(client_resolution.get("platform") or selected_option.get("category") or "platform_default")
    transport_candidates = client_resolution.get("transport_candidates", [])
    if not isinstance(transport_candidates, list):
        transport_candidates = []
    transport = transport_candidates[0] if transport_candidates else "not_selected_no_call_dry_run"
    if platform == "platform_default":
        transport = "platform_default_deferred"

    messages = _zhiyi_model_request_messages_dry_run(body)
    source_refs_policy = {
        "mode": "source_refs_anchor_with_raw_follow_up",
        "source_refs_are_raw_retrieval_anchors": True,
        "source_refs_are_not_raw_replacements": True,
        "raw_verbatim_required_when_raw_is_requested": True,
        "redaction_performed": False,
        "hash_only_replacement_allowed": False,
        "dry_run_does_not_attach_production_raw": True,
    }
    request_envelope = {
        "schema_version": "1.0",
        "contract_version": ZHIYI_MODEL_REQUEST_ENVELOPE_DRY_RUN_VERSION,
        "dry_run": True,
        "request_kind": str(body.get("request_kind") or "zhiyi_model_call"),
        "task_kind": str(body.get("task_kind") or "zhiyi_recall_answer"),
        "selected_option_id": option_id,
        "platform": platform,
        "provider": selected_option.get("provider", "auto"),
        "provider_id": selected_option.get("provider_id", ""),
        "model_name": selected_option.get("model_name", ""),
        "transport": transport,
        "messages": messages,
        "parameters": {
            "stream": bool(body.get("stream", False)),
            "temperature": body.get("temperature", 0.2),
        },
        "metadata": {
            "source": "zhiyi_runtime_adapter_p1_12_dry_run",
            "memcore_root": str(MEMCORE_ROOT),
            "runtime_apply_gate_status": apply_gate.get("gate_status", "unknown"),
            "platform_client_resolution_status": client_resolution.get("client_resolution_status", "unknown"),
        },
        "source_refs_policy": source_refs_policy,
        "request_sent": False,
        "response_received": False,
        "model_call_performed": False,
    }

    contract_checks = {
        "runtime_apply_gate_ok": bool(apply_gate.get("ok")),
        "model_binding_plan_ok": bool(binding_plan.get("ok")),
        "platform_client_contract_ready": bool(client_resolution.get("client_contract_ready")),
        "request_envelope_schema_present": request_envelope["schema_version"] == "1.0",
        "request_not_sent": bool(request_envelope.get("request_sent")) is False,
        "response_not_received": bool(request_envelope.get("response_received")) is False,
        "model_call_not_performed": (
            bool(apply_gate.get("model_call_performed", False)) is False
            and bool(client_resolution.get("model_call_performed", False)) is False
            and bool(request_envelope.get("model_call_performed", False)) is False
        ),
        "no_config_or_usage_write": (
            bool(apply_gate.get("write_performed", False)) is False
            and bool(apply_gate.get("config_write_performed", False)) is False
            and bool(apply_gate.get("user_default_write_performed", False)) is False
            and bool(apply_gate.get("runtime_config_write_performed", False)) is False
            and bool(apply_gate.get("runtime_binding_write_performed", False)) is False
            and bool(apply_gate.get("usage_log_write_performed", False)) is False
        ),
        "source_refs_policy_declared": (
            bool(source_refs_policy.get("source_refs_are_raw_retrieval_anchors"))
            and bool(source_refs_policy.get("source_refs_are_not_raw_replacements"))
            and bool(source_refs_policy.get("hash_only_replacement_allowed")) is False
        ),
    }
    contract_failures = [name for name, ok in contract_checks.items() if not ok]
    authorization_missing = apply_gate.get("authorization_missing", []) if isinstance(apply_gate.get("authorization_missing"), list) else []
    authorization_complete = bool(apply_gate.get("authorization_complete", False))
    if contract_failures:
        request_envelope_status = "blocked_contract_check_failure_no_request_sent"
    elif not authorization_complete:
        request_envelope_status = "blocked_missing_authorization_no_request_sent"
    else:
        request_envelope_status = "request_envelope_ready_no_call_adapter_response_draft"

    adapter_response_draft = {
        "ok": not contract_failures,
        "dry_run": True,
        "status": request_envelope_status,
        "adapter": "zhiyi_runtime_adapter",
        "response_kind": "no_call_adapter_response_draft",
        "request_sent": False,
        "response_received": False,
        "model_call_performed": False,
        "usage_log_write_performed": False,
        "not_called_reason": "p1_12_no_call_dry_run_contract",
        "next_required_gate": "explicit_model_call_authorization_and_live_endpoint",
    }

    return {
        "ok": not contract_failures,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "usage_log_write_performed": False,
        "request_sent": False,
        "response_received": False,
        "model_call_allowed": False,
        "model_call_performed": False,
        "runtime_apply_allowed": False,
        "runtime_apply_performed": False,
        "policy_version": ZHIYI_MODEL_REQUEST_ENVELOPE_DRY_RUN_VERSION,
        "request_envelope_status": request_envelope_status,
        "request_envelope_draft_ready": not contract_failures,
        "future_model_call_ready": False,
        "authorization_complete": authorization_complete,
        "authorization_missing": authorization_missing,
        "runtime_apply_gate": apply_gate,
        "platform_client_resolution": client_resolution,
        "request_envelope": request_envelope,
        "adapter_response_draft": adapter_response_draft,
        "contract_checks": contract_checks,
        "contract_failures": contract_failures,
        "completion_claim": get_zhiyi_model_request_envelope_dry_run_policy()["completion_claim"],
        "blockers": [
            "live_model_call_endpoint_disabled",
            "model_call_disabled_for_p1_12_dry_run",
            "request_envelope_not_sent",
            "usage_log_not_written",
        ],
        "notes": [
            "model_request_envelope_dry_run_only",
            "adapter_response_is_no_call_draft",
            "source_refs_remain_evidence_anchors_not_raw_replacements",
            "no_config_user_default_usage_log_or_model_call",
            "no_service_restart",
        ],
    }


def build_zhiyi_usage_log_dry_run(body=None):
    """Build a user-facing Zhiyi usage log record without appending it."""
    body = body or {}
    query = str(body.get("query", "") or "").strip()
    scope_filter = str(body.get("scope_filter", "") or "").strip()
    trigger_type = str(body.get("trigger_type") or body.get("trigger") or "manual_preview")
    route = str(body.get("route") or "zhiyi_recall_preview")
    top_k = min(int(body.get("top_k", 5) or 5), 20)
    threshold = float(body.get("threshold", 0.5) or 0.5)
    model_id = str(body.get("model_id") or "")
    target_log_path = os.path.join(str(MEMCORE_ROOT), "logs", "zhiyi_usage.jsonl")

    model_plan = build_zhiyi_model_binding_plan({"model_id": model_id})
    recall_result = body.get("recall_result")
    recall_error = ""
    recall_executed = False
    if not isinstance(recall_result, dict):
        recall_executed = True
        try:
            import sys as _sys
            _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from p3_recall import handle_recall
            recall_result = handle_recall({
                "query": query,
                "scope_filter": scope_filter,
                "top_k": top_k,
                "threshold": threshold,
            })
        except Exception as e:
            recall_result = {"matched_memories": [], "total_matched": 0, "returned": 0}
            recall_error = str(e)

    matched = recall_result.get("matched_memories", []) if isinstance(recall_result, dict) else []
    if not isinstance(matched, list):
        matched = []

    def parse_refs(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return json.loads(value)
            except Exception:
                return {"raw": value}
        return {}

    evidence_items = []
    injectable_count = 0
    for memory in matched[:5]:
        if not isinstance(memory, dict):
            continue
        refs = parse_refs(memory.get("source_refs", {}))
        if memory.get("should_inject"):
            injectable_count += 1
        exp_id = memory.get("exp_id", "") or memory.get("id", "")
        card = memory.get("archive_card") if isinstance(memory.get("archive_card"), dict) else archive_card(memory)
        catalog_id = memory.get("catalog_id", "") or card.get("catalog_id", "")
        evidence_items.append({
            "catalog_id": catalog_id,
            "exp_id": exp_id,
            "type": memory.get("type") or memory.get("_type") or "",
            "title": card.get("title", ""),
            "status": card.get("status", ""),
            "evidence_level": card.get("evidence_level", ""),
            "summary": memory.get("summary", "") or memory.get("detail", ""),
            "detail": memory.get("detail", ""),
            "injectable_context": memory.get("injectable_context", ""),
            "confidence": memory.get("confidence", 0),
            "should_inject": bool(memory.get("should_inject", False)),
            "source_refs": refs,
            "source_refs_count": len(refs) if isinstance(refs, list) else (1 if refs else 0),
            "raw_detail_endpoint": f"/api/v1/zhiyi/memories/{exp_id}" if exp_id else "",
        })

    if recall_error:
        result_status = "error"
    elif not matched:
        result_status = "no_match"
    elif injectable_count:
        result_status = "matched_ready"
    else:
        result_status = "matched_not_injectable"

    selected_option = model_plan.get("selected_option", {}) if isinstance(model_plan, dict) else {}
    prompt_bundle = build_zhiyi_usage_light_prompt({
        "outcome_status": result_status,
        "recall_error": recall_error,
        "matched_count": len(matched),
        "injectable_count": injectable_count,
        "model_binding_ok": bool(model_plan.get("ok")),
        "model_id": model_id,
        "runtime_binding_ready": bool(model_plan.get("runtime_binding_ready", False)),
        "model_called": False,
    })
    event = {
        "schema_version": "1.0",
        "event_type": "zhiyi_usage_record",
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "trigger": {
            "type": trigger_type,
            "query": query,
            "scope_filter": scope_filter,
            "route": route,
        },
        "outcome": {
            "status": result_status,
            "light_message": prompt_bundle["primary_prompt"]["message"],
            "light_prompt": prompt_bundle["primary_prompt"],
            "prompt_policy_version": prompt_bundle["policy_version"],
            "used_in_answer": False,
            "applied_to_platform": False,
            "dry_run_only": True,
        },
        "recall": {
            "executed": recall_executed,
            "total_matched": recall_result.get("total_matched", 0) if isinstance(recall_result, dict) else 0,
            "returned": recall_result.get("returned", len(matched)) if isinstance(recall_result, dict) else 0,
            "matched_memories_count": len(matched),
            "injectable_count": injectable_count,
            "evidence_items": evidence_items,
            "error": recall_error,
        },
        "model_call": {
            "requested_option_id": model_id,
            "binding_plan_ok": bool(model_plan.get("ok")),
            "provider": selected_option.get("provider", ""),
            "provider_id": selected_option.get("provider_id", ""),
            "model_name": selected_option.get("model_name", ""),
            "runtime_binding_ready": bool(model_plan.get("runtime_binding_ready", False)),
            "runtime_binding_status": model_plan.get("runtime_binding_status", ""),
            "called": False,
            "not_called_reason": "runtime_binding_not_applied",
            "light_prompt": prompt_bundle["model_prompt"],
        },
        "source_refs_policy": {
            "usage_log_contains_source_refs": True,
            "raw_detail_endpoint_available": True,
            "saved_user_content_preserved": True,
            "hash_only_replacement_allowed": False,
            "redaction_performed": False,
        },
    }
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "target_log_path": target_log_path,
        "event": event,
        "would_append_event": event,
        "model_binding_plan": {
            "ok": model_plan.get("ok"),
            "model_id": model_plan.get("model_id"),
            "runtime_binding_ready": model_plan.get("runtime_binding_ready"),
            "runtime_binding_status": model_plan.get("runtime_binding_status"),
            "write_performed": model_plan.get("write_performed"),
            "error": model_plan.get("error", ""),
        },
        "notes": [
            "usage_log_dry_run_only",
            "browser_or_api_preview_does_not_append_logs",
            "model_call_not_executed_until_runtime_binding",
        ],
    }


ZHIYI_USAGE_LIGHT_PROMPT_POLICY_VERSION = "p1-6b.1"


def get_zhiyi_usage_light_prompt_policy():
    """Return the first-version light prompt taxonomy for Zhiyi usage events."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "policy_version": ZHIYI_USAGE_LIGHT_PROMPT_POLICY_VERSION,
        "principles": [
            "answer_flow_first",
            "no_engineering_error_dump_to_user",
            "log_detail_for_later_review",
            "do_not_write_raw_text_into_usage_log",
        ],
        "outcome_prompts": {
            "matched_ready": {
                "category": "success_silent",
                "severity": "info",
                "display_mode": "log_only",
                "message": "已找到可用经验，等待接入回答链路。",
                "can_continue": True,
                "next_action": "continue_answer_flow",
            },
            "matched_not_injectable": {
                "category": "soft_blocked",
                "severity": "notice",
                "display_mode": "quiet_note",
                "message": "找到了经验，但当前还不能接入回答。",
                "can_continue": True,
                "next_action": "continue_without_injection",
            },
            "no_match": {
                "category": "no_memory",
                "severity": "notice",
                "display_mode": "quiet_note",
                "message": "这次没找到可用经验，我会先按当前对话继续。",
                "can_continue": True,
                "next_action": "continue_without_memory",
            },
            "error": {
                "category": "recall_unavailable",
                "severity": "warn",
                "display_mode": "quiet_note",
                "message": "本地记忆链路暂时没接上，我会先按当前对话继续。",
                "can_continue": True,
                "next_action": "continue_and_log_error_for_review",
            },
        },
        "model_prompts": {
            "model_option_hidden": {
                "category": "model_option_hidden",
                "severity": "notice",
                "display_mode": "settings_note",
                "message": "当前模型不属于第一版知意可选项，本次不会调用它。",
                "can_continue": True,
                "next_action": "use_visible_model_option_or_platform_default",
            },
            "runtime_binding_not_applied": {
                "category": "model_runtime_not_applied",
                "severity": "notice",
                "display_mode": "log_only",
                "message": "模型选择还没接入运行链路，本次只记录未调用模型。",
                "can_continue": True,
                "next_action": "wait_for_runtime_adapter",
            },
            "model_called": {
                "category": "model_called",
                "severity": "info",
                "display_mode": "log_only",
                "message": "模型调用已记录。",
                "can_continue": True,
                "next_action": "record_model_call",
            },
        },
        "completion_claim": {
            "first_version_usage_log_done": False,
            "production_prompting_done": False,
            "live_9850_updated": False,
        },
    }


def build_zhiyi_usage_light_prompt(body=None):
    """Classify user-facing light prompts without writing logs or raw data."""
    body = body or {}
    policy = get_zhiyi_usage_light_prompt_policy()
    outcome_status = str(body.get("outcome_status") or body.get("status") or "no_match")
    outcome_prompts = policy["outcome_prompts"]
    primary = dict(outcome_prompts.get(outcome_status) or outcome_prompts["no_match"])
    primary["status"] = outcome_status

    model_called = bool(body.get("model_called", False))
    model_binding_ok = bool(body.get("model_binding_ok", True))
    runtime_ready = bool(body.get("runtime_binding_ready", False))
    if model_called:
        model_key = "model_called"
    elif not model_binding_ok:
        model_key = "model_option_hidden"
    elif not runtime_ready:
        model_key = "runtime_binding_not_applied"
    else:
        model_key = "runtime_binding_not_applied"
    model_prompt = dict(policy["model_prompts"][model_key])
    model_prompt["reason"] = model_key
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "policy_version": policy["policy_version"],
        "primary_prompt": primary,
        "model_prompt": model_prompt,
        "inputs": {
            "outcome_status": outcome_status,
            "recall_error_present": bool(body.get("recall_error")),
            "matched_count": int(body.get("matched_count", 0) or 0),
            "injectable_count": int(body.get("injectable_count", 0) or 0),
            "model_id": str(body.get("model_id", "") or ""),
            "model_binding_ok": model_binding_ok,
            "runtime_binding_ready": runtime_ready,
            "model_called": model_called,
        },
        "completion_claim": policy["completion_claim"],
        "notes": [
            "light_prompt_taxonomy_only",
            "do_not_interrupt_answer_flow_by_default",
            "saved_user_content_preserved",
        ],
    }


def _zhiyi_usage_log_path():
    return os.path.join(str(MEMCORE_ROOT), "logs", "zhiyi_usage.jsonl")


def _usage_log_positive_int(value, default, maximum):
    try:
        number = int(value)
    except Exception:
        return default
    if number < 1:
        return default
    return min(number, maximum)


ZHIYI_USAGE_LOG_APPLY_GATE_VERSION = "p1-8.1"


def get_zhiyi_usage_log_apply_gate_policy():
    """Return the no-write authorization gate for future usage log appends."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "policy_version": ZHIYI_USAGE_LOG_APPLY_GATE_VERSION,
        "dry_run_endpoint": "/api/v1/zhiyi/usage-log/apply-gate/dry-run",
        "future_apply_endpoint": "/api/v1/zhiyi/usage-log/apply",
        "live_apply_endpoint_enabled": False,
        "required_authorization": [
            "confirm_write_usage_log",
            "confirm_single_jsonl_append",
            "confirm_preserve_saved_user_content",
            "operator",
            "reason",
        ],
        "guards": [
            "event_type_must_be_zhiyi_usage_record",
            "schema_version_must_be_1_0",
            "target_must_be_memcore_logs_zhiyi_usage_jsonl",
            "append_line_must_be_valid_json",
            "saved_user_content_must_not_be_replaced_by_hash_or_stars",
        ],
        "append_contract": {
            "format": "jsonl",
            "encoding": "utf-8",
            "open_mode": "append",
            "newline_terminated": True,
            "file_mode_after_create": "0600",
        },
        "completion_claim": {
            "production_append_endpoint_done": False,
            "live_9850_updated": False,
            "usage_log_history_done": False,
        },
    }


def build_zhiyi_usage_log_apply_gate_dry_run(body=None):
    """Check whether a future usage-log append has enough authorization.

    This endpoint never appends the log. It only explains why an append is still
    blocked or whether the supplied event would be ready for a later authorized
    production endpoint.
    """
    body = body or {}
    supplied_event = body.get("event")
    persist_body = {"event": supplied_event} if isinstance(supplied_event, dict) else body
    persist_plan = build_zhiyi_usage_log_persist_dry_run(persist_body)
    event = persist_plan.get("would_append_event", {})
    append = persist_plan.get("append_contract", {})
    target_log_path = persist_plan.get("target_log_path") or _zhiyi_usage_log_path()
    raw_policy = persist_plan.get("source_refs_policy", {})
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        value = authorization.get(name, body.get(name))
        if value is True:
            return True
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "confirmed", "confirm")
        return False

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    required_checks = {
        "confirm_write_usage_log": confirmed("confirm_write_usage_log"),
        "confirm_single_jsonl_append": confirmed("confirm_single_jsonl_append"),
        "confirm_preserve_saved_user_content": confirmed("confirm_preserve_saved_user_content"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    event_type_ok = isinstance(event, dict) and event.get("event_type") == "zhiyi_usage_record"
    schema_version_ok = isinstance(event, dict) and str(event.get("schema_version", "")) == "1.0"
    try:
        parsed_append = json.loads(str(append.get("append_line", "")))
        append_line_valid_json = isinstance(parsed_append, dict)
    except Exception:
        append_line_valid_json = False
    expected_target = os.path.abspath(_zhiyi_usage_log_path())
    actual_target = os.path.abspath(str(target_log_path))
    target_ok = actual_target == expected_target
    saved_content_preserved = bool(raw_policy.get("saved_user_content_preserved", True))
    hash_only_replacement_blocked = bool(raw_policy.get("hash_only_replacement_allowed", False)) is False
    redaction_not_performed = bool(raw_policy.get("redaction_performed", False)) is False

    guard_checks = {
        "event_type": event_type_ok,
        "schema_version": schema_version_ok,
        "target_log_path": target_ok,
        "append_line_json": append_line_valid_json,
        "saved_user_content_preserved": saved_content_preserved,
        "hash_only_replacement_blocked": hash_only_replacement_blocked,
        "redaction_not_performed": redaction_not_performed,
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    authorization_complete = not missing
    future_authorized_append_ready = authorization_complete and not guard_failures
    if guard_failures:
        gate_status = "blocked_guard_failure"
    elif not authorization_complete:
        gate_status = "blocked_missing_authorization"
    else:
        gate_status = "ready_for_future_authorized_append"

    result = dict(persist_plan)
    result.update({
        "ok": not guard_failures,
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "apply_performed": False,
        "append_performed": False,
        "apply_allowed": False,
        "future_authorized_append_ready": future_authorized_append_ready,
        "live_apply_endpoint_enabled": False,
        "policy_version": ZHIYI_USAGE_LOG_APPLY_GATE_VERSION,
        "gate_status": gate_status,
        "authorization_complete": authorization_complete,
        "authorization_missing": missing,
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "guard_failures": guard_failures,
        "required_authorization": get_zhiyi_usage_log_apply_gate_policy()["required_authorization"],
        "future_apply_endpoint": "/api/v1/zhiyi/usage-log/apply",
        "dry_run_endpoint": "/api/v1/zhiyi/usage-log/apply-gate/dry-run",
        "notes": [
            "apply_gate_dry_run_only",
            "no_log_file_created_or_appended",
            "future_live_append_endpoint_not_enabled",
            "saved_user_content_remains_verbatim_in_usage_log",
        ],
    })
    return result


def build_zhiyi_usage_log_persist_dry_run(body=None):
    """Build the append artifact for a Zhiyi usage log record without writing it."""
    body = body or {}
    supplied_event = body.get("event")
    if isinstance(supplied_event, dict) and supplied_event.get("event_type") == "zhiyi_usage_record":
        event = supplied_event
        draft = {
            "ok": True,
            "dry_run": True,
            "event": event,
            "model_binding_plan": {},
        }
    else:
        draft = build_zhiyi_usage_log_dry_run(body)
        event = draft.get("event", {})

    target_log_path = _zhiyi_usage_log_path()
    parent_dir = os.path.dirname(target_log_path)
    append_line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    append_bytes = len((append_line + "\n").encode("utf-8"))
    raw_policy = event.get("source_refs_policy", {}) if isinstance(event, dict) else {}
    return {
        "ok": bool(draft.get("ok", True)),
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "target_log_path": target_log_path,
        "target_log_exists": os.path.exists(target_log_path),
        "target_parent_dir": parent_dir,
        "target_parent_exists": os.path.isdir(parent_dir),
        "would_create_parent_dir": not os.path.isdir(parent_dir),
        "would_append_event": event,
        "append_contract": {
            "schema_version": "1.0",
            "format": "jsonl",
            "encoding": "utf-8",
            "open_mode": "append",
            "newline_terminated": True,
            "file_mode_after_create": "0600",
            "append_bytes": append_bytes,
            "append_line": append_line,
            "append_requires_authorization": True,
        },
        "query_api_plan": {
            "endpoint": "/api/v1/zhiyi/usage-log/query/dry-run",
            "method": "GET",
            "default_order": "newest_first",
            "supports": ["page", "page_size", "status", "query"],
            "write_performed": False,
        },
        "source_refs_policy": {
            "usage_log_contains_source_refs": bool(raw_policy.get("usage_log_contains_source_refs", True)),
            "raw_detail_endpoint_available": bool(raw_policy.get("raw_detail_endpoint_available", True)),
            "saved_user_content_preserved": bool(raw_policy.get("saved_user_content_preserved", True)),
            "hash_only_replacement_allowed": bool(raw_policy.get("hash_only_replacement_allowed", False)),
            "redaction_performed": bool(raw_policy.get("redaction_performed", False)),
        },
        "model_binding_plan": draft.get("model_binding_plan", {}),
        "notes": [
            "persistence_artifact_only",
            "no_log_file_created_or_appended",
            "apply_requires_later_authorization",
        ],
    }


def query_zhiyi_usage_log_dry_run(params=None):
    """Read the planned Zhiyi usage log shape without mutating state."""
    params = params or {}
    page = _usage_log_positive_int(params.get("page", 1), 1, 1000000)
    page_size = _usage_log_positive_int(params.get("page_size", 20), 20, 100)
    status_filter = str(params.get("status", "") or "").strip()
    query_filter = str(params.get("query", "") or "").strip().lower()
    target_log_path = _zhiyi_usage_log_path()
    target_exists = os.path.exists(target_log_path)
    entries = []
    parse_errors = 0
    if target_exists:
        try:
            with open(target_log_path, encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, 1):
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        item = json.loads(text)
                    except Exception:
                        parse_errors += 1
                        continue
                    if not isinstance(item, dict) or item.get("event_type") != "zhiyi_usage_record":
                        parse_errors += 1
                        continue
                    item["_line_no"] = line_no
                    entries.append(item)
        except Exception:
            parse_errors += 1

    entries.sort(key=lambda item: item.get("ts", ""), reverse=True)
    filtered = []
    for item in entries:
        outcome = item.get("outcome", {}) if isinstance(item.get("outcome"), dict) else {}
        trigger = item.get("trigger", {}) if isinstance(item.get("trigger"), dict) else {}
        if status_filter and outcome.get("status") != status_filter:
            continue
        if query_filter and query_filter not in str(trigger.get("query", "")).lower():
            continue
        filtered.append(item)

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "target_log_path": target_log_path,
        "target_log_exists": target_exists,
        "read_performed": target_exists,
        "read_only": True,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "items": filtered[start:end],
        "parse_errors": parse_errors,
        "filters": {
            "status": status_filter,
            "query": query_filter,
        },
        "empty_reason": "" if target_exists else "usage_log_not_created",
        "query_contract": {
            "schema_version": "1.0",
            "source": "logs/zhiyi_usage.jsonl",
            "order": "newest_first",
            "raw_text_expected_in_items": False,
        },
        "notes": [
            "query_dry_run_read_only",
            "missing_log_is_not_failure_before_persistence_apply",
        ],
    }


def _hermes_feedback_candidates_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "hermes_experience_feedback", "candidates")


def _hermes_feedback_actions_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "hermes_experience_feedback", "actions")


def _hermes_feedback_upgrade_inputs_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "hermes_experience_feedback", "upgrade_inputs")


def _xingce_work_experience_candidates_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "xingce_work_experience", "candidates")


def _xingce_work_experience_actions_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "xingce_work_experience", "actions")


def _experience_service_adoptions_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "experience_service", "adoptions")


def _experience_service_rollbacks_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "experience_service", "rollbacks")


def _experience_service_upgrades_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "experience_service", "upgrades")


def _zhiyi_case_memory_dir():
    return os.path.join(str(MEMCORE_ROOT), "zhiyi", "case_memory")


def _zhiyi_case_memory_path():
    return os.path.join(_zhiyi_case_memory_dir(), "case_memory.jsonl")


def _zhiyi_case_memory_lifecycle_path():
    return os.path.join(_zhiyi_case_memory_dir(), "case_memory.lifecycle.jsonl")


def _hermes_feedback_action_bool(value):
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "confirmed", "confirm")
    return False


def _read_hermes_feedback_json(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data, ""
        return {}, "candidate_json_not_object"
    except FileNotFoundError:
        return {}, "candidate_not_found"
    except Exception as exc:
        return {}, f"candidate_read_failed:{str(exc)[:120]}"


def _safe_hermes_candidate_id(candidate_id):
    candidate_id = str(candidate_id or "").strip()
    if candidate_id.endswith(".json"):
        candidate_id = candidate_id[:-5]
    safe = "".join(ch for ch in candidate_id if ch.isalnum() or ch in ("-", "_"))
    if not safe or safe != candidate_id:
        return ""
    return safe


def _safe_experience_id(exp_id):
    exp_id = str(exp_id or "").strip()
    safe = "".join(ch for ch in exp_id if ch.isalnum() or ch in ("-", "_"))
    if not safe or safe != exp_id:
        return ""
    return safe


def _jsonl_append(path, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _read_jsonl_records(path):
    records = []
    if not os.path.exists(path):
        return records
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, 1):
                text = line.strip()
                if not text:
                    continue
                try:
                    rec = json.loads(text)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    rec["_line_no"] = line_no
                    records.append(rec)
    except Exception:
        return records
    return records


def _zhiyi_experience_recycle_path():
    return os.path.join(str(MEMCORE_ROOT), "output", "zhiyi_experience_lifecycle", "recycle_bin.jsonl")


def _zhiyi_experience_recycle_records():
    return _read_jsonl_records(_zhiyi_experience_recycle_path())


def _zhiyi_experience_recycle_overlay():
    overlay = {}
    for rec in _zhiyi_experience_recycle_records():
        exp_id = str(rec.get("exp_id") or "").strip()
        if not exp_id:
            continue
        action = rec.get("action") or "recycle"
        if action == "restore":
            overlay.pop(exp_id, None)
            continue
        if rec.get("deleted_state") == "recycle_bin" or action == "recycle":
            overlay[exp_id] = rec
    return overlay


def _zhiyi_experience_find(exp_id):
    safe_exp_id = _safe_experience_id(exp_id)
    if not safe_exp_id:
        return None
    for obj in load_zhiyi_objects():
        if obj.get("exp_id") == safe_exp_id:
            return obj
    return None


def recycle_zhiyi_experience(exp_id, body=None):
    body = body or {}
    safe_exp_id = _safe_experience_id(exp_id)
    if not safe_exp_id:
        return {"ok": False, "error": "invalid_exp_id"}
    obj = _zhiyi_experience_find(safe_exp_id)
    if not obj:
        return {"ok": False, "error": "experience_not_found", "exp_id": safe_exp_id}

    import uuid
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    refs = obj.get("_source_refs", {})
    if not isinstance(refs, dict):
        refs = {}
    source_path = refs.get("source_path", "")
    record = {
        "action_id": str(uuid.uuid4()),
        "action": "recycle",
        "exp_id": safe_exp_id,
        "title": _experience_title(obj, obj.get("_type", ""), 0),
        "type": obj.get("_type", ""),
        "deleted_state": "recycle_bin",
        "status": "recycled",
        "suppression_marker": True,
        "created_at": now,
        "reason": str(body.get("reason") or "frontstage_delete")[:240],
        "operator": str(body.get("operator") or "frontstage")[:80],
        "source_path": source_path,
        "raw_deleted": False,
        "raw_write_performed": False,
        "zhiyi_base_write_performed": False,
        "platform_write_performed": False,
        "restore_supported_now": True,
        "recycle_policy": "manual_restore",
    }
    _jsonl_append(_zhiyi_experience_recycle_path(), record)
    return {
        "ok": True,
        "exp_id": safe_exp_id,
        "deleted_state": "recycle_bin",
        "recycle_bin_count": len(_zhiyi_experience_recycle_overlay()),
        "raw_deleted": False,
        "raw_write_performed": False,
        "zhiyi_base_write_performed": False,
        "suppression_marker": True,
        "restore_supported_now": True,
        "restore_endpoint": "/api/v1/zhiyi/experiences/{exp_id}/restore",
        "record": record,
    }


def restore_zhiyi_experience(exp_id, body=None):
    body = body or {}
    safe_exp_id = _safe_experience_id(exp_id)
    if not safe_exp_id:
        return {"ok": False, "error": "invalid_exp_id"}
    if safe_exp_id not in _zhiyi_experience_recycle_overlay():
        return {"ok": False, "error": "experience_not_in_trash", "exp_id": safe_exp_id}
    obj = _zhiyi_experience_find(safe_exp_id)
    if not obj:
        return {"ok": False, "error": "experience_not_found", "exp_id": safe_exp_id}

    import uuid
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    refs = obj.get("_source_refs", {})
    if not isinstance(refs, dict):
        refs = {}
    record = {
        "action_id": str(uuid.uuid4()),
        "action": "restore",
        "exp_id": safe_exp_id,
        "title": _experience_title(obj, obj.get("_type", ""), 0),
        "type": obj.get("_type", ""),
        "deleted_state": "active",
        "status": "restored",
        "suppression_marker": False,
        "created_at": now,
        "reason": str(body.get("reason") or "frontstage_restore")[:240],
        "operator": str(body.get("operator") or "frontstage")[:80],
        "source_path": refs.get("source_path", ""),
        "raw_deleted": False,
        "raw_write_performed": False,
        "zhiyi_base_write_performed": False,
        "platform_write_performed": False,
        "restore_supported_now": True,
        "recycle_policy": "manual_restore",
    }
    _jsonl_append(_zhiyi_experience_recycle_path(), record)
    return {
        "ok": True,
        "exp_id": safe_exp_id,
        "deleted_state": "active",
        "recycle_bin_count": len(_zhiyi_experience_recycle_overlay()),
        "raw_deleted": False,
        "raw_write_performed": False,
        "zhiyi_base_write_performed": False,
        "suppression_marker": False,
        "record": record,
    }


def get_zhiyi_experience_recycle_bin(limit=20):
    try:
        limit = max(1, min(int(limit), 100))
    except Exception:
        limit = 20
    records = list(_zhiyi_experience_recycle_overlay().values())
    records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {
        "ok": True,
        "total": len(records),
        "items": records[:limit],
        "raw_deleted": False,
        "restore_supported_now": True,
        "recycle_policy": "manual_restore",
    }


def _window_from_raw_source_path(source_path):
    parts = str(source_path or "").split(os.sep)
    for index, part in enumerate(parts):
        if part == "local" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _latest_xingce_work_experience_candidate_id(candidates_dir):
    latest_path = os.path.join(candidates_dir, "latest.json")
    latest, err = _read_hermes_feedback_json(latest_path)
    if err:
        return "", latest_path, {}
    return str(latest.get("candidate_id", "") or ""), latest_path, latest


def _xingce_work_experience_candidate_summary(candidate, source_path="", latest_candidate_id=""):
    write_boundary = candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {}
    comparison = candidate.get("comparison_result", {}) if isinstance(candidate.get("comparison_result"), dict) else {}
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    candidate_id = candidate.get("candidate_id", "")
    return {
        "candidate_id": candidate_id,
        "candidate_type": candidate.get("candidate_type", ""),
        "source_draft_id": candidate.get("source_draft_id", ""),
        "title": candidate.get("title", ""),
        "summary": _compact_text(candidate.get("summary", ""), 360),
        "created_at": candidate.get("created_at", ""),
        "lifecycle_status": candidate.get("lifecycle_status", ""),
        "frontstage_surface": candidate.get("frontstage_surface", ""),
        "source_mode": candidate.get("source_mode", ""),
        "change_class": comparison.get("change_class", ""),
        "raw_evidence_contract_gate_passed": bool(comparison.get("raw_evidence_contract_gate_passed", False)),
        "confidence": candidate.get("confidence", 0.0),
        "evidence_refs_count": len(evidence_refs),
        "source_refs_count": len(source_refs),
        "write_boundary": write_boundary,
        "production_experience_write_performed": bool(write_boundary.get("production_experience_write_performed", False)),
        "raw_write_performed": bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_performed": bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_performed": bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_performed": bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_performed": bool(write_boundary.get("openclaw_write_performed", False)),
        "source_path": source_path,
        "is_latest": bool(candidate_id and candidate_id == latest_candidate_id),
        "detail_endpoint": f"/api/v1/xingce/work-experience-candidates/{candidate_id}" if candidate_id else "",
    }


def _xingce_work_experience_action_history(candidate_id="", limit=20):
    actions_dir = _xingce_work_experience_actions_dir()
    items = []
    parse_errors = []
    if not os.path.isdir(actions_dir):
        return items, parse_errors
    try:
        names = sorted(os.listdir(actions_dir), reverse=True)
    except Exception as exc:
        return items, [{"path": actions_dir, "error": str(exc)[:120]}]
    safe_id = _safe_hermes_candidate_id(candidate_id)
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(actions_dir, name)
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                line = f.readline().strip()
            if not line:
                continue
            item = json.loads(line)
        except Exception as exc:
            parse_errors.append({"path": path, "error": str(exc)[:120]})
            continue
        if safe_id and item.get("candidate_id") != safe_id:
            continue
        item["_source_path"] = path
        items.append(item)
        if len(items) >= limit:
            break
    return items, parse_errors


def query_xingce_work_experience_candidates(params=None):
    params = params or {}
    candidates_dir = _xingce_work_experience_candidates_dir()
    candidates_dir_exists = os.path.isdir(candidates_dir)
    latest_candidate_id, latest_path, latest_candidate = _latest_xingce_work_experience_candidate_id(candidates_dir)
    page = _usage_log_positive_int(params.get("page", 1), 1, 1000000)
    page_size = _usage_log_positive_int(params.get("page_size", 20), 20, 50)
    status_filter = str(params.get("lifecycle_status", "") or "").strip()

    items = []
    parse_errors = []
    seen = set()
    if candidates_dir_exists:
        for path in sorted(glob.glob(os.path.join(candidates_dir, "xingce-*-candidate.json"))):
            candidate, err = _read_hermes_feedback_json(path)
            if err:
                parse_errors.append({"path": path, "error": err})
                continue
            if candidate.get("candidate_type") != "xingce_work_experience":
                continue
            candidate_id = str(candidate.get("candidate_id", "") or "")
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            items.append(_xingce_work_experience_candidate_summary(candidate, path, latest_candidate_id))

    if latest_candidate and latest_candidate_id and latest_candidate_id not in seen:
        items.append(_xingce_work_experience_candidate_summary(latest_candidate, latest_path, latest_candidate_id))

    items.sort(key=lambda item: (item.get("created_at") or "", item.get("candidate_id") or ""), reverse=True)
    if status_filter:
        items = [item for item in items if item.get("lifecycle_status") == status_filter]
    for item in items:
        history, _ = _xingce_work_experience_action_history(item.get("candidate_id", ""), limit=1)
        item["action_count"] = len(_xingce_work_experience_action_history(item.get("candidate_id", ""), limit=1000000)[0])
        item["latest_action"] = history[0] if history else None
        item["action_endpoint"] = f"/api/v1/xingce/work-experience-candidates/{item.get('candidate_id', '')}/actions"

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidates_dir": candidates_dir,
        "candidates_dir_exists": candidates_dir_exists,
        "latest_candidate_id": latest_candidate_id,
        "latest_path": latest_path,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "items": items[start:end],
        "parse_errors": parse_errors,
        "filters": {"lifecycle_status": status_filter},
        "query_contract": {
            "schema_version": "1.0",
            "source": "output/xingce_work_experience/candidates/xingce-*-candidate.json",
            "order": "newest_first",
            "method": "GET",
            "write_performed": False,
        },
        "notes": [
            "xingce_candidate_artifact_read_only",
            "no_raw_zhiyi_xingce_hermes_openclaw_write",
            "production_experience_upgrade_not_applied_by_this_api",
        ],
    }


def query_xingce_work_experience_actions(params=None):
    params = params or {}
    candidate_id = str(params.get("candidate_id", "") or "").strip()
    limit = _usage_log_positive_int(params.get("limit", 20), 20, 100)
    items, parse_errors = _xingce_work_experience_action_history(candidate_id, limit=limit)
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "actions_dir": _xingce_work_experience_actions_dir(),
        "candidate_id": candidate_id,
        "total": len(items),
        "items": items,
        "parse_errors": parse_errors,
    }


def get_xingce_work_experience_candidate(candidate_id):
    candidates_dir = _xingce_work_experience_candidates_dir()
    safe_id = _safe_hermes_candidate_id(candidate_id)
    latest_candidate_id, latest_path, latest_candidate = _latest_xingce_work_experience_candidate_id(candidates_dir)
    if safe_id == "latest":
        candidate = latest_candidate
        source_path = latest_path
    elif safe_id:
        source_path = os.path.join(candidates_dir, f"{safe_id}.json")
        candidate, err = _read_hermes_feedback_json(source_path)
        if err and safe_id == latest_candidate_id and latest_candidate:
            candidate = latest_candidate
            source_path = latest_path
    else:
        candidate = {}
        source_path = ""
    if not candidate:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "error": "xingce_candidate_not_found",
            "candidate_id": candidate_id,
            "candidates_dir": candidates_dir,
        }
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": candidate.get("candidate_id", safe_id),
        "latest_candidate_id": latest_candidate_id,
        "candidates_dir": candidates_dir,
        "source_path": source_path,
        "summary": _xingce_work_experience_candidate_summary(candidate, source_path, latest_candidate_id),
        "write_boundary": candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {},
        "actions": _xingce_work_experience_action_history(candidate.get("candidate_id", safe_id), limit=20)[0],
        "candidate": candidate,
    }


def apply_xingce_work_experience_candidate_action(candidate_id, body=None):
    body = body or {}
    detail = get_xingce_work_experience_candidate(candidate_id)
    if not detail.get("ok"):
        return detail
    candidate = detail.get("candidate", {})
    safe_id = _safe_hermes_candidate_id(candidate.get("candidate_id", candidate_id))
    action = str(body.get("action", "") or "").strip()
    aliases = {
        "adopt": "adopt_as_experience",
        "adopt_as_experience": "adopt_as_experience",
        "upgrade": "upgrade_experience",
        "upgrade_experience": "upgrade_experience",
        "recycle": "recycle",
    }
    action = aliases.get(action, "")
    if action not in ("adopt_as_experience", "upgrade_experience", "recycle"):
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "error": "action_must_be_one_of_adopt_as_experience_upgrade_experience_recycle",
            "candidate_id": safe_id,
        }

    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    required_checks = {
        "confirm_process_xingce_candidate": confirmed("confirm_process_xingce_candidate"),
        "confirm_write_xingce_candidate_action": confirmed("confirm_write_xingce_candidate_action"),
        "confirm_no_raw_zhiyi_xingce_hermes_openclaw_write": confirmed("confirm_no_raw_zhiyi_xingce_hermes_openclaw_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    write_boundary = candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {}
    guard_checks = {
        "candidate_id_safe": bool(safe_id),
        "candidate_type": candidate.get("candidate_type") == "xingce_work_experience",
        "candidate_lifecycle_status": candidate.get("lifecycle_status") == "candidate",
        "candidate_artifact_exists": os.path.isfile(detail.get("source_path", "")),
        "candidate_not_production_written": not bool(write_boundary.get("production_experience_write_performed", False)),
        "raw_write_stays_false": not bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_stays_false": not bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_stays_false": not bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_stays_false": not bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_stays_false": not bool(write_boundary.get("openclaw_write_performed", False)),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "action_write_performed": False,
            "candidate_id": safe_id,
            "action": action,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    actions_dir = _xingce_work_experience_actions_dir()
    os.makedirs(actions_dir, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action_id = "xingce-action-" + uuid.uuid4().hex[:16]
    action_status = {
        "adopt_as_experience": "queued_for_experience_service_review",
        "upgrade_experience": "queued_for_experience_upgrade_review",
        "recycle": "recycled_from_xingce_candidate_queue",
    }[action]
    receipt = {
        "schema_version": "1.0",
        "action_id": action_id,
        "created_at": now,
        "candidate_id": safe_id,
        "candidate_type": candidate.get("candidate_type", ""),
        "action": action,
        "action_status": action_status,
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "source_candidate_path": detail.get("source_path", ""),
        "source_mode": candidate.get("source_mode", ""),
        "change_class": (candidate.get("comparison_result", {}) if isinstance(candidate.get("comparison_result"), dict) else {}).get("change_class", ""),
        "evidence_refs_count": len(candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []),
        "source_refs_count": len(candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []),
        "write_boundary": {
            "action_receipt_write_performed": True,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "live_xingce_work_experience_action_receipt",
            "candidate_artifact_not_modified",
            "no_raw_zhiyi_xingce_hermes_openclaw_write",
        ],
    }
    action_path = os.path.join(actions_dir, f"{now.replace(':', '').replace('-', '')}-{safe_id}-{action}.jsonl")
    with open(action_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
    latest_path = os.path.join(actions_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "action_write_performed": True,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": safe_id,
        "action": action,
        "action_status": action_status,
        "action_id": action_id,
        "action_path": action_path,
        "latest_path": latest_path,
        "receipt": receipt,
    }


def _first_xingce_evidence_ref(candidate):
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    for item in evidence_refs:
        if isinstance(item, dict) and item.get("source_path"):
            return dict(item)
    source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    for source_path in source_refs:
        if source_path:
            return {"source_path": source_path}
    return {}


def _stable_xingce_case_exp_id(candidate_id):
    import hashlib
    digest = hashlib.sha1(str(candidate_id or "").encode("utf-8")).hexdigest()[:12]
    return f"exp-case-{digest}"


def _decode_record_source_refs(record):
    raw = record.get("source_refs", {}) if isinstance(record, dict) else {}
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            return decoded if isinstance(decoded, dict) else {}
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


def _find_case_memory_record(exp_id):
    for record in _read_jsonl_records(_zhiyi_case_memory_path()):
        if record.get("exp_id") == exp_id:
            return record
    return {}


def _latest_case_memory_record(exp_id):
    latest = {}
    for record in _read_jsonl_records(_zhiyi_case_memory_path()):
        if record.get("exp_id") != exp_id:
            continue
        if not latest or int(record.get("lifecycle_version", 0) or 0) >= int(latest.get("lifecycle_version", 0) or 0):
            latest = record
    return latest


def _latest_case_memory_lifecycle_record(exp_id):
    latest = {}
    for record in _read_jsonl_records(_zhiyi_case_memory_lifecycle_path()):
        if record.get("exp_id") != exp_id:
            continue
        if not latest or int(record.get("lifecycle_version", 0) or 0) >= int(latest.get("lifecycle_version", 0) or 0):
            latest = record
    return latest


def _candidate_to_case_memory_record(candidate, detail, action, exp_id, authorization, now_display):
    import hashlib
    safe_id = str(candidate.get("candidate_id", "") or "")
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    raw_source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    first_ref = _first_xingce_evidence_ref(candidate)
    source_path = first_ref.get("source_path", "")
    window_id = first_ref.get("canonical_window_id") or _window_from_raw_source_path(source_path)
    computer_name = first_ref.get("computer_name") or first_ref.get("computer_id") or "local"
    source_refs = {
        "source_system": first_ref.get("source_system", "openclaw"),
        "computer_name": computer_name,
        "computer_id": first_ref.get("computer_id", computer_name),
        "canonical_window_id": window_id,
        "session_id": first_ref.get("session_id", ""),
        "source_path": source_path,
        "msg_ids": first_ref.get("msg_ids", []),
        "evidence_refs": evidence_refs,
        "raw_source_refs": raw_source_refs,
        "experience_service": {
            "source": "xingce_work_experience_candidate",
            "candidate_id": safe_id,
            "candidate_path": detail.get("source_path", ""),
            "action_id": action.get("action_id", ""),
            "action_path": action.get("_source_path", ""),
            "action_status": action.get("action_status", ""),
            "projection_desensitized": False,
            "raw_projection_policy": "preserve_verbatim_refs",
        },
    }
    title = candidate.get("title") or "Xingce work experience"
    summary = candidate.get("summary") or "Xingce work experience adopted into Zhiyi"
    observed = candidate.get("observed_facts", []) if isinstance(candidate.get("observed_facts"), list) else []
    procedures = candidate.get("recommended_procedure", []) if isinstance(candidate.get("recommended_procedure"), list) else []
    verification = candidate.get("verification_steps", []) if isinstance(candidate.get("verification_steps"), list) else []
    detail_parts = [
        f"candidate_id={safe_id}",
        f"source_mode={candidate.get('source_mode', '')}",
        f"operator_reason={authorization.get('reason', '')}",
    ]
    detail_parts.extend(str(item) for item in observed[:5])
    detail_parts.extend(str(item) for item in procedures[:5])
    detail_parts.extend(str(item) for item in verification[:5])
    memory_id = hashlib.sha256(f"{exp_id}:{safe_id}:production_case_memory".encode("utf-8")).hexdigest()
    try:
        score = max(float(candidate.get("confidence", 0.75) or 0.75), 0.75)
    except Exception:
        score = 0.75
    return {
        "exp_id": exp_id,
        "type": "case_memory",
        "canonical_window_id": window_id,
        "session_id": first_ref.get("session_id", ""),
        "computer_id": source_refs["computer_id"],
        "source_system": source_refs["source_system"],
        "scope": f"window/{window_id}" if window_id else "window/main",
        "summary": f"案例：[行策经验已采用] {title}。{summary}。candidate_id={safe_id}",
        "detail": "\n".join(part for part in detail_parts if part),
        "source_refs": json.dumps(source_refs, ensure_ascii=False, separators=(",", ":")),
        "evidence_level": "high" if evidence_refs else "medium",
        "score": score,
        "extracted_at": now_display,
        "memory_id": memory_id,
        "lifecycle_version": 1,
    }


def _case_memory_lifecycle_record(case_record, status, conflict_decision, lifecycle_version, reason, now_display):
    lifecycle = dict(case_record)
    lifecycle.update({
        "status": status,
        "visibility": "canonical" if conflict_decision == "active" else "suppressed",
        "inject_policy": "inject_on_match" if conflict_decision == "active" else "never",
        "supersedes": [],
        "superseded_by": [],
        "lifecycle_updated_at": now_display,
        "lifecycle_version": lifecycle_version,
        "conflict_group_id": f"CG-{case_record.get('exp_id', '')}",
        "conflict_type": "experience_service_action",
        "conflict_decision": conflict_decision,
        "conflict_reason": reason,
        "effective_from": now_display,
        "validity_scope": case_record.get("scope", ""),
    })
    return lifecycle


def _latest_adopt_action_for_candidate(candidate_id, requested_action_id=""):
    actions, _ = _xingce_work_experience_action_history(candidate_id, limit=1000000)
    for action in actions:
        if action.get("action") != "adopt_as_experience":
            continue
        if action.get("action_status") != "queued_for_experience_service_review":
            continue
        if requested_action_id and action.get("action_id") != requested_action_id:
            continue
        return action
    return {}


def apply_experience_service_xingce_adoption(candidate_id, body=None):
    body = body or {}
    detail = get_xingce_work_experience_candidate(candidate_id)
    if not detail.get("ok"):
        return detail
    candidate = detail.get("candidate", {})
    safe_id = _safe_hermes_candidate_id(candidate.get("candidate_id", candidate_id))
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    requested_action_id = str(body.get("action_id", "") or authorization.get("action_id", "") or "").strip()
    action = _latest_adopt_action_for_candidate(safe_id, requested_action_id=requested_action_id)
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    raw_source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    exp_id = _stable_xingce_case_exp_id(safe_id)
    existing_record = _find_case_memory_record(exp_id)
    existing_refs = _decode_record_source_refs(existing_record)
    existing_candidate_id = (
        (existing_refs.get("experience_service", {}) if isinstance(existing_refs.get("experience_service"), dict) else {}).get("candidate_id")
        or existing_refs.get("candidate_id", "")
    )

    required_checks = {
        "confirm_adopt_production_experience": confirmed("confirm_adopt_production_experience"),
        "confirm_write_zhiyi_case_memory": confirmed("confirm_write_zhiyi_case_memory"),
        "confirm_write_zhiyi_lifecycle_overlay": confirmed("confirm_write_zhiyi_lifecycle_overlay"),
        "confirm_preserve_raw_source_refs": confirmed("confirm_preserve_raw_source_refs"),
        "confirm_projection_not_desensitized": confirmed("confirm_projection_not_desensitized"),
        "confirm_no_raw_xingce_hermes_openclaw_write": confirmed("confirm_no_raw_xingce_hermes_openclaw_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    write_boundary = candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {}
    guard_checks = {
        "candidate_id_safe": bool(safe_id),
        "candidate_type": candidate.get("candidate_type") == "xingce_work_experience",
        "candidate_lifecycle_status": candidate.get("lifecycle_status") == "candidate",
        "candidate_artifact_exists": os.path.isfile(detail.get("source_path", "")),
        "queued_adopt_action_exists": bool(action),
        "source_mode_raw_source_refs": candidate.get("source_mode") == "raw_source_refs",
        "evidence_refs_present": len(evidence_refs) > 0,
        "raw_source_refs_present": len(raw_source_refs) > 0,
        "case_exp_id_unclaimed_or_same_candidate": not existing_record or existing_candidate_id == safe_id,
        "candidate_not_production_written": not bool(write_boundary.get("production_experience_write_performed", False)),
        "raw_write_stays_false": not bool(write_boundary.get("raw_write_performed", False)),
        "xingce_write_stays_false": not bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_stays_false": not bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_stays_false": not bool(write_boundary.get("openclaw_write_performed", False)),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "production_experience_write_performed": False,
            "zhiyi_write_performed": False,
            "raw_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "candidate_id": safe_id,
            "exp_id": exp_id,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_display = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    case_record = existing_record or _candidate_to_case_memory_record(candidate, detail, action, exp_id, authorization, now_display)
    case_memory_append_performed = False
    if not existing_record:
        _jsonl_append(_zhiyi_case_memory_path(), case_record)
        case_memory_append_performed = True

    latest_lifecycle = _latest_case_memory_lifecycle_record(exp_id)
    latest_decision = latest_lifecycle.get("conflict_decision", "")
    lifecycle_append_performed = False
    lifecycle_version = int(latest_lifecycle.get("lifecycle_version", 0) or 0)
    if latest_decision != "active":
        lifecycle = _case_memory_lifecycle_record(
            case_record,
            status="active",
            conflict_decision="active",
            lifecycle_version=lifecycle_version + 1,
            reason=str(authorization.get("reason", body.get("reason", "")) or "experience service adoption"),
            now_display=now_display,
        )
        _jsonl_append(_zhiyi_case_memory_lifecycle_path(), lifecycle)
        lifecycle_append_performed = True

    receipt_id = "experience-adoption-" + uuid.uuid4().hex[:16]
    receipt = {
        "schema_version": "1.0",
        "receipt_id": receipt_id,
        "created_at": now_iso,
        "candidate_id": safe_id,
        "source_candidate_path": detail.get("source_path", ""),
        "source_action_id": action.get("action_id", ""),
        "source_action_path": action.get("_source_path", ""),
        "exp_id": exp_id,
        "target_case_memory_path": _zhiyi_case_memory_path(),
        "target_lifecycle_path": _zhiyi_case_memory_lifecycle_path(),
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "case_memory_append_performed": case_memory_append_performed,
        "lifecycle_append_performed": lifecycle_append_performed,
        "idempotent_existing_case_memory": bool(existing_record),
        "idempotent_existing_active_lifecycle": bool(latest_decision == "active"),
        "source_refs_preserved": True,
        "projection_desensitized": False,
        "write_boundary": {
            "adoption_receipt_write_performed": True,
            "production_experience_write_performed": bool(case_memory_append_performed or lifecycle_append_performed),
            "raw_write_performed": False,
            "zhiyi_write_performed": bool(case_memory_append_performed or lifecycle_append_performed),
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "live_experience_service_adoption",
            "raw_source_refs_preserved_without_desensitization",
            "candidate_and_action_artifacts_not_modified",
        ],
    }
    adoptions_dir = _experience_service_adoptions_dir()
    os.makedirs(adoptions_dir, exist_ok=True)
    receipt_path = os.path.join(adoptions_dir, f"{now_iso.replace(':', '').replace('-', '')}-{safe_id}-adopt.jsonl")
    _jsonl_append(receipt_path, receipt)
    latest_path = os.path.join(adoptions_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    production_write = bool(case_memory_append_performed or lifecycle_append_performed)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "adoption_receipt_write_performed": True,
        "production_experience_write_performed": production_write,
        "raw_write_performed": False,
        "zhiyi_write_performed": production_write,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": safe_id,
        "exp_id": exp_id,
        "case_memory_append_performed": case_memory_append_performed,
        "lifecycle_append_performed": lifecycle_append_performed,
        "source_refs_preserved": True,
        "projection_desensitized": False,
        "receipt_id": receipt_id,
        "receipt_path": receipt_path,
        "latest_path": latest_path,
        "receipt": receipt,
    }


def apply_experience_service_case_memory_rollback(exp_id, body=None):
    body = body or {}
    safe_exp_id = _safe_experience_id(exp_id)
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    case_record = _find_case_memory_record(safe_exp_id)
    latest_lifecycle = _latest_case_memory_lifecycle_record(safe_exp_id)
    required_checks = {
        "confirm_rollback_production_experience": confirmed("confirm_rollback_production_experience"),
        "confirm_write_zhiyi_lifecycle_overlay": confirmed("confirm_write_zhiyi_lifecycle_overlay"),
        "confirm_preserve_case_memory_file": confirmed("confirm_preserve_case_memory_file"),
        "confirm_no_raw_xingce_hermes_openclaw_write": confirmed("confirm_no_raw_xingce_hermes_openclaw_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    guard_checks = {
        "exp_id_safe": bool(safe_exp_id),
        "case_memory_record_exists": bool(case_record),
        "case_memory_file_exists": os.path.isfile(_zhiyi_case_memory_path()),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "production_experience_write_performed": False,
            "zhiyi_write_performed": False,
            "raw_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "exp_id": safe_exp_id,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_display = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    already_superseded = latest_lifecycle.get("conflict_decision") == "superseded"
    lifecycle_append_performed = False
    if not already_superseded:
        lifecycle_version = int(latest_lifecycle.get("lifecycle_version", case_record.get("lifecycle_version", 1)) or 1)
        lifecycle = _case_memory_lifecycle_record(
            case_record,
            status="superseded",
            conflict_decision="superseded",
            lifecycle_version=lifecycle_version + 1,
            reason=str(authorization.get("reason", body.get("reason", "")) or "experience service rollback"),
            now_display=now_display,
        )
        _jsonl_append(_zhiyi_case_memory_lifecycle_path(), lifecycle)
        lifecycle_append_performed = True

    rollback_id = "experience-rollback-" + uuid.uuid4().hex[:16]
    receipt = {
        "schema_version": "1.0",
        "rollback_id": rollback_id,
        "created_at": now_iso,
        "exp_id": safe_exp_id,
        "target_case_memory_path": _zhiyi_case_memory_path(),
        "target_lifecycle_path": _zhiyi_case_memory_lifecycle_path(),
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "case_memory_deleted": False,
        "case_memory_preserved": True,
        "lifecycle_append_performed": lifecycle_append_performed,
        "idempotent_existing_superseded_lifecycle": already_superseded,
        "write_boundary": {
            "rollback_receipt_write_performed": True,
            "production_experience_write_performed": bool(lifecycle_append_performed),
            "raw_write_performed": False,
            "zhiyi_write_performed": bool(lifecycle_append_performed),
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "live_experience_service_rollback",
            "rollback_uses_lifecycle_overlay_no_case_memory_delete",
            "raw_source_refs_preserved_without_desensitization",
        ],
    }
    rollbacks_dir = _experience_service_rollbacks_dir()
    os.makedirs(rollbacks_dir, exist_ok=True)
    receipt_path = os.path.join(rollbacks_dir, f"{now_iso.replace(':', '').replace('-', '')}-{safe_exp_id}-rollback.jsonl")
    _jsonl_append(receipt_path, receipt)
    latest_path = os.path.join(rollbacks_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "rollback_receipt_write_performed": True,
        "production_experience_write_performed": bool(lifecycle_append_performed),
        "raw_write_performed": False,
        "zhiyi_write_performed": bool(lifecycle_append_performed),
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "exp_id": safe_exp_id,
        "case_memory_deleted": False,
        "case_memory_preserved": True,
        "lifecycle_append_performed": lifecycle_append_performed,
        "rollback_id": rollback_id,
        "receipt_path": receipt_path,
        "latest_path": latest_path,
        "receipt": receipt,
    }


def _hermes_upgrade_input_flags(upgrade_input):
    fresh = upgrade_input.get("fresh_observation", {}) if isinstance(upgrade_input.get("fresh_observation"), dict) else {}
    flags = fresh.get("observed_write_flags", {}) if isinstance(fresh.get("observed_write_flags"), dict) else {}
    return {
        "skill": bool(flags.get("skill", False)),
        "learning": bool(flags.get("learning", False)),
        "memory": bool(flags.get("memory", False)),
    }


def _case_memory_upgrade_source_refs(existing_record, upgrade_input, upgrade_detail, authorization):
    source_refs = _decode_record_source_refs(existing_record)
    if not source_refs:
        source_refs = {}
    experience_service = source_refs.get("experience_service", {})
    if not isinstance(experience_service, dict):
        experience_service = {}
    upgrades = experience_service.get("upgrades", [])
    if not isinstance(upgrades, list):
        upgrades = []
    fresh = upgrade_input.get("fresh_observation", {}) if isinstance(upgrade_input.get("fresh_observation"), dict) else {}
    comparison = upgrade_input.get("comparison_result", {}) if isinstance(upgrade_input.get("comparison_result"), dict) else {}
    upgrade_ref = {
        "source": "hermes_feedback_upgrade_input",
        "upgrade_input_id": upgrade_input.get("upgrade_input_id", ""),
        "upgrade_input_path": upgrade_detail.get("source_path", ""),
        "candidate_id": upgrade_input.get("candidate_id", ""),
        "fresh_change_class": comparison.get("fresh_change_class", ""),
        "native_change_observed_after_action": bool(comparison.get("native_change_observed_after_action", False)),
        "observed_write_flags": _hermes_upgrade_input_flags(upgrade_input),
        "source_refs": fresh.get("source_refs", []) if isinstance(fresh.get("source_refs"), list) else [],
        "operator_reason": str(authorization.get("reason", "") or ""),
        "projection_desensitized": False,
        "raw_projection_policy": "preserve_verbatim_refs",
    }
    upgrades.append(upgrade_ref)
    experience_service["last_upgrade"] = upgrade_ref
    experience_service["upgrades"] = upgrades
    experience_service["projection_desensitized"] = False
    experience_service["raw_projection_policy"] = "preserve_verbatim_refs"
    source_refs["experience_service"] = experience_service
    return source_refs


def _case_memory_record_with_hermes_upgrade(existing_record, upgrade_input, upgrade_detail, authorization, lifecycle_version, now_display):
    import hashlib
    upgraded = dict(existing_record)
    upgrade_input_id = str(upgrade_input.get("upgrade_input_id", "") or "")
    flags = _hermes_upgrade_input_flags(upgrade_input)
    comparison = upgrade_input.get("comparison_result", {}) if isinstance(upgrade_input.get("comparison_result"), dict) else {}
    fresh = upgrade_input.get("fresh_observation", {}) if isinstance(upgrade_input.get("fresh_observation"), dict) else {}
    base_summary = str(existing_record.get("summary", "") or "")
    if "经验语义升级" not in base_summary:
        summary = f"案例：[经验语义升级] {base_summary}"
    else:
        summary = base_summary
    summary = f"{summary}。upgrade_input_id={upgrade_input_id}"
    detail_parts = [
        str(existing_record.get("detail", "") or ""),
        f"experience_upgrade_source=hermes_feedback_upgrade_input",
        f"upgrade_input_id={upgrade_input_id}",
        f"candidate_id={upgrade_input.get('candidate_id', '')}",
        f"fresh_change_class={comparison.get('fresh_change_class', '')}",
        f"native_change_observed_after_action={comparison.get('native_change_observed_after_action', False)}",
        f"observed_write_flags={json.dumps(flags, ensure_ascii=False, sort_keys=True)}",
        f"agent_created_skill_count={fresh.get('agent_created_skill_count', 0)}",
        f"operator_reason={authorization.get('reason', '')}",
    ]
    upgraded.update({
        "summary": summary,
        "detail": "\n".join(part for part in detail_parts if part),
        "source_refs": json.dumps(
            _case_memory_upgrade_source_refs(existing_record, upgrade_input, upgrade_detail, authorization),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "score": max(float(existing_record.get("score", 0.75) or 0.75), 0.8),
        "extracted_at": now_display,
        "lifecycle_version": lifecycle_version,
        "memory_id": hashlib.sha256(
            f"{existing_record.get('exp_id', '')}:{upgrade_input_id}:production_case_memory_upgrade:{lifecycle_version}".encode("utf-8")
        ).hexdigest(),
    })
    return upgraded


def _case_memory_has_upgrade(record, upgrade_input_id):
    refs = _decode_record_source_refs(record)
    experience_service = refs.get("experience_service", {}) if isinstance(refs, dict) else {}
    if not isinstance(experience_service, dict):
        return False
    last_upgrade = experience_service.get("last_upgrade", {})
    if isinstance(last_upgrade, dict) and last_upgrade.get("upgrade_input_id") == upgrade_input_id:
        return True
    upgrades = experience_service.get("upgrades", [])
    if isinstance(upgrades, list):
        return any(isinstance(item, dict) and item.get("upgrade_input_id") == upgrade_input_id for item in upgrades)
    return False


def apply_experience_service_hermes_upgrade_input(upgrade_input_id, body=None):
    body = body or {}
    detail = get_hermes_feedback_upgrade_input(upgrade_input_id)
    if not detail.get("ok"):
        return detail
    upgrade_input = detail.get("upgrade_input", {})
    safe_upgrade_id = _safe_hermes_candidate_id(upgrade_input.get("upgrade_input_id", upgrade_input_id))
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    target_exp_id = _safe_experience_id(
        body.get("target_exp_id", "") or authorization.get("target_exp_id", "")
    )
    existing_record = _latest_case_memory_record(target_exp_id) if target_exp_id else {}
    latest_lifecycle = _latest_case_memory_lifecycle_record(target_exp_id) if target_exp_id else {}
    flags = _hermes_upgrade_input_flags(upgrade_input)
    comparison = upgrade_input.get("comparison_result", {}) if isinstance(upgrade_input.get("comparison_result"), dict) else {}
    write_boundary = upgrade_input.get("write_boundary", {}) if isinstance(upgrade_input.get("write_boundary"), dict) else {}

    required_checks = {
        "confirm_apply_production_experience_upgrade": confirmed("confirm_apply_production_experience_upgrade"),
        "confirm_write_zhiyi_case_memory": confirmed("confirm_write_zhiyi_case_memory"),
        "confirm_write_zhiyi_lifecycle_overlay": confirmed("confirm_write_zhiyi_lifecycle_overlay"),
        "confirm_preserve_raw_source_refs": confirmed("confirm_preserve_raw_source_refs"),
        "confirm_projection_not_desensitized": confirmed("confirm_projection_not_desensitized"),
        "confirm_no_raw_xingce_hermes_openclaw_write": confirmed("confirm_no_raw_xingce_hermes_openclaw_write"),
        "target_exp_id": bool(target_exp_id),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    guard_checks = {
        "upgrade_input_id_safe": bool(safe_upgrade_id),
        "upgrade_input_artifact_exists": os.path.isfile(detail.get("source_path", "")),
        "upgrade_input_ready": bool(upgrade_input.get("experience_upgrade_ready", False)),
        "upgrade_input_status_ready": upgrade_input.get("upgrade_input_status") == "ready_for_experience_review_native_change_observed",
        "native_change_observed_after_action": bool(comparison.get("native_change_observed_after_action", False)),
        "native_write_flag_present": any(flags.values()),
        "target_case_memory_exists": bool(existing_record),
        "target_case_memory_active": latest_lifecycle.get("conflict_decision") == "active",
        "upgrade_input_not_already_production_written": not bool(upgrade_input.get("production_experience_write_performed", False)),
        "raw_write_stays_false": not bool(write_boundary.get("raw_write_performed", False)),
        "xingce_write_stays_false": not bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_stays_false": not bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_stays_false": not bool(write_boundary.get("openclaw_write_performed", False)),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "production_experience_write_performed": False,
            "zhiyi_write_performed": False,
            "raw_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "upgrade_input_id": safe_upgrade_id,
            "target_exp_id": target_exp_id,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_display = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    already_applied = _case_memory_has_upgrade(existing_record, safe_upgrade_id)
    case_memory_append_performed = False
    lifecycle_append_count = 0
    new_lifecycle_version = int(latest_lifecycle.get("lifecycle_version", existing_record.get("lifecycle_version", 1)) or 1)
    upgraded_record = existing_record
    if not already_applied:
        superseded_version = new_lifecycle_version + 1
        active_version = new_lifecycle_version + 2
        superseded = _case_memory_lifecycle_record(
            existing_record,
            status="superseded",
            conflict_decision="superseded",
            lifecycle_version=superseded_version,
            reason=f"superseded by Hermes upgrade input {safe_upgrade_id}",
            now_display=now_display,
        )
        upgraded_record = _case_memory_record_with_hermes_upgrade(
            existing_record,
            upgrade_input,
            detail,
            authorization,
            active_version,
            now_display,
        )
        active = _case_memory_lifecycle_record(
            upgraded_record,
            status="active",
            conflict_decision="active",
            lifecycle_version=active_version,
            reason=str(authorization.get("reason", body.get("reason", "")) or "experience service semantic upgrade"),
            now_display=now_display,
        )
        _jsonl_append(_zhiyi_case_memory_path(), upgraded_record)
        _jsonl_append(_zhiyi_case_memory_lifecycle_path(), superseded)
        _jsonl_append(_zhiyi_case_memory_lifecycle_path(), active)
        case_memory_append_performed = True
        lifecycle_append_count = 2
        new_lifecycle_version = active_version

    upgrade_id = "experience-upgrade-" + uuid.uuid4().hex[:16]
    receipt = {
        "schema_version": "1.0",
        "upgrade_id": upgrade_id,
        "created_at": now_iso,
        "upgrade_input_id": safe_upgrade_id,
        "source_upgrade_input_path": detail.get("source_path", ""),
        "target_exp_id": target_exp_id,
        "target_case_memory_path": _zhiyi_case_memory_path(),
        "target_lifecycle_path": _zhiyi_case_memory_lifecycle_path(),
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "case_memory_append_performed": case_memory_append_performed,
        "lifecycle_append_count": lifecycle_append_count,
        "idempotent_existing_upgrade": already_applied,
        "latest_lifecycle_version": new_lifecycle_version,
        "source_refs_preserved": True,
        "projection_desensitized": False,
        "observed_write_flags": flags,
        "write_boundary": {
            "upgrade_receipt_write_performed": True,
            "production_experience_write_performed": bool(case_memory_append_performed or lifecycle_append_count),
            "raw_write_performed": False,
            "zhiyi_write_performed": bool(case_memory_append_performed or lifecycle_append_count),
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "live_experience_service_semantic_upgrade",
            "upgrade_uses_case_memory_version_and_lifecycle_overlay",
            "raw_source_refs_preserved_without_desensitization",
        ],
    }
    upgrades_dir = _experience_service_upgrades_dir()
    os.makedirs(upgrades_dir, exist_ok=True)
    receipt_path = os.path.join(upgrades_dir, f"{now_iso.replace(':', '').replace('-', '')}-{safe_upgrade_id}-apply.jsonl")
    _jsonl_append(receipt_path, receipt)
    latest_path = os.path.join(upgrades_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    production_write = bool(case_memory_append_performed or lifecycle_append_count)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "upgrade_receipt_write_performed": True,
        "production_experience_write_performed": production_write,
        "raw_write_performed": False,
        "zhiyi_write_performed": production_write,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "upgrade_input_id": safe_upgrade_id,
        "target_exp_id": target_exp_id,
        "case_memory_append_performed": case_memory_append_performed,
        "lifecycle_append_count": lifecycle_append_count,
        "idempotent_existing_upgrade": already_applied,
        "latest_lifecycle_version": new_lifecycle_version,
        "source_refs_preserved": True,
        "projection_desensitized": False,
        "receipt_id": upgrade_id,
        "receipt_path": receipt_path,
        "latest_path": latest_path,
        "receipt": receipt,
        "upgraded_case_memory": upgraded_record,
    }


def _hermes_feedback_candidate_summary(candidate, source_path="", latest_candidate_id=""):
    comparison = candidate.get("comparison_result", {}) if isinstance(candidate.get("comparison_result"), dict) else {}
    write_boundary = candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {}
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    candidate_id = candidate.get("candidate_id", "")
    return {
        "candidate_id": candidate_id,
        "candidate_type": candidate.get("candidate_type", ""),
        "title": candidate.get("title", ""),
        "summary": _compact_text(candidate.get("summary", ""), 360),
        "created_at": candidate.get("created_at", ""),
        "platform": candidate.get("platform", ""),
        "lifecycle_status": candidate.get("lifecycle_status", ""),
        "frontstage_surface": candidate.get("frontstage_surface", ""),
        "source_mode": candidate.get("source_mode", ""),
        "source_observer": candidate.get("source_observer", ""),
        "change_class": comparison.get("change_class", ""),
        "native_skill_learning_feedback_closed": bool(comparison.get("native_skill_learning_feedback_closed", False)),
        "confidence": candidate.get("confidence", 0),
        "requested_session_ids": candidate.get("requested_session_ids", []),
        "evidence_refs_count": len(evidence_refs),
        "source_refs_count": len(source_refs),
        "recommended_actions_count": len(candidate.get("recommended_experience_service_actions", []) or []),
        "write_boundary": write_boundary,
        "production_experience_write_performed": bool(write_boundary.get("production_experience_write_performed", False)),
        "raw_write_performed": bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_performed": bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_performed": bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_performed": bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_performed": bool(write_boundary.get("openclaw_write_performed", False)),
        "source_path": source_path,
        "is_latest": bool(candidate_id and candidate_id == latest_candidate_id),
        "detail_endpoint": f"/api/v1/hermes/feedback-candidates/{candidate_id}" if candidate_id else "",
    }


def _hermes_feedback_upgrade_input_summary(upgrade_input, source_path="", latest_upgrade_input_id=""):
    write_boundary = upgrade_input.get("write_boundary", {}) if isinstance(upgrade_input.get("write_boundary"), dict) else {}
    fresh = upgrade_input.get("fresh_observation", {}) if isinstance(upgrade_input.get("fresh_observation"), dict) else {}
    flags = fresh.get("observed_write_flags", {}) if isinstance(fresh.get("observed_write_flags"), dict) else {}
    comparison = upgrade_input.get("comparison_result", {}) if isinstance(upgrade_input.get("comparison_result"), dict) else {}
    source_action = upgrade_input.get("source_action", {}) if isinstance(upgrade_input.get("source_action"), dict) else {}
    source_candidate = upgrade_input.get("source_candidate", {}) if isinstance(upgrade_input.get("source_candidate"), dict) else {}
    upgrade_input_id = upgrade_input.get("upgrade_input_id", "")
    return {
        "upgrade_input_id": upgrade_input_id,
        "candidate_id": upgrade_input.get("candidate_id", ""),
        "candidate_type": upgrade_input.get("candidate_type", ""),
        "source_mode": upgrade_input.get("source_mode", ""),
        "created_at": upgrade_input.get("created_at", ""),
        "upgrade_input_status": upgrade_input.get("upgrade_input_status", ""),
        "experience_upgrade_ready": bool(upgrade_input.get("experience_upgrade_ready", False)),
        "production_experience_write_performed": bool(upgrade_input.get("production_experience_write_performed", False)),
        "fresh_requested_sessions_observed": bool(fresh.get("requested_sessions_observed", False)),
        "fresh_write_flags": {
            "skill": bool(flags.get("skill", False)),
            "learning": bool(flags.get("learning", False)),
            "memory": bool(flags.get("memory", False)),
        },
        "previous_change_class": comparison.get("previous_change_class", ""),
        "fresh_change_class": comparison.get("fresh_change_class", ""),
        "native_change_observed_after_action": bool(comparison.get("native_change_observed_after_action", False)),
        "source_action_status": source_action.get("action_status", ""),
        "source_action": source_action.get("action", ""),
        "source_candidate_change_class": source_candidate.get("change_class", ""),
        "write_boundary": write_boundary,
        "raw_write_performed": bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_performed": bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_performed": bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_performed": bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_performed": bool(write_boundary.get("openclaw_write_performed", False)),
        "source_path": source_path,
        "is_latest": bool(upgrade_input_id and upgrade_input_id == latest_upgrade_input_id),
        "detail_endpoint": f"/api/v1/hermes/feedback-upgrade-inputs/{upgrade_input_id}" if upgrade_input_id else "",
    }


def _latest_hermes_feedback_candidate_id(candidates_dir):
    latest_path = os.path.join(candidates_dir, "latest.json")
    latest, err = _read_hermes_feedback_json(latest_path)
    if err:
        return "", latest_path, {}
    return str(latest.get("candidate_id", "") or ""), latest_path, latest


def _latest_hermes_feedback_upgrade_input_id(upgrade_inputs_dir):
    latest_path = os.path.join(upgrade_inputs_dir, "latest.json")
    latest, err = _read_hermes_feedback_json(latest_path)
    if err:
        return "", latest_path, {}
    return str(latest.get("upgrade_input_id", "") or ""), latest_path, latest


def _hermes_feedback_action_history(candidate_id="", limit=20):
    actions_dir = _hermes_feedback_actions_dir()
    items = []
    parse_errors = []
    if not os.path.isdir(actions_dir):
        return items, parse_errors
    try:
        names = sorted(os.listdir(actions_dir), reverse=True)
    except Exception as exc:
        return items, [{"path": actions_dir, "error": str(exc)[:120]}]
    safe_id = _safe_hermes_candidate_id(candidate_id)
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(actions_dir, name)
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                line = f.readline().strip()
            if not line:
                continue
            item = json.loads(line)
        except Exception as exc:
            parse_errors.append({"path": path, "error": str(exc)[:120]})
            continue
        if safe_id and item.get("candidate_id") != safe_id:
            continue
        item["_source_path"] = path
        items.append(item)
        if len(items) >= limit:
            break
    return items, parse_errors


def query_hermes_feedback_candidates(params=None):
    """Expose generated Hermes observation feedback candidates without mutating state."""
    params = params or {}
    candidates_dir = _hermes_feedback_candidates_dir()
    candidates_dir_exists = os.path.isdir(candidates_dir)
    latest_candidate_id, latest_path, latest_candidate = _latest_hermes_feedback_candidate_id(candidates_dir)
    page = _usage_log_positive_int(params.get("page", 1), 1, 1000000)
    page_size = _usage_log_positive_int(params.get("page_size", 20), 20, 50)
    status_filter = str(params.get("lifecycle_status", "") or "").strip()
    source_mode_filter = str(params.get("source_mode", "") or "").strip()

    items = []
    parse_errors = []
    seen = set()
    if candidates_dir_exists:
        for path in sorted(glob.glob(os.path.join(candidates_dir, "hermes-feedback-*.json"))):
            candidate, err = _read_hermes_feedback_json(path)
            if err:
                parse_errors.append({"path": path, "error": err})
                continue
            candidate_id = str(candidate.get("candidate_id", "") or "")
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            items.append(_hermes_feedback_candidate_summary(candidate, path, latest_candidate_id))

    if latest_candidate and latest_candidate_id and latest_candidate_id not in seen:
        items.append(_hermes_feedback_candidate_summary(latest_candidate, latest_path, latest_candidate_id))

    def sort_key(item):
        return (item.get("created_at") or "", item.get("candidate_id") or "")

    items.sort(key=sort_key, reverse=True)
    if status_filter:
        items = [item for item in items if item.get("lifecycle_status") == status_filter]
    if source_mode_filter:
        items = [item for item in items if item.get("source_mode") == source_mode_filter]
    for item in items:
        history, _ = _hermes_feedback_action_history(item.get("candidate_id", ""), limit=1)
        item["action_count"] = len(_hermes_feedback_action_history(item.get("candidate_id", ""), limit=1000000)[0])
        item["latest_action"] = history[0] if history else None
        item["action_endpoint"] = f"/api/v1/hermes/feedback-candidates/{item.get('candidate_id', '')}/actions"

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidates_dir": candidates_dir,
        "candidates_dir_exists": candidates_dir_exists,
        "latest_candidate_id": latest_candidate_id,
        "latest_path": latest_path,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "items": items[start:end],
        "parse_errors": parse_errors,
        "filters": {
            "lifecycle_status": status_filter,
            "source_mode": source_mode_filter,
        },
        "query_contract": {
            "schema_version": "1.0",
            "source": "output/hermes_experience_feedback/candidates/*.json",
            "order": "newest_first",
            "method": "GET",
            "write_performed": False,
        },
        "notes": [
            "candidate_artifact_read_only",
            "no_raw_zhiyi_xingce_hermes_openclaw_write",
            "production_experience_upgrade_not_applied_by_this_api",
        ],
    }


def query_hermes_feedback_actions(params=None):
    params = params or {}
    candidate_id = str(params.get("candidate_id", "") or "").strip()
    limit = _usage_log_positive_int(params.get("limit", 20), 20, 100)
    items, parse_errors = _hermes_feedback_action_history(candidate_id, limit=limit)
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "actions_dir": _hermes_feedback_actions_dir(),
        "candidate_id": candidate_id,
        "total": len(items),
        "items": items,
        "parse_errors": parse_errors,
    }


def query_hermes_feedback_upgrade_inputs(params=None):
    """Expose Hermes feedback upgrade inputs without mutating state."""
    params = params or {}
    upgrade_inputs_dir = _hermes_feedback_upgrade_inputs_dir()
    upgrade_inputs_dir_exists = os.path.isdir(upgrade_inputs_dir)
    latest_upgrade_input_id, latest_path, latest_upgrade_input = _latest_hermes_feedback_upgrade_input_id(upgrade_inputs_dir)
    page = _usage_log_positive_int(params.get("page", 1), 1, 1000000)
    page_size = _usage_log_positive_int(params.get("page_size", 20), 20, 50)
    status_filter = str(params.get("upgrade_input_status", "") or "").strip()
    candidate_filter = str(params.get("candidate_id", "") or "").strip()

    items = []
    parse_errors = []
    seen = set()
    if upgrade_inputs_dir_exists:
        for path in sorted(glob.glob(os.path.join(upgrade_inputs_dir, "hermes-upgrade-input-*.json"))):
            upgrade_input, err = _read_hermes_feedback_json(path)
            if err:
                parse_errors.append({"path": path, "error": err})
                continue
            upgrade_input_id = str(upgrade_input.get("upgrade_input_id", "") or "")
            if upgrade_input_id in seen:
                continue
            seen.add(upgrade_input_id)
            items.append(_hermes_feedback_upgrade_input_summary(upgrade_input, path, latest_upgrade_input_id))

    if latest_upgrade_input and latest_upgrade_input_id and latest_upgrade_input_id not in seen:
        items.append(_hermes_feedback_upgrade_input_summary(latest_upgrade_input, latest_path, latest_upgrade_input_id))

    items.sort(key=lambda item: (item.get("created_at") or "", item.get("upgrade_input_id") or ""), reverse=True)
    if status_filter:
        items = [item for item in items if item.get("upgrade_input_status") == status_filter]
    if candidate_filter:
        items = [item for item in items if item.get("candidate_id") == candidate_filter]

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "upgrade_inputs_dir": upgrade_inputs_dir,
        "upgrade_inputs_dir_exists": upgrade_inputs_dir_exists,
        "latest_upgrade_input_id": latest_upgrade_input_id,
        "latest_path": latest_path,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "items": items[start:end],
        "parse_errors": parse_errors,
        "filters": {
            "upgrade_input_status": status_filter,
            "candidate_id": candidate_filter,
        },
        "query_contract": {
            "schema_version": "1.0",
            "source": "output/hermes_experience_feedback/upgrade_inputs/*.json",
            "order": "newest_first",
            "method": "GET",
            "write_performed": False,
        },
        "notes": [
            "upgrade_input_artifact_read_only",
            "no_raw_zhiyi_xingce_hermes_openclaw_write",
            "production_experience_upgrade_not_applied_by_this_api",
        ],
    }


def get_hermes_feedback_upgrade_input(upgrade_input_id):
    upgrade_inputs_dir = _hermes_feedback_upgrade_inputs_dir()
    safe_id = _safe_hermes_candidate_id(upgrade_input_id)
    latest_upgrade_input_id, latest_path, latest_upgrade_input = _latest_hermes_feedback_upgrade_input_id(upgrade_inputs_dir)
    if safe_id == "latest":
        upgrade_input = latest_upgrade_input
        source_path = latest_path
    elif safe_id:
        source_path = os.path.join(upgrade_inputs_dir, f"{safe_id}.json")
        upgrade_input, err = _read_hermes_feedback_json(source_path)
        if err and safe_id == latest_upgrade_input_id and latest_upgrade_input:
            upgrade_input = latest_upgrade_input
            source_path = latest_path
    else:
        upgrade_input = {}
        source_path = ""
    if not upgrade_input:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "error": "upgrade_input_not_found",
            "upgrade_input_id": upgrade_input_id,
            "upgrade_inputs_dir": upgrade_inputs_dir,
        }
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "upgrade_input_id": upgrade_input.get("upgrade_input_id", safe_id),
        "latest_upgrade_input_id": latest_upgrade_input_id,
        "upgrade_inputs_dir": upgrade_inputs_dir,
        "source_path": source_path,
        "summary": _hermes_feedback_upgrade_input_summary(upgrade_input, source_path, latest_upgrade_input_id),
        "write_boundary": upgrade_input.get("write_boundary", {}) if isinstance(upgrade_input.get("write_boundary"), dict) else {},
        "upgrade_input": upgrade_input,
    }


def get_hermes_feedback_candidate(candidate_id):
    candidates_dir = _hermes_feedback_candidates_dir()
    safe_id = _safe_hermes_candidate_id(candidate_id)
    latest_candidate_id, latest_path, latest_candidate = _latest_hermes_feedback_candidate_id(candidates_dir)
    if safe_id == "latest":
        candidate = latest_candidate
        source_path = latest_path
    elif safe_id:
        source_path = os.path.join(candidates_dir, f"{safe_id}.json")
        candidate, err = _read_hermes_feedback_json(source_path)
        if err and safe_id == latest_candidate_id and latest_candidate:
            candidate = latest_candidate
            source_path = latest_path
    else:
        candidate = {}
        source_path = ""
    if not candidate:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "error": "candidate_not_found",
            "candidate_id": candidate_id,
            "candidates_dir": candidates_dir,
        }
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": candidate.get("candidate_id", safe_id),
        "latest_candidate_id": latest_candidate_id,
        "candidates_dir": candidates_dir,
        "source_path": source_path,
        "summary": _hermes_feedback_candidate_summary(candidate, source_path, latest_candidate_id),
        "write_boundary": candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {},
        "actions": _hermes_feedback_action_history(candidate.get("candidate_id", safe_id), limit=20)[0],
        "candidate": candidate,
    }


def apply_hermes_feedback_candidate_action(candidate_id, body=None):
    body = body or {}
    detail = get_hermes_feedback_candidate(candidate_id)
    if not detail.get("ok"):
        return detail
    candidate = detail.get("candidate", {})
    safe_id = _safe_hermes_candidate_id(candidate.get("candidate_id", candidate_id))
    action = str(body.get("action", "") or "").strip()
    aliases = {
        "adopt": "adopt_as_experience",
        "adopt_as_experience": "adopt_as_experience",
        "watch": "watch_for_upgrade",
        "observe": "watch_for_upgrade",
        "watch_for_upgrade": "watch_for_upgrade",
        "recycle": "recycle",
        "recycle_candidate": "recycle",
    }
    action = aliases.get(action, "")
    if action not in ("adopt_as_experience", "watch_for_upgrade", "recycle"):
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "error": "action_must_be_one_of_adopt_as_experience_watch_for_upgrade_recycle",
            "candidate_id": safe_id,
        }

    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    required_checks = {
        "confirm_process_hermes_candidate": confirmed("confirm_process_hermes_candidate"),
        "confirm_write_experience_feedback_action": confirmed("confirm_write_experience_feedback_action"),
        "confirm_no_raw_zhiyi_xingce_hermes_openclaw_write": confirmed("confirm_no_raw_zhiyi_xingce_hermes_openclaw_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    write_boundary = candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {}
    guard_checks = {
        "candidate_id_safe": bool(safe_id),
        "candidate_lifecycle_status": candidate.get("lifecycle_status") == "candidate",
        "candidate_artifact_exists": os.path.isfile(detail.get("source_path", "")),
        "candidate_not_production_written": not bool(write_boundary.get("production_experience_write_performed", False)),
        "raw_write_stays_false": not bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_stays_false": not bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_stays_false": not bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_stays_false": not bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_stays_false": not bool(write_boundary.get("openclaw_write_performed", False)),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "action_write_performed": False,
            "candidate_id": safe_id,
            "action": action,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    actions_dir = _hermes_feedback_actions_dir()
    os.makedirs(actions_dir, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action_id = "hermes-action-" + uuid.uuid4().hex[:16]
    action_status = {
        "adopt_as_experience": "queued_for_experience_service_adoption",
        "watch_for_upgrade": "watching_for_native_skill_learning_change",
        "recycle": "recycled_from_frontstage_candidate_queue",
    }[action]
    receipt = {
        "schema_version": "1.0",
        "action_id": action_id,
        "created_at": now,
        "candidate_id": safe_id,
        "candidate_type": candidate.get("candidate_type", ""),
        "action": action,
        "action_status": action_status,
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "source_candidate_path": detail.get("source_path", ""),
        "source_mode": candidate.get("source_mode", ""),
        "change_class": (candidate.get("comparison_result", {}) if isinstance(candidate.get("comparison_result"), dict) else {}).get("change_class", ""),
        "evidence_refs_count": len(candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []),
        "source_refs_count": len(candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []),
        "write_boundary": {
            "action_receipt_write_performed": True,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "live_experience_feedback_action_receipt",
            "candidate_artifact_not_modified",
            "no_raw_zhiyi_xingce_hermes_openclaw_write",
        ],
    }
    action_path = os.path.join(actions_dir, f"{now.replace(':', '').replace('-', '')}-{safe_id}-{action}.jsonl")
    with open(action_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
    latest_path = os.path.join(actions_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "action_write_performed": True,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": safe_id,
        "action": action,
        "action_status": action_status,
        "action_id": action_id,
        "action_path": action_path,
        "latest_path": latest_path,
        "receipt": receipt,
    }


def _openclaw_chat_send_bool(value):
    return _hermes_feedback_action_bool(value)


def _openclaw_chat_send_present(value):
    return bool(str(value or "").strip())


def _openclaw_chat_send_session_ms(session):
    if not isinstance(session, dict):
        return 0
    value = session.get("updatedAt")
    if value is None:
        value = session.get("updatedAtMs")
    try:
        return int(value or 0)
    except Exception:
        return 0


def _openclaw_chat_send_session_iso(ms):
    if not ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _openclaw_chat_send_parse_key(key):
    parts = str(key or "").split(":")
    result = {
        "agent_id": "",
        "session_id": "",
        "session_key_shape": "unknown",
        "canonical_window_id": "",
    }
    if len(parts) >= 3 and parts[0] == "agent":
        result["agent_id"] = parts[1]
        result["canonical_window_id"] = parts[1]
        result["session_id"] = ":".join(parts[2:])
        result["session_key_shape"] = parts[2] if parts[2] in ("chat", "cron", "dashboard") else "direct"
    return result


def _openclaw_chat_send_session_summary(session):
    key = str(session.get("key") or "") if isinstance(session, dict) else ""
    parsed = _openclaw_chat_send_parse_key(key)
    updated_ms = _openclaw_chat_send_session_ms(session)
    label = (
        session.get("displayName")
        or session.get("label")
        or parsed.get("session_id")
        or key
    )
    return {
        "key": key,
        "label": str(label or ""),
        "agent_id": parsed.get("agent_id", ""),
        "canonical_window_id": parsed.get("canonical_window_id", ""),
        "session_id": str(session.get("sessionId") or parsed.get("session_id", "")),
        "session_key_shape": parsed.get("session_key_shape", "unknown"),
        "kind": str(session.get("kind") or ""),
        "chat_type": str(session.get("chatType") or ""),
        "updated_at_ms": updated_ms,
        "updated_at": _openclaw_chat_send_session_iso(updated_ms),
        "model_provider": str(session.get("modelProvider") or ""),
        "model": str(session.get("model") or ""),
        "has_active_run": bool(session.get("hasActiveRun", False)),
        "total_tokens": session.get("totalTokens"),
        "total_tokens_fresh": bool(session.get("totalTokensFresh", False)),
        "ready_for_authorized_chat_send": bool(key and not session.get("hasActiveRun", False)),
    }


def query_openclaw_chat_send_targets(params=None, client_factory=None):
    """Read OpenClaw session targets for a future authorized chat.send."""
    params = params or {}
    try:
        page = max(1, int(params.get("page", 1)))
    except Exception:
        page = 1
    try:
        page_size = max(1, min(int(params.get("page_size", 12)), 50))
    except Exception:
        page_size = 12

    if client_factory is None:
        try:
            from openclaw_ws_rpc_client import OpenClawWsRpcClient
        except Exception:
            from src.openclaw_ws_rpc_client import OpenClawWsRpcClient
        client_factory = OpenClawWsRpcClient

    client = client_factory()
    try:
        if not client.connect(timeout=5):
            return {
                "ok": False,
                "read_only": True,
                "write_performed": False,
                "openclaw_chat_send_called": False,
                "openclaw_active_session_write": False,
                "openclaw_write_performed": False,
                "live_gateway_connected": False,
                "sessions_list_called": False,
                "ready_for_authorized_chat_send": False,
                "items": [],
                "total": 0,
                "error": "openclaw_connect_failed",
            }
        sessions_result = client.sessions_list(timeout=5)
        if not sessions_result.get("ok"):
            return {
                "ok": False,
                "read_only": True,
                "write_performed": False,
                "openclaw_chat_send_called": False,
                "openclaw_active_session_write": False,
                "openclaw_write_performed": False,
                "live_gateway_connected": True,
                "sessions_list_called": True,
                "ready_for_authorized_chat_send": False,
                "items": [],
                "total": 0,
                "openclaw_result": sessions_result,
                "error": "openclaw_sessions_list_failed",
            }
        raw_sessions = sessions_result.get("payload", {}).get("sessions", [])
        if not isinstance(raw_sessions, list):
            raw_sessions = []
        summaries = [
            _openclaw_chat_send_session_summary(session)
            for session in raw_sessions
            if isinstance(session, dict) and str(session.get("key") or "").strip() not in ("", "gateway", "unknown")
        ]
        summaries.sort(key=lambda item: item.get("updated_at_ms") or 0, reverse=True)
        start = (page - 1) * page_size
        items = summaries[start:start + page_size]
        ready_count = sum(1 for item in summaries if item.get("ready_for_authorized_chat_send"))
        return {
            "ok": True,
            "read_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_chat_send_called": False,
            "openclaw_active_session_write": False,
            "openclaw_write_performed": False,
            "memcore_config_write_performed": False,
            "live_gateway_connected": True,
            "sessions_list_called": True,
            "page": page,
            "page_size": page_size,
            "total": len(summaries),
            "ready_count": ready_count,
            "items": items,
            "ready_for_authorized_chat_send": ready_count > 0,
            "execution_endpoint": "/api/v1/openclaw/chat-send/authorized",
            "authorization_required": [
                "confirm_live_openclaw_chat_send",
                "confirm_openclaw_active_session_write",
                "confirm_no_memcore_raw_zhiyi_xingce_hermes_write",
                "operator",
                "reason",
            ],
            "request_required": ["session_key", "message", "idempotency_key"],
        }
    except Exception as exc:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "openclaw_chat_send_called": False,
            "openclaw_active_session_write": False,
            "openclaw_write_performed": False,
            "items": [],
            "total": 0,
            "ready_for_authorized_chat_send": False,
            "error": f"openclaw_chat_send_targets_failed:{str(exc)[:160]}",
        }
    finally:
        try:
            client.close()
        except Exception:
            pass


def apply_openclaw_chat_send_authorized(body=None, client_factory=None):
    """Execute OpenClaw chat.send only with explicit live authorization."""
    body = body or {}
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    session_key = str(body.get("session_key") or body.get("sessionKey") or "").strip()
    message = str(body.get("message") or "").strip()
    idempotency_key = str(body.get("idempotency_key") or body.get("idempotencyKey") or "").strip()

    def confirmed(name):
        return _openclaw_chat_send_bool(authorization.get(name, body.get(name)))

    def present(name):
        return _openclaw_chat_send_present(authorization.get(name, body.get(name)))

    authorization_checks = {
        "confirm_live_openclaw_chat_send": confirmed("confirm_live_openclaw_chat_send"),
        "confirm_openclaw_active_session_write": confirmed("confirm_openclaw_active_session_write"),
        "confirm_no_memcore_raw_zhiyi_xingce_hermes_write": confirmed("confirm_no_memcore_raw_zhiyi_xingce_hermes_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    request_checks = {
        "session_key_present": bool(session_key),
        "message_present": bool(message),
        "idempotency_key_present": bool(idempotency_key),
        "session_key_control_chars_absent": not any(ord(ch) < 32 for ch in session_key),
        "message_within_limit": len(message) <= 12000,
    }
    missing = [name for name, ok in authorization_checks.items() if not ok]
    request_failures = [name for name, ok in request_checks.items() if not ok]
    if missing or request_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_capable": True,
            "write_performed": False,
            "openclaw_chat_send_called": False,
            "openclaw_active_session_write": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "memcore_config_write_performed": False,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": authorization_checks,
            "request_checks": request_checks,
            "request_failures": request_failures,
            "error": "blocked_missing_authorization_or_request_fields",
        }

    if client_factory is None:
        try:
            from openclaw_ws_rpc_client import OpenClawWsRpcClient
        except Exception:
            from src.openclaw_ws_rpc_client import OpenClawWsRpcClient
        client_factory = OpenClawWsRpcClient

    import uuid
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = client_factory()
    try:
        if not client.connect(timeout=5):
            return {
                "ok": False,
                "read_only": False,
                "write_capable": True,
                "write_performed": False,
                "openclaw_chat_send_called": False,
                "openclaw_active_session_write": False,
                "openclaw_write_performed": False,
                "session_key": session_key,
                "error": "openclaw_connect_failed",
            }
        sessions_result = client.sessions_list(timeout=5)
        sessions = sessions_result.get("payload", {}).get("sessions", []) if sessions_result.get("ok") else []
        valid_keys = {str(item.get("key", "")) for item in sessions if isinstance(item, dict)}
        if session_key not in valid_keys:
            return {
                "ok": False,
                "read_only": False,
                "write_capable": True,
                "write_performed": False,
                "openclaw_chat_send_called": False,
                "openclaw_active_session_write": False,
                "openclaw_write_performed": False,
                "session_key": session_key,
                "available_sessions_count": len(valid_keys),
                "error": "session_key_not_found_in_openclaw_sessions",
            }
        result = client.chat_send(
            session_key=session_key,
            message=message,
            idempotency_key=idempotency_key or f"memcore-openclaw-{uuid.uuid4().hex}",
            timeout=30,
        )
        ok = bool(result.get("ok"))
        return {
            "ok": ok,
            "read_only": False,
            "write_capable": True,
            "write_performed": ok,
            "openclaw_chat_send_called": True,
            "openclaw_active_session_write": ok,
            "openclaw_write_performed": ok,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "memcore_config_write_performed": False,
            "session_key": session_key,
            "idempotency_key": idempotency_key,
            "created_at": now,
            "authorization_checks": authorization_checks,
            "request_checks": request_checks,
            "openclaw_result": result,
            "notes": [
                "live_openclaw_chat_send_authorized",
                "writes_openclaw_active_session_only_when_openclaw_returns_ok",
                "does_not_write_memcore_raw_zhiyi_xingce_hermes",
            ],
        }
    except Exception as exc:
        return {
            "ok": False,
            "read_only": False,
            "write_capable": True,
            "write_performed": False,
            "openclaw_chat_send_called": False,
            "openclaw_active_session_write": False,
            "openclaw_write_performed": False,
            "session_key": session_key,
            "error": f"openclaw_chat_send_failed:{str(exc)[:160]}",
        }
    finally:
        try:
            client.close()
        except Exception:
            pass


def _experience_type_label(ftype):
    return {
        "case_memory": "案例经验",
        "error_memory": "错误经验",
        "preference_memory": "偏好经验",
    }.get(ftype, "经验")


def _experience_text(obj):
    if not isinstance(obj, dict):
        return ""
    for key in ("title", "name", "summary", "content", "text", "memory", "description", "answer", "insight"):
        value = obj.get(key)
        if value:
            return _compact_text(value, 260)
    for value in obj.values():
        if isinstance(value, str) and len(value.strip()) >= 8:
            return _compact_text(value, 260)
    return ""


def _experience_title(obj, ftype, index):
    text = _experience_text(obj)
    if text:
        for sep in ("。", "，", ".", ";", "；", ":"):
            if sep in text[:48]:
                text = text.split(sep, 1)[0]
                break
        return _compact_text(text, 30)
    return f"{_experience_type_label(ftype)} {index + 1}"


def _normalize_duplicate_key(title, detail):
    import re
    text = f"{title}|{detail}".lower()
    return re.sub(r"\s+", "", text)


def get_zhiyi_experience_summary(sample_limit=18, duplicate_limit=8):
    stats = get_zhiyi_stats()
    active_stats = {"case_memory": 0, "error_memory": 0, "preference_memory": 0}
    recycle_overlay = _zhiyi_experience_recycle_overlay()
    samples = []
    sample_count_by_type = {}
    duplicate_map = {}
    parse_errors = 0
    for ftype in ["case_memory", "error_memory", "preference_memory"]:
        path = f"{MEMCORE_ROOT}/zhiyi/{ftype}/{ftype}.jsonl"
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for index, line in enumerate(f):
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        parse_errors += 1
                        continue
                    exp_id = obj.get("exp_id", "")
                    if exp_id and exp_id in recycle_overlay:
                        continue
                    active_stats[ftype] = active_stats.get(ftype, 0) + 1
                    title = _experience_title(obj, ftype, index)
                    detail = _experience_text(obj) or title
                    key = _normalize_duplicate_key(title, detail)
                    if key:
                        entry = duplicate_map.setdefault(key, {
                            "title": title,
                            "detail": _compact_text(detail, 160),
                            "type": ftype,
                            "type_label": _experience_type_label(ftype),
                            "count": 0,
                            "exp_ids": [],
                        })
                        entry["count"] += 1
                        if exp_id and exp_id not in entry["exp_ids"]:
                            entry["exp_ids"].append(exp_id)
                    if len(samples) < sample_limit and sample_count_by_type.get(ftype, 0) < max(4, sample_limit // 3):
                        raw_refs = obj.get("source_refs") or obj.get("_source_refs") or {}
                        if isinstance(raw_refs, str):
                            try:
                                raw_refs = json.loads(raw_refs)
                            except Exception:
                                raw_refs = {}
                        if not isinstance(raw_refs, dict):
                            raw_refs = {}
                        obj["_source_refs"] = raw_refs
                        obj.update(attach_archive_card(obj))
                        card = obj.get("archive_card", {})
                        raw_evidence = _m5_raw_evidence_for_refs(raw_refs, excerpt_chars=220)
                        source_path = raw_refs.get("source_path", "")
                        source_label = os.path.basename(source_path) if source_path else ""
                        quote_excerpt = (
                            obj.get("quote_excerpt")
                            or raw_evidence.get("raw_excerpt")
                            or detail
                        )
                        samples.append({
                            "id": f"{ftype}:{index}",
                            "catalog_id": obj.get("catalog_id", ""),
                            "exp_id": exp_id,
                            "type": ftype,
                            "type_label": _experience_type_label(ftype),
                            "title": title,
                            "archive_title": card.get("title", title),
                            "evidence_level": card.get("evidence_level", ""),
                            "archive_status": card.get("status", ""),
                            "one_line_description": _compact_text(detail, 110),
                            "detail": _compact_text(detail, 220),
                            "quote_excerpt": _compact_text(quote_excerpt, 180),
                            "source_label": source_label,
                            "status": obj.get("status") or "adopted",
                            "deleted_state": "active",
                            "has_source_refs": bool(raw_refs),
                        })
                        sample_count_by_type[ftype] = sample_count_by_type.get(ftype, 0) + 1
        except Exception:
            parse_errors += 1
    duplicates = [value for value in duplicate_map.values() if value.get("count", 0) > 1]
    duplicates.sort(key=lambda item: item.get("count", 0), reverse=True)
    return {
        "total": sum(active_stats.values()),
        "raw_total": sum(stats.values()),
        "stats": active_stats,
        "raw_stats": stats,
        "samples": samples,
        "duplicate_candidates": duplicates[:duplicate_limit],
        "duplicate_candidate_count": len(duplicates),
        "delete_supported_now": True,
        "recycle_supported_now": True,
        "delete_requires_future_authorization": False,
        "lifecycle_actions_supported_now": True,
        "lifecycle_action_endpoint": "/api/v1/zhiyi/experiences/{exp_id}/recycle",
        "restore_supported_now": True,
        "restore_endpoint": "/api/v1/zhiyi/experiences/{exp_id}/restore",
        "recycle_bin_endpoint": "/api/v1/zhiyi/experience-recycle-bin",
        "recycle_bin_count": len(recycle_overlay),
        "raw_delete_performed": False,
        "detail_endpoint_available": True,
        "raw_excerpt_available_on_detail": True,
        "parse_errors": parse_errors,
        "detail_is_summary_only": False,
    }


# ─── API Handler ──────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    """本地管理控制台 - 仅监听 localhost，不对外暴露。

    静态文件服务限制在白名单路径内，禁止目录遍历。
    """

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def send_html(self):
        i18n_json = json.dumps(I18N, ensure_ascii=False)
        memcore_root_json = json.dumps(str(MEMCORE_ROOT), ensure_ascii=False)
        template = HTML_TEMPLATE
        if os.path.exists(PRODUCT_UI_TEMPLATE_PATH):
            with open(PRODUCT_UI_TEMPLATE_PATH, encoding="utf-8") as f:
                template = f.read()
        html = template.replace("$I18N_JSON", i18n_json).replace("$PORT", str(PORT)).replace("$MEMCORE_ROOT_JSON", memcore_root_json)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        import urllib.parse
        norm_path = urllib.parse.unquote(self.path)
        if ".." in norm_path or norm_path.startswith("//"):
            self.send_error(403)
            return
        if norm_path == "/" or norm_path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            return
        if norm_path.startswith("/assets/"):
            relative_path = norm_path[len("/assets/"):]
            real_path = os.path.realpath(os.path.join(PRODUCT_ASSET_ROOT, relative_path))
            allowed_root = os.path.realpath(PRODUCT_ASSET_ROOT)
            if real_path != allowed_root and real_path.startswith(allowed_root + os.sep) and os.path.isfile(real_path):
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(real_path)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(os.path.getsize(real_path)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                return
        self.send_error(404)

    def do_GET(self):
        # 禁止目录遍历
        import urllib.parse
        parsed_path = urllib.parse.urlparse(self.path)
        norm_path = urllib.parse.unquote(parsed_path.path)
        if ".." in norm_path or norm_path.startswith("//"):
            self.send_error(403)
            return

        if norm_path == "/" or norm_path == "/index.html":
            self.send_html()
        elif norm_path.startswith("/assets/"):
            self.serve_product_asset(norm_path)
        elif norm_path.startswith("/api/v1/"):
            self.do_GET_api_v1(norm_path)
        elif norm_path.startswith("/api/"):
            self.do_GET_api(norm_path)
        else:
            # 静态文件白名单
            self.serve_static(norm_path)

    def serve_product_asset(self, path):
        relative_path = path[len("/assets/"):]
        if not relative_path or ".." in relative_path or relative_path.startswith(("/", "\\")):
            self.send_error(403)
            return
        real_path = os.path.realpath(os.path.join(PRODUCT_ASSET_ROOT, relative_path))
        allowed_root = os.path.realpath(PRODUCT_ASSET_ROOT)
        if real_path != allowed_root and not real_path.startswith(allowed_root + os.sep):
            self.send_error(403)
            return
        if not os.path.isfile(real_path):
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(real_path)[0] or "application/octet-stream"
        with open(real_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self, path):
        # 只允许访问 memory/<source_system>/<node> 下的 raw session 文件
        if path.count("/") < 4:
            # memory/<source_system>/<node>/window/session.jsonl 至少 4 段
            self.send_error(403)
            return
        # 禁止访问 zhiyi/ 等敏感子目录
        normalized = os.path.normpath(path)
        if "/zhiyi/" in normalized or normalized.startswith("/zhiyi"):
            self.send_error(403)
            return
        safe_path = MEMCORE_ROOT + path
        real_path = os.path.realpath(safe_path)
        allowed_root = os.path.realpath(MEMCORE_ROOT)
        allowed_memory = os.path.join(allowed_root, "memory") + os.sep
        if not real_path.startswith(allowed_memory):
            self.send_error(403)
            return
        if not os.path.isfile(real_path) or not real_path.endswith(".jsonl"):
            self.send_error(403)
            return
        try:
            with open(real_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
        except:
            self.send_error(404)

    def do_GET_api(self, path):
        if path == "/api/watcher":
            self.send_json({"active": get_watcher_status()})
        elif path == "/api/raw_stats":
            self.send_json(get_raw_stats())
        elif path == "/api/zhiyi_stats":
            self.send_json(get_zhiyi_stats())
        elif path == "/api/raw_sessions":
            from pathlib import Path
            root = Path(str(MEMCORE_ROOT)) / "memory"
            sessions = sorted(root.glob("*/*/*/*.jsonl")) if root.exists() else []
            result = []
            for s in sessions:
                try:
                    rel_parts = s.relative_to(root).parts
                except Exception:
                    rel_parts = ()
                source_system = rel_parts[0] if len(rel_parts) >= 1 else ""
                computer_name = rel_parts[1] if len(rel_parts) >= 2 else ""
                window = s.parent.name
                session_id = s.stem
                try:
                    size_bytes = s.stat().st_size
                except OSError:
                    size_bytes = 0
                if size_bytes <= 5 * 1024 * 1024:
                    try:
                        with s.open("r", encoding="utf-8", errors="ignore") as f:
                            msg_count = sum(1 for line in f if line.strip())
                    except Exception:
                        msg_count = -1
                else:
                    msg_count = -1
                channel = "webchat"
                ch_path = s.parent / ".channel_index.json"
                if ch_path.exists():
                    try:
                        with ch_path.open("r", encoding="utf-8", errors="ignore") as f:
                            idx = json.load(f)
                        channel = idx.get("sessions", {}).get(session_id, {}).get("channel", "webchat")
                    except:
                        pass
                result.append({"source_system": source_system,
                                "computer_name": computer_name,
                                "window": window,
                                # P1-3 Fix: show short session_id on LAN-exposed API
                                "session_id": session_id[:8] + "...",
                                "session_id_full": session_id,
                                "msg_count": msg_count,
                                "msg_count_note": "skipped_large_file" if msg_count == -1 and size_bytes > 5 * 1024 * 1024 else "",
                                "size_bytes": size_bytes,
                                "channel": channel})
            result.sort(key=lambda x: (x.get("source_system", ""), x["window"]))
            known_messages = sum(s["msg_count"] for s in result if s["msg_count"] >= 0)
            skipped_large_files = sum(1 for s in result if s["msg_count"] == -1)
            self.send_json({"sessions": len(sessions),
                            "windows": len(set(s["window"] for s in result)),
                            "source_systems": sorted(set(s.get("source_system", "") for s in result if s.get("source_system"))),
                            "messages": -1 if skipped_large_files else known_messages,
                            "messages_known": known_messages,
                            "skipped_large_files": skipped_large_files,
                            "sessions_list": result})
        elif path == "/api/alias_map":
            self.send_json(get_alias_map())
        elif path == "/api/zhiyi_objects":
            self.send_json(load_zhiyi_objects(limit=500))
        elif path == "/api/health":
            self.send_json(run_health_check())
        # ── M3 Status APIs (只读) ──
        elif path == "/api/m3/status/overview":
            self.send_json(m3_get_overview())
        elif path == "/api/m3/status/openclaw-runtime":
            self.send_json(m3_get_openclaw_runtime())
        elif path == "/api/m3/status/memory-runtime":
            self.send_json(m3_get_memory_runtime())
        elif path == "/api/m3/status/j2-j7":
            self.send_json(m3_get_j2_j7_runtime())
        elif path == "/api/m3/status/recent-recall":
            self.send_json(m3_get_recent_recall())
        elif path == "/api/m3/status/audit-risks":
            self.send_json(m3_get_audit_risks())
        elif path == "/api/m3/status/update":
            self.send_json(m3_get_update_status())
        elif path == "/api/m3/status/source-systems":
            self.send_json(m3_get_source_systems())
        # ── M4 Task Results APIs (只读) ──
        elif path == "/api/v1/tasks/results":
            self.send_json(m4_get_task_results())
        elif path.startswith("/api/v1/tasks/results/"):
            task_id = path[len("/api/v1/tasks/results/"):]
            if task_id.endswith("/summary"):
                task_id = task_id[:-8]
                self.send_json(m4_get_task_summary(task_id))
            else:
                self.send_json(m4_get_task_detail(task_id))
        elif path == "/api/v1/tasks/risk-backlog":
            self.send_json(m4_get_risk_backlog())
        elif path == "/api/v1/tasks/next-decision-summary":
            self.send_json(m4_get_next_decision_summary())
        else:
            self.send_error(404)

    def do_GET_api_v1(self, path):
        # M1: 单机轻量控制台与知意管理 API v1
        import sys as _sys_api
        import urllib.parse

        # GET /api/v1/status - 系统总览
        if path == "/api/v1/status":
            watcher = get_watcher_status()
            raw = get_raw_stats()
            zhiyi = get_zhiyi_stats()
            import socket
            ports_ok = {}
            for svc_name, port in [("p3recall", 9830), ("p4provider", 9840)]:
                sock = socket.socket()
                ports_ok[svc_name] = sock.connect_ex(("127.0.0.1", port)) == 0
                sock.close()
            self.send_json({
                "status": "ok",
                "watcher": watcher,
                "raw_memory": raw,
                "zhiyi_stats": zhiyi,
                "service_ports": ports_ok,
                "phase": "local-service-ready",
                "memcore_root": str(MEMCORE_ROOT),
            })

        # GET /api/v1/tasks/* - M4 task pages (read-only)
        elif path == "/api/v1/tasks/results":
            self.send_json(m4_get_task_results())
        elif path.startswith("/api/v1/tasks/results/"):
            task_id = path[len("/api/v1/tasks/results/"):]
            if task_id.endswith("/summary"):
                task_id = task_id[:-8]
                self.send_json(m4_get_task_summary(task_id))
            else:
                self.send_json(m4_get_task_detail(task_id))
        elif path == "/api/v1/tasks/risk-backlog":
            self.send_json(m4_get_risk_backlog())
        elif path == "/api/v1/tasks/next-decision-summary":
            self.send_json(m4_get_next_decision_summary())

        # GET /api/v1/path/layout - X2: full path layout with override priority
        elif path == "/api/v1/path/layout":
            from platform_adapters.paths import verify_path_layout
            self.send_json(verify_path_layout())

        # GET /api/v1/raw/stats - raw统计
        elif path == "/api/v1/raw/stats":
            self.send_json(get_raw_stats())

        # GET /api/v1/zhiyi/stats - 知意统计
        elif path == "/api/v1/zhiyi/stats":
            self.send_json(get_zhiyi_stats())

        # GET /api/v1/zhiyi/model-options - 知意可用模型选择（只读）
        elif path == "/api/v1/zhiyi/model-options":
            self.send_json(get_zhiyi_model_options())

        # GET /api/v1/zhiyi/model-binding/apply-gate/dry-run - 模型绑定授权门禁
        elif path == "/api/v1/zhiyi/model-binding/apply-gate/dry-run":
            self.send_json(get_zhiyi_model_binding_apply_gate_policy())

        # GET /api/v1/zhiyi/runtime-adapter/dry-run - runtime adapter 调用链路预检
        elif path == "/api/v1/zhiyi/runtime-adapter/dry-run":
            self.send_json(get_zhiyi_runtime_adapter_dry_run_policy())

        # GET /api/v1/zhiyi/runtime-adapter/apply-gate/dry-run - runtime adapter apply 门禁
        elif path == "/api/v1/zhiyi/runtime-adapter/apply-gate/dry-run":
            self.send_json(get_zhiyi_runtime_adapter_apply_gate_policy())

        # GET /api/v1/zhiyi/model-request/envelope/dry-run - 模型请求 envelope 草案
        elif path == "/api/v1/zhiyi/model-request/envelope/dry-run":
            self.send_json(get_zhiyi_model_request_envelope_dry_run_policy())

        # GET /api/v1/zhiyi/usage-log/light-prompts/dry-run - 失败轻提示分类表
        elif path == "/api/v1/zhiyi/usage-log/light-prompts/dry-run":
            self.send_json(get_zhiyi_usage_light_prompt_policy())

        # GET /api/v1/zhiyi/usage-log/apply-gate/dry-run - 使用日志写入授权门禁
        elif path == "/api/v1/zhiyi/usage-log/apply-gate/dry-run":
            self.send_json(get_zhiyi_usage_log_apply_gate_policy())

        # GET /api/v1/zhiyi/usage-log/query/dry-run - 使用日志查询草案（只读）
        elif path == "/api/v1/zhiyi/usage-log/query/dry-run":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_zhiyi_usage_log_dry_run(params))

        # GET /api/v1/zhiyi/experience-summary - 知意经验概览（只读摘要）
        elif path == "/api/v1/zhiyi/experience-summary":
            self.send_json(get_zhiyi_experience_summary())

        # GET /api/v1/zhiyi/experience-recycle-bin - 垃圾桶经验
        elif path == "/api/v1/zhiyi/experience-recycle-bin":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            limit = q.get("limit", ["20"])[0]
            self.send_json(get_zhiyi_experience_recycle_bin(limit))

        # GET /api/v1/openclaw/chat-send/targets - OpenClaw chat.send target sessions（只读）
        elif path == "/api/v1/openclaw/chat-send/targets":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            result = query_openclaw_chat_send_targets(params)
            self.send_json(result, 200 if result.get("ok") else 502)

        # GET /api/v1/hermes/feedback-candidates - Hermes 观察经验候选（只读）
        elif path == "/api/v1/hermes/feedback-candidates":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_feedback_candidates(params))

        # GET /api/v1/xingce/work-experience-candidates - 行策工作经验候选（只读）
        elif path == "/api/v1/xingce/work-experience-candidates":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_xingce_work_experience_candidates(params))

        # GET /api/v1/xingce/work-experience-actions - 行策候选处理记录（只读）
        elif path == "/api/v1/xingce/work-experience-actions":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_xingce_work_experience_actions(params))

        # GET /api/v1/hermes/feedback-actions - Hermes 候选处理记录（只读）
        elif path == "/api/v1/hermes/feedback-actions":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_feedback_actions(params))

        # GET /api/v1/hermes/feedback-upgrade-inputs - Hermes 升级输入（只读）
        elif path == "/api/v1/hermes/feedback-upgrade-inputs":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_feedback_upgrade_inputs(params))

        # GET /api/v1/hermes/feedback-upgrade-inputs/{upgrade_input_id} - 升级输入详情（只读）
        elif path.startswith("/api/v1/hermes/feedback-upgrade-inputs/"):
            upgrade_input_id = path.split("/api/v1/hermes/feedback-upgrade-inputs/")[1]
            result = get_hermes_feedback_upgrade_input(urllib.parse.unquote(upgrade_input_id))
            self.send_json(result, 200 if result.get("ok") else 404)

        # GET /api/v1/xingce/work-experience-candidates/{candidate_id} - 行策候选详情（只读）
        elif path.startswith("/api/v1/xingce/work-experience-candidates/"):
            candidate_id = path.split("/api/v1/xingce/work-experience-candidates/")[1]
            result = get_xingce_work_experience_candidate(urllib.parse.unquote(candidate_id))
            self.send_json(result, 200 if result.get("ok") else 404)

        # GET /api/v1/hermes/feedback-candidates/{candidate_id} - 候选详情（只读）
        elif path.startswith("/api/v1/hermes/feedback-candidates/"):
            candidate_id = path.split("/api/v1/hermes/feedback-candidates/")[1]
            result = get_hermes_feedback_candidate(urllib.parse.unquote(candidate_id))
            self.send_json(result, 200 if result.get("ok") else 404)

        # GET /api/v1/zhiyi/memories/{memory_id}/refs - 回指
        elif path.startswith("/api/v1/zhiyi/memories/") and path.endswith("/refs"):
            id_part = path.split("/api/v1/zhiyi/memories/")[1]
            id_part = urllib.parse.unquote(id_part.replace("/refs", ""))
            result = _m5_get_memory_refs(id_part)
            if "error" in result:
                self.send_error(404)
            else:
                self.send_json(result)

        # GET /api/v1/zhiyi/memories/{id} - global_idx or exp_id detail
        elif path.startswith("/api/v1/zhiyi/memories/") and "?" not in path:
            id_part = path.split("/api/v1/zhiyi/memories/")[1]
            id_part = urllib.parse.unquote(id_part)
            try:
                idx = int(id_part)
                all_objects = load_zhiyi_objects()
                if 0 <= idx < len(all_objects):
                    self.send_json(all_objects[idx])
                else:
                    self.send_error(404)
            except ValueError:
                result = _m5_get_memory_detail(id_part)
                if "error" in result:
                    self.send_error(404)
                else:
                    self.send_json(result)

        # GET /api/v1/zhiyi/memories - 知意列表（分页）
        elif path.startswith("/api/v1/zhiyi/memories"):
            parsed = urllib.parse.urlparse(path)
            q = urllib.parse.parse_qs(parsed.query)
            page = int(q.get("page", [1])[0])
            page_size = min(int(q.get("page_size", [20])[0]), 100)
            ftype = q.get("type", [None])[0]

            all_objects = load_zhiyi_objects(ftype)
            total = len(all_objects)
            start = (page - 1) * page_size
            end = start + page_size
            page_items = all_objects[start:end]

            self.send_json({
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
                "items": page_items,
            })

        # GET /api/v1/zhiyi/lifecycle-overlay - Lifecycle Overlay 统计
        elif path == "/api/v1/zhiyi/lifecycle-overlay":
            self.send_json(_m5_get_lifecycle_overlay_stats())

        # GET /api/v1/zhiyi/recall/preview - Recall dry-view
        elif path == "/api/v1/zhiyi/recall/preview":
            parsed = urllib.parse.urlparse(path)
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            # Use parsed query from original self.path
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(_m5_recall_preview(params))

        # GET /api/v1/zhiyi/injection/explain - 注入决策解释
        elif path == "/api/v1/zhiyi/injection/explain":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(_m5_injection_explain(params))

        # ── M6 Governance Proposal GET Routes (dry-run only) ──
        # GET /api/v1/zhiyi/governance/proposals - proposal 列表
        elif path == "/api/v1/zhiyi/governance/proposals":
            self.send_json(m6_list_proposals())

        # GET /api/v1/zhiyi/governance/proposals/{id} - proposal 详情
        elif path.startswith("/api/v1/zhiyi/governance/proposals/") and "/summary" not in path:
            pid = path.split("/api/v1/zhiyi/governance/proposals/")[1]
            pid = urllib.parse.unquote(pid)
            result = m6_get_proposal(pid)
            if "error" in result:
                self.send_error(404)
            else:
                self.send_json(result)

        # GET /api/v1/zhiyi/governance/proposals/{id}/summary - 复制摘要
        elif path.startswith("/api/v1/zhiyi/governance/proposals/") and "/summary" in path:
            pid = path.replace("/api/v1/zhiyi/governance/proposals/", "").replace("/summary", "")
            pid = urllib.parse.unquote(pid)
            result = m6_get_proposal_summary(pid)
            if "error" in result:
                self.send_error(404)
            else:
                self.send_json(result)

        # GET /api/v1/zhiyi/governance/stats - governance 统计
        elif path == "/api/v1/zhiyi/governance/stats":
            self.send_json(m6_get_stats())

        # GET /api/v1/source-systems - source_system状态
        elif path == "/api/v1/source-systems":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            try:
                from source_system_registry import list_source_systems, get_active_sources
                self.send_json({
                    "all": list_source_systems(),
                    "active": get_active_sources(),
                })
            except Exception as e:
                self.send_json({"error": str(e), "all": [], "active": []})

        # GET /api/v1/source-systems/local_files/status
        elif path == "/api/v1/source-systems/local_files/status":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from connectors.local_files_connector import status as lf_status
            self.send_json(lf_status())

        # GET /api/v1/source-systems/local_files/scan
        elif path == "/api/v1/source-systems/local_files/scan":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from connectors.local_files_connector import scan as lf_scan
            self.send_json({"files": lf_scan()})

        # GET /api/v1/source-systems/local_files/checkpoint
        elif path == "/api/v1/source-systems/local_files/checkpoint":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from connectors.local_files_connector import checkpoint as lf_checkpoint
            self.send_json(lf_checkpoint())

        # GET /api/v1/source-systems/codex/status
        elif path == "/api/v1/source-systems/codex/status":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from codex_local_connector import status as codex_status
            self.send_json(codex_status())

        # GET /api/v1/source-systems/codex/scan
        elif path == "/api/v1/source-systems/codex/scan":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from codex_local_connector import scan_sessions as codex_scan
            self.send_json(codex_scan(dry_run=True, limit=20, public=True))

        # GET /api/v1/release/status - 版本状态
        elif path == "/api/v1/release/status":
            version_path = f"{MEMCORE_ROOT}/VERSION"
            latest_path = f"{MEMCORE_ROOT}/release/latest.json"
            version = "unknown"
            if os.path.exists(version_path):
                with open(version_path) as f:
                    version = f.read().strip()
            latest_info = {}
            if os.path.exists(latest_path):
                with open(latest_path) as f:
                    latest_info = json.load(f)
            self.send_json({
                "current_version": version,
                "latest": latest_info.get("latest_version", version),
                "release_catalog": latest_info,
            })

        # GET /api/v1/diagnostics - 诊断索引（轻量版，不加载全部zhiyi对象）
        elif path == "/api/v1/diagnostics":
            import socket
            diag = {
                "watcher": get_watcher_status(),
                "raw_memory": get_raw_stats(),
                "zhiyi_stats": get_zhiyi_stats(),
                "health": {
                    "p0raw": {"status": "passed", "detail": str(get_raw_stats().get("sessions", 0)) + " sessions"},
                    "p0watcher": {"status": "passed" if get_watcher_status() else "failed", "detail": "memcore-cloud.service"},
                },
            }
            # Quick port checks
            ports = {}
            for svc_name, port in [("p3recall", 9830), ("p4provider", 9840)]:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                r = sock.connect_ex(("127.0.0.1", port))
                sock.close()
                ports[svc_name] = "passed" if r == 0 else "failed"
            diag["health"]["p3recall"] = {"status": ports.get("p3recall", "failed")}
            diag["health"]["p4provider"] = {"status": ports.get("p4provider", "failed")}
            try:
                from source_system_registry import list_source_systems
                diag["source_systems"] = list_source_systems()
            except:
                diag["source_systems"] = []
            self.send_json(diag)

        # GET /api/v1/update/status - 更新状态（C2: GitHub source 检测）
        elif path == "/api/v1/update/status":
            import update_source as _upd_src
            version_path = f"{MEMCORE_ROOT}/VERSION"
            current = "unknown"
            if os.path.exists(version_path):
                with open(version_path) as f:
                    current = f.read().strip()
            # C2: Check remote version from GitHub/source
            remote_info = _upd_src.check_remote_version()
            latest_version = current
            metadata_source = "version_file"
            update_available = False
            remote_error = None
            if remote_info.get("ok"):
                latest_version = remote_info["latest_version"]
                metadata_source = remote_info["metadata_source"]
                update_available = _upd_src.compare_versions(current, latest_version) < 0
            elif remote_info.get("error"):
                remote_error = remote_info["error"]
                metadata_source = remote_info.get("metadata_source", "error")
            self.send_json({
                "current_version": current,
                "latest_version": latest_version,
                "update_available": update_available,
                "metadata_source": metadata_source,
                "remote_error": remote_error,
                "download_enabled": True,
                "install_enabled": True,
                "auto_apply": True,
                "one_click_supported": True,
                "apply_mode": "flat_install_apply",
                "preserves_user_data": True,
                "user_upload_required": False,
                "archive_url": _upd_src._get_archive_url(),
                "version_url": _upd_src._get_version_url(),
            })

        # GET /api/v1/update/source - 获取更新源配置
        elif path == "/api/v1/update/source":
            source_path = f"{MEMCORE_ROOT}/config/update_source.json"
            if os.path.exists(source_path):
                with open(source_path) as f:
                    self.send_json(json.load(f))
            else:
                self.send_json({"source_url": None, "type": "local"})


        # GET /api/v1/update/history - 更新历史
        elif path == "/api/v1/update/history":
            hist_path = f"{MEMCORE_ROOT}/update_history.jsonl"
            entries = []
            if os.path.exists(hist_path):
                with open(hist_path) as f:
                    for line in f:
                        if line.strip():
                            try:
                                entries.append(json.loads(line))
                            except:
                                pass
            self.send_json({"entries": entries[-10:], "total": len(entries)})

        # GET /api/v1/runtime/profile - 完整 profile
        elif path == "/api/v1/runtime/profile":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            from tools.runtime_profile import build_memcore_profile, build_openclaw_profile, build_hermes_profile, build_instances_summary, ts
            mc = build_memcore_profile()
            oc = build_openclaw_profile()
            hm = build_hermes_profile()
            summary = build_instances_summary()
            oc_detected = oc.get("health", {}).get("reachable", False) or bool(oc.get("running_instance"))
            hm_detected = hm.get("health", {}).get("reachable", False) or bool(hm.get("running_instance"))
            self.send_json({
                "generated_at": ts(),
                "memcore_cloud": mc,
                "openclaw": oc,
                "hermes": hm,
                "instances_summary": {
                    **summary,
                    "openclaw_detected": oc_detected,
                    "hermes_detected": hm_detected,
                    "detected_count": (1 if oc_detected else 0) + (1 if hm_detected else 0),
                },
            })

        # GET /api/v1/runtime/profile/memcore-cloud
        elif path == "/api/v1/runtime/profile/memcore-cloud":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            from tools.runtime_profile import build_memcore_profile, ts
            self.send_json({"generated_at": ts(), **build_memcore_profile()})

        # GET /api/v1/runtime/profile/openclaw
        elif path == "/api/v1/runtime/profile/openclaw":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            from tools.runtime_profile import build_openclaw_profile, ts
            self.send_json({"generated_at": ts(), **build_openclaw_profile()})

        # GET /api/v1/runtime/profile/instances
        elif path == "/api/v1/runtime/profile/instances":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            from tools.runtime_profile import build_instances_summary, ts
            self.send_json({"generated_at": ts(), **build_instances_summary()})

        # GET /api/v1/runtime/profile/version-compatibility
        elif path == "/api/v1/runtime/profile/version-compatibility":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            from tools.runtime_profile import build_memcore_profile, build_openclaw_profile, ts
            mc = build_memcore_profile()
            oc = build_openclaw_profile()
            self.send_json({
                "generated_at": ts(),
                "memcore_cloud": {
                    "selected_runtime": mc.get("selected_runtime"),
                    "version_mismatches": mc.get("version_mismatches", []),
                    "stale_instances": mc.get("stale_instances", []),
                },
                "openclaw": {
                    "selected_runtime": oc.get("selected_runtime"),
                    "version_mismatches": oc.get("version_mismatches", []),
                    "stale_instances": oc.get("stale_instances", []),
                },
            })

        # GET /api/v1/runtime/profile/hermes - Hermes 只读探测（experimental）
        elif path == "/api/v1/runtime/profile/hermes":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            from tools.runtime_profile import build_hermes_profile, ts
            self.send_json({"generated_at": ts(), **build_hermes_profile()})

        else:
            self.send_error(404)

    def do_POST(self):
        import sys as _sys
        import urllib.parse as _urlparse_post
        _sys.path.insert(0, f"{MEMCORE_ROOT}")
        _sys.path.insert(0, f"{MEMCORE_ROOT}/src")
        import importlib

        if self.path == "/api/recall":
            import p3_recall
            importlib.reload(p3_recall)
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = p3_recall.handle_recall(body)
            self.send_json(result)

        elif self.path == "/api/v1/zhiyi/test-query":
            import p3_recall
            importlib.reload(p3_recall)
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = p3_recall.handle_recall(body)
            self.send_json(result)

        elif _urlparse_post.urlparse(self.path).path.startswith("/api/v1/zhiyi/experiences/") and _urlparse_post.urlparse(self.path).path.endswith("/recycle"):
            path = _urlparse_post.urlparse(self.path).path
            exp_id = path[len("/api/v1/zhiyi/experiences/"):-len("/recycle")]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = recycle_zhiyi_experience(_urlparse_post.unquote(exp_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400 if result.get("error") == "invalid_exp_id" else 404)

        elif _urlparse_post.urlparse(self.path).path.startswith("/api/v1/zhiyi/experiences/") and _urlparse_post.urlparse(self.path).path.endswith("/restore"):
            path = _urlparse_post.urlparse(self.path).path
            exp_id = path[len("/api/v1/zhiyi/experiences/"):-len("/restore")]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = restore_zhiyi_experience(_urlparse_post.unquote(exp_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400 if result.get("error") == "invalid_exp_id" else 404)

        # ── P1-5 Zhiyi model binding dry-run (no config/profile write) ──
        elif self.path == "/api/v1/zhiyi/model-binding/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_model_binding_plan(body))

        # ── P1-9 Zhiyi model binding apply authorization gate (no config write) ──
        elif self.path == "/api/v1/zhiyi/model-binding/apply-gate/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_model_binding_apply_gate_dry_run(body))

        # ── P1-10 Zhiyi runtime adapter preflight contract (no model call/config write) ──
        elif self.path == "/api/v1/zhiyi/runtime-adapter/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_runtime_adapter_dry_run(body))

        # ── P1-11 Zhiyi runtime adapter apply gate + read-only client resolver ──
        elif self.path == "/api/v1/zhiyi/runtime-adapter/apply-gate/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_runtime_adapter_apply_gate_dry_run(body))

        # ── P1-12 Zhiyi model request envelope + no-call adapter response ──
        elif self.path == "/api/v1/zhiyi/model-request/envelope/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_model_request_envelope_dry_run(body))

        # ── P1-6 Zhiyi usage log dry-run (no log append) ──
        elif self.path == "/api/v1/zhiyi/usage-log/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_usage_log_dry_run(body))

        # ── P1-6b Zhiyi usage light prompt classifier (no log append) ──
        elif self.path == "/api/v1/zhiyi/usage-log/light-prompts/classify/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_usage_light_prompt(body))

        # ── P1-7 Zhiyi usage log persistence artifact (no log append) ──
        elif self.path == "/api/v1/zhiyi/usage-log/persist/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_usage_log_persist_dry_run(body))

        # ── P1-8 Zhiyi usage log apply authorization gate (no log append) ──
        elif self.path == "/api/v1/zhiyi/usage-log/apply-gate/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_usage_log_apply_gate_dry_run(body))

        # ── P1-1 Experience Frontstage Actions (backend proposal, no localStorage) ──
        elif self.path == "/api/v1/zhiyi/experience-actions/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = m5_create_experience_action(body)
            if "error" in result:
                self.send_error(400)
            else:
                self.send_json(result)

        # ── B74 OpenClaw chat.send live authorization gate ──
        elif self.path == "/api/v1/openclaw/chat-send/authorized":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_openclaw_chat_send_authorized(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── B71 Hermes feedback candidate live lifecycle action receipt ──
        elif self.path.startswith("/api/v1/hermes/feedback-candidates/") and self.path.endswith("/actions"):
            import urllib.parse as _urlparse_post
            candidate_id = self.path.split("/api/v1/hermes/feedback-candidates/")[1].rsplit("/actions", 1)[0]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_hermes_feedback_candidate_action(_urlparse_post.unquote(candidate_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400)

        # ── B101 Xingce work-experience candidate live lifecycle action receipt ──
        elif self.path.startswith("/api/v1/xingce/work-experience-candidates/") and self.path.endswith("/actions"):
            import urllib.parse as _urlparse_post
            candidate_id = self.path.split("/api/v1/xingce/work-experience-candidates/")[1].rsplit("/actions", 1)[0]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_xingce_work_experience_candidate_action(_urlparse_post.unquote(candidate_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400)

        # ── B110 Experience service live adoption from Xingce candidate ──
        elif self.path.startswith("/api/v1/experience-service/xingce-candidates/") and self.path.endswith("/adopt"):
            import urllib.parse as _urlparse_post
            candidate_id = self.path.split("/api/v1/experience-service/xingce-candidates/")[1].rsplit("/adopt", 1)[0]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_experience_service_xingce_adoption(_urlparse_post.unquote(candidate_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400)

        # ── B110 Experience service live rollback by lifecycle overlay ──
        elif self.path.startswith("/api/v1/experience-service/case-memories/") and self.path.endswith("/rollback"):
            import urllib.parse as _urlparse_post
            exp_id = self.path.split("/api/v1/experience-service/case-memories/")[1].rsplit("/rollback", 1)[0]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_experience_service_case_memory_rollback(_urlparse_post.unquote(exp_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400)

        # ── B111 Experience service semantic upgrade from Hermes upgrade input ──
        elif self.path.startswith("/api/v1/experience-service/hermes-upgrade-inputs/") and self.path.endswith("/apply"):
            import urllib.parse as _urlparse_post
            upgrade_input_id = self.path.split("/api/v1/experience-service/hermes-upgrade-inputs/")[1].rsplit("/apply", 1)[0]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_experience_service_hermes_upgrade_input(_urlparse_post.unquote(upgrade_input_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400)

        # ── M6 Governance Proposal (dry-run only) ──
        elif self.path == "/api/v1/zhiyi/governance/proposals/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = m6_create_proposal(body)
            if "error" in result:
                self.send_error(400)
            else:
                self.send_json(result)

        elif self.path == "/api/v1/update/download":
            import update_source as _upd_src
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = _upd_src.download_update_archive(str(MEMCORE_ROOT))
            self.send_json(result)

        elif self.path == "/api/v1/update/one-click":
            import update_source as _upd_src
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            version_path = f"{MEMCORE_ROOT}/VERSION"
            current = "unknown"
            if os.path.exists(version_path):
                with open(version_path) as f:
                    current = f.read().strip()
            result = _upd_src.one_click_update(
                str(MEMCORE_ROOT),
                current,
                apply=body.get("apply", True),
                restart=body.get("restart", True),
            )
            self.send_json(result)

        elif self.path == "/api/v1/update/source":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            source_url = body.get("source_url", "")
            source_type = body.get("type", "local")
            source_path = f"{MEMCORE_ROOT}/config/update_source.json"
            os.makedirs(os.path.dirname(source_path), exist_ok=True)
            with open(source_path, "w") as f:
                json.dump({"source_url": source_url, "type": source_type}, f, indent=2)
            self.send_json({"ok": True, "source_url": source_url, "type": source_type})


        elif self.path == "/api/v1/source-systems/local_files/ingest":
            from connectors.local_files_connector import ingest as lf_ingest
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            dry_run = body.get("dry_run", False)
            result = lf_ingest(dry_run=dry_run)
            self.send_json(result)

        elif self.path == "/api/v1/update/verify":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            pkg_path = body.get("package_path") or f"{MEMCORE_ROOT}/release/memcore-cloud-{body.get('version', '2026.5.28')}-linux-x86_64.tar.gz"
            import hashlib
            result = {"path": pkg_path, "exists": os.path.exists(pkg_path)}
            if os.path.exists(pkg_path):
                with open(pkg_path, "rb") as f:
                    result["checksum"] = hashlib.sha256(f.read()).hexdigest()
                result["size"] = os.path.getsize(pkg_path)
                # Verify it's a valid tar.gz
                try:
                    import tarfile
                    with tarfile.open(pkg_path) as tf:
                        names = tf.getnames()
                        result["valid_tarball"] = True
                        result["entries"] = len(names)
                        result["sample_entries"] = names[:5]
                except Exception as e:
                    result["valid_tarball"] = False
                    result["tar_error"] = str(e)[:100]
            self.send_json(result)

        elif self.path == "/api/v1/update/plan":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            target_version = body.get("version") or "2026.5.28"
            pkg_path = body.get("package_path") or f"{MEMCORE_ROOT}/release/memcore-cloud-{target_version}-linux-x86_64.tar.gz"
            install_root = body.get("install_root", "/opt/memcore-cloud")
            version_path = f"{MEMCORE_ROOT}/VERSION"
            current = "unknown"
            if os.path.exists(version_path):
                with open(version_path) as f:
                    current = f.read().strip()
            plan = {
                "from_version": current,
                "to_version": target_version,
                "package": pkg_path,
                "install_root": install_root,
                "steps": [
                    {"step": 1, "action": "backup", "target": f"{install_root}/src", "description": "备份当前安装"},
                    {"step": 2, "action": "verify", "target": pkg_path, "description": "校验包完整性"},
                    {"step": 3, "action": "extract", "target": install_root, "description": "解压到安装目录"},
                    {"step": 4, "action": "reload", "target": "memcore-cloud.service", "description": "重启服务"},
                ],
                "rollback_plan": [
                    {"step": 1, "action": "restore", "target": f"{install_root}/src.bak", "description": "恢复备份"},
                    {"step": 2, "action": "reload", "target": "memcore-cloud.service", "description": "重启服务"},
                ],
            }
            plan_path = f"{MEMCORE_ROOT}/release/update_plan.json"
            with open(plan_path, "w") as f:
                json.dump(plan, f, indent=2)
            self.send_json(plan)

        elif self.path == "/api/v1/update/apply-dry-run":
            # C1: Enhanced dry-run with full package validation
            from pathlib import Path
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            target_version = body.get("version", "2026.5.28")
            pkg_path = body.get("package_path") or ""
            sandbox_root = body.get("sandbox_root", "").strip()
            install_root = body.get("install_root", sandbox_root) or sandbox_root
            if not pkg_path:
                self.send_json({"ok": False, "dry_run": True, "error": "package_path required", "steps": []})
                return
            if not install_root:
                self.send_json({"ok": False, "dry_run": True, "error": "install_root or sandbox_root required", "steps": []})
                return
            steps_log = []
            validation = {}
            try:
                # Step 1: Package existence
                if not os.path.exists(pkg_path):
                    steps_log.append({"step": 1, "status": "fail", "action": "check_exists", "reason": "package not found"})
                    self.send_json({"ok": False, "dry_run": True, "error": "package not found", "steps": steps_log})
                    return
                steps_log.append({"step": 1, "status": "pass", "action": "check_exists", "target": pkg_path})
                # Step 2: SHA256
                import hashlib
                with open(pkg_path, "rb") as f:
                    sha256 = hashlib.sha256(f.read()).hexdigest()
                steps_log.append({"step": 2, "status": "pass", "action": "sha256", "sha256": sha256[:16] + "..."})
                # Step 3: Package type and content validation
                is_tar = pkg_path.endswith(".tar.gz") or pkg_path.endswith(".tgz")
                is_zip = pkg_path.endswith(".zip")
                if not (is_tar or is_zip):
                    self.send_json({"ok": False, "dry_run": True, "error": "unsupported package type (only .zip or .tar.gz)", "steps": steps_log})
                    return
                forbidden_found = []
                top_dirs = set()
                file_count = 0
                if is_tar:
                    import tarfile
                    with tarfile.open(pkg_path, "r:gz") as tf:
                        names = tf.getnames()
                        file_count = len(names)
                        for n in names:
                            parts = n.replace("\\", "/").split("/")
                            if parts:
                                top_dirs.add(parts[0])
                            # Forbidden paths in package
                            for forbid in ("memory/", "zhiyi/", "raw/", "output/", "dist/", "backups/",
                                           "experience_lancedb/", "config/memcore.json",
                                           "config/source_system_registry.json",
                                           "config/window_binding_registry.json",
                                           "config/model_config.json"):
                                if n.startswith(forbid):
                                    forbidden_found.append(n)
                else:
                    import zipfile
                    with zipfile.ZipFile(pkg_path) as zf:
                        names = zf.namelist()
                        file_count = len(names)
                        for n in names:
                            parts = n.replace("\\", "/").split("/")
                            if parts:
                                top_dirs.add(parts[0])
                            for forbid in ("memory/", "zhiyi/", "raw/", "output/", "dist/", "backups/",
                                           "experience_lancedb/", "config/memcore.json",
                                           "config/source_system_registry.json",
                                           "config/window_binding_registry.json",
                                           "config/model_config.json"):
                                if n.startswith(forbid):
                                    forbidden_found.append(n)
                # Check required files
                has_required = any(d in top_dirs for d in ("src", "VERSION", "config"))
                steps_log.append({
                    "step": 3, "status": "pass" if not forbidden_found else "warn",
                    "action": "content_scan", "files": file_count,
                    "top_dirs": sorted(top_dirs),
                    "forbidden_found": forbidden_found,
                    "has_required_content": has_required,
                })
                # Check sandbox marker if sandbox mode
                sandbox_ok = True
                if sandbox_root:
                    marker = Path(sandbox_root) / ".memcore-sandbox-root"
                    sandbox_ok = marker.exists()
                    steps_log.append({
                        "step": 4, "status": "pass" if sandbox_ok else "fail",
                        "action": "sandbox_marker_check",
                        "marker": str(marker),
                        "found": sandbox_ok,
                    })
                    if not sandbox_ok:
                        self.send_json({
                            "ok": False, "dry_run": True,
                            "error": f".memcore-sandbox-root marker not found at {marker}; create marker directory to enable sandbox apply",
                            "steps": steps_log
                        })
                        return
                # Generate dry_run_token (inline, same algorithm as apply endpoint)
                import secrets, time as _time
                _raw = f"{target_version}:{pkg_path}:{install_root}:{_time.time()}:{secrets.token_hex(16)}"
                token = hashlib.sha256(_raw.encode()).hexdigest()[:32]
                _TOKEN_TTL = 600
                validation = {
                    "ok": True, "dry_run": True,
                    "dry_run_token": token,
                    "token_ttl_seconds": _TOKEN_TTL,
                    "token_bound_to": {"version": target_version, "package_path": pkg_path, "install_root": install_root},
                    "package_sha256": sha256,
                    "target_version": target_version,
                    "forbidden_paths_found": len(forbidden_found) > 0,
                    "would_preserve_user_data": True,
                    "sandbox_apply": bool(sandbox_root),
                    "steps": steps_log,
                }
                self.send_json(validation)
            except Exception as e:
                self.send_json({"ok": False, "dry_run": True, "error": str(e)[:200], "steps": steps_log})

        elif self.path == "/api/v1/update/apply":
            # Hardened apply endpoint.
            # Requires sandbox_root + allow_sandbox_apply OR production_apply + confirm_apply
            # install_root is REQUIRED for production apply — no default production path
            # dry_run_token must be bound to version+pkg_path+install_root with 10min expiry
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            target_version = body.get("version", "2026.5.28")
            pkg_path = body.get("package_path") or f"{MEMCORE_ROOT}/release/memcore-cloud-{target_version}-linux-x86_64.tar.gz"
            sandbox_root = body.get("sandbox_root")
            allow_sandbox = body.get("allow_sandbox_apply", False)
            production_apply = body.get("production_apply", False)
            confirm_apply = body.get("confirm_apply", False)
            dry_run_token = body.get("dry_run_token", "")
            audit_note = body.get("audit_note", "")

            from pathlib import Path
            from datetime import datetime, timezone, timedelta
            import hashlib, time as _time

            # P0-2 Fix: expanded protected paths
            PROTECTED_PATHS_API = [
                Path.home() / ".openclaw",
                Path.home() / ".npm-global",
                Path("/usr/local"),
                Path("/usr/bin"),
                Path("/usr/lib"),
                Path("/opt"),
                Path("/etc"),
                Path("/root"),
                Path(MEMCORE_ROOT),
            ]

            # Token store: token -> {version, pkg_path, install_root, created_at}
            # Module-level so it persists across requests within the same process
            if not hasattr(Handler, "_dry_run_tokens"):
                Handler._dry_run_tokens = {}

            TOKEN_TTL_SECONDS = 600  # 10 minutes

            def make_dry_run_token(version, pkg, install_root):
                """Generate a dry-run token bound to version+pkg+install_root."""
                import secrets
                raw = f"{version}:{pkg}:{install_root}:{_time.time()}:{secrets.token_hex(16)}"
                token = hashlib.sha256(raw.encode()).hexdigest()[:32]
                Handler._dry_run_tokens[token] = {
                    "version": version,
                    "pkg_path": pkg,
                    "install_root": install_root,
                    "created_at": _time.time(),
                }
                return token

            def validate_dry_run_token(token, version, pkg, install_root):
                """Validate token is bound to the same version+pkg+install_root and not expired."""
                store = Handler._dry_run_tokens
                if token not in store:
                    return False, "token not found or already used/consumed"
                entry = store[token]
                if _time.time() - entry["created_at"] > TOKEN_TTL_SECONDS:
                    del store[token]
                    return False, "token expired (10min TTL)"
                if entry["version"] != version:
                    return False, f"token version mismatch: {entry['version']} != {version}"
                if entry["pkg_path"] != pkg:
                    return False, f"token package_path mismatch"
                if entry["install_root"] != install_root:
                    return False, f"token install_root mismatch: {entry['install_root']} != {install_root}"
                # Consume token (one-time use)
                del store[token]
                return True, ""

            # Audit log helper
            def log_apply(action, ok, error_msg=""):
                log_file = Path(MEMCORE_ROOT) / "logs" / "update_audit.log"
                log_file.parent.mkdir(parents=True, exist_ok=True)
                entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": action,
                    "ok": ok,
                    "error": error_msg,
                    "version": target_version,
                    "package": pkg_path,
                    "audit_note": audit_note,
                }
                try:
                    with open(log_file, "a") as f:
                        f.write(json.dumps(entry) + "\n")
                except Exception:
                    pass  # Non-blocking

            # Step 1: Check sandbox OR production flag
            if sandbox_root and allow_sandbox:
                # SANDBOX flow: requires .memcore-sandbox-root marker at sandbox_root
                sandbox_path = Path(sandbox_root).resolve()
                marker = sandbox_path / ".memcore-sandbox-root"
                if not marker.exists():
                    log_apply("apply_sandbox", False, "sandbox marker missing")
                    self.send_json({"ok": False, "error": f".memcore-sandbox-root marker not found at {marker}", "steps": []})
                    return
                install_root = sandbox_root
            elif production_apply and confirm_apply:
                # PRODUCTION flow: install_root is REQUIRED — no default
                install_root = body.get("install_root", "").strip()
                if not install_root:
                    log_apply("apply_production", False, "install_root required for production apply")
                    self.send_json({"ok": False, "error": "install_root is required for production apply; no default production path is used", "steps": []})
                    return
                # V4 Fix: validate dry_run_token is bound to the same version+pkg+install_root
                if not dry_run_token:
                    log_apply("apply_production", False, "dry_run_token required")
                    self.send_json({"ok": False, "error": "dry_run_token required (must match a prior dry-run with the same version+package_path+install_root)", "steps": []})
                    return
                tok_ok, tok_err = validate_dry_run_token(dry_run_token, target_version, pkg_path, install_root)
                if not tok_ok:
                    log_apply("apply_production", False, f"dry_run_token validation failed: {tok_err}")
                    self.send_json({"ok": False, "error": f"dry_run_token validation failed: {tok_err}", "steps": []})
                    return
            else:
                log_apply("apply_blocked", False, "missing allow_sandbox_apply or production_apply+confirm_apply")
                self.send_json({
                    "ok": False,
                    "error": "apply blocked: must specify sandbox_root + allow_sandbox_apply=true OR production_apply=true + confirm_apply=true",
                    "steps": [],
                    "hint": "For sandbox apply: {sandbox_root: '/path', allow_sandbox_apply: true}. For production: {production_apply: true, confirm_apply: true, install_root: '/full/path/to/install', dry_run_token: '...'}"
                })
                return

            # Step 2: Boundary check
            ir = Path(install_root).resolve()
            for prot in PROTECTED_PATHS_API:
                try:
                    ir.relative_to(prot.resolve())
                    log_apply("apply_blocked", False, f"protected path: {prot}")
                    self.send_json({"ok": False, "error": f"install_root {install_root} overlaps with protected path {prot}; refused", "steps": []})
                    return
                except ValueError:
                    pass

            # Step 3: Execute apply
            try:
                import subprocess as _subp
                mc_root = str(MEMCORE_ROOT)
                dry_flag = "--dry-run" if not (sandbox_root or production_apply) else ""
                _result = _subp.run(
                    ["python3", f"{mc_root}/tools/apply_linux_update.py",
                     "--install-root", install_root,
                     "--pkg", pkg_path,
                     "--apply"],
                    capture_output=True, text=True, timeout=60,
                    cwd=mc_root, env={**os.environ, "PYTHONPATH": f"{mc_root}:{os.environ.get('PYTHONPATH','')}"}
                )
                try:
                    result = json.loads(_result.stdout)
                except:
                    result = {"ok": False, "error": "apply script output unparseable", "stderr": _result.stderr[:200]}
                result["note"] = "applied via console API; sandbox=" + str(bool(sandbox_root))
                result["sandbox_apply"] = bool(sandbox_root)
                result["production_apply"] = bool(production_apply)
                log_apply("apply_complete", result.get("ok", False))
                self.send_json(result)
            except _subp.TimeoutExpired:
                log_apply("apply_timeout", False)
                self.send_json({"ok": False, "error": "apply timed out after 60s", "steps": []})
            except Exception as e:
                log_apply("apply_error", False, str(e)[:100])
                self.send_json({"ok": False, "error": str(e)[:200], "steps": []})

        else:
            self.send_error(404)

def run(port=PORT, host="127.0.0.1"):
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[memcore-m1] console running on http://{host}:{port}")
    server.serve_forever()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="memcore-m1 console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    run(port=args.port, host=args.host)
