# Memory Layout

Starting with the 2026.6.1 line, new local records use a computer-first layout:

```text
memory/<computer-name>/<source-tool>/<app-format>/<window-or-project>/<session>.jsonl
```

This makes multi-device setups easier to read. When records from several computers are gathered later, the first question is "which computer did this come from?", then "which tool produced it?"

Older source-first layouts remain readable, but new installs and new records should follow the new contract.

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
