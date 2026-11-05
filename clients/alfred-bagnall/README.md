# Debtor & Filing Agent: built as a prototype for Alfred Bagnall & Sons Limited

A working prototype of a large part of the **Branch Administrator** job: reconciling the aged debtor list,
chasing what's overdue, and keeping project files in order.

**What it does**

1. Reads the branch's Excel sales ledger (26 open invoices for 10 customers) and the bank statement, and matches
   each payment received to its invoice in code: by invoice number, or by customer name and exact amount when
   the payment has no usable reference. Part payments, unmatched receipts and credit balances are flagged.
2. Ages every open invoice at the report date (current, 1–30, 31–60, 61–90, over 90 days) and picks a chase tier
   per customer: reminder, second reminder or final notice. Disputed invoices are left out of the chase.
3. Drafts one chase email per overdue customer at the right tone, with every invoice number, amount, due date
   and days overdue taken from the checked figures. Nothing is sent.
4. Reads 24 documents waiting to be filed (contracts, customer orders, variation instructions, site minutes,
   remittance advices and correspondence). Claude reads each one; code checks the job number against the project
   register, or matches the site name, then renames the file and puts it in the project's folder. Anything
   unclear stays in `_To file`.
5. Produces an Excel pack (aged debtors, customer balances, filing index, exceptions, emails), a PDF report for
   the branch manager, the chase emails as a Word file, an exceptions CSV and a zip of the filed documents.

Anything uncertain goes on a **Needs human check** list with a suggested action.

## Files

| Path | What it is |
|---|---|
| `app.py` | Streamlit entry point (a thin wrapper around `tools/bookkeeping`, with its debtors and filing modules) |
| `config.yaml` | Headline and wording, modules switched on, chase tiers and tones, filing rule, output names, suggested actions, checklist, AI context, time-saved assumptions |
| `sample_data/` | Synthetic data for an invented decorating contractor's branch ("Demo Decorating Contractors Ltd"): sales ledger (Excel), bank statement, customer list, project register and `inbox/` (24 documents). `generate.py` recreates them and lists the 11 planted problems. |
| `fixtures/` | Pre-recorded AI text for the sample run, used in mock mode (see `fixtures/README.md`) |
| `DEMO_SCRIPT.md` | 60-second screen-recording script |
| `PITCH_MESSAGE.md` | Short application message |
| `NEXT_STEPS.md` | What it would take to use real data, plus risks and limitations |

## Run it

From the repo root:

```bash
pip install -r requirements.txt
```

```bash
streamlit run clients/alfred-bagnall/app.py
```

Without `ANTHROPIC_API_KEY` the app runs in **mock mode** (badge in the header) with pre-recorded AI text. With a
key, set `CLAUDE_MODEL` too. See the [root README](../../README.md) for environment variables and how to deploy on
Streamlit Community Cloud with main file path `clients/alfred-bagnall/app.py`.

All data is synthetic. This is an independent prototype; it is not affiliated with or endorsed by Alfred Bagnall
& Sons Limited.
