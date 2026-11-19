# Rivile ERP integration for Flow Steward

<img src="icon.png" width="96" alt="Rivile ERP integration for Flow Steward">

[![CI](https://img.shields.io/github/actions/workflow/status/Flow-Steward/ext-finance-rivile-erp/ci.yml?branch=main&label=CI)](https://github.com/Flow-Steward/ext-finance-rivile-erp/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/Flow-Steward/ext-finance-rivile-erp)](https://github.com/Flow-Steward/ext-finance-rivile-erp/releases/latest)

Automate Rivile ERP with Flow Steward workflows and AI agents: create invoices, clients and products, register payments and read stock — without writing code.

This Flow Steward extension is an ERP and accounting integration for companies in Lithuania that
work with Rivile ERP. It connects the Rivile ERP cloud to workflow automation through its REST API
(Public API), so invoices, clients, items and stock come from any system without retyping.

## What is this

Rivile ERP is Rivile's cloud accounting and ERP system: there is nothing to install. This
extension is a connector: it adds ready workflow steps to Flow Steward, and the same steps are
available as tools for AI agents. Learn more about Flow Steward at
[docs.flowsteward.org](https://docs.flowsteward.org).

## What you can automate

- Create sales invoices in Rivile ERP from orders in your shop — the client is found or created, no retyping.
- Enter supplier invoices as purchase invoices with their lines, optionally posted.
- Register payments received or sent and link them to their invoices.
- Send stock levels and product prices from Rivile ERP to your online shop.
- Turn approved sale orders into sale invoices.
- Pass records changed since the last run to another system.
- Check a client's debt before a new order is shipped.

## Why teams use it

- **No duplicate records.** Clients and products are looked up before they are created, and an invoice number Rivile ERP already has for the client is not created a second time.
- **Exact amounts.** Amounts are handled as exact decimals; an ambiguous number such as "1,500" is refused rather than guessed.
- **A change is never sent twice.** When the answer to a write is lost, the step reports the outcome as unknown and does not retry it.
- **A test run changes nothing.** Every write is skipped in test runs, so you can try a workflow safely.
- **The whole API.** Each of the 136 Rivile ERP Public API endpoints has its own step.
- **The key stays secret.** It is stored encrypted and removed from every answer before it is read.

## What's inside

Everyday steps:

- **Test the connection** — checks the API key, read-only.
- **Find or create customer / supplier** — by client code, registration code or VAT number.
- **Create sales invoice**, **Create purchase invoice** — up to 100 lines in one request, optionally posted.
- **Register payment** — received or sent, optionally linked to an invoice.
- **Download document file** — an attached file as a workflow file.
- **Find or create product** — by code or barcode.
- **Read stock levels**, **Read product prices** — plain lists with exact decimals.
- **Read records changed since a date** — records of one kind changed after a moment.
- **Read client debt** — exact decimal totals.

All 136 Rivile ERP Public API endpoints are available as steps (149 steps in total, with **Call any Rivile ERP endpoint** and **Export a Rivile ERP list to a JSONL file**): clients and contacts, products, sale and purchase orders and invoices, deliveries, payments, receivables and payables, inventory adjustments and movements, lots, manufacturing, gift cards, employees, timesheets and workflow statuses. The [workflow action guide](docs/workflow-actions.md) shows examples.

## Get started

1. In Flow Steward, open **Extensions → Catalog** and install **Rivile ERP**.
2. In Rivile ERP, open **Nustatymai → Bendrieji → API Raktai**, press **Sukurti naują raktą**, choose the company and the validity date, and copy the key. In the extension's **Connection** page, add a connection named after the company and paste the key.
3. Press **Test connection**.
4. Build your first workflow, for example **Create sales invoice** from a new shop order.

## Requirements

- A Rivile ERP company and a user who may change settings, to create the API key.
- An API key: one key belongs to one company and gives full API access to it. Rivile shows it only once; for another company, create another key and connection.
- Numbers use "." as the decimal separator.
- Flow Steward 0.9.16 or later.

## FAQ

**How do I connect Rivile ERP to my online shop?**
Install the extension, add the Rivile ERP API key as a connection, and use **Create sales invoice** for new orders and **Read stock levels** and **Read product prices** to update the shop.

**Where do I create a Rivile ERP API key?**
In Rivile ERP under **Nustatymai → Bendrieji → API Raktai → Sukurti naują raktą**. Choose the company and the validity date; the key is shown once.

**Will running a workflow again create the same invoice twice?**
No. When Rivile ERP already has an invoice with that number for the client, the step does not create a second one.

**Can I try it before using it on a working company?**
Yes. Create a key in Rivile ERP's 30-day free trial, and use test runs, which skip every write.

**Is this the same as the Rivile GAMA extension?**
No. Rivile GAMA, installed at the company with Manorivile-Gateway, has its own extension, `flowsteward.rivile-gama`.

## In your language

Rivile ERP integracija su Flow Steward per Rivile ERP REST API automatizuoja debesų apskaitą: sąskaitos faktūros, klientai, prekės, mokėjimai ir likučiai keliauja iš kitų sistemų be rankinio įvedimo. Plėtinys apima visus 136 Rivile ERP Public API veiksmus.

## Links

- [Flow Steward documentation](https://docs.flowsteward.org)
- [Flow Steward extension catalog](https://github.com/Flow-Steward/extensions)
- [Issues](https://github.com/Flow-Steward/ext-finance-rivile-erp/issues)
- [Rivile ERP API reference](https://erp.rivile.cloud/public-api/swagger-ui/index.html) · [Rivile guide: API](https://guide.rivile.cloud/integrative_solutions/api)

## For developers

The contracts are generated from the pinned OpenAPI document; do not edit them by hand.

```bash
python3 tests/reference/build_contracts.py   # regenerate contracts, registry and pages
```

From a Flow Steward checkout:

```bash
./flow-steward extensions validate flowsteward.rivile-erp --root <parent> --health --marketplace
./flow-steward extensions test flowsteward.rivile-erp --root <parent> --non-interactive
./core/entrypoints/cli/scripts/lint.sh --checks extension-static,extension-tests --extension-root <abs path>
```

Rivile, Rivile ERP and their marks belong to their owner; see [BRANDING.md](BRANDING.md).
