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
