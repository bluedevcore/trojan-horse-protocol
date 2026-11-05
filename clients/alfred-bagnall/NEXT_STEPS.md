# Next steps: from prototype to the Erith branch's real files

The prototype shows the workflow on synthetic data. This is what it would take to run it on the real thing, and
where it could go wrong.

## 1. Connecting to the real systems (Excel first)

The advert mentions Excel. The first version should fit around how the branch already works, with no new system.

| Input or output | What's needed | Effort |
|---|---|---|
| **Sales ledger / aged debtors** | The spreadsheet the branch keeps today, or an aged debtors export from the accounts system. Column names are mapped in `config.yaml` (Customer, Invoice No, Dates, Amount, Paid, Job), so a different layout is usually a config change. | Small |
| **Bank statement** | The bank's CSV export for the period (online banking). Money in / money out or a signed amount both work. | Small |
| **Customer list** | Accounts contact, email, payment terms and credit limit for each customer. Missing emails are flagged. | Small |
| **Project register** | The list of live jobs: job number, name, client, site and any other names people use for the site. This drives the filing. | Small |
| **Documents to file** | Where they arrive today: the branch inbox, a scanner folder or a shared drive. Phase 1: drop a batch into the app. Phase 2: read new emails and attachments from the branch mailbox (Microsoft 365) and write straight into the project folders on SharePoint or the shared drive. | Small, then medium |
| **Outputs** | Phase 1: the Excel pack, the PDF report and the Word file of chase emails, checked and sent by the branch administrator. Phase 2: put each approved email into Outlook as a draft, and write the matched receipts back to the sales ledger spreadsheet. Nothing would be sent or posted without a person approving it. | Small, then medium |

## 2. Tuning on real data

- **Calibrate on a past month:** run last month's ledger, bank statement and documents, where the branch already
  knows the answers. Compare the matching, chase tiers and filing with what was actually done, then adjust the
  rules, tones and site keywords.
- **Remittance advices:** the prototype files remittances but does not yet use them to allocate payments. Reading
  them would clear payments that cover several invoices or arrive without a reference.
- **Construction payment terms:** retentions, applications for payment, payment and pay less notices, CIS
  deductions and domestic reverse charge VAT are not handled. A payment net of retention or CIS would show as
  unmatched for a person to allocate.
- **Chase rules:** the tiers (1, 31 and 61 days overdue), the wording and who approves a final notice should be
  agreed with the branch manager. Statutory late payment interest is not calculated.
- **Scanned and photographed documents:** the prototype reads PDFs and emails with a text layer. Photos and scans
  need OCR or Claude's image input, which the prototype doesn't use yet.

## 3. Data protection and hosting

- **Real data must not go on the public demo link.** Streamlit Community Cloud is fine for synthetic demos only.
  Real use needs private hosting with sign-in, limited to the branch team.
- **Personal data:** customer contacts, residents' names in correspondence and bank details are personal or
  sensitive data under UK GDPR. A data protection check (DPIA) and agreed retention are needed before go-live.
- **What goes to the AI:** document text (to read and classify it) and the facts for each email. The ledger,
  bank matching and ageing never leave the code. Anthropic's commercial terms and data retention settings should
  be reviewed and agreed first.
- **Audit trail:** every filed document keeps its original name, the folder chosen and how it was chosen; every
  exception keeps the finding and the suggested action. Archiving each run's Excel pack gives a record.

## 4. Risks and limitations

- **AI reading can be wrong.** Claude reads the documents; code then checks the job number against the project
  register. A misread or mistyped job number could file a document in the wrong folder, so the filing index is
  checked before the files are moved.
- **Matching by name and amount can be fooled** when one customer has two invoices for the same amount and pays
  without a reference. Payments matched without an invoice number should be spot-checked against the bank
  statement (the "Received" column in the Aged debtors table) before the ledger is updated.
- **A chase can cross with a payment.** If money arrives after the bank export, a reminder may go to a customer
  who has just paid. Running it on the latest statement and checking the unmatched payments first reduces this.
- **The time-saved figure is an estimate** from assumptions in `config.yaml`, not a measurement. It should be
  replaced with real timings from a pilot.
- **Prototype code:** it has unit and end-to-end tests, but it hasn't been security-reviewed or tested at volume.

## 5. Suggested pilot (2–4 weeks)

1. Week 1: collect the sales ledger, one month's bank export, the customer list, the job list and a sample of
   documents from the shared drive; map the columns and site names.
2. Week 2: run a past month, compare with what the branch did, tune the matching, chase tiers and filing rules.
3. Weeks 3–4: run it alongside the normal process each week, with the branch administrator checking every email
   and filing decision; record the time taken and the issues caught each way.
4. Decide: keep the Excel workflow, connect it to the mailbox and shared drive, or stop.
