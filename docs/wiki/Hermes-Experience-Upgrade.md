# Hermes Experience Upgrade

Hermes is a second platform wired into Time Library on purpose. It is not just another source of raw — it is where a distinctive loop runs: Hermes generates skills, Time Library observes them and lifts them into platform-neutral experience. The point is that experience can be abstracted across platforms — "different flowers from the same soil."

## The loop

```text
raw record
-> Hermes generates / upgrades a skill   (a platform projection, not the source of truth)
-> Time Library observes the skill        (never writes Hermes skills itself)
-> abstracts a source-backed experience candidate  (points back to origin)
-> candidate delivered for review          (not auto-adopted)
```

Time Library only **observes** Hermes-generated skills and abstracts experience candidates from them; it never writes a skill for Hermes, and it never silently adopts a candidate into production experience. Hermes reads raw (with source refs) to generate skills; recall for other purposes stays window-isolated.

## Autonomous, value-gated

When Hermes is connected, the autonomous loop is gated by value rather than a fixed schedule:

- **Change gate** — it only fires when there is new raw. No new raw means no trigger and no spend.
- **Value-adaptive frequency** — a run that produces usable candidates keeps or tightens the cadence; repeated empty runs back off automatically until new material arrives.
- **Cost ceiling** — a hard per-cycle cap, as a guardrail, not a knob.

This autonomous chain has been proven end to end on a controlled run: a change in raw flipped the gate to trigger, Hermes triggered itself and wrote a new `SKILL.md` (authored by Hermes, verified by hash, not written by a human), and a source-backed candidate was delivered read-only for review.

## What this does and does not claim

- **Does:** on a trigger, Hermes writes its own native skill artifact, and Time Library lifts it into a reviewable, source-backed experience candidate; spend is bounded and the loop returns to idle when there is no new raw. It runs as a registered, value-gated background agent (wakes hourly, a 24h minimum interval, one run per day) — verified to wake, gate, and correctly skip when nothing is due, with no idle spend.
- **Does not:** auto-adopt candidates into production experience — that stays a separate, authorized, closed gate. Note also that the unattended fire-through (a background tick actually triggering Hermes end to end) has not been observed yet, because the gate correctly skips until the minimum interval elapses with new raw; the full fire-through was proven on the earlier controlled run.

## 中文

Hermes 是刻意接进时间图书馆的第二个平台。它不只是又一个 raw 来源——它是一条独特回路的所在：Hermes 生成 skill，时间图书馆观察它、抽成平台无关的经验。要点是经验能跨平台抽象——“同一片土地长不同花”。

**回路：**

```text
原始记录
→ Hermes 生成/升级 skill（平台投影，不是源头真相）
→ 时间图书馆观察 skill（从不替它写 skill）
→ 抽成可回源的经验候选（回指起源）
→ 候选送去评审（不自动采纳）
```

时间图书馆**只观察** Hermes 自生成的 skill 并抽经验候选；从不替 Hermes 写 skill，也从不把候选偷偷采纳进生产经验。Hermes 读带来源的 raw 来生成 skill；其它用途的召回仍单窗口隔离。

**自主、价值门控：** 接上 Hermes 后，自主环跟价值走而不是定时死跑——**变化门控**（只在有新料时点火，无新料零花费）；**价值自适应**（有可用产出就保持/加密，连续空产自动退频，有新料恢复）；**成本天花板**（护栏，不是旋钮）。

这条自主链路已在**受控 run-once** 上端到端跑通：raw 变化把门控翻成触发，Hermes 自己触发、写了新的 `SKILL.md`（作者是 Hermes、哈希可核，不是人代写），一条可回源候选被只读送达评审。

**声明边界：** *做到*——触发时 Hermes 写自己的 native skill，时间图书馆抽成可回源、可评审的经验候选，花费有界、无新料即回到 idle。它以**受价值门控的后台常驻**（已注册进系统调度器）运行：每小时醒、24h 最小间隔、每日 1 次，已验证会醒、会门控、无到期料时正确跳过、零空烧。*不声称*——候选自动采纳进生产经验（那是另一道、需授权、默认关闭的硬门）；也不声称无人值守的完整 fire-through（后台 tick 真把 Hermes 端到端点起来）已发生——门控会正确跳过直到最小间隔满且有新料，完整 fire-through 是早先受控 run 证的。
