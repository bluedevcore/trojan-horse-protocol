# Financial Data Entry Agent: built as a prototype for Chapel Properties Ltd

A working prototype of a large part of the **Accounts Administrator** job at a property company: high-volume
purchase-ledger data entry, by property and nominal account, with the checks and the analysis that go with it.
Invoices and statements go in; a spreadsheet of coded lines, totals by property and account, an exceptions list
and a short summary come out.

**What it does**

1. Reads 24 synthetic documents (PDF invoices, emails with attachments, a credit note and a supplier statement).
   Claude extracts the fields and the property each one relates to; code then checks the arithmetic, VAT rates,
   VAT numbers (HMRC check digits), bank details against the supplier list, duplicates and invoice dates.
2. Codes every line to the chart of accounts: supplier list first, then keyword rules, then a Claude suggestion
   for the rest. Low-confidence suggestions (is a new kitchen a repair or an improvement?) go to a person.
3. Puts the property on every line and totals the costs by property and by account (screen, Excel and PDF).
   Anything it cannot place, such as a locksmith's invoice that only says "Flat 2", is flagged, not guessed.
4. Reconciles the supplier statement against the invoices received: one invoice is missing and one amount
   differs.
5. Flags prepayments (the portfolio insurance and a half-yearly service charge) and invoices dated outside the
   month, files every document into a property folder, and drafts 5 supplier query emails.
6. Builds a Xero bills import file (with the property as a tracking category), an Excel pack, a PDF report, the
   emails as a Word file, the exceptions as CSV and the filed documents as a ZIP.

Anything uncertain goes on a **Needs human check** list, and lines with an open problem are held out of the
import file. Nothing is posted automatically.

## Files

| Path | What it is |
|---|---|
| `app.py` | Streamlit entry point (a thin wrapper around `tools/bookkeeping`) |
| `config.yaml` | Headline and wording, modules switched on, keyword coding rules, check wording, month-end checklist, AI context, time-saved assumptions |
| `sample_data/` | Synthetic October 2026 for an invented company ("Demo Properties Ltd") with 7 properties near Ipswich: `inbox/` (24 documents), supplier list, chart of accounts, property register. `generate.py` recreates them and lists the 15 planted problems. |
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
streamlit run clients/chapel-properties/app.py
```

Without `ANTHROPIC_API_KEY` the app runs in **mock mode** (badge in the header) with pre-recorded AI text. See the
[root README](../../README.md) for environment variables and how to deploy on Streamlit Community Cloud with main
file path `clients/chapel-properties/app.py`.

The advert does not name the accounting package, so the demo produces Xero CSVs (tracking categories suit
per-property analysis). Changing `accounting_system` in `config.yaml` to `sage50` or `quickbooks` switches the
import files; see `NEXT_STEPS.md` for how the property would map in those packages.

All data is synthetic. This is an independent prototype; it is not affiliated with or endorsed by Chapel
Properties Ltd or Xero.
