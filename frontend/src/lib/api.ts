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
  benchmark_return_7d: number | null
  benchmark_return_30d: number | null
}

/** A latest signal plus the same ticker's previous one, for the day-over-day change. */
export interface LatestSignal extends Signal {
  previous_signal: SignalType | null
  previous_score: number | null
  previous_as_of_date: string | null
}

export interface LatestSignals {
  as_of_date: string | null
  signals: LatestSignal[]
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
  /** How often an "always bullish" guess would have hit. */
  base_rate_up: number | null
  relative_directional: number
  relative_hits: number
  /** Hit rate against the benchmark: bullish beat SPY, bearish lagged it. */
  relative_hit_rate: number | null
  avg_benchmark_return: number | null
  by_signal: Record<
    SignalType,
    { count: number; avg_return: number | null; avg_excess_return: number | null }
  >
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
const WAKE_DEADLINE_MS = 90_000
const REQUEST_TIMEOUT_MS = 25_000
const WAKING_STATUSES = new Set([502, 503, 504])

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

interface RequestOptions {
  signal?: AbortSignal
  onWaking?: () => void
}

async function fetchWithTimeout(url: string, init: RequestInit, signal?: AbortSignal) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  const onAbort = () => controller.abort()
  signal?.addEventListener('abort', onAbort)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onAbort)
  }
}

/** The API's own error message (FastAPI's `detail`), if the body has one. */
async function errorDetail(response: Response): Promise<string | null> {
  try {
    const body = (await response.clone().json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) return 'Please check your input and try again.'
  } catch {
    // Not JSON: e.g. the hosting platform's own "service waking up" page.
  }
  return null
}

async function request<T>(path: string, init: RequestInit, options: RequestOptions): Promise<T> {
  const { signal, onWaking } = options
  const deadline = Date.now() + WAKE_DEADLINE_MS
  for (let attempt = 1; ; attempt++) {
    try {
      const response = await fetchWithTimeout(`${API_URL}${path}`, init, signal)
      if (response.ok) return (await response.json()) as T
      const detail = await errorDetail(response)
      // A JSON error came from our API itself, so the server is awake: don't retry.
      if (detail !== null || !WAKING_STATUSES.has(response.status) || Date.now() > deadline) {
        const hint = response.status >= 500 ? ' The server hit an error; see the API logs.' : ''
        throw new ApiError(response.status, detail ?? `Request failed (${response.status}).${hint}`)
      }
    } catch (error) {
      if (signal?.aborted || error instanceof ApiError) throw error
      if (Date.now() > deadline) {
        // A CORS rejection looks exactly like a network error to the browser, so name both.
        throw new Error(
          `Could not reach the API at ${API_URL}. If this keeps happening, check that ` +
            'VITE_API_URL points to the API and that CORS_ORIGINS on the API includes ' +
            `${window.location.origin}.`,
        )
      }
    }
    // Network error, timeout or gateway error: the server is most likely still waking up.
    onWaking?.()
    await sleep(Math.min(2_000 * attempt, 8_000))
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  }
}

export function apiGet<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return request<T>(path, { headers: { Accept: 'application/json' } }, options)
}

export function apiPost<T>(path: string, body: unknown, options: RequestOptions = {}): Promise<T> {
  return request<T>(
    path,
    {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    options,
  )
}

// --- Ask the news -----------------------------------------------------------

export interface AskSource {
  id: number
  kind: 'news' | 'signal'
  title: string
  url: string
  source: string
  published_at: string
  ticker: string
  similarity: number
}

export interface AskResponse {
  answer: string
  sources: AskSource[]
  sufficient_evidence: boolean
  retrieved_count: number
  tokens: { embedding: number; input: number; output: number }
  est_cost_usd: number
}
