# GitHub Positioning Draft For 2026.6.16

This is a local maintainer draft. Do not publish it before the release decision.

## One-line Positioning

Keep local AI agents from starting over.

## Chinese Positioning

让本机 AI 不再每次从零开始。忆凡尘会保留可回源的工作上下文：找回旧对话和偏好，复用做成过的修复办法，并且能回到原始记录核对。

## Homepage Should Lead With Features

Use the high-star memory-project pattern: one sentence, feature list, quick
demo, install, safe verification. Do not lead with internal theory.

1. **Shared local context**
   One local record base for Claude Desktop, Claude Code CLI, Codex, OpenClaw,
   Hermes, Cursor-style tools, and popular open-source agents.

2. **Automatic local records**
   Useful AI conversations and tool traces stay on the user's own computer,
   organized by device and source tool.

3. **Source-backed recall**
   The agent can answer old decisions, preferences, fixes, and project
   boundaries with compact source refs, hit reasons, and optional bounded
   excerpts.

4. **Reusable work paths**
   Repeated fixes, review steps, project rules, gotchas, and validation paths
   become reusable guidance for the next AI window.

5. **Traceable experience evolution**
   Successful fixes, mistakes, and user corrections can become candidates.
   Only source-backed candidates with original evidence and acceptance checks
   can be adopted into Xingce; later changes can leave errata, upgrade, or
   rollback receipts.

6. **Experience for every local agent**
   Xingce is not private to one tool. Skill-, custom-instruction-, and
   MCP-capable local agents can read the same work experience before acting.

7. **Record Doctor**
   A one-command safe check shows whether records are guarded before the user
   trusts recall.

8. **Local console**
   A browser page shows connected tools, recent record health, safe capability
   checks, and raw record locations.

9. **No cloud account required**
   Data stays local by default. Summaries help navigation, but original records
   remain the source of truth.

10. **Simple install**
   One shell command, PowerShell, or double-click installers in the release zip.

## Product Story To Keep

- Keep the homepage centered on user tasks: preserve local records, recall prior
  context, reuse proven work paths, and verify answers from source evidence.
- Raw records are the trust basis: public copy should say source-backed, raw
  records, source refs, receipts, and record chain.
- AI-readable knowledge sediment should reuse the existing five shelves instead
  of adding a sixth Obsidian-like layer:
   - `raw`: original records and source material.
   - `zhiyi`: preference, intent, corrections, and stable understanding.
   - `xingce`: work experience, methods, validation paths, and adoption status.
   - `toolbook`: tool-facing usage knowledge and operational notes.
   - `errata`: corrections, conflicts, and trust repair.
- Quiet recall remains a feature: default to compact source refs, counts,
  receipts, and rank reasons; raw excerpts are explicit and bounded.

## What Not To Lead With

- Do not present this as an Obsidian integration. Markdown-like, AI-readable
  structure is an inspiration, not a product dependency.
- Do not present Xingce as a Skill marketplace. Xingce is experience sediment
  and validation governance.
- Do not put detailed connector matrices in the main public story. Public copy
  can say "supports local AI tool connection"; maintainer docs can keep the
  detailed integration table.
- Do not mention private local agent-rule files or maintainer-only repository
  mechanics.

## Suggested README Shape

1. Hero:
   "Keep local AI agents from starting over."

2. Feature list:
   shared local context, automatic local records, source-backed recall,
   reusable work paths, Record Doctor, local console, no cloud account, simple
   install.

3. Quick demo:
   local console, safe capability check, one sample real recall question.

4. Proof blocks:
   - "Records are guarded": record doctor / record chain.
   - "Recall is source-backed": source refs and bounded raw excerpts.
   - "Experience can improve": Xingce candidates, validation receipts, apply
     gates, rollback receipts.

5. Install:
   simple commands plus double-click installer entries for macOS and Windows.

6. Safety first:
   capability check before real recall.

## Short Chinese Homepage Copy

忆凡尘让本机 AI 工具保留可回源的工作上下文：自动保留本机对话记录，按来源归档；问旧决定、偏好、修复办法或项目边界时，默认返回来源线索和命中理由；需要原文时，再展开有界证据。

它不只找回“说过什么”，也保留“下次怎么做”：排障顺序、复核步骤、项目规矩、踩坑记录和验收办法，都可以变成下一次可参考的工作路径。行策经验不是某个工具的私有 skill；支持 skill、自定义指令或 MCP 的本机 agent，都能在动手前读取同一套经验。经验会进化，但不黑箱；做成、踩坑、纠错会先进入候选馆藏，带来源、原文和验收条件后才能采纳进行策，后续还能升级、勘误或回滚。记录医生会先证明记录链路守住了，再让你测试真实召回。

## Release Decision Notes

- 2026.6.16 is still a local candidate until the user explicitly authorizes
  push, tag, or GitHub Release publication.
- The candidate package must be rebuilt after any README or release-note edits
  that should ship.
- Public release claims should only cite validation actually run in the current
  candidate pass.
