# SignalForge AI: Project Specification for Claude Code

You are building **SignalForge AI**, a small, production-style AI research pipeline for a portfolio project.
Read this whole file before writing any code. Then follow the phases at the end **one at a time**.

---

## 1. Goal

A pipeline that runs automatically once per weekday and does the following:
1. collects price data and recent news for a fixed watchlist of stocks,
2. uses an LLM to turn that unstructured news into a **structured, scored signal** per ticker,
3. stores everything in PostgreSQL,
4. later checks how each signal actually performed (7 and 30 days later) to build an honest **track record**,
5. shows it all on a simple web dashboard.

The point of the project is to show that I can **build and operate** an AI pipeline reliably: clean code, scheduled runs, logging, cost control and measurable results. It should be simple, not over-engineered.

This is a research prototype and **not investment advice**. Show that disclaimer in the README and the dashboard footer.

---

## 2. Hard constraints

- **Cost must stay near zero.** Hosting is entirely on free tiers. The only paid service is the OpenAI API, and usage must stay very small.
- **No paid data APIs.** Use only `yfinance` and free RSS feeds.
- **The LLM never invents data.** Prices and numbers always come from `yfinance`, never from the model. The model only interprets the news text and numbers we give it.
- **No secrets in git.** Commit only `.env.example` with placeholder values. `.env` must be in `.gitignore`.
- **Use only the hosting described here.** Do not add other services without asking me.

---

## 3. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Price and news data | `yfinance` (prices, `Ticker.news`), Google News RSS via `feedparser` |
| LLM | OpenAI Python SDK, **Structured Outputs** parsed into a Pydantic model |
| Validation | Pydantic v2, `pydantic-settings` for config |
| Database | PostgreSQL (Neon, free tier); SQLAlchemy 2.0 ORM; Alembic migrations; `psycopg` v3 driver |
| API | FastAPI + Uvicorn |
| Frontend | React + Vite + TypeScript; one small charting library (e.g. Recharts) |
| Scheduling | GitHub Actions cron |
| Hosting | Neon (DB), Render free web service (API), Vercel (frontend) |
| Quality | `ruff` (lint + format), `pytest` |

Use the **current** OpenAI SDK API for structured outputs. If you are unsure of the exact method signature, check the installed SDK version instead of guessing.
The model name comes from the env var `OPENAI_MODEL`. Do not hardcode a model name anywhere.

---

## 4. Repository structure

```
signalforge/
├── backend/
│   ├── app/                  # FastAPI application
│   │   ├── main.py
│   │   ├── api/              # routers
│   │   └── schemas.py        # API response models
│   ├── core/
│   │   ├── config.py         # pydantic-settings
│   │   ├── db.py             # engine/session
│   │   └── models.py         # SQLAlchemy models
│   ├── pipeline/
│   │   ├── run.py            # CLI entrypoint: python -m pipeline.run
│   │   ├── collectors/       # prices.py, news.py
│   │   ├── analyzer/         # base.py (interface), openai_analyzer.py, prompts.py
│   │   └── evaluate.py       # fills in 7d/30d outcomes
│   ├── alembic/
│   ├── tests/
│   ├── watchlist.yaml
│   ├── requirements.txt
│   └── .env.example
├── frontend/
├── .github/workflows/
│   ├── daily.yml
│   └── ci.yml
├── render.yaml
├── README.md
└── SPEC.md
```

---

## 5. Configuration (`.env.example`)

```
DATABASE_URL=postgresql+psycopg://user:password@host/dbname?sslmode=require
OPENAI_API_KEY=sk-...
OPENAI_MODEL=            # cheapest current small model, set by me
MAX_NEWS_PER_TICKER=8
NEWS_LOOKBACK_HOURS=48
MAX_TICKERS_PER_RUN=30
LLM_MAX_OUTPUT_TOKENS=400
CORS_ORIGINS=http://localhost:5173
```

Also store the model's input and output price per 1M tokens as config values, so each run can log an **estimated cost**.

---

## 6. Watchlist

`backend/watchlist.yaml` should hold about 25 well-known tickers: a mix of US tech, European large caps that trade on yfinance (e.g. `ASML`, `SAP`), and a few non-tech names. Each entry has `ticker`, `name`, and a `query` used for the Google News search.

---

## 7. Database schema

**`pipeline_runs`**
`id`, `started_at`, `finished_at`, `status` (`running` | `success` | `partial` | `failed`), `tickers_processed`, `tickers_failed`, `input_tokens`, `output_tokens`, `est_cost_usd`, `model`, `error_summary` (text, nullable).

**`news_items`**
`id`, `ticker`, `title`, `summary` (nullable), `url` (**unique**), `source`, `published_at`, `fetched_at`.

**`signals`**
`id`, `run_id` (FK), `ticker`, `as_of_date` (date), `signal` (`bullish` | `bearish` | `neutral`), `score` (int 1–10), `risk` (`low` | `medium` | `high`), `confidence` (float 0–1), `reasoning` (text), `key_factors` (JSONB list of strings), `sources` (JSONB list of URLs), `price_at_signal` (numeric), `model`, `created_at`.
Outcome columns, filled later and nullable: `price_7d`, `return_7d`, `price_30d`, `return_30d`, `evaluated_7d_at`, `evaluated_30d_at`.
Unique constraint on **(`ticker`, `as_of_date`)**.

Use Alembic for every schema change.

---

## 8. Pipeline behaviour (`python -m pipeline.run`)

1. Create a `pipeline_runs` row with status `running`.
2. Load the watchlist (capped by `MAX_TICKERS_PER_RUN`).
3. **For each ticker, isolated:** one ticker failing must never stop the run.
   - **Prices** (yfinance): last close, % change over 1 day, 5 days and 30 days, and volume compared with the 20-day average. Retry with backoff, because yfinance is unofficial and flaky.
   - **News**: merge `Ticker.news` and Google News RSS. Keep only items within `NEWS_LOOKBACK_HOURS`. Deduplicate by URL and by near-identical title. Keep at most `MAX_NEWS_PER_TICKER`. Store new items in `news_items`.
   - **Analyze**: send the ticker, its price metrics, and the news items (title, short summary, source, date, URL; each summary truncated to about 300 characters) to the analyzer.
   - **Validate the output**: every URL in `sources` must come from the news items we provided. Drop any other URL. Clamp `score` and `confidence` to their ranges.
   - **Save**: upsert the signal for (`ticker`, today). Running the pipeline twice on the same day must not create duplicates.
4. Run **evaluate**: for every signal at least 7 or 30 calendar days old that has no outcome yet, take the first available close on or after the target date. Store the price and the return. Use batched yfinance downloads.
5. Finish the run. Status is `success` if all tickers worked, `partial` if some failed, and `failed` if none worked. Record token totals and estimated cost. Exit with a non-zero code only if the status is `failed`.

**CLI flags:**
- `--tickers AAPL,MSFT` runs a subset.
- `--dry-run` does everything but writes nothing to the DB and prints the results.
- `--no-llm` collects data only.
- `--evaluate-only` runs only step 4.

**Logging:** use structured, readable logs with the `logging` module. Never log the API key.

---

## 9. Analyzer

- `analyzer/base.py` defines an interface: `analyze(ticker, metrics, news) -> SignalResult`. `SignalResult` is a Pydantic model that includes token usage.
- `openai_analyzer.py` implements it with OpenAI Structured Outputs. Adding another provider (Gemini, Grok) later should only need a new class and one config switch.
- System prompt rules, kept in `prompts.py`:
  - Act as a cautious equity research assistant.
  - Use **only** the data provided. Do not use outside knowledge about recent events.
  - If the news is thin, irrelevant or contradictory, return `neutral` with low confidence.
  - `reasoning`: 2–3 plain sentences. `key_factors`: up to 4 short strings.
  - `sources`: only URLs from the provided list.
- Keep the token count low. Set the output cap with `LLM_MAX_OUTPUT_TOKENS`.

---

## 10. API (FastAPI)

- `GET /health`: status plus whether the DB is reachable.
- `GET /runs?limit=20`: recent pipeline runs.
- `GET /signals/latest?limit=25&sort=score`: signals from the most recent run date.
- `GET /signals?ticker=&from=&to=`: signal history.
- `GET /tickers/{ticker}`: signal history plus recent news for one ticker.
- `GET /stats/track-record`: hit rates for 7 and 30 days. A bullish signal hits if its return is above 0; a bearish signal hits if its return is below 0; neutral signals are excluded. Also return counts, average return by signal type, and a breakdown by confidence bucket.

Also:
- CORS origins come from `CORS_ORIGINS`.
- The API is read-only and has no write endpoints.
- Response models live in `schemas.py`.
- OpenAPI docs are enabled.

---

## 11. Frontend (React + Vite + TS)

Pages:
1. **Overview**: last-run status card (time, status, tickers processed, estimated cost) and a table of the latest signals sorted by score, with signal badge, score, risk, confidence and a short reasoning.
2. **Ticker detail**: price line with signal markers, signal history, news list with links.
3. **Track record**: hit-rate cards (7 days and 30 days), returns by signal type, and a table of evaluated signals.
4. **About**: how the pipeline works (simple diagram or steps), tech stack, and the disclaimer.

Requirements:
- The API URL comes from `VITE_API_URL`.
- **Cold-start handling**: the Render free tier sleeps, so the first request can take about 60 seconds. Show a friendly "Waking up the server…" state with retries, not an error.
- Clean, minimal, responsive design, with dark mode supported.
- No UI framework bloat.

---

## 12. GitHub Actions

**`daily.yml`**
- Triggers: `schedule` with `cron: "0 6 * * 1-5"`, plus `workflow_dispatch`.
- Steps: set up Python 3.12, install dependencies (with pip caching), run `alembic upgrade head`, then run `python -m pipeline.run`.
- Secrets used: `DATABASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`.
- Timeout: 20 minutes.

**`ci.yml`**
- Runs on push and pull requests.
- Runs `ruff check`, `ruff format --check`, and `pytest`.
- Builds the frontend.

---

## 13. Tests

Use `pytest`. Tests must **never call real external APIs**: mock yfinance, RSS and OpenAI.

Cover at least:
- news deduplication and the lookback filter,
- source-URL validation and value clamping,
- the upsert being idempotent,
- the evaluate logic (choosing the first close on or after the target date, return calculation),
- the track-record hit-rate calculation,
- one API test per endpoint using a test DB or fixtures.

---

## 14. Deployment files

- `render.yaml`: one **free** web service with `rootDir: backend`, a build command, and the start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Env vars `DATABASE_URL` and `CORS_ORIGINS` are set with `sync: false`. No Render database: we use Neon.
- Frontend: make sure a Vercel deploy works with `frontend/` as the root directory.

---

## 15. README

The README must include:
- a one-paragraph pitch,
- an architecture diagram (Mermaid),
- the tech stack,
- how the pipeline and the track record work,
- local setup steps for **Windows PowerShell** and for macOS/Linux,
- env vars,
- deployment steps (Neon → GitHub secrets → Render → Vercel),
- cost notes,
- limitations and future work (more data sources, X sentiment via Grok, startup screening),
- the disclaimer.

Add a placeholder for screenshots.

---

## 16. Working rules for you (Claude Code)

- **My environment is Windows with PowerShell and VS Code.** Every command you give me or run must work in PowerShell, e.g. `.\.venv\Scripts\Activate.ps1`, not `source`.
- **Git:** make small, logical commits with clear conventional-commit messages (`feat:`, `fix:`, `chore:`, …) after each meaningful step. **Never run `git push`.** I push everything myself.
- Never commit `.env` or any secret.
- Do not make real OpenAI calls except when I explicitly ask for a test run. When you do, use `--tickers` with 1–2 tickers.
- Prefer simple, readable code over clever abstractions. Use type hints everywhere.
- If something in this spec is unclear or impossible, **ask me** instead of guessing.
- At the end of each phase, give me a short summary: what was done, how to run or verify it, and what I need to do manually (accounts, keys, secrets). Then **wait for my OK** before starting the next phase.

---

## 17. Phases

0. **Plan.** Read the spec, list any questions, and propose the exact package versions. Do not write code yet.
1. **Scaffold.** Repo structure, config, `.env.example`, `.gitignore`, ruff, pytest setup, `requirements.txt`.
2. **Database.** SQLAlchemy models, Alembic setup, initial migration.
3. **Collectors.** Prices and news, with tests.
4. **Analyzer.** OpenAI structured-output analyzer, prompt, validation, with tests (mocked).
5. **Pipeline.** Orchestration, CLI flags, run logging, cost estimate, evaluate step, with tests.
6. **API.** FastAPI endpoints, with tests.
7. **Frontend.** All four pages, cold-start handling.
8. **Automation and deploy.** `daily.yml`, `ci.yml`, `render.yaml`, Vercel config.
9. **README** and final cleanup.

---

## 18. Decisions from Phase 0

- Python 3.12 everywhere (local venv via `py -3.12 -m venv .venv`).
- Extra table `price_bars` (`ticker`, `date`, `close`; unique on `ticker`+`date`), upserted each run with ~90 recent closes, to drive the price chart.
- Tests run against real PostgreSQL: a service container in CI, `TEST_DATABASE_URL` locally.
- European names use their US listings (USD, one trading calendar).
- `as_of_date` is the run's UTC date; `price_at_signal` is the last available close.
- Returns are simple returns; the target date is `as_of_date + N` calendar days, first close on or after it.
- Runtime deps in `requirements.txt`; dev tools in `requirements-dev.txt`.
