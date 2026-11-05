# Mock-mode fixtures

When the app runs without `ANTHROPIC_API_KEY` (or with `DEMO_MOCK=1`), `core.claude.ClaudeClient`
makes no network calls. For the sample data it replays the JSON files in this folder, one per
Claude request, keyed by a hash of the exact request (task + system prompt + prompt + schema).

The text in these files was written to show what the app's Claude steps produce for the sample
data, using only the facts in each request. To replace it with real responses from the API:

```bash
ANTHROPIC_API_KEY=... DEMO_RECORD_FIXTURES=1 streamlit run clients/nfu-energy/app.py   # run the demo once
```

If you change the prompts, rules or sample data, the hashes change and the sample run falls back
to template text (`tests/test_nfu_pipeline.py` will fail). Re-key the existing notes with:

```bash
python -m tools.data_validation.refresh_fixtures clients/nfu-energy
```
