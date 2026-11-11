# Rivile ERP for Flow Steward

Bring Rivile ERP cloud accounting and operational records into Flow Steward workflows. Everyday steps find or create customers, suppliers and products, create sales and purchase invoices with document lines and optional posting, register payments, download attached document files and read stock, prices and client debt. Changes-since reads help pass updated records to another system.

The release also exposes a registry of 136 Public API endpoints as typed advanced operations. Its supported families include clients and contacts, products, sales and purchase orders and invoices, deliveries, payments, receivables and payables, inventory adjustments and movements, lots, manufacturing, gift cards, employees, timesheets and workflow statuses. Supported endpoint actions include reads, creation, updates and deletion where the particular API route permits them. List export writes JSONL files for larger exchanges.

Combine these capabilities to turn storefront orders into accounting documents, exchange warehouse availability, build payment-registration workflows or connect operational records to reporting. A company-specific API key determines the connection's access. Invoice steps support optional posting, and advanced operations expose the individual document and line actions when a process needs more control. Lists and file exports provide records for subsequent workflow steps.

Create a company API key in Rivile ERP under Settings, General, API Keys, choose its validity and store it in the project connection. Use a separate connection for each company and confirm that the key permits the document and operational actions your workflow needs.

Rivile GAMA (the on-premise product with Manorivile-Gateway) has its own extension,
`flowsteward.rivile-gama`.

## Everyday operations (start here)

| Operation | What it does |
|---|---|
| Find or create customer / supplier | A client code must name an existing client; by registration code or VAT number the client is found or created. |
| Create sales invoice / Create purchase invoice | Client found (or found or created), document with up to 100 lines, optional posting; an existing number for the client is returned (and posted if asked) instead of a duplicate. |
| Download document file | Saves an attached file as a workflow file. |
| Register payment | Payment received or sent, optionally linked to an invoice and posted. |
| Find or create product | By code or barcode. |
| Stock levels, Product prices, Client debt | Plain lists and exact decimal totals. |
| Changes since | Records of one list changed after a moment (`updatedAt`). |

Raw endpoints are named "Advanced · …" in the step picker. **Call any Rivile ERP endpoint** and
**Export a Rivile ERP list to a JSONL file** complete the set.

## Getting a key

In Rivile ERP: **Nustatymai → Bendrieji → API Raktai → Sukurti naują raktą**. Choose the company
and the validity date. The key is shown once; one key belongs to one company. Every request sends
it in `X-SessionToken`. There is no sandbox; Rivile ERP's 30-day free trial can be used to test.

## Writes and failures

- Numbers use "." as the decimal separator; "1,500" is refused (it could mean 1.5 or 1500).
- Codes that go into a lookup filter (client, registration, VAT, product, barcode) are limited to
  letters, digits, spaces and `. _ / -`; codes sent only in a request body (lines, units,
  departments, currencies, accounts) may be any printable text, such as `MĖSA-01` or `m²`.

- Every POST, PATCH and DELETE is a declared external effect, suppressed in test runs.
- Rivile ERP has no idempotency key: a timeout, 5xx or lost connection after a write was sent is
  `timeout_unknown` and is never retried automatically. HTTP 429 (not documented) is retried after
  1, 2, 4 and 8 seconds; the request was not executed.
- 400 answers (`{code, values.violations}`) become one error entry per refused field, with its
  JSON path (`lines[0].itemCode`). 401 is `authentication_failed`, 404 `not_found`.
- Composite steps that fail part-way say exactly what was created (for example "client created;
  sales invoice S-3 created with 12 lines; Posting failed") and are not retried.
- The API key is removed from every answer before it is parsed or shortened.

## Development

The contracts are generated from the pinned OpenAPI document; do not edit them by hand.

```bash
python3 tests/reference/build_contracts.py     # regenerate contracts, registry and pages
```

From the Flow Steward application checkout:

```bash
./flow-steward extensions validate flowsteward.rivile-erp --root <parent> --health --marketplace
./flow-steward extensions test flowsteward.rivile-erp --root <parent> --non-interactive
./core/entrypoints/cli/scripts/lint.sh --checks extension-static,extension-tests --extension-root <abs path>
```
