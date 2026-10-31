import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { PricePoint, Signal, SignalType } from '../lib/api'
import { price, shortDate } from '../lib/format'

interface ChartPoint {
  date: string
  close: number
  bullish?: number
  bearish?: number
  neutral?: number
  signal?: Signal
}

const SIGNAL_TYPES: SignalType[] = ['bullish', 'bearish', 'neutral']

/** Put each signal on the last trading day on or before its as-of date. */
function buildPoints(prices: PricePoint[], signals: Signal[]): ChartPoint[] {
  const points: ChartPoint[] = prices.map((p) => ({ date: p.date, close: p.close }))
  for (const signal of signals) {
    let index = -1
    for (let i = points.length - 1; i >= 0; i--) {
      if (points[i].date <= signal.as_of_date) {
        index = i
        break
      }
    }
    if (index === -1) continue
    points[index][signal.signal] = signal.price_at_signal
    points[index].signal = signal
  }
  return points
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: ChartPoint }[] }) {
  if (!active || !payload?.length) return null
  const point = payload[0].payload
  return (
    <div className="chart-tooltip">
      <div className="muted">{shortDate(point.date)}</div>
      <div>
        Close <strong>{price(point.close)}</strong>
      </div>
      {point.signal && (
        <div>
          Signal <strong>{point.signal.signal}</strong> · score {point.signal.score}
        </div>
      )}
    </div>
  )
}

function Marker(props: { cx?: number; cy?: number; type: SignalType }) {
  const { cx, cy, type } = props
  if (cx === undefined || cy === undefined) return null
  return <circle cx={cx} cy={cy} r={6} className={`marker marker-${type}`} />
}

export function PriceChart({ prices, signals }: { prices: PricePoint[]; signals: Signal[] }) {
  if (prices.length < 2) {
    return <p className="muted">Not enough price history yet.</p>
  }
  const points = buildPoints(prices, signals)
  const shownTypes = SIGNAL_TYPES.filter((t) => points.some((p) => p[t] !== undefined))

  return (
    <figure className="chart">
      {shownTypes.length > 0 && (
        <figcaption className="legend">
          <span className="legend-item">
            <span className="legend-line" aria-hidden="true" /> Close
          </span>
          {shownTypes.map((t) => (
            <span key={t} className="legend-item">
              <span className={`legend-dot marker-${t}`} aria-hidden="true" /> {t} signal
            </span>
          ))}
        </figcaption>
      )}
      <div className="chart-body">
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} className="chart-grid" />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              minTickGap={32}
              tickLine={false}
              axisLine={false}
              className="chart-axis"
            />
            <YAxis
              domain={['auto', 'auto']}
              tickFormatter={(v: number) => price(v)}
              width={64}
              tickLine={false}
              axisLine={false}
              className="chart-axis"
            />
            <Tooltip content={<ChartTooltip />} cursor={{ className: 'chart-cursor' }} />
            <Line
              type="monotone"
              dataKey="close"
              dot={false}
              strokeWidth={2}
              className="price-line"
              isAnimationActive={false}
            />
            {SIGNAL_TYPES.map((t) => (
              <Scatter
                key={t}
                dataKey={t}
                isAnimationActive={false}
                shape={(props: { cx?: number; cy?: number }) => <Marker {...props} type={t} />}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
