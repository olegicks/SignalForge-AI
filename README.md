# SignalForge AI

SignalForge AI is a small, production-style AI research pipeline. Every weekday it collects prices and fresh headlines for a fixed watchlist of 25 stocks, asks an LLM to turn that unstructured news into a **structured, scored signal** (bullish / bearish / neutral, score, risk, confidence, reasoning, sources), stores everything in PostgreSQL, and then **checks every signal 7 and 30 days later** against real prices to build an honest, public track record. It runs entirely on free tiers; the only paid piece is a few cents of OpenAI usage. The goal is to show how an AI pipeline is built *and operated*: scheduled runs, validation, logging, cost control and measurable results.

> **Not investment advice.** This is a research prototype. See the [disclaimer](#disclaimer).

## Screenshots

_Coming soon._ Add `overview.png`, `ticker.png` and `track-record.png` to `docs/screenshots/`, then uncomment:

<!--
![Overview](docs/screenshots/overview.png)
![Ticker detail](docs/screenshots/ticker.png)
![Track record](docs/screenshots/track-record.png)
-->

---

## Architecture

```mermaid
flowchart LR
    subgraph GH["GitHub Actions (weekdays 06:00 UTC)"]
        P["pipeline.run"]
    end
    YF["yfinance<br/>prices + Ticker.news"] --> P
    GN["Google News RSS"] --> P
    P -- "news + price metrics" --> LLM["OpenAI<br/>Structured Outputs"]
    LLM -- "SignalResult (Pydantic)" --> P
    P -- "validate, upsert" --> DB[("PostgreSQL<br/>Neon")]
    P -- "evaluate 7d / 30d" --> DB
    DB --> API["FastAPI<br/>Render"]
    API --> WEB["React dashboard<br/>Vercel"]
```

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Data | `yfinance` (prices, `Ticker.news`), Google News RSS via `feedparser` |
| LLM | OpenAI Python SDK, Structured Outputs (Responses API) parsed into Pydantic |
| Validation & config | Pydantic v2, `pydantic-settings` |
| Database | PostgreSQL on Neon, SQLAlchemy 2, Alembic, `psycopg` 3 |
| API | FastAPI + Uvicorn on Render (free) |
| Frontend | React 19, Vite, TypeScript, Recharts on Vercel |
| Scheduling & CI | GitHub Actions |
| Quality | `ruff`, `pytest` (79 tests, real Postgres, all external APIs mocked) |

## How the pipeline works

`python -m pipeline.run` does the following. Each ticker is processed in isolation, so one failure never stops the run.

1. **Start a run.** A `pipeline_runs` row is created with status `running`.
2. **Load the watchlist.** `backend/watchlist.yaml` is read, capped by `MAX_TICKERS_PER_RUN`.
3. **For each ticker:**
   - **Prices** (yfinance, with retry and backoff): last close, change over 1 day, 5 days and 30 days, and volume compared with the 20-day average. About 90 days of closes are stored for the chart.
   - **News**: Yahoo Finance and Google News RSS are merged, then filtered:
     - only items from the last `NEWS_LOOKBACK_HOURS` are kept,
     - duplicates are removed by URL and by near-identical headline,
     - at most `MAX_NEWS_PER_TICKER` items are kept,
     - new items are saved to `news_items`.
   - **Analyze**: the model gets the ticker, the price metrics we computed, and the numbered news items (title, summary truncated to about 300 characters, source, date). It returns a structured signal and cites news by item number; the code maps the numbers back to URLs. That saves tokens, since news URLs are long, and the model can't invent a link. If there is no news at all, the LLM is skipped and a neutral, zero-confidence signal is saved. This is cheaper and more honest.
   - **Validate**:
     - any source URL that was not in the news we provided is dropped,
     - `score` is clamped to 1–10 and `confidence` to 0–1,
     - lists are trimmed.
   - **Save**: the signal is upserted on (`ticker`, `as_of_date`), so re-running on the same day replaces it instead of duplicating it.
4. **Evaluate**: see the next section.
5. **Finish the run.** The status is set:
   - `success` if every ticker worked,
   - `partial` if some failed,
   - `failed` if none worked.

   Token totals, the estimated cost and any errors are stored. The process exits with a non-zero code only on `failed`.

**The model never supplies numbers.** Every price and percentage comes from yfinance. The model only interprets the text and the figures we pass in.

CLI flags:

| Flag | Effect |
|---|---|
| `--tickers AAPL,MSFT` | Run a subset (tickers not in the watchlist get a default news query) |
| `--dry-run` | Do everything but write nothing to the database; print a JSON report |
| `--no-llm` | Collect prices and news only |
| `--evaluate-only` | Only fill in 7d/30d outcomes (combine with `--dry-run` to preview) |

## How the track record works

- For every signal at least 7 (or 30) calendar days old without an outcome, the evaluator takes the **first available close on or after** `as_of_date + 7` (or `+ 30`).
- Prices come from **one batched yfinance download** per run.
- Only closes from before the current day are used, so a partial intraday price never counts.
- Return = `close_N / price_at_signal − 1`.
- A **bullish** signal *hits* if the return is above 0. A **bearish** signal hits if it is below 0.
- **Neutral** signals have no direction, so they are excluded from hit rates. Their average return is still shown.
- `/stats/track-record` reports:
  - hit rates for both horizons,
  - counts,
  - average return by signal type,
  - hit rates by confidence bucket (0–0.4, 0.4–0.7, 0.7–1.0). If confidence means anything, the higher buckets should hit more often.

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

You need Python 3.12, Node 22 and a PostgreSQL database. A free Neon project works for development too. For tests, use a **separate, disposable** database: the test suite drops and recreates its schema.

### Windows (PowerShell)

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

A quick local Postgres for tests, if you have Docker Desktop running:

```powershell
docker run --name signalforge-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=signalforge_test -p 5432:5432 -d postgres:16
# TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/signalforge_test
```

### macOS / Linux

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

## Environment variables

Backend (`backend/.env`, GitHub secrets/variables, Render):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | Postgres URL. `postgresql://…` from Neon is accepted as is |
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

## Deployment

### 1. Neon (database)
1. Create a free project at neon.tech and copy the connection string (`postgresql://…?sslmode=require`).
2. Optionally create a second branch or database for tests.

### 2. GitHub secrets
1. Push the repository to GitHub.
2. Under **Settings → Secrets and variables → Actions → Secrets**, add `DATABASE_URL`, `OPENAI_API_KEY` and `OPENAI_MODEL`.
3. Optionally, under **Variables**, add `OPENAI_PRICE_INPUT_PER_1M`, `OPENAI_PRICE_OUTPUT_PER_1M` and `OPENAI_REASONING_EFFORT`.
4. Start the first run by hand: **Actions → Daily pipeline → Run workflow**. You can enter `AAPL,MSFT` as the tickers for a cheap test. The workflow runs `alembic upgrade head` first, so the schema is created automatically.

### 3. Render (API)
1. In Render, choose **New → Blueprint** and select the repository. `render.yaml` creates one free web service with `rootDir: backend`.
2. Set `DATABASE_URL` (the Neon URL) and `CORS_ORIGINS` (your Vercel URL, e.g. `https://signalforge.vercel.app`) when prompted.
3. Check `https://<service>.onrender.com/health` and `/docs`.

### 4. Vercel (frontend)
1. Import the repository and set the **Root Directory** to `frontend`. Vite is detected, and `vercel.json` adds the SPA rewrite.
2. Add the environment variable `VITE_API_URL=https://<service>.onrender.com` and deploy.
3. Add the Vercel URL to `CORS_ORIGINS` on Render if you haven't already.

## Cost notes

- **Hosting is free.** Neon, Render and Vercel free tiers, plus GitHub Actions minutes. Render's health check uses `/`, which does not touch the database, so Neon can suspend when idle.
- **LLM usage is tiny.** One call per ticker per weekday is about 25 calls a day, or about 550 a month. Each call is roughly 1–2k input tokens and at most 400 output tokens. That is around 1M input and well under 0.2M output tokens a month, which costs cents with a small model.
- Tickers with no fresh news skip the LLM entirely.
- Every run stores `input_tokens`, `output_tokens` and `est_cost_usd`, and the dashboard shows the latest cost. Set the two price variables to make the estimate real.
- Hard caps: `MAX_TICKERS_PER_RUN`, `MAX_NEWS_PER_TICKER`, `LLM_MAX_OUTPUT_TOKENS`, and a 20-minute workflow timeout.

## Limitations

- yfinance is unofficial and can break or rate-limit. Calls are retried, and failures are isolated per ticker. Yahoo's news feed is sometimes empty, so Google News carries most of the load.
- Headlines and short summaries are a thin signal. Full articles are not read.
- Google News links are redirect URLs. An article that is relevant to two tickers is stored once, under the first ticker.
- Returns are simple price returns. They exclude dividends and are not adjusted for splits that happen between the signal and evaluation.
- A small sample and a short history make hit rates noisy for a long time.
- The free Render API sleeps when idle. The dashboard shows a "Waking up the server…" state and retries.

## Future work

- More data sources: SEC filings, earnings calendars, analyst rating changes.
- X/Twitter sentiment via Grok, as a second analyzer behind `ANALYZER_PROVIDER`.
- Startup and small-cap screening beyond a fixed watchlist.
- Benchmark-relative returns (vs. SPY) and per-sector breakdowns.

## Disclaimer

SignalForge AI is a research and portfolio prototype and **not investment advice**. Signals are generated automatically by a language model from a small sample of public headlines and can be wrong, incomplete or out of date. Past hit rates say nothing reliable about future results. Do not make financial decisions based on this project.
