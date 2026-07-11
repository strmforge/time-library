import json
import subprocess

from src import model_connection_smoke as smoke


AUTHORIZATION = {
    "confirm_live_model_call": True,
    "confirm_no_platform_config_write": True,
    "operator": "pytest",
    "reason": "verify selected model",
}


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "TIME_LIBRARY_MODEL_OK"}}]}).encode()


def test_model_connection_smoke_requires_authorization_without_calling():
    result = smoke.run_model_connection_smoke(
        {"model_name": "deepseek-chat"},
        run_command=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
        urlopen=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    assert result["ok"] is False
    assert result["model_call_performed"] is False
    assert "confirm_live_model_call" in result["missing_authorization"]


def test_direct_model_smoke_uses_selected_model_and_never_returns_secret():
    captured = {}

    def fake_urlopen(request, **kwargs):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse()

    result = smoke.run_model_connection_smoke(
        {
            "model_id": "manual:deepseek:deepseek-chat",
            "provider": "DeepSeek",
            "provider_id": "deepseek",
            "model_name": "deepseek-chat",
            "api_key_env": "DEEPSEEK_API_KEY",
            "authorization": AUTHORIZATION,
        },
        env={"DEEPSEEK_API_KEY": "sk-private-value"},
        urlopen=fake_urlopen,
    )

    assert result["ok"] is True
    assert result["model_call_performed"] is True
    assert result["test_path"] == "openai_compatible_http"
    assert result["model"] == "deepseek-chat"
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-private-value"
    assert captured["payload"]["model"] == "deepseek-chat"
    assert "sk-private-value" not in json.dumps(result)


def test_direct_model_smoke_reports_missing_environment_secret_without_calling():
    result = smoke.run_model_connection_smoke(
        {
            "model_id": "manual:minimax:MiniMax-M2",
            "provider": "MiniMax",
            "provider_id": "minimax",
            "model_name": "MiniMax-M2",
            "api_key_env": "MINIMAX_API_KEY",
            "authorization": AUTHORIZATION,
        },
        env={},
        urlopen=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    assert result["ok"] is False
    assert result["model_call_performed"] is False
    assert result["error"] == "model_config_missing"
    assert result["missing"] == ["api_key_env_value"]


def test_hermes_model_smoke_targets_selected_model_without_writing_config():
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="TIME_LIBRARY_MODEL_OK\n", stderr="")

    result = smoke.run_model_connection_smoke(
        {
            "model_id": "hermes-config:minimax:MiniMax-M2",
            "option_category": "hermes",
            "provider": "Hermes",
            "provider_id": "minimax",
            "model_name": "MiniMax-M2",
            "authorization": AUTHORIZATION,
        },
        env={},
        run_command=fake_run,
    )

    assert result["ok"] is True
    assert result["test_path"] == "hermes_cli"
    assert result["model_call_performed"] is True
    assert result["platform_config_write_performed"] is False
    assert captured["command"][captured["command"].index("--model") + 1] == "MiniMax-M2"
    assert captured["command"][captured["command"].index("--provider") + 1] == "minimax"


def test_hermes_model_smoke_uses_cli_path_from_passed_runtime_environment():
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="TIME_LIBRARY_MODEL_OK\n", stderr="")

    result = smoke.run_model_connection_smoke(
        {
            "model_id": "hermes-config:minimax:MiniMax-M3",
            "option_category": "hermes",
            "provider": "Hermes",
            "provider_id": "minimax",
            "model_name": "MiniMax-M3",
            "authorization": AUTHORIZATION,
        },
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "MEMCORE_HERMES_CLI": "/opt/time-library/bin/hermes",
        },
        run_command=fake_run,
    )

    assert result["ok"] is True
    assert captured["command"][0] == "/opt/time-library/bin/hermes"
