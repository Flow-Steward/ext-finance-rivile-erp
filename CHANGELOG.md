# Changelog

## 0.1.0 — unreleased

First release, not yet verified against a live Rivile ERP company (1.0.0 follows that check).

- Every endpoint of the Rivile ERP Public API (OpenAPI document "Rivile ERP Public API" 0.1) as
  a typed workflow operation named "Advanced · …", generated from the document: path ids and query parameters as inputs, request bodies typed with Rivile's schemas,
  responses typed as outputs, list filters limited to the fields Rivile documents per list.
- Everyday operations, listed first: Find or create customer / supplier, Create sales invoice,
  Create purchase invoice, Download document file, Register payment, Find or create product,
  Stock levels, Product prices, Changes since, Client debt.
- Test the connection, Call any Rivile ERP endpoint, and Export a Rivile ERP list to a JSONL file.
- Every write is a declared external effect, suppressed in test runs; a timeout or 5xx on a write is
  reported as `timeout_unknown` and not retried (Rivile ERP has no idempotency key).
- Rivile's 400 answers become per-field errors with the JSON path of the refused field.
- Invoices take up to 100 lines, Rivile's limit for creating a document in one request. A client
  code must name an existing client; clients are created only by registration or VAT code.
- Client debt is totalled per registry type and says when it is partial.
- Not offered, because the Rivile ERP API has no upload: attaching a file to a document.
- Icon: the official Rivile mark from [rivile.lt/favicon.svg](https://www.rivile.lt/favicon.svg) (© Rivile), scaled to
  128×128 with proportions and colour unchanged, used to identify the integration.
