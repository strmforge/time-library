import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path

from src import distill_transparency
from src.evidence_bound_model import EvidenceBoundModelConfig, _http_chat_completion, run_evidence_bound_answer


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(
            {"choices": [{"message": {"content": '{"verdict":"refined"}'}}]},
            ensure_ascii=False,
        ).encode("utf-8")


def test_transparency_ledger_records_actual_request_bytes_and_response(monkeypatch, tmp_path):
    captured = {}

    def fake_urlopen(request, **_kwargs):
        captured["request_body"] = request.data
        captured["authorization"] = request.get_header("Authorization")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    ledger = tmp_path / "runtime" / "distill_transparency_ledger.jsonl"
    config = EvidenceBoundModelConfig(
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        timeout_seconds=5,
        transparency_ledger_path=str(ledger),
        transparency_call_kind="distillation",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-secret")
    messages = [{"role": "user", "content": json.dumps({"candidate_id": "candidate-1", "text": "用户偏好"}, ensure_ascii=False)}]

    result = _http_chat_completion(messages, config)

    assert result["ok"] is True
    assert captured["authorization"] == "Bearer fixture-secret"
    entries = distill_transparency.read_entries(ledger)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["payload_source"] == "actual_http_request_data"
    assert entry["payload_text"].encode("utf-8") == captured["request_body"]
    assert entry["payload_sha256"] == hashlib.sha256(captured["request_body"]).hexdigest()
    assert entry["payload_byte_count"] == len(captured["request_body"])
    assert entry["associated_artifact_id"] == "candidate-1"
    assert entry["destination_scope"] == "cloud"
    assert entry["response_sha256"]
    assert "fixture-secret" not in ledger.read_text(encoding="utf-8")
    assert stat.S_IMODE(ledger.stat().st_mode) == 0o600


def test_transparency_ledger_is_append_only_and_queryable(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    first = {"call_id": "call-1", "payload_text": "第一条", "payload_sha256": "a"}
    second = {"call_id": "call-2", "payload_text": "第二条", "payload_sha256": "b"}

    distill_transparency.append_entry(first, ledger)
    first_bytes = ledger.read_bytes()
    distill_transparency.append_entry(second, ledger)

    lines = ledger.read_bytes().splitlines()
    assert lines[0] == first_bytes.splitlines()[0]
    assert distill_transparency.get_entry("call-1", ledger) == first
    assert distill_transparency.get_entry("call-2", ledger) == second
    assert distill_transparency.ledger_status(ledger)["entry_count"] == 2


def test_transparency_ledger_empty_status_is_explicit(tmp_path):
    status = distill_transparency.ledger_status(tmp_path / "missing.jsonl")

    assert status["exists"] is False
    assert status["append_only"] is True
    assert status["local_only"] is True
    assert status["entry_count"] == 0


def test_append_entry_uses_windows_file_lock_when_fcntl_is_unavailable(tmp_path, monkeypatch):
    class FakeMsvcrt:
        LK_LOCK = 1
        LK_UNLCK = 2

        def __init__(self):
            self.calls = []

        def locking(self, _fd, mode, byte_count):
            self.calls.append((mode, byte_count))

    fake_msvcrt = FakeMsvcrt()
    monkeypatch.setattr(distill_transparency, "_fcntl", None)
    monkeypatch.setattr(distill_transparency, "_msvcrt", fake_msvcrt)
    ledger = tmp_path / "runtime" / "distill_transparency_ledger.jsonl"

    distill_transparency.append_entry({"call_id": "windows-lock"}, ledger)

    assert fake_msvcrt.calls == [(fake_msvcrt.LK_LOCK, 1), (fake_msvcrt.LK_UNLCK, 1)]
    assert distill_transparency.get_entry("windows-lock", ledger) == {"call_id": "windows-lock"}


def test_successful_model_call_stays_successful_when_transparency_lock_fails(monkeypatch, tmp_path):
    calls = {"http": 0, "ledger": 0}

    def fake_urlopen(_request, **_kwargs):
        calls["http"] += 1
        return FakeResponse()

    def fail_ledger(**_kwargs):
        calls["ledger"] += 1
        raise OSError("ledger lock timeout")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(distill_transparency, "record_http_call", fail_ledger)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-secret")
    config = EvidenceBoundModelConfig(
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        timeout_seconds=5,
        transparency_ledger_path=str(tmp_path / "ledger.jsonl"),
        transparency_call_kind="distillation",
    )

    result = _http_chat_completion([{"role": "user", "content": "fixture"}], config)

    assert result["ok"] is True
    assert result["transparency_recorded"] is False
    assert result["transparency_error"] == "OSError: ledger lock timeout"
    assert calls == {"http": 1, "ledger": 1}


def test_high_level_model_result_surfaces_transparency_failure():
    def client(_messages, _config):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "answer": "已确认",
                    "verdict": "answered",
                    "confidence": 1,
                    "supporting_refs": ["E1"],
                },
                ensure_ascii=False,
            ),
            "transparency_recorded": False,
            "transparency_error": "OSError: ledger lock timeout",
        }

    result = run_evidence_bound_answer(
        "状态？",
        [{"text": "user: 已确认"}],
        client=client,
    )

    assert result["ok"] is True
    assert result["transparency_recorded"] is False
    assert result["transparency_error"] == "OSError: ledger lock timeout"
    assert result["transparency_warning"] == "model_call_succeeded_but_transparency_ledger_write_failed"


def test_failed_model_call_does_not_claim_success_when_transparency_also_fails():
    result = run_evidence_bound_answer(
        "状态？",
        [{"text": "user: 已确认"}],
        client=lambda *_args: {
            "ok": False,
            "error": "http_500",
            "transparency_recorded": False,
            "transparency_error": "OSError: ledger lock timeout",
        },
    )

    assert result["ok"] is False
    assert result["transparency_warning"] == "model_call_failed_and_transparency_ledger_write_failed"


def test_transparency_cli_list_keeps_payload_for_show_only(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    distill_transparency.append_entry(
        {"call_id": "call-1", "payload_text": "private fixture payload", "payload_sha256": "a"},
        ledger,
    )

    result = subprocess.run(
        [sys.executable, "tools/distill_transparency.py", "list", "--ledger", str(ledger)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "private fixture payload" not in result.stdout
    assert '"payload_sha256": "a"' in result.stdout
