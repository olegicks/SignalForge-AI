import { Link } from 'react-router-dom'
import { AsyncState } from '../components/AsyncState'
import { RiskTag, ScoreMeter, SignalBadge, StatusBadge } from '../components/Badges'
import type { LatestSignals, Run } from '../lib/api'
import { dateTime, rate, relativeTime, shortDate, usd } from '../lib/format'
import { useApi } from '../lib/useApi'

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

function SignalsTable({ latest }: { latest: LatestSignals }) {
  if (latest.signals.length === 0) {
    return <p className="muted">No signals yet.</p>
  }
  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Latest signals</h2>
        {latest.as_of_date && <span className="muted">as of {shortDate(latest.as_of_date)}</span>}
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
            </tr>
          </thead>
          <tbody>
            {latest.signals.map((s) => (
              <tr key={s.id}>
                <td>
                  <Link to={`/tickers/${s.ticker}`} className="ticker-link">
                    {s.ticker}
                  </Link>
                </td>
                <td>
                  <SignalBadge signal={s.signal} />
                </td>
                <td>
                  <ScoreMeter score={s.score} />
                </td>
                <td>
                  <RiskTag risk={s.risk} />
                </td>
                <td className="num">{rate(s.confidence)}</td>
                <td className="col-wide">
                  <span className="clamp-2" title={s.reasoning}>
                    {s.reasoning}
                  </span>
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
