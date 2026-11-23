"""What counts as dialogue, and what is runtime and must stay on the computer."""

from __future__ import annotations

import pytest

from tl_client.formats import BUILTIN_FORMATS, extract_message, spec_from_report
from tl_client.redact import redact

ENVELOPE = BUILTIN_FORMATS["message_envelope_content_blocks"]
PAYLOAD = BUILTIN_FORMATS["response_item_payload_message"]


def envelope(kind, content, **extra):
    return {
        "type": kind,
        "sessionId": "s1",
        "timestamp": "2026-11-16T00:00:00Z",
        "message": {"role": kind, "content": content},
        **extra,
    }


def test_plain_user_and_assistant_text_is_dialogue():
    message = extract_message(envelope("user", "服务端放在 NAS 上"), ENVELOPE)
    assert (message.role, message.text, message.session_id) == ("user", "服务端放在 NAS 上", "s1")
    message = extract_message(envelope("assistant", [{"type": "text", "text": "好,这样本机不占空间"}]), ENVELOPE)
    assert (message.role, message.text) == ("assistant", "好,这样本机不占空间")


def test_tool_calls_tool_output_and_reasoning_are_runtime():
    blocks = [
        {"type": "thinking", "thinking": "PRIVATE REASONING"},
        {"type": "text", "text": "我看一下文件"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "cat secrets"}},
    ]
    assert extract_message(envelope("assistant", blocks), ENVELOPE).text == "我看一下文件"
    # A "user" turn that is only tool output was never said by the user.
    assert extract_message(envelope("user", [{"type": "tool_result", "content": "TOOL OUTPUT"}]), ENVELOPE) is None
    # Tool output sitting next to real text does not ride along with it.
    mixed = [{"type": "tool_result", "content": "TOOL OUTPUT"}, {"type": "text", "text": "继续"}]
    assert extract_message(envelope("user", mixed), ENVELOPE).text == "继续"
    assert extract_message(envelope("user", [{"type": "image", "source": {"data": "AAAA"}}]), ENVELOPE) is None


@pytest.mark.parametrize("flag", ["isMeta", "isSidechain", "isCompactSummary", "isVisibleInTranscriptOnly"])
def test_flagged_bookkeeping_turns_are_skipped(flag):
    assert extract_message(envelope("user", "looks like text", **{flag: True}), ENVELOPE) is None


@pytest.mark.parametrize("kind", ["system", "attachment", "file-history-snapshot", "queue-operation"])
def test_non_dialogue_record_types_are_skipped(kind):
    assert extract_message({"type": kind, "message": {"role": "user", "content": "x"}}, ENVELOPE) is None


def test_injected_wrappers_are_removed_from_user_turns():
    only_injected = "<system-reminder>\ninjected context\n</system-reminder>"
    assert extract_message(envelope("user", only_injected), ENVELOPE) is None
    command = "<command-name>/model</command-name>\n<command-message>model</command-message>\n<command-args>x</command-args>"
    assert extract_message(envelope("user", command), ENVELOPE) is None
    said = "<system-reminder>injected</system-reminder>\n把设备页改成一句话接入"
    assert extract_message(envelope("user", said), ENVELOPE).text == "把设备页改成一句话接入"
    viewer = '<artifact-view-context artifact="abc">{"mode":"canvas"}</artifact-view-context>\n\n这块无所谓'
    assert extract_message(envelope("user", viewer), ENVELOPE).text == "这块无所谓"


def test_harness_placeholders_written_in_the_users_name_are_dropped():
    assert extract_message(envelope("user", "[Request interrupted by user]"), ENVELOPE) is None
    assert extract_message(envelope("user", "[Request interrupted by user for tool use]"), ENVELOPE) is None
    dump = "# AGENTS.md instructions for /repo\n\n<INSTRUCTIONS>\nrules...\n</INSTRUCTIONS>"
    assert extract_message(payload("user", dump), PAYLOAD) is None
    kept = "他那边显示 [Request interrupted by user] 是什么意思"
    assert extract_message(envelope("user", kept), ENVELOPE).text == kept
    spec = spec_from_report({"base": "flat_role_content", "runtime_messages": [r"\(no content\)"]})
    assert extract_message({"role": "user", "content": "(no content)"}, spec) is None
    assert extract_message({"role": "user", "content": "[Request interrupted by user]"}, spec) is None
    with pytest.raises(ValueError):
        spec_from_report({"base": "flat_role_content", "runtime_messages": ["("]})


def test_ordinary_markup_the_user_typed_is_kept():
    text = "把 <div> 换成 <section>,再看 <pasted_content>abc</pasted_content>"
    assert extract_message(envelope("user", text), ENVELOPE).text == text


def test_inline_binary_data_is_replaced_not_uploaded():
    text = "看这张图 data:image/png;base64," + "A" * 500 + " 就这样"
    cleaned = extract_message(envelope("user", text), ENVELOPE).text
    assert "AAAA" not in cleaned and cleaned.startswith("看这张图") and cleaned.endswith("就这样")


def payload(role, text, kind="message", block="input_text"):
    return {
        "timestamp": "2026-11-16T00:00:00Z",
        "type": "response_item",
        "payload": {"type": kind, "role": role, "content": [{"type": block, "text": text}]},
    }


def test_payload_shape_keeps_only_user_and_assistant_messages():
    assert extract_message(payload("user", "换成本地模型"), PAYLOAD).text == "换成本地模型"
    assert extract_message(payload("assistant", "已切换", block="output_text"), PAYLOAD).role == "assistant"
    assert extract_message(payload("developer", "<permissions>...</permissions>"), PAYLOAD) is None
    assert extract_message(payload("user", "<environment_context>\n<cwd>/x</cwd>\n</environment_context>"), PAYLOAD) is None
    assert extract_message(payload(None, "thinking", kind="reasoning"), PAYLOAD) is None
    assert extract_message({"type": "event_msg", "payload": {"type": "token_count"}}, PAYLOAD) is None
    assert extract_message({"type": "response_item", "payload": {"type": "function_call_output", "output": "x"}}, PAYLOAD) is None


def test_progress_narration_and_harness_wrappers_are_runtime():
    narration = payload("assistant", "我先读一下配置文件", block="output_text")
    narration["payload"]["phase"] = "commentary"
    assert extract_message(narration, PAYLOAD) is None
    answer = payload("assistant", "结论:服务端放 NAS", block="output_text")
    answer["payload"]["phase"] = "final_answer"
    assert extract_message(answer, PAYLOAD).text == "结论:服务端放 NAS"
    for wrapper in ("subagent_notification", "heartbeat", "turn_aborted", "goal_context", "codex_internal_context"):
        assert extract_message(payload("user", f"<{wrapper}>\nruntime\n</{wrapper}>"), PAYLOAD) is None, wrapper
    assert extract_message(payload("assistant", "<thinking>想一想</thinking>好的", block="output_text"), PAYLOAD).text == "好的"
    spec = spec_from_report({"base": "flat_role_content", "skip_if_equals": {"kind": ["progress"]}})
    assert extract_message({"role": "assistant", "content": "进度 50%", "kind": "progress"}, spec) is None
    assert extract_message({"role": "assistant", "content": "做完了", "kind": "answer"}, spec).text == "做完了"


def test_an_unfamiliar_agent_is_read_from_its_own_description_without_new_code():
    reported = {
        "name": "some-new-agent",
        "base": "flat_role_content",
        "match": {"kind": ["chat"]},
        "role": ["who"],
        "content": ["body.parts"],
        "timestamp": ["at"],
        "session_id": ["thread"],
        "text_block_types": ["say"],
        "skip_if_true": ["hidden"],
        "runtime_elements": ["harness-note"],
    }
    spec = spec_from_report(reported)
    record = {
        "kind": "chat",
        "who": "human",
        "at": "2026-11-16T01:02:03Z",
        "thread": "t-9",
        "body": {"parts": [{"type": "say", "text": "<harness-note>x</harness-note>记住这个"}, {"type": "run", "text": "ls"}]},
    }
    message = extract_message(record, spec)
    assert (message.role, message.text, message.session_id, message.timestamp) == (
        "user",
        "记住这个",
        "t-9",
        "2026-11-16T01:02:03Z",
    )
    assert extract_message({**record, "hidden": True}, spec) is None
    assert extract_message({**record, "kind": "tool"}, spec) is None
    # The shared wrapper list still applies on top of what the agent reported.
    assert "system-reminder" in spec.runtime_elements


def test_bad_format_reports_are_rejected():
    with pytest.raises(ValueError):
        spec_from_report("no_such_format")
    with pytest.raises(ValueError):
        spec_from_report({"base": "flat_role_content", "role": "role"})
    with pytest.raises(ValueError):
        spec_from_report(42)


def test_credentials_are_always_masked():
    text = (
        "key 是 sk-abcdefghijklmnopqrstuvwxyz123456,"
        "GitHub ghp_abcdefghijklmnopqrstuvwxyz0123456789,"
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz.0123456789,"
        "password = Hunter2hunter2,"
        "postgres://admin:s3cretpw@db.local/app"
    )
    masked = redact(text)
    for leaked in ("sk-abcdef", "ghp_abc", "abcdefghijklmnopqrstuvwxyz.0123", "Hunter2hunter2", "s3cretpw"):
        assert leaked not in masked
    assert masked.count("[已打码:密钥]") == 3 and masked.count("[已打码:口令]") == 2
    assert "postgres://admin:" in masked and "@db.local/app" in masked

    pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAB3NzaC1\nxyz\n-----END OPENSSH PRIVATE KEY-----"
    assert redact(f"私钥:\n{pem}\n完") == "私钥:\n[已打码:私钥]\n完"


def test_ordinary_text_is_left_alone():
    for text in (
        "token 用量约 720 万,花费上限无所谓",
        "password: 我不能替你输",
        "token: unknown",
        "把 sk- 开头的 key 填进去",
        "端口 9850,地址 192.168.1.20",
        "提交 977ccebc8fd5ca68",
    ):
        assert redact(text) == text


def test_personal_identifiers_are_masked_by_default_and_can_be_switched_off():
    text = "邮箱 someone@example.com 手机 13800138000 证件 110101199003074514"
    masked = redact(text)
    assert masked == "邮箱 [已打码:邮箱] 手机 [已打码:手机号] 证件 [已打码:证件号]"
    kept = redact(text, {"email": False, "phone": False, "id_number": False})
    assert kept == text
    # Credentials cannot be switched off.
    assert "sk-" not in redact("sk-abcdefghijklmnopqrstuvwxyz123456", {"secrets": False})
