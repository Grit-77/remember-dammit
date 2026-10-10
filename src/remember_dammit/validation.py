"""Shared portable identifiers for the store, retrieval and client proposals."""

import re

from .errors import VaultError

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def validate_identifier(value, label="ID") -> str:
    if (not isinstance(value, str) or not _IDENTIFIER.fullmatch(value)
            or value.endswith(".") or value.split(".")[0].upper() in _RESERVED):
        raise VaultError("invalid_input", f"{label} must be a portable identifier.")
    return value
