# Meter Data Checker: built as a prototype for NFU Energy

A working prototype of the core of the **Technical Data Administrator** job: validating energy meter and consumption data, investigating discrepancies, and preparing recurring reports against deadlines.

**What it does**

1. Reads meter exports (CSV or Excel, in any of the column layouts set in `config.yaml`) and matches every meter to the site register.
2. Runs 9 deterministic checks: missing readings, unreadable values, duplicates, impossible values (negative, or above what the meter's capacity allows), register vs daily kWh mismatches, isolated spikes, zero-generation runs on PV, and missing days.
3. Calculates validated monthly totals per meter and per meter type. Doubtful readings are held out of the totals.
4. Checks the reporting calendar and shows which upcoming deadlines are blocked by open exceptions.
5. Uses Claude to draft a discrepancy note for each exception and a 20-second manager summary. Claude only writes the text; all figures come from the code.
6. Produces an Excel report pack, a PDF report, editable Word discrepancy notes and an exceptions CSV.

Anything uncertain goes on a **Needs human check** list instead of being guessed.

## Files

| Path | What it is |
|---|---|
| `app.py` | Streamlit entry point (a thin wrapper around `tools/data_validation`) |
| `config.yaml` | Headline and wording, column aliases, rules and thresholds, AI context, time-saved assumptions |
| `sample_data/` | Synthetic data: 3 meter exports (2,193 daily readings, 24 meters, 20 invented farm sites, Aug–Oct 2026), a site register and a reporting calendar. `generate.py` recreates them and lists the 15 deliberate problems. |
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
streamlit run clients/nfu-energy/app.py
```

Without `ANTHROPIC_API_KEY` the app runs in **mock mode** (badge in the header) with pre-recorded AI text. See the [root README](../../README.md) for environment variables and how to deploy on Streamlit Community Cloud with main file path `clients/nfu-energy/app.py`.

All data is synthetic. This is an independent prototype; it is not affiliated with or endorsed by NFU Energy.
