# Client demo apps

Each demo is a small working web app that shows a UK small business an AI tool doing much of a job they are hiring for. It is sent as a link plus a 60-second video, alongside a CV.

- **One shared core:** a Claude client with a disk cache and mock mode, a Streamlit page shell, a step-progress widget, a summary panel, a "needs human check" list, download builders and neutral styling.
- **One reusable engine per job type:** for example `tools/data_validation/`. It holds the logic and the Claude prompts, and contains no client names.
- **One thin folder per client:** `clients/<slug>/` holds the config, synthetic sample data and pitch documents. Each client folder deploys on its own as a Streamlit app.

The rules for working in this repo are in [CLAUDE.md](CLAUDE.md). The build order is in [QUEUE.md](QUEUE.md).

## Demos

| Client | Tool | Main file path | Status |
|---|---|---|---|
| NFU Energy: Technical Data Administrator | Meter Data Checker (`data_validation`) | `clients/nfu-energy/app.py` | Built |

## Repo structure

```
core/                 shared code: claude.py (wrapper + cache + mock mode), ui.py (page shell, progress,
                      summary, human-check list, downloads), downloads.py (Excel/CSV/Word/PDF), styling.py
tools/<tool>/         one engine per job type, e.g. tools/data_validation/
clients/<slug>/       app.py, config.yaml, sample_data/, fixtures/, DEMO_SCRIPT.md, PITCH_MESSAGE.md, NEXT_STEPS.md
briefs/<tool>/        the original per-client briefs (read-only)
tests/                pytest suite for core/ and tools/, plus end-to-end tests per client
requirements.txt      everything any demo needs at runtime (Streamlit Cloud installs this)
.streamlit/config.toml  neutral theme shared by all demos
```

## Run a demo locally

You need Python 3.11 (3.12 and 3.13 also work). Run these from the **repo root**:

```bash
python3.11 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
streamlit run clients/nfu-energy/app.py
```

To run a different demo, swap `nfu-energy` for its slug. Streamlit opens http://localhost:8501. Click **Run demo with sample data**.

**Mock mode vs live mode**

- **No API key set:** the app runs in **mock mode**. It makes no network calls, the AI text for the sample data is replayed from `clients/<slug>/fixtures/`, and a "Mock mode" badge shows in the header. Uploaded files still work, with template wording in place of Claude's.
- **Live mode:** set the key, and optionally the model, before starting:

  ```bash
  export ANTHROPIC_API_KEY="sk-ant-..."
  ```

  ```bash
  export CLAUDE_MODEL="claude-opus-5-5"
  ```

  You can also put them in `.streamlit/secrets.toml`, which is git-ignored, in the same format as the Cloud secrets below. Claude responses are cached in `.cache/claude/`, so re-running the demo is instant and free.

**Run the tests**

```bash
pytest
```

The suite covers the core wrapper and builders, every validation rule, the deadline tracker, a full NFU run in mock mode (it checks that it finds exactly the 15 planted problems and that every output file is valid), and a headless drive of the real Streamlit app.

### Environment variables

| Name | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | not set | Turns on live Claude calls. When it's missing, the app uses mock mode. |
| `CLAUDE_MODEL` | `claude-opus-5-5` | The model used for notes and summaries. |
| `DEMO_MOCK` | not set | Set to `1` to force mock mode even when a key is set. Useful for recording videos. |
| `DEMO_CLAUDE_EFFORT` | `low` | Effort level sent to the API (`low`/`medium`/`high`/`xhigh`/`max`). Use `none` to omit it for older models. Low keeps a demo run well under 60 seconds. |
| `DEMO_RECORD_FIXTURES` | not set | Set to `1` to save every Claude response as a fixture, so mock mode replays real output. |
| `CLAUDE_CACHE_DIR` | `.cache/claude` | Where cached responses are stored. |

With Opus 5.5 (and the other models that support it), requests ask the API to retry a declined request on Anthropic's recommended fallback model (`fallbacks: "default"`). If a call still fails, or the key is wrong, the app uses template text, shows a warning and keeps working.

## Deploy a client demo on Streamlit Community Cloud (free)

Every client folder is a separate app from the **same repository**. Repeat these steps once per client, changing only the main file path and the app URL.

1. **Push the repo to GitHub.** It can be private; Community Cloud asks for permission to read it.
2. **Get an Anthropic API key** from the Claude Console. Set a monthly spend limit on it: these are public demos. Leave this step out if you only want mock mode.
3. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub. Authorise Streamlit to access your repositories the first time.
4. Click **Create app**, then choose to deploy from a GitHub repository.
5. Fill in the form:
   - **Repository:** `<your-github-user>/trojan-horse-protocol`
   - **Branch:** `main` (or the branch you want to show)
   - **Main file path:** `clients/<slug>/app.py`, for example `clients/nfu-energy/app.py`
   - **App URL:** choose a readable subdomain, for example `meter-data-checker` → `https://meter-data-checker.streamlit.app`
6. Open **Advanced settings**:
   - **Python version:** 3.11
   - **Secrets:** paste this (TOML):

     ```toml
     ANTHROPIC_API_KEY = "sk-ant-..."
     CLAUDE_MODEL = "claude-opus-5-5"
     ```

     Leave the secrets empty to deploy in mock mode. Add `DEMO_MOCK = "1"` to force mock mode while keeping the key stored.
7. Click **Deploy**. The first build installs the root `requirements.txt` and takes a few minutes. Don't add a `requirements.txt` inside a client folder: Streamlit looks next to the main file first, and that would replace the root one.
8. **Check it:** open the URL, click **Run demo with sample data**, and confirm the header badge shows the live model (or "Mock mode" if you meant it to). Run it once more: the second run uses the cache and is instant.

**Changing secrets later:** open the app's menu (⋮) on your Community Cloud dashboard, choose **Settings**, then **Secrets**, edit and save. The app picks up the change within about a minute.

**Before you send a link or record a video:** apps go to sleep after a period with no visitors, and the first visit then wakes them, which takes a short while. Open the app yourself first.

**Updating a demo:** push to the deployed branch. Community Cloud redeploys automatically.

Notes:

- The app adds the repo root to `sys.path` itself, so `core/` and `tools/` import correctly from `clients/<slug>/app.py`.
- The theme in `.streamlit/config.toml` at the repo root applies to every demo.
- Community Cloud apps are public. Use synthetic data only; real client data needs private hosting (see each client's `NEXT_STEPS.md`).

## Adding a new client demo

1. Read the brief in `briefs/<tool>/` and the rules in `CLAUDE.md`.
2. Copy an existing client folder to `clients/<new-slug>/`. Edit `config.yaml` (headline, wording, column aliases, rules, AI context, time assumptions) and create synthetic `sample_data/`.
3. Record fixtures for mock mode: run once with a key and `DEMO_RECORD_FIXTURES=1`, or curate them and run `python -m tools.data_validation.refresh_fixtures clients/<new-slug>`.
4. Add an end-to-end test like `tests/test_nfu_pipeline.py`, run `pytest`, launch the app, and write `DEMO_SCRIPT.md`, `PITCH_MESSAGE.md` and `NEXT_STEPS.md`.
5. Deploy it as a new app with main file path `clients/<new-slug>/app.py`.
