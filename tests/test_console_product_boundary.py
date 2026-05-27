import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reload_p6(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in ["config_loader", "src.config_loader", "p6_console", "src.p6_console"]:
        sys.modules.pop(name, None)
    return importlib.import_module("p6_console")


def test_console_i18n_keeps_zh_cn_labels_chinese(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    zh = p6.I18N["zh-CN"]
    assert zh["nav.settings"] == "设置"
    assert zh["nav.update"] == "系统更新"
    assert zh["nav.sourceSystems"] == "数据源"
    assert zh["runtime.refresh"] == "刷新"


def test_console_user_visible_text_has_no_internal_phase_codes(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    visible_payload = json.dumps(p6.I18N, ensure_ascii=False) + p6.HTML_TEMPLATE

    assert "".join(["P9", "-Audit", "-Fix-1"]) not in visible_payload
    assert "".join(["Audit", "-Fix"]) not in visible_payload
    assert p6.I18N["zh-CN"]["dashboard.sealed"] == "本机服务就绪"
    assert p6.I18N["en-US"]["dashboard.sealed"] == "Local Service Ready"


def test_console_status_api_uses_public_phase_name(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    monkeypatch.setattr(p6, "get_watcher_status", lambda: True)
    monkeypatch.setattr(p6, "get_raw_stats", lambda: {"sessions": 0})
    monkeypatch.setattr(p6, "get_zhiyi_stats", lambda: {"total": 0})

    overview = p6.m3_get_overview()

    assert overview["phase"] == "local-service-ready"
    assert "P9" not in json.dumps(overview, ensure_ascii=False)


def test_console_legacy_review_apis_hide_internal_phase_names(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    payload = {
        "risk_backlog": p6.m4_get_risk_backlog(),
        "next_decision": p6.m4_get_next_decision_summary(),
    }
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "".join(["P9", "-System"]) not in serialized
    assert "".join(["Audit", "-Fix"]) not in serialized
    assert payload["risk_backlog"]["risks"][0]["task"] == "runtime-status"
    assert payload["next_decision"]["current_phase"] == "local-console-review-complete"


def test_product_console_explains_zhiyi_xingce_in_both_languages():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert "知意负责看见，行策负责落地" in html
    assert "知行合一" in html
    assert "Zhiyi understands intent" in html
    assert "Xingce turns source-backed understanding into action experience" in html
    assert "Knowing and doing as one" in html
