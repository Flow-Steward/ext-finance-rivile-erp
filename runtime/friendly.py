"""Everyday operations: plain inputs, several Rivile ERP calls in one step.

Each operation takes the inputs an operator thinks in (a client code, a product,
invoice lines with quantity and price) and makes the documented Rivile ERP calls
for them. Rules every operation follows:

* lookup values are allowlisted before they go into a filter, and filters only
  name fields Rivile documents for that list;
* money and quantities are ``Decimal`` from input to output; totals are returned
  as exact decimal text;
* Rivile's JSON field names are matched case-insensitively;
* a composite write that fails part-way reports exactly what it already created
  and is not retried (``timeout_unknown``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import budget, errors
from .errors import ExtensionError
from .fields import field
from .transport import DeadlineReached, encode_path

MAX_TEXT = 150
#: Rivile creates a document with at most 100 lines in one request. More lines
#: would need one request each, and those cannot be shown to fit the step's time
#: limit (each may take up to Rivile's 5 minutes), so a step takes at most 100.
MAX_LINES = 100
MONEY = Decimal("0.01")
PRICE = Decimal("0.0001")
QUANTITY = Decimal("0.0001")
#: Bounds that keep every value exact as a JSON number: at most 12 significant
#: digits, which a binary float holds and prints back unchanged.
MAX_AMOUNT = Decimal("9999999999.99")
MAX_QUANTITY = Decimal("99999999.9999")

#: Lists that document updatedAt as a filter field (same table as the contract).
CHANGE_LISTS: dict[str, str] = {
    "clients": "/v1/clients",
    "contacts": "/v1/contacts",
    "products": "/v1/products",
    "sale_prices": "/v1/sale-prices",
    "sale_invoices": "/v1/sale-invoices",
    "purchase_invoices": "/v1/purchase-invoices",
    "sale_orders": "/v1/sale-orders",
    "purchase_orders": "/v1/purchase-orders",
    "deliveries": "/v1/deliveries",
    "inventory_movements": "/v1/inventory-movements",
    "inventory_adjustments": "/v1/inventory-adjustments",
    "manufactures": "/v1/manufactures",
    "lots": "/v1/lots",
    "gift_cards": "/v1/gift-cards",
    "employees": "/v1/employees",
    "timesheet_schedules": "/v1/timesheet-schedules",
}
#: Records whose GET-by-id answer lists attachments[].
DOCUMENT_TYPES: dict[str, str] = {
    "sale_invoice": "/v1/sale-invoices/{id}",
    "purchase_invoice": "/v1/purchase-invoices/{id}",
    "sale_order": "/v1/sale-orders/{id}",
    "purchase_order": "/v1/purchase-orders/{id}",
    "delivery": "/v1/deliveries/{deliveryId}",
    "payment": "/v1/payments/{id}",
    "inventory_movement": "/v1/inventory-movements/{id}",
    "inventory_adjustment": "/v1/inventory-adjustments/{id}",
    "manufacture": "/v1/manufactures/{id}",
    "client": "/v1/clients/{id}",
    "contact": "/v1/contacts/{id}",
    "product": "/v1/products/{id}",
}
INVOICE_PATHS = {"sales": "/v1/sale-invoices", "purchase": "/v1/purchase-invoices"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SINCE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z)?$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
#: Codes that go into a filter. ASCII only, no quotes or control characters.
_CODE_RE = re.compile(r"^[A-Za-z0-9 ._/-]{1,50}$")
_NUMBER_RE = re.compile(r"^-?[0-9]{0,15}([.,][0-9]{1,6})?$")


# ---------------------------------------------------------------------------
# Inputs


def _invalid(message: str) -> ExtensionError:
    return ExtensionError(
        errors.INVALID_PAYLOAD,
        message,
        definitely_no_external_effect=True,
        external_effect_status="failed",
    )


def _allowed(inputs: Mapping[str, Any], names: set[str]) -> None:
    unknown = set(inputs) - names - {"connection_ref"}
    if unknown:
        raise _invalid(f"Unknown input: {', '.join(sorted(unknown))}")


def _text(
    inputs: Mapping[str, Any], name: str, *, required: bool = False, limit: int = MAX_TEXT
) -> str:
    value = inputs.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise _invalid(f"{name} is required")
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _invalid(f"{name} must be text")
    text = str(value).strip()
    if len(text) > limit or not text.isprintable():
        raise _invalid(f"{name} must be at most {limit} printable characters")
    return text


def code(inputs: Mapping[str, Any], name: str, *, required: bool = False) -> str:
    """A Rivile code: letters, digits, space and . _ / - only (it may go into a filter)."""
    text = _text(inputs, name, required=required, limit=50)
    if text and not _CODE_RE.fullmatch(text):
        raise _invalid(f"{name} may contain only letters, digits, spaces and . _ / -")
    return text


def _uuid(inputs: Mapping[str, Any], name: str, *, required: bool = False) -> str:
    text = _text(inputs, name, required=required, limit=36)
    if text and not _UUID_RE.fullmatch(text):
        raise _invalid(f"{name} must be a Rivile ERP id (UUID)")
    return text


def decimal_input(
    value: Any,
    name: str,
    step: Decimal,
    *,
    minimum: Decimal | None = None,
    maximum: Decimal = MAX_AMOUNT,
) -> Decimal:
    if isinstance(value, bool):
        raise _invalid(f"{name} must be a number")
    if isinstance(value, (int, float)):
        text = repr(value) if isinstance(value, float) else str(value)
    elif isinstance(value, str) and value.strip() and _NUMBER_RE.fullmatch(value.strip()):
        text = value.strip().replace(",", ".")
    else:
        raise _invalid(f"{name} must be a number")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise _invalid(f"{name} must be a number") from exc
    if not number.is_finite():
        raise _invalid(f"{name} must be a number")
    number = number.quantize(step, rounding=ROUND_HALF_UP)
    if minimum is not None and number < minimum:
        raise _invalid(f"{name} must be at least {minimum}")
    if number > maximum:
        raise _invalid(f"{name} must be at most {maximum}")
    return number


def wire(number: Decimal) -> int | float:
    """A JSON number with exactly the rounded value."""
    return int(number) if number == number.to_integral_value() else float(number)


def _date(inputs: Mapping[str, Any], name: str) -> str:
    value = inputs.get(name)
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value.strip()):
        raise _invalid(f"{name} must be a date YYYY-MM-DD")
    try:
        date.fromisoformat(value.strip())
    except ValueError as exc:
        raise _invalid(f"{name} is not a valid date") from exc
    return value.strip()


def _bool(inputs: Mapping[str, Any], name: str, default: bool) -> bool:
    value = inputs.get(name)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise _invalid(f"{name} must be true or false")
    return value


def _choice(inputs: Mapping[str, Any], name: str, values: tuple[Any, ...], default: Any) -> Any:
    value = inputs.get(name, default)
    if value not in values or isinstance(value, bool):
        raise _invalid(f"{name} must be one of: {', '.join(str(v) for v in values)}")
    return value


def _max_pages(inputs: Mapping[str, Any]) -> int:
    value = inputs.get("max_pages", 10)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise _invalid("max_pages must be a whole number from 1 to 100")
    return value


# ---------------------------------------------------------------------------
# Reading Rivile answers


def text_of(record: Any, name: str) -> str:
    value = field(record, name)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def decimal_of(record: Any, name: str) -> Decimal | None:
    """A Rivile number as an exact Decimal (JSON floats via their shortest repr)."""
    value = field(record, name)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", value.strip()):
        return Decimal(value.strip())
    return None


def decimal_text(number: Decimal | None, step: Decimal = MONEY) -> str | None:
    return None if number is None else str(number.quantize(step, rounding=ROUND_HALF_UP))


def _same(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


# ---------------------------------------------------------------------------
# Calls


class Api:
    """The Rivile ERP calls an everyday operation may make, bound to one invocation."""

    def __init__(self, context: Any) -> None:
        self._context = context

    def list(
        self,
        path: str,
        conditions: list[dict[str, Any]],
        *,
        max_pages: int = 1,
        size: int = 100,
        first_page: int = 0,
        meter: budget.Meter | None = None,
    ) -> dict[str, Any]:
        from . import catalog, operations

        endpoint = catalog.LISTS_BY_PATH[path]
        return operations.read_pages(
            self._context,
            path,
            [],
            filter_json=operations.build_filter(conditions or None, endpoint.filter_fields),
            first_page=first_page,
            size=size,
            max_pages=max_pages,
            meter=meter,
        )

    def get(self, path: str) -> Any:
        reply, _took = self._context.call("GET", path, mutating=False)
        return reply.data

    def write(self, method: str, path: str, body: Any) -> Any:
        reply, _took = self._context.call(method, path, body=body, mutating=True)
        return reply.data

    def download(self, file_id: str) -> tuple[str, int]:
        from . import catalog, operations

        handle, size, _ct, _status, _ms = operations.download_file(
            self._context, file_id, binding_key=catalog.FRIENDLY_DOWNLOAD_BINDING
        )
        return handle, size


class Progress:
    """The writes a composite step has completed, for an honest failure message."""

    def __init__(self) -> None:
        self.done: list[str] = []

    def add(self, text: str) -> None:
        self.done.append(text)

    def fail(self, exc: ExtensionError, step: str) -> ExtensionError:
        if not self.done:
            return exc
        message = (
            f"{step} failed: {exc.message}. Already done in Rivile ERP: {'; '.join(self.done)}. "
            "Check Rivile ERP before running this step again."
        )
        # The failing call's own code stays (validation, timeout…); what changes is
        # the effect: earlier writes happened, so the step may not be rerun blindly.
        return ExtensionError(
            exc.code,
            message,
            failure_class="provider",
            retryable=False,
            definitely_no_external_effect=False,
            external_effect_status="timeout_unknown",
            http_status=exc.http_status,
            data_errors=exc.data_errors,
        )

    def guard(self, step: str, run: Callable[[], Any]) -> Any:
        """Run one part of a composite step; a failure after a write reports the write."""
        try:
            return run()
        except ExtensionError as exc:
            raise self.fail(exc, step) from exc
        except DeadlineReached as exc:
            if not self.done:
                raise
            raise self.fail(
                ExtensionError(errors.TIMEOUT_UNKNOWN, "the step ran out of time"), step
            ) from exc


# ---------------------------------------------------------------------------
# Clients

CLIENT_LOOKUP = (("client_code", "code"), ("reg_code", "regCode"), ("vat_number", "vatNumber"))
CLIENT_INPUTS = {
    "client_code",
    "reg_code",
    "vat_number",
    "name",
    "client_type",
    "address",
    "email",
    "phone",
    "is_customer",
    "is_supplier",
}


def _client_identifiers(inputs: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    found = []
    for name, rivile_field in CLIENT_LOOKUP:
        value = code(inputs, name)
        if value:
            found.append((name, rivile_field, value))
    return found


def client_body(
    inputs: Mapping[str, Any], *, customer: bool, supplier: bool, require_name: bool
) -> dict[str, Any]:
    name = _text(inputs, "name", required=require_name, limit=MAX_TEXT)
    body: dict[str, Any] = {
        "name": name,
        "typeId": _choice(inputs, "client_type", (0, 1), 0),
        "isCustomer": _bool(inputs, "is_customer", customer),
        "isSupplier": _bool(inputs, "is_supplier", supplier),
    }
    for input_name, rivile_field in (("reg_code", "regCode"), ("vat_number", "vatNumber")):
        value = code(inputs, input_name)
        if value:
            body[rivile_field] = value
    for input_name in ("address", "email", "phone"):
        value = _text(inputs, input_name, limit=MAX_TEXT)
        if value:
            body[input_name] = value
    return body


def _find_client(api: Api, inputs: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    identifiers = _client_identifiers(inputs)
    for name, rivile_field, value in identifiers:
        read = api.list(
            "/v1/clients", [{"field": rivile_field, "operation": "EQUAL", "value": value}], size=2
        )
        rows = [r for r in read["records"] if isinstance(r, Mapping)]
        if len(rows) > 1:
            raise _invalid(f"Several Rivile ERP clients have {name} {value}; give client_code")
        if rows:
            record = dict(rows[0])
            for other, other_field, other_value in identifiers:
                found = text_of(record, other_field)
                if other != name and found and not _same(found, other_value):
                    raise _invalid(
                        f"The client found by {name} has {other} {found}, not {other_value}; "
                        "nothing was created"
                    )
            return record, name
    return None, ""


def find_or_create_client(
    api: Api,
    inputs: Mapping[str, Any],
    progress: Progress,
    *,
    customer: bool = True,
    supplier: bool = False,
) -> dict[str, Any]:
    if not _client_identifiers(inputs):
        raise _invalid("Give client_code, reg_code or vat_number to look the client up")
    record, matched_by = _find_client(api, inputs)
    client_code = code(inputs, "client_code")
    if record is None and client_code:
        # A code names an existing client: a typo must not create a second one.
        raise _invalid(
            f"No Rivile ERP client has client_code {client_code}; nothing was created. To "
            "find or create a client, leave client_code empty and give reg_code or vat_number."
        )
    if record is not None:
        return {
            "client_id": text_of(record, "id") or None,
            "client_code": text_of(record, "code") or None,
            "created": False,
            "matched_by": matched_by,
            "record": record,
        }
    body = client_body(inputs, customer=customer, supplier=supplier, require_name=True)
    created = progress.guard("Creating the client", lambda: api.write("POST", "/v1/clients", body))
    created = created if isinstance(created, Mapping) else {}
    new_code = text_of(created, "code") or None
    progress.add(f"client {new_code or text_of(created, 'id')} created")
    return {
        "client_id": text_of(created, "id") or None,
        "client_code": new_code,
        "created": True,
        "matched_by": None,
        "record": dict(created) or None,
    }


# ---------------------------------------------------------------------------
# Invoices

INVOICE_INPUTS = CLIENT_INPUTS | {
    "number",
    "date",
    "document_date",
    "department_code",
    "currency_code",
    "prices_include_tax",
    "notes",
    "lines",
    "post",
}
_LINE_KEYS = {
    "item_code",
    "unit",
    "quantity",
    "price",
    "discount_percent",
    "department_code",
    "notes",
}


def invoice_lines(inputs: Mapping[str, Any], department: str) -> list[dict[str, Any]]:
    raw = inputs.get("lines")
    if not isinstance(raw, list) or not raw:
        raise _invalid("lines must be a list with at least one line")
    if len(raw) > MAX_LINES:
        raise _invalid(
            f"An invoice step takes at most {MAX_LINES} lines (Rivile's limit for one create "
            "request); add further lines with the Advanced create-line step"
        )
    lines = []
    for index, item in enumerate(raw):
        where = f"lines[{index}]"
        if not isinstance(item, Mapping) or set(item) - _LINE_KEYS:
            raise _invalid(f"{where} may have only: {', '.join(sorted(_LINE_KEYS))}")
        line: dict[str, Any] = {
            "itemCode": code(item, "item_code", required=True),
            "qtyAlt": wire(
                decimal_input(
                    item.get("quantity"),
                    f"{where}.quantity",
                    QUANTITY,
                    minimum=QUANTITY,
                    maximum=MAX_QUANTITY,
                )
            ),
            "departmentCode": code(item, "department_code") or department,
        }
        unit = code(item, "unit")
        if unit:
            line["uomAltCode"] = unit
        if item.get("price") is not None:
            line["price"] = wire(
                decimal_input(
                    item["price"], f"{where}.price", PRICE, minimum=Decimal(0), maximum=MAX_QUANTITY
                )
            )
        if item.get("discount_percent") is not None:
            line["discountPerc"] = wire(
                decimal_input(
                    item["discount_percent"],
                    f"{where}.discount_percent",
                    MONEY,
                    minimum=Decimal(0),
                    maximum=Decimal(100),
                )
            )
        notes = _text(item, "notes", limit=500)
        if notes:
            line["notes"] = notes
        lines.append(line)
    return lines


def invoice_header(inputs: Mapping[str, Any]) -> dict[str, Any]:
    department = code(inputs, "department_code", required=True)
    header: dict[str, Any] = {"departmentCode": department}
    number = _text(inputs, "number", limit=50)
    if number:
        header["documentNo"] = number
    op_date = _date(inputs, "date")
    if op_date:
        header["opDate"] = op_date
    doc_date = _date(inputs, "document_date") or op_date
    if doc_date:
        header["docDate"] = doc_date
    currency = code(inputs, "currency_code")
    if currency:
        header["currencyCode"] = currency
    if inputs.get("prices_include_tax") is not None:
        header["isTaxIncluded"] = _bool(inputs, "prices_include_tax", False)
    notes = _text(inputs, "notes", limit=1000)
    if notes:
        header["notes"] = notes
    return header


def _invoice_result(
    record: Any,
    *,
    created: bool,
    client: dict[str, Any],
    lines: int,
    posted: bool | None,
    post_note: str | None = None,
) -> dict[str, Any]:
    record = dict(record) if isinstance(record, Mapping) else None
    status = field(record, "statusId")
    return {
        "document_id": text_of(record, "id") or None,
        "number": text_of(record, "documentNo") or None,
        "created": created,
        "client_code": client.get("client_code"),
        "client_created": bool(client.get("created")),
        "lines_created": lines,
        "total_amount": decimal_text(decimal_of(record, "totalAmount")),
        "total_tax": decimal_text(decimal_of(record, "totalTaxAmount")),
        "total_with_tax": decimal_text(decimal_of(record, "totalAmountWithTax")),
        "status_id": status if isinstance(status, int) and not isinstance(status, bool) else None,
        "posted": posted,
        "post_note": post_note,
        "record": record,
    }


def create_invoice(
    api: Api, inputs: Mapping[str, Any], progress: Progress, *, kind: str
) -> dict[str, Any]:
    path = INVOICE_PATHS[kind]
    noun = "sales invoice" if kind == "sales" else "purchase invoice"
    header = invoice_header(inputs)
    lines = invoice_lines(inputs, header["departmentCode"])
    post = _bool(inputs, "post", False)
    client = find_or_create_client(
        api, inputs, progress, customer=kind == "sales", supplier=kind == "purchase"
    )
    client_code = client.get("client_code")
    if not client_code:
        raise progress.fail(
            ExtensionError(errors.UPSTREAM_FAILURE, "Rivile ERP returned no client code"),
            "Creating the invoice",
        )
    if header.get("documentNo"):
        existing = progress.guard(
            "Looking up the invoice number",
            lambda: api.list(
                path,
                [
                    {"field": "documentNo", "operation": "EQUAL", "value": header["documentNo"]},
                    {"field": "clientCode", "operation": "EQUAL", "value": client_code},
                ],
                size=2,
            ),
        )
        if existing["records"]:
            return _existing_invoice(
                api, existing["records"][0], path, noun, client, post=post, progress=progress
            )
    body = {**header, "clientCode": client_code, "lines": lines}
    record = progress.guard(f"Creating the {noun}", lambda: api.write("POST", path, body))
    document_id = text_of(record, "id")
    if not document_id:
        raise progress.fail(
            ExtensionError(
                errors.TIMEOUT_UNKNOWN, f"Rivile ERP saved the {noun} but returned no id"
            ),
            f"Creating the {noun}",
        )
    progress.add(
        f"{noun} {text_of(record, 'documentNo') or document_id} created with {len(lines)} lines"
    )
    posted = False
    if post:
        post_path = encode_path(path + "/{id}/post", {"id": document_id})
        progress.guard(f"Posting the {noun}", lambda: api.write("PATCH", post_path, None))
        posted = True
        progress.add(f"{noun} posted")
        # Posting can change the document; a failed re-read keeps the create answer.
        try:
            fresh = api.get(encode_path(path + "/{id}", {"id": document_id}))
            if isinstance(fresh, Mapping):
                record = fresh
        except (ExtensionError, DeadlineReached):
            pass
    return _invoice_result(record, created=True, client=client, lines=len(lines), posted=posted)


def _existing_invoice(
    api: Api,
    record: Any,
    path: str,
    noun: str,
    client: dict[str, Any],
    *,
    post: bool,
    progress: Progress,
) -> dict[str, Any]:
    """An invoice with this number already exists: return it, and post it if asked.

    Rivile does not document which statusId means "posted", so the state is not
    guessed: ``posted`` is null unless this step posted it, and a refusal to post
    (for example because it already is) is reported in ``post_note``.
    """
    document_id = text_of(record, "id")
    if not post or not document_id:
        return _invoice_result(record, created=False, client=client, lines=0, posted=None)
    post_path = encode_path(path + "/{id}/post", {"id": document_id})
    try:
        progress.guard(f"Posting the existing {noun}", lambda: api.write("PATCH", post_path, None))
    except ExtensionError as exc:
        if exc.code != errors.UPSTREAM_VALIDATION_FAILED or progress.done:
            raise
        return _invoice_result(
            record, created=False, client=client, lines=0, posted=None, post_note=exc.message
        )
    return _invoice_result(record, created=False, client=client, lines=0, posted=True)


# ---------------------------------------------------------------------------
# Payments

PAYMENT_INPUTS = {
    "direction",
    "client_code",
    "amount",
    "currency_code",
    "date",
    "account_code",
    "payment_method_code",
    "document_no",
    "purpose",
    "invoice_id",
    "invoice_type",
    "post",
}


def payment_body(inputs: Mapping[str, Any]) -> tuple[dict[str, Any], str, int, bool]:
    _allowed(inputs, PAYMENT_INPUTS)
    direction = _choice(inputs, "direction", ("received", "sent"), None)
    body: dict[str, Any] = {
        "typeId": 5 if direction == "received" else 4,
        "clientCode": code(inputs, "client_code", required=True),
        "amountCur": wire(
            decimal_input(
                inputs.get("amount"), "amount", MONEY, minimum=Decimal("0.01"), maximum=MAX_AMOUNT
            )
        ),
    }
    for input_name, rivile_field in (
        ("currency_code", "currencyCode"),
        ("account_code", "accountCode"),
        ("payment_method_code", "paymentMethodCode"),
    ):
        value = code(inputs, input_name)
        if value:
            body[rivile_field] = value
    op_date = _date(inputs, "date")
    if op_date:
        body["opDate"] = op_date
    for input_name, rivile_field, limit in (
        ("document_no", "documentNo", 50),
        ("purpose", "purposeText", 500),
    ):
        value = _text(inputs, input_name, limit=limit)
        if value:
            body[rivile_field] = value
    invoice_id = _uuid(inputs, "invoice_id")
    default_type = "sale_invoice" if direction == "received" else "purchase_invoice"
    invoice_type = _choice(
        inputs, "invoice_type", ("sale_invoice", "purchase_invoice"), default_type
    )
    module = 0 if invoice_type == "sale_invoice" else 1
    return body, invoice_id, module, _bool(inputs, "post", False)


def register_payment(api: Api, inputs: Mapping[str, Any], progress: Progress) -> dict[str, Any]:
    body, invoice_id, module, post = payment_body(inputs)
    record = progress.guard("Creating the payment", lambda: api.write("POST", "/v1/payments", body))
    payment_id = text_of(record, "id")
    if not payment_id:
        raise progress.fail(
            ExtensionError(
                errors.TIMEOUT_UNKNOWN, "Rivile ERP saved the payment but returned no id"
            ),
            "Creating the payment",
        )
    progress.add(f"payment {text_of(record, 'documentNo') or payment_id} created")
    linked = False
    if invoice_id:
        link_path = encode_path("/v1/payments/{id}/link-payment", {"id": payment_id})
        progress.guard(
            "Linking the payment",
            lambda: api.write("PATCH", link_path, {"refId": invoice_id, "refModuleId": module}),
        )
        linked = True
        progress.add(f"payment linked to invoice {invoice_id}")
    posted = False
    if post:
        post_path = encode_path("/v1/payments/{id}/post", {"id": payment_id})
        progress.guard("Posting the payment", lambda: api.write("PATCH", post_path, None))
        posted = True
    return {
        "payment_id": payment_id,
        "linked": linked,
        "posted": posted,
        "record": dict(record) if isinstance(record, Mapping) else None,
    }


# ---------------------------------------------------------------------------
# Products

PRODUCT_INPUTS = {"product_code", "barcode", "name", "product_type", "unit", "description"}


def product_body(inputs: Mapping[str, Any], *, require_name: bool) -> dict[str, Any]:
    _allowed(inputs, PRODUCT_INPUTS)
    body: dict[str, Any] = {
        "name": _text(inputs, "name", required=require_name),
        "productTypeId": _choice(inputs, "product_type", (1, 2), 1),
        # 1 — Single: a plain product or service, not a set (Mixed) or tare.
        "bomTypeId": 1,
    }
    product_code = code(inputs, "product_code")
    if product_code:
        body["code"] = product_code
    description = _text(inputs, "description", limit=1000)
    if description:
        body["description"] = description
    unit = code(inputs, "unit")
    barcode = code(inputs, "barcode")
    if unit or barcode:
        uom: dict[str, Any] = {}
        if unit:
            uom["uomCode"] = unit
        if barcode:
            uom["mainBarcode"] = barcode
        body["productUnitOfMeasure"] = uom
    return body


def find_or_create_product(
    api: Api, inputs: Mapping[str, Any], progress: Progress
) -> dict[str, Any]:
    product_body(inputs, require_name=False)
    lookups = [
        (name, rivile_field, value)
        for name, rivile_field in (("product_code", "code"), ("barcode", "mainBarcode"))
        if (value := code(inputs, name))
    ]
    if not lookups:
        raise _invalid("Give product_code or barcode")
    for name, rivile_field, value in lookups:
        read = api.list(
            "/v1/products", [{"field": rivile_field, "operation": "EQUAL", "value": value}], size=2
        )
        rows = [r for r in read["records"] if isinstance(r, Mapping)]
        if len(rows) > 1:
            raise _invalid(f"Several Rivile ERP products have {name} {value}")
        if rows:
            record = dict(rows[0])
            for other, other_field, other_value in lookups:
                found = text_of(record, other_field)
                if other != name and found and not _same(found, other_value):
                    raise _invalid(
                        f"The product found by {name} has {other} {found}, not {other_value}; "
                        "nothing was created"
                    )
            return {
                "product_id": text_of(record, "id") or None,
                "product_code": text_of(record, "code") or None,
                "created": False,
                "matched_by": name,
                "record": record,
            }
    body = product_body(inputs, require_name=True)
    created = progress.guard(
        "Creating the product", lambda: api.write("POST", "/v1/products", body)
    )
    created = created if isinstance(created, Mapping) else {}
    progress.add("product created")
    return {
        "product_id": text_of(created, "id") or None,
        "product_code": text_of(created, "code") or body.get("code") or None,
        "created": True,
        "matched_by": None,
        "record": dict(created) or None,
    }


# ---------------------------------------------------------------------------
# Reads


def _conditions(
    inputs: Mapping[str, Any], pairs: tuple[tuple[str, str], ...]
) -> list[dict[str, Any]]:
    return [
        {"field": rivile_field, "operation": "EQUAL", "value": value}
        for name, rivile_field in pairs
        if (value := code(inputs, name))
    ]


def _fit(read: dict[str, Any], build: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    from . import operations

    return operations.fit_pages(read, build)


def stock_levels(api: Api, inputs: Mapping[str, Any]) -> dict[str, Any]:
    _allowed(inputs, {"product_code", "department_code", "max_pages"})
    read = api.list(
        "/v1/inventory-stocks",
        _conditions(
            inputs, (("product_code", "productCode"), ("department_code", "departmentCode"))
        ),
        max_pages=_max_pages(inputs),
        meter=budget.Meter(),
    )

    def build(done: dict[str, Any]) -> dict[str, Any]:
        items = []
        # Quantities only add up for the same product in the same unit.
        totals: dict[tuple[str, str], Decimal] = {}
        for row in done["records"]:
            available = decimal_of(row, "qtyAvailable")
            key = (text_of(row, "productCode"), text_of(row, "uomCode"))
            totals[key] = totals.get(key, Decimal(0)) + (available or Decimal(0))
            items.append(
                {
                    "product_code": key[0],
                    "department_code": text_of(row, "departmentCode"),
                    "unit": key[1],
                    "available": decimal_text(available, QUANTITY),
                    "in_warehouse": decimal_text(decimal_of(row, "qtyWarehouse"), QUANTITY),
                    "reserved": decimal_text(decimal_of(row, "qtyReserved"), QUANTITY),
                    "lot_code": text_of(row, "lotCode") or None,
                }
            )
        return {
            "items": items,
            "count": len(items),
            "totals": [
                {"product_code": product, "unit": unit, "available": decimal_text(total, QUANTITY)}
                for (product, unit), total in totals.items()
            ],
            "has_more": done["has_more"],
        }

    return _fit(read, build)


def product_prices(api: Api, inputs: Mapping[str, Any]) -> dict[str, Any]:
    _allowed(inputs, {"product_code", "price_category_code", "currency_code", "department_code"})
    code(inputs, "product_code", required=True)
    read = api.list(
        "/v1/sale-prices",
        _conditions(
            inputs,
            (
                ("product_code", "productCode"),
                ("price_category_code", "priceCategoryCode"),
                ("currency_code", "currencyCode"),
                ("department_code", "departmentCode"),
            ),
        ),
        max_pages=5,
        meter=budget.Meter(),
    )

    def build(done: dict[str, Any]) -> dict[str, Any]:
        prices = [
            {
                "price_excluding_tax": decimal_text(decimal_of(row, "priceExcludingTax"), PRICE),
                "price_including_tax": decimal_text(decimal_of(row, "priceIncludingTax"), PRICE),
                "valid_from": text_of(row, "validFrom") or None,
                "valid_to": text_of(row, "validTo") or None,
                "currency": text_of(row, "currencyCode") or None,
                "category": text_of(row, "priceCategoryCode") or None,
                "unit": text_of(row, "productUnitOfMeasureCode") or None,
                "department_code": text_of(row, "departmentCode") or None,
            }
            for row in done["records"]
        ]
        return {"prices": prices, "count": len(prices), "has_more": done["has_more"]}

    return _fit(read, build)


def _since(inputs: Mapping[str, Any]) -> str:
    since = _text(inputs, "since", required=True, limit=30)
    if not _SINCE_RE.fullmatch(since):
        raise _invalid("since must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS(.SSS)Z")
    try:
        date.fromisoformat(since[:10])
    except ValueError as exc:
        raise _invalid("since is not a valid date") from exc
    return since


def _page(inputs: Mapping[str, Any]) -> int:
    value = inputs.get("page", 0)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000000:
        raise _invalid("page must be a whole number from 0")
    return value


def changes_since(api: Api, inputs: Mapping[str, Any]) -> dict[str, Any]:
    _allowed(inputs, {"entity", "since", "page", "max_pages"})
    path = CHANGE_LISTS.get(_text(inputs, "entity", required=True, limit=40))
    if path is None:
        raise _invalid(f"entity must be one of: {', '.join(sorted(CHANGE_LISTS))}")
    read = api.list(
        path,
        [{"field": "updatedAt", "operation": "GREATER_THAN", "value": _since(inputs)}],
        max_pages=_max_pages(inputs),
        first_page=_page(inputs),
        meter=budget.Meter(),
    )

    def build(done: dict[str, Any]) -> dict[str, Any]:
        return {
            "records": done["records"],
            "count": len(done["records"]),
            "has_more": done["has_more"],
            "next_page": done["next_page"],
        }

    return _fit(read, build)


def client_debt(api: Api, inputs: Mapping[str, Any]) -> dict[str, Any]:
    _allowed(inputs, {"client_code", "max_pages"})
    client_code = code(inputs, "client_code", required=True)
    read = api.list(
        "/v1/pr-registries",
        [{"field": "clientCode", "operation": "EQUAL", "value": client_code}],
        max_pages=_max_pages(inputs),
        meter=budget.Meter(),
    )

    def build(done: dict[str, Any]) -> dict[str, Any]:
        total = overdue = Decimal(0)
        by_type: dict[tuple[int | None, str], dict[str, Any]] = {}
        documents = []
        for row in done["records"]:
            due = decimal_of(row, "totalBaseDue") or Decimal(0)
            days = field(row, "overDueDays")
            days = days if isinstance(days, int) and not isinstance(days, bool) else None
            type_id = field(row, "typeId")
            type_id = (
                type_id if isinstance(type_id, int) and not isinstance(type_id, bool) else None
            )
            group = by_type.setdefault(
                (type_id, text_of(row, "typeName")),
                {"due": Decimal(0), "overdue": Decimal(0), "count": 0},
            )
            group["due"] += due
            group["count"] += 1
            total += due
            if days is not None and days > 0:
                overdue += due
                group["overdue"] += due
            documents.append(
                {
                    "document_no": text_of(row, "documentNo") or None,
                    "type_id": type_id,
                    "type_name": text_of(row, "typeName") or None,
                    "date": text_of(row, "date") or None,
                    "due_date": text_of(row, "dueDate") or None,
                    "due": decimal_text(due),
                    "overdue_days": days,
                    "currency": text_of(row, "currencyCode") or None,
                    "due_in_currency": decimal_text(decimal_of(row, "totalCurDue")),
                }
            )
        return {
            "total_due": decimal_text(total),
            "overdue": decimal_text(overdue),
            "totals_by_type": [
                {
                    "type_id": type_id,
                    "type_name": type_name or None,
                    "total_due": decimal_text(group["due"]),
                    "overdue": decimal_text(group["overdue"]),
                    "count": group["count"],
                }
                for (type_id, type_name), group in by_type.items()
            ],
            "documents": documents,
            "count": len(documents),
            "complete": not done["has_more"],
            "has_more": done["has_more"],
        }

    return _fit(read, build)


def download_document_file(api: Api, inputs: Mapping[str, Any]) -> dict[str, Any]:
    file_id, document_path, file_name = _download_target(inputs)
    original = None
    if not file_id:
        document = api.get(document_path)
        attachments = field(document, "attachments")
        files = [
            item
            for item in (attachments if isinstance(attachments, list) else [])
            if isinstance(item, Mapping)
            and text_of(item, "typeId").upper() != "LINK"
            and _UUID_RE.fullmatch(text_of(item, "id"))
        ]
        if file_name:
            files = [item for item in files if _same(_attachment_name(item), file_name)]
        if not files:
            return {
                "found": False,
                "document_file": None,
                "file_id": None,
                "original_filename": None,
                "size_bytes": None,
            }
        file_id = text_of(files[0], "id")
        original = _attachment_name(files[0]) or None
    handle, size = api.download(file_id)
    return {
        "found": True,
        "document_file": handle,
        "file_id": file_id,
        "original_filename": original,
        "size_bytes": size,
    }


def _attachment_name(item: Mapping[str, Any]) -> str:
    name = text_of(item, "name")
    extension = text_of(item, "extension").lstrip(".")
    if extension and not name.lower().endswith("." + extension.lower()):
        return f"{name}.{extension}" if name else ""
    return name


def _download_target(inputs: Mapping[str, Any]) -> tuple[str, str, str]:
    _allowed(inputs, {"file_id", "document_type", "document_id", "file_name"})
    file_id = _uuid(inputs, "file_id")
    document_type = _text(inputs, "document_type", limit=40)
    document_id = _uuid(inputs, "document_id")
    file_name = _text(inputs, "file_name", limit=255)
    if file_id:
        if document_type or document_id:
            raise _invalid("Give file_id, or document_type and document_id — not both")
        return file_id, "", file_name
    template = DOCUMENT_TYPES.get(document_type)
    if template is None or not document_id:
        raise _invalid(
            "Give file_id, or document_type (one of: "
            f"{', '.join(sorted(DOCUMENT_TYPES))}) and document_id"
        )
    placeholder = "deliveryId" if "{deliveryId}" in template else "id"
    return "", encode_path(template, {placeholder: document_id}), file_name


# ---------------------------------------------------------------------------
# Dispatch, validation and test-mode results


def run(api: Api, operation_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    progress = Progress()
    if operation_id == "find_or_create_client":
        _allowed(inputs, CLIENT_INPUTS)
        return find_or_create_client(
            api,
            inputs,
            progress,
            customer=_bool(inputs, "is_customer", True),
            supplier=_bool(inputs, "is_supplier", False),
        )
    if operation_id == "create_sales_invoice":
        return create_invoice(api, inputs, progress, kind="sales")
    if operation_id == "create_purchase_invoice":
        return create_invoice(api, inputs, progress, kind="purchase")
    if operation_id == "register_payment":
        return register_payment(api, inputs, progress)
    if operation_id == "find_or_create_product":
        return find_or_create_product(api, inputs, progress)
    if operation_id == "stock_levels":
        return stock_levels(api, inputs)
    if operation_id == "product_prices":
        return product_prices(api, inputs)
    if operation_id == "changes_since":
        return changes_since(api, inputs)
    if operation_id == "client_debt":
        return client_debt(api, inputs)
    return download_document_file(api, inputs)


def validate(operation_id: str, inputs: Mapping[str, Any]) -> None:
    """Check an everyday operation's inputs without calling Rivile ERP."""
    inputs = {k: v for k, v in inputs.items() if k != "connection_ref"}
    if operation_id == "find_or_create_client":
        _allowed(inputs, CLIENT_INPUTS)
        if not _client_identifiers(inputs):
            raise _invalid("Give client_code, reg_code or vat_number to look the client up")
        client_body(inputs, customer=True, supplier=False, require_name=False)
    elif operation_id in {"create_sales_invoice", "create_purchase_invoice"}:
        _allowed(inputs, INVOICE_INPUTS)
        header = invoice_header(inputs)
        invoice_lines(inputs, header["departmentCode"])
        _bool(inputs, "post", False)
        if not _client_identifiers(inputs):
            raise _invalid(
                "Give client_code, or reg_code / vat_number to find or create the client"
            )
        client_body(inputs, customer=True, supplier=False, require_name=False)
    elif operation_id == "register_payment":
        payment_body(inputs)
    elif operation_id == "find_or_create_product":
        product_body(inputs, require_name=False)
        if not code(inputs, "product_code") and not code(inputs, "barcode"):
            raise _invalid("Give product_code or barcode")
    elif operation_id == "download_document_file":
        _download_target(inputs)
    elif operation_id == "stock_levels":
        _allowed(inputs, {"product_code", "department_code", "max_pages"})
    elif operation_id == "product_prices":
        _allowed(
            inputs, {"product_code", "price_category_code", "currency_code", "department_code"}
        )
        code(inputs, "product_code", required=True)
    elif operation_id == "changes_since":
        _allowed(inputs, {"entity", "since", "page", "max_pages"})
        _since(inputs)
        _page(inputs)
    elif operation_id == "client_debt":
        _allowed(inputs, {"client_code", "max_pages"})
        code(inputs, "client_code", required=True)


#: Every declared output of each everyday write, as a test run returns it:
#: nothing was sent, so nothing was found or created.
NEUTRAL_OUTPUTS: dict[str, dict[str, Any]] = {
    "find_or_create_client": {
        "client_id": None,
        "client_code": None,
        "created": False,
        "matched_by": None,
        "record": None,
    },
    "create_sales_invoice": {
        "document_id": None,
        "number": None,
        "created": False,
        "client_code": None,
        "client_created": False,
        "lines_created": 0,
        "total_amount": None,
        "total_tax": None,
        "total_with_tax": None,
        "status_id": None,
        "posted": False,
        "post_note": None,
        "record": None,
    },
    "register_payment": {"payment_id": None, "linked": False, "posted": False, "record": None},
    "find_or_create_product": {
        "product_id": None,
        "product_code": None,
        "created": False,
        "matched_by": None,
        "record": None,
    },
}
NEUTRAL_OUTPUTS["create_purchase_invoice"] = dict(NEUTRAL_OUTPUTS["create_sales_invoice"])


def neutral_result(operation_id: str) -> dict[str, Any]:
    return dict(NEUTRAL_OUTPUTS[operation_id])


__all__ = [
    "CHANGE_LISTS",
    "DOCUMENT_TYPES",
    "NEUTRAL_OUTPUTS",
    "Api",
    "Progress",
    "decimal_of",
    "field",
    "neutral_result",
    "run",
    "validate",
]
