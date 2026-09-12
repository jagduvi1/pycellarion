"""pycellarion — async client for the Cellarion wine-cellar API."""

from .client import MAX_BODY_BYTES, CellarionClient, JsonDict
from .exceptions import (
    CellarionApiError,
    CellarionAuthError,
    CellarionPushForbidden,
    CellarionPushNotSupported,
    CellarionScopeError,
    CellarionTokensNotSupported,
)

__version__ = "0.1.0"

__all__ = [
    "MAX_BODY_BYTES",
    "CellarionApiError",
    "CellarionAuthError",
    "CellarionClient",
    "CellarionPushForbidden",
    "CellarionPushNotSupported",
    "CellarionScopeError",
    "CellarionTokensNotSupported",
    "JsonDict",
    "__version__",
]
