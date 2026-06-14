# Local Tool Recognition

Memcore Cloud tries to make new local AI tools less annoying to connect.

After install, it looks for local signals such as:

- installed apps and app data folders;
- package-manager or CLI traces;
- workspace files and project markers;
- existing local integration entries;
- known local storage patterns.

When a supported local entry is found, Memcore Cloud can connect it
automatically. When a conversation source is found, Memcore Cloud still requires
a verified local format before treating it as complete memory.

## Optional Model Help

Memcore Cloud uses one visible model setting: **Zhiyi model**.

If you configure that model, Memcore Cloud can reuse it to identify unfamiliar
local AI tools from metadata. If no model is configured, local rules still work.

Default scans stay metadata-only. They do not send chat bodies or raw excerpts
to a model just to identify a tool.

## Why This Matters

New AI tools appear quickly. Waiting for every tool to be hand-added makes the
product feel stale. Metadata-first recognition gives Memcore Cloud a way to say:

- "this looks like a local AI coding tool";
- "this tool has a usable local integration entry";
- "this tool has local records, but the format still needs verification";
- "this tool is only discovered for now."

That is more useful than hiding unknown tools, and safer than pretending every
unknown folder is already memory.

## 中文

忆凡尘安装后会尽量自动识别本机 AI 工具，少让用户自己填一堆东西。

它会看：

- 已安装应用和应用数据目录；
- 包管理器或 CLI 痕迹；
- 工作区文件和项目标记；
- 已有本机接入入口；
- 已知的本地存储形态。

如果发现可用的本机入口，可以自动接入。如果发现了可能的对话来源，
仍然要先验证本地格式，才能把它当成完整记忆来源。

用户界面只保留一个模型设置：**知意模型**。

如果你配置了知意模型，忆凡尘可以复用它来识别陌生的本机 AI 工具。如果没有配置，
本地规则照样工作。默认扫描只看本机元数据，不会为了识别软件就把聊天正文或原始摘录
发给模型。

这样做的目的很简单：新 AI 工具出现太快，不能每个都等人工适配；但也不能看到一个
文件夹就假装已经保存了完整对话。
