# Next steps: from prototype to Cosgrove & Cosgrove's real books

The prototype shows the workflow on synthetic data. This is what it would take to run it on the real thing, and
where it could go wrong.

## 1. Connecting to the real systems (QuickBooks Online and Excel)

The advert mentions Excel, QuickBooks and QuickBooks Online. The first version should fit around how the team
already works, with no new system.

| Input or output | What's needed | Effort |
|---|---|---|
| **Supplier invoices and receipts** | Where they arrive today: an accounts inbox, a scanning app or a shared folder. A copy of a month's documents to tune the reading and the checks. | Small |
| **Chart of accounts, supplier and customer lists** | Exported from QuickBooks Online (Lists → Export) or read through the QuickBooks API. Supplier default accounts, VAT codes and bank details drive most of the coding and the fraud check. | Small |
| **Company card statements** | The card provider's CSV export. Column names are mapped in `config.yaml`, so a different layout is usually a config change. | Small |
| **Payroll bureau report** | The bureau's monthly summary (CSV or Excel), plus the account names used for the payroll journal. | Small |
| **Jobs to invoice** | Wherever completed work is recorded today (a spreadsheet, a job system). | Small to medium |
| **QuickBooks import** | Phase 1: the CSV files the demo produces, imported through QuickBooks Online's own import screens (bills, invoices, journals) and checked on the first import. Card expenses and supplier credits have no built-in CSV import, so they would go through the API or the bank feed's rules. | Small |
| **QuickBooks API** | Phase 2: post approved bills, expenses and journals directly through the QuickBooks Online Accounting API (OAuth app, sandbox company first), attach the source document to each entry, and read back the supplier list and chart of accounts. Nothing is posted until a person approves it. | Medium |

Later, only if worthwhile: read new documents from the accounts inbox automatically (Microsoft 365 or Gmail),
reconcile the bank feed, and add an approval screen for the finance manager.

## 2. Tuning on real data

- **Calibrate on a past month:** run last month's real documents, where the team already knows the right answers.
  Compare the coding and the flags with what was actually posted, then adjust the keyword rules, supplier
  defaults and tolerances.
- **Coding rules:** most coding should come from the supplier list and simple rules; Claude only suggests the rest.
  Each month's corrections can become new rules.
- **Scanned and photographed receipts:** the demo reads PDFs and emails with a text layer. Photos need OCR, or
  Claude's image input, which the prototype doesn't use yet.
- **VAT:** partial exemption, flat-rate schemes, domestic reverse charge for construction services and
  fuel scale charges are not handled. The VAT treatment of unusual items should be agreed with the accountant.
- **Payroll:** the demo checks the bureau's arithmetic; it does not calculate PAYE, NI or pensions.

## 3. Data protection and hosting

- **Real data must not go on the public demo link.** Streamlit Community Cloud is fine for synthetic demos only.
  Real use needs private hosting with sign-in, limited to the finance team.
- **Personal data:** payroll reports, staff names and supplier bank details are personal or sensitive data under
  UK GDPR. A data protection check (DPIA) and agreed retention are needed before go-live.
- **What goes to the AI:** document text (to read it), short descriptions of uncoded items, and the facts for
  each email. Payroll figures only reach the AI when a payroll query email is drafted. Anthropic's commercial terms and data retention
  settings should be reviewed and agreed first; staff names in emails could be pseudonymised if required.
- **Audit trail:** every entry keeps its source document, how it was coded and why, and every exception keeps the
  finding and the suggested action. Archiving each month's Excel pack gives a record of what was checked.

## 4. Risks and limitations

- **AI reading can be wrong.** Claude reads the documents; code then checks the arithmetic, VAT and dates, but a
  misread supplier name or invoice number can slip through. Low-confidence readings and coding go to a person,
  and nothing is posted automatically.
- **The fraud check only covers what it can see.** It compares bank details on invoices with the supplier list.
  It is not a substitute for the phone call to the supplier before a change is accepted.
- **Rules miss what nobody has written a rule for,** and may flag things that are fine. Hence the human-check
  list and the calibration step.
- **The time-saved figure is an estimate** from assumptions in `config.yaml`, not a measurement. It should be
  replaced with real timings from a pilot.
- **Prototype code:** it has unit and end-to-end tests, but it hasn't been security-reviewed or tested at volume.

## 5. Suggested pilot (2–4 weeks)

1. Week 1: export the chart of accounts, supplier and customer lists from QuickBooks Online; collect one past
   month's invoices, receipts, card statement and payroll report; map the columns.
2. Week 2: run the past month, compare with what was posted, tune the rules and the checks.
3. Weeks 3–4: run it alongside the normal process for one month end, importing the CSVs into a QuickBooks
   sandbox company first, and record the time taken and the issues caught each way.
4. Decide: adopt the CSV workflow, move to the QuickBooks API, or stop.
