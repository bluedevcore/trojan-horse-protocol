# Demo script: 60-second screen recording

**Debtor & Filing Agent: built as a prototype for Alfred Bagnall & Sons Limited**

## Before you record

- Open the deployed app (or `streamlit run clients/alfred-bagnall/app.py`) in a browser window about
  1280 × 800, zoom 100%.
- Run the demo once and refresh the page, so the app is awake and any AI text is cached.
- With an API key set, the badge shows the live model. Without one, it shows **Mock mode** and uses pre-recorded
  AI text. Both look the same on screen; mock mode is the safer choice for a recording.
- Close other tabs and turn notifications off. Keep the mouse still while you talk.

## Script

| Time | On screen | Voice-over |
|---|---|---|
| **0–10s** | Landing page: headline, the "what this replaces" line and the **Run demo with sample data** button. | "Your Branch Administrator role covers project files, reconciling aged debtor accounts and chasing what's owed, and keeping contracts and correspondence in order. I built a tool that does a big part of that." |
| **10–20s** | Click **Run demo with sample data**. The progress list ticks through: *Read 23 documents… Aged 26 open invoices: £94,346 outstanding… Filed 20 of 23 documents… Found 11 exceptions… Drafted 7 emails.* | "This is an invented decorating contractor's branch: the Excel sales ledger, the bank statement, the project register and 24 documents waiting to be filed." |
| **20–30s** | Scroll to the **Summary**: £68,220 overdue, 20 of 23 filed, 10 items to check, about 4 hours saved. Pause on the manager summary, then on **Needs human check**. | "It ticks off six payments against their invoices, even one with no reference, and spots a part payment. It won't guess about the rest: a £1,950 bank giro credit with no name, a disputed invoice, a customer over its credit limit." |
| **30–38s** | Click the **Aged debtors** tab (the Chase column: Final notice, Second reminder, Reminder), then **Emails (7)** and open the final notice to Ambleford. | "Each overdue customer gets a drafted email at the right tone, from a friendly reminder to a final notice for the manager to approve. The disputed invoice is left out of that school's reminder." |
| **38–45s** | Click the **Filing** tab (project folders, three marked "needs a person"), then scroll to **Downloads**: Excel pack, PDF report, Word emails, filed documents zip. | "Contracts, orders and letters are renamed and filed into each project's folder. The three it can't place are left for a person, like a delivery note quoting a job number that doesn't exist." |
| **45–60s** | Scroll back up and open **…or upload your own files**. | "On your real data it would read your Excel ledger, your bank export and your project folders. The maths is done in code and anything uncertain comes to a person. The link is in my message. I'd love to talk about the role, or about setting this up for the branch." |

## If something goes wrong

- **The app is asleep or slow to start:** this is normal on Streamlit Community Cloud after a period with no
  visitors. Wait for it to load, run the demo once, then record.
- **There's a yellow warning about the API:** the key is missing or has no credit. Remove the key to use mock
  mode, or fix it in the app's **Secrets**.
