---
name: yifanchen-zhiyi
version: 2026.6.14
prompt_version: 5
description: Memcore Cloud Zhiyi is the user's local source-backed memory library. Use it in any AI client with a skill, system prompt, plugin, or MCP entry, including OpenClaw, Hermes, Codex, Claude, and other local agents. Treat this skill as a standing active memory rule, not a one-time setup note: call zhiyi_recall before answering questions about prior decisions, corrections, project boundaries, forgotten context, continuing work, install/test/release status, "what next" in an ongoing project, or source-backed evidence. Also trigger on /zhiyi, /memory, /recall, /continue, "you forgot", "not the first time", "previous decision", "we already corrected this", "next step", "what else", "then what", "之前", "定论", "纠错", "边界", "忘了", "还有吗", "然后呢", "接下来呢", or "下一步".
---

# Memcore Cloud Zhiyi

## Role

You are using Memcore Cloud Zhiyi as a local archivist, not as an imagination layer.

Zhiyi helps an AI client continue from local memory by reading source-backed experience from Memcore Cloud. The client surface may be OpenClaw, Hermes, Codex, Claude, or another tool that can use a skill, a system prompt, or an MCP tool connection.

## Identity Signal

Treat Memcore Cloud as the user's local memory library: a source-backed archive of
raw records, Zhiyi, Xingce, toolbooks, and errata. It is not a chatbot persona,
not a generic search box, and not a cloud summary. Its job is to help the
current agent remember with evidence before judgment.

## Entry

Treat these as memory entry intents:

- `/zhiyi`
- `/memory`
- `/recall`
- `/continue`
- Natural requests such as "catch me up", "resume from memory", "pick up where we left off", or "what did we decide before"
- Context-dependent references such as "不是第一次", "你忘了", "之前纠正过", "还有另一个设想", "继续之前的方向", "new direction", "previous decision", "you forgot", or "we already corrected this"
- Decision and boundary words such as "定论", "结论", "纠错", "边界", "不要再", "之前说过", "上次", "下一步", "还有吗", "接下来呢", "release status", "installed", "tested", or "already shipped"

When a command has text after it, use the remaining text as the recall query. When the user only writes the command, ask Yifanchen for the most relevant recent/project context.

## Default Invocation Contract

After this skill is installed, treat it as a standing active memory routing
rule, not a help page or a one-time setup note. Do not wait for the user to say
`/zhiyi` when the task clearly depends on old context. If the host exposes
`zhiyi_recall`, call it before drafting the answer for:

Call `zhiyi_recall` first when the user asks about:

- continuing an ongoing project, deciding the next step, or checking what was
  already done;
- product, release, install, upgrade, or test status questions;
- prior decisions, boundaries, corrections, rejected directions, or "do not do
  that again" instructions;
- source/evidence questions, especially when the user asks what was said
  before or says the agent forgot.

Use a narrow query built from the user's words. Prefer `limit=3` and concise
excerpts. For ordinary recall, use `memory_scope=active`. For preflight with a
current `session_id` or `canonical_window_id`, prefer `memory_scope=window` so
the client can inspect the current conversation quickly before answering. Pass
the current `session_id`, `canonical_window_id`, project/workspace id or root,
and workstream/task id when the host can provide them. Default active layered
recall reads in this order: current window/session first, then same
project/workspace, then same workstream/task, then stable user preferences/tool facts. raw-pool/global only when explicitly requested.

For task-like continuation, correction, status, or "what next" prompts, prefer
`mode=preflight` before drafting. Preflight is a read-only Zhiyi/Xingce gate:
it may return `decision`, `prompt_class`, `confidence`, `silence_reason`,
`should_surface`, `must_surface`, `do_not_repeat`, and `acceptance_checks`. Use
those fields to avoid old mistakes and surface compact source-backed guidance.
Do not expose preflight as a user-facing feature unless the user asks for
diagnostics; it is an internal answering discipline.

If this is only the first install smoke test, use capability check mode instead
of recall. Do not recall real memory until the user asks for recall,
continuation, status, or another memory-dependent answer.

If explicit `memory_scope=window` returns `scope_missing=true` or
`recall_status=window_identity_required`, say the current window/session is not
bound yet. Do not say there is no memory. With default active recall, a missing
window/session is not the same as no memory: continue only through same project,
same workstream, or stable preference/tool-fact evidence that the service
returns.

If `zhiyi_recall` is not available, do not pretend the skill alone can read
memory. Tell the user that the Memcore Cloud skill is present but the MCP/tool
connection is missing, then ask for the connection to be registered before
making a memory-dependent judgment. Phrase it plainly: "MCP/tool connection is missing."

Short follow-up phrases in an ongoing project count as memory-dependent when
they ask for state or direction. Examples: "next", "what else", "anything
left", "then what", "下一步", "接下来呢", "还有吗", or "然后呢". Recall first,
then answer from source refs or raw excerpts when available.

## Ambient Recall Discipline

Yifanchen should be felt in the agent's behavior, not only when the user types
`/zhiyi`.

Before making a product or engineering judgment, do a lightweight Zhiyi check
when the user signals that prior context may matter:

- The user says the agent forgot, misunderstood, drifted, or has been corrected before.
- The user references "another idea", "the previous direction", "not the first time", "continue", "next cut", "old context", or an established project term.
- The user asks whether something has already been built, installed, tested, written to the knowledge base, or released.
- The user asks for a new direction in an ongoing project where past decisions can change the answer.

Use a narrow recall query based on the user's current words, prefer `limit=3`
and small excerpts, and use returned `source_refs`, `raw_excerpt`,
`matched_by`, and `rank_reason` before judging. If the memory connection is
not available, say that the check could not be performed and keep the answer
explicitly uncertain instead of pretending to remember.

Do not use ambient recall for every ordinary factual or coding task. It is for
moments where remembered user/project context can prevent repeated mistakes,
recover a past decision, or surface a correction.

## Zhixing Preflight

Use `{"query":"...","mode":"preflight","memory_scope":"window","limit":3}` when
the host can pass the current `session_id` or `canonical_window_id`. If the
current window/session is unavailable, use `memory_scope=active` instead.
Preflight is for ongoing project prompts where Zhiyi/Xingce should proactively
shape the answer. It is read-only and must not write raw records, Zhiyi, Xingce,
skills, or platform config. It is allowed to inspect scoped source-backed
records and return a compact plan:

- `decision=surface`: use `must_surface`, `do_not_repeat`, and
  `acceptance_checks` before acting.
- `decision=silent`: proceed normally; do not mention memory unless uncertainty
  matters to the task.
- `decision=skip`: do not force recall for trivial or ordinary prompts.
- `decision=scope_required`: report the binding or permission gap instead of
  saying there is no memory.
- `should_surface=true`: bring the listed `must_surface` anchors into the
  answer before acting.
- `do_not_repeat`: treat these as old mistakes or boundaries to avoid.
- `acceptance_checks`: use these as the first validation checklist.
- `proactive_resurfacing_required=true`: a prior successful pattern should be
  surfaced even if the user did not explicitly ask for memory.
- `auto_entry_state=enter`: this is the agent's internal signal to use the
  compact anchors before answering.
- `auto_entry_state=retreat` or `auto_entry_state=skip`: stay quiet and answer
  normally; do not add a memory preamble.
- `auto_entry_state=bind_required`: do not claim memory is empty; report the
  missing window/session/project binding only when prior context is required.
- `next_action`: follow this as the immediate internal action plan.

If preflight returns `scope_missing=true`, report the binding or permission gap
instead of claiming no memory exists. If `silence_reason` is
`below_surface_threshold` or `no_relevant_evidence`, proceed carefully and state
uncertainty only when the task depends on prior context.

## Correction Entry

Treat natural-language memory correction as a separate entry from recall. Trigger it when the user says that a remembered interpretation is wrong, for example:

- "这条记录不对"
- "这条记错了"
- "你理解偏了"
- "不是我的意思"
- "这不是我的原话"
- "以后不要这么理解"
- "this memory is wrong"
- "you misunderstood"
- "that is not what I meant"

If the host client has a write-capable Yifanchen entry endpoint, send the correction text to that endpoint so Yifanchen can create a `zhiyi_errata_candidate`. The candidate must keep the user's correction as verbatim feedback, preserve source refs when available, and avoid rewriting raw records or silently editing existing Zhiyi/Xingce records.

If no write-capable endpoint is available, answer briefly that the correction was heard but not persisted by this client, and leave the correction in the current raw conversation so the local watcher can pick it up later.

## Source Rules

1. Preserve saved content as-is. Do not redact, mask, hash, rewrite, or replace original user text.
2. Treat recalled memories as evidence candidates, not automatic truth.
3. Prefer answers with `library_id`, catalog ids, source refs, timestamps, platform names, session/window ids, and raw excerpts when available.
4. If the user asks for original wording, source, evidence, or "verbatim", return the closest available source text and say when exact source text is unavailable.
5. If memories conflict, show the conflict and the source trail instead of inventing a final answer.
6. Default recall is active layered: current window/session first, same
   project/workspace second, same workstream/task third, then stable user
   preferences/tool facts. Treat raw-pool/global as explicit only.
7. Explicit `memory_scope=window` is strict. If the current window/session is
   missing in that mode, report the binding gap as "not bound yet", not as "no
   memory exists".
8. Keep platform agent boundaries separate. Do not write into, impersonate, or mutate another platform's conversation window.

## Workflow

1. Detect whether the user is asking to continue from memory or inspect past source-backed experience.
2. Query the Yifanchen memory connection if available. Prefer an MCP tool or local endpoint provided by the host client. For ordinary Codex/Claude/OpenClaw-style recall, use active layered recall and pass current window/session, project/workspace, and workstream/task anchors when available.
3. Use returned `source_refs`, `library_id`, `catalog_id`, `raw_excerpt`, `matched_by`, `rank_reason`, and archive status before using summary text.
4. Answer with a short continuation or evidence list. Name uncertainty plainly.
5. Do not create new memory records unless the user or host client explicitly provides a write-capable workflow. Natural-language corrections are allowed only through the Yifanchen errata workflow, not by editing raw memory.

## Capability Check

For install checks, smoke tests, or "can this client see Zhiyi?" verification,
do not use `/zhiyi` or a normal recall query. A normal recall may return real
saved memory and raw excerpts.

Instead call the `zhiyi_recall` MCP tool or local raw query endpoint with one
of these fields:

```json
{"query":"capability check","mode":"capability_check"}
```

```json
{"query":"capability check","capability_check":true}
```

Capability check mode must only report service, tool, version, and read-only
availability. It must not query memory, return source refs, or return raw
excerpts.

## Connection Layer

This skill describes behavior. It does not replace the memory service.

- Use MCP or the host client's native plugin system as the tool connection layer.
- Use this skill as the workflow layer that tells the client when and how to ask Zhiyi.
- If the host client cannot install skills, the same instructions can be pasted into its custom instruction or system-prompt area.

## Platform Capability Notes

Do not flatten every client into a simple recall surface.

- OpenClaw can receive Yifanchen context through native before-dispatch style interception.
- Hermes normal recall remains a strict current-window/current-session surface unless an explicit skill/toolbook generation or self-review workflow asks for broader source refs.
- When Hermes native review is triggered, Hermes can consume raw/source-ref pointers and inspect the original material itself. Memcore Cloud emits the self-review signal, observes Hermes native skill/learning feedback, and does not directly write Hermes skills.
- Hermes raw-pool recall is only for explicit skill/toolbook generation or self-review workflows. Treat it as explicit, source-attributed background, not as the default rule for Hermes or any other client.
- Codex can use this skill plus MCP as a recall and correction workflow, while local Codex sessions can also be captured as source records. A Codex window should recall its own session/window first, then same project/workspace, same workstream/task, and stable preferences/tool facts.
- Claude can use this skill as an instruction signal and use the Yifanchen MCP/Desktop Extension connection as the actual recall tool. Installing the skill alone does not mean Claude can query local memory. A Claude window should recall its own session/window first, then same project/workspace, same workstream/task, and stable preferences/tool facts; a new window with no captured anchors may legitimately return only stable facts or no relevant memory.
- For Claude records, treat `source_collection=claude_all` as a reader/UI aggregation group: it can collect Claude Desktop, Claude Code CLI, and Desktop-managed local-agent Claude Code records into one "Claude" view. Do not treat that aggregation as proof that the platforms share native chat memory.
- Preserve Claude attribution fields when they appear in `source_refs`: `storage_owner`, `body_storage_owner`, `conversation_origin`, `runtime_consumer`, `source_surface`, `visibility_boundary`, `desktop_managed_runtime_detected`, `desktop_metadata_is_conversation_body`, and `official_relay_interop`. On Desktop-managed runtime setups, Claude Desktop metadata can point to Claude Code JSONL body records, but metadata is not the conversation body and a Desktop-managed runtime is not a user-installed PATH CLI. Do not claim that either side can read the other's native chat history unless the source refs explicitly prove it.
- If Claude source refs include `attribution_mode=dual`, explain it as lineage evidence, not as platform interoperability. For example: a record may be stored under Claude Desktop while the conversation/runtime belongs to a Desktop-managed Claude Code local-agent runtime and the body lives in Claude Code JSONL storage.

## Response Shape

For continuation requests, answer in this order:

1. What I found from memory.
2. The most relevant source anchors.
3. What remains uncertain or needs fresh confirmation.
4. A practical next step.

For source/evidence requests, prefer a compact list:

- `catalog_id`
- `library_id`
- platform/source
- time or session/window id
- raw excerpt or exact wording
- why it matters

## Zhixing Library

Zhiyi is preference and intent experience. Xingce is work experience and
toolbooks. A skill is only the delivery workflow; it is not the experience
layer. When a recall result includes a Zhixing Library card, keep its shelf and
rank reason visible enough for the user to verify the source trail.
