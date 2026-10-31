const STEPS = [
  {
    title: 'Collect',
    text: 'Every weekday at 06:00 UTC a GitHub Actions job pulls prices from yfinance and recent headlines from Yahoo Finance and Google News RSS.',
  },
  {
    title: 'Clean',
    text: 'News older than 48 hours is dropped, duplicates are removed by URL and by near-identical headline, and each ticker keeps at most 8 items.',
  },
  {
    title: 'Analyze',
    text: 'An OpenAI model reads only that news plus price metrics we computed, and returns a structured signal: direction, score, risk, confidence and reasoning.',
  },
  {
    title: 'Validate',
    text: 'Any source URL the model did not receive is dropped, numbers are clamped to their ranges, and everything is stored in PostgreSQL.',
  },
  {
    title: 'Evaluate',
    text: '7 and 30 days later each signal is checked against the real closing price, which builds an honest, public track record.',
  },
]

const STACK: [string, string][] = [
  ['Pipeline', 'Python 3.12, yfinance, feedparser, Pydantic'],
  ['LLM', 'OpenAI Structured Outputs, parsed into Pydantic models'],
  ['Database', 'PostgreSQL on Neon, SQLAlchemy 2, Alembic'],
  ['API', 'FastAPI on Render (free tier)'],
  ['Frontend', 'React, Vite, TypeScript, Recharts on Vercel'],
  ['Automation', 'GitHub Actions: daily cron and CI (ruff, pytest, build)'],
]

export function About() {
  return (
    <div className="stack">
      <div className="page-head">
        <h1>About</h1>
        <p className="muted">
          SignalForge AI is a small, production-style AI pipeline: scheduled runs, logging, cost
          control and measurable results, built to run on free tiers for a few cents a month.
        </p>
      </div>

      <section className="card">
        <h2 className="card-title">How it works</h2>
        <ol className="steps">
          {STEPS.map((step, i) => (
            <li key={step.title} className="step">
              <span className="step-number" aria-hidden="true">
                {i + 1}
              </span>
              <div>
                <strong>{step.title}</strong>
                <p className="muted">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="small muted">
          The model never supplies prices or numbers. Those always come from yfinance.
        </p>
      </section>

      <section className="card">
        <h2 className="card-title">Tech stack</h2>
        <dl className="stack-list">
          {STACK.map(([layer, tech]) => (
            <div key={layer}>
              <dt>{layer}</dt>
              <dd>{tech}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="card disclaimer">
        <h2 className="card-title">Disclaimer</h2>
        <p>
          This is a research prototype and <strong>not investment advice</strong>. Signals are
          produced automatically from a small sample of public headlines and can be wrong,
          incomplete or out of date. Past hit rates say nothing reliable about the future. Do not
          make financial decisions based on this site.
        </p>
      </section>
    </div>
  )
}
