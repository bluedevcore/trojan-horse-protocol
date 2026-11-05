# Demo script: 60-second screen recording

**Financial Data Entry Agent: built as a prototype for Chapel Properties Ltd**

## Before you record

- Open the deployed app (or `streamlit run clients/chapel-properties/app.py`) in a browser window about
  1280 × 800, zoom 100%.
- Run the demo once and refresh the page, so the app is awake and any AI text is cached.
- With an API key set, the badge shows the live model. Without one, it shows **Mock mode** and uses pre-recorded
  AI text. Both look the same on screen; mock mode is the safer choice for a recording.
- Close other tabs and turn notifications off. Keep the mouse still while you talk.

## Script

| Time | On screen | Voice-over |
|---|---|---|
| **0–10s** | Landing page: headline, the "what this replaces" line and the **Run demo with sample data** button. | "Your Accounts Administrator role is high-volume financial data entry and analysis for a property company, across the purchase and nominal ledgers. I built a tool that does a big part of that." |
| **10–20s** | Click **Run demo with sample data**. The progress list ticks through: *Read 24 documents… Coded 22 items… Reconciled 1 supplier statement… Filed 23 of 24 documents… Found 15 exceptions… Drafted 5 emails.* | "This is an invented property company's October: contractor invoices, utility bills, a service charge demand and a supplier statement. It reads every document and codes each line to a nominal account and to its property." |
| **20–30s** | Scroll to the **Summary**: 15 of 22 ready, 12 items to check, about 5 hours saved. Pause on the manager summary, then show **EX-01** in **Needs human check**. | "Most of it is ready for the ledger. The important bit is what it won't guess about. This grounds contractor's invoice came with new bank details, a classic fraud pattern, so it's held, and the email says we'll phone them on the number we hold." |
| **30–40s** | Click the **Coded entries** tab (Property column), open **Totals by property**, then click **Supplier statements**. | "Every line carries its property, so the cost analysis by property is already done. The supplier statement is ticked off too: one invoice we never received, and one amount that doesn't match." |
| **40–45s** | Scroll to **Downloads** and click **Bookkeeping pack (Excel)** and **Month-end report (PDF)**. | "Everything downloads: the Excel analysis, a PDF report, the drafted supplier emails and an import file for the accounts package." |
| **45–60s** | Scroll back up and open **…or upload your own files**. | "On your real data it would read your invoice inbox and use your own supplier list, chart of accounts and property list. The maths is done in code and anything uncertain comes to a person. The link is in my message. I'd be glad to talk about the role, or about setting this up for your team." |

## If something goes wrong

- **The app is asleep or slow to start:** this is normal on Streamlit Community Cloud after a period with no
  visitors. Wait for it to load, run the demo once, then record.
- **There's a yellow warning about the API:** the key is missing or has no credit. Remove the key to use mock
  mode, or fix it in the app's **Secrets**.
