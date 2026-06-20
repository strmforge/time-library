# Release History

The current published release has its own release note in the repository root.

Older highlights are kept in:

- [UPDATE_HISTORY.md](../../UPDATE_HISTORY.md)
- [CHANGELOG.md](../../CHANGELOG.md)

## Current Published Release

See:

- [RELEASE_NOTES_2026.6.20.2.md](../../RELEASE_NOTES_2026.6.20.2.md)

## Maintainer Release Check

Before publishing a new release, run the clean release gate from the repository:

```bash
python3 tools/release_gate.py --source head
```

The gate checks a clean archive of `HEAD`, not the local runtime directory. It
creates an isolated Python environment, checks installer syntax, scans public
install wording, compiles Python files, and runs the test suite.

## Why History Is Split

The README should stay short enough for new users to understand the product quickly.

Release notes describe the current release. Update history keeps older feature highlights. Changelog keeps lower-level changes.

## 中文

最新版保留独立发布说明。

旧版本亮点统一进入 `UPDATE_HISTORY.md`，更底层的工程变更进入 `CHANGELOG.md`。这样首页不会越写越长。

发布新版本前，维护者应运行：

```bash
python3 tools/release_gate.py --source head
```

这个检查使用干净的 `HEAD` 归档，不依赖本机运行目录或未提交文件。
