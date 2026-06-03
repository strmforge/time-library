# Memory Layout

Starting with the 2026.6.1 line, new local records use a computer-first layout:

```text
memory/<computer-name>/<source-tool>/<app-format>/<window-or-project>/<session>.jsonl
```

This makes multi-device setups easier to read. When records from several computers are gathered later, the first question is "which computer did this come from?", then "which tool produced it?"

Older source-first layouts remain readable, but new installs and new records should follow the new contract.

## Why The Computer Comes First

The first partition is the computer because future multi-machine setups may gather
records from several machines. In that shape, the first question is not "how
many machines installed Cursor or Claude?" but "which computer produced this
record?"

After the computer, records are grouped by the source tool and that tool's
native artifact format:

```text
memory/<computer-name>/<source-system>/<native-artifact-format>/...
```

Examples:

```text
memory/Office-PC/codex/codex-session-records/...
memory/Laptop/openclaw/openclaw-workspace-records/...
memory/Mac-mini/claude_desktop/claude-desktop-records/...
```

Use this layout for new writes starting with the 2026.6.1 line. Legacy layouts
are read compatibility only.

## Layers

Memcore Cloud keeps several layers distinct:

- **raw records**: original source-backed records;
- **Zhiyi**: preference, intent, correction, and background experience;
- **Xingce**: work experience, validation paths, toolbooks, and next-step patterns;
- **receipts**: what was consumed, whether recall ran, and whether anything was written.

Summaries can help navigation, but raw records remain the highest evidence.

## 中文

从 2026.6.1 线开始，新增记录默认先按电脑分组，再按产生记录的 AI 工具分组：

```text
memory/<计算机名>/<软件名>/<软件自己的保存格式>/<窗口或项目>/<会话>.jsonl
```

原因很简单：如果以后有中央汇集模式，先要知道是哪台机器，再看这台机器上的哪个软件。

旧目录继续可读，但新装和新增记录走新契约。

计算机名放在第一层，是为了未来多机器汇总时先按机器分组：先看是哪台机器，再看这台机器上的哪个软件、哪种原生保存格式。

新写入默认形状：

```text
memory/<计算机名>/<软件名>/<软件自己的保存格式>/...
```

旧契约继续兼容读取，但 2026.6.1 线之后的新装和新增记录不再新增旧布局。
