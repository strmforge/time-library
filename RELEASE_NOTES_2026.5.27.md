# Yifanchen 2026.5.27

This release brings Codex into Yifanchen's local memory base.

## What's New

- Codex local sessions can now be discovered and preserved as raw memory.
- Codex records can be organized into Zhiyi experience with traceable source references.
- Platform records are kept as originally recorded, without redaction, rewriting, or hash-only replacement.
- OpenClaw, Hermes, and Codex now share the same local raw memory base while keeping each platform and conversation window separate.
- Growing session files are captured incrementally from saved offsets.
- Raw evidence lookup can jump directly to byte offsets, with a resumable segmented fallback for older records.
- Hermes reads the shared local memory base in read-only mode by default.

## Update

Open `http://127.0.0.1:9850`, go to Settings & Update, then use Check for updates and One-click update.

If the local page cannot open, rerun the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows:

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```
