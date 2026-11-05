# Next steps: from prototype to Complete Fixing Solutions' real timesheets and Sage

The prototype shows the workflow on synthetic data. This is what it would take to run it on the real thing, and
where it could go wrong.

## 1. Connecting to the real systems (Sage and the internal records)

The advert mentions Sage and internal systems. The first version should fit around how the office already works,
with no new system for site teams.

| Input or output | What's needed | Effort |
|---|---|---|
| **Weekly timesheets** | How they arrive today. If they are paper sheets, they are keyed into a spreadsheet (the demo's format) or photographed; photos need OCR or Claude's image reading, which the prototype doesn't do yet. If a timesheet app is used, its CSV export; column names are mapped in `config.yaml`. | Small (spreadsheet) to medium (photos) |
| **Employee list** | Operatives' payroll IDs, hourly rates, contracted hours and overtime rates, exported from Sage 50 Payroll or kept as a list. New starters appear as exceptions until they are added. | Small |
| **Job list** | Job numbers, names and status (open or closed), from wherever jobs are tracked today. | Small |
| **Purchase orders** | The PO list (number, supplier, job, net value), from Sage or the internal PO log. | Small |
| **Supplier invoices** | Where they arrive: an accounts inbox, post scanned to PDF, or a shared folder. A month of past invoices to tune the reading and the checks. | Small |
| **Supplier list and nominal codes** | Exported from Sage 50 Accounts. Supplier default nominal codes and bank details drive the coding and the fraud check. | Small |
| **Sage 50 Accounts import** | Phase 1: the audit-trail CSV the demo produces (PI and PC lines), imported through Sage's File → Import, checked on a backup or test company first. Phase 2: post approved invoices through the Sage 50 API or an integration, once the CSV route is trusted. | Small, then medium |
| **Sage 50 Payroll** | The payroll hours file lists basic, overtime and weekend hours per operative per week. The exact layout for Sage Payroll's import (or how the hours are entered today) needs confirming and mapping. | Small to medium |

Later, only if worthwhile: read invoices from the accounts inbox automatically, keep the PO list in step with
Sage, and check new starter paperwork (starter checklist, right to work, bank details) against the personnel files.

## 2. Tuning on real data

- **Calibrate on a past week and a past month:** run real timesheets and invoices where the team already knows the
  right answers, compare the flags and hours with what was paid and posted, then adjust the rules.
- **Pay rules:** the demo uses time and a half after 40 hours and for Saturdays, and a 12-hour daily limit. Real
  rules (Sunday rates, travel time, bonuses, different contracts, holiday and sick pay) need adding to the config
  or flagging for a person.
- **Gross pay is only an estimate** for checking. Sage Payroll still calculates pay, tax, NI and pensions.
- **Purchase orders:** the tolerance (2% or £5) and which suppliers need a PO (fuel cards and utilities usually
  don't) should be agreed. The demo flags every invoice without a PO.
- **Construction tax rules:** CIS deductions and the domestic reverse charge for construction services are not
  handled. Subcontractor invoices would need those rules added and checked with the accountant.

## 3. Data protection and hosting

- **Real data must not go on the public demo link.** Streamlit Community Cloud is fine for synthetic demos only.
  Real use needs private hosting with sign-in, limited to the office team.
- **Personal data:** timesheets, pay rates, employee lists and supplier bank details are personal or sensitive data
  under UK GDPR. A data protection check (DPIA) and agreed retention are needed before go-live.
- **What goes to the AI:** supplier document text (to read it), short descriptions of uncoded invoices, the facts
  for each email (including timesheet queries, which name operatives) and the summary. Timesheet hours and pay
  are worked out in code. Anthropic's commercial terms and data retention settings should be reviewed first.
- **Audit trail:** every hour paid traces back to a timesheet line, and every invoice to its PO and document.
  Archiving each week's Excel pack gives a record of what was checked.

## 4. Risks and limitations

- **AI reading can be wrong.** Claude reads the invoices; code then checks the arithmetic, VAT, POs and dates, but
  a misread PO number or amount can slip through. Low-confidence readings go to a person, and nothing is posted
  automatically.
- **Timesheet checks only see what is on the timesheet.** They can't tell whether someone was really on site. The
  supervisor's sign-off is still the control.
- **The fraud check only covers what it can see.** It compares bank details on invoices with the supplier list. It
  is not a substitute for phoning the supplier before a change is accepted.
- **The time-saved figure is an estimate** from assumptions in `config.yaml`, not a measurement. It should be
  replaced with real timings from a pilot.
- **Prototype code:** it has unit and end-to-end tests, but it hasn't been security-reviewed or tested at volume.

## 5. Suggested pilot (3–4 weeks)

1. Week 1: export the employee list, job list, supplier list and nominal codes; collect two past weeks of
   timesheets and a month of invoices and POs; map the columns and pay rules.
2. Week 2: run the past weeks and month, compare with what was paid and posted, tune the rules.
3. Weeks 3–4: run it alongside the normal Monday-to-Wednesday process for two pay weeks, importing into a Sage
   test company first, and record the time taken and the issues caught each way.
4. Decide: adopt the CSV workflow, connect to Sage directly, or stop.
