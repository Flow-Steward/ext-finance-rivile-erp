"""Operation registry: every Rivile ERP endpoint plus the extension's own operations."""

from __future__ import annotations

from .endpoints import ENDPOINTS
from .models import Endpoint

TEST_CONNECTION = "test_connection"
CALL_ENDPOINT = "call_endpoint"
EXPORT_LIST = "export_list"
SPECIAL_OPERATION_IDS: frozenset[str] = frozenset({TEST_CONNECTION, CALL_ENDPOINT, EXPORT_LIST})

#: Everyday operations: plain inputs, several Rivile ERP calls in one step.
FRIENDLY_WRITE_IDS: frozenset[str] = frozenset(
    {
        "find_or_create_client",
        "create_sales_invoice",
        "create_purchase_invoice",
        "register_payment",
        "find_or_create_product",
    }
)
FRIENDLY_READ_IDS: frozenset[str] = frozenset(
    {"download_document_file", "stock_levels", "product_prices", "changes_since", "client_debt"}
)
FRIENDLY_IDS: frozenset[str] = FRIENDLY_WRITE_IDS | FRIENDLY_READ_IDS

ENDPOINTS_BY_OPERATION: dict[str, Endpoint] = {e.operation_id: e for e in ENDPOINTS}
#: GET lists by path, for export_list and the everyday reads.
LISTS_BY_PATH: dict[str, Endpoint] = {e.path: e for e in ENDPOINTS if e.paged}
OPERATION_IDS: frozenset[str] = (
    frozenset(ENDPOINTS_BY_OPERATION) | SPECIAL_OPERATION_IDS | FRIENDLY_IDS
)
WRITE_OPERATION_IDS: frozenset[str] = frozenset(
    {e.operation_id for e in ENDPOINTS if e.write} | {CALL_ENDPOINT} | FRIENDLY_WRITE_IDS
)

DOWNLOAD_BINDING = "rivile_erp_file"
FRIENDLY_DOWNLOAD_BINDING = "rivile_erp_document_file"
EXPORT_BINDING = "rivile_erp_export"
FILE_CONTENT_PATH = "/v1/files/{id}/content"

__all__ = [
    "CALL_ENDPOINT",
    "DOWNLOAD_BINDING",
    "ENDPOINTS_BY_OPERATION",
    "EXPORT_BINDING",
    "EXPORT_LIST",
    "FILE_CONTENT_PATH",
    "FRIENDLY_DOWNLOAD_BINDING",
    "FRIENDLY_IDS",
    "FRIENDLY_READ_IDS",
    "FRIENDLY_WRITE_IDS",
    "LISTS_BY_PATH",
    "OPERATION_IDS",
    "SPECIAL_OPERATION_IDS",
    "TEST_CONNECTION",
    "WRITE_OPERATION_IDS",
]
