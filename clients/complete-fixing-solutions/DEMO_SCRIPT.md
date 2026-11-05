# Demo script: 60-second screen recording

**Timesheet-to-Payroll Agent: built as a prototype for Complete Fixing Solutions**

## Before you record

- Open the deployed app (or `streamlit run clients/complete-fixing-solutions/app.py`) in a browser window about
  1280 × 800, zoom 100%.
- Run the demo once and refresh the page, so the app is awake and any AI text is cached.
- With an API key set, the badge shows the live model. Without one, it shows **Mock mode** and uses pre-recorded
  AI text. Both look the same on screen; mock mode is the safer choice for a recording.
- Close other tabs and turn notifications off. Keep the mouse still while you talk.

## Script

| Time | On screen | Voice-over |
|---|---|---|
| **0–10s** | Landing page: headline, the "what this replaces" line and the **Run demo with sample data** button. | "Your Office Administrator spends Monday to Wednesday on weekly timesheets, then raises POs, reconciles invoices and updates Sage. I built a tool that does a big part of that." |
| **10–20s** | Click **Run demo with sample data**. The progress list ticks through: *Read 18 documents and 6 spreadsheets… Summarised hours for 18 employees… Matched 11 invoices to purchase orders… Found 18 exceptions… Drafted 7 emails.* | "This is an invented drylining firm's week: 95 timesheet lines for 18 operatives, 18 supplier invoices and the PO list. It works out everyone's hours and checks every line and every invoice." |
| **20–32s** | Scroll to the **Summary**: 636.5 of 768 hours ready for payroll, 3 operatives held, £12,162 of invoices ready for Sage, about 7 hours saved. Open the **Hours for payroll** tab: basic, overtime and weekend hours, three rows marked *Held*. | "Most of the week is ready for payroll. Three people are held: two lines that overlap by an hour and a half, a Saturday nobody signed off, and a new starter who isn't on the employee list yet." |
| **32–40s** | Click **PO matching**: a second delivery that takes a PO £190 over, scissor-lift hire billed for three weeks against a two-week PO, a PO number that doesn't exist. Show **EX-01** in **Needs human check**: changed bank details. | "On the invoices it caught two over-billed POs, a wrong PO number, and an invoice with new bank details from a look-alike email address, so that one is held until someone phones the supplier." |
| **40–47s** | Click **Emails (7)** and open the timesheet queries to the contracts manager, then scroll to **Downloads**: **Payroll hours (CSV)** and **Sage 50 transactions (CSV)**. | "It drafts the queries: one email to the contracts manager with every timesheet question, and one to each supplier. Then the payroll hours and the Sage import download, held items left out." |
| **47–60s** | Scroll back up and open **…or upload your own files**. | "On your real data it would read your timesheets and Sage lists, and the maths is all done in code, with anything uncertain left for a person. The link is in my message. I'd love to talk about the role, or about setting this up for your office." |

## If something goes wrong

- **The app is asleep or slow to start:** this is normal on Streamlit Community Cloud after a period with no
  visitors. Wait for it to load, run the demo once, then record.
- **There's a yellow warning about the API:** the key is missing or has no credit. Remove the key to use mock
  mode, or fix it in the app's **Secrets**.
