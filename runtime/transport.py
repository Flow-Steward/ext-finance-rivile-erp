"""The only way this extension reaches Rivile ERP.

Plain REST against ``https://erp.rivile.cloud/public-api`` with JSON bodies and
the API key in ``X-SessionToken``. Requests go out through the public Flow
Steward extension SDK, which pins DNS, verifies the connected peer, refuses
redirects and enforces the timeout.

Documented limits (guide.rivile.cloud …/api/api_usage): at most 100 records per
GET, POST/PUT bodies up to 5 MB, and Rivile stops a request after 5 minutes
("Read TimeOut"). No rate limit and no idempotency key are documented, so:

* a write is sent exactly once — a 5xx, a timeout or a lost connection after it
  may have been sent leaves its outcome unknown (``timeout_unknown``) and it is
  not retried here;
* HTTP 429 is still handled defensively: a request refused with 429 was not
  executed, so it is retried after 1, 2, 4 and 8 seconds within the step budget.
"""

from __future__ import annotations

import http.client
import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request

from flowsteward_extension_sdk import PinnedPeerError, open_pinned_url, parse_retry_after

from . import errors
from .connection import BASE_URL, Connection
from .errors import ExtensionError
from .fields import field

#: Rivile answers or gives up within 5 minutes; a little more is allowed for the network.
DEFAULT_TIMEOUT_SECONDS = 310.0
#: Documented POST/PUT body limit.
MAX_REQUEST_BODY_BYTES = 5 * 1024 * 1024
MAX_RESPONSE_BYTES = 60 * 1024 * 1024
MAX_ERROR_BODY_BYTES = 1024 * 1024
CHUNK_BYTES = 64 * 1024
#: No rate limit is documented; requests of one step are still spaced a little.
MIN_INTERVAL_SECONDS = 0.05
#: 429 retries: wait 1, 2, 4, 8 seconds.
BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)
#: Shortest window still worth starting a request in.
MIN_CALL_WINDOW_SECONDS = 15.0
_USER_AGENT = "FlowSteward-RivileErp/0.1"


class DeadlineReached(Exception):
    """The invocation's time budget leaves no room for another request."""


@dataclass
class Reply:
    status: int
    #: Parsed JSON (dict, list, scalar or None for an empty body), or raw bytes
    #: for a binary download.
    data: Any
    content_type: str = ""


def encode_path(template: str, values: Mapping[str, str]) -> str:
    """Fill ``{name}`` placeholders with URL-quoted values (no ``/`` allowed)."""
    path = template
    for name, value in values.items():
        path = path.replace("{" + name + "}", quote(str(value), safe=""))
    return path


class RivileTransport:
    """Sends Rivile ERP requests for one connection."""

    def __init__(
        self,
        connection: Connection,
        *,
        opener: Callable[..., Any] = open_pinned_url,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._connection = connection
        self._opener = opener
        self._sleep = sleeper
        self.clock = clock
        self._timeout_seconds = timeout_seconds
        self._last_sent: float | None = None
        #: True once any request may have left this process.
        self.attempted = False
        #: Monotonic time after which no request may start (set by the operation).
        self.deadline: float | None = None
        self._call_timeout = timeout_seconds

    def remaining(self) -> float:
        return float("inf") if self.deadline is None else self.deadline - self.clock()

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Iterable[tuple[str, str]] = (),
        body: Any = None,
        mutating: bool,
        binary: bool = False,
    ) -> Reply:
        """Send one request; ``path`` is already filled and quoted (``/v1/...``)."""
        encoded: bytes | None = None
        if body is not None:
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) > MAX_REQUEST_BODY_BYTES:
                raise ExtensionError(
                    errors.INVALID_PAYLOAD,
                    "The request body is larger than the 5 MB Rivile ERP accepts",
                    definitely_no_external_effect=True,
                    external_effect_status="failed",
                )
        query_list = list(query)
        url = BASE_URL + path + (("?" + urlencode(query_list)) if query_list else "")
        for attempt in range(len(BACKOFF_SECONDS) + 1):
            remaining = self.remaining()
            if remaining < MIN_CALL_WINDOW_SECONDS:
                raise DeadlineReached
            self._call_timeout = min(self._timeout_seconds, remaining)
            try:
                return self._send(method, url, encoded, mutating=mutating, binary=binary)
            except ExtensionError as exc:
                if exc.code != errors.RATE_LIMITED or attempt == len(BACKOFF_SECONDS):
                    raise
                wait = BACKOFF_SECONDS[attempt]
                if exc.retry_after_seconds:
                    wait = max(wait, min(float(exc.retry_after_seconds), 30.0))
                if wait > self.remaining() - MIN_CALL_WINDOW_SECONDS:
                    raise
                self._sleep(wait)
                self._last_sent = None
        raise AssertionError("unreachable")  # pragma: no cover

    # -- one request -------------------------------------------------------

    def _send(
        self, method: str, url: str, encoded: bytes | None, *, mutating: bool, binary: bool
    ) -> Reply:
        headers = {
            "Accept": "application/octet-stream, application/json"
            if binary
            else "application/json",
            "User-Agent": _USER_AGENT,
            **self._connection.headers(),
        }
        if encoded is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(url, method=method, data=encoded, headers=headers)
        self._pace()
        status, raw, response_headers = self._open(request, mutating=mutating)
        content_type = _header(response_headers, "Content-Type").lower()
        if binary and "json" not in content_type:
            return Reply(status=status, data=raw, content_type=content_type)
        raw = _redact_bytes(raw, self._connection)
        if not raw.strip():
            return Reply(status=status, data=None, content_type=content_type)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if mutating:
                raise ExtensionError(
                    errors.TIMEOUT_UNKNOWN,
                    f"Rivile ERP accepted the request (HTTP {status}) but the answer could not "
                    "be read; check in Rivile ERP whether it was applied",
                    failure_class="provider",
                    retryable=False,
                    definitely_no_external_effect=False,
                    external_effect_status="timeout_unknown",
                    http_status=status,
                ) from exc
            raise ExtensionError(
                errors.INVALID_JSON_RESPONSE,
                "Rivile ERP answered with something that is not JSON",
                failure_class="provider",
                retryable=False,
                definitely_no_external_effect=True,
                external_effect_status="failed",
                http_status=status,
            ) from exc
        return Reply(status=status, data=data, content_type=content_type)

    def _pace(self) -> None:
        if self._last_sent is not None:
            wait = MIN_INTERVAL_SECONDS - (self.clock() - self._last_sent)
            if wait > 0:
                self._sleep(wait)
        self._last_sent = self.clock()

    def _open(self, request: Request, *, mutating: bool) -> tuple[int, bytes, Any]:
        try:
            self.attempted = True
            with self._opener(
                request,
                timeout_seconds=self._call_timeout,
                purpose="Rivile ERP API",
            ) as response:
                status = int(getattr(response, "status", 0) or getattr(response, "code", 0) or 0)
                headers = getattr(response, "headers", None)
                raw = read_bounded(response, MAX_RESPONSE_BYTES, mutating=mutating, status=status)
        except HTTPError as exc:
            raise _http_error(exc, self._connection, mutating=mutating) from exc
        except PinnedPeerError as exc:
            # Raised while resolving and pinning, before anything was sent.
            if "cannot be resolved" in str(exc):
                raise ExtensionError(
                    errors.CONNECTION_FAILED,
                    "erp.rivile.cloud could not be resolved; check the network",
                    failure_class="transient",
                    retryable=True,
                    definitely_no_external_effect=True,
                    external_effect_status="failed",
                ) from exc
            raise ExtensionError(
                errors.BLOCKED_ADDRESS,
                "erp.rivile.cloud is not reachable under the host network policy",
                definitely_no_external_effect=True,
                external_effect_status="failed",
            ) from exc
        except TimeoutError as exc:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN if mutating else errors.TIMEOUT,
                "Rivile ERP did not answer in time",
                **_transport_failure_facts(mutating=mutating),
            ) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN if mutating else errors.CONNECTION_FAILED,
                "The connection to Rivile ERP failed",
                **_transport_failure_facts(mutating=mutating),
            ) from exc
        if 300 <= status < 400:
            raise ExtensionError(
                errors.REDIRECT_REJECTED,
                "Rivile ERP redirected the request and it was not followed",
                definitely_no_external_effect=not mutating,
                external_effect_status="failed" if not mutating else "timeout_unknown",
            )
        if status >= 400:
            raise _status_error(
                status,
                _redact_bytes(raw, self._connection)[:MAX_ERROR_BODY_BYTES],
                headers,
                self._connection,
                mutating=mutating,
            )
        return status, raw, headers


def read_bounded(response: Any, limit: int, *, mutating: bool = False, status: int = 0) -> bytes:
    """Read at most ``limit`` bytes; an oversized answer to a write is an unknown outcome."""
    buffer = bytearray()
    while True:
        chunk = response.read(min(CHUNK_BYTES, limit + 1 - len(buffer)))
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN if mutating else errors.RESPONSE_TOO_LARGE,
                (
                    f"Rivile ERP accepted the request (HTTP {status}) but the answer was too "
                    "large to read; check in Rivile ERP whether it was applied"
                    if mutating
                    else "The Rivile ERP response exceeds its safe limit; narrow it with filters"
                ),
                definitely_no_external_effect=not mutating,
                external_effect_status="timeout_unknown" if mutating else "failed",
            )
    return bytes(buffer)


def _header(headers: Any, name: str) -> str:
    try:
        value = headers.get(name) if headers is not None else None
    except (AttributeError, TypeError, ValueError):
        return ""
    return str(value) if value is not None else ""


def _json_escaped(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)[1:-1]


def _redact_bytes(raw: bytes, connection: Connection) -> bytes:
    """Remove the key from a body before anything parses or truncates it."""
    for secret in connection.secret_fragments():
        for form in {secret, _json_escaped(secret)}:
            encoded = form.encode("utf-8")
            if encoded and encoded in raw:
                raw = raw.replace(encoded, b"[redacted]")
    return raw


def _http_error(exc: HTTPError, connection: Connection, *, mutating: bool) -> ExtensionError:
    try:
        # Read past the limit by more than a key's length, redact, then cut: a key
        # straddling the cut is removed whole instead of leaving a fragment.
        raw = exc.read(MAX_ERROR_BODY_BYTES + 4096)
    except Exception:  # pragma: no cover - upstream body is optional
        raw = b""
    raw = _redact_bytes(raw, connection)[:MAX_ERROR_BODY_BYTES]
    return _status_error(int(exc.code), raw, exc.headers, connection, mutating=mutating)


def parse_error_body(raw: bytes) -> tuple[str, list[dict[str, str]]]:
    """Rivile's ErrorResponse ``{code, values: {path, violations: {json path: text}}}``.

    Returns the error code and one entry per violation (``path``, ``message``,
    ``code``). Anything else in the body is reduced to safe text.
    """
    if not raw:
        return "", []
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return errors.safe_text(raw.decode("utf-8", "replace"), 300), []
    if not isinstance(body, Mapping):
        return errors.safe_text(body, 300), []
    code = errors.safe_text(field(body, "code"), 120)
    values = field(body, "values")
    entries: list[dict[str, str]] = []
    if isinstance(values, Mapping):
        violations = field(values, "violations")
        if isinstance(violations, Mapping):
            for path, text in list(violations.items())[:100]:
                entries.append(
                    {
                        "path": errors.safe_text(path, 200),
                        "message": errors.safe_text(text, 300),
                        "code": code,
                    }
                )
        elif isinstance(violations, list):
            for item in violations[:100]:
                entries.append({"path": "", "message": errors.safe_text(item, 300), "code": code})
        for key in ("message", "error", "detail"):
            if not entries and isinstance(field(values, key), str):
                entries.append(
                    {"path": "", "message": errors.safe_text(field(values, key), 300), "code": code}
                )
    for key in ("message", "error", "detail"):
        if not code and isinstance(field(body, key), str):
            code = errors.safe_text(field(body, key), 300)
    return code, entries


def _status_error(
    status: int, raw: bytes, headers: Any, connection: Connection, *, mutating: bool
) -> ExtensionError:
    code, violations = parse_error_body(_redact_bytes(raw, connection))
    detail = f": {code}" if code else ""
    retry_after = None
    try:
        retry_after = parse_retry_after(headers.get("Retry-After")) if headers is not None else None
    except (AttributeError, TypeError, ValueError):
        retry_after = None

    def failure(name: str, message: str, *, retryable: bool, no_effect: bool) -> ExtensionError:
        return ExtensionError(
            name,
            message,
            failure_class="provider",
            retryable=retryable,
            retry_after_seconds=retry_after,
            definitely_no_external_effect=no_effect,
            external_effect_status="failed" if no_effect else "timeout_unknown",
            http_status=status,
            data_errors=violations,
        )

    if status in {401, 403}:
        return failure(
            errors.AUTHENTICATION_FAILED,
            f"Rivile ERP refused the API key (wrong, expired or deactivated){detail}",
            retryable=False,
            no_effect=True,
        )
    if status == 404:
        return failure(
            errors.NOT_FOUND,
            f"Rivile ERP has no such record{detail}",
            retryable=False,
            no_effect=True,
        )
    if status == 429:
        return failure(
            errors.RATE_LIMITED,
            "Rivile ERP is rate limiting this API key",
            retryable=True,
            no_effect=True,
        )
    if status == 408 or status >= 500:
        if mutating:
            # Rivile may have saved the write before failing to answer; no
            # idempotency key exists, so it must not be sent again blindly.
            return failure(
                errors.TIMEOUT_UNKNOWN,
                "Rivile ERP did not confirm the write; check the record in Rivile ERP before "
                f"retrying{detail}",
                retryable=False,
                no_effect=False,
            )
        return failure(
            errors.TIMEOUT if status in {408, 504} else errors.UPSTREAM_FAILURE,
            f"Rivile ERP could not complete the request{detail}",
            retryable=True,
            no_effect=True,
        )
    if 400 <= status < 500:
        lines = [errors.format_data_error(item) for item in violations[:10]]
        joined = "; ".join(line for line in lines if line)
        message = f"Rivile ERP rejected the request (HTTP {status}){detail}"
        if joined:
            message = f"{message} — {joined}"
        return failure(errors.UPSTREAM_VALIDATION_FAILED, message, retryable=False, no_effect=True)
    return failure(
        errors.UPSTREAM_FAILURE,
        f"Rivile ERP answered HTTP {status}{detail}",
        retryable=False,
        no_effect=not mutating,
    )


def _transport_failure_facts(*, mutating: bool) -> dict[str, Any]:
    return {
        "failure_class": "transient",
        "retryable": not mutating,
        "definitely_no_external_effect": not mutating,
        "external_effect_status": "timeout_unknown" if mutating else "failed",
    }


__all__ = [
    "BACKOFF_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_REQUEST_BODY_BYTES",
    "MAX_RESPONSE_BYTES",
    "MIN_CALL_WINDOW_SECONDS",
    "DeadlineReached",
    "Reply",
    "RivileTransport",
    "encode_path",
    "parse_error_body",
    "read_bounded",
]
