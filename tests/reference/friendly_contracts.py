"""Contracts of the everyday operations (runtime/friendly.py), listed first in the step picker."""

from __future__ import annotations

from typing import Any

CONNECTION = {"name": "connection_ref", "value_type": "connection_ref", "required": True}
CODE_HELP = " Letters, digits, spaces and . _ / - only."

#: Lists that document updatedAt as a filter field, by the entity name a step uses.
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
#: Records whose GET-by-id answer lists attachments[], by the name a step uses.
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
UUID_PATTERN = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def text(
    name: str, title: str, description: str, *, required: bool = False, **extra: Any
) -> dict[str, Any]:
    schema = {"type": "string", "title": title, "description": description, "maxLength": 150}
    schema.update(extra)
    return {"name": name, "value_type": "text", "required": required, "schema": schema}


def code(name: str, title: str, description: str, *, required: bool = False) -> dict[str, Any]:
    return text(
        name,
        title,
        description + CODE_HELP,
        required=required,
        maxLength=50,
        pattern="^[A-Za-z0-9 ._/-]{1,50}$",
    )


def number(name: str, title: str, description: str, *, required: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "value_type": "number",
        "required": required,
        "schema": {"type": "number", "title": title, "description": description},
    }


def flag(name: str, title: str, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "value_type": "boolean",
        "required": False,
        "schema": {"type": "boolean", "title": title, "description": description},
    }


def choice(
    name: str, title: str, description: str, values: list[Any], *, required: bool = False
) -> dict[str, Any]:
    kind = "integer" if all(isinstance(v, int) for v in values) else "string"
    return {
        "name": name,
        "value_type": "integer" if kind == "integer" else "text",
        "required": required,
        "schema": {"type": kind, "enum": values, "title": title, "description": description},
    }


def out(name: str, value_type: str, schema_type: Any, description: str = "") -> dict[str, Any]:
    if value_type == "artifact_handle":
        return {"name": name, "value_type": value_type}
    schema: dict[str, Any] = {"type": schema_type}
    if description:
        schema["description"] = description
    return {"name": name, "value_type": value_type, "schema": schema}


DATE: dict[str, Any] = {"pattern": r"^\d{4}-\d{2}-\d{2}$", "maxLength": 10}

CLIENT_LOOKUP = [
    code(
        "client_code",
        "Client code",
        "Rivile ERP client code (code), looked up first; used as the new code when creating "
        "(else Rivile numbers it). Several matches, or a match whose registration or VAT code "
        "differs from the ones given, is an error and nothing is created.",
    ),
    code("reg_code", "Registration code", "Company registration code (regCode), looked up second."),
    code(
        "vat_number",
        "VAT number",
        "VAT payer code, e.g. LT100001234567 (vatNumber), looked up last.",
    ),
]
CLIENT_NEW = [
    text("name", "Name", "Client name, needed when the client has to be created (name)."),
    choice(
        "client_type",
        "Client type",
        "0 — legal entity (JURIDICAL, default), 1 — individual (INDIVIDUAL); typeId.",
        [0, 1],
    ),
    text("address", "Address", "address."),
    text("email", "E-mail", "email."),
    text("phone", "Phone", "phone."),
    flag(
        "is_customer",
        "Customer",
        "Mark the new client as a customer (isCustomer). Default true for sales.",
    ),
    flag(
        "is_supplier",
        "Supplier",
        "Mark the new client as a supplier (isSupplier). Default true for purchases.",
    ),
]
CLIENT_OUTPUTS = [
    out("client_id", "text", ["string", "null"], "The client's id (UUID)."),
    out("client_code", "text", ["string", "null"]),
    out("created", "boolean", "boolean", "True when this step created the client."),
    out("matched_by", "text", ["string", "null"], "client_code, reg_code or vat_number."),
    out("record", "object", ["object", "null"]),
]

LINE_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["item_code", "quantity"],
    "properties": {
        "item_code": {
            "type": "string",
            "maxLength": 50,
            "description": "Product or service code (itemCode).",
        },
        "unit": {
            "type": "string",
            "maxLength": 20,
            "description": "Unit of measure code, e.g. VNT (uomAltCode). Default: the product's.",
        },
        "quantity": {
            "type": ["number", "string"],
            "description": "Quantity in that unit (qtyAlt).",
        },
        "price": {
            "type": ["number", "string"],
            "description": "Unit price (price). Default: Rivile's price list.",
        },
        "discount_percent": {"type": ["number", "string"], "description": "discountPerc."},
        "department_code": {
            "type": "string",
            "maxLength": 50,
            "description": "Department (warehouse) code for this line; default: the document's.",
        },
        "notes": {"type": "string", "maxLength": 500},
    },
}


def invoice(kind: str) -> dict[str, Any]:
    sale = kind == "sales"
    noun = "sales invoice" if sale else "purchase invoice"
    path = "/v1/sale-invoices" if sale else "/v1/purchase-invoices"
    inputs = [
        CONNECTION,
        *CLIENT_LOOKUP,
        *CLIENT_NEW,
        text(
            "number",
            "Number",
            "Document number (documentNo). With a number the step first looks for a "
            f"{noun} with this number for this client and returns it instead of creating a "
            "second one. Without it Rivile numbers the document.",
            maxLength=50,
        ),
        text(
            "date", "Date", "Operation date YYYY-MM-DD (opDate). Default: Rivile's (today).", **DATE
        ),
        text("document_date", "Document date", "docDate, YYYY-MM-DD. Default: date.", **DATE),
        code(
            "department_code",
            "Department",
            "Department (warehouse) code for every line (departmentCode).",
            required=True,
        ),
        code(
            "currency_code",
            "Currency",
            "Currency code, e.g. EUR (currencyCode). Default: the base currency.",
        ),
        flag("prices_include_tax", "Prices include VAT", "isTaxIncluded."),
        text("notes", "Notes", "notes.", maxLength=1000),
        {
            "name": "lines",
            "value_type": "array",
            "required": True,
            "schema": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1000,
                "items": LINE_ITEM,
                "title": "Lines",
                "description": (
                    "Invoice lines. Rivile takes up to 100 lines when a document is created; "
                    "further lines are added one by one (POST …/lines)."
                ),
            },
        },
        flag("post", "Post", f"Post the {noun} after it is created (PATCH …/post)."),
    ]
    outputs = [
        out("document_id", "text", ["string", "null"], "The document's id (UUID)."),
        out("number", "text", ["string", "null"], "documentNo."),
        out("created", "boolean", "boolean", "False when an existing document was returned."),
        out("client_code", "text", ["string", "null"]),
        out("client_created", "boolean", "boolean"),
        out("lines_created", "integer", "integer", "Lines saved by this step."),
        out("total_amount", "text", ["string", "null"], "totalAmount, as an exact decimal."),
        out("total_tax", "text", ["string", "null"], "totalTaxAmount."),
        out("posted", "boolean", "boolean"),
        out("record", "object", ["object", "null"]),
    ]
    return {
        "operation_id": f"create_{kind}_invoice",
        "display_name": f"Create {noun}",
        "kind": "action",
        "description": (
            f"Creates a {noun} with its lines (POST {path}), finding or creating the client first "
            "when no client code is given; lines beyond the first 100 are added one by one, and "
            "it can post the document. If a later call fails, the step says exactly what was "
            "already created and is not retried."
        ),
        "inputs": inputs,
        "outputs": outputs,
    }


def operations() -> list[dict[str, Any]]:
    paging = {
        "name": "max_pages",
        "value_type": "integer",
        "required": False,
        "schema": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "title": "Max pages",
            "description": "Pages of 100 records to read. Default 10.",
        },
    }
    return [
        {
            "operation_id": "find_or_create_client",
            "display_name": "Find or create customer / supplier",
            "kind": "action",
            "description": (
                "Looks the client up by client code, then registration code, then VAT number "
                "(GET /v1/clients); several matches or conflicting codes are an error. Creates "
                "it (POST /v1/clients) only when none matches, so running it again is safe — "
                "but not two runs at the same time."
            ),
            "inputs": [CONNECTION, *CLIENT_LOOKUP, *CLIENT_NEW],
            "outputs": CLIENT_OUTPUTS,
        },
        invoice("sales"),
        invoice("purchase"),
        {
            "operation_id": "download_document_file",
            "display_name": "Download document file",
            "kind": "source",
            "description": (
                "Saves a file attached in Rivile ERP as a workflow file (GET /v1/files/{id}/"
                "content). Give the file id, or a document type and id to take its attachment "
                "(by name, or the first one)."
            ),
            "inputs": [
                CONNECTION,
                text(
                    "file_id",
                    "File id",
                    "The attachment id (attachments[].id).",
                    pattern=UUID_PATTERN,
                    maxLength=36,
                ),
                choice(
                    "document_type",
                    "Document type",
                    "Where the attachment is.",
                    sorted(DOCUMENT_TYPES),
                ),
                text(
                    "document_id",
                    "Document id",
                    "The document's id (UUID).",
                    pattern=UUID_PATTERN,
                    maxLength=36,
                ),
                text(
                    "file_name", "File name", "Pick the attachment with this name.", maxLength=255
                ),
            ],
            "outputs": [
                out("found", "boolean", "boolean"),
                out("document_file", "artifact_handle", None),
                out("file_id", "text", ["string", "null"]),
                out("original_filename", "text", ["string", "null"], "The name in Rivile ERP."),
                out("size_bytes", "integer", ["integer", "null"]),
            ],
        },
        {
            "operation_id": "register_payment",
            "display_name": "Register payment",
            "kind": "action",
            "description": (
                "Creates a payment received or sent (POST /v1/payments) and, when an invoice id "
                "is given, links it to that invoice (PATCH /v1/payments/{id}/link-payment)."
            ),
            "inputs": [
                CONNECTION,
                choice(
                    "direction",
                    "Direction",
                    "received (typeId 5) or sent (typeId 4).",
                    ["received", "sent"],
                    required=True,
                ),
                code("client_code", "Client code", "clientCode.", required=True),
                {
                    "name": "amount",
                    "value_type": "text",
                    "required": True,
                    "schema": {
                        "type": ["string", "number"],
                        "title": "Amount",
                        "description": "Amount in the payment currency (amountCur), e.g. 121.00.",
                    },
                },
                code("currency_code", "Currency", "currencyCode. Default: the base currency."),
                text("date", "Date", "opDate, YYYY-MM-DD. Default: today.", **DATE),
                code(
                    "account_code", "Money account", "The bank or cash account code (accountCode)."
                ),
                code("payment_method_code", "Payment method", "paymentMethodCode."),
                text("document_no", "Number", "documentNo.", maxLength=50),
                text("purpose", "Purpose", "purposeText.", maxLength=500),
                text(
                    "invoice_id",
                    "Invoice id",
                    "Link the payment to this invoice (UUID).",
                    pattern=UUID_PATTERN,
                    maxLength=36,
                ),
                choice(
                    "invoice_type",
                    "Invoice type",
                    "sale_invoice (default for received) or purchase_invoice.",
                    ["sale_invoice", "purchase_invoice"],
                ),
                flag("post", "Post", "Post the payment (PATCH /v1/payments/{id}/post)."),
            ],
            "outputs": [
                out("payment_id", "text", ["string", "null"]),
                out("linked", "boolean", "boolean"),
                out("posted", "boolean", "boolean"),
                out("record", "object", ["object", "null"]),
            ],
        },
        {
            "operation_id": "find_or_create_product",
            "display_name": "Find or create product",
            "kind": "action",
            "description": (
                "Looks the product up by code, then barcode (GET /v1/products); creates it "
                "(POST /v1/products) only when none matches."
            ),
            "inputs": [
                CONNECTION,
                code("product_code", "Product code", "code; used as the new code when creating."),
                code("barcode", "Barcode", "mainBarcode."),
                text("name", "Name", "Needed when the product has to be created."),
                choice(
                    "product_type",
                    "Product type",
                    "1 — product (default), 2 — service; productTypeId.",
                    [1, 2],
                ),
                code("unit", "Unit", "Unit of measure code for a new product, e.g. VNT (uomCode)."),
                text("description", "Description", "description.", maxLength=1000),
            ],
            "outputs": [
                out("product_id", "text", ["string", "null"]),
                out("product_code", "text", ["string", "null"]),
                out("created", "boolean", "boolean"),
                out("matched_by", "text", ["string", "null"]),
                out("record", "object", ["object", "null"]),
            ],
        },
        {
            "operation_id": "stock_levels",
            "display_name": "Stock levels",
            "kind": "source",
            "description": "Quantities on hand per product and department (GET /v1/inventory-stocks).",
            "inputs": [
                CONNECTION,
                code("product_code", "Product code", "productCode."),
                code("department_code", "Department", "departmentCode (warehouse)."),
                paging,
            ],
            "outputs": [
                out(
                    "items",
                    "array",
                    "array",
                    "productCode, departmentCode, uomCode, available, in_warehouse, reserved.",
                ),
                out("count", "integer", "integer"),
                out(
                    "total_available", "text", "string", "Sum of qtyAvailable, as an exact decimal."
                ),
                out("has_more", "boolean", "boolean"),
            ],
        },
        {
            "operation_id": "product_prices",
            "display_name": "Product prices",
            "kind": "source",
            "description": "Sale prices of a product (GET /v1/sale-prices).",
            "inputs": [
                CONNECTION,
                code("product_code", "Product code", "productCode.", required=True),
                code("price_category_code", "Price category", "priceCategoryCode."),
                code("currency_code", "Currency", "currencyCode."),
                code("department_code", "Department", "departmentCode."),
            ],
            "outputs": [
                out(
                    "prices",
                    "array",
                    "array",
                    "price_excluding_tax, price_including_tax, valid_from, valid_to, currency, category, unit.",
                ),
                out("count", "integer", "integer"),
            ],
        },
        {
            "operation_id": "changes_since",
            "display_name": "Changes since",
            "kind": "source",
            "description": (
                "Records of one kind changed after a moment, from the list's updatedAt filter "
                "(updatedAt GREATER_THAN since)."
            ),
            "inputs": [
                CONNECTION,
                choice("entity", "What", "The list to read.", sorted(CHANGE_LISTS), required=True),
                text(
                    "since",
                    "Since",
                    "YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS(.SSS)Z.",
                    required=True,
                    maxLength=30,
                    pattern=r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z)?$",
                ),
                paging,
            ],
            "outputs": [
                out("records", "array", "array"),
                out("count", "integer", "integer"),
                out("has_more", "boolean", "boolean"),
                out("next_page", "integer", ["integer", "null"]),
            ],
        },
        {
            "operation_id": "client_debt",
            "display_name": "Client debt",
            "kind": "source",
            "description": (
                "Open amounts of one client from the receivables and payables registry "
                "(GET /v1/pr-registries, totalBaseDue), with the overdue part."
            ),
            "inputs": [
                CONNECTION,
                code("client_code", "Client code", "clientCode.", required=True),
                paging,
            ],
            "outputs": [
                out(
                    "total_due",
                    "text",
                    "string",
                    "Sum of totalBaseDue (base currency), exact decimal.",
                ),
                out("overdue", "text", "string", "Sum of totalBaseDue where overDueDays > 0."),
                out(
                    "documents",
                    "array",
                    "array",
                    "document_no, date, due_date, due, overdue_days, currency, due_in_currency.",
                ),
                out("count", "integer", "integer"),
                out(
                    "has_more",
                    "boolean",
                    "boolean",
                    "True when there were more records than were read.",
                ),
            ],
        },
    ]
