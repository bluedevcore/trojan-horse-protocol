# Demo script: 60-second screen recording

**Meter Data Checker: built as a prototype for NFU Energy**

## Before you record

- Open the deployed app (or `streamlit run clients/nfu-energy/app.py`) in a browser window about 1280 × 800, zoom 100%.
- Run the demo once and refresh the page, so the app is awake and the AI text is cached.
- With an API key set, the badge shows the live model. Without one, it shows **Mock mode** and uses pre-recorded AI text. Both look the same on screen. Mock mode is the safer choice for a recording.
- Close other tabs and turn notifications off. Keep the mouse still while you talk.

## Script

| Time | On screen | Voice-over |
|---|---|---|
| **0–10s** | Landing page: headline, the "what this replaces" line and the **Run demo with sample data** button. | "The Technical Data Administrator role is about validating meter and consumption data, investigating discrepancies and getting Ofgem, HMRC and supplier reports out on time. I built a tool that does a big part of that." |
| **10–20s** | Click **Run demo with sample data**. The progress list ticks through: *Read 3 files: 2,193 readings from 24 meters… Matched 23 of 24 meters… Found 15 exceptions… Drafted 15 discrepancy notes… Built the report pack.* | "Here are three months of synthetic exports from 20 farms: electricity, solar FIT and biomass RHI meters, each file in a different format. It checks every reading against the site register." |
| **20–30s** | Scroll to the **Summary**: 94.8% passed, 15 exceptions, 9 need a human check, about 8 hours saved. Pause on the manager summary. Then show **Needs human check** and point at **EX-05**. | "Most of the data is fine. Fifteen problems were found. This one is 2,450 kWh from a 50 kWp array, which is impossible, and the register shows 245, so it's most likely a decimal slip. It flags the issue and drafts the note, but it doesn't change the value itself." |
| **30–38s** | Point at **EX-03** (a serial with two digits swapped). Click the **Deadline tracker** tab: the FIT readings due in 5 days are shown in red, blocked by EX-05 and EX-06. | "It also catches a mistyped meter serial, and it links problems to deadlines. The FIT readings are due in five days and two solar issues are holding them up." |
| **38–45s** | Scroll to **Downloads** and click **Report pack (Excel)** and **Validation report (PDF)**. Briefly open the PDF if you can. | "Everything downloads: an Excel report pack, a PDF for the manager, editable Word discrepancy notes and a CSV of exceptions." |
| **45–60s** | Scroll back up and open **…or check your own files**. | "On your real data, you'd drop in your Excel exports, site register and reporting calendar. The rules are a simple settings file, the maths is done in code, and anything uncertain comes to a person. The link is in my message. I'd love to talk about the role, or about setting this up for your team." |

## If something goes wrong

- **The app is asleep or slow to start:** this is normal on Streamlit Community Cloud after a period with no visitors. Wait for it to load, run the demo once, then record.
- **There's a yellow warning about the API:** the key is missing or has no credit. Remove the key to use mock mode, or fix it in the app's **Secrets**.
