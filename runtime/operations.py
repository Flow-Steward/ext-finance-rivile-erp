"""Run one workflow operation against the Rivile ERP Public API."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

from flowsteward_extension_sdk import write_artifact_stream

from . import budget, catalog, errors, friendly
from .connection import Connection, connection_from_payload
from .errors import ExtensionError, error_response
from .fields import field
from .models import Endpoint
from .transport import DeadlineReached, Reply, RivileTransport, encode_path

PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 10
MAX_PAGES = 100
EXPORT_MAX_PAGES = 2000
MAX_FILTERS = 20
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_EXPORT_BYTES = 200 * 1024 * 1024
MAX_QUERY_TEXT = 200
#: The entrypoint is given 600 s (extension.yaml). Every request must start early
#: enough to finish inside it; an operation that saves a file keeps the artifact
#: write's own timeout in reserve, so it can always save what it read.
STEP_TIMEOUT_SECONDS = 600.0
STEP_MARGIN_SECONDS = 30.0
ARTIFACT_WRITE_TIMEOUT_SECONDS = 180.0

#: Must equal the content types granted in contracts/artifact_policies.yaml: the
#: SDK refuses an upload whose type differs from the signed grant.
DOWNLOAD_CONTENT_TYPE = "application/octet-stream"
EXPORT_CONTENT_TYPE = "application/x-ndjson"
EXPORT_FILENAME = "rivile-erp-export.jsonl"

#: The OpenAPI filter enum without GROUP, whose value is not described.
FILTER_OPERATIONS: frozenset[str] = frozenset(
    {
        "EQUAL",
        "NOT_EQUAL",
        "CONTAINS",
        "NOT_CONTAINS",
        "STARTS_WITH",
        "ENDS_WITH",
        "GREATER_THAN",
        "GREATER_THAN_OR_EQUAL",
        "LESS_THAN",
        "LESS_THAN_OR_EQUAL",
    }
)
CALL_METHODS: frozenset[str] = frozenset({"GET", "POST", "PATCH", "PUT", "DELETE"})

_ALLOWED_ACTION_KEYS = frozenset(
    {"action_id", "operation_id", "page_id", "component_id", "context", "input", "target"}
)
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
#: Non-UUID path values (none in the 0.1 document): no dots, so no "." or ".." segment.
_PATH_VALUE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CALL_PATH_RE = re.compile(r"^/v1/[A-Za-z0-9/_.-]{1,200}$")
_DIGITS = re.compile(r"[0-9]{1,9}")
_FIELD_RE = re.compile(r"^\w{1,64}$")
#: Fields kept when a write's echo is shrunk to fit the step output.
_KEY_FIELDS = re.compile(r"(^id$|Id$|^code$|Code$|^documentNo$|^name$)")

#: Operations that save a workflow file after reading.
_FILE_WRITING_OPS = frozenset(
    {
        catalog.EXPORT_LIST,
        "download_document_file",
        *(e.operation_id for e in catalog.ENDPOINTS_BY_OPERATION.values() if e.binary),
    }
)

TransportFactory = Callable[[Connection], RivileTransport]
ArtifactWriter = Callable[..., Mapping[str, Any]]


def _invalid(message: str) -> ExtensionError:
    return ExtensionError(
        errors.INVALID_PAYLOAD,
        message,
        definitely_no_external_effect=True,
        external_effect_status="failed",
    )


# ---------------------------------------------------------------------------
# Entry point


def handle_runtime(
    payload: Mapping[str, Any],
    *,
    transport_factory: TransportFactory = RivileTransport,
    artifact_writer: ArtifactWriter = write_artifact_stream,
) -> dict[str, Any]:
    """Dispatch one invocation through the closed registry."""
    transport: RivileTransport | None = None
    try:
        operation_id, raw_input = _envelope(payload)
        if operation_id not in catalog.OPERATION_IDS:
            raise ExtensionError(
                errors.UNSUPPORTED_OPERATION,
                "That operation is not part of this extension",
                definitely_no_external_effect=True,
                external_effect_status="failed",
            )
        operation_input = _as_input(raw_input)
        write = operation_id in catalog.WRITE_OPERATION_IDS
        if write and _test_mode(payload):
            # The host suppresses test-mode writes before spawning the extension;
            # this is the backstop. Validated first, then nothing is sent.
            _validate_only(operation_id, operation_input)
            return _ok(_neutral_result(operation_id))
        connection = connection_from_payload(
            payload, connection_ref=_text(operation_input.get("connection_ref"))
        )
        transport = transport_factory(connection)
        reserve = ARTIFACT_WRITE_TIMEOUT_SECONDS if operation_id in _FILE_WRITING_OPS else 0.0
        transport.deadline = (
            transport.clock() + STEP_TIMEOUT_SECONDS - STEP_MARGIN_SECONDS - reserve
        )
        context = _Context(
            payload=payload,
            operation_input=operation_input,
            transport=transport,
            artifact_writer=artifact_writer,
        )
        if operation_id == catalog.TEST_CONNECTION:
            return _ok(_test_connection(context))
        if operation_id == catalog.CALL_ENDPOINT:
            return _ok(_call_endpoint(context))
        if operation_id == catalog.EXPORT_LIST:
            return _ok(_export_list(context))
        if operation_id in catalog.FRIENDLY_IDS:
            return _ok(_run_friendly(context, operation_id))
        endpoint = catalog.ENDPOINTS_BY_OPERATION[operation_id]
        return _ok(_run_endpoint(context, endpoint))
    except DeadlineReached:
        return error_response(
            errors.TIMEOUT,
            "The step ran out of time before Rivile ERP could be called",
            retry_facts={"definitely_no_external_effect": True, "external_effect_status": "failed"},
        )
    except ExtensionError as exc:
        _mark_unsent(exc, transport)
        return error_response(
            exc.code, exc.message, retry_facts=exc.retry_facts(), data_errors=exc.data_errors
        )
    except Exception:
        unsent = transport is None or not transport.attempted
        response = error_response(errors.INTERNAL_ERROR, "The operation could not be completed")
        if unsent:
            response["definitely_no_external_effect"] = True
            response["external_effect_status"] = "failed"
        return response


def _mark_unsent(exc: ExtensionError, transport: RivileTransport | None) -> None:
    """A failure before any request left the process cannot have had an effect."""
    if transport is not None and transport.attempted:
        return
    if exc.definitely_no_external_effect is None:
        exc.definitely_no_external_effect = True
    if exc.definitely_no_external_effect and exc.external_effect_status is None:
        exc.external_effect_status = "failed"


class _Context:
    def __init__(
        self,
        *,
        payload: Mapping[str, Any],
        operation_input: Mapping[str, Any],
        transport: RivileTransport,
        artifact_writer: ArtifactWriter,
    ) -> None:
        self.payload = payload
        self.operation_input = operation_input
        self.transport = transport
        self.artifact_writer = artifact_writer

    def clock(self) -> float:
        clock = getattr(self.transport, "clock", None)
        return float(clock()) if callable(clock) else time.monotonic()

    def call(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, str]] | None = None,
        body: Any = None,
        mutating: bool,
        binary: bool = False,
    ) -> tuple[Reply, int]:
        """One request and its duration in milliseconds."""
        started = self.clock()
        reply = self.transport.request(
            method, path, query=query or [], body=body, mutating=mutating, binary=binary
        )
        return reply, int((self.clock() - started) * 1000)


# ---------------------------------------------------------------------------
# Envelope and inputs


def _envelope(payload: Mapping[str, Any]) -> tuple[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("mode") != "action":
        raise _invalid("Request mode must be action")
    action = payload.get("action")
    if not isinstance(action, Mapping) or set(action) - _ALLOWED_ACTION_KEYS:
        raise _invalid("The action envelope is invalid")
    operation_id = action.get("action_id") or action.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id.strip():
        raise _invalid("An operation id is required")
    return operation_id.strip(), action.get("input")


def _as_input(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise _invalid("The operation input must be an object")
    return {str(k): v for k, v in raw.items() if v is not None}


def _test_mode(payload: Mapping[str, Any]) -> bool:
    context = payload.get("runtime_context")
    if not isinstance(context, Mapping):
        return False
    value = context.get("test_mode", False)
    if not isinstance(value, bool):
        raise _invalid("runtime_context.test_mode must be boolean")
    return value


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _whole(name: str, value: Any, *, default: int, minimum: int, maximum: int) -> int:
    """A whole number in range; ASCII digit strings are accepted."""
    if value is None:
        return default
    if isinstance(value, str) and _DIGITS.fullmatch(value.strip()):
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise _invalid(f"{name} must be a whole number from {minimum} to {maximum}")
    return value


def _bool(name: str, value: Any, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise _invalid(f"{name} must be true or false")
    return value


def _scalar_text(name: str, value: Any) -> str:
    """A query value as Rivile expects it in the URL."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    if isinstance(value, str) and len(value) <= MAX_QUERY_TEXT and value.isprintable():
        return value
    raise _invalid(f"{name} must be short text, a number or true/false")


def _filter_value(name: str, value: Any) -> Any:
    if isinstance(value, bool) or (isinstance(value, int) and abs(value) < 10**15):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, str) and len(value) <= MAX_QUERY_TEXT and value.isprintable():
        return value
    raise _invalid(f"{name} must be short printable text, a number or true/false")


def build_filter(raw: Any, allowed: tuple[str, ...] | None) -> str:
    """Typed filter conditions -> Rivile's JSON filter list, only on documented fields.

    ``allowed`` is the field list Rivile documents for the list; ``None`` admits
    any well-formed field name (only for paths outside the registry).
    """
    if raw is None:
        return ""
    if not isinstance(raw, list) or len(raw) > MAX_FILTERS:
        raise _invalid(f"filters must be a list of at most {MAX_FILTERS} conditions")
    lowered = {f.lower(): f for f in (allowed or ())}
    conditions = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or set(item) - {"field", "operation", "value"}:
            raise _invalid(f"filters[{index}] must have field, operation and value")
        field = _text(item.get("field"))
        if allowed is not None:
            field = lowered.get(field.lower(), "")
            if not field:
                raise _invalid(
                    f"filters[{index}].field must be one of: {', '.join(allowed) or 'none'}"
                )
        elif not _FIELD_RE.fullmatch(field):
            raise _invalid(f"filters[{index}].field is not a field name")
        operation = _text(item.get("operation")).upper()
        if operation not in FILTER_OPERATIONS:
            raise _invalid(f"filters[{index}].operation is not a supported operation")
        if "value" not in item:
            raise _invalid(f"filters[{index}].value is required")
        value = _filter_value(f"filters[{index}].value", item.get("value"))
        conditions.append({"operation": operation, "name": field, "value": value})
    if not conditions:
        return ""
    return json.dumps(conditions, ensure_ascii=False, separators=(",", ":"))


def path_value(name: str, value: Any, fmt: str = "uuid") -> str:
    """A path id: a UUID when the document says so (every 0.1 path id), else a plain code."""
    text = (
        str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    )
    pattern = _UUID_RE if fmt == "uuid" else _PATH_VALUE_RE
    if not text or not pattern.fullmatch(text):
        what = "a Rivile ERP id (UUID)" if fmt == "uuid" else "a Rivile ERP code"
        raise _invalid(f"{name} must be {what}")
    return text


def _allowed_inputs(endpoint: Endpoint) -> set[str]:
    names = {"connection_ref"}
    names |= {name for name, _wire, _fmt in endpoint.path_params}
    names |= {name for name, _wire, _kind, _required in endpoint.query_params}
    if endpoint.has_body:
        names.add("body")
    if endpoint.paged:
        names |= {"filters", "page", "size", "fetch_all_pages", "max_pages"}
    return names


def endpoint_request(
    endpoint: Endpoint, operation_input: Mapping[str, Any]
) -> tuple[str, list[tuple[str, str]], Any]:
    """Typed inputs -> the filled path, the query list and the JSON body."""
    unknown = set(operation_input) - _allowed_inputs(endpoint)
    if unknown:
        raise _invalid(f"Unknown input: {', '.join(sorted(unknown))}")
    values: dict[str, str] = {}
    for name, wire, fmt in endpoint.path_params:
        if operation_input.get(name) in (None, ""):
            raise _invalid(f"Required input missing: {name}")
        values[wire] = path_value(name, operation_input[name], fmt)
    path = encode_path(endpoint.path, values)
    query: list[tuple[str, str]] = []
    for name, wire, _kind, required in endpoint.query_params:
        if name in operation_input and operation_input[name] != "":
            query.append((wire, _scalar_text(name, operation_input[name])))
        elif required:
            raise _invalid(f"Required input missing: {name}")
    body = operation_input.get("body")
    if endpoint.has_body:
        if body is None and endpoint.body_required:
            raise _invalid("body is required")
        if body is not None and not isinstance(body, (Mapping, list)):
            raise _invalid("body must be a JSON object")
    if endpoint.paged:
        _whole("page", operation_input.get("page"), default=0, minimum=0, maximum=1000000)
        _whole("size", operation_input.get("size"), default=PAGE_SIZE, minimum=1, maximum=PAGE_SIZE)
        build_filter(operation_input.get("filters"), endpoint.filter_fields)
    return path, query, body


def _validate_only(operation_id: str, operation_input: Mapping[str, Any]) -> None:
    if operation_id in catalog.FRIENDLY_IDS:
        friendly.validate(operation_id, operation_input)
        return
    if operation_id == catalog.CALL_ENDPOINT:
        _call_request(operation_input)
        return
    endpoint_request(catalog.ENDPOINTS_BY_OPERATION[operation_id], operation_input)


# ---------------------------------------------------------------------------
# Results


def _neutral_result(operation_id: str) -> dict[str, Any]:
    """Every declared output of a write, for a test run where nothing was sent."""
    if operation_id in catalog.FRIENDLY_WRITE_IDS:
        result = friendly.neutral_result(operation_id)
    elif operation_id == catalog.CALL_ENDPOINT:
        result = {"endpoint": "", "response": None, "http_status": 0, "duration_ms": None}
    else:
        endpoint = catalog.ENDPOINTS_BY_OPERATION[operation_id]
        result = {"endpoint": endpoint.wire, "http_status": 0, "duration_ms": None}
        result.update(_empty_payload_fields(endpoint))
    # Nothing was sent. "failed" + definitely-no-effect is the pair Core accepts
    # for "no external effect happened"; an extension may not report "suppressed".
    result["external_effect_status"] = "failed"
    result["definitely_no_external_effect"] = True
    return result


def _empty_payload_fields(endpoint: Endpoint) -> dict[str, Any]:
    if endpoint.payload == "list":
        return {
            "records": [],
            "record": None,
            "count": 0,
            "total_elements": None,
            "total_pages": None,
            "page_number": None,
            "next_page": None,
            "pages_fetched": 0,
            "has_more": False,
        }
    if endpoint.payload == "file":
        return {"document_file": None, "size_bytes": 0, "original_content_type": None}
    return {endpoint.payload: [] if endpoint.payload == "records" else None}


def _mark_write(result: dict[str, Any]) -> dict[str, Any]:
    result["external_effect_status"] = "succeeded"
    result["definitely_no_external_effect"] = False
    return result


def _ok(result: Mapping[str, Any]) -> dict[str, Any]:
    response: dict[str, Any] = {
        "ok": True,
        "result": dict(result),
        "error_code": None,
        "error": None,
        "errors": [],
    }
    if "external_effect_status" in result:
        response["external_effect_status"] = result["external_effect_status"]
        response["definitely_no_external_effect"] = result["definitely_no_external_effect"]
    return response


def _payload_fields(endpoint: Endpoint, data: Any) -> dict[str, Any]:
    """The answer of a non-list endpoint in its declared output field."""
    if endpoint.payload == "records":
        return {"records": data if isinstance(data, list) else ([] if data is None else [data])}
    if endpoint.payload == "value":
        return {"value": data if not isinstance(data, (dict, list)) else None}
    return {"record": data if isinstance(data, dict) else None}


def fit_write_result(result: dict[str, Any], keys: tuple[str, ...] = ("record",)) -> dict[str, Any]:
    """Shrink a write's echo until it fits; the write itself already happened.

    Failing here would turn a saved record into an error the workflow might retry,
    so the result keeps its success and loses detail instead: the record is cut
    down to its id, code, number and name fields.
    """
    if budget.fits(result):
        return result
    for key in keys:
        value = result.get(key)
        if isinstance(value, dict):
            result[key] = {k: v for k, v in value.items() if _KEY_FIELDS.search(k)}
        elif isinstance(value, list):
            result[key] = []
    if not budget.fits(result):
        for key in keys:
            result[key] = [] if isinstance(result.get(key), list) else None
    return result


# ---------------------------------------------------------------------------
# Operations


def _test_connection(context: _Context) -> dict[str, Any]:
    unknown = set(context.operation_input) - {"connection_ref"}
    if unknown:
        raise _invalid(f"Unknown input: {', '.join(sorted(unknown))}")
    reply, duration = context.call("GET", "/v1/users/api-keys", mutating=False)
    status = None
    if isinstance(reply.data, str):
        status = errors.safe_text(reply.data, 200)
    elif isinstance(reply.data, Mapping):
        status = (
            errors.safe_text(reply.data.get("message") or reply.data.get("status"), 200) or None
        )
    elif isinstance(reply.data, bool):
        status = "valid" if reply.data else "invalid"
    return {
        "connected": True,
        "service_status": status,
        "duration_ms": duration,
        "http_status": reply.status,
    }


def _run_endpoint(context: _Context, endpoint: Endpoint) -> dict[str, Any]:
    path, query, body = endpoint_request(endpoint, context.operation_input)
    if endpoint.binary:
        return _download(context, endpoint, path)
    if endpoint.paged:
        return _run_paged(context, endpoint, path, query)
    reply, duration = context.call(
        endpoint.http_method, path, query=query, body=body, mutating=endpoint.write
    )
    result: dict[str, Any] = {"endpoint": endpoint.wire}
    result.update(_payload_fields(endpoint, reply.data))
    result["http_status"] = reply.status
    result["duration_ms"] = duration
    if endpoint.write:
        return _mark_write(fit_write_result(result, ("record", "records")))
    budget.ensure_fits(result)
    return result


def _page_of(data: Any) -> tuple[list[Any], int | None, int | None]:
    """(content, totalElements, totalPages) of a ListPageResponse."""
    if not isinstance(data, Mapping):
        raise ExtensionError(
            errors.INVALID_JSON_RESPONSE,
            "Rivile ERP's list answer has no content",
            definitely_no_external_effect=True,
            external_effect_status="failed",
        )
    content = field(data, "content")
    content = content if isinstance(content, list) else []
    total = field(data, "totalElements")
    pages = field(data, "totalPages")
    return (
        content,
        total if isinstance(total, int) and not isinstance(total, bool) else None,
        pages if isinstance(pages, int) and not isinstance(pages, bool) else None,
    )


def _more_after(page: int, size: int, content: list[Any], pages: int | None) -> bool:
    if pages is not None:
        return page + 1 < pages
    return len(content) >= size


def read_pages(
    context: _Context,
    path: str,
    query: list[tuple[str, str]],
    *,
    filter_json: str,
    first_page: int,
    size: int,
    max_pages: int,
    meter: budget.Meter | None,
) -> dict[str, Any]:
    """Read pages until the last one, ``max_pages``, the output budget or the deadline."""
    records: list[Any] = []
    page_sizes: list[int] = []
    page = first_page
    fetched = 0
    has_more = False
    total = pages_total = None
    last_page: int | None = None
    duration = 0
    status = 0
    while fetched < max_pages:
        page_query = [*query, ("page", str(page)), ("size", str(size))]
        if filter_json:
            page_query.append(("filter", filter_json))
        try:
            reply, took = context.call("GET", path, query=page_query, mutating=False)
        except DeadlineReached:
            if fetched == 0:
                raise
            has_more = True  # out of time: continue from next_page
            break
        content, total, pages_total = _page_of(reply.data)
        # The first record is repeated as ``record`` in the result: meter it twice.
        chunk = [content, content[0]] if fetched == 0 and content else content
        if meter is not None and not meter.admit(chunk):
            if fetched == 0:
                raise budget.too_large()
            has_more = True  # this page does not fit: stop before it
            break
        records.extend(content)
        page_sizes.append(len(content))
        fetched += 1
        duration += took
        status = reply.status
        last_page = page
        has_more = _more_after(page, size, content, pages_total)
        if not has_more:
            break
        page += 1
    return {
        "records": records,
        "total_elements": total,
        "total_pages": pages_total,
        "page_number": last_page,
        "next_page": (last_page if last_page is not None else page - 1) + 1 if has_more else None,
        "pages_fetched": fetched,
        "has_more": has_more,
        "http_status": status,
        "duration_ms": duration,
        "page_sizes": page_sizes,
    }


def fit_pages(
    read: dict[str, Any], build: Callable[[dict[str, Any]], dict[str, Any]]
) -> dict[str, Any]:
    """The result built from ``read``, dropping whole trailing pages until it fits.

    The meter keeps a margin, so this rarely drops anything; it makes sure a
    multi-page read always ends at a page boundary with ``has_more`` and
    ``next_page`` instead of failing after the pages were read.
    """
    while True:
        result = build(read)
        if budget.fits(result):
            return result
        sizes = read["page_sizes"]
        if len(sizes) <= 1:
            raise budget.too_large()
        dropped = sizes.pop()
        read["records"] = read["records"][: len(read["records"]) - dropped]
        read["pages_fetched"] -= 1
        read["page_number"] -= 1
        read["next_page"] = read["page_number"] + 1
        read["has_more"] = True


def _run_paged(
    context: _Context, endpoint: Endpoint, path: str, query: list[tuple[str, str]]
) -> dict[str, Any]:
    inputs = context.operation_input
    fetch_all = _bool("fetch_all_pages", inputs.get("fetch_all_pages"), False)
    max_pages = _whole(
        "max_pages",
        inputs.get("max_pages"),
        default=DEFAULT_MAX_PAGES,
        minimum=1,
        maximum=MAX_PAGES,
    )
    page = _whole("page", inputs.get("page"), default=0, minimum=0, maximum=1000000)
    size = _whole("size", inputs.get("size"), default=PAGE_SIZE, minimum=1, maximum=PAGE_SIZE)
    meter = budget.Meter()
    read = read_pages(
        context,
        path,
        query,
        filter_json=build_filter(inputs.get("filters"), endpoint.filter_fields),
        first_page=page,
        size=size,
        max_pages=max_pages if fetch_all else 1,
        meter=meter,
    )

    def build(done: dict[str, Any]) -> dict[str, Any]:
        records = done["records"]
        return {
            "endpoint": endpoint.wire,
            "records": records,
            "record": records[0] if records else None,
            "count": len(records),
            **{k: v for k, v in done.items() if k not in {"records", "page_sizes"}},
        }

    return fit_pages(read, build)


def _call_request(
    operation_input: Mapping[str, Any],
) -> tuple[str, str, list[tuple[str, str]], Any]:
    unknown = set(operation_input) - {"connection_ref", "method", "path", "query", "body"}
    if unknown:
        raise _invalid(f"Unknown input: {', '.join(sorted(unknown))}")
    method = _text(operation_input.get("method")).upper()
    if method not in CALL_METHODS:
        raise _invalid("method must be GET, POST, PATCH, PUT or DELETE")
    path = _text(operation_input.get("path"))
    segments = path.split("/")[1:]
    if not _CALL_PATH_RE.fullmatch(path) or any(s in {"", ".", ".."} for s in segments):
        raise _invalid("path must be a Rivile ERP path under /v1, for example /v1/clients")
    raw_query = operation_input.get("query") or {}
    if not isinstance(raw_query, Mapping) or len(raw_query) > 30:
        raise _invalid("query must be an object of at most 30 parameters")
    query: list[tuple[str, str]] = []
    for key, value in raw_query.items():
        name = str(key).strip()
        if not _FIELD_RE.fullmatch(name):
            raise _invalid("query parameter names are letters, digits and _ only")
        if name == "filter" and isinstance(value, list):
            query.append((name, build_filter(value, None)))
        else:
            query.append((name, _scalar_text(f"query.{name}", value)))
    return method, path, query, operation_input.get("body")


def _call_endpoint(context: _Context) -> dict[str, Any]:
    method, path, query, body = _call_request(context.operation_input)
    reply, duration = context.call(method, path, query=query, body=body, mutating=True)
    result = {
        "endpoint": f"{method} {path}",
        "response": reply.data,
        "http_status": reply.status,
        "duration_ms": duration,
    }
    if not budget.fits(result):
        result["response"] = None
    # call_endpoint is a declared external effect whatever it sends; "succeeded"
    # with "may have an effect" is the consistent, conservative pair.
    return _mark_write(result)


def _export_list(context: _Context) -> dict[str, Any]:
    inputs = context.operation_input
    unknown = set(inputs) - {"connection_ref", "list", "filters", "max_pages", "start_page"}
    if unknown:
        raise _invalid(f"Unknown input: {', '.join(sorted(unknown))}")
    endpoint = catalog.LISTS_BY_PATH.get(_text(inputs.get("list")))
    if endpoint is None:
        raise _invalid("list must be one of the Rivile ERP list paths, for example /v1/clients")
    filter_json = build_filter(inputs.get("filters"), endpoint.filter_fields)
    max_pages = _whole(
        "max_pages",
        inputs.get("max_pages"),
        default=EXPORT_MAX_PAGES,
        minimum=1,
        maximum=EXPORT_MAX_PAGES,
    )
    page = _whole("start_page", inputs.get("start_page"), default=0, minimum=0, maximum=1000000)
    # Records are buffered (one copy, at most 200 MB) and written once at the end,
    # so a failure part-way still saves what was read.
    chunks: list[bytes] = []
    size_total = count = fetched = 0
    complete = False
    total: int | None = None
    while fetched < max_pages:
        query = [("page", str(page)), ("size", str(PAGE_SIZE))]
        if filter_json:
            query.append(("filter", filter_json))
        try:
            reply, _took = context.call("GET", endpoint.path, query=query, mutating=False)
        except DeadlineReached:
            if fetched == 0:
                raise
            break  # save what was read; resume_page continues
        content, total, pages_total = _page_of(reply.data)
        page_chunks = [
            (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8") for record in content
        ]
        page_bytes = sum(len(chunk) for chunk in page_chunks)
        if size_total + page_bytes > MAX_EXPORT_BYTES:
            if fetched == 0:
                raise ExtensionError(
                    errors.RESPONSE_TOO_LARGE,
                    "One Rivile ERP page exceeds the 200 MB export limit",
                    definitely_no_external_effect=True,
                    external_effect_status="failed",
                )
            break
        fetched += 1
        chunks.extend(page_chunks)
        size_total += page_bytes
        count += len(page_chunks)
        more = _more_after(page, PAGE_SIZE, content, pages_total)
        page += 1
        if not more:
            complete = True
            break
    handle = write_artifact(
        context,
        chunks,
        binding_key=catalog.EXPORT_BINDING,
        content_type=EXPORT_CONTENT_TYPE,
        what="The export file",
    )
    return {
        "artifact_handle": handle,
        "filename": EXPORT_FILENAME,
        "content_type": EXPORT_CONTENT_TYPE,
        "record_count": count,
        "pages_fetched": fetched,
        "complete": complete,
        "resume_page": None if complete else page,
        "total_elements": total,
    }


# ---------------------------------------------------------------------------
# Files


def write_artifact(
    context: _Context, chunks: list[bytes], *, binding_key: str, content_type: str, what: str
) -> str:
    try:
        written = context.artifact_writer(
            dict(context.payload),
            chunks,
            binding_key=binding_key,
            content_type=content_type,
            timeout_seconds=ARTIFACT_WRITE_TIMEOUT_SECONDS,
        )
    except ExtensionError:
        raise
    except Exception as exc:
        raise ExtensionError(
            errors.ARTIFACT_OUTPUT_UNAVAILABLE,
            f"{what} could not be saved",
            definitely_no_external_effect=True,
            external_effect_status="failed",
        ) from exc
    handle = _text(written.get("artifact_handle")) if isinstance(written, Mapping) else ""
    if not handle:
        raise ExtensionError(
            errors.ARTIFACT_OUTPUT_UNAVAILABLE,
            f"{what} could not be saved",
            definitely_no_external_effect=True,
            external_effect_status="failed",
        )
    return handle


def download_file(
    context: _Context, file_id: str, *, binding_key: str
) -> tuple[str, int, str, int, int]:
    """(artifact handle, size, Rivile content type, HTTP status, duration ms) of one file."""
    path = encode_path(catalog.FILE_CONTENT_PATH, {"id": path_value("file_id", file_id)})
    reply, duration = context.call("GET", path, mutating=False, binary=True)
    body = reply.data
    if not isinstance(body, (bytes, bytearray)):
        raise ExtensionError(
            errors.INVALID_JSON_RESPONSE,
            "Rivile ERP did not return file content",
            definitely_no_external_effect=True,
            external_effect_status="failed",
        )
    if len(body) > MAX_DOWNLOAD_BYTES:
        raise ExtensionError(errors.RESPONSE_TOO_LARGE, "The file is larger than 50 MB")
    handle = write_artifact(
        context,
        [bytes(body)],
        binding_key=binding_key,
        content_type=DOWNLOAD_CONTENT_TYPE,
        what="The file",
    )
    return handle, len(body), errors.safe_text(reply.content_type, 120), reply.status, duration


def _download(context: _Context, endpoint: Endpoint, path: str) -> dict[str, Any]:
    file_id = path.rsplit("/", 2)[-2]
    handle, size, content_type, status, duration = download_file(
        context, file_id, binding_key=catalog.DOWNLOAD_BINDING
    )
    return {
        "endpoint": endpoint.wire,
        "document_file": handle,
        "size_bytes": size,
        "original_content_type": content_type or None,
        "http_status": status,
        "duration_ms": duration,
    }


# ---------------------------------------------------------------------------
# Everyday operations


def _run_friendly(context: _Context, operation_id: str) -> dict[str, Any]:
    inputs = {k: v for k, v in context.operation_input.items() if k != "connection_ref"}
    friendly.validate(operation_id, inputs)
    api = friendly.Api(context)
    result = friendly.run(api, operation_id, inputs)
    if operation_id in catalog.FRIENDLY_WRITE_IDS:
        return _mark_write(fit_write_result(result))
    budget.ensure_fits(result)
    return result


__all__ = [
    "DEFAULT_MAX_PAGES",
    "DOWNLOAD_CONTENT_TYPE",
    "EXPORT_CONTENT_TYPE",
    "MAX_PAGES",
    "PAGE_SIZE",
    "build_filter",
    "download_file",
    "endpoint_request",
    "fit_write_result",
    "handle_runtime",
    "read_pages",
    "write_artifact",
]
