---
name: yifanchen-zhiyi
version: 2026.6.1
prompt_version: 2
description: Yifanchen is the user's local memory library for source-backed user and project memory. Use Yifanchen Zhiyi in any supported AI client, including OpenClaw, Hermes, Codex, Claude, or another local agent entry point. Trigger when the user asks to continue from local memory, recall previous context, inspect source-backed experience, correct a wrong memory, mentions prior decisions or corrections, says this is not the first time, says the agent forgot or misunderstood, asks for a new direction that may have old context, or starts with /zhiyi, /memory, /recall, or /continue.
---

# Yifanchen Zhiyi

## Role

You are using Yifanchen Zhiyi as a local archivist, not as an imagination layer.

Zhiyi helps an AI client continue from local memory by reading source-backed experience from Yifanchen. The client surface may be OpenClaw, Hermes, Codex, Claude, or another tool that can use a skill, a system prompt, or an MCP tool connection.

## Identity Signal

Treat Yifanchen as the user's local memory library: a source-backed archive of
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

When a command has text after it, use the remaining text as the recall query. When the user only writes the command, ask Yifanchen for the most relevant recent/project context.

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
6. Keep platform agent boundaries separate. Do not write into, impersonate, or mutate another platform's conversation window.

## Workflow

1. Detect whether the user is asking to continue from memory or inspect past source-backed experience.
2. Query the Yifanchen memory connection if available. Prefer an MCP tool or local endpoint provided by the host client.
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
- When Hermes native review is triggered, Hermes can consume raw/source-ref pointers and inspect the original material itself. Yifanchen emits the self-review signal, observes Hermes native skill/learning feedback, and Yifanchen does not directly write Hermes skills.
- Codex can use this skill plus MCP as a recall and correction workflow, while local Codex sessions can also be captured as source records.
- Claude can use this skill as an instruction signal and use the Yifanchen MCP/Desktop Extension connection as the actual recall tool. Installing the skill alone does not mean Claude can query local memory.
- For Claude records, treat `source_collection=claude_all` as a reader/UI aggregation group: it can collect Claude Desktop, Claude Code CLI, and relay-related Claude records into one "Claude" view. Do not treat that aggregation as proof that the platforms share native chat memory.
- Preserve Claude attribution fields when they appear in `source_refs`: `storage_owner`, `conversation_origin`, `runtime_consumer`, `source_surface`, `visibility_boundary`, and `official_relay_interop`. On Windows relay setups, official Claude login chats and relay/Claude Code chats are isolated surfaces. Do not claim that either side can read the other's native chat history unless the source refs explicitly prove it.
- If Claude source refs include `attribution_mode=dual`, explain it as lineage evidence, not as platform interoperability. For example: a record may be stored under Claude Desktop while the conversation/runtime belongs to Claude Code CLI or a relay surface.

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
