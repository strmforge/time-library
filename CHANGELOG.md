# Changelog

## [2026.5.27] - 2026-05-27

- Added Codex local record support. Yifanchen can discover local Codex sessions, preserve them as raw memory, and organize useful experience from them without reading login, token, or auth files.
- Extended the shared local memory base for OpenClaw, Hermes, and Codex while keeping each platform and conversation window separate.
- Added incremental capture for growing session files, so new conversation records are processed from saved offsets instead of rereading from the beginning.
- Added direct raw evidence lookup by byte offset, with a resumable segmented fallback for older records.
- Updated Hermes memory provider defaults to read the shared local memory base in read-only mode.
- Added tests for Codex capture, Zhiyi extraction, shared raw access, segmented resume, and offset lookup.

## [2026.5.26] - 2026-05-26

- Enabled the local one-click update flow: check, download, validate, back up app files, apply the new version, and restart local services.
- Preserved local memory, raw records, Zhiyi experience, configuration, logs, backups, and virtualenv state during update.
- Fixed the update history API so the local page can read past update records.
- Updated README and wiki guidance for install, repair install, and one-click update.

## [2026.5.25] - 2026-05-25

- First public release of Yifanchen.
- Added one-command installers for macOS, Linux, WSL, and Windows.
- Added the local memory center page for platform status, model settings, and generated experience.
- Kept the public repository focused on the installable product.
