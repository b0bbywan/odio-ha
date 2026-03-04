"""Exceptions for the Odio Remote integration.

These exceptions have no Home Assistant dependency so they can be raised
by the API client layer and re-mapped to HA-specific exceptions at the
integration boundary (e.g. api_command decorator).
"""


class OdioError(Exception):
    """Base for all Odio errors."""


class OdioConnectionError(OdioError):
    """Network/connection failure when reaching the Odio API."""


class OdioApiError(OdioError):
    """The Odio API responded with an error (4xx, 5xx) or an invalid payload."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class OdioTimeoutError(OdioError):
    """Timeout while waiting for the Odio API."""
