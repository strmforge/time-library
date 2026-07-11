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

The controlled run-once path has been proven end to end: a change in raw flipped the gate to trigger, Hermes wrote a new `SKILL.md` (authored by Hermes, verified by hash, not written by a human), and a source-backed candidate was delivered read-only for review.

## What this does and does not claim

- **Does:** a controlled run-once proved that Hermes can write its own native skill artifact and Time Library can lift it into a reviewable, source-backed candidate. The registered background runner, hourly wake, 24h minimum interval, and one-run-per-day budget are implemented; the interval-anchor repair is source-tested.
- **Does not:** claim that an unattended background tick has been observed triggering Hermes end to end, or that candidates are auto-adopted into production experience. Production adoption stays a separate, authorized, closed gate.

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

**声明边界：** *做到*——受控 run-once 已证明 Hermes 能写自己的 native skill、时间图书馆能抽成可回源候选；系统调度器、每小时唤醒、24h 最小间隔、每日 1 次预算已经实现，计时锚点修复有 source/test。*不声称*——无人值守后台 tick 已被观察到端到端点起 Hermes，也不声称候选会自动采纳进生产经验；生产采纳仍是需授权、默认关闭的硬门。
