"""Everyday operations, against a fake Rivile ERP."""

from __future__ import annotations

import json

from conftest import UUID_A, UUID_B, ArtifactSink, FakeOpener, page, payload

from runtime.operations import handle_runtime

CLIENT = {"id": UUID_A, "code": "000005", "regCode": "111", "vatNumber": "LT111", "name": "UAB X"}


def run(make_factory, opener: FakeOpener, operation_id: str, inputs: dict | None = None, **kw):
    sink = kw.pop("sink", None) or ArtifactSink()
    response = handle_runtime(
        payload(operation_id, inputs, **kw),
        transport_factory=make_factory(opener),
        artifact_writer=sink,
    )
    return response, sink


def _filter(request: dict) -> list[dict]:
    return json.loads(request["query"]["filter"])


def test_find_client_by_code_creates_nothing(make_factory) -> None:
    opener = FakeOpener((200, page(CLIENT)))
    response, _ = run(make_factory, opener, "find_or_create_client", {"client_code": "000005"})
    result = response["result"]
    assert result["created"] is False
    assert result["client_id"] == UUID_A
    assert result["matched_by"] == "client_code"
    assert _filter(opener.requests[0]) == [
        {"operation": "EQUAL", "name": "code", "value": "000005"}
    ]
    assert len(opener.requests) == 1


def test_create_client_when_none_matches(make_factory) -> None:
    opener = FakeOpener((200, page()), (200, page()), (201, {"id": UUID_B, "code": "000099"}))
    response, _ = run(
        make_factory,
        opener,
        "find_or_create_client",
        {"reg_code": "222", "vat_number": "LT222", "name": "UAB Y"},
    )
    result = response["result"]
    assert result["created"] is True
    assert result["client_code"] == "000099"
    post = opener.requests[-1]
    assert post["method"] == "POST" and post["path"].endswith("/v1/clients")
    assert post["body"] == {
        "name": "UAB Y",
        "typeId": 0,
        "isCustomer": True,
        "isSupplier": False,
        "regCode": "222",
        "vatNumber": "LT222",
    }
    assert response["external_effect_status"] == "succeeded"


def test_several_matches_are_an_error(make_factory) -> None:
    opener = FakeOpener((200, page(CLIENT, dict(CLIENT, id=UUID_B))))
    response, _ = run(make_factory, opener, "find_or_create_client", {"reg_code": "111"})
    assert response["error_code"] == "invalid_payload"
    assert len(opener.requests) == 1


def test_conflicting_codes_create_nothing(make_factory) -> None:
    opener = FakeOpener((200, page(CLIENT)))
    response, _ = run(
        make_factory,
        opener,
        "find_or_create_client",
        {"client_code": "000005", "vat_number": "LT999", "name": "X"},
    )
    assert response["error_code"] == "invalid_payload"
    assert "LT999" in response["error"]
    assert all(r["method"] == "GET" for r in opener.requests)


def test_lookup_values_are_allowlisted(make_factory) -> None:
    opener = FakeOpener()
    response, _ = run(make_factory, opener, "find_or_create_client", {"client_code": "a'b"})
    assert response["error_code"] == "invalid_payload"
    assert opener.requests == []


def _lines(count: int) -> list[dict]:
    return [{"item_code": f"P{n}", "quantity": "1.5", "price": "10.10"} for n in range(count)]


def test_invoice_with_an_existing_number_is_returned_not_duplicated(make_factory) -> None:
    existing = {"id": UUID_B, "documentNo": "S-1", "totalAmount": 12.1}
    opener = FakeOpener((200, page(CLIENT)), (200, page(existing)))
    response, _ = run(
        make_factory,
        opener,
        "create_sales_invoice",
        {"client_code": "000005", "number": "S-1", "department_code": "D1", "lines": _lines(1)},
    )
    result = response["result"]
    assert result["created"] is False
    assert result["document_id"] == UUID_B
    assert result["total_amount"] == "12.10"
    assert _filter(opener.requests[1]) == [
        {"operation": "EQUAL", "name": "documentNo", "value": "S-1"},
        {"operation": "EQUAL", "name": "clientCode", "value": "000005"},
    ]
    assert all(r["method"] == "GET" for r in opener.requests)


def test_invoice_over_100_lines_adds_the_rest_and_posts(make_factory) -> None:
    created = {"id": UUID_B, "documentNo": "S-2", "totalAmount": 1.0}
    answers = [(200, page(CLIENT)), (201, created)]
    answers += [(201, {"id": f"line-{n}"}) for n in range(20)]
    answers += [(200, True), (200, dict(created, totalAmount=1818.0, totalTaxAmount=315.52))]
    opener = FakeOpener(*answers)
    response, _ = run(
        make_factory,
        opener,
        "create_sales_invoice",
        {"client_code": "000005", "department_code": "D1", "lines": _lines(120), "post": True},
    )
    result = response["result"]
    assert response["ok"] is True, response
    create = opener.requests[1]
    assert len(create["body"]["lines"]) == 100
    assert create["body"]["lines"][0] == {
        "itemCode": "P0",
        "qtyAlt": 1.5,
        "departmentCode": "D1",
        "price": 10.1,
    }
    line_posts = [r for r in opener.requests if r["path"].endswith("/lines")]
    assert len(line_posts) == 20
    assert line_posts[0]["body"]["itemCode"] == "P100"
    assert opener.requests[-2]["method"] == "PATCH"
    assert opener.requests[-2]["path"].endswith(f"/v1/sale-invoices/{UUID_B}/post")
    assert result["lines_created"] == 120
    assert result["posted"] is True
    assert result["total_amount"] == "1818.00"
    assert result["total_tax"] == "315.52"


def test_invoice_failing_mid_way_reports_what_was_saved(make_factory) -> None:
    created = {"id": UUID_B, "documentNo": "S-3"}
    answers = [(200, page(CLIENT)), (201, created)]
    answers += [(201, {"id": f"line-{n}"}) for n in range(4)]
    answers += [(500, "")]
    opener = FakeOpener(*answers)
    response, _ = run(
        make_factory,
        opener,
        "create_sales_invoice",
        {"client_code": "000005", "department_code": "D1", "lines": _lines(110)},
    )
    assert response["error_code"] == "timeout_unknown"
    assert response["definitely_no_external_effect"] is False
    assert response["retryable"] is False
    assert "lines 1–104" in response["error"]
    assert "Adding line 105" in response["error"]


def test_invoice_validation_happens_before_any_call(make_factory) -> None:
    opener = FakeOpener()
    response, _ = run(
        make_factory,
        opener,
        "create_purchase_invoice",
        {
            "client_code": "1",
            "department_code": "D1",
            "lines": [{"item_code": "P", "quantity": "x"}],
        },
    )
    assert response["error_code"] == "invalid_payload"
    assert opener.requests == []


def test_register_payment_and_link(make_factory) -> None:
    opener = FakeOpener((201, {"id": UUID_A, "documentNo": "P-1"}), (200, True))
    response, _ = run(
        make_factory,
        opener,
        "register_payment",
        {
            "direction": "received",
            "client_code": "000005",
            "amount": "121.005",
            "invoice_id": UUID_B,
        },
    )
    result = response["result"]
    assert result["payment_id"] == UUID_A
    assert result["linked"] is True
    assert opener.requests[0]["body"] == {"typeId": 5, "clientCode": "000005", "amountCur": 121.01}
    assert opener.requests[1]["body"] == {"refId": UUID_B, "refModuleId": 0}


def test_find_or_create_product_by_barcode(make_factory) -> None:
    opener = FakeOpener((200, page()), (200, page()), (201, {"id": UUID_A, "code": "P9"}))
    response, _ = run(
        make_factory,
        opener,
        "find_or_create_product",
        {"product_code": "P9", "barcode": "4770001", "name": "Tea", "unit": "VNT"},
    )
    assert response["result"]["created"] is True
    assert opener.requests[-1]["body"] == {
        "name": "Tea",
        "productTypeId": 1,
        "bomTypeId": 1,
        "code": "P9",
        "productUnitOfMeasure": {"uomCode": "VNT", "mainBarcode": "4770001"},
    }
    assert _filter(opener.requests[1]) == [
        {"operation": "EQUAL", "name": "mainBarcode", "value": "4770001"}
    ]


def test_client_debt_sums_exactly(make_factory) -> None:
    rows = [
        {"documentNo": "S-1", "totalBaseDue": 0.1, "overDueDays": 5, "totalCurDue": 0.1},
        {"documentNo": "S-2", "totalBaseDue": 0.2, "overDueDays": 0},
    ]
    opener = FakeOpener((200, page(*rows)))
    response, _ = run(make_factory, opener, "client_debt", {"client_code": "000005"})
    result = response["result"]
    assert result["total_due"] == "0.30"
    assert result["overdue"] == "0.10"
    assert result["count"] == 2


def test_changes_since_filters_updated_at(make_factory) -> None:
    opener = FakeOpener((200, page({"id": "1"})))
    response, _ = run(
        make_factory, opener, "changes_since", {"entity": "products", "since": "2026-11-01"}
    )
    assert response["result"]["count"] == 1
    assert opener.requests[0]["path"].endswith("/v1/products")
    assert _filter(opener.requests[0]) == [
        {"operation": "GREATER_THAN", "name": "updatedAt", "value": "2026-11-01"}
    ]


def test_stock_levels_totals(make_factory) -> None:
    rows = [
        {"productCode": "P1", "departmentCode": "D1", "qtyAvailable": 1.25},
        {"productCode": "P1", "departmentCode": "D2", "qtyAvailable": 2},
    ]
    opener = FakeOpener((200, page(*rows)))
    response, _ = run(make_factory, opener, "stock_levels", {"product_code": "P1"})
    assert response["result"]["total_available"] == "3.2500"
    assert response["result"]["items"][0]["available"] == "1.2500"


def test_download_document_file_takes_the_named_attachment(make_factory) -> None:
    invoice = {
        "id": UUID_A,
        "attachments": [
            {"id": UUID_B, "name": "scan", "extension": "pdf", "typeId": "ATTACHMENT"},
            {"id": UUID_A, "name": "link", "typeId": "LINK", "externalLinkUrl": "https://x"},
        ],
    }
    opener = FakeOpener((200, invoice), (200, b"%PDF", {"Content-Type": "application/pdf"}))
    response, sink = run(
        make_factory,
        opener,
        "download_document_file",
        {"document_type": "sale_invoice", "document_id": UUID_A, "file_name": "scan.pdf"},
    )
    result = response["result"]
    assert result["found"] is True
    assert result["file_id"] == UUID_B
    assert result["original_filename"] == "scan.pdf"
    assert opener.requests[1]["path"].endswith(f"/v1/files/{UUID_B}/content")
    assert sink.writes[0]["binding_key"] == "rivile_erp_document_file"


def test_download_without_attachment_is_not_found(make_factory) -> None:
    opener = FakeOpener((200, {"id": UUID_A, "attachments": []}))
    response, sink = run(
        make_factory,
        opener,
        "download_document_file",
        {"document_type": "delivery", "document_id": UUID_A},
    )
    assert response["result"]["found"] is False
    assert opener.requests[0]["path"].endswith(f"/v1/deliveries/{UUID_A}")
    assert sink.writes == []


def test_everyday_writes_send_nothing_in_test_mode(make_factory) -> None:
    opener = FakeOpener()
    response, _ = run(
        make_factory,
        opener,
        "create_sales_invoice",
        {"client_code": "1", "department_code": "D1", "lines": _lines(2)},
        test_mode=True,
    )
    assert response["ok"] is True
    assert response["result"]["created"] is False
    assert opener.requests == []
