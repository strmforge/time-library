# Time Library / 时间图书馆

<p align="center">
  <img src="assets/brand/time-library-logo-zh.png" alt="忆凡尘 时间图书馆" width="220">
</p>

<p align="center">
  <strong>把人间说过的话，留在自己身边。</strong>
</p>

**时间图书馆（忆凡尘 · Time Library）** 是一层 AI 工作续接系统。

你在 Claude Code、Codex、OpenClaw 等 AI 工具里和 agent 说过的话、定下的事、纠正过的错，
它都收在你自己的服务器上（家里的 NAS），整理成每条都能回到原话的记忆，
让下一个窗口、下一台电脑、下一个 agent 接得上，不用你再讲一遍。

它不是让你多开一个系统。你继续在原来的 AI 工具里工作，它在旁边记、在需要时递上来。

> 2026.11.23 是一次**重构**：目标没变，架构、代码和安装方式都重做了。
> 改了什么、为什么改，见 README 的[这是一次重构](README.zh-CN.md#这是一次重构)。

---

## 一句话

时间图书馆不是聊天记录相册，也不是技能库。

它是一份放在你自己家里的记忆：所有电脑上的所有 agent 共用；底下是原话，上面是从原话里
提炼出来的决定、偏好、纠正、事实和教训；每条记忆都说得出出自哪句话、是谁说的。
换窗口、换电脑、换 agent 时，AI 不必每次都从头认识你。

---

## 名字

**忆凡尘**是它最早的名字。

"忆"是记忆，也是回忆：保存、回指、追溯。它关心的不是某一轮回答结束后还剩多少上下文，
而是那些真实发生过的对话、选择、纠偏、失败、偏好和经验。只有原话还在，之后整理出来的
经验才有根。

"凡尘"是普通人真实生活和工作的现场。人用 AI 工具时并不总是在做一个正式项目：可能在排查
一台机器、比较一个选择、解释自己的偏好、学一个工具，也可能在反复试错后改了原来的做法。
这些看似琐碎的痕迹，往往正是长期经验的来源。

**时间图书馆**说的是它怎么运作：

- 原话是**底本**，每条记忆都是从底本里摘出来的，引文逐字核对，对不上就不收。
- 每个项目有一份**书单**，agent 一打开窗口就看得到这个项目里记着什么。
- agent 查记忆是**借书**；用完可以**还书**，并评价"有用 / 没用上 / 误导"，下一个借的人看得到。
- 记忆有**时间**：第一次和最后一次说起、出现在几段对话、后来的说法取代了哪条旧的、
  哪条被一再评为误导而过时。翻得到它怎么变过来的。

---

## 原样保存是底线

时间图书馆的判断很简单：你说过的话本身就是最高事实。

很多 AI 记忆方案会把原话压缩、改写成第三人称结论，只留摘要或标签。时间图书馆不把这些当作
原话的替代品：

- 不改写；
- 不替换成摘要；
- 不替换成哈希；
- 不把整理结果冒充原文。

提炼可以发生，召回可以发生，经验也可以从中长出来；但每条记忆都必须带着它所依据的原话，
要看完整的前后文，一次调用就到。

只有两处例外，都在对话离开电脑之前完成，而且不冒充原文：

- **运行态留在电脑上**：工具调用、工具输出、思考过程、注入的上下文不是你和 AI 说的话，
  客户端在本机就去掉，不上传。原始会话文件仍在各工具自己的位置。
- **密钥打码**：API key、令牌、私钥、口令一律换成"[已打码:…]"标记；邮箱、手机号、证件号
  默认打码，可以关。打码处明确标出，不会被当成原话的一部分。

---

## 分得清是谁说的

在对话记录里，你贴进来的东西也算"用户说的"：别的 AI 的报告、一篇文章、另一个窗口的结论。
但那不是你的话。

时间图书馆把三种声音分开：你亲口说的、助手转述的、你贴进来的别人的话。一条"偏好"如果只
建立在别人的话上，会被明确标出来，不会冒充成你的偏好。

---

## 经验不是 Skill

在很多 AI 工具里，"skill"通常意味着一个可调用的能力：有触发条件，有步骤，有输入输出，
像一个可以被包装起来的函数。

但人在真实生活和工作中积累的很多东西，并不是函数。它可能是：

- 一个长期偏好；
- 一次明确纠偏；
- 一个项目不能乱动的边界；
- 一次失败后留下的验收方法；
- 某类问题下次应该先查的链路；
- 一个 AI 下次不该再重复犯的错误。

这些都没有标准输入输出，却会真实影响下一次怎么回答、怎么排障、怎么继续推进。

所以时间图书馆把记忆分成**决定、偏好、纠正、事实、教训**五种，每个项目再归纳成几张
**经验卡**；它们都能回到原话。Skill 可以是某个平台的入口；经验才是跨平台、可回源、
可审查、可继续生长的底层资产。

---

## 平台自己接入

时间图书馆不为任何 AI 工具写适配。

你把一句话发给某个 agent，它自己装客户端，自己描述"我是谁、会话记录存在哪、长什么样、
支持哪些接入方式"，先在自己的文件上检查对了，再报上来。遇到没见过的新 AI 工具，也不用等谁
给它写代码：它能把自己说清楚，就能接进来。

---

## 它实际怎么用

日常使用时，你不需要先打开时间图书馆再聊天。

你继续在原来的 AI 工具里工作。时间图书馆在旁边：

- 客户端把新对话送到 NAS，每晚提炼成记忆；
- agent 一打开窗口就看到当前项目的书单；
- 有提问前钩子的 agent，每次提问前自动查一次，只在记忆真的相关时才带原话出现；
- agent 需要时自己查（MCP）：按话题召回、看原话前后文、要一个不能猜的确切答案时只凭记忆作答，
  记忆没说就答"不知道"；
- 同一个项目里几个 agent 在白板上写下领了什么、做到哪、交给谁，下一个窗口接得上，不用你转述。

在新窗口想接上前情，可以说 `/memory`、`/recall`、`/continue`，或者自然地问"之前怎么定的""下一步呢"。
这要求那个 agent 装了时间图书馆的 skill。

---

## 它不是什么

时间图书馆不是：

- 某个 AI 工具的附属插件；
- 把聊天记录压缩成摘要的工具；
- 把你的数据传到别人云上的记忆库：服务端在你自己的 NAS 上；
- skill 市场，也不是 skill 生成器；
- 替你做决定的系统；
- 记录一个人全部生活的工具。

它更像一层安静的记忆底座，放在你自己家里：原话在底下，记忆和经验在上面生长，
接入的 AI 工具按需借阅。

---

## English Short Version

**Time Library** is a continuity layer for personal AI work.

It keeps what you said with your AI agents — Claude Code, Codex, OpenClaw and
others, on every computer — on your own server (a NAS at home), and distills it
into memories that each point back to the original words, so the next window,
the next computer, or the next agent can pick up where you left off.

- **The original words are the ground truth.** Every memory quotes the words it
  rests on, checked character for character; the surrounding conversation is
  one call away. Summaries never replace them.
- **It knows whose words they are.** What you said, what an assistant relayed,
  and what you pasted in (another AI's report, an article) are kept apart.
- **Experience is not a skill.** Decisions, preferences, corrections, facts and
  lessons, with experience cards per project: things that change how the next
  answer is given, without being a callable workflow.
- **Agents connect themselves.** An agent installs the client, describes its own
  session files, checks the description, and reports it. Time Library has no
  code for any particular product.
- **It works like a library.** Original words are the source text; each project
  has a catalog; recall is a loan, and an agent can return a memory as useful,
  useless or misleading for the next borrower; every memory keeps its history.

Two things are deliberately not kept: runtime (tool calls, tool output,
reasoning) stays on the computer, and credentials are masked before anything
leaves it. Neither is ever passed off as the original words.

2026.11.23 is a rebuild: the same aim, a new architecture. See
[A rebuild](README.md#a-rebuild).
