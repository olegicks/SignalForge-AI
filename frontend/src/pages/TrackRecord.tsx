import { Link } from 'react-router-dom'
import { AsyncState } from '../components/AsyncState'
import { HitMark, SignalBadge } from '../components/Badges'
import type { HorizonStats, SignalType, TrackRecord as TrackRecordData } from '../lib/api'
import { isHit, pct, price, rate, shortDate } from '../lib/format'
import { useApi } from '../lib/useApi'

const SIGNAL_TYPES: SignalType[] = ['bullish', 'bearish', 'neutral']

function HitRateCard({ stats }: { stats: HorizonStats }) {
  return (
    <section className="card hero-card">
      <h2 className="card-title">{stats.horizon_days}-day hit rate</h2>
      <div className="hero-number">{rate(stats.hit_rate)}</div>
      <p className="muted">
        {stats.directional > 0
          ? `${stats.hits} of ${stats.directional} bullish/bearish signals moved the right way`
          : 'No evaluated bullish/bearish signals yet'}
        {stats.evaluated > stats.directional &&
          ` · ${stats.evaluated - stats.directional} neutral excluded`}
      </p>
    </section>
  )
}

function ReturnsBySignal({ horizons }: { horizons: HorizonStats[] }) {
  return (
    <section className="card">
      <h2 className="card-title">Average return by signal type</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Signal</th>
              {horizons.map((h) => (
                <th key={h.horizon_days} className="num">
                  {h.horizon_days}d avg return (n)
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SIGNAL_TYPES.map((type) => (
              <tr key={type}>
                <td>
                  <SignalBadge signal={type} />
                </td>
                {horizons.map((h) => (
                  <td key={h.horizon_days} className="num">
                    {pct(h.by_signal[type].avg_return, 2)}{' '}
                    <span className="muted">({h.by_signal[type].count})</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function ByConfidence({ horizons }: { horizons: HorizonStats[] }) {
  const buckets = horizons[0]?.by_confidence.map((b) => b.bucket) ?? []
  return (
    <section className="card">
      <h2 className="card-title">Hit rate by model confidence</h2>
      <p className="muted small">
        If confidence means anything, higher buckets should hit more often.
      </p>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Confidence</th>
              {horizons.map((h) => (
                <th key={h.horizon_days} className="num">
                  {h.horizon_days}d hit rate (n)
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket, i) => (
              <tr key={bucket}>
                <td className="mono">{bucket}</td>
                {horizons.map((h) => (
                  <td key={h.horizon_days} className="num">
                    {rate(h.by_confidence[i].hit_rate)}{' '}
                    <span className="muted">({h.by_confidence[i].count})</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Content({ data }: { data: TrackRecordData }) {
  return (
    <div className="stack">
      <div className="page-head">
        <h1>Track record</h1>
        <p className="muted">
          Every signal is checked 7 and 30 calendar days later against the first available close.
          A bullish signal hits if the price went up; a bearish one hits if it went down. Neutral
          signals are not counted. {data.total_signals} signals recorded so far.
        </p>
      </div>
      <div className="grid-2">
        {data.horizons.map((h) => (
          <HitRateCard key={h.horizon_days} stats={h} />
        ))}
      </div>
      <ReturnsBySignal horizons={data.horizons} />
      <ByConfidence horizons={data.horizons} />
      <section className="card">
        <h2 className="card-title">Evaluated signals</h2>
        {data.recent_evaluated.length === 0 ? (
          <p className="muted">
            Nothing evaluated yet. The first results appear 7 days after the first run.
          </p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Ticker</th>
                  <th>Signal</th>
                  <th className="num">Conf.</th>
                  <th className="num">Price</th>
                  <th className="num">7d</th>
                  <th>Hit</th>
                  <th className="num">30d</th>
                  <th>Hit</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_evaluated.map((s) => (
                  <tr key={s.id}>
                    <td>{shortDate(s.as_of_date)}</td>
                    <td>
                      <Link to={`/tickers/${s.ticker}`} className="ticker-link">
                        {s.ticker}
                      </Link>
                    </td>
                    <td>
                      <SignalBadge signal={s.signal} />
                    </td>
                    <td className="num">{rate(s.confidence)}</td>
                    <td className="num">{price(s.price_at_signal)}</td>
                    <td className="num">{pct(s.return_7d)}</td>
                    <td>
                      <HitMark hit={isHit(s.signal, s.return_7d)} />
                    </td>
                    <td className="num">{pct(s.return_30d)}</td>
                    <td>
                      <HitMark hit={isHit(s.signal, s.return_30d)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

export function TrackRecord() {
  const state = useApi<TrackRecordData>('/stats/track-record')
  return <AsyncState state={state}>{(data) => <Content data={data} />}</AsyncState>
}
