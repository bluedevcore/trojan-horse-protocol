# QuickBooks Bookkeeping Agent: built as a prototype for Cosgrove & Cosgrove Ltd

A working prototype of a large part of the **Accounts Assistant** job: turning supplier invoices, receipts and
the company card statement into coded QuickBooks Online entries, preparing the payroll journal and sales
invoices, chasing what's missing, and supporting month end.

**What it does**

1. Reads 28 synthetic documents (PDF invoices and receipts, emails with attachments). Claude extracts the fields;
   code then checks the arithmetic, VAT rates, VAT numbers (HMRC check digits), bank details against the supplier
   list, duplicates and invoice dates.
2. Matches 17 company card payments to their receipts (amount, date, merchant name, tips, a US-dollar receipt)
   and lists the receipts that are missing.
3. Codes every entry to the chart of accounts: supplier list first, then keyword rules, then a Claude suggestion
   for the rest. Low-confidence suggestions go to a person. VAT on client entertaining is not reclaimed.
4. Checks the payroll bureau report and builds a balanced payroll journal (a £100 net-pay difference is posted to
   Suspense and queried). Raises 5 sales invoices from the jobs completed in October.
5. Drafts 8 emails: supplier queries, receipt requests to cardholders, a payroll query and a PO request.
6. Builds QuickBooks Online import files (bills, supplier credits, card expenses, payroll journal, sales
   invoices), a month-end checklist, an Excel pack, a PDF report and the emails as a Word file.

Anything uncertain goes on a **Needs human check** list, and entries with an open problem are held out of the
import files. Nothing is posted to QuickBooks automatically.

## Files

| Path | What it is |
|---|---|
| `app.py` | Streamlit entry point (a thin wrapper around `tools/bookkeeping`) |
| `config.yaml` | Headline and wording, modules switched on, keyword coding rules, VAT settings, contacts, month-end checklist, AI context, time-saved assumptions |
| `sample_data/` | Synthetic October 2026 month end for an invented company ("Demo Company Ltd"): `inbox/` (28 documents), card statement, payroll summary, work to invoice, supplier list, customer list, chart of accounts. `generate.py` recreates them and lists the 17 planted problems. |
| `fixtures/` | Pre-recorded AI text for the sample run, used in mock mode (see `fixtures/README.md`) |
| `DEMO_SCRIPT.md` | 60-second screen-recording script |
| `PITCH_MESSAGE.md` | Short application message |
| `NEXT_STEPS.md` | What it would take to use real data in QuickBooks Online, plus risks and limitations |

## Run it

From the repo root:

```bash
pip install -r requirements.txt
```

```bash
streamlit run clients/cosgrove-cosgrove/app.py
```

Without `ANTHROPIC_API_KEY` the app runs in **mock mode** (badge in the header) with pre-recorded AI text. See the
[root README](../../README.md) for environment variables and how to deploy on Streamlit Community Cloud with main
file path `clients/cosgrove-cosgrove/app.py`.

All data is synthetic. This is an independent prototype; it is not affiliated with or endorsed by Cosgrove &
Cosgrove Ltd or Intuit.
