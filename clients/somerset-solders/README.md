# Bookkeeping Agent: built as a prototype for Somerset Solders Ltd

A working prototype of a large part of the **part-time Accounts Administrator/Bookkeeper** job: keeping the sales
and purchase ledgers in Xero, sorting out supplier and customer invoice queries, preparing the VAT return workings
and supporting month end.

**What it does**

1. Reads 19 synthetic supplier documents (PDF invoices, emails with attachments, a supplier statement). Claude
   extracts the fields; code then checks the arithmetic, VAT rates, VAT numbers (HMRC check digits), bank details
   against the supplier list, duplicates and invoice dates.
2. Codes every bill to the chart of accounts: supplier list first, then keyword rules, then a Claude suggestion.
   Low-confidence suggestions go to a person. A mixed-rate freight invoice is split by VAT rate, and VAT on
   customer entertaining is not reclaimed.
3. Matches supplier invoices to the purchase order log (one is £450 over its PO) and reconciles a supplier
   statement (it lists an invoice that never arrived).
4. Raises 6 sales invoices from October's despatches (exports zero-rated; one held for a missing customer PO),
   matches 9 customer receipts on the bank statement to open invoices, ages the debtors and picks the chase tier.
5. Prepares draft 9-box VAT return workings from the entries that are ready to post.
6. Drafts 10 emails: supplier queries and customer chase letters, including a final notice.
7. Builds Xero import files (bills, sales invoices), a month-end checklist, an Excel pack, a PDF report and the
   emails as a Word file.

Anything uncertain goes on a **Needs human check** list, and entries with an open problem are held out of the
import files. Nothing is posted to Xero and nothing is sent to HMRC.

## Files

| Path | What it is |
|---|---|
| `app.py` | Streamlit entry point (a thin wrapper around `tools/bookkeeping`) |
| `config.yaml` | Headline and wording, modules switched on, column names, keyword coding rules, VAT and PO settings, chase tiers, month-end checklist, AI context, time-saved assumptions |
| `sample_data/` | Synthetic October 2026 month end for an invented solder manufacturer ("Demo Company Ltd"): `inbox/` (19 documents), despatches to invoice, open sales invoices, bank statement, purchase order log, supplier list, customer list, chart of accounts. `generate.py` recreates them and lists the 17 planted problems. |
| `fixtures/` | Pre-recorded AI text for the sample run, used in mock mode (see `fixtures/README.md`) |
| `DEMO_SCRIPT.md` | 60-second screen-recording script |
| `PITCH_MESSAGE.md` | Short application message |
| `NEXT_STEPS.md` | What it would take to use real data in Xero, plus risks and limitations |

## Run it

From the repo root:

```bash
pip install -r requirements.txt
```

```bash
streamlit run clients/somerset-solders/app.py
```

Without `ANTHROPIC_API_KEY` the app runs in **mock mode** (badge in the header) with pre-recorded AI text. See the
[root README](../../README.md) for environment variables and how to deploy on Streamlit Community Cloud with main
file path `clients/somerset-solders/app.py`.

All data is synthetic. This is an independent prototype; it is not affiliated with or endorsed by Somerset Solders
Ltd or Xero.
