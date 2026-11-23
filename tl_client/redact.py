"""Redaction that runs before anything leaves the computer.

Credentials are always masked. Personal identifiers (email, phone, ID number)
are masked by default and can be switched off per category in the client
config; credentials cannot be switched off.
"""

from __future__ import annotations

import re
from typing import Mapping

MASK_KEY = "[已打码:密钥]"
MASK_PRIVATE_KEY = "[已打码:私钥]"
MASK_PASSWORD = "[已打码:口令]"
MASK_EMAIL = "[已打码:邮箱]"
MASK_PHONE = "[已打码:手机号]"
MASK_ID = "[已打码:证件号]"

DEFAULT_CATEGORIES = {"email": True, "phone": True, "id_number": True}

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.DOTALL
)

# Vendor key shapes: specific prefixes followed by a long opaque tail.
_KEY_SHAPES = re.compile(
    r"""(?x)
    (?<![A-Za-z0-9_-])
    (?:
        sk-[A-Za-z0-9_-]{20,}                 # OpenAI / Anthropic style (sk-, sk-proj-, sk-ant-)
      | gh[pousr]_[A-Za-z0-9]{30,}            # GitHub tokens
      | github_pat_[A-Za-z0-9_]{30,}
      | glpat-[A-Za-z0-9_-]{20,}              # GitLab
      | xox[abprs]-[A-Za-z0-9-]{10,}          # Slack
      | AKIA[0-9A-Z]{16}                      # AWS access key id
      | AIza[0-9A-Za-z_-]{35}                 # Google API key
      | hf_[A-Za-z0-9]{30,}                   # Hugging Face
      | tl[pca]_[A-Za-z0-9_-]{20,}            # Time Library's own tokens
      | eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}   # JWT
    )
    (?![A-Za-z0-9_-])
    """
)

_BEARER = re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]{20,}")
_URL_PASSWORD = re.compile(r"(?P<head>[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@]+:)(?P<secret>[^\s/@]{3,})(?=@)")

# name = value / name: value, where the name says it is a secret. The value must
# look like a credential (a digit in 8+ characters, or 16+ characters), so that
# ordinary prose such as "token: unknown" is left alone.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?P<name>\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|access[_-]?token|auth[_-]?token|token)\b
       |密码|口令|密钥)
    (?P<sep>["']?\s*[:=：]\s*["']?)
    (?P<value>[A-Za-z0-9!@\#$%^&*()_+\-=.~/]{8,})
    """
)

_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![A-Za-z0-9-])")
_CN_MOBILE = re.compile(r"(?<![0-9A-Za-z.])(?:\+?86[- ]?)?1[3-9]\d{9}(?![0-9A-Za-z])")
_CN_ID = re.compile(r"(?<![0-9A-Za-z])[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?![0-9A-Za-z])")


def _looks_like_credential(value: str) -> bool:
    return len(value) >= 16 or any(char.isdigit() for char in value)


def _mask_assignment(match: "re.Match[str]") -> str:
    value = match.group("value")
    if value.startswith("[已打码") or not _looks_like_credential(value):
        return match.group(0)
    return f"{match.group('name')}{match.group('sep')}{MASK_PASSWORD}"


def redact(text: str, categories: Mapping[str, bool] | None = None) -> str:
    enabled = dict(DEFAULT_CATEGORIES)
    if categories:
        enabled.update({key: bool(value) for key, value in categories.items() if key in DEFAULT_CATEGORIES})

    text = _PRIVATE_KEY.sub(MASK_PRIVATE_KEY, text)
    text = _KEY_SHAPES.sub(MASK_KEY, text)
    text = _BEARER.sub(lambda match: f"{match.group(1)} {MASK_KEY}", text)
    text = _URL_PASSWORD.sub(lambda match: f"{match.group('head')}{MASK_PASSWORD}", text)
    text = _ASSIGNMENT.sub(_mask_assignment, text)
    if enabled["id_number"]:
        text = _CN_ID.sub(MASK_ID, text)
    if enabled["phone"]:
        text = _CN_MOBILE.sub(MASK_PHONE, text)
    if enabled["email"]:
        text = _EMAIL.sub(MASK_EMAIL, text)
    return text
