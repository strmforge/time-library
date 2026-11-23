"""Time Library server (server/client redesign).

One authoritative server holds storage, distillation and recall. Thin clients on
each computer read agent sessions, strip runtime noise, redact, and upload.
"""

API_VERSION = "v1"
DEFAULT_PORT = 9850
