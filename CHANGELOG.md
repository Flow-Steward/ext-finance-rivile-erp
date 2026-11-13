# Changelog

## 0.1.4

- Clarify everyday read action titles and add schema-compatible form examples.
- Add a workflow action guide covering setup, invoice lines, paging and advanced inputs.


## 0.1.3

### Changed

- Clarified the catalog description, supported operations and connection setup.

### Security

- Updated the CI pytest pin from 8.3.5 to 9.0.3.

## 0.1.2

### Changed

- README: internal working notes and the icon note removed.
- Releases: the release text is this version's section of the changelog, checked before anything is built,
  followed by GitHub's list of changes since the previous release.

## 0.1.1

Version number only: the same code as 0.1.0, which already contains every review fix.

## 0.1.0

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
- An invoice found by number counts as already created only when client, number and date match;
  an older document with the same number, or several same-day matches, stop the step with no
  write; a refusal to post an existing invoice fails the step.
- Stock levels report base-unit and alternative-unit quantities separately; stock levels, product
  prices and client debt take a start page and return `next_page` and `complete`.
- A malformed list answer is an error, never "not found", so it cannot lead to a create.
- Reading an answer stops at the step's time limit; Export keeps every page read when a later page
  fails and says why (`stopped_by`); a file download keeps any 2xx answer as bytes; redirects are
  refused, and unknown for writes.
- Call any Rivile ERP endpoint sends GET as a read and returns a non-JSON answer as Base64.
- Numbers take "." only; codes sent only in a request body may contain any printable letters.
- Not offered, because the Rivile ERP API has no upload: attaching a file to a document.
- Icon: the official Rivile mark from [rivile.lt/favicon.svg](https://www.rivile.lt/favicon.svg) (© Rivile), scaled to
  128×128 with proportions and colour unchanged, used to identify the integration.
