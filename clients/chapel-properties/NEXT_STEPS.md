# Next steps: from prototype to Chapel Properties' real ledgers

The prototype shows the workflow on synthetic data. This is what it would take to run it on the real thing, and
where it could go wrong.

## 1. Connecting to the real systems (Excel and the accounting software)

The advert names Excel and "standard accounting software" across the sales, purchase and nominal ledgers, but
not the package. The first version should fit around how the team already works, with no new system.

| Input or output | What's needed | Effort |
|---|---|---|
| **Supplier invoices, credit notes and statements** | Where they arrive today: an accounts inbox, post that is scanned, or a shared folder. A copy of one month's documents to tune the reading and the checks. | Small |
| **Property register** | The list of properties (and units) with a short name or code for each, plus head office. This drives the property on every line. | Small |
| **Chart of accounts and supplier list** | Exported from the accounting package. Supplier default accounts, VAT numbers and bank details drive most of the coding and the fraud check. | Small |
| **Excel outputs** | The Excel pack already has the coded lines (with property and account), totals by property and by account, the statement reconciliation and the exceptions. A sheet can be laid out to match the property cost report the directors already receive. | Small |
| **Import into the accounting package** | Phase 1: CSV import. The demo produces a Xero bills file with the property as a tracking category; Sage 50 and QuickBooks Online layouts are built in too. In Sage the property would map to a department or project, in QuickBooks to a class or location, set up once. | Small to medium |
| **API connection** | Phase 2, only if worthwhile: post approved bills straight into the package through its API, attach the source document to each one, and read the supplier list back. Nothing is posted until a person approves it. | Medium |

The same engine can also cover the sales ledger (rent and service charge demands, tenant arrears from a bank
statement export), which is not switched on in this demo.

## 2. Tuning on real data

- **Calibrate on a past month:** run last month's real documents, where the team already knows the answers.
  Compare the coding, the property and the flags with what was posted, then adjust the keyword rules, supplier
  defaults and tolerances.
- **Property matching:** contractors often write "Flat 2" or a street name only. Adding the names and addresses
  people actually use to the property register (the keywords column) reduces the "could not tell which property"
  checks; anything still unclear stays with a person.
- **Scanned and photographed invoices:** the demo reads PDFs and emails with a text layer. Paper invoices need
  OCR, or Claude's image input, which the prototype doesn't use yet.
- **VAT:** the demo records the VAT shown on each invoice. A mixed portfolio (residential lets are exempt,
  commercial units may be opted to tax) usually means partial exemption, worked out at the VAT return with the
  accountant; the demo does not do that calculation. The domestic reverse charge for building work and the
  Construction Industry Scheme (CIS) deductions on contractor invoices are not handled either.
- **Service charges and recharges:** costs on blocks where tenants pay a service charge, and repairs that can be
  recharged to a commercial tenant, could carry an extra tag so they flow into service charge accounts and
  recharge invoices. That needs agreeing with the team first.

## 3. Data protection and hosting

- **Real data must not go on the public demo link.** Streamlit Community Cloud is fine for synthetic demos only.
  Real use needs private hosting with sign-in, limited to the accounts team.
- **Personal data:** tenant names, sole-trader contractors and bank details are personal data under UK GDPR. A
  data protection check (DPIA) and agreed retention are needed before go-live.
- **What goes to the AI:** document text (to read it), short descriptions of items no rule covers, and the facts
  for each email and the summary. Anthropic's commercial terms and data retention settings should be reviewed and
  agreed first.
- **Audit trail:** every line keeps its source document, its property, how it was coded and why, and every
  exception keeps the finding and the suggested action. Archiving each month's Excel pack gives a record of what
  was checked.

## 4. Risks and limitations

- **AI reading can be wrong.** Claude reads the documents and picks the property; code then checks the
  arithmetic, VAT, dates and the statement, but a misread name or reference can slip through. Low-confidence
  readings and coding go to a person, and nothing is posted automatically.
- **The fraud check only covers what it can see.** It compares bank details on invoices with the supplier list.
  It is not a substitute for the phone call to the supplier before a change is accepted.
- **Rules miss what nobody has written a rule for,** and may flag things that are fine. Hence the human-check
  list and the calibration step. Repair versus capital decisions always stay with a person.
- **The time-saved figure is an estimate** from assumptions in `config.yaml`, not a measurement. It should be
  replaced with real timings from a pilot.
- **Prototype code:** it has unit and end-to-end tests, but it hasn't been security-reviewed or tested at volume.

## 5. Suggested pilot (2–4 weeks)

1. Week 1: export the chart of accounts and supplier list, agree the property register, and collect one past
   month's invoices, credit notes and supplier statements.
2. Week 2: run the past month, compare with what was posted, tune the rules, the property keywords and the checks.
3. Weeks 3–4: run it alongside the normal process for one month, importing the CSV into a test company first,
   and record the time taken and the issues caught each way.
4. Decide: adopt the spreadsheet and CSV workflow, connect it through the accounting package's API, or stop.
