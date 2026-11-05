from __future__ import annotations

import io
import json
import sys
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
if str(BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(BUNDLE_ROOT))
GENERATOR_ROOT = BUNDLE_ROOT / "tests" / "reference"
if str(GENERATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(GENERATOR_ROOT))

from runtime.transport import RivileTransport  # noqa: E402


def _core_secret_guard():
    """The host's own value_exposes_secret, loaded from the Flow Steward checkout.

    Loaded by file path (no Core package import chain). The gate mounts the
    checkout at /app; FLOW_STEWARD_ROOT overrides that.
    """
    import importlib.util
    import os

    candidates = [os.environ.get("FLOW_STEWARD_ROOT", ""), "/app", *map(str, BUNDLE_ROOT.parents)]
    for root in candidates:
        path = Path(root) / "core/application/extensions/secret_reflection.py" if root else None
        if path and path.is_file():
            spec = importlib.util.spec_from_file_location("fs_core_secret_reflection", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module.value_exposes_secret
    return None


@pytest.fixture
def host_secret_guard():
    guard = _core_secret_guard()
    if guard is None:
        pytest.skip("Flow Steward checkout not found; set FLOW_STEWARD_ROOT")
    return guard


CONNECTION_ID = "conn-rivile-erp-1"
API_KEY = "erp-fixture-key-0001-abcdefghijklmnop"  # pragma: allowlist secret
ROOT_SCOPE: dict[str, Any] = {
    "group_id": None,
    "for_each_id": None,
    "step_id": "rivile_erp_step",
    "step_execution_id": "5c1d2e3f-4a5b-4c6d-8e7f-000000000001",
}
UUID_A = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
UUID_B = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"


def payload(
    operation_id: str,
    operation_input: dict[str, Any] | None = None,
    *,
    test_mode: bool = False,
    secrets: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": "extension_host_v2",
        "mode": "action",
        "runtime_context": {
            **ROOT_SCOPE,
            "test_mode": test_mode,
            "external_effect_id": "6a3f1c2e-7b45-4d0a-9c11-2f8e5b7a0d31",
        },
        "action": {
            "action_id": operation_id,
            "input": {"connection_ref": CONNECTION_ID, **(operation_input or {})},
            "target": {
                "connection": {
                    "connection_id": CONNECTION_ID,
                    "connection_type_id": "rivile_erp",
                    "config": config if config is not None else {"language": "en"},
                    "secrets": secrets if secrets is not None else {"api_key": API_KEY},
                }
            },
        },
    }


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.code = status
        self._buffer = body
        message = Message()
        for key, value in (headers or {}).items():
            message[key] = value
        self.headers = message

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk, self._buffer = self._buffer, b""
            return chunk
        chunk, self._buffer = self._buffer[:size], self._buffer[size:]
        return chunk

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeOpener:
    """Records every request and answers from a queue of (status, body[, headers])."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: Any, *, timeout_seconds: float, purpose: str) -> Any:
        url = urlsplit(request.full_url)
        query = parse_qs(url.query)
        self.requests.append(
            {
                "url": request.full_url,
                "path": url.path,
                "query": {k: v[0] for k, v in query.items()},
                "method": request.get_method(),
                "headers": {k.lower(): v for k, v in request.header_items()},
                "body": json.loads(request.data.decode("utf-8")) if request.data else None,
                "timeout": timeout_seconds,
            }
        )
        if not self.answers:
            raise AssertionError(f"unexpected request {request.get_method()} {url.path}")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        status, body, *rest = answer
        headers = rest[0] if rest else {"Content-Type": "application/json"}
        if isinstance(body, (bytes, bytearray)):
            raw = bytes(body)
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        else:
            raw = json.dumps(body).encode("utf-8")
        if status >= 400:
            message = Message()
            for key, value in headers.items():
                message[key] = value
            raise HTTPError(request.full_url, status, "error", message, io.BytesIO(raw))
        return FakeResponse(status, raw, headers)


@pytest.fixture
def make_factory():
    def factory(opener: FakeOpener):
        sleeps: list[float] = []

        def build(connection):
            return RivileTransport(connection, opener=opener, sleeper=sleeps.append)

        build.sleeps = sleeps  # type: ignore[attr-defined]
        return build

    return factory


class ArtifactSink:
    """Stands in for the SDK's write_artifact_stream."""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    def __call__(self, payload, chunks, *, binding_key, content_type, timeout_seconds):
        body = b"".join(chunks)
        self.writes.append({"binding_key": binding_key, "content_type": content_type, "body": body})
        return {"artifact_handle": f"artifact-{len(self.writes)}"}


def page(*records: dict[str, Any], total_pages: int = 1, total: int | None = None) -> dict:
    return {
        "totalElements": total if total is not None else len(records),
        "totalPages": total_pages,
        "content": list(records),
    }
