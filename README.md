# Rivile ERP for Flow Steward

`flowsteward.rivile-erp` connects Flow Steward workflows to the **Rivile ERP Public API**
(`https://erp.rivile.cloud/public-api`), the cloud ERP from Rivile. Every endpoint of Rivile's
OpenAPI document ([Swagger UI](https://erp.rivile.cloud/public-api/swagger-ui/index.html),
[guide](https://guide.rivile.cloud/integrative_solutions/api)) is a typed workflow operation —
**136 endpoints**, 43 reads and 93 writes — plus everyday steps that make several calls for you.

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

## Assumptions not yet verified against a live Rivile ERP company

1. The list `filter` is sent as a JSON array (`[{...},{...}]`), as in Rivile's Python sample and
   the OpenAPI type; the guide's printed URL shows the objects without brackets.
2. Pages count from 0 (`page=0` in the guide) and `totalPages` ends paging.
3. `GET /v1/users/api-keys` answers 2xx for a valid key (used by Test the connection).
4. `register_payment` sends the amount as `amountCur`; `typeId` 5 is received, 4 sent (from the
   schema description).
5. Client debt sums `totalBaseDue` of `/v1/pr-registries` as Rivile reports it; overdue is the
   part with `overDueDays > 0`.
6. A new product is created with `bomTypeId` 1 (Single); unit and barcode go into
   `productUnitOfMeasure`.
7. Invoice lines take the header's `departmentCode` unless a line names its own.
8. A request answered with HTTP 429 was not executed (HTTP convention; Rivile documents no rate
   limit), so it is retried after 1, 2, 4 and 8 seconds — writes included.
9. Which `statusId` means "posted" is not documented: an existing invoice is reported with its raw
   `status_id` and `posted: null` unless the step posts it.
10. Find or create customer / product report `external_effect_status: succeeded` even when they
    only found the record: Core has no "success without effect" status an extension may report
    ("suppressed" is reserved to the host), and "failed" would turn a successful run into a failure.
    The ledger therefore records these steps as completed effects.
11. An invoice found by number counts as "already created" only when client, number and operation
    date all match; the same number on another date stops the step. Rivile documents no "already
    posted" error, so any refusal to post fails the step.

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

## Icon

`icon.png` is the Rivile logo, © Rivile, used to identify the integration. Source:
https://www.rivile.lt/favicon.svg (the embedded image), scaled to 128×128 on a transparent
background with its proportions and colour unchanged.
