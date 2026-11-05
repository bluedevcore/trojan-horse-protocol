# Demo script: 60-second screen recording

**Bookkeeping Agent: built as a prototype for Somerset Solders Ltd**

## Before you record

- Open the deployed app (or `streamlit run clients/somerset-solders/app.py`) in a browser window about
  1280 × 800, zoom 100%.
- Run the demo once and refresh the page, so the app is awake and any AI text is cached.
- With an API key set, the badge shows the live model. Without one, it shows **Mock mode** and uses pre-recorded
  AI text. Both look the same on screen; mock mode is the safer choice for a recording.
- Close other tabs and turn notifications off. Keep the mouse still while you talk.

## Script

| Time | On screen | Voice-over |
|---|---|---|
| **0–10s** | Landing page: headline, the "what this replaces" line and the **Run demo with sample data** button. | "Your part-time bookkeeper looks after the sales and purchase ledgers in Xero, sorts out supplier and customer invoice queries, prepares the VAT returns and supports month end. I built a tool that does a big part of that." |
| **10–20s** | Click **Run demo with sample data**. The progress list ticks through: *Read 19 documents… Coded 17 items… Raised 6 sales invoices… Aged 14 open invoices… Matched 3 invoice(s) to purchase orders… Found 17 exceptions… Drafted 10 emails.* | "This is an invented solder maker's October: supplier invoices and emails, a supplier statement, the despatches to invoice, the open sales invoices, the bank statement and the purchase orders." |
| **20–30s** | Scroll to the **Summary**: £20,842 of purchases ready for Xero, £9,791 overdue, 13 items to check, about 6 hours saved. Pause on the manager summary, then show **EX-01** and **EX-16** in **Needs human check**. | "Most of it is ready for Xero. The important part is what it won't guess about. The assay lab's invoice came with new bank details, a classic fraud pattern, so it's held. And the tin supplier has charged £450 more than the purchase order." |
| **30–40s** | Click the **VAT return** tab (box 5 £219.62), then **Aged debtors**, then **Emails (10)** and open the final notice to Saltmarsh Marine Electronics. | "It prepares the VAT return workings from the checked entries: exports zero-rated, no VAT reclaimed on the customer lunch. It matches customer receipts to invoices, ages the debtors and drafts the chasers, leaving the disputed invoice out." |
| **40–45s** | Scroll to **Downloads** and click **Xero bills (CSV)** and **Month-end report (PDF)**. | "Everything downloads: Xero import files for bills and sales invoices, an Excel pack, a PDF month-end report and the emails in Word." |
| **45–60s** | Scroll back up and open **…or upload your own files**. | "On your real data it would read your accounts inbox and your Xero lists, and it could create draft bills and invoices through the Xero API instead of CSV files. The maths is done in code and anything uncertain comes to a person. The link is in my message. I'd be glad to talk about the role, or about setting this up for you." |

## If something goes wrong

- **The app is asleep or slow to start:** this is normal on Streamlit Community Cloud after a period with no
  visitors. Wait for it to load, run the demo once, then record.
- **There's a yellow warning about the API:** the key is missing or has no credit. Remove the key to use mock
  mode, or fix it in the app's **Secrets**.
