"""Time Library client (server/client redesign).

The client only does what must happen on the computer itself: read agent
session files, drop everything that is not dialogue, redact, and upload. It
keeps no copy of the dialogue: only how far it has read.
"""

CLIENT_VERSION = "2026.11.23.22"
