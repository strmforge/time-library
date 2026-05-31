import importlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_module():
    sys.modules.pop("model_facts", None)
    sys.modules.pop("src.model_facts", None)
    return importlib.import_module("model_facts")


def _write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_model_facts_reads_openclaw_default_and_catalog_without_writing(tmp_path):
    model_facts = _load_module()
    openclaw = tmp_path / "openclaw"
    _write_json(
        openclaw / "openclaw.json",
        {
            "gateway": {"auth": {"token": "OPENCLAW-SECRET-TOKEN"}},
            "models": {
                "providers": {
                    "minimax": {
                        "type": "openai-compatible",
                        "api_key": "sk-secret",
                        "models": [
                            {"id": "MiniMax-M1", "name": "MiniMax M1"},
                            {"id": "abab6.5s-chat"},
                        ],
                    }
                }
            },
            "agents": {
                "defaults": {
                    "model": {
                        "primary": "minimax/MiniMax-M1",
                        "fallbacks": ["minimax/abab6.5s-chat"],
                    },
                    "models": [
                        {"provider": "tencent", "id": "hunyuan-t1"},
                    ],
                },
                "list": [
                    {"id": "main", "model": {"provider": "minimax", "primary": "MiniMax-M1"}},
                ],
            },
        },
    )
    _write_json(openclaw / "clawui-models.json", {"anthropic/claude-opus-4.6": {"apiKey": "secret"}})

    result = model_facts.build_model_facts_report(
        openclaw_roots=[openclaw],
        hermes_roots=[],
        codex_roots=[],
    )

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["platform_write_performed"] is False
    assert result["runtime_boundary"]["yifanchen_is_not_a_model_center"] is True
    assert result["counts"]["by_platform"]["openclaw"] >= 5
    roles = {fact["role"] for fact in result["facts"]}
    assert {"catalog", "default", "fallback", "agent_default"}.issubset(roles)
    assert all(fact["platform"] == "openclaw" for fact in result["facts"])
    assert all(fact["runnable"] == "unknown" for fact in result["facts"])
    assert all(fact["runtime_ownership"] == "borrowed_runtime" for fact in result["facts"])
    assert all(fact["write_boundary"]["openclaw_write_performed"] is False for fact in result["facts"])

    serialized = json.dumps(result, ensure_ascii=False)
    assert "OPENCLAW-SECRET-TOKEN" not in serialized
    assert "sk-secret" not in serialized
    assert "secret" not in serialized
    assert any(fact["credentials"]["has_sensitive_fields"] for fact in result["facts"])


def test_model_facts_reads_hermes_legacy_custom_provider_v12_and_models_json(tmp_path):
    model_facts = _load_module()
    hermes = tmp_path / "hermes"
    _write_text(
        hermes / "profiles" / "default" / "config.yaml",
        """
model:
  provider: anthropic
  default: claude-opus-4.6
custom_providers:
  - id: minimax
    type: openai-compatible
    api_key: SECRET
    models:
      - id: MiniMax-M1
providers:
  tencent-token-plan:
    type: openai-compatible
    models:
      - id: hunyuan-t1
""",
    )
    _write_json(
        hermes / "models.json",
        {
            "providers": {
                "gemini": {
                    "type": "gemini",
                    "models": {"gemini-2.5-pro": {"label": "Gemini 2.5 Pro"}},
                }
            }
        },
    )

    result = model_facts.build_model_facts_report(
        openclaw_roots=[],
        hermes_roots=[hermes],
        codex_roots=[],
    )

    assert result["counts"]["by_platform"]["hermes"] >= 4
    by_kind = {fact["source_kind"] for fact in result["facts"]}
    assert "hermes_config_yaml" in by_kind
    assert "hermes_custom_providers" in by_kind
    assert "hermes_providers" in by_kind
    assert "hermes_models.json" in by_kind
    models = {fact["model"] for fact in result["facts"]}
    assert {"claude-opus-4.6", "MiniMax-M1", "hunyuan-t1", "gemini-2.5-pro"}.issubset(models)
    assert all(fact["write_boundary"]["hermes_write_performed"] is False for fact in result["facts"])

    serialized = json.dumps(result, ensure_ascii=False)
    assert "SECRET" not in serialized
    assert result["detected_is_not_runnable"] is True


def test_model_facts_reads_codex_config_minimally_as_read_only(tmp_path):
    model_facts = _load_module()
    codex = tmp_path / "codex"
    _write_text(
        codex / "config.toml",
        """
model = "gpt-5-codex"
model_provider = "openai"
""",
    )

    result = model_facts.build_model_facts_report(
        openclaw_roots=[],
        hermes_roots=[],
        codex_roots=[codex],
    )

    assert result["counts"]["by_platform"]["codex"] == 1
    fact = result["facts"][0]
    assert fact["platform"] == "codex"
    assert fact["model"] == "gpt-5-codex"
    assert fact["provider_id"] == "openai"
    assert fact["runnable"] == "unknown"
    assert fact["write_boundary"]["codex_write_performed"] is False


def test_model_facts_plan_declares_read_only_runtime_boundary():
    model_facts = _load_module()

    plan = model_facts.get_model_facts_plan()

    assert plan["ok"] is True
    assert plan["read_only"] is True
    assert plan["write_performed"] is False
    assert plan["platform_write_performed"] is False
    assert plan["endpoint"] == "/api/v1/model-facts"
    assert "detected_is_not_runnable" in plan["contracts"]
    assert "platform_configs_are_never_written" in plan["contracts"]


def test_model_runnable_doctor_plan_declares_authorized_smoke_boundary():
    model_facts = _load_module()

    plan = model_facts.get_model_runnable_doctor_plan()

    assert plan["ok"] is True
    assert plan["read_only"] is True
    assert plan["write_performed"] is False
    assert plan["smoke_endpoint"] == "/api/v1/model-facts/runnable-doctor/smoke"
    assert "detected_true_is_not_runnable_true" in plan["contracts"]
    assert "doctor_never_returns_secret_values" in plan["contracts"]
    assert "confirm_live_runtime_smoke" in plan["authorization_required"]


def test_model_runnable_doctor_requires_authorization_without_running(tmp_path):
    model_facts = _load_module()

    result = model_facts.build_model_runnable_doctor_smoke(
        {"platform": "hermes", "operator": "pytest"},
        run_command=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    assert result["ok"] is False
    assert result["runtime_smoke_performed"] is False
    assert result["write_performed"] is False
    assert "confirm_live_runtime_smoke" in result["missing_authorization"]
    assert "reason" in result["missing_authorization"]


def test_model_runnable_doctor_reports_success_without_returning_secret(tmp_path):
    model_facts = _load_module()
    hermes_cli = tmp_path / "hermes"
    _write_text(hermes_cli, "#!/bin/sh\n")

    def fake_run(command, **kwargs):
        assert command[0] == str(hermes_cli)
        assert kwargs["env"]["MINIMAX_API_KEY"] == "sk-secret"
        return subprocess.CompletedProcess(command, 0, stdout="OK\n", stderr="")

    result = model_facts.build_model_runnable_doctor_smoke(
        {
            "platform": "hermes",
            "hermes_cli": str(hermes_cli),
            "confirm_live_runtime_smoke": True,
            "confirm_no_platform_config_write": True,
            "operator": "pytest",
            "reason": "verify runnable doctor",
        },
        env={"MINIMAX_API_KEY": "sk-secret", "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic"},
        run_command=fake_run,
    )

    assert result["ok"] is True
    assert result["runtime_smoke_performed"] is True
    assert result["runnable"] is True
    assert result["write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["service_environment"]["secret_values_returned"] is False
    assert result["service_environment"]["probes"]["MINIMAX_API_KEY"]["present"] is True
    serialized = json.dumps(result, ensure_ascii=False)
    assert "sk-secret" not in serialized


def test_model_runnable_doctor_classifies_auth_failure_as_service_env_gap(tmp_path):
    model_facts = _load_module()
    hermes_cli = tmp_path / "hermes"
    _write_text(hermes_cli, "#!/bin/sh\n")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="Anthropic 401 authentication failed. Token prefix: no-key-requi...",
            stderr="Please carry the API secret key in the X-Api-Key field",
        )

    result = model_facts.build_model_runnable_doctor_smoke(
        {
            "platform": "hermes",
            "hermes_cli": str(hermes_cli),
            "confirm_live_runtime_smoke": True,
            "confirm_no_platform_config_write": True,
            "operator": "pytest",
            "reason": "verify auth failure classification",
        },
        env={"ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic"},
        run_command=fake_run,
    )

    assert result["ok"] is False
    assert result["runnable"] is False
    assert result["failure"]["category"] == "auth_failed"
    assert result["failure"]["likely_gap"] == "service_env_missing_or_mismatched_runtime_credentials"
    assert result["service_environment"]["probes"]["MINIMAX_API_KEY"]["present"] is False
