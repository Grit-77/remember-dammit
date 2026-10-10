"""Structured errors shared by the core and its transports."""


class VaultError(Exception):
    """A stable machine-readable failure; detail must not expose secrets."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
