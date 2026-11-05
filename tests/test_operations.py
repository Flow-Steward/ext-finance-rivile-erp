"""Transport and per-endpoint behaviour, against a fake Rivile ERP."""

from __future__ import annotations

import json
from conftest import API_KEY, UUID_A, ArtifactSink, FakeOpener, page, payload

from runtime import operations
from runtime.operations import handle_runtime


def run(make_factory, opener: FakeOpener, operation_id: str, inputs: dict | None = None, **kw):
    sink = kw.pop("sink", None) or ArtifactSink()
    factory = make_factory(opener)
    response = handle_runtime(
        payload(operation_id, inputs, **kw), transport_factory=factory, artifact_writer=sink
    )
    return response, factory, sink


def test_test_connection_sends_the_key_header(make_factory) -> None:
    opener = FakeOpener((200, True))
    response, _f, _s = run(make_factory, opener, "test_connection")
    assert response["ok"] is True
    assert response["result"]["connected"] is True
    request = opener.requests[0]
    assert request["method"] == "GET"
    assert request["url"] == "https://erp.rivile.cloud/public-api/v1/users/api-keys"
    assert request["headers"]["x-sessiontoken"] == API_KEY
    assert request["headers"]["accept-language"] == "en"


def test_list_sends_documented_filter_as_json_array(make_factory) -> None:
    opener = FakeOpener((200, page({"id": UUID_A, "code": "000005"}, total_pages=3)))
    response, _f, _s = run(
        make_factory,
        opener,
        "get_clients",
        {"filters": [{"field": "code", "operation": "equal", "value": "000005"}], "size": 50},
    )
    assert response["ok"] is True
    query = opener.requests[0]["query"]
    assert query["page"] == "0"
    assert query["size"] == "50"
    assert json.loads(query["filter"]) == [
        {"operation": "EQUAL", "name": "code", "value": "000005"}
    ]
    result = response["result"]
    assert result["count"] == 1
    assert result["record"]["code"] == "000005"
    assert result["has_more"] is True
    assert result["next_page"] == 1
    assert result["total_pages"] == 3


def test_undocumented_filter_field_is_refused_before_sending(make_factory) -> None:
    opener = FakeOpener()
    response, _f, _s = run(
        make_factory,
        opener,
        "get_clients",
        {"filters": [{"field": "secretColumn", "operation": "EQUAL", "value": "x"}]},
    )
    assert response["error_code"] == "invalid_payload"
    assert response["definitely_no_external_effect"] is True
    assert opener.requests == []


def test_filter_value_with_control_characters_is_refused(make_factory) -> None:
    opener = FakeOpener()
    response, _f, _s = run(
        make_factory,
        opener,
        "get_clients",
        {"filters": [{"field": "name", "operation": "CONTAINS", "value": "a\nb"}]},
    )
    assert response["error_code"] == "invalid_payload"
    assert opener.requests == []


def test_fetch_all_pages_reads_until_the_last_page(make_factory) -> None:
    opener = FakeOpener(
        (200, page({"id": "1"}, total_pages=2, total=2)),
        (200, page({"id": "2"}, total_pages=2, total=2)),
    )
    response, _f, _s = run(make_factory, opener, "get_products", {"fetch_all_pages": True})
    result = response["result"]
    assert [r["id"] for r in result["records"]] == ["1", "2"]
    assert result["pages_fetched"] == 2
    assert result["has_more"] is False
    assert [r["query"]["page"] for r in opener.requests] == ["0", "1"]


def test_a_write_sends_its_body_once_and_reports_the_record(make_factory) -> None:
    opener = FakeOpener((201, {"id": UUID_A, "code": "C1", "name": "UAB X"}))
    response, _f, _s = run(
        make_factory, opener, "post_clients", {"body": {"name": "UAB X", "typeId": 0}}
    )
    assert response["ok"] is True
    assert opener.requests[0]["method"] == "POST"
    assert opener.requests[0]["body"] == {"name": "UAB X", "typeId": 0}
    assert response["result"]["record"]["code"] == "C1"
    assert response["external_effect_status"] == "succeeded"
    assert response["definitely_no_external_effect"] is False


def test_a_5xx_on_a_write_is_an_unknown_outcome_and_not_retried(make_factory) -> None:
    opener = FakeOpener((500, {"code": "error.internal"}))
    response, _f, _s = run(make_factory, opener, "patch_sale_invoices_id_post", {"id": UUID_A})
    assert response["error_code"] == "timeout_unknown"
    assert response["external_effect_status"] == "timeout_unknown"
    assert response["definitely_no_external_effect"] is False
    assert response["retryable"] is False
    assert len(opener.requests) == 1


def test_a_timeout_on_a_write_is_an_unknown_outcome(make_factory) -> None:
    opener = FakeOpener(TimeoutError("read timed out"))
    response, _f, _s = run(make_factory, opener, "delete_sale_invoices_id", {"id": UUID_A})
    assert response["error_code"] == "timeout_unknown"
    assert response["definitely_no_external_effect"] is False


def test_a_5xx_on_a_read_is_retryable_without_effect(make_factory) -> None:
    opener = FakeOpener((503, ""))
    response, _f, _s = run(make_factory, opener, "get_clients_id", {"id": UUID_A})
    assert response["error_code"] == "upstream_failure"
    assert response["retryable"] is True
    assert response["definitely_no_external_effect"] is True


def test_validation_errors_carry_the_json_path(make_factory) -> None:
    body = {
        "code": "error.purchase-invoice.create.lines",
        "values": {
            "path": "createPurchaseInvoiceLine",
            "violations": {
                "lines[0].itemUomAltCode": "ItemUomAlt not found - Metras",
                "lines[3].itemCode": "Item not found - ABC123DEF",
            },
        },
    }
    opener = FakeOpener((400, body))
    response, _f, _s = run(
        make_factory, opener, "post_purchase_invoices", {"body": {"clientCode": "1"}}
    )
    assert response["error_code"] == "upstream_validation_failed"
    assert response["definitely_no_external_effect"] is True
    paths = [e.get("rivile_path") for e in response["errors"][1:]]
    assert paths == ["lines[0].itemUomAltCode", "lines[3].itemCode"]
    assert "Item not found - ABC123DEF" in response["error"]


def test_401_and_404(make_factory) -> None:
    response, _f, _s = run(make_factory, FakeOpener((401, "")), "get_clients_id", {"id": UUID_A})
    assert response["error_code"] == "authentication_failed"
    response, _f, _s = run(make_factory, FakeOpener((404, "")), "get_clients_id", {"id": UUID_A})
    assert response["error_code"] == "not_found"


def test_429_is_retried_with_backoff(make_factory) -> None:
    opener = FakeOpener((429, ""), (201, {"id": UUID_A}))
    response, factory, _s = run(make_factory, opener, "post_lots", {"body": {"code": "L1"}})
    assert response["ok"] is True
    assert len(opener.requests) == 2
    assert 1.0 in factory.sleeps


def test_test_mode_write_sends_nothing(make_factory) -> None:
    opener = FakeOpener()
    response, _f, _s = run(
        make_factory, opener, "post_clients", {"body": {"name": "X", "typeId": 0}}, test_mode=True
    )
    assert response["ok"] is True
    assert response["result"]["external_effect_status"] == "failed"
    assert response["result"]["definitely_no_external_effect"] is True
    assert opener.requests == []


def test_test_mode_still_validates(make_factory) -> None:
    response, _f, _s = run(make_factory, FakeOpener(), "post_clients", {"bogus": 1}, test_mode=True)
    assert response["error_code"] == "invalid_payload"


def test_unknown_operation_and_unknown_input(make_factory) -> None:
    response, _f, _s = run(make_factory, FakeOpener(), "drop_everything")
    assert response["error_code"] == "unsupported_operation"
    response, _f, _s = run(make_factory, FakeOpener(), "get_clients", {"sql": "x"})
    assert response["error_code"] == "invalid_payload"


def test_path_ids_are_validated(make_factory) -> None:
    opener = FakeOpener()
    response, _f, _s = run(make_factory, opener, "get_clients_id", {"id": "../users"})
    assert response["error_code"] == "invalid_payload"
    assert opener.requests == []


def test_file_content_is_saved_as_a_workflow_file(make_factory) -> None:
    opener = FakeOpener((200, b"%PDF-1.7 data", {"Content-Type": "application/pdf"}))
    response, _f, sink = run(make_factory, opener, "get_files_id_content", {"id": UUID_A})
    assert response["ok"] is True
    assert response["result"]["document_file"] == "artifact-1"
    assert response["result"]["size_bytes"] == len(b"%PDF-1.7 data")
    assert sink.writes[0]["content_type"] == operations.DOWNLOAD_CONTENT_TYPE
    assert sink.writes[0]["binding_key"] == "rivile_erp_file"
    assert sink.writes[0]["body"] == b"%PDF-1.7 data"


def test_export_list_writes_jsonl(make_factory) -> None:
    opener = FakeOpener(
        (200, page({"id": "1"}, {"id": "2"}, total_pages=2, total=3)),
        (200, page({"id": "3"}, total_pages=2, total=3)),
    )
    response, _f, sink = run(make_factory, opener, "export_list", {"list": "/v1/products"})
    result = response["result"]
    assert result["complete"] is True
    assert result["record_count"] == 3
    lines = sink.writes[0]["body"].decode().splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["1", "2", "3"]
    assert sink.writes[0]["content_type"] == operations.EXPORT_CONTENT_TYPE


def test_call_endpoint_refuses_paths_outside_v1(make_factory) -> None:
    for path in ("/v1/../admin", "/health/status", "https://evil.example/v1/x"):
        response, _f, _s = run(
            make_factory, FakeOpener(), "call_endpoint", {"method": "GET", "path": path}
        )
        assert response["error_code"] == "invalid_payload", path


def test_call_endpoint_is_a_write(make_factory) -> None:
    opener = FakeOpener((200, {"ok": True}))
    response, _f, _s = run(
        make_factory, opener, "call_endpoint", {"method": "GET", "path": "/v1/clients"}
    )
    assert response["external_effect_status"] == "succeeded"
    assert response["result"]["response"] == {"ok": True}


def test_the_api_key_is_redacted_from_answers(make_factory, host_secret_guard) -> None:
    opener = FakeOpener((200, {"id": UUID_A, "notes": f"key {API_KEY} echoed"}))
    response, _f, _s = run(make_factory, opener, "get_clients_id", {"id": UUID_A})
    text = json.dumps(response)
    assert API_KEY not in text
    assert "[redacted]" in text
    assert not host_secret_guard(response, [API_KEY])


def test_a_list_too_large_for_one_output_stops_at_a_page(make_factory) -> None:
    wide = {f"field{i}": f"value-{i}" for i in range(40)}
    big_page = page(*[dict(wide, id=str(n)) for n in range(100)], total_pages=5)
    opener = FakeOpener(*[(200, big_page) for _ in range(5)])
    response, _f, _s = run(
        make_factory, opener, "get_products", {"fetch_all_pages": True, "max_pages": 5}
    )
    result = response["result"]
    assert response["ok"] is True
    assert result["has_more"] is True
    assert result["pages_fetched"] < 5
    assert result["next_page"] == result["pages_fetched"]


def test_no_time_left_means_no_request(make_factory) -> None:
    opener = FakeOpener()

    def factory(connection):
        transport = make_factory(opener)(connection)
        transport.clock = iter([0.0, 0.0, 10_000.0, 10_000.0]).__next__  # type: ignore[method-assign]
        return transport

    response = handle_runtime(payload("get_clients"), transport_factory=factory)
    assert response["error_code"] == "timeout"
    assert response["definitely_no_external_effect"] is True
    assert opener.requests == []


def test_query_parameters_are_typed(make_factory) -> None:
    opener = FakeOpener((200, [{"id": "d1"}]))
    response, _f, _s = run(
        make_factory,
        opener,
        "get_timesheet_schedules_id_days",
        {"id": UUID_A, "date_from": "2026-01-01", "date_to": "2026-01-31"},
    )
    assert response["ok"] is True, response
    assert opener.requests[0]["query"] == {"dateFrom": "2026-01-01", "dateTo": "2026-01-31"}


def test_a_long_multi_page_read_ends_at_a_page_boundary(make_factory) -> None:
    wide = {f"field{i}": f"value-{i}" for i in range(19)}
    pages = [
        (200, page(*[dict(wide, id=f"{p}-{n}") for n in range(15)], total_pages=60))
        for p in range(60)
    ]
    opener = FakeOpener(*pages)
    response, _f, _s = run(
        make_factory, opener, "get_products", {"fetch_all_pages": True, "max_pages": 60, "size": 15}
    )
    assert response["ok"] is True, response["error"]
    result = response["result"]
    assert result["has_more"] is True
    assert result["count"] == result["pages_fetched"] * 15
    assert result["next_page"] == result["pages_fetched"]
    assert result["page_number"] == result["pages_fetched"] - 1


def test_fit_pages_drops_whole_trailing_pages() -> None:
    read = {
        "records": [{"v": "x" * 1000} for _ in range(30)],
        "page_sizes": [10, 10, 10],
        "pages_fetched": 3,
        "page_number": 2,
        "next_page": None,
        "has_more": False,
    }
    calls = []

    def build(done):
        calls.append(len(done["records"]))
        return {
            "records": done["records"],
            "pad": "y" * (4_000_000 if len(done["records"]) > 10 else 0),
        }

    result = operations.fit_pages(read, build)
    assert calls == [30, 20, 10]
    assert len(result["records"]) == 10
    assert read["has_more"] is True and read["next_page"] == 1


def test_path_ids_must_be_uuids(make_factory) -> None:
    opener = FakeOpener()
    for value in ("..", ".", "abc", f"{UUID_A}/..", "%2e%2e"):
        response, _f, _s = run(
            make_factory,
            opener,
            "delete_deliveries_delivery_id_lines_line_id",
            {"delivery_id": UUID_A, "line_id": value},
        )
        assert response["error_code"] == "invalid_payload", value
    assert opener.requests == []


def test_call_endpoint_refuses_dot_segments(make_factory) -> None:
    for path in ("/v1/./clients", "/v1/clients/.", "/v1/a/../b", "/v1/clients/"):
        response, _f, _s = run(
            make_factory, FakeOpener(), "call_endpoint", {"method": "DELETE", "path": path}
        )
        assert response["error_code"] == "invalid_payload", path


def test_a_redirect_on_a_write_is_an_unknown_outcome(make_factory) -> None:
    opener = FakeOpener((302, "", {"Location": "https://elsewhere.example/"}))
    response, _f, _s = run(make_factory, opener, "post_lots", {"body": {"code": "L1"}})
    assert response["error_code"] == "redirect_rejected"
    assert response["external_effect_status"] == "timeout_unknown"
    assert response["definitely_no_external_effect"] is False
    opener = FakeOpener((302, "", {"Location": "https://elsewhere.example/"}))
    response, _f, _s = run(make_factory, opener, "get_clients_id", {"id": UUID_A})
    assert response["error_code"] == "redirect_rejected"
    assert response["definitely_no_external_effect"] is True


def test_an_unreadable_answer_to_a_write_says_it_was_accepted(make_factory) -> None:
    opener = FakeOpener((201, "<html>not json</html>", {"Content-Type": "text/html"}))
    response, _f, _s = run(make_factory, opener, "post_lots", {"body": {"code": "L1"}})
    assert response["error_code"] == "timeout_unknown"
    assert "accepted the request (HTTP 201)" in response["error"]
    assert response["definitely_no_external_effect"] is False


def test_required_query_parameters_are_enforced(make_factory) -> None:
    opener = FakeOpener()
    response, _f, _s = run(make_factory, opener, "get_timesheets", {"employee_code": "E1"})
    assert response["error_code"] == "invalid_payload"
    assert "calendar_period_code" in response["error"]
    response, _f, _s = run(
        make_factory,
        opener,
        "get_timesheet_schedules_id_days",
        {"id": UUID_A, "date_from": "2026-01-01"},
    )
    assert response["error_code"] == "invalid_payload"
    assert opener.requests == []


def test_error_fields_are_read_case_insensitively(make_factory) -> None:
    body = {"Code": "error.x", "Values": {"Violations": {"name": "Required"}}}
    response, _f, _s = run(make_factory, FakeOpener((400, body)), "post_lots", {"body": {}})
    assert response["errors"][1]["rivile_path"] == "name"
    assert "error.x" in response["error"]


def test_a_key_in_a_long_error_body_is_redacted_before_it_is_cut(make_factory) -> None:
    from runtime.transport import MAX_ERROR_BODY_BYTES

    padding = "x" * (MAX_ERROR_BODY_BYTES - 10)
    opener = FakeOpener((400, padding + API_KEY + "tail"))
    response, _f, _s = run(make_factory, opener, "get_clients_id", {"id": UUID_A})
    text = json.dumps(response)
    assert API_KEY[:10] not in text


class SlowResponse:
    """An answer that arrives in small pieces while the clock runs."""

    def __init__(self, clock, chunks: int, seconds_per_chunk: float) -> None:
        self.status = 200
        self.headers = {"Content-Type": "application/json"}
        self._clock = clock
        self._left = chunks
        self._step = seconds_per_chunk

    def read(self, size: int = -1) -> bytes:
        if self._left == 0:
            return b""
        self._left -= 1
        self._clock.now += self._step
        return b" "

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _slow_run(operation_id: str, inputs: dict, make_factory):
    clock = Clock()
    requests = []

    def opener(request, *, timeout_seconds, purpose):
        requests.append(request)
        return SlowResponse(clock, chunks=1000, seconds_per_chunk=5.0)

    def factory(connection):
        transport = make_factory(FakeOpener())(connection)
        transport._opener = opener
        transport.clock = clock
        return transport

    return handle_runtime(payload(operation_id, inputs), transport_factory=factory), requests


def test_a_trickling_read_stops_at_the_step_deadline(make_factory) -> None:
    response, requests = _slow_run("get_clients_id", {"id": UUID_A}, make_factory)
    assert response["error_code"] == "timeout"
    assert response["definitely_no_external_effect"] is True
    assert len(requests) == 1


def test_a_trickling_answer_to_a_write_is_an_unknown_outcome(make_factory) -> None:
    response, _requests = _slow_run("post_lots", {"body": {"code": "L1"}}, make_factory)
    assert response["error_code"] == "timeout_unknown"
    assert response["definitely_no_external_effect"] is False


def test_export_keeps_what_was_read_when_a_later_page_fails(make_factory) -> None:
    opener = FakeOpener((200, page({"id": "1"}, {"id": "2"}, total_pages=3)), (502, ""))
    response, _f, sink = run(make_factory, opener, "export_list", {"list": "/v1/products"})
    result = response["result"]
    assert response["ok"] is True
    assert result["complete"] is False and result["resume_page"] == 1
    assert result["record_count"] == 2
    assert result["stopped_by"].startswith("upstream_failure")
    assert len(sink.writes[0]["body"].splitlines()) == 2


def test_call_endpoint_get_is_a_read(make_factory) -> None:
    response, _f, _s = run(
        make_factory, FakeOpener((500, "")), "call_endpoint", {"method": "GET", "path": "/v1/lots"}
    )
    assert response["error_code"] == "upstream_failure"
    assert response["definitely_no_external_effect"] is True
    opener = FakeOpener((200, b"%PDF-1.7", {"Content-Type": "application/pdf"}))
    response, _f, _s = run(
        make_factory,
        opener,
        "call_endpoint",
        {"method": "GET", "path": f"/v1/files/{UUID_A}/content"},
    )
    answer = response["result"]["response"]
    assert answer["content_type"] == "application/pdf" and answer["size_bytes"] == 8
    assert response["external_effect_status"] == "succeeded"


def test_a_json_attachment_is_saved_as_a_file(make_factory) -> None:
    body = b'{"invoice": 1}'
    opener = FakeOpener((200, body, {"Content-Type": "application/json"}))
    response, _f, sink = run(make_factory, opener, "get_files_id_content", {"id": UUID_A})
    assert response["ok"] is True
    assert sink.writes[0]["body"] == body
