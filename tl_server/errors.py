"""Errors that map directly onto HTTP responses."""

from __future__ import annotations


class ApiError(Exception):
    """A refusal the client can act on: HTTP status + stable machine code."""

    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code
