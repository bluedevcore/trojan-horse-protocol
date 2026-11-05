# Mock-mode fixtures

When the app runs without `ANTHROPIC_API_KEY` (or with `DEMO_MOCK=1`), `core.claude.ClaudeClient` makes no
network calls. For the sample data it replays the JSON files in the `bookkeeping.*` folders, one per Claude
request, keyed by a hash of the exact request (task + system prompt + prompt + schema): 28 document readings,
1 coding batch, 3 email batches and the summary.

The responses are written by hand in `curated.json`, using only the facts in each request, to show what the
app's Claude steps produce for the sample data. The app labels them "pre-recorded AI text". To rebuild the
hashed files after a change to the prompts, config or sample data:

```bash
python -m tools.bookkeeping.refresh_fixtures clients/cosgrove-cosgrove
```

`tests/test_cosgrove_cosgrove_pipeline.py` fails if any sample request is not served from these fixtures.
To record real responses instead, run the demo once with an API key and `DEMO_RECORD_FIXTURES=1`.
