import copy
import json
from pathlib import Path

import pytest

from tools.r2_state_extractor_pilot import (
    APPROVED_FROZEN_MANIFEST_SHA256,
    AUTHORIZATION_PHRASE,
    HYBRID_AUTHORIZATION_PHRASE,
    PilotError,
    build_model_messages,
    build_hybrid_plan_manifest,
    call_openai_compatible,
    freeze_case_manifest,
    normalize_model_result,
    public_safe_findings,
    run_arm,
    sha256_json,
)
from src.model_api_key_store import store_model_api_key


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "tests/fixtures/r2_state_extractor_pilot_cases.json"


def _spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def _frozen():
    return freeze_case_manifest(_spec())


def _perfect_raw_atom(case, expected):
    refs = [ref["evidence_ref"] for ref in expected["source_refs"]]
    return {
        "source_quote": expected["source_span"]["text"],
        "source_ref_ids": refs,
        "shelf": expected["shelf"],
        "semantic_type": expected["semantic_type"],
        "state_role": expected["state_role"],
        "content": expected["source_span"]["text"],
        "observed_at": expected["observed_at"],
        "recorded_at": expected["recorded_at"],
        "valid_from": expected["valid_from"],
        "valid_to": expected["valid_to"],
        "taint": expected["taint"],
        "verifier": {"coverage": "pass", "preservation": "pass", "faithfulness": "pass"},
        "activation_allowed": False,
    }


def test_freezes_36_balanced_public_safe_cases_deterministically():
    first = _frozen()
    second = _frozen()

    assert first == second
    assert first["case_count"] == 36
    assert set(first["stratum_counts"].values()) == {6}
    assert all(value == {"en": 3, "zh": 3} for value in first["language_counts"].values())
    assert first["frozen_manifest_sha256"] == second["frozen_manifest_sha256"]
    assert first["frozen_manifest_sha256"] == APPROVED_FROZEN_MANIFEST_SHA256
    assert public_safe_findings(first) == []


def test_model_prompt_never_contains_answer_key_or_derived_atom_ids():
    case = _frozen()["cases"][0]
    messages = build_model_messages(case)
    prompt = json.dumps(messages, ensure_ascii=False)

    assert "expected_atoms" not in prompt
    assert "required_atom_ids" not in prompt
    assert "preserved_atom_ids" not in prompt
    assert "forbidden_atom_ids" not in prompt
    for expected in case["expected_atoms"]:
        assert expected["atom_id"] not in prompt


def test_model_prompt_distinguishes_data_safety_from_taint_and_forbids_raw_output():
    case = _frozen()["cases"][0]
    payload = json.loads(build_model_messages(case)[1]["content"])

    assert "raw" not in payload["allowed_values"]["shelf"]
    rules = "\n".join(payload["rules"])
    assert "Ordinary synthetic/public statements use taint trusted" in rules
    assert "one atomic state" in rules
    assert "raw is the evidence source and is never an output shelf" in rules


def test_utf8_span_and_atom_id_are_derived_after_exact_quote_verification():
    case = next(item for item in _frozen()["cases"] if item["language"] == "zh")
    raw_atoms = [_perfect_raw_atom(case, item) for item in case["expected_atoms"]]

    atoms, errors = normalize_model_result(case, {"atoms": raw_atoms})

    assert errors == []
    assert [item["atom_id"] for item in atoms] == [
        item["atom_id"] for item in case["expected_atoms"]
    ]
    for atom in atoms:
        span = atom["source_span"]
        source_bytes = case["source_text"].encode("utf-8")
        assert source_bytes[span["byte_start"]:span["byte_end"]].decode("utf-8") == span["text"]


def test_non_exact_or_ambiguous_quotes_fail_closed():
    case = _frozen()["cases"][0]
    atom = _perfect_raw_atom(case, case["expected_atoms"][0])
    atom["source_quote"] = "not copied from source"

    atoms, errors = normalize_model_result(case, {"atoms": [atom]})

    assert atoms == []
    assert errors == ["atom_0_source_quote_must_match_exactly_once"]


def test_shorter_exact_quote_maps_to_one_expected_atom_but_cross_atom_quote_does_not():
    case = _frozen()["cases"][0]
    first = _perfect_raw_atom(case, case["expected_atoms"][0])
    first["source_quote"] = "dashboard theme is light"

    atoms, errors = normalize_model_result(case, {"atoms": [first]})

    assert errors == []
    assert atoms[0]["atom_id"] == case["expected_atoms"][0]["atom_id"]

    crossing = _perfect_raw_atom(case, case["expected_atoms"][0])
    crossing["source_quote"] = case["sources"][0]["text"]
    crossing["source_ref_ids"] = [case["sources"][0]["source_ref_id"]]
    atoms, errors = normalize_model_result(case, {"atoms": [crossing]})

    assert errors == ["atom_0_source_span_crosses_multiple_expected_atoms"]
    assert atoms[0]["atom_id"] not in {
        item["atom_id"] for item in case["expected_atoms"]
    }


def test_freeze_rejects_private_cloud_bound_material():
    spec = _spec()
    spec["cases"][0]["sources"][0]["text"] += " /" + "Users" + "/private/example"

    with pytest.raises(PilotError, match="public_safe_scan_failed"):
        freeze_case_manifest(spec)


def test_run_requires_exact_owner_authorization(tmp_path):
    with pytest.raises(PilotError, match="explicit_owner_authorization_required"):
        run_arm(
            _frozen(),
            arm_kind="local",
            model_id="test-model",
            model_revision="test-revision",
            output_dir=tmp_path,
            pricing={"input": 0.0, "output": 0.0},
            budget_cap_usd=5.0,
            authorization="not-authorized",
            base_url="http://127.0.0.1:1",
        )


def test_runner_rejects_a_modified_manifest_with_a_stale_frozen_hash(tmp_path):
    manifest = _frozen()
    manifest["cases"][0]["sources"][0]["text"] += " Changed after freeze."

    with pytest.raises(PilotError, match="frozen_manifest_hash_mismatch"):
        run_arm(
            manifest,
            arm_kind="local",
            model_id="test-model",
            model_revision="test-revision",
            output_dir=tmp_path,
            pricing={"input": 0.0, "output": 0.0},
            budget_cap_usd=5.0,
            authorization=AUTHORIZATION_PHRASE,
            base_url="http://127.0.0.1:1",
        )


def test_runner_rejects_a_modified_manifest_even_after_rehashing(tmp_path):
    manifest = _frozen()
    manifest["cases"][0]["sources"][0]["text"] += " Changed and rehashed."
    identity = copy.deepcopy(manifest)
    identity.pop("frozen_manifest_sha256")
    manifest["frozen_manifest_sha256"] = sha256_json(identity)

    with pytest.raises(PilotError, match="frozen_manifest_not_owner_approved"):
        run_arm(
            manifest,
            arm_kind="local",
            model_id="test-model",
            model_revision="test-revision",
            output_dir=tmp_path,
            pricing={"input": 0.0, "output": 0.0},
            budget_cap_usd=5.0,
            authorization=AUTHORIZATION_PHRASE,
            base_url="http://127.0.0.1:1",
        )


def test_cloud_call_uses_designed_saved_credential_without_returning_it(tmp_path):
    secret = "fixture-r2-saved-cloud-key"
    ref = "analysis-model:deepseek"
    store_model_api_key(tmp_path, ref, secret)
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @property
        def status(self):
            return 200

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "{\"atoms\": []}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }).encode()

    def fake_urlopen(request, **_kwargs):
        captured["authorization"] = request.get_header("Authorization")
        return FakeResponse()

    result = call_openai_compatible(
        [{"role": "user", "content": "public fixture"}],
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-flash",
        api_key_env="DEEPSEEK_API_KEY",
        credential_root=str(tmp_path),
        credential_ref=ref,
        urlopen=fake_urlopen,
    )

    assert result["ok"] is True
    assert captured["authorization"] == "Bearer " + secret
    assert secret not in json.dumps(result)


def test_runner_writes_only_private_receipts_and_resumes_without_second_call(tmp_path):
    calls = []

    def fake_local(messages, **_kwargs):
        calls.append(copy.deepcopy(messages))
        case_id = json.loads(messages[1]["content"])["case"]["case_id"]
        case = next(item for item in _frozen()["cases"] if item["case_id"] == case_id)
        raw_atoms = [_perfect_raw_atom(case, item) for item in case["expected_atoms"]]
        return {
            "ok": True,
            "status": 200,
            "content": json.dumps({"atoms": raw_atoms}, ensure_ascii=False),
            "latency_ms": 10.0,
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "request_sha256": "request",
            "response_sha256": "response",
            "response": {"message": {"content": "private pilot response"}},
        }

    kwargs = dict(
        manifest=_frozen(),
        arm_kind="local",
        model_id="test-model",
        model_revision="test-revision",
        output_dir=tmp_path,
        pricing={"input": 0.0, "output": 0.0},
        budget_cap_usd=5.0,
        authorization=AUTHORIZATION_PHRASE,
        base_url="http://127.0.0.1:1",
        limit=1,
        call_local=fake_local,
    )
    first = run_arm(**kwargs)
    second = run_arm(**kwargs)

    assert first == second
    assert len(calls) == 1
    assert first["processed_case_count"] == 1
    receipt = json.loads(next(path for path in tmp_path.glob("*.json") if path.name != "arm_summary.json").read_text(encoding="utf-8"))
    assert receipt["production_shadow_write_performed"] is False
    assert receipt["raw_write_performed"] is False
    assert receipt["memory_write_performed"] is False
    assert receipt["platform_write_performed"] is False


def test_prompt_digest_changes_when_a_public_source_changes():
    frozen = _frozen()
    before = sha256_json(build_model_messages(frozen["cases"][0]))
    changed = copy.deepcopy(frozen["cases"][0])
    changed["sources"][0]["text"] += " Extra public sentence."

    assert sha256_json(build_model_messages(changed)) != before


def test_hybrid_runner_skips_model_when_rules_resolve_the_case(tmp_path):
    calls = []

    def forbidden_call(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("rule-only case must not call a model")

    summary = run_arm(
        _frozen(),
        arm_kind="local",
        model_id="test-model",
        model_revision="test-revision",
        output_dir=tmp_path,
        pricing={"input": 0.0, "output": 0.0},
        budget_cap_usd=5.0,
        authorization=HYBRID_AUTHORIZATION_PHRASE,
        base_url="http://127.0.0.1:1",
        limit=1,
        pipeline_mode="hybrid_ambiguity",
        call_local=forbidden_call,
    )

    assert calls == []
    assert summary["processed_case_count"] == 1
    assert summary["model_call_case_count"] == 0
    assert summary["rule_only_case_count"] == 1
    assert len(summary["arm"]["results"][0]["atoms"]) == 3


def test_hybrid_runner_sends_only_ambiguous_candidates_to_the_model(tmp_path):
    manifest = _frozen()
    calls = []

    def fake_local(messages, **_kwargs):
        payload = json.loads(messages[1]["content"])
        calls.append(copy.deepcopy(payload))
        assert len(payload["candidates"]) == 1
        assert payload["candidates"][0]["quote"] == (
            "Policy v2 disabled guest access from 2026-04-01 onward."
        )
        return {
            "ok": True,
            "status": 200,
            "content": json.dumps({
                "decisions": [{
                    "candidate_id": payload["candidates"][0]["candidate_id"],
                    "semantic_type": "claim",
                }]
            }),
            "latency_ms": 12.0,
            "usage": {"input_tokens": 40, "output_tokens": 8},
            "request_sha256": "request",
            "response_sha256": "response",
            "response": {"message": {"content": "private hybrid response"}},
        }

    summary = run_arm(
        manifest,
        arm_kind="local",
        model_id="test-model",
        model_revision="test-revision",
        output_dir=tmp_path,
        pricing={"input": 0.0, "output": 0.0},
        budget_cap_usd=5.0,
        authorization=HYBRID_AUTHORIZATION_PHRASE,
        base_url="http://127.0.0.1:1",
        pipeline_mode="hybrid_ambiguity",
        call_local=fake_local,
    )

    assert len(calls) == 1
    assert summary["model_call_case_count"] == 1
    assert summary["rule_only_case_count"] == 35
    result = next(
        item for item in summary["arm"]["results"] if item["case_id"] == "history-en-02"
    )
    assert len(result["atoms"]) == 3
    assert result["model_call_performed"] is True
    assert result["ambiguity_candidate_count"] == 1
    assert result["model_decision_count"] == 1


def test_hybrid_plan_manifest_is_deterministic_answer_key_blind_and_write_free():
    first = build_hybrid_plan_manifest(_frozen())
    second = build_hybrid_plan_manifest(_frozen())
    serialized = json.dumps(first, ensure_ascii=False)

    assert first == second
    assert first["candidate_count"] == 90
    assert first["ambiguity_candidate_count"] == 1
    assert first["model_call_case_count_planned"] == 1
    assert first["rule_only_case_count"] == 35
    assert first["ambiguity_cases"] == ["history-en-02"]
    assert first["all_source_spans_faithful"] is True
    assert first["all_source_refs_present"] is True
    assert first["all_activation_denied"] is True
    assert first["write_performed"] is False
    assert "expected_atoms" not in serialized
    assert "required_atom_ids" not in serialized
    assert "preserved_atom_ids" not in serialized
    assert "forbidden_atom_ids" not in serialized
