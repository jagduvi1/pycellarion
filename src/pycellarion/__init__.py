"""pycellarion — async client for the Cellarion wine-cellar API."""

from .client import (
    IMAGE_PATH_RE,
    MAX_BODY_BYTES,
    MAX_IMAGE_BYTES,
    MAX_INVENTORY_BYTES,
    CellarionClient,
    InventoryResult,
    JsonDict,
)
from .exceptions import (
    CellarionApiError,
    CellarionAuthError,
    CellarionInventoryNotSupported,
    CellarionPushForbidden,
    CellarionPushNotSupported,
    CellarionScopeError,
    CellarionTokensNotSupported,
)

__version__ = "0.2.0"

__all__ = [
    "IMAGE_PATH_RE",
    "MAX_BODY_BYTES",
    "MAX_IMAGE_BYTES",
    "MAX_INVENTORY_BYTES",
    "CellarionApiError",
    "CellarionAuthError",
    "CellarionClient",
    "CellarionInventoryNotSupported",
    "CellarionPushForbidden",
    "CellarionPushNotSupported",
    "CellarionScopeError",
    "CellarionTokensNotSupported",
    "InventoryResult",
    "JsonDict",
    "__version__",
]
