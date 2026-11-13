# Rivile ERP workflow actions

Choose an everyday action for common invoices, clients, products and payments.
Choose **Advanced ·** actions when you need a particular provider method or record shape.
Action IDs in parentheses remain compatible with existing workflows.

## Connect and check access

Create a company API key in Rivile ERP under Settings → General → API Keys and add it to a project connection. Use a separate connection per company. Run **Test the connection** (`test_connection`) and check that the key permits the records and actions you need. Rivile GAMA uses a separate extension.

## Create an invoice from an approved order

1. Add **Create sales invoice** (`create_sales_invoice`) and select the project connection.
2. Set **Client code** to an existing client. Alternatively, give a registration code or VAT number and the name needed to create a missing client. Set **Number** to your source invoice number and **Date** to `2026-01-15`.
3. Set **Lines** to a JSON array, binding values from earlier steps as needed:

   ```json
   [{"item_code":"PRODUCT01","quantity":2,"price":12.5}]
   ```

Replace PRODUCT01 with an existing product or service code. Rivile supplies its unit when omitted; select the correct department and currency for your company. Up to 100 lines fit one create request. Leave **Post** disabled for a draft. If a later request fails, inspect the partial-result details and Rivile before repeating: a document or client may already exist.

Use the purchase invoice/vendor bill action for supplier documents; check its
partner, product and tax settings before execution. File inputs accept workflow
files from earlier steps. Download actions return workflow files for later email,
archive or document steps, rather than local filesystem paths.

## Read stock, prices, balances and changes

- **Read stock levels** (`stock_levels`): select a product and the warehouse/location filters needed for the company.
- **Read product prices** (`product_prices`): read product pricing; client/pricelist options depend on the provider.
- **Read client debt** (`client_debt`): read existing debt/balance information before a follow-up workflow.
- **Read records changed since a date** (`changes_since`): choose **What** and set **Since** to `2026-01-01T00:00:00Z`.

Pages start at 0. Pass `next_page` into **Page** while `has_more` is true; keep the same entity and timestamp during a page sequence.

**Advanced · Export a Rivile ERP list to a JSONL file** (`export_list`) reads a list route in 100-record pages and saves a workflow file. Raw **Filters** use only fields documented for that route.

## Work with advanced records

**Advanced ·** actions expose individual Public API routes. A read-by-ID action requires the actual record UUID; create/update actions take the route-specific **Body** JSON. Use the generated body schema and linked API page for its required fields. Do not send an everyday invoice Lines array as a raw API body: the two input shapes differ. Status, posting, reservation and deletion actions act on their named record type.

Read actions still contact the provider during a workflow test. Write actions are
suppressed in test mode. A lost response after a write can leave an unknown
outcome; inspect provider records and reported effects before running it again.
