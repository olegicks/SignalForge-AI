<div align="center">

<img src="docs/logo.svg" alt="SignalForge AI logo" width="96" height="96" />

# SignalForge AI

**News in, scored stock signals out, and an honest record of how they actually performed.**

[![Live demo](https://img.shields.io/badge/demo-signal--forge--ai.vercel.app-2a78d6?style=for-the-badge&logo=vercel&logoColor=white)](https://signal-forge-ai.vercel.app)
[![API docs](https://img.shields.io/badge/API-OpenAPI%20docs-6250d6?style=for-the-badge&logo=fastapi&logoColor=white)](https://signalforge-api-92bs.onrender.com/docs)

[![CI](https://github.com/olegicks/SignalForge-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/olegicks/SignalForge-AI/actions/workflows/ci.yml)
[![Daily pipeline](https://github.com/olegicks/SignalForge-AI/actions/workflows/daily.yml/badge.svg)](https://github.com/olegicks/SignalForge-AI/actions/workflows/daily.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React_19-20232a?logo=react&logoColor=61dafb)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169e1?logo=postgresql&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-Structured_Outputs-412991?logo=openai&logoColor=white)

[**Live demo**](https://signal-forge-ai.vercel.app) · [API docs](https://signalforge-api-92bs.onrender.com/docs) · [How it works](#how-it-works) · [Track record](#how-the-track-record-works) · [Run it yourself](#local-setup)

</div>

---

SignalForge AI is a small, production-style **AI research pipeline**. Every weekday it:

1. collects prices and fresh headlines for a watchlist of 25 stocks,
2. has an LLM turn that unstructured news into a **structured, scored signal**: bullish, bearish or neutral, with a score, risk, confidence, reasoning and sources,
3. stores everything in PostgreSQL,
4. **checks every signal 7 and 30 days later** against real prices to build a public track record.

It runs entirely on free tiers. A full daily run of 25 tickers costs about **$0.004** in OpenAI usage. The point is to show how an AI pipeline is built *and operated*: scheduled runs, validation, logging, cost control and measurable results.

> [!NOTE]
> The live demo's API runs on Render's free tier and sleeps when idle. The first visit can take up to a minute while it wakes up; the dashboard shows a "Waking up the server…" state and loads by itself.

<p align="center">
  <a href="https://signal-forge-ai.vercel.app">
    <img src="docs/screenshots/overview.png" alt="SignalForge AI dashboard: last pipeline run and the latest LLM-scored signals" width="900" />
  </a>
</p>

## Highlights

| | |
|---|---|
| 🧠 **Structured LLM output** | OpenAI Structured Outputs parsed straight into Pydantic models. No free-text parsing. |
| 🔢 **The model never invents numbers** | Every price and percentage comes from yfinance. The model cites news by item number, so it can't make up a link either. |
| 🛡️ **Validation after the model** | Out-of-range scores and confidences are clamped, unknown sources are dropped, lists are trimmed. |
| 📈 **Honest track record** | Each signal is scored against the first real close 7 and 30 days later, **and against SPY over the same days**. Hit rates are shown next to an "always bullish" baseline and broken down by confidence bucket. |
| 🔁 **Day-over-day view** | The overview shows how each score moved since the previous signal (▲2, ▼1, "was bearish") and filters by signal type. |
| ⏰ **Runs itself** | A GitHub Actions cron job every weekday at 05:17 UTC. It applies migrations, then runs the pipeline. |
| 🧱 **Fails gracefully** | Each ticker is isolated. Network calls retry with backoff. A run ends as `success`, `partial` or `failed`. |
| 💸 **Cost-aware** | Token usage and the estimated cost of every run are logged and shown on the dashboard. Tickers with no news skip the LLM. |
| ✅ **Tested** | 95 pytest tests against a real Postgres, with yfinance, RSS and OpenAI mocked. CI runs ruff, pytest and the frontend build. |

## How it works

```mermaid
flowchart LR
    subgraph GH["GitHub Actions · weekdays 05:17 UTC"]
        P["pipeline.run"]
    end
    YF["yfinance<br/>prices + Ticker.news"] --> P
    GN["Google News RSS"] --> P
    P -- "numbered news + price metrics" --> LLM["OpenAI<br/>Structured Outputs"]
    LLM -- "SignalResult (Pydantic)" --> P
    P -- "validate · upsert" --> DB[("PostgreSQL<br/>Neon")]
    P -- "evaluate 7d / 30d" --> DB
    DB --> API["FastAPI<br/>Render"]
    API --> WEB["React dashboard<br/>Vercel"]
```

`python -m pipeline.run` does the following. Each ticker is processed in isolation, so one failure never stops the run.

1. **Start a run.** A `pipeline_runs` row is created with status `running`.
2. **Load the watchlist.** `backend/watchlist.yaml` is read: US tech, European large caps through their US listings, and some non-tech names, capped by `MAX_TICKERS_PER_RUN`.
3. **For each ticker:**
   - **Prices** (yfinance, retried with backoff): last close, change over 1, 5 and 30 days, and volume compared with the 20-day average. About 90 days of closes are kept for the chart.
   - **News**: Yahoo Finance and Google News RSS are merged. Only items from the last `NEWS_LOOKBACK_HOURS` are kept (24 hours more on Mondays, so Friday's news isn't skipped over the weekend), duplicates are removed by URL and by near-identical headline, and at most `MAX_NEWS_PER_TICKER` items remain.
   - **Analyze**: the model gets the ticker, our price metrics and the **numbered** news items (title, summary cut to about 300 characters, source, date). It returns a structured signal and cites news by item number, which the code maps back to URLs. If there is no news at all, the LLM is skipped and a neutral, zero-confidence signal is saved.
   - **Validate**: `score` is clamped to 1–10 and `confidence` to 0–1, unknown sources are dropped, lists are trimmed.
   - **Save**: the signal is upserted on (`ticker`, `as_of_date`), so re-running on the same day never creates duplicates.
4. **Evaluate**: outcomes are filled in for past signals (see below).
5. **Finish.** The run is marked `success`, `partial` or `failed`, with token totals, the estimated cost and any errors. The process exits non-zero only on `failed`.

| CLI flag | Effect |
|---|---|
| `--tickers AAPL,MSFT` | Run a subset (tickers not in the watchlist get a default news query) |
| `--dry-run` | Do everything but write nothing to the database; print a JSON report |
| `--no-llm` | Collect prices and news only |
| `--evaluate-only` | Only fill in 7d/30d outcomes (combine with `--dry-run` to preview) |

## How the track record works

- For every signal at least 7 (or 30) calendar days old without an outcome, the evaluator takes the **first available close on or after** `as_of_date + 7` (or `+ 30`). It uses one batched yfinance download per run.
- Only closes from before the current day count, so a partial intraday price is never used.
- Return = `close_N / price_at_signal − 1`.
- A **bullish** signal *hits* if the return is above 0. A **bearish** signal hits if it is below 0. **Neutral** signals have no direction and are left out of hit rates, though their average return is still shown.
- **Benchmark.** SPY's return over the same window is stored next to every outcome: from its last close before the signal date, which matches `price_at_signal`, to the same target close. This gives:
  - **excess return**, the stock's return minus SPY's;
  - a **relative hit rate**: a bullish call hits if it beat SPY, a bearish call if it lagged SPY;
  - an **"always bullish" baseline**: how often any stock simply went up. A hit rate means little unless it beats this.
- `/stats/track-record` returns all of the above for both horizons, plus average return and excess return by signal type, and hit rates by confidence bucket (0–0.4, 0.4–0.7, 0.7–1.0). If confidence means anything, the higher buckets should hit more often.

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Data | `yfinance` (prices, `Ticker.news`), Google News RSS via `feedparser` |
| LLM | OpenAI Python SDK, Structured Outputs (Responses API) parsed into Pydantic; model set by `OPENAI_MODEL` (currently `gpt-6-luna`) |
| Validation & config | Pydantic v2, `pydantic-settings` |
| Database | PostgreSQL on Neon, SQLAlchemy 2, Alembic, `psycopg` 3 |
| API | FastAPI + Uvicorn on Render (free), read-only |
| Frontend | React 19, Vite, TypeScript, Recharts on Vercel; light and dark themes |
| Scheduling & CI | GitHub Actions |
| Quality | `ruff`, `pytest` |

## Project layout

```
backend/
  app/            FastAPI app (main.py, api/routes.py, schemas.py, stats.py)
  core/           config.py, db.py, models.py
  pipeline/       run.py (CLI), collectors/, analyzer/, evaluate.py, storage.py
  alembic/        migrations
  tests/
frontend/         React + Vite + TS dashboard
.github/workflows daily.yml, ci.yml
render.yaml       Render blueprint for the API
```

## Local setup

You need Python 3.12, Node 22 and a PostgreSQL database; a free Neon project works for development too. Tests need a **separate, disposable** database, because the suite drops and recreates its schema.

<details>
<summary><b>Windows (PowerShell)</b></summary>

If PowerShell refuses to run `Activate.ps1` or `npm` ("running scripts is disabled"), allow local scripts for your user once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Backend:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env      # then edit .env
alembic upgrade head
python -m pipeline.run --no-llm --tickers AAPL,MSFT   # collect data, no OpenAI cost
uvicorn app.main:app --reload    # http://localhost:8000/docs
```

Tests and lint (with `TEST_DATABASE_URL` set in `.env`):

```powershell
ruff check . ; ruff format --check . ; pytest
```

Frontend (in a second terminal):

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local    # VITE_API_URL=http://localhost:8000
npm run dev                          # http://localhost:5173
```

A quick local Postgres for tests, if Docker Desktop is running:

```powershell
docker run --name signalforge-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=signalforge_test -p 5432:5432 -d postgres:16
# TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/signalforge_test
```

</details>

<details>
<summary><b>macOS / Linux</b></summary>

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env             # then edit .env
alembic upgrade head
python -m pipeline.run --no-llm --tickers AAPL,MSFT
uvicorn app.main:app --reload

# in another terminal
cd frontend && npm install && cp .env.example .env.local && npm run dev
```

</details>

<details>
<summary><b>Environment variables</b></summary>

Backend (`backend/.env`, GitHub secrets or variables, Render):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | Postgres URL. Neon's `postgresql://…` works as is, even with quotes or a `psql '…'` wrapper |
| `TEST_DATABASE_URL` | — | Disposable database for `pytest` (tests are skipped without it) |
| `OPENAI_API_KEY` | — | OpenAI key (pipeline only, never needed by the API) |
| `OPENAI_MODEL` | — | Model name; nothing is hardcoded |
| `OPENAI_REASONING_EFFORT` | empty | Only for reasoning models, e.g. `none` for `gpt-6-luna`, so reasoning doesn't eat the output cap |
| `OPENAI_PRICE_INPUT_PER_1M` | `0` | USD per 1M input tokens, for the cost estimate |
| `OPENAI_PRICE_OUTPUT_PER_1M` | `0` | USD per 1M output tokens |
| `MAX_NEWS_PER_TICKER` | `8` | News items sent to the model per ticker |
| `NEWS_LOOKBACK_HOURS` | `48` | News age limit |
| `MAX_TICKERS_PER_RUN` | `30` | Watchlist cap |
| `LLM_MAX_OUTPUT_TOKENS` | `400` | Output token cap per call |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed frontend origins |
| `ANALYZER_PROVIDER` | `openai` | Which analyzer class to use (one switch for future providers) |
| `LOG_LEVEL` | `INFO` | `DEBUG` also prints full tracebacks for failed tickers |

Frontend: `VITE_API_URL`, the public URL of the API.

</details>

<details>
<summary><b>Deployment: Neon → GitHub → Render → Vercel</b></summary>

**1. Neon (database).** Create a free project at neon.tech and copy the connection string (`postgresql://…?sslmode=require`). Optionally create a second branch for tests.

**2. GitHub secrets.**
1. Push the repository.
2. Under **Settings → Secrets and variables → Actions**, add `DATABASE_URL`, `OPENAI_API_KEY` and `OPENAI_MODEL`.
3. Optionally add `OPENAI_PRICE_INPUT_PER_1M`, `OPENAI_PRICE_OUTPUT_PER_1M` and `OPENAI_REASONING_EFFORT` as variables or secrets.
4. Start the first run with **Actions → Daily pipeline → Run workflow**. It runs `alembic upgrade head` first, so the schema is created automatically.

**3. Render (API).** Choose **New → Blueprint** and pick the repository; `render.yaml` creates one free web service with `rootDir: backend`. Set `DATABASE_URL` and `CORS_ORIGINS` (your Vercel URL, no trailing slash), then check `/health` and `/docs`.

**4. Vercel (frontend).** Import the repository and set the **Root Directory** to `frontend` (`vercel.json` adds the SPA rewrite). Add `VITE_API_URL=https://<service>.onrender.com` and deploy. Finally, add the Vercel URL to `CORS_ORIGINS` on Render.

</details>

## Cost notes

- **Hosting is free:** Neon, Render and Vercel free tiers, plus GitHub Actions minutes. Render's health check uses `/`, which doesn't touch the database, so Neon can suspend when idle.
- **LLM usage is tiny:** the first full production run (25 tickers, `gpt-6-luna`) used 19,303 input and 3,769 output tokens, **$0.0038** in total. That's under **$0.10 a month** on weekdays.
- Every run stores `input_tokens`, `output_tokens` and `est_cost_usd`, and the dashboard shows the latest cost.
- Hard caps: `MAX_TICKERS_PER_RUN`, `MAX_NEWS_PER_TICKER`, `LLM_MAX_OUTPUT_TOKENS`, and a 20-minute workflow timeout.

## Limitations

- yfinance is unofficial and can break or rate-limit. Calls are retried and failures are isolated per ticker. Yahoo's news feed is sometimes empty, so Google News carries most of the load.
- Headlines and short summaries are a thin signal; full articles are not read.
- Google News links are redirect URLs. An article relevant to two tickers is stored once, under the first.
- Returns are simple price returns: no dividends, and no adjustment for splits between the signal and its evaluation.
- With a small sample and a short history, hit rates stay noisy for a long time.

## Future work

- More data sources: SEC filings, earnings calendars, analyst rating changes.
- X/Twitter sentiment via Grok, as a second analyzer behind `ANALYZER_PROVIDER`.
- Startup and small-cap screening beyond a fixed watchlist.
- Per-sector breakdowns and more benchmarks (e.g. a sector ETF per ticker).

## Disclaimer

SignalForge AI is a research and portfolio prototype and **not investment advice**. Signals are generated automatically by a language model from a small sample of public headlines and can be wrong, incomplete or out of date. Past hit rates say nothing reliable about future results. Do not make financial decisions based on this project.
