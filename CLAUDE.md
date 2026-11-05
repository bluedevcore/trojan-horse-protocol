# trojan-horse-protocol

Client demo apps. Each demo shows a UK small business a working AI tool that does much of a job they are hiring for. Demos are sent as a link + 60-second video in place of a CV.

## Repo structure (keep to this)
```
core/            shared code: Claude client wrapper, Streamlit page shell, step-progress widget,
                 download helpers, caching, styling. Every demo imports from here.
tools/<tool>/    one reusable engine per job type (bookkeeping, compliance, leasehold_packs,
                 bid_writer, data_validation, listings). Pure logic + Claude prompts, no client names.
clients/<slug>/  one thin demo per client: app.py, config.yaml (name, wording, headline),
                 sample_data/, DEMO_SCRIPT.md, PITCH_MESSAGE.md, NEXT_STEPS.md
briefs/<tool>/   the original per-client briefs (read-only input; do not edit)
```

## Rules
- Python 3.11, Streamlit, `anthropic` SDK. Model from env `CLAUDE_MODEL`, key from `ANTHROPIC_API_KEY`. Never hard-code keys.
- Deterministic Python for maths, matching, validation and totals. Claude only for reading unstructured docs, classifying and writing text.
- Cache Claude responses on disk keyed by input hash so demo re-runs are fast and cheap.
- Synthetic sample data only. No real personal data. Never use a client's logo or make a demo look like their official software. Headline format: "<Tool name>: built as a prototype for <Client>".
- Every client app must have a "Run demo with sample data" button, a visible step-by-step progress list, a summary panel, a "needs human check" list, and download buttons for every output.
- Each client app must be deployable on its own on Streamlit Community Cloud (main file path `clients/<slug>/app.py`), with a root `requirements.txt` that covers everything.
- Tests in `tests/` for deterministic logic in `core/` and `tools/`. Run `pytest` and launch the app before declaring work done.
- Work in small commits. Do not touch other tools or clients than the one you were asked to work on, except to fix a genuine bug in `core/` (say so in the commit message).
