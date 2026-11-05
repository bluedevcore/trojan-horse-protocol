# Build queue (closing dates from the Reed adverts, as of 5 Nov 2026)

## Tools

| Step | Tool | Status |
|---|---|---|
| – | data_validation | ✅ built (NFU Energy) |
| 1 | bookkeeping | ✅ built (5 clients, PR #2) |
| 2 | compliance | IN PROGRESS (see note below) |
| 3 | listings | not started |
| 4 | leasehold_packs | not started |
| 5 | data_validation for East Anglian Air Ambulance | not started (tool exists) |
| 6 | bid_writer | not started |

## Clients

| # | Client | Role | Tool | Closes | Status |
|---|---|---|---|---|---|
| 1 | NFU Energy | Technical Data Administrator | data_validation | 15 Nov | ✅ built |
| 2 | Cosgrove & Cosgrove | Accounts Assistant | bookkeeping | 11 Nov | ✅ built |
| 3 | Somerset Solders | P/T Accounts Admin / Bookkeeper | bookkeeping | 11 Nov | ✅ built |
| 4 | Evolution Money | Compliance Administrator | compliance | 11 Nov | IN PROGRESS |
| 5 | Areera | Re-use Administrator (listings) | listings | 11 Nov | |
| 6 | Wilkinson Grant | Block Management & Legal Admin | leasehold_packs | 12 Nov | |
| 7 | East Anglian Air Ambulance | Data Analyst | data_validation | 12 Nov | |
| 8 | Alfred Bagnall & Sons | Branch Administrator | bookkeeping | 13 Nov | ✅ built |
| 9 | Complete Fixing Solutions | Office Administrator | bookkeeping | 16 Nov | ✅ built |
| 10 | Wireless CCTV | Compliance Coordinator | compliance | 17 Nov | |
| 11 | Chapel Properties | Accounts Administrator | bookkeeping | 20 Nov | ✅ built |
| 12 | Westone Housing | Bid Writer | bid_writer | 23 Nov | |
| 13 | Swedencare | E-Commerce Executive | listings | 4 Dec | |
| 14 | Mellcrest | Operations Assistant | compliance | 4 Dec | |
| 15 | Medstrom | H&S Compliance Coordinator | compliance | 8 Dec | |
| 16 | Trinity Estates | Resales Administrator | leasehold_packs | 11 Dec | |

Status: built / video recorded / sent (date) / replied / call / paid

## IN PROGRESS: step 2, compliance (paused 5 Nov 2026, commit 4853db6)

**Built, not yet tested or used by anything:**
- `tools/compliance/tables.py`: reads 14 kinds of table (actions, risks, documents, certificates, training, audits, incidents, people, form_updates, framework, mi_history, content_requests, hazards, sales). Column names are matched from aliases, with extra aliases from config; unknown columns are kept so a register can be written back in the client's own layout. Reads every sheet of a workbook and detects which kind each uploaded sheet is (`detect_role`, `route_upload`). Reuses helpers from `tools/data_validation/loader.py`.
- `tools/compliance/documents.py`: reads PDF, Word (.docx), .eml and text files, including email sender, received date and attachments. Has a fallback reader that works without Claude (finds dates, references and keywords).
- `tools/compliance/checks.py`: a `Finding` class and about 60 checks in 12 areas (default severity, human-check flag, action, email recipient), plus `configure`, `finalise` (numbers findings EX-01…) and `findings_frame`. A client's config can override any check.

**Left to build in `tools/compliance/`:** `registers.py` (date and status checks), `updates.py` (apply department updates and log each change), `framework.py` (clause coverage, gaps, evidence pack), `schedule.py` (audit schedule), `content.py` (risk scoring, H&S draft requests), `kpis.py`, `mi.py` (monthly MI pack), `letters.py` (chase emails grouped by owner), `ai.py` (Claude tasks with schemas and template fallbacks), `reports.py`, `pipeline.py`, `views.py`, `refresh_fixtures.py`, `README.md`.

**Left for Evolution Money:** all of `clients/evolution-money/` (config, seeded sample data, app, fixtures, README, DEMO_SCRIPT, PITCH_MESSAGE, NEXT_STEPS). Planned sample: an invented lender, "Demo Lending Ltd", with:
- a register workbook: action log, risk register, policy register, breach log
- 11 department emails and a 10-row update form
- a staff list and 2 months of earlier MI figures

About 33 planted exceptions, roughly 15 of which need a human check:
- **Actions:** overdue actions, extension requests, an update matched without a reference, an unknown reference, completions without evidence, an update not from the owner, a duplicate form response
- **Mailbox:** a complaint and a data breach
- **Risks:** a rating that doesn't match its scores, a high risk with no action, overdue reviews
- **Policies:** overdue policy reviews, an unapproved policy
- **Register hygiene:** an action with no owner, one closed without evidence, a stale action, dates out of order, a duplicate reference

**Untested:** everything in `tools/compliance/` (no `tests/test_compliance_*.py` or `tests/test_evolution_money_*.py` yet). No browser check yet. The full suite still passes (212).

**Then:** Wireless CCTV, Mellcrest and Medstrom on the same engine, a PR and merge, then steps 3–6.
