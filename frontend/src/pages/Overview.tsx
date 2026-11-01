import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AsyncState } from '../components/AsyncState'
import { RiskTag, ScoreMeter, SignalBadge, StatusBadge } from '../components/Badges'
import type { LatestSignal, LatestSignals, Run, SignalType } from '../lib/api'
import { dateTime, rate, relativeTime, shortDate, usd } from '../lib/format'
import { useApi } from '../lib/useApi'
import { useRowLink } from '../lib/useRowLink'

function LastRunCard({ runs }: { runs: Run[] }) {
  const run = runs[0]
  if (!run) {
    return (
      <section className="card">
        <h2 className="card-title">Last pipeline run</h2>
        <p className="muted">No runs yet. The pipeline runs every weekday at 06:00 UTC.</p>
      </section>
    )
  }
  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Last pipeline run</h2>
        <StatusBadge status={run.status} />
      </div>
      <dl className="stats-row">
        <div>
          <dt>Started</dt>
          <dd title={dateTime(run.started_at)}>{relativeTime(run.started_at)}</dd>
        </div>
        <div>
          <dt>Tickers</dt>
          <dd>
            {run.tickers_processed}
            {run.tickers_failed > 0 && <span className="muted"> · {run.tickers_failed} failed</span>}
          </dd>
        </div>
        <div>
          <dt>Est. LLM cost</dt>
          <dd>{usd(run.est_cost_usd)}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd className="mono">{run.model ?? '—'}</dd>
        </div>
      </dl>
    </section>
  )
}

type Filter = 'all' | SignalType
const FILTERS: Filter[] = ['all', 'bullish', 'bearish', 'neutral']

/** Score change since the ticker's previous signal, e.g. ▲2. */
function ScoreChange({ signal }: { signal: LatestSignal }) {
  if (signal.previous_score === null || signal.previous_as_of_date === null) return null
  const delta = signal.score - signal.previous_score
  const since = `${signal.previous_signal} ${signal.previous_score} on ${shortDate(signal.previous_as_of_date)}`
  if (delta === 0) {
    return (
      <span className="delta delta-flat" title={`Unchanged since ${since}`}>
        =
      </span>
    )
  }
  return (
    <span className={`delta ${delta > 0 ? 'delta-up' : 'delta-down'}`} title={`Was ${since}`}>
      {delta > 0 ? '▲' : '▼'}
      {Math.abs(delta)}
    </span>
  )
}

function SignalsTable({ latest }: { latest: LatestSignals }) {
  const rowLink = useRowLink()
  const [filter, setFilter] = useState<Filter>('all')
  if (latest.signals.length === 0) {
    return <p className="muted">No signals yet.</p>
  }
  const counts = Object.fromEntries(
    FILTERS.map((f) => [
      f,
      f === 'all' ? latest.signals.length : latest.signals.filter((s) => s.signal === f).length,
    ]),
  ) as Record<Filter, number>
  const shown = filter === 'all' ? latest.signals : latest.signals.filter((s) => s.signal === filter)

  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Latest signals</h2>
        {latest.as_of_date && <span className="muted">as of {shortDate(latest.as_of_date)}</span>}
      </div>
      <div className="filters" role="group" aria-label="Filter by signal">
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            className={`filter-chip${filter === f ? ' active' : ''}`}
            aria-pressed={filter === f}
            onClick={() => setFilter(f)}
          >
            {f === 'all' ? 'All' : f} <span className="filter-count">{counts[f]}</span>
          </button>
        ))}
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Signal</th>
              <th>Score</th>
              <th>Risk</th>
              <th className="num">Confidence</th>
              <th className="col-wide">Reasoning</th>
              <th aria-hidden="true" />
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  No {filter} signals today.
                </td>
              </tr>
            )}
            {shown.map((s) => (
              <tr key={s.id} {...rowLink(`/tickers/${s.ticker}`)} title={`Open ${s.ticker} details`}>
                <td>
                  <Link to={`/tickers/${s.ticker}`} className="ticker-link">
                    {s.ticker}
                  </Link>
                </td>
                <td>
                  <SignalBadge signal={s.signal} />
                  {s.previous_signal && s.previous_signal !== s.signal && (
                    <div className="was small muted">was {s.previous_signal}</div>
                  )}
                </td>
                <td>
                  <span className="score-cell">
                    <ScoreMeter score={s.score} />
                    <ScoreChange signal={s} />
                  </span>
                </td>
                <td>
                  <RiskTag risk={s.risk} />
                </td>
                <td className="num">{rate(s.confidence)}</td>
                <td className="col-wide">
                  <span className="clamp-2">{s.reasoning}</span>
                </td>
                <td className="row-chevron" aria-hidden="true">
                  ›
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function Overview() {
  const runs = useApi<Run[]>('/runs?limit=1')
  const latest = useApi<LatestSignals>('/signals/latest?limit=25&sort=score')

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Overview</h1>
        <p className="muted">
          Daily, LLM-scored signals from recent news for a fixed watchlist, sorted by score.
        </p>
      </div>
      <AsyncState state={runs}>{(data) => <LastRunCard runs={data} />}</AsyncState>
      {/* Only one "waking up" message: wait for the first request before showing the second. */}
      {!runs.loading && (
        <AsyncState state={latest}>{(data) => <SignalsTable latest={data} />}</AsyncState>
      )}
    </div>
  )
}
