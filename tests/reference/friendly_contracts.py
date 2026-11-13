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


def body_code(name: str, title: str, description: str, *, required: bool = False) -> dict[str, Any]:
    """A code sent only in the request body: any printable text, up to 50 characters."""
    return text(name, title, description, required=required, maxLength=50)


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

#: Words shown for coded select values (the form shows the label, the step gets the value).
OPTION_LABELS: dict[str, dict[Any, str]] = {
    "client_type": {0: "Legal entity", 1: "Individual"},
    "product_type": {1: "Product", 2: "Service"},
    "direction": {"received": "Payment received", "sent": "Payment sent"},
    "invoice_type": {"sale_invoice": "Sales invoice", "purchase_invoice": "Purchase invoice"},
    "entity": {key: key.replace("_", " ").capitalize() for key in CHANGE_LISTS},
    "document_type": {key: key.replace("_", " ").capitalize() for key in DOCUMENT_TYPES},
}

CLIENT_LOOKUP = [
    code(
        "client_code",
        "Client code",
        "The code of an existing client in Rivile ERP. When given, that client must exist: the "
        "step never creates a client for a code, so a typo cannot add a second client.",
    ),
    code(
        "reg_code",
        "Registration code",
        "The company registration code, used to find the client, or to create it when no client "
        "has this code.",
    ),
    code(
        "vat_number",
        "VAT number",
        "The VAT payer code, for example LT100001234567, used like the registration code.",
    ),
]
CLIENT_NEW = [
    text("name", "Name", "The client's name, needed when the client has to be created."),
    choice(
        "client_type",
        "Client type",
        "Whether a new client is a company or a person. Default: legal entity.",
        [0, 1],
    ),
    text("address", "Address", "The address saved on a new client."),
    text("email", "E-mail", "The e-mail address saved on a new client."),
    text("phone", "Phone", "The phone number saved on a new client."),
    flag(
        "is_customer",
        "Customer",
        "Mark a new client as a customer. Default: yes for sales invoices.",
    ),
    flag(
        "is_supplier",
        "Supplier",
        "Mark a new client as a supplier. Default: yes for purchase invoices.",
    ),
]
CLIENT_OUTPUTS = [
    out("client_id", "text", ["string", "null"], "The client's id (UUID)."),
    out("client_code", "text", ["string", "null"], "The client's code in Rivile ERP."),
    out("created", "boolean", "boolean", "True when this step created the client."),
    out("matched_by", "text", ["string", "null"], "client_code, reg_code or vat_number."),
    out("record", "object", ["object", "null"], "The client as Rivile ERP returned it."),
]

LINE_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["item_code", "quantity"],
    "properties": {
        "item_code": {"type": "string", "maxLength": 50, "description": "Product or service code."},
        "unit": {
            "type": "string",
            "maxLength": 20,
            "description": "Unit of measure code, for example VNT. Default: the product's unit.",
        },
        "quantity": {"type": ["number", "string"], "description": "Quantity in that unit."},
        "price": {
            "type": ["number", "string"],
            "description": "Unit price. Default: the price from Rivile's price list.",
        },
        "discount_percent": {"type": ["number", "string"], "description": "Discount in percent."},
        "department_code": {
            "type": "string",
            "maxLength": 50,
            "description": "Department (warehouse) for this line. Default: the invoice's.",
        },
        "notes": {"type": "string", "maxLength": 500, "description": "A note on the line."},
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
            f"The document number. With a number the step first looks for a {noun} with this "
            "number, client and date: if one exists it is returned (and posted if asked) instead "
            "of creating a second one; the same number with another date stops the step. "
            "Without a number Rivile numbers the document.",
            maxLength=50,
        ),
        text("date", "Date", "The operation date, YYYY-MM-DD. Default: today.", **DATE),
        text(
            "document_date",
            "Document date",
            "The date printed on the document, YYYY-MM-DD. Default: the operation date.",
            **DATE,
        ),
        body_code(
            "department_code",
            "Department",
            "The department (warehouse) code used for every line that does not name its own.",
            required=True,
        ),
        body_code(
            "currency_code",
            "Currency",
            "The currency code, for example EUR. Default: the company's base currency.",
        ),
        flag("prices_include_tax", "Prices include VAT", "Whether the line prices include VAT."),
        text("notes", "Notes", "A note printed on the document.", maxLength=1000),
        {
            "name": "lines",
            "value_type": "array",
            "required": True,
            "schema": {
                "type": "array",
                "minItems": 1,
                "maxItems": 100,
                "items": LINE_ITEM,
                "title": "Lines",
                "description": (
                    "The invoice lines, 1 to 100 — Rivile's limit for creating a document in one "
                    "request. For more, add lines afterwards with the Advanced create-line step."
                ),
            },
        },
        flag("post", "Post", f"Post the {noun} once it is created."),
    ]
    outputs = [
        out("document_id", "text", ["string", "null"], "The document's id (UUID)."),
        out("number", "text", ["string", "null"], "The document number."),
        out("created", "boolean", "boolean", "False when an existing document was returned."),
        out("client_code", "text", ["string", "null"], "The client's code."),
        out("client_created", "boolean", "boolean", "True when this step created the client."),
        out("lines_created", "integer", "integer", "Lines saved by this step."),
        out("total_amount", "text", ["string", "null"], "Rivile's totalAmount, exact decimal."),
        out("total_tax", "text", ["string", "null"], "Rivile's totalTaxAmount, exact decimal."),
        out(
            "total_with_tax",
            "text",
            ["string", "null"],
            "Rivile's totalAmountWithTax, exact decimal.",
        ),
        out(
            "status_id",
            "integer",
            ["integer", "null"],
            "Rivile's statusId of the document, as returned (its values are not documented).",
        ),
        out(
            "posted",
            "boolean",
            ["boolean", "null"],
            "True when this step posted the document; null when an existing document was "
            "returned without posting (Rivile does not document which status means posted).",
        ),
        out("record", "object", ["object", "null"], "The document as Rivile ERP returned it."),
    ]
    return {
        "operation_id": f"create_{kind}_invoice",
        "display_name": f"Create {noun}",
        "kind": "action",
        "description": (
            f"Creates a {noun} with up to 100 lines in one request (POST {path}), after finding "
            "the client by code — or finding or creating it by registration or VAT code — and "
            "can post it. If a later call fails, the step says exactly what was already created "
            "and is not retried."
        ),
        "inputs": inputs,
        "outputs": outputs,
    }


START_PAGE = {
    "name": "page",
    "value_type": "integer",
    "required": False,
    "schema": {
        "type": "integer",
        "minimum": 0,
        "maximum": 1000000,
        "title": "Page",
        "description": "The page to start from, counted from 0; pass next_page to continue.",
    },
}
CONTINUATION = [
    out("next_page", "integer", ["integer", "null"], "The page to continue from, or null."),
    out("complete", "boolean", "boolean", "False when more rows exist than were read."),
]


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
            "description": "How many pages of 100 records to read at most. Default 10.",
        },
    }
    return [
        {
            "operation_id": "find_or_create_client",
            "display_name": "Find or create customer / supplier",
            "kind": "action",
            "description": (
                "Finds the client by code, which must exist, or finds it by registration code "
                "or VAT number and creates it when none matches (GET and POST /v1/clients). "
                "Several matches or conflicting codes are an error and nothing is created. "
                "Running it again is safe — but not two runs at the same time."
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
                    "The attachment's id, as listed in a document's attachments.",
                    pattern=UUID_PATTERN,
                    maxLength=36,
                ),
                choice(
                    "document_type",
                    "Document type",
                    "The kind of record the file is attached to.",
                    sorted(DOCUMENT_TYPES),
                ),
                text(
                    "document_id",
                    "Document id",
                    "The id (UUID) of the record the file is attached to.",
                    pattern=UUID_PATTERN,
                    maxLength=36,
                ),
                text(
                    "file_name",
                    "File name",
                    "Take the attachment with this name. Default: the first attachment.",
                    maxLength=255,
                ),
            ],
            "outputs": [
                out("found", "boolean", "boolean", "False when the record has no attached file."),
                out("document_file", "artifact_handle", None),
                out("file_id", "text", ["string", "null"], "The attachment's id."),
                out("original_filename", "text", ["string", "null"], "The name in Rivile ERP."),
                out("size_bytes", "integer", ["integer", "null"], "The file size in bytes."),
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
                    "Whether the money was received from the client or sent to them.",
                    ["received", "sent"],
                    required=True,
                ),
                body_code(
                    "client_code",
                    "Client code",
                    "The code of the client who paid or is paid.",
                    required=True,
                ),
                {
                    "name": "amount",
                    "value_type": "text",
                    "required": True,
                    "schema": {
                        "type": ["string", "number"],
                        "title": "Amount",
                        "description": "The amount in the payment currency, for example 121.00.",
                    },
                },
                body_code(
                    "currency_code", "Currency", "The currency code. Default: the base currency."
                ),
                text("date", "Date", "The payment date, YYYY-MM-DD. Default: today.", **DATE),
                body_code("account_code", "Money account", "The bank or cash account code."),
                body_code("payment_method_code", "Payment method", "The payment method code."),
                text("document_no", "Number", "The payment document number.", maxLength=50),
                text("purpose", "Purpose", "The payment purpose text.", maxLength=500),
                text(
                    "invoice_id",
                    "Invoice id",
                    "Link the payment to the invoice with this id (UUID).",
                    pattern=UUID_PATTERN,
                    maxLength=36,
                ),
                choice(
                    "invoice_type",
                    "Invoice type",
                    "The kind of invoice to link. Default: sales invoice for money received.",
                    ["sale_invoice", "purchase_invoice"],
                ),
                flag("post", "Post", "Post the payment once it is created."),
            ],
            "outputs": [
                out("payment_id", "text", ["string", "null"], "The payment's id (UUID)."),
                out("linked", "boolean", "boolean", "True when linked to the invoice."),
                out("posted", "boolean", "boolean", "True when this step posted the payment."),
                out(
                    "record", "object", ["object", "null"], "The payment as Rivile ERP returned it."
                ),
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
                code(
                    "product_code",
                    "Product code",
                    "The product code, looked up first and used as the code of a new product.",
                ),
                code("barcode", "Barcode", "The main barcode, looked up second."),
                text("name", "Name", "The product name, needed when it has to be created."),
                choice(
                    "product_type",
                    "Product type",
                    "Whether a new product is a stocked product or a service. Default: product.",
                    [1, 2],
                ),
                body_code(
                    "unit", "Unit", "The unit of measure code for a new product, for example VNT."
                ),
                text(
                    "description",
                    "Description",
                    "A description saved on a new product.",
                    maxLength=1000,
                ),
            ],
            "outputs": [
                out("product_id", "text", ["string", "null"], "The product's id (UUID)."),
                out("product_code", "text", ["string", "null"], "The product's code."),
                out("created", "boolean", "boolean", "True when this step created the product."),
                out("matched_by", "text", ["string", "null"], "product_code or barcode."),
                out(
                    "record", "object", ["object", "null"], "The product as Rivile ERP returned it."
                ),
            ],
        },
        {
            "operation_id": "stock_levels",
            "display_name": "Read stock levels",
            "kind": "source",
            "description": "Quantities on hand per product and department (GET /v1/inventory-stocks).",
            "inputs": [
                CONNECTION,
                code("product_code", "Product code", "Only this product. Default: all products."),
                code("department_code", "Department", "Only this department (warehouse)."),
                START_PAGE,
                paging,
            ],
            "outputs": [
                out(
                    "items",
                    "array",
                    "array",
                    "One row per product, department and lot: available, in warehouse and "
                    "reserved in the product's base unit, and the same in the alternative unit "
                    "(alt_unit, alt_unit_ratio, alt_available…).",
                ),
                out("count", "integer", "integer", "Rows returned."),
                out(
                    "totals",
                    "array",
                    "array",
                    "Available quantity summed per product, in its base unit, as exact decimals.",
                ),
                out("has_more", "boolean", "boolean", "True when there are more rows to read."),
                *CONTINUATION,
            ],
        },
        {
            "operation_id": "product_prices",
            "display_name": "Read product prices",
            "kind": "source",
            "description": "Sale prices of a product (GET /v1/sale-prices).",
            "inputs": [
                CONNECTION,
                code(
                    "product_code",
                    "Product code",
                    "The product whose prices to read.",
                    required=True,
                ),
                code(
                    "price_category_code", "Price category", "Only prices of this price category."
                ),
                code("currency_code", "Currency", "Only prices in this currency."),
                code("department_code", "Department", "Only prices of this department."),
                START_PAGE,
                paging,
            ],
            "outputs": [
                out(
                    "prices",
                    "array",
                    "array",
                    "Prices with and without VAT, validity dates, currency, category and unit.",
                ),
                out("count", "integer", "integer", "Prices returned."),
                out("has_more", "boolean", "boolean", "True when there are more prices to read."),
                *CONTINUATION,
            ],
        },
        {
            "operation_id": "changes_since",
            "display_name": "Read records changed since a date",
            "kind": "source",
            "description": (
                "Records of one kind changed after a moment, from the list's updatedAt filter "
                "(updatedAt GREATER_THAN since)."
            ),
            "inputs": [
                CONNECTION,
                choice(
                    "entity",
                    "What",
                    "The kind of records to read.",
                    sorted(CHANGE_LISTS),
                    required=True,
                ),
                text(
                    "since",
                    "Since",
                    "Read records changed after this moment: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.SSSZ.",
                    required=True,
                    maxLength=30,
                    pattern=r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z)?$",
                ),
                {
                    "name": "page",
                    "value_type": "integer",
                    "required": False,
                    "schema": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 1000000,
                        "title": "Page",
                        "description": "The page to start from, counted from 0; pass next_page to continue.",
                    },
                },
                paging,
            ],
            "outputs": [
                out(
                    "records", "array", "array", "The changed records, as Rivile ERP returned them."
                ),
                out("count", "integer", "integer", "Records returned."),
                out("has_more", "boolean", "boolean", "True when there are more records to read."),
                out("next_page", "integer", ["integer", "null"], "The page to continue from."),
            ],
        },
        {
            "operation_id": "client_debt",
            "display_name": "Read client debt",
            "kind": "source",
            "description": (
                "Open amounts of one client from the receivables and payables registry "
                "(GET /v1/pr-registries, totalBaseDue), totalled per registry type, with the "
                "overdue part."
            ),
            "inputs": [
                CONNECTION,
                code(
                    "client_code",
                    "Client code",
                    "The client whose open amounts to read.",
                    required=True,
                ),
                START_PAGE,
                paging,
            ],
            "outputs": [
                out(
                    "total_due",
                    "text",
                    "string",
                    "The sum of totalBaseDue over every row read, in the base currency. It adds "
                    "up all registry types; see totals_by_type. Partial when complete is false.",
                ),
                out("overdue", "text", "string", "The part of total_due with overDueDays above 0."),
                out(
                    "totals_by_type",
                    "array",
                    "array",
                    "total_due, overdue and count per Rivile registry type (typeId, typeName).",
                ),
                out(
                    "documents",
                    "array",
                    "array",
                    "Each open document: number, type, dates, amount due and days overdue.",
                ),
                out("count", "integer", "integer", "Documents returned."),
                out("complete", "boolean", "boolean", "False when more rows exist than were read."),
                out("has_more", "boolean", "boolean", "True when there are more rows to read."),
                out(
                    "next_page",
                    "integer",
                    ["integer", "null"],
                    "The page to continue from, or null.",
                ),
            ],
        },
    ]
