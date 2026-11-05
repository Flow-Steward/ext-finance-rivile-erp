"""Health command for the Rivile ERP extension (no network)."""

from __future__ import annotations

import json


def check_health() -> dict[str, object]:
    from runtime.catalog import ENDPOINTS_BY_OPERATION, OPERATION_IDS, WRITE_OPERATION_IDS
    from runtime.connection import BASE_URL
    from runtime.endpoints import SPEC_SHA256

    return {
        "extension_id": "flowsteward.rivile-erp",
        "ok": True,
        "status": "healthy",
        "base_url": BASE_URL,
        "openapi_sha256": SPEC_SHA256,
        "rivile_endpoints": len(ENDPOINTS_BY_OPERATION),
        "declared_operations": len(OPERATION_IDS),
        "write_operations": len(WRITE_OPERATION_IDS),
    }


if __name__ == "__main__":
    print(json.dumps(check_health(), separators=(",", ":"), sort_keys=True))
