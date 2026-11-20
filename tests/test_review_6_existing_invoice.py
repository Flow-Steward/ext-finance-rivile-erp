"""Review 2026-11-17, item 6: returning an existing invoice requires matching currency
and lines. Posting an existing invoice requires a separate action.

Anything else is a conflict naming the document found; it is never posted.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import UUID_A, UUID_B, FakeOpener, page
from test_friendly import CLIENT, TODAY, run


def _inputs(**extra: Any) -> dict[str, Any]:
    return {
        "client_code": "000005",
        "number": "S-1",
        "department_code": "D1",
        "currency_code": "EUR",
        "lines": [
            {"item_code": "P0", "quantity": "1.5", "price": "10.10"},
            {"item_code": "P1", "quantity": "2", "price": "5", "discount_percent": "10"},
        ],
        **extra,
    }


def _line(code: str, qty: Any, price: Any, **extra: Any) -> dict[str, Any]:
    return {"itemCode": code, "qtyAlt": qty, "price": price, **extra}


def _document(**changes: Any) -> dict[str, Any]:
    document = {
        "id": UUID_B,
        "documentNo": "S-1",
        "opDate": TODAY,
        "currencyCode": "EUR",
        "isCurrency": False,
        "totalAmount": 24.15,
        "lines": [_line("P1", 2, 5, discountPerc=10), _line("P0", 1.5, 10.1)],
    }
    document.update(changes)
    return document


def _listed() -> dict[str, Any]:
    return {"id": UUID_B, "documentNo": "S-1", "opDate": TODAY}


def _methods(opener: FakeOpener) -> list[str]:
    return [r["method"] for r in opener.requests]


def test_6_the_same_document_is_returned_read_only(make_factory: Any) -> None:
    opener = FakeOpener((200, page(CLIENT)), (200, page(_listed())), (200, _document()))
    response, _ = run(make_factory, opener, "create_sales_invoice", _inputs())
    assert response["ok"] is True, response
    result = response["result"]
    assert result["created"] is False and result["posted"] is None
    assert result["document_id"] == UUID_B
    assert opener.requests[2]["path"].endswith(f"/v1/sale-invoices/{UUID_B}")
    assert _methods(opener) == ["GET", "GET", "GET"]


@pytest.mark.parametrize("kind", ["sales", "purchase"])
def test_post_requires_confirmation_for_a_matching_existing_invoice(
    make_factory: Any, kind: str
) -> None:
    opener = FakeOpener(
        (200, page(CLIENT)), (200, page(_listed())), (200, _document()), (200, True)
    )
    response, _ = run(make_factory, opener, f"create_{kind}_invoice", _inputs(post=True))
    assert response["error_code"] == "conflict", response
    assert UUID_B in response["error"]
    assert response["definitely_no_external_effect"] is True
    assert _methods(opener) == ["GET", "GET", "GET"]


DIFFERENT = [
    pytest.param({"lines": [_line("P1", 2, 5, discountPerc=10), _line("P0", 3, 10.1)]}, id="qty"),
    pytest.param({"lines": [_line("P1", 2, 5, discountPerc=10), _line("P0", 1.5, 20)]}, id="price"),
    pytest.param({"lines": [_line("P1", 2, 5), _line("P0", 1.5, 10.1)]}, id="discount"),
    pytest.param(
        {"lines": [_line("P1", 2, 5, discountPerc=10), _line("P9", 1.5, 10.1)]}, id="item"
    ),
    pytest.param({"lines": [_line("P0", 1.5, 10.1)]}, id="fewer-lines"),
    pytest.param(
        {"lines": [_line("P1", 2, 5, discountPerc=10), _line("P0", 1.5, 10.1), _line("P2", 1, 1)]},
        id="more-lines",
    ),
    pytest.param({"currencyCode": "USD", "isCurrency": True}, id="currency"),
    pytest.param({"lines": None}, id="lines-not-returned"),
    pytest.param({"lines": []}, id="no-lines"),
]


@pytest.mark.parametrize("changes", DIFFERENT)
def test_6_another_document_with_the_same_identity_is_never_posted(
    make_factory: Any, changes: dict[str, Any]
) -> None:
    opener = FakeOpener(
        (200, page(CLIENT)), (200, page(_listed())), (200, _document(**changes)), (200, True)
    )
    response, _ = run(make_factory, opener, "create_sales_invoice", _inputs(post=True))
    assert response["error_code"] == "conflict", response
    assert UUID_B in response["error"]
    assert response["definitely_no_external_effect"] is True
    assert "PATCH" not in _methods(opener) and "POST" not in _methods(opener)


@pytest.mark.parametrize("changes", DIFFERENT[:2])
def test_6_another_document_is_not_returned_as_this_one(
    make_factory: Any, changes: dict[str, Any]
) -> None:
    opener = FakeOpener((200, page(CLIENT)), (200, page(_listed())), (200, _document(**changes)))
    response, _ = run(make_factory, opener, "create_sales_invoice", _inputs())
    assert response["error_code"] == "conflict", response
    assert set(_methods(opener)) == {"GET"}


def test_6_a_foreign_currency_document_is_not_one_without_a_currency(make_factory: Any) -> None:
    opener = FakeOpener(
        (200, page(CLIENT)),
        (200, page(_listed())),
        (200, _document(currencyCode="USD", isCurrency=True)),
    )
    inputs = {k: v for k, v in _inputs(post=True).items() if k != "currency_code"}
    response, _ = run(make_factory, opener, "create_sales_invoice", inputs)
    assert response["error_code"] == "conflict", response
    assert "PATCH" not in _methods(opener)


def test_6_a_purchase_invoice_is_compared_too(make_factory: Any) -> None:
    opener = FakeOpener(
        (200, page(CLIENT)),
        (200, page(_listed())),
        (200, _document(lines=[_line("P0", 9, 10.1), _line("P1", 2, 5, discountPerc=10)])),
        (200, True),
    )
    response, _ = run(make_factory, opener, "create_purchase_invoice", _inputs(post=True))
    assert response["error_code"] == "conflict", response
    assert "PATCH" not in _methods(opener)
    assert UUID_A not in response["error"]
