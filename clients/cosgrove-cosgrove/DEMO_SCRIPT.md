# Demo script: 60-second screen recording

**QuickBooks Bookkeeping Agent: built as a prototype for Cosgrove & Cosgrove Ltd**

## Before you record

- Open the deployed app (or `streamlit run clients/cosgrove-cosgrove/app.py`) in a browser window about
  1280 × 800, zoom 100%.
- Run the demo once and refresh the page, so the app is awake and any AI text is cached.
- With an API key set, the badge shows the live model. Without one, it shows **Mock mode** and uses pre-recorded
  AI text. Both look the same on screen; mock mode is the safer choice for a recording.
- Close other tabs and turn notifications off. Keep the mouse still while you talk.

## Script

| Time | On screen | Voice-over |
|---|---|---|
| **0–10s** | Landing page: headline, the "what this replaces" line and the **Run demo with sample data** button. | "Your Accounts Assistant role is about keeping QuickBooks Online accurate: supplier invoices, expenses and card transactions, receipts, payroll journals and month end. I built a tool that does a big part of that." |
| **10–20s** | Click **Run demo with sample data**. The progress list ticks through: *Read 28 documents… Matched 13 of 17 card transactions… Coded 31 items… Payroll journal… Found 17 exceptions… Drafted 8 emails.* | "This is an invented company's October: 28 invoices, receipts and emails, the credit card statement, the payroll report and the jobs to invoice. It reads every document, matches card spend to receipts and codes each line." |
| **20–30s** | Scroll to the **Summary**: £6,680 of purchases ready for QuickBooks, 13 of 17 card payments matched, 12 items to check, about 5.5 hours saved. Pause on the manager summary, then show **EX-01** in **Needs human check**. | "Most of it is ready to import. The important bit is what it won't guess about. This IT supplier's invoice arrived with new bank details, a classic fraud pattern, so it's held and the email says we'll phone them on the number we hold." |
| **30–38s** | Click the **Card matching** tab (two receipts missing, a tip on a café bill), then **Emails (8)** and open the receipt request to Alex Morgan. | "Two card payments have no receipt, so it drafts the requests to the cardholders. It also caught an invoice that doesn't add up, a VAT number that fails HMRC's check, and a payslip that's £100 out." |
| **38–45s** | Click **Month-end checklist**, then scroll to **Downloads** and click **QuickBooks bills (CSV)** and **Month-end report (PDF)**. | "It ticks off what it can on the month-end checklist, and everything downloads: QuickBooks import files for bills, card expenses, the payroll journal and sales invoices, plus an Excel pack and a PDF report." |
| **45–60s** | Scroll back up and open **…or upload your own files**. | "On your real data it would read your inbox and your QuickBooks lists, and it could post through the QuickBooks API instead of CSV files. The maths is done in code and anything uncertain comes to a person. The link is in my message. I'd love to talk about the role, or about setting this up for your team." |

## If something goes wrong

- **The app is asleep or slow to start:** this is normal on Streamlit Community Cloud after a period with no
  visitors. Wait for it to load, run the demo once, then record.
- **There's a yellow warning about the API:** the key is missing or has no credit. Remove the key to use mock
  mode, or fix it in the app's **Secrets**.
