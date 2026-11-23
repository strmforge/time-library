"""Time Library server (server/client redesign).

One authoritative server holds storage, distillation and recall. Thin clients on
each computer read agent sessions, strip runtime noise, redact, and upload.
"""

API_VERSION = "v1"
SERVER_VERSION = "2026.11.23.2"  # a release: also its tag (v<version>) and its image tag
DEFAULT_PORT = 9850
