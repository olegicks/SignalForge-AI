// Typed client for the SignalForge API, with cold-start handling for Render's free tier.

export const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export type SignalType = 'bullish' | 'bearish' | 'neutral'
export type RiskLevel = 'low' | 'medium' | 'high'

export interface Run {
  id: number
  started_at: string
  finished_at: string | null
  status: 'running' | 'success' | 'partial' | 'failed'
  tickers_processed: number
  tickers_failed: number
  input_tokens: number
  output_tokens: number
  est_cost_usd: number
  model: string | null
  error_summary: string | null
}

export interface Signal {
  id: number
  run_id: number
  ticker: string
  as_of_date: string
  signal: SignalType
  score: number
  risk: RiskLevel
  confidence: number
  reasoning: string
  key_factors: string[]
  sources: string[]
  price_at_signal: number
  model: string
  created_at: string
  price_7d: number | null
  return_7d: number | null
  price_30d: number | null
  return_30d: number | null
}

export interface LatestSignals {
  as_of_date: string | null
  signals: Signal[]
}

export interface NewsItem {
  id: number
  ticker: string
  title: string
  summary: string | null
  url: string
  source: string
  published_at: string
}

export interface PricePoint {
  date: string
  close: number
}

export interface TickerDetail {
  ticker: string
  name: string | null
  signals: Signal[]
  news: NewsItem[]
  prices: PricePoint[]
}

export interface HorizonStats {
  horizon_days: number
  evaluated: number
  directional: number
  hits: number
  hit_rate: number | null
  by_signal: Record<SignalType, { count: number; avg_return: number | null }>
  by_confidence: { bucket: string; count: number; hits: number; hit_rate: number | null }[]
}

export interface TrackRecord {
  total_signals: number
  horizons: HorizonStats[]
  recent_evaluated: Signal[]
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// A sleeping Render service can take about a minute to boot, so keep retrying for a while.
const WAKE_DEADLINE_MS = 120_000
const REQUEST_TIMEOUT_MS = 25_000
const WAKING_STATUSES = new Set([502, 503, 504])

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function fetchWithTimeout(url: string, signal?: AbortSignal): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  const onAbort = () => controller.abort()
  signal?.addEventListener('abort', onAbort)
  try {
    return await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } })
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onAbort)
  }
}

export async function apiGet<T>(
  path: string,
  options: { signal?: AbortSignal; onWaking?: () => void } = {},
): Promise<T> {
  const { signal, onWaking } = options
  const deadline = Date.now() + WAKE_DEADLINE_MS
  for (let attempt = 1; ; attempt++) {
    try {
      const response = await fetchWithTimeout(`${API_URL}${path}`, signal)
      if (response.ok) return (await response.json()) as T
      if (!WAKING_STATUSES.has(response.status) || Date.now() > deadline) {
        throw new ApiError(response.status, `Request failed (${response.status})`)
      }
    } catch (error) {
      if (signal?.aborted || error instanceof ApiError) throw error
      if (Date.now() > deadline) throw new Error('The server did not respond. Please try again.')
    }
    // Network error, timeout or gateway error: the server is most likely still waking up.
    onWaking?.()
    await sleep(Math.min(2_000 * attempt, 8_000))
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  }
}
