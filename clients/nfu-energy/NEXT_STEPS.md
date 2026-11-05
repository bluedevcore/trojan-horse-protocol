# Next steps: from prototype to NFU Energy's real data

The prototype shows the workflow on synthetic data. This is what it would take to run it on the real thing, and where it could go wrong.

## 1. Connecting to the real inputs (Excel first)

The advert mentions Excel, so the first version should take the spreadsheets and exports the team already uses. No new system is needed.

| Input | What's needed | Effort |
|---|---|---|
| **Meter exports** (supplier/AMR portals, FIT generation, RHI heat meter loggers) | One real example of each export format. Column names are mapped in `config.yaml` (`dataset.aliases`), so new formats usually need config changes, not code. | Small |
| **Site / meter register** | The current spreadsheet of meters: serial, site, meter type, scheme, capacity. This drives matching and the "impossible value" limits. | Small |
| **Reporting calendar** | The current deadline tracker (Ofgem RHI periodic data, FIT readings, supplier reports, HMRC evidence) with the data period and meter types each report covers. The dates in the demo are illustrative. | Small |
| **Output templates** | The team's existing report layouts, so the Excel pack and PDF match what managers and suppliers already receive. Submissions themselves stay manual. | Medium |

Later phases, only if they prove worthwhile:

1. **Shared folder:** read new exports from a SharePoint/OneDrive folder and write the report pack back there (Microsoft Graph), on a schedule.
2. **Data platform:** connect directly to any database or AMR provider API the team already uses, instead of exported files.
3. **Half-hourly data:** the demo checks daily reads. Half-hourly data for many meters means millions of rows and needs chunked processing or a database.

## 2. Tuning the checks

- **Calibrate on a past quarter:** run last quarter's real exports, where the team already knows what the problems were. Compare what the tool flags with what was actually found, then adjust thresholds (spike factor, gap length, tolerance) per meter type.
- **Seasonal patterns:** grain drying, poultry crop cycles and glasshouse heating change usage legitimately. The spike rule ignores sustained step changes, but real data will still need tuning to keep false alarms down.
- **Meter exchanges:** add the meter exchange log as an input, so register resets are explained automatically instead of flagged.
- **Estimated reads:** if exports mark reads as actual or estimated, add a rule so estimated reads are flagged before submissions.
- **Other fuels:** gas (m³ to kWh conversion with calorific values) and other meter types are not in the demo.

## 3. Data protection and hosting

- **Real data must not go on the public demo link.** Streamlit Community Cloud is fine for synthetic demos only. Real use needs private hosting with sign-in (for example an internal server, Azure, or Streamlit in Snowflake) and access limited to the team.
- **Personal data:** farm names, addresses and sole-trader details can be personal data under UK GDPR. A data protection check (DPIA) is needed before go-live.
- **What goes to the AI:** only the exceptions (around 15 short records per run) are sent to Claude, never the full dataset. Site names could be pseudonymised before sending if required. Anthropic's commercial terms and data retention settings should be reviewed and agreed first.
- **Audit trail:** every exception keeps its source file and row, and the Excel pack lists the rules applied. Archiving each run's pack gives a record of what was checked and when.

## 4. Risks and limitations

- **AI-drafted notes are drafts.** Claude writes the wording, and it can be wrong about likely causes. All figures, matching and totals come from deterministic code, and every note is labelled with its source. A person should review notes before they go outside the team.
- **The checks are only as good as their rules.** They will miss problems nobody has written a rule for, and may flag things that are fine. Hence the "needs human check" list and the calibration step above.
- **Nothing is corrected automatically,** apart from exact duplicate rows. The tool flags and explains issues; fixing the source data and making submissions stay with the team.
- **The time-saved figure is an estimate** built from assumptions in `config.yaml`, not a measurement. It should be replaced with real timings from a pilot.
- **Scheme rules change.** The tool doesn't encode Ofgem or HMRC scheme rules. The team's own knowledge of RHI, FIT and CCL requirements is still needed.
- **Prototype code:** it has unit tests, but it hasn't been security-reviewed or load-tested for production.

## 5. Suggested pilot (2–4 weeks)

1. Week 1: collect sample exports, the register and the reporting calendar; map columns; run on last quarter.
2. Week 2: review the flags with the team; tune rules; adjust the report pack layout.
3. Weeks 3–4: run it alongside the current process for one reporting cycle, and record the time taken and the issues caught by each method.
4. Decide: adopt as-is, extend (shared folder, half-hourly data), or stop.
