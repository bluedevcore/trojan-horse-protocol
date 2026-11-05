# tools/bookkeeping

One engine for the bookkeeping-type demos: invoices, receipts, statements and spreadsheets in; coded entries,
checks, accounting-system import files, drafted emails and a month-end pack out. No client names live here:
each client is a `config.yaml`, sample data and fixtures under `clients/<slug>/`.

Claude only **reads documents**, **suggests account codes** that no rule covers, and **writes emails and the
summary**. Everything else (arithmetic, VAT, matching, totals, ageing, hours, journals) is deterministic code.

## Pipeline (pipeline.py, in order)

| Step | What happens | Module | Switch (`modules.`) | Needs |
|---|---|---|---|---|
| 1 | Read PDFs, emails (with PDF attachments) and text; load spreadsheets by role | `documents.py`, `tables.py` | always | any files |
| 2 | Claude extracts fields from each document (parallel, JSON schema); pattern reader if no AI | `ai.py` | `documents` | documents |
| 3 | Arithmetic, VAT rate, VAT number (HMRC check digits), VAT without a number, bank-detail changes, duplicates, new supplier, prior/future period, prepayments, foreign currency | `documents.py`, `coding.py`, `pipeline.py` | `documents` | documents (+ `suppliers`) |
| 4 | Match card spend to receipts (amount, date, merchant name; tips; foreign currency) | `matching.py` | `card_matching` | `card_statement` |
| 5 | Ledger lines (one per VAT rate) and nominal coding: supplier list → keyword rules → Claude → fallback | `coding.py`, `ai.py` | `coding` | `chart_of_accounts` |
| 6 | Payroll report check and balanced payroll journal (difference to Suspense) | `payroll.py` | `payroll_journal` | `payroll` |
| 7 | Sales invoices from completed work (numbering, terms, VAT, PO rules) | `sales.py` | `sales_invoices` | `sales_to_invoice` (+ `customers`) |
| 8 | Aged debtors: allocate receipts, buckets, disputes, chase tiers | `sales.py` | `debtors` | `open_invoices` (+ `bank_statement`, `customers`) |
| 9 | Timesheets: hours per employee per week, overtime, weekend, approvals | `payroll.py` | `timesheets` | `timesheets` (+ `employees`) |
| 10 | Supplier invoices against purchase orders | `orders.py` | `purchase_orders` | `purchase_orders` |
| 11 | Supplier statements against invoices received | `matching.py` | `statements` | statement documents |
| 12 | File documents into project folders (+ zip) | `filing.py` | `filing` (off by default) | `projects` |
| 13 | Exceptions numbered EX-01…, holds applied to entries | `checks.py` | always | |
| 14 | Draft 9-box VAT return workings | `vat.py` | `vat_return` (off by default) | entries |
| 15 | Import CSVs for QuickBooks Online / Xero / Sage 50 | `exports.py` | `exports:` list | entries |
| 16 | Month-end checklist from this run's results | `month_end.py` | `month_end` | |
| 17 | Claude drafts emails (one per recipient) and the manager summary, in parallel | `ai.py` | `letters` | findings |
| 18 | Excel pack, PDF report, Word emails, exceptions CSV, filing zip | `reports.py` | always | |

`views.py` is the Streamlit app (`run_app(client_dir)`); tabs appear only when their table has rows.

## Inputs

**Documents** (PDF, EML, TXT): invoices, receipts, credit notes, supplier statements, contracts, letters.
Photos/scans without a text layer are reported as unreadable (OCR is a next step, not built).

**Spreadsheets** (CSV/XLSX) are loaded by **role**. Default column aliases for common UK exports are in
`tables.py` (`TABLE_SPECS`); headings are matched ignoring case and punctuation. Uploaded spreadsheets are routed
to a role from their headings; a missing reference list (`suppliers`, `customers`, `chart_of_accounts`,
`employees`, `projects`) falls back to the client's sample one, with a note.

| Role | Required columns (canonical) | Useful optional columns |
|---|---|---|
| `card_statement` | date, description, amount (+ card_last4 or cardholder) | original_currency, original_amount |
| `bank_statement` | date, description, amount (or Money in/Money out, Debit/Credit) | reference, balance |
| `suppliers` | name | account_ref, default_account, vat_code, vat_number, sort_code, account_number, terms_days, email, contact |
| `customers` | name | account_ref, email, contact, terms_days, po_required, credit_limit |
| `chart_of_accounts` | name | code, type, description |
| `payroll` | employee, gross, net_pay | employee_id, department, paye, employee_ni, employer_ni, employee_pension, employer_pension, student_loan, other_deductions (a row named TOTAL is checked against the rows) |
| `sales_to_invoice` | customer, description, quantity, unit_price | date, job, item, vat_code, po_number |
| `open_invoices` | customer, invoice_number, amount | invoice_date, due_date, paid, status (e.g. "Disputed"), project_ref |
| `timesheets` | employee, date | start, finish, break_minutes, hours, job, approved_by |
| `employees` | employee | employee_id, hourly_rate, contracted_hours, overtime_multiplier, department |
| `purchase_orders` | po_number, supplier, net_amount | date, description, job, status |
| `projects` | project_ref, project_name | client, site, keywords (`;`-separated) |

Add aliases without code: `tables: {card_statement: {aliases: {amount: ["Spend (£)"]}}}`. A `label` there
(e.g. `tables: {projects: {label: property register}}`) renames the table in the progress list and notices.

## Config keys (`clients/<slug>/config.yaml`)

```yaml
slug, client_name, tool_name, role, headline ("<Tool>: built as a prototype for <Client>"), replaces, badges,
footer, footer_short, sample_caption, upload_help
step_delay_seconds: 0.4
sample_as_of: 2026-11-05            # ageing and dates are reproducible for the sample
period: {start: 2026-10-01, end: 2026-10-31}   # sample only; uploads use the month most documents fall in
company: {name: Demo Company Ltd}   # the invented business whose books these are (never the client)
accounting_system: quickbooks       # quickbooks | xero | sage50: picks the default exports and tax codes
exports: [quickbooks_bills, ...]    # optional: list from exports.EXPORTS (default: all for the system)
export_settings: {card_payment_account, card_bank_nominal, journal_number, tax_codes: {S: ...},
                  sales_account_code, sales_nominal, tracking_as_class, tracking_name}
sample_data:
  documents: ["sample_data/inbox/*"]          # globs or file paths
  tables: {card_statement: sample_data/x.csv, suppliers: ..., chart_of_accounts: ...}   # role: path (or list)
modules: {documents, card_matching, coding, payroll_journal, sales_invoices, debtors, timesheets,
          purchase_orders, statements, filing, vat_return, letters, month_end}   # true/false
tables: {<role>: {aliases: {...}}}
coding:
  fallback_account: Suspense
  account_types: [Expense, Cost of sales, Suspense]   # chart rows Claude may choose from
  items_per_request: 12
  rules: [{match: "REGEX", account: "Name or code", vat_code: S|R|Z|E|O|RC, receipt_needed: false, reason: "..."}]
vat: {allowed_rates: [0, 5, 20], blocked_accounts: [Entertainment]}
vat_return: {start, end}            # with modules.vat_return: true (default: the period)
matching: {date_window_days: 7, near_abs: 10, near_pct: 0.15, min_name_score: 0.6, supplier_name_threshold: 0.85}
card: {missing_receipt_min_amount: 0}
checks_settings: {prepayment_min_amount: 500}
checks: {<check_id>: {severity, needs_human_check, hold, enabled, label, action}}   # override CHECKS in checks.py
payroll: {by_department: true, journal_reference: PAYROLL-OCT-2026, accounts: {wages: ..., suspense: ...}}
sales: {invoice_prefix: "INV-", first_invoice_number: 1001, default_terms_days: 30, default_vat_code: S, group_by: job}
debtors: {buckets: [0, 30, 60, 90], tiers: [{from: 1, tier: Reminder, tone: "friendly"}, ...], default_terms_days: 30}
timesheets: {overtime_after_weekly_hours: 40, overtime_multiplier: 1.5, weekend_multiplier: 1.5,
             max_daily_hours: 12, require_approval: true, expected_days: true}
purchase_orders: {tolerance_pct: 2, tolerance_abs: 5, require_po: true}
filing: {reference_pattern: "P-\\d{4}", unfiled_folder: "_To file", noun: property}   # noun: wording (default project)
contacts:
  cardholders: [{card: "4417", name: Alex Morgan, email: ...}]
  payroll_bureau: {name, contact, email}
month_end: {checklist: [{id: purchase_invoices}, {label: "Manual step", manual: true}, ...]}   # ids in month_end.py
analysis: {tracking_label: Property}   # entries carry the document's project/property ref (or the cardholder)
          # optional: entries_column: true (the ref on every coded line, screen and Excel; replaces "Coded by" on
          # screen), in_report: true (totals by tracking value in the PDF report)
views: {tabs: [entries, card, payroll, sales, debtors, hours, po, statements, filing, vat, emails, checklist,
               exceptions, documents]}
ai: {domain: "...", signature: "...", reply_by: "by Friday 13 November", letters_per_request: 3}
time_estimate:                      # counts: documents invoices receipts card_txns entries exceptions human_checks
  manual: [["label", "count key", minutes], ...]          #   emails employees sales_invoices debtor_items
  with_tool: [["label", "count key", minutes], ...]       #   timesheet_rows fixed
```

## Checks

Every check id, its default severity, whether it needs a human check, whether it holds the entries out of the
import files, and who gets an email about it are in `CHECKS` in `checks.py`. Findings with the same recipient
share one drafted email. Recipient types: `supplier` (supplier list email/contact), `cardholder`
(`contacts.cardholders`), `customer` (customer list), `payroll_bureau` (`contacts.payroll_bureau`).

## Claude tasks and mock-mode fixtures

| Task | Stable id in the prompt | Template when no AI |
|---|---|---|
| `bookkeeping.extract` | `File name: <file>` | `documents.pattern_extract` |
| `bookkeeping.coding` | entry id (`D-07`, `T-05`) + payee | fallback account, low confidence |
| `bookkeeping.letters` | key `<type>:<recipient>` | `ai.template_letter` |
| `bookkeeping.summary` | one per run | `ai.template_summary` |

Curated responses live in `clients/<slug>/fixtures/curated.json`; `refresh_fixtures.py` turns them into the hashed
fixture files that mock mode replays:

```bash
python -m tools.bookkeeping.refresh_fixtures clients/<slug> --seed   # first time: writes template text marked _todo
# edit curated.json: realistic text that uses only facts in each request; remove the _todo marks
python -m tools.bookkeeping.refresh_fixtures clients/<slug>          # after any prompt, config or data change
```

Extraction entries need only the non-empty fields. The script reports missing, stale and `_todo` entries.

## Adding a client

1. Copy `clients/cosgrove-cosgrove/` to `clients/<slug>/`; rewrite `config.yaml` (headline, `modules`,
   `accounting_system`, `sample_data`, rules, contacts, checklist, `views.tabs`, `ai`, `time_estimate`).
2. Rewrite `sample_data/generate.py` (seeded, docstring listing every planted problem; invented names,
   `.example` emails, 00- sort codes, Ofcom drama phone numbers; PDFs with `invariant=1`) and run it.
3. Write `fixtures/curated.json` (`--seed`, then edit), run `refresh_fixtures`.
4. Copy `tests/test_cosgrove_cosgrove_pipeline.py` and `tests/test_cosgrove_cosgrove_app.py`; change the expected
   findings, counts and totals. Run `pytest`, launch the app, check it at 1280×900.

Suggested modules for the other bookkeeping briefs: Xero bookkeeping + VAT return (`accounting_system: xero`,
`vat_return: true`); debtor chasing and filing (`debtors`, `filing`, `open_invoices`, `bank_statement`,
`projects`); timesheets, POs and Sage (`timesheets`, `purchase_orders`, `accounting_system: sage50`, export
`payroll_hours`); data entry and analysis for a property company (`documents`, `statements`, `projects` as the
property list, `analysis.tracking_label: Property`).
