"""Project-scoped Rivile ERP connection: one API key of one Rivile ERP company.

A connection is built from what the host hydrates for one invocation and is
discarded when that invocation ends. The API key lives in a private field of a
frozen dataclass whose ``repr`` never shows it, and it is never placed in a
result, a log line or an exception message.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import errors
from .errors import ExtensionError

CONNECTION_TYPE_ID = "rivile_erp"
#: The Rivile ERP Public API base (OpenAPI ``servers``). Fixed here and never taken
#: from configuration or workflow input.
BASE_URL = "https://erp.rivile.cloud/public-api"
ENDPOINT_HOST = "erp.rivile.cloud"
#: Every request carries the key in this header (guide: "API naudojimo būdai").
KEY_HEADER = "X-SessionToken"

CONFIG_FIELDS: frozenset[str] = frozenset({"label", "language"})
SECRET_FIELDS: frozenset[str] = frozenset({"api_key"})
LANGUAGES: frozenset[str] = frozenset({"lt", "en"})

MIN_KEY_LENGTH = 8
MAX_KEY_LENGTH = 1024
#: Printable, non-space ASCII. Anything else could inject a header.
_KEY_RE = re.compile(r"^[\x21-\x7e]+$")


@dataclass(frozen=True)
class Connection:
    """One validated Rivile ERP API key and the language Rivile answers in."""

    connection_id: str
    language: str
    _api_key: str = field(repr=False)

    def secret_fragments(self) -> tuple[str, ...]:
        """The key, for redacting text Rivile might echo back."""
        return (self._api_key,)

    def headers(self) -> dict[str, str]:
        return {KEY_HEADER: self._api_key, "Accept-Language": self.language}

    def __repr__(self) -> str:  # pragma: no cover - defensive
        return f"Connection(connection_id={self.connection_id!r})"

    __str__ = __repr__


def _invalid(message: str) -> ExtensionError:
    return ExtensionError(
        errors.INVALID_CONNECTION,
        message,
        definitely_no_external_effect=True,
        external_effect_status="failed",
    )


def _api_key(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise _invalid("Add the Rivile ERP API key to this connection")
    if len(text) < MIN_KEY_LENGTH or len(text) > MAX_KEY_LENGTH or _KEY_RE.fullmatch(text) is None:
        raise _invalid("The Rivile ERP API key is not usable")
    return text


def _language(value: Any) -> str:
    if value in (None, ""):
        return "en"
    if isinstance(value, str) and value.strip().lower() in LANGUAGES:
        return value.strip().lower()
    raise _invalid("language must be lt or en")


def connection_from_payload(payload: Mapping[str, Any], *, connection_ref: str) -> Connection:
    """Validate the selected project connection before any outbound request.

    Connection material is read only from ``action.target.connection``, and the
    operation's ``connection_ref`` must name that same connection.
    """
    action = payload.get("action")
    target = action.get("target") if isinstance(action, Mapping) else None
    connection = target.get("connection") if isinstance(target, Mapping) else None
    if not isinstance(connection, Mapping):
        raise _invalid("The selected connection is unavailable")
    connection_id = str(connection.get("connection_id") or "")
    if not connection_id or (connection_ref and connection_id != connection_ref):
        raise _invalid("The selected connection does not match connection_ref")
    connection_type = str(
        connection.get("connection_type_id") or connection.get("connection_type") or ""
    )
    if connection_type and connection_type != CONNECTION_TYPE_ID:
        raise _invalid("The selected connection is not supported")
    config = connection.get("config")
    config = config if isinstance(config, Mapping) else {}
    secrets = connection.get("secrets")
    secrets = secrets if isinstance(secrets, Mapping) else {}
    if set(secrets) - SECRET_FIELDS:
        raise _invalid("The connection carries unsupported secrets")
    return Connection(
        connection_id=connection_id,
        language=_language(config.get("language")),
        _api_key=_api_key(secrets.get("api_key")),
    )


__all__ = [
    "BASE_URL",
    "CONFIG_FIELDS",
    "CONNECTION_TYPE_ID",
    "ENDPOINT_HOST",
    "KEY_HEADER",
    "LANGUAGES",
    "SECRET_FIELDS",
    "Connection",
    "connection_from_payload",
]
