# Timesheet-to-Payroll Agent: built as a prototype for Complete Fixing Solutions

A working prototype of a large part of the **Office Administrator** job: checking the weekly timesheets and
turning them into payroll hours, matching supplier invoices to purchase orders, and preparing the Sage 50 import
and the queries that need sending.

**What it does**

1. Reads a week of timesheets (95 lines for 18 operatives, w/c 26 October 2026). Code works out the hours from
   start and finish times less breaks, splits basic, overtime and weekend hours for each person, and checks every
   line: signed off by a supervisor, overlapping times, a day over the 12-hour limit, hours keyed wrongly, a line
   keyed twice, hours on a closed job or a job that doesn't exist, someone not on the employee list (a new starter
   without paperwork), and anyone with no timesheet at all.
2. Builds the **payroll hours file**: one line per operative for the week. Weeks with an open problem (unsigned,
   overlapping, not on the employee list) are held out until a person clears them.
3. Reads 18 supplier invoices and emails (PDF and .eml). Claude extracts the fields; code checks the arithmetic,
   VAT numbers (HMRC check digits), bank details against the supplier list and duplicates.
4. Matches every invoice to the purchase order list: by PO number, or by supplier and amount when no PO is quoted.
   It keeps a running total per PO, so a second delivery that takes a PO over its value is caught, and lists the
   POs still awaiting an invoice.
5. Codes each invoice to the Sage nominal codes (supplier defaults first, Claude for a new supplier) and builds a
   **Sage 50 audit-trail import** (PI and PC lines, with the job number as the project reference). Held invoices
   are left out.
6. Drafts 7 emails: 6 supplier queries and one list of timesheet queries for the contracts manager.
7. Produces a checklist, an Excel pack (hours, hours by job, every timesheet line, PO matching, entries,
   exceptions), a PDF report and the emails as a Word file.

Anything uncertain goes on a **Needs human check** list. Nothing is posted to Sage automatically.

## Files

| Path | What it is |
|---|---|
| `app.py` | Streamlit entry point (a thin wrapper around `tools/bookkeeping`) |
| `config.yaml` | Headline and wording, modules switched on, timesheet rules (overtime, weekend rate, daily limit), PO tolerance, contacts, checklist, AI context, time-saved assumptions |
| `sample_data/` | Synthetic data for an invented drylining and ceilings firm near Wrexham ("Demo Fixings Ltd"): weekly timesheets (Excel), employee list, job list, purchase orders, supplier list, Sage nominal codes, and `inbox/` (18 documents). `generate.py` recreates them and lists the 18 planted problems. |
| `fixtures/` | Pre-recorded AI text for the sample run, used in mock mode (see `fixtures/README.md`) |
| `DEMO_SCRIPT.md` | 60-second screen-recording script |
| `PITCH_MESSAGE.md` | Short application message |
| `NEXT_STEPS.md` | What it would take to use real timesheets and Sage, plus risks and limitations |

## Run it

From the repo root:

```bash
pip install -r requirements.txt
```

```bash
streamlit run clients/complete-fixing-solutions/app.py
```

Without `ANTHROPIC_API_KEY` the app runs in **mock mode** (badge in the header) with pre-recorded AI text. See the
[root README](../../README.md) for environment variables and how to deploy on Streamlit Community Cloud with main
file path `clients/complete-fixing-solutions/app.py`.

All data is synthetic. This is an independent prototype; it is not affiliated with or endorsed by Complete Fixing
Solutions or Sage.
