"""Render the UI pages that restate the operation registry, so they cannot drift.

* ``ui/pages/rivile-erp-api.yaml`` — the everyday operations in full detail, how operations
  behave, every Rivile ERP endpoint grouped by area, and coverage
* ``ui/pages/changelog.yaml``      — ``CHANGELOG.md``

The platform renders page bodies as simple markdown: headings, paragraphs, lists,
bold, code and ``[label](https://…)`` links. Tables and bare URLs are not
rendered, so no page uses them (``tests/test_contracts.py`` checks that).

Called by ``build_contracts.py``; the inputs are the operations it builds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SWAGGER_URL = "https://erp.rivile.cloud/public-api/swagger-ui/index.html"
GUIDE_URL = "https://guide.rivile.cloud/integrative_solutions/api/api_usage"
ADVANCED_PREFIX = "Advanced · "

#: The Rivile ERP endpoints each everyday operation calls.
FRIENDLY_ENDPOINTS: dict[str, tuple[str, ...]] = {
    "test_connection": ("GET /v1/users/api-keys",),
    "find_or_create_client": ("GET /v1/clients", "POST /v1/clients"),
    "create_sales_invoice": (
        "GET /v1/clients",
        "POST /v1/clients",
        "GET /v1/sale-invoices",
        "POST /v1/sale-invoices",
        "PATCH /v1/sale-invoices/{id}/post",
    ),
    "create_purchase_invoice": (
        "GET /v1/clients",
        "POST /v1/clients",
        "GET /v1/purchase-invoices",
        "POST /v1/purchase-invoices",
        "PATCH /v1/purchase-invoices/{id}/post",
    ),
    "download_document_file": ("the document's own read by id", "GET /v1/files/{id}/content"),
    "register_payment": (
        "POST /v1/payments",
        "PATCH /v1/payments/{id}/link-payment",
        "PATCH /v1/payments/{id}/post",
    ),
    "find_or_create_product": ("GET /v1/products", "POST /v1/products"),
    "stock_levels": ("GET /v1/inventory-stocks",),
    "product_prices": ("GET /v1/sale-prices",),
    "changes_since": ("the chosen list, filtered on updatedAt",),
    "client_debt": ("GET /v1/pr-registries",),
}

#: Host plumbing for the external-effect record: declared in the contract, not shown.
HIDDEN_RESULTS = frozenset({"external_effect_status", "definitely_no_external_effect"})

BEHAVIOUR = """\
### Inputs

- Every step needs a **connection**: the Rivile ERP API key it runs with.
- Everyday steps take plain inputs. Codes your company sets up its own way — departments, units, money accounts, price categories — are inputs.
- Advanced steps take the path ids, query parameters and a `body` with Rivile ERP's own field names (camelCase), as in the [Rivile ERP API reference](https://erp.rivile.cloud/public-api/swagger-ui/index.html). Where both an Id and a Code field exist (`clientId` / `clientCode`), either may be given.

### Lists and filters

- Rivile returns at most 100 records per page. Pages count from 0. Set `page`, or turn on `fetch_all_pages` (up to `max_pages`).
- `filters` are combined with AND. Each names a field Rivile documents for that list, an operation (EQUAL, CONTAINS, GREATER_THAN…) and a value. Dates are written YYYY-MM-DD, date-times YYYY-MM-DDTHH:MM:SS.SSSZ.
- A step output has a size limit. A long read stops at the last page that fits and returns `has_more` and `next_page`. For whole lists use **Export a Rivile ERP list to a JSONL file**.

### Files

- Rivile ERP's API can only download attached files. **Download document file** saves one as a workflow file. Attaching a file is not possible through the API.

### Writes, retries and errors

- Every create, update, post, cancel, approve, reserve, link and delete goes through Flow Steward's external-effect record, so a retried step does not send it twice. Test runs never write.
- **HTTP 400:** Rivile refused the data and nothing was saved. The step fails with Rivile's code and every refused field with its JSON path, for example `lines[0].itemCode`.
- **401:** the API key is wrong, expired or deactivated. **404:** the record does not exist.
- **Timeout, 5xx or a lost connection on a write:** Rivile may have saved it, and Rivile ERP has no idempotency key. The step fails as `timeout_unknown` and is not retried; check the record in Rivile ERP first.
- Rivile stops a request after 5 minutes. Request bodies are limited to 5 MB.
- If a step that writes several things fails half-way, it says exactly what was already created and is not retried.
"""


class _PageDumper(yaml.SafeDumper):
    """Multi-line strings as ``|`` blocks, so the page files read like markdown."""


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_PageDumper.add_representer(str, _represent_str)


def dump_page(path: Path, header: str, page: dict[str, Any]) -> None:
    text = yaml.dump(page, Dumper=_PageDumper, sort_keys=False, allow_unicode=True, width=1000)
    path.write_text(header + text, encoding="utf-8")


def _names(fields: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in fields) if fields else "none"


def _inputs(op: dict[str, Any]) -> str:
    parts = []
    for item in op["inputs"]:
        if item["name"] == "connection_ref":
            continue
        parts.append(f"`{item['name']}`" + ("" if item.get("required") else " (optional)"))
    return ", ".join(parts) if parts else "none"


def _results(op: dict[str, Any]) -> list[str]:
    names = [name.removeprefix("result.") for name in op["result_fields"]]
    return [name for name in names if name not in HIDDEN_RESULTS]


def _kind(op: dict[str, Any]) -> str:
    return "write" if op["operation_kind"] == "action" else "read"


def _plain_title(op: dict[str, Any]) -> str:
    return str(op["display_name"]).removeprefix(ADVANCED_PREFIX)


def _call(text: str) -> str:
    """An endpoint as code; a plain description as text."""
    return f"`{text}`" if text.split(" ", 1)[0] in {"GET", "POST", "PATCH", "DELETE"} else text


def _everyday_section(op: dict[str, Any]) -> list[str]:
    endpoints = FRIENDLY_ENDPOINTS[op["operation_id"]]
    return [
        f"### {op['display_name']}",
        "",
        str(op["description"]),
        "",
        f"- Action id: `{op['operation_id']}`",
        f"- Kind: {_kind(op)}",
        f"- Rivile ERP calls: {', '.join(_call(e) for e in endpoints)}",
        f"- Inputs: {_inputs(op)}",
        f"- Results: {_names(_results(op))}",
        "",
    ]


def _endpoint_section(op: dict[str, Any], row: dict[str, Any] | None) -> list[str]:
    from build_contracts import ENDPOINT_NOTES, swagger_link

    lines = [f"### {_plain_title(op)}", ""]
    if row is None:
        lines += [str(op["description"]), ""]
        where = "any path under `/v1`"
    else:
        wire = f"{row['http_method']} {row['path']}"
        if wire in ENDPOINT_NOTES:
            lines += [ENDPOINT_NOTES[wire], ""]
        where = f"`{wire}` · [API reference]({swagger_link(row)})"
    lines += [
        f"- Action id: `{op['operation_id']}` · {_kind(op)} · {where}",
        f"- Inputs: {_inputs(op)}",
        f"- Results: {_names(_results(op))}",
        "",
    ]
    return lines


def coverage_body(rows: list[dict[str, Any]]) -> str:
    writes = sum(1 for r in rows if r["write"])
    return (
        "\n".join(
            [
                f"- **Covered:** all {len(rows)} endpoints of the Rivile ERP Public API "
                f"({len(rows) - writes} read, {writes} write), each as its own step, generated "
                "from Rivile's OpenAPI document.",
                "- **Inputs:** every path id and query parameter is its own input; every request "
                "body is one `body` input typed with Rivile's schema; list filters accept only the "
                "fields Rivile documents for that list.",
                "- **Newer than this release:** **Call any Rivile ERP endpoint** sends any path "
                "under `/v1` (always treated as a write).",
                "- **Not offered by the Rivile ERP API: attaching files.** The API has no upload; "
                "files can only be downloaded.",
                "- **Not offered: the GROUP filter operation.** It is in Rivile's enum, but its "
                "value is not described.",
                "- **Not offered: stock changes since a date.** The stock list does not document "
                "updatedAt as a filter field.",
                "- **Not offered: rate coordination across steps.** No rate limit is documented; "
                "HTTP 429 is still retried after 1, 2, 4 and 8 seconds within a step.",
            ]
        )
        + "\n"
    )


def api_page(ops: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One page, like Shopify's: everyday steps, behaviour, every endpoint by area, coverage."""
    by_id = {row["operation_id"]: row for row in rows}
    everyday = [op for op in ops if op["operation_id"] in FRIENDLY_ENDPOINTS]
    lines = [
        "These steps take plain inputs and make the Rivile ERP calls for you. Every Rivile ERP "
        "endpoint is also available on its own, as **Advanced · …** — see **Advanced endpoints** "
        "below.",
        "",
    ]
    for op in everyday:
        lines.extend(_everyday_section(op))
    components: list[dict[str, Any]] = [
        {
            "component_id": "operations_everyday",
            "type": "markdown",
            "title": "Everyday operations",
            "body": "\n".join(lines).rstrip() + "\n",
        },
        {
            "component_id": "operations_behaviour",
            "type": "markdown",
            "title": "How operations behave",
            "body": BEHAVIOUR,
        },
        {
            "component_id": "advanced_intro",
            "type": "markdown",
            "title": "Advanced endpoints",
            "body": (
                "Every Rivile ERP Public API endpoint as its own step, named **Advanced · …** in "
                "the step picker and grouped below by area. Field names and types are Rivile's; "
                f"the [Rivile ERP API reference]({SWAGGER_URL}) shows every schema, and the "
                f"[Rivile guide]({GUIDE_URL}) explains filters and limits.\n"
            ),
        },
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for op in ops:
        row = by_id.get(op["operation_id"])
        if row is not None:
            groups.setdefault(row["group"], []).append(op)
    for index, group in enumerate(sorted(groups)):
        body: list[str] = []
        for op in groups[group]:
            body.extend(_endpoint_section(op, by_id[op["operation_id"]]))
        components.append(
            {
                "component_id": f"advanced_group_{index + 1}",
                "type": "markdown",
                "title": group,
                "body": "\n".join(body).rstrip() + "\n",
            }
        )
    tools: list[str] = []
    for op in ops:
        if op["operation_id"] in {"call_endpoint", "export_list"}:
            tools.extend(_endpoint_section(op, None))
    components.append(
        {
            "component_id": "advanced_any_endpoint",
            "type": "markdown",
            "title": "Any endpoint and exports",
            "body": "\n".join(tools).rstrip() + "\n",
        }
    )
    components.append(
        {
            "component_id": "advanced_coverage",
            "type": "markdown",
            "title": "Coverage",
            "body": coverage_body(rows),
        }
    )
    return {
        "page_id": "rivile-erp-api",
        "title": "Rivile ERP API",
        "description": "Every Rivile ERP step: what it does, which endpoint it calls, its inputs and results.",
        "components": components,
    }


def changelog_page() -> dict[str, Any]:
    """The Changelog page renders CHANGELOG.md, so the two cannot disagree."""
    lines = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return {
        "page_id": "changelog",
        "title": "Changelog",
        "description": "What changed in each release of this extension.",
        "components": [
            {
                "component_id": "changelog_entries",
                "type": "markdown",
                "title": "Release history",
                "body": "\n".join(line.rstrip() for line in lines).strip() + "\n",
            }
        ],
    }
