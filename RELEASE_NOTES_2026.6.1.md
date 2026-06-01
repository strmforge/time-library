# Memcore Cloud 2026.6.1

Memcore Cloud 2026.6.1 is the first release that presents the project with its English product name by default. **忆凡尘 / Yifanchen** remains the Chinese name and codename.

This release is about making local AI memory easier to explain and easier to try. Paste one prompt into a local agent, let it install the skill and MCP connection, then run a safe check before any real memory is recalled.

## English

### Highlights

- **Memcore Cloud is now the English-first name**: Yifanchen stays as the Chinese name and codename, while the repository becomes easier to search and explain in English.
- **Your agent can install it for you**: paste the install prompt into Codex, Claude Code CLI, OpenClaw, Hermes, or another local agent. It can add the skill, connect MCP where supported, and finish with a safe capability check.
- **It helps AI tools stop starting from zero**: Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and newer local agents can connect to the same local memory base.
- **It keeps sources checkable**: remembered items can point back to source refs and raw excerpts instead of becoming a loose summary nobody can verify.
- **It shows what is already on this machine**: the local page can show which AI tools are present, which ones can run a safe capability check, and which ones still need a permission step.
- **Claude stays separated by surface**: Claude Desktop, Claude Code CLI, official-login records, and relay records keep their attribution boundaries.
- **New records are easier to browse later**: records are grouped by computer first, then by the AI tool that produced them.
- **The first check is safe**: capability check confirms the path is alive without recalling real memory or returning raw excerpts.

### Boundaries

- The local page is read-only by default.
- Installing a skill is an intent signal, not permission to read chat bodies.
- Capability check does not recall real memory and does not return raw excerpts.
- Deeper local scans can be heavier on Windows; the default page stays fast, and broader checks should be treated as explicit/background work.

## 中文

### 主要更新

- **英文首屏统一为 Memcore Cloud**：忆凡尘 / Yifanchen 保留为中文名和 codename，英文用户更容易搜到和理解。
- **可以把安装交给本机 agent**：把提示发给 Codex、Claude Code CLI、OpenClaw、Hermes 或其他本机 agent，它会帮你安装 Skill、接 MCP，并只做安全能力检查。
- **让 AI 工具不用每次从零开始**：Claude Desktop、Claude Code CLI、Codex、OpenClaw、Hermes、Cursor 类工具和新的本机 agent 可以接到同一个本机记忆底座。
- **记忆能回到来源**：召回结果可以带来源线索和原文摘录，不只是几句无法核对的摘要。
- **能看见本机有哪些 AI 工具**：本地页面会告诉你看到了哪些工具、哪些可以先做安全能力检查、哪些还差一次授权接入。
- **Claude 各入口分开看待**：Claude Desktop、Claude Code CLI、官方登录记录和中转记录保留归属边界。
- **新记录以后更好翻**：新增记录先按电脑分组，再按产生记录的 AI 工具分组。
- **第一步检查是安全的**：capability check 只确认链路可用，不召回真实记忆，也不返回原文。

### 边界

- 本机发现默认只读。
- 安装 Skill 只是接入意图信号，不等于授权读取聊天正文。
- capability check 不召回真实记忆，不返回原文摘录。
- Windows 上更深的本机扫描可能较重；默认面板保持快速，深扫应作为显式或后台任务处理。
