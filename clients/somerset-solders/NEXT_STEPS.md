# Next steps: from prototype to Somerset Solders' real books

The prototype shows the workflow on synthetic data. This is what it would take to run it on the real thing, and
where it could go wrong.

## 1. Connecting to Xero

The advert mentions Xero. The first version should fit around how the books are kept today, with no new system.

| Input or output | What's needed | Effort |
|---|---|---|
| **Supplier invoices, credit notes and statements** | Where they arrive today: an accounts inbox, Xero's own bills inbox or a shared folder. A copy of one month's documents to tune the reading and the checks. | Small |
| **Chart of accounts, supplier and customer lists** | Exported from Xero (Accounting → Chart of accounts → Export; Contacts → Export) or read through the Xero API. Supplier default accounts, VAT rates and bank details drive most of the coding and the fraud check. | Small |
| **Despatches to invoice** | Wherever despatch notes or sales orders are recorded today (a spreadsheet, a stock or order system). Column names are mapped in `config.yaml`. | Small to medium |
| **Open sales invoices and bank receipts** | Xero's aged receivables (or the invoices list) and the bank statement CSV. Through the API, Xero's own invoice and bank transaction data. | Small |
| **Purchase orders** | Xero's purchase orders, or the existing PO log. | Small |
| **Xero import** | Phase 1: the CSV files the demo produces, loaded with Xero's own bill and sales invoice CSV import, with the column mapping checked on the first import. | Small |
| **Xero API** | Phase 2: create bills and sales invoices as **drafts** through the Xero Accounting API (OAuth app, Xero demo company first), so a person approves each one in Xero; attach the source PDF to each bill; read back contacts, accounts and payments. Nothing is approved or paid automatically. | Medium |

Later, only if worthwhile: pick up new documents from the accounts inbox automatically, suggest bank
reconciliation matches, and add an approval screen for the managing director.

## 2. VAT returns

- **The demo prepares workings for the period it processes** (one month in the sample). For a quarterly return,
  run it over the quarter's transactions read from Xero, then compare with Xero's own VAT return report.
- **Xero files the return with HMRC under Making Tax Digital.** The tool's workings are a cross-check and a list
  of points to resolve first; it never submits anything.
- **Not handled yet:** postponed VAT accounting on imported metal (import VAT shown on the monthly C79 or PVA
  statement), evidence that zero-rated exports left the UK, partial exemption, the flat-rate scheme and bad-debt
  relief. The VAT treatment of unusual items should be agreed with the company's accountant.

## 3. Tuning on real data

- **Calibrate on a past month:** run last month's real documents, where the right answers are already known.
  Compare the coding and the flags with what was actually posted, then adjust the keyword rules, supplier defaults
  and tolerances (for example the PO tolerance, set at 2% or £5).
- **Coding rules:** most coding should come from the Xero supplier defaults and simple rules; Claude only suggests
  the rest. Each month's corrections can become new rules.
- **Metal prices:** surcharges for tin or silver price movements are common. The PO check flags them so a person
  can agree them; it does not judge whether a surcharge is fair.
- **Scanned and photographed documents:** the demo reads PDFs and emails with a text layer. Photos need OCR, or
  Claude's image input, which the prototype doesn't use yet.
- **Supplier credit notes:** the Xero file and the VAT workings handle them correctly, but two on-screen totals in
  the prototype (the "purchases ready" figure and the totals by account) add them instead of taking them off. This
  needs fixing before real use.

## 4. Data protection and hosting

- **Real data must not go on the public demo link.** Streamlit Community Cloud is fine for synthetic demos only.
  Real use needs private hosting with sign-in, limited to the people who keep the books.
- **Personal data:** customer and supplier contacts and bank details are personal or sensitive data under UK GDPR
  (sole traders especially). A data protection check (DPIA) and agreed retention are needed before go-live.
- **What goes to the AI:** document text (to read it), short descriptions of uncoded items, and the facts for each
  email. Anthropic's commercial terms and data retention settings should be reviewed and agreed first.
- **Audit trail:** every entry keeps its source document, how it was coded and why, and every exception keeps the
  finding and the suggested action. Archiving each month's Excel pack gives a record of what was checked.

## 5. Risks and limitations

- **AI reading can be wrong.** Claude reads the documents; code then checks the arithmetic, VAT and dates, but a
  misread supplier name or invoice number can slip through. Low-confidence readings and coding go to a person,
  and nothing is posted automatically.
- **The fraud check only covers what it can see.** It compares bank details on invoices with the supplier list.
  It is not a substitute for the phone call to the supplier before a change is accepted.
- **Receipt matching is by invoice number, or customer name and exact amount.** Payments that cover several
  invoices or deduct a credit are left unallocated for a person, as in the sample.
- **Rules miss what nobody has written a rule for,** and may flag things that are fine. Hence the human-check list
  and the calibration step.
- **The time-saved figure is an estimate** from assumptions in `config.yaml`, not a measurement. It should be
  replaced with real timings from a pilot.
- **Prototype code:** it has unit and end-to-end tests, but it hasn't been security-reviewed or tested at volume.

## 6. Suggested pilot (2–4 weeks)

1. Week 1: export the chart of accounts, contacts, open invoices and purchase orders from Xero; collect one past
   month's supplier documents, statements, despatch list and bank statement; map the columns.
2. Week 2: run the past month, compare with what was posted and with that period's VAT workings, tune the rules
   and the checks.
3. Weeks 3–4: run it alongside the normal process for one month end, importing the CSVs into the Xero demo company
   first, and record the time taken and the issues caught each way.
4. Decide: adopt the CSV workflow, move to the Xero API, or stop.
