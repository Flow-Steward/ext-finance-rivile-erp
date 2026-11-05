"""The committed contracts are exactly what the generator builds from the pinned OpenAPI."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import build_contracts
import pytest
import yaml

from runtime import catalog, friendly
from runtime.connection import ENDPOINT_HOST
from runtime.operations import FILTER_OPERATIONS

BUNDLE_ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> Any:
    return yaml.safe_load((BUNDLE_ROOT / relative).read_text("utf-8"))


@pytest.fixture(scope="module")
def built() -> dict[str, Any]:
    return build_contracts.outputs()


def test_openapi_document_is_the_pinned_one() -> None:
    raw = (BUNDLE_ROOT / "tests/reference/rivile_erp_openapi.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == build_contracts.SPEC_SHA256
    spec = json.loads(raw)
    assert spec["servers"] == [{"url": "https://erp.rivile.cloud/public-api"}]
    assert spec["components"]["securitySchemes"]["apiKey"]["name"] == "X-SessionToken"


def test_generated_files_match(built) -> None:
    assert _load("contracts/operation_manifest.yaml") == {"operations": built["operations"]}
    assert _load("contracts/step_ui_manifest.yaml") == {"forms": built["forms"]}
    assert _load("contracts/artifact_policies.yaml") == {
        "artifact_policies": built["artifact_policies"]
    }
    assert _load("ui/actions/actions.yaml") == {"actions": built["actions"]}
    assert _load("ui/pages/rivile-erp-api.yaml") == built["api_page"]
    assert _load("ui/pages/changelog.yaml") == built["changelog_page"]
    assert _load("extension.yaml")["external_effects"] == built["effects"]
    committed = (BUNDLE_ROOT / "runtime/endpoints.py").read_text("utf-8")
    # Compared as syntax trees: the formatter may re-wrap the generated source.
    assert ast.dump(ast.parse(committed)) == ast.dump(ast.parse(built["registry"]))


def test_every_documented_endpoint_is_an_operation(built) -> None:
    spec = json.loads((BUNDLE_ROOT / "tests/reference/rivile_erp_openapi.json").read_text("utf-8"))
    documented = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    registered = {(e.http_method, e.path) for e in catalog.ENDPOINTS_BY_OPERATION.values()}
    assert registered == documented
    assert len(documented) == 136
    op_ids = {op["operation_id"] for op in built["operations"]}
    assert set(catalog.ENDPOINTS_BY_OPERATION) <= op_ids
    assert op_ids == set(catalog.OPERATION_IDS)


def test_writes_are_external_effects(built) -> None:
    writes = {op["operation_id"] for op in built["operations"] if op["operation_kind"] == "action"}
    assert writes == set(catalog.WRITE_OPERATION_IDS)
    for endpoint in catalog.ENDPOINTS_BY_OPERATION.values():
        assert endpoint.write == (endpoint.http_method != "GET"), endpoint.wire
    effects = {e["operation_id"]: e for e in _load("extension.yaml")["external_effects"]}
    assert set(effects) == writes
    for effect in effects.values():
        assert effect["idempotency"] == "required"
        assert effect["test_mode_behavior"] == "suppress"


def test_list_filters_only_name_documented_fields(built) -> None:
    ops = {op["operation_id"]: op for op in built["operations"]}
    for endpoint in catalog.ENDPOINTS_BY_OPERATION.values():
        if not endpoint.paged:
            continue
        assert endpoint.filter_fields, endpoint.wire
        filters = next(i for i in ops[endpoint.operation_id]["inputs"] if i["name"] == "filters")
        item = filters["schema"]["items"]["properties"]
        assert item["field"]["enum"] == list(endpoint.filter_fields)
        assert set(item["operation"]["enum"]) == set(FILTER_OPERATIONS)
    assert "updatedAt" in catalog.LISTS_BY_PATH["/v1/clients"].filter_fields
    assert "GROUP" not in FILTER_OPERATIONS


def test_everyday_tables_match_the_contract() -> None:
    import friendly_contracts

    assert friendly.CHANGE_LISTS == friendly_contracts.CHANGE_LISTS
    assert friendly.DOCUMENT_TYPES == friendly_contracts.DOCUMENT_TYPES
    for path in friendly.CHANGE_LISTS.values():
        assert "updatedAt" in catalog.LISTS_BY_PATH[path].filter_fields, path
    gets = {e.path for e in catalog.ENDPOINTS_BY_OPERATION.values() if e.http_method == "GET"}
    assert set(friendly.DOCUMENT_TYPES.values()) <= gets


def test_neutral_test_mode_result_has_every_declared_output(built) -> None:
    from runtime.operations import _neutral_result

    for op in built["operations"]:
        if op["operation_kind"] != "action":
            continue
        result = _neutral_result(op["operation_id"])
        assert set(result) == {o["name"] for o in op["outputs"]}, op["operation_id"]
        assert result["external_effect_status"] == "failed"
        assert result["definitely_no_external_effect"] is True


_WIDGETS_BY_VALUE_TYPE = {
    "artifact_handle": {"artifact_picker"},
    "object": {"json", "select"},
    "array": {"json", "select"},
    "json": {"json"},
    "boolean": {"boolean", "select"},
    "integer": {"number", "select"},
    "number": {"number", "select"},
    "text": {"text", "textarea", "select"},
}


def test_every_input_has_a_matching_form_field(built) -> None:
    forms = {form["operation_id"]: form for form in built["forms"]}
    actions = {action["action_id"]: action for action in built["actions"]}
    for op in built["operations"]:
        oid = op["operation_id"]
        fields = {field["name"]: field for field in forms[oid]["fields"]}
        inputs = {item["name"]: item for item in op["inputs"] if item["name"] != "connection_ref"}
        assert set(fields) == set(inputs), oid
        for name, item in inputs.items():
            field = fields[name]
            assert field["required"] == bool(item.get("required")), (oid, name)
            allowed = _WIDGETS_BY_VALUE_TYPE[item["value_type"]]
            assert field["widget_type"] in allowed, (oid, name, field["widget_type"])
            if field["widget_type"] == "select":
                assert (item.get("schema") or {}).get("enum"), (oid, name)
        action = actions[oid]
        assert [p["name"] for p in action["parameters"]] == [i["name"] for i in op["inputs"]], oid
        # Actions name results bare (as Shopify's do); operations prefix them with "result.".
        assert [f"result.{name}" for name in action["result_fields"]] == op["result_fields"], oid
        assert op["result_fields"] == [f"result.{o['name']}" for o in op["outputs"]], oid


def test_every_file_input_has_a_file_picker(built) -> None:
    forms = {form["operation_id"]: form for form in built["forms"]}
    for op in built["operations"]:
        for item in op["inputs"]:
            if item["value_type"] == "artifact_handle":
                field = next(
                    f for f in forms[op["operation_id"]]["fields"] if f["name"] == item["name"]
                )
                assert field["widget_type"] == "artifact_picker"


def test_file_outputs_have_a_grant_with_the_runtime_content_type(built) -> None:
    from runtime import operations

    granted = {
        policy["operation_id"]: policy["outputs"][0]
        for policy in built["artifact_policies"]
        if policy.get("outputs")
    }
    for op in built["operations"]:
        if any(o["value_type"] == "artifact_handle" for o in op["outputs"]):
            assert op["operation_id"] in granted, op["operation_id"]
    assert granted["export_list"]["content_type"] == operations.EXPORT_CONTENT_TYPE
    assert granted["download_document_file"]["content_type"] == operations.DOWNLOAD_CONTENT_TYPE
    assert granted["get_files_id_content"]["content_type"] == operations.DOWNLOAD_CONTENT_TYPE
    assert granted["download_document_file"]["binding_key"] == catalog.FRIENDLY_DOWNLOAD_BINDING
    assert granted["export_list"]["binding_key"] == catalog.EXPORT_BINDING


def test_every_shipped_page_is_in_the_ui_manifest() -> None:
    refs = {page["ref"] for page in _load("ui/ui_manifest.yaml")["pages"]}
    shipped = {f"pages/{path.name}" for path in (BUNDLE_ROOT / "ui" / "pages").glob("*.yaml")}
    assert refs == shipped


def test_no_page_uses_a_markdown_table_or_a_bare_url() -> None:
    for path in (BUNDLE_ROOT / "ui" / "pages").glob("*.yaml"):
        for component in yaml.safe_load(path.read_text("utf-8"))["components"]:
            for line in str(component.get("body", "")).splitlines():
                assert not line.lstrip().startswith("|"), f"{path.name}: {line}"
                for word in line.split():
                    if word.startswith("http"):
                        raise AssertionError(f"{path.name}: bare URL {word}")


def test_pages_do_not_list_effect_plumbing() -> None:
    for path in (BUNDLE_ROOT / "ui" / "pages").glob("*.yaml"):
        text = path.read_text("utf-8")
        assert "external_effect_status" not in text, path.name
        assert "definitely_no_external_effect" not in text, path.name


def test_api_page_order_and_coverage(built) -> None:
    components = built["api_page"]["components"]
    assert [c["title"] for c in components[:3]] == [
        "Everyday operations",
        "How operations behave",
        "Advanced endpoints",
    ]
    assert components[-1]["title"] == "Coverage"
    everyday = components[0]["body"]
    for op in built["operations"]:
        if not op["display_name"].startswith("Advanced") and op["operation_id"] not in (
            "call_endpoint",
            "export_list",
        ):
            assert f"### {op['display_name']}" in everyday, op["operation_id"]
    bodies = "\n".join(c["body"] for c in components)
    for endpoint in catalog.ENDPOINTS_BY_OPERATION.values():
        assert f"`{endpoint.operation_id}`" in bodies
    assert "attaching files" in components[-1]["body"]


def _user_facing_texts() -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    manifest = _load("extension.yaml")
    listing = manifest.get("listing") or {}
    texts += [("display_name", manifest["display_name"]), ("description", manifest["description"])]
    texts += [("summary", str(listing.get("summary", ""))), ("tags", " ".join(listing["tags"]))]
    texts += [("account_scope", manifest["account_scope"]["description"])]
    for ctype in _load("contracts/connection_types.yaml")["connection_types"]:
        texts.append(("connection_type", yaml.safe_dump(ctype, allow_unicode=True)))
    for op in _load("contracts/operation_manifest.yaml")["operations"]:
        texts += [(op["operation_id"], op["display_name"]), (op["operation_id"], op["description"])]
    for path in (BUNDLE_ROOT / "ui" / "pages").glob("*.yaml"):
        page = yaml.safe_load(path.read_text("utf-8"))
        texts += [(path.name, page["title"]), (path.name, page["description"])]
        for component in page["components"]:
            texts.append((path.name, f"{component.get('title', '')}\n{component.get('body', '')}"))
    for doc in ("README.md", "CHANGELOG.md"):
        texts.append((doc, (BUNDLE_ROOT / doc).read_text("utf-8")))
    return texts


def test_product_name_is_spelled_rivile_in_plain_latin() -> None:
    offenders = [where for where, text in _user_facing_texts() if "Rivilė" in text]
    assert offenders == []


def test_manifest_basics() -> None:
    manifest = _load("extension.yaml")
    assert manifest["extension_id"] == "flowsteward.rivile-erp"
    assert manifest["version"] == "0.1.0"
    assert manifest["egress"]["hosts"] == [ENDPOINT_HOST]
    assert manifest["listing"]["category"] == "finance"
    categories = json.loads((BUNDLE_ROOT / "tests/reference/categories.json").read_text("utf-8"))
    assert set(manifest["listing"]["categories"]) <= set(categories)
    assert manifest["entrypoint"]["timeout_seconds"] == 600


def test_health_command() -> None:
    import health

    result = health.check_health()
    assert result["ok"] is True
    assert result["rivile_endpoints"] == 136
    assert result["openapi_sha256"] == build_contracts.SPEC_SHA256


def test_icon_is_present() -> None:
    icon = (BUNDLE_ROOT / "icon.png").read_bytes()
    assert icon.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(icon) <= 100 * 1024


def test_help_texts_are_sentences(built) -> None:
    for form in built["forms"]:
        for field in form["fields"]:
            help_text = field.get("help_text", "")
            assert len(help_text.split()) >= 4, (form["operation_id"], field["name"], help_text)


def test_notes_are_multiline(built) -> None:
    for form in built["forms"]:
        for field in form["fields"]:
            if field["name"] in {"notes", "purpose", "description"}:
                assert field["widget_type"] == "textarea", (form["operation_id"], field["name"])


def test_coded_options_have_words(built) -> None:
    forms = {form["operation_id"]: form for form in built["forms"]}
    for oid, name in (
        ("find_or_create_client", "client_type"),
        ("find_or_create_product", "product_type"),
        ("register_payment", "direction"),
        ("register_payment", "invoice_type"),
        ("changes_since", "entity"),
        ("download_document_file", "document_type"),
        ("export_list", "list"),
    ):
        field = next(f for f in forms[oid]["fields"] if f["name"] == name)
        for option in field["options"]:
            assert option["label"] != str(option["value"]), (oid, name, option)


def test_advanced_titles_are_plain_and_unique(built) -> None:
    names = [op["display_name"] for op in built["operations"]]
    assert len(names) == len(set(names))
    for name in names:
        title = name.removeprefix("Advanced · ")
        assert "/v1" not in title and " (GET" not in title, name
        head, _, rest = title.partition(": ")
        assert head.lower() != rest.lower(), name
        assert "UnPost" not in title and " qty " not in title, name


def test_every_endpoint_section_links_to_the_reference(built) -> None:
    bodies = "\n".join(c["body"] for c in built["api_page"]["components"])
    for row in built["rows"]:
        link = f"#/{row['tag']}/{row['openapi_operation_id']}"
        assert link in bodies, row["operation_id"]
        assert bodies.count(f"`{row['http_method']} {row['path']}`") >= 1


def test_every_path_id_is_a_uuid() -> None:
    for endpoint in catalog.ENDPOINTS_BY_OPERATION.values():
        for _name, _wire, fmt in endpoint.path_params:
            assert fmt == "uuid", endpoint.wire
