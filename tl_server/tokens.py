"""Token minting and hashing.

Tokens are high-entropy random strings, so a plain SHA-256 is enough: the server
stores only the hash and never the token itself.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

PAIRING_PREFIX = "tlp_"  # one-time, pairs a new computer
DEVICE_PREFIX = "tlc_"  # long-lived, held by a paired client
ADMIN_PREFIX = "tla_"  # held by whoever administers the server
SESSION_PREFIX = "tls_"  # a signed-in browser


def mint(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(24)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def matches(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(digest(token), token_hash)
