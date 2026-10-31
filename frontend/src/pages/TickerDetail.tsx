import { Link, useParams } from 'react-router-dom'
import { AsyncState } from '../components/AsyncState'
import { RiskTag, ScoreMeter, SignalBadge } from '../components/Badges'
import { PriceChart } from '../components/PriceChart'
import type { Signal, TickerDetail as TickerDetailData } from '../lib/api'
import { pct, price, rate, relativeTime, shortDate } from '../lib/format'
import { useApi } from '../lib/useApi'

function LatestSignal({ signal }: { signal: Signal }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Latest signal · {shortDate(signal.as_of_date)}</h2>
        <SignalBadge signal={signal.signal} />
      </div>
      <dl className="stats-row">
        <div>
          <dt>Score</dt>
          <dd>
            <ScoreMeter score={signal.score} />
          </dd>
        </div>
        <div>
          <dt>Risk</dt>
          <dd>
            <RiskTag risk={signal.risk} />
          </dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{rate(signal.confidence)}</dd>
        </div>
        <div>
          <dt>Price at signal</dt>
          <dd>{price(signal.price_at_signal)}</dd>
        </div>
      </dl>
      <p>{signal.reasoning}</p>
      {signal.key_factors.length > 0 && (
        <ul className="chips" aria-label="Key factors">
          {signal.key_factors.map((factor) => (
            <li key={factor} className="chip">
              {factor}
            </li>
          ))}
        </ul>
      )}
      {signal.sources.length > 0 && (
        <p className="sources muted">
          Sources:{' '}
          {signal.sources.map((url, i) => (
            <a key={url} href={url} target="_blank" rel="noreferrer">
              [{i + 1}]
            </a>
          ))}
        </p>
      )}
    </section>
  )
}

function History({ signals }: { signals: Signal[] }) {
  return (
    <section className="card">
      <h2 className="card-title">Signal history</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Signal</th>
              <th>Score</th>
              <th className="num">Conf.</th>
              <th className="num">Price</th>
              <th className="num">7d</th>
              <th className="num">30d</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => (
              <tr key={s.id}>
                <td>{shortDate(s.as_of_date)}</td>
                <td>
                  <SignalBadge signal={s.signal} />
                </td>
                <td>{s.score}</td>
                <td className="num">{rate(s.confidence)}</td>
                <td className="num">{price(s.price_at_signal)}</td>
                <td className="num">{pct(s.return_7d)}</td>
                <td className="num">{pct(s.return_30d)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Detail({ data }: { data: TickerDetailData }) {
  const latest = data.signals[0]
  return (
    <div className="stack">
      <div className="page-head">
        <Link to="/" className="back-link">
          ← Overview
        </Link>
        <h1>
          {data.ticker} {data.name && <span className="muted">· {data.name}</span>}
        </h1>
      </div>

      <section className="card">
        <h2 className="card-title">Price, last 90 days</h2>
        <PriceChart prices={data.prices} signals={data.signals} />
      </section>

      {latest && <LatestSignal signal={latest} />}
      {data.signals.length > 0 && <History signals={data.signals} />}

      <section className="card">
        <h2 className="card-title">Recent news</h2>
        {data.news.length === 0 ? (
          <p className="muted">No news stored yet.</p>
        ) : (
          <ul className="news-list">
            {data.news.map((item) => (
              <li key={item.id}>
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.title}
                </a>
                <div className="muted small">
                  {item.source} · {relativeTime(item.published_at)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

export function TickerDetail() {
  const { ticker = '' } = useParams()
  const state = useApi<TickerDetailData>(`/tickers/${encodeURIComponent(ticker)}`)
  return <AsyncState state={state}>{(data) => <Detail data={data} />}</AsyncState>
}
