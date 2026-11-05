# Session prompts (paste one per Claude Code session)

Run these in order. Session 1 alone first. After that, sessions 2–6 can run in parallel (3–5 at a time), each on its own branch. Session 7 is repeated once per client.

---

## Session 1: core + first demo (NFU Energy)
Read CLAUDE.md and briefs/data_validation/001_strong_d1_nfu-energy_technical-data-administator.md.

1. Build `core/` as described in CLAUDE.md (Claude wrapper with disk cache, page shell, step-progress widget, summary panel, human-check list, download helpers, neutral professional styling).
2. Build `tools/data_validation/`: a generic engine that validates tabular data against configurable rules (missing values, out-of-range, duplicates, sudden spikes, date gaps), produces an exceptions list, and uses Claude to write discrepancy notes and a short report summary.
3. Build `clients/nfu-energy/` from the brief, with realistic synthetic meter/consumption data, using the core and the tool.
4. Add tests, run them, run the app, fix issues. Write README.md at repo root covering local run and Streamlit Cloud deploy for any client folder.
Stop when the NFU demo works end to end in under 60 seconds.

---

## Sessions 2–6: one per tool (parallel, separate branches)
Use this template, swapping in the tool name:

> Read CLAUDE.md and every brief in `briefs/<TOOL>/`. Build `tools/<TOOL>/` as a reusable engine that covers what all those briefs need, using `core/` (do not duplicate core code). Then build the client demo for the brief with the **earliest closing date** in `clients/<slug>/`, including synthetic sample data, DEMO_SCRIPT.md, PITCH_MESSAGE.md and NEXT_STEPS.md as the brief describes. Add tests, run them, launch the app, fix issues.

Tools: `bookkeeping`, `compliance`, `leasehold_packs`, `bid_writer`, `listings`.

---

## Session 7: each extra client on an existing tool (short)
> Read CLAUDE.md and `briefs/<TOOL>/<BRIEF FILE>`. Using the existing `tools/<TOOL>/` engine and `core/`, create `clients/<slug>/` for this client: config, realistic synthetic sample data for their business, app.py, DEMO_SCRIPT.md, PITCH_MESSAGE.md, NEXT_STEPS.md. Only extend the tool if the brief needs something it can't do, and keep that change generic. Run tests and the app.
