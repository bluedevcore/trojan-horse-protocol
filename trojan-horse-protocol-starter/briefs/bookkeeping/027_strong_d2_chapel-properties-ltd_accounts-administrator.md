# Build a client demo: Financial Data Entry Agent for Chapel Properties ltd

## Context
I'm pitching an AI automation to **Chapel Properties ltd**, who are hiring a **Accounts Administrator** in IP45PD. Instead of a CV, I'm sending them a working demo plus a 60-second video showing a tool that does a large chunk of this job. Build that demo.

**What the job involves (from their advert):**
High-volume financial data entry and analysis for a property company.

**Duties listed in the advert:**
- About the Role – Accounts Administrator
- Key Responsibilities – Accounts Administrator
- Managing high-volume data entry and accurate financial analysis.
- Operating confidently across all ledgers (Sales, Purchase, and Nominal/General) within our accounting software.
- Assisting with broader accounting tasks and financial reporting as required.
- Working independently to resolve queries and streamline processes using your own initiative.
- Requirements & Skills – Accounts Administrator
- Qualifications: Qualified by experience or actively working towards AAT qualifications.
- Software: Prior experience using standard accounting software packages across all ledgers.
- Excel: Strong Microsoft Excel skills are essential for data manipulation and reporting.

## What to build
Financial Data Entry Agent: invoices/statements in -> extracted to spreadsheet with analysis summary.

Build it as a small, polished web app I can deploy and send as a link.

## Requirements

### 1. Sample data (critical)
- Create realistic **synthetic** sample data that matches this business and industry (company size, UK context, believable names, amounts, dates in the last 3 months, a few deliberate errors and edge cases for the tool to catch).
- Store it in `/sample_data` (CSV, XLSX, PDF or EML as appropriate to the inputs above). Include at least 15–30 records so the output looks substantial.
- Never use real personal data. Do not use Chapel Properties ltd's logo or make the app look like their official software.

### 2. The app
- Stack: **Python + Streamlit**, single repo, Claude API via the `anthropic` SDK (model from env var `CLAUDE_MODEL`, key from `ANTHROPIC_API_KEY`). Use deterministic Python for maths, matching and validation; use Claude only for reading unstructured documents, classifying, and writing text.
- Landing screen: one-line headline ("Financial Data Entry Agent: built as a prototype for Chapel Properties ltd"), a short "what this replaces" line, and a big **Run demo with sample data** button so it works with zero setup. Also allow uploading their own files.
- Show the work happening step by step (progress list: "Reading 24 documents… Found 3 discrepancies… Drafting report…") so the video shows the agent working.
- Results screen: a clear summary panel at the top (counts, totals, time saved estimate vs doing it by hand), then the detailed outputs, then **download buttons** for every output file (Excel/CSV/Word/PDF as appropriate).
- Flag anything uncertain for human review instead of guessing; show a "needs human check" list.
- Clean, professional look: neutral colours, readable tables, no clutter. Must work on a laptop screen at 1280px wide.

### 3. Outputs the demo must produce
Derive these from the solution above. At minimum: the main work product(s) the Accounts Administrator would normally produce by hand, an exceptions/issues list, and a short plain-English summary a manager could read in 20 seconds.

### 4. Quality bar
- Runs end to end on the sample data in under 60 seconds.
- Handles a missing or malformed file gracefully with a friendly message.
- Include `tests/` with a few tests on the deterministic parts (validation, matching, totals).
- Cache Claude calls during the demo run so repeat runs are fast and cheap.

### 5. Deliverables
1. The working app (`app.py` plus modules) and `requirements.txt`.
2. `README.md`: what it does, how to run locally, how to deploy free on Streamlit Community Cloud (step by step), and environment variables.
3. `DEMO_SCRIPT.md`: a 60-second screen-recording script (timestamped: 0–10s the problem in their words, 10–45s run demo and show outputs, 45–60s what it would look like on their real data + call to action).
4. `PITCH_MESSAGE.md`: a short, friendly application message to Chapel Properties ltd (under 150 words) that says I built this instead of sending a CV, links the demo and video, and offers to discuss it as a hire or as a tool. Honest, no exaggerated claims.
5. `NEXT_STEPS.md`: what would be needed to connect it to their real systems (the advert mentions: Excel), and the main risks/limitations.

Work in small steps: scaffold, sample data, core logic with tests, Claude steps, UI, then docs. Run the app and the tests before you finish, and fix anything that fails.
