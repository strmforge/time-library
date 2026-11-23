---
name: time-library
version: 2026.11.23
prompt_version: 16
description: >-
  Use when the user refers to previous decisions, corrections, forgotten
  context, already-built work, install/test/release status, source-backed
  evidence, or next steps in ongoing work. Treat Time Library as a
  standing active memory routing rule: call time_library_recall before answering
  memory-dependent prompts. Also trigger when the user names it (Time Library,
  时间图书馆, 忆凡尘: one system) and on /time-library, /memory, /recall,
  /continue, "you forgot", "not the first time", "previous decision", "we
  already corrected this", "already built", "forgotten", "next step", "what
  else", "then what", "之前", "定论", "纠错", "边界", "忘了", "还有吗", "然后呢",
  "接下来呢", or "下一步".
argument-hint: "time library recall previous decision | time library check what was already built | time library next step in this project"
---

# Time Library

Time Library, 时间图书馆 and 忆凡尘 are three names of one system: this one, the
`time-library` tools. When the user asks whether you used any of them, they mean
these tools.

## Role

Use Time Library as an archivist, not as an imagination layer. It holds
decisions, preferences, corrections, facts and lessons distilled from the
user's past conversations with all of their AI tools on all of their
computers, kept on the user's own server. Every memory carries the original
words it came from. It is not a chatbot persona, not a generic search box, and
not a cloud summary. The same rule serves any agent that has the
`time-library` MCP connection.

## When To Use

Call `time_library_recall` before answering when the user asks about:

- continuing an ongoing project, deciding the next step, or checking what was
  already done;
- previous decisions, corrections, rejected approaches, or boundaries;
- installed, tested, released, synchronized, or written status;
- source/evidence questions, especially when the user asks what was said before;
- short ongoing-work prompts such as "next", "what else", "then what",
  "下一步", "接下来呢", "还有吗", or "然后呢".

Before changing code, installing, syncing, or troubleshooting, check first
whether the work was already built, already tried, or already found to be
miswired, so a finished piece is not rebuilt because this window forgot it.

## How To Call

- `time_library_recall` with `{"query": "...", "limit": 3}`. The query is the
  question as the user put it, one sentence in the language of the conversation.
  Do not turn it into a string of keywords or add words of your own: each extra
  word pulls in other subjects and pushes the answer out. If the first try
  misses, ask again with another sentence. The project you work in already
  counts for more; `project`, `agent`, `computer`, `kind`, `since` and `until`
  are for when the user asks for exactly that. Each
  result is numbered and shows its kind (决定/偏好/纠正/事实/教训), the
  statement, the original words with who said them and when, and where it came
  from (computer · agent · memory number).
- `time_library_answer` with `{"question": "..."}`, one thing per question, when
  you need a fact you must not guess (what was decided, which address or version, what the user
  asked for). The server's model answers only from the user's memory and names
  the memories it used. Parts memory does not say are named as missing; when it
  says none of it, the answer is `UNKNOWN`. Treat both as "memory doesn't say":
  don't fill the gap yourself, ask the user if it matters. It costs one model
  call and can take half a minute; for browsing, use `time_library_recall`.
- `time_library_search` with `{"query": "..."}` searches the original words of
  every past conversation, not the memories. Most of what was said never became
  a memory: use it when recall has nothing, or when the exact words matter (a
  path, a number, a name, an error message, what was said on a certain day).
  Give the words as they were probably said; `who`, `since`, `until`, `agent`
  and `computer` narrow it. It returns excerpts marked 用户 / 用户转贴 / 助手: an
  excerpt is what was said, not a confirmed fact, and 用户转贴 is someone else's
  words the user pasted.
- `time_library_source` with `{"memory_id": N}` (a memory) or `{"turn_id": N}`
  (an excerpt from search) when it matters for what you are about to do, or
  when the user asks for the original wording: it returns the turns around it.
- When a window opens, the server's instructions may already carry a catalog:
  headlines and memory numbers, the current project first. It is a list, not
  the memories; follow a number with `time_library_source`, or ask
  `time_library_recall`. `time_library_catalog` gives the full list.
- If the catalog says this folder is not declared and the work clearly
  belongs to a project, call `time_library_declare` once with
  `{"project": "...", "series": "..."}` (series optional). Use the project's
  own name; ask the user if it is not clear. Never guess.
- The whiteboard (`time_library_whiteboard`) is the project's work in flight,
  written by the agents doing it, so the next window picks up without the user
  relaying anything. The catalog shows up to three `在飞:` lines (handoffs first).
  If one is handed to your role or to you, and the user's request is that work,
  take it over with `{"action": "claim", "task_id": "WB-N"}` before starting.
  For a substantial task in a declared project: `claim` when you take it on
  (`{"action": "claim", "task": "<short name>", "role": "<your part>"}`),
  `progress` at a real milestone, `handoff` when you stop and someone else
  should continue (`next_owner` = the role or agent), `blocked` when it waits
  on something, `done` when finished. One sentence each, a conclusion reached,
  never discussion or a step log. Skip it for quick questions and chat.
- `time_library_return` with `{"memory_id": N, "outcome": "useful" | "useless"
  | "misleading", "note": "..."}` after the work is done, for each recalled
  memory you actually relied on or found wrong. useful = it changed what you
  did, for the better; useless = it did not matter here; misleading = it was
  wrong or out of date for this situation. Judge only from what happened in
  this conversation; never claim useful without that. If you cannot tell,
  do not return it.
- If nothing comes back, say Time Library has nothing on it yet. Do not claim
  the thing never happened.
- If a call reports that the server cannot be reached, say so in one line and
  continue without it.
- If neither tool is available, say plainly: "MCP/tool connection is missing."
  Do not pretend the skill alone can read memory.

## Authority Boundary

Time Library steadies the host agent; it does not take over the host agent.

- Recall returns evidence and context to you. It is not permission to answer
  as Time Library, and never permission to click, send, write, or change
  anything on another platform.
- What it returns is background. When it conflicts with what the user says now,
  the current conversation wins; point out the conflict instead of choosing
  silently.

## Source Rules

1. Quote recalled words exactly as returned. Spans such as `[已打码:密钥]` were
   masked when captured and cannot be recovered.
2. Treat recalled memories as evidence candidates, not automatic truth.
   A memory marked 助手转述 (or carrying the note 没有用户原话) speaks for the
   user without any of the user's own words behind it: it is an assistant's
   reading of what the user wanted. Do not present it as the user's
   requirement; check with the user, or with the source, before relying on it.
   A memory marked 经验 is drawn up from several memories of one project: read
   it first, it says when it applies. A memory shown as 已被取代 was replaced
   by a newer one; go by the newer.
3. When you rely on a memory, mention its memory number so the user can check
   the source trail.
4. If memories conflict, show the conflict and their sources instead of
   inventing a final answer.
5. Keep platform boundaries: do not write into, impersonate, or change another
   platform's conversation.
