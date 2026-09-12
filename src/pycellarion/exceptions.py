"""Exceptions raised by the Cellarion client."""

from __future__ import annotations


class CellarionApiError(Exception):
    """Base exception for Cellarion API errors."""


class CellarionAuthError(CellarionApiError):
    """Authentication failed."""


class CellarionPushNotSupported(CellarionApiError):
    """The server does not offer the push event stream."""


class CellarionPushForbidden(CellarionApiError):
    """The credential lacks the scope required for the push stream."""


class CellarionScopeError(CellarionApiError):
    """The API token is valid but lacks a required scope."""


class CellarionTokensNotSupported(CellarionApiError):
    """The server does not support personal API tokens."""
