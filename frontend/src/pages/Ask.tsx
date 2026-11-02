import { type FormEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { WakingNotice } from '../components/AsyncState'
import { type AskResponse, type AskSource, apiPost, type LatestSignals } from '../lib/api'
import { relativeTime, usd } from '../lib/format'
import { useApi } from '../lib/useApi'

const MAX_CHARS = 300
const EXAMPLES = [
  'What are the main risks mentioned for NVDA?',
  'Which companies have earnings-related news right now?',
  'Why is the latest signal for MSFT what it is?',
]

type Status = 'idle' | 'loading' | 'done' | 'error'

/** Turns "[2]" citations in the answer into links to the matching source below. */
function AnswerText({ text, sourceIds }: { text: string; sourceIds: Set<number> }) {
  const parts: ReactNode[] = text.split(/(\[\d+\])/g).map((part, i) => {
    const match = /^\[(\d+)\]$/.exec(part)
    if (!match) return part
    const id = Number(match[1])
    return sourceIds.has(id) ? (
      <a key={i} href={`#source-${id}`} className="cite">
        {id}
      </a>
    ) : null
  })
  return <p className="answer-text">{parts}</p>
}

function SourceItem({ source }: { source: AskSource }) {
  const percent = Math.round(source.similarity * 100)
  const title =
    source.kind === 'signal' ? (
      <Link to={source.url}>{source.title}</Link>
    ) : (
      <a href={source.url} target="_blank" rel="noreferrer">
        {source.title}
      </a>
    )
  return (
    <li id={`source-${source.id}`} className="source-item">
      <span className="source-number">{source.id}</span>
      <div className="source-body">
        {title}
        <div className="muted small">
          {source.kind === 'signal' ? 'SignalForge signal' : source.source} · {source.ticker} ·{' '}
          {relativeTime(source.published_at)}
        </div>
      </div>
      <span className="similarity" title="Cosine similarity between the question and this item">
        <span className="similarity-track" aria-hidden="true">
          <span className="similarity-fill" style={{ width: `${Math.max(percent, 0)}%` }} />
        </span>
        {percent}% match
      </span>
    </li>
  )
}

function AnswerCard({ result }: { result: AskResponse }) {
  if (!result.sufficient_evidence) {
    return (
      <section className="card insufficient" role="status">
        <h2 className="card-title">
          <span aria-hidden="true">∅</span> Not enough data in the news database
        </h2>
        <p>{result.answer}</p>
        <p className="muted small">
          {result.retrieved_count === 0
            ? 'No stored news or signals were close enough to the question.'
            : `${result.retrieved_count} items were retrieved, but they don't answer the question.`}{' '}
          The model is not allowed to guess.
        </p>
      </section>
    )
  }
  const ids = new Set(result.sources.map((s) => s.id))
  return (
    <section className="card">
      <h2 className="card-title">Answer</h2>
      <AnswerText text={result.answer} sourceIds={ids} />
      <h3 className="sources-title">Sources</h3>
      <ol className="source-list">
        {result.sources.map((source) => (
          <SourceItem key={source.id} source={source} />
        ))}
      </ol>
      <p className="muted small">
        Answered only from {result.retrieved_count} retrieved items ·{' '}
        {result.tokens.embedding + result.tokens.input + result.tokens.output} tokens · ≈
        {usd(result.est_cost_usd)}. Research only, not investment advice.
      </p>
    </section>
  )
}

export function Ask() {
  const [question, setQuestion] = useState('')
  const [ticker, setTicker] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [waking, setWaking] = useState(false)
  const [result, setResult] = useState<AskResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  // Ticker options from the latest signals; this also starts waking the API early.
  const latest = useApi<LatestSignals>('/signals/latest?limit=100&sort=ticker')
  const tickers = latest.data?.signals.map((s) => s.ticker) ?? []

  useEffect(() => () => controller.current?.abort(), [])

  const trimmed = question.trim()
  const canSubmit = trimmed.length >= 3 && trimmed.length <= MAX_CHARS && status !== 'loading'

  async function ask(text: string) {
    controller.current?.abort()
    const current = new AbortController()
    controller.current = current
    setStatus('loading')
    setWaking(false)
    setError(null)
    setResult(null)
    const slowTimer = setTimeout(() => setWaking(true), 2_500)
    try {
      const response = await apiPost<AskResponse>(
        '/ask',
        { question: text, ticker: ticker || null },
        { signal: current.signal, onWaking: () => setWaking(true) },
      )
      setResult(response)
      setStatus('done')
    } catch (err) {
      if (current.signal.aborted) return
      setError(err instanceof Error ? err.message : 'Something went wrong')
      setStatus('error')
    } finally {
      clearTimeout(slowTimer)
      setWaking(false)
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (canSubmit) void ask(trimmed)
  }

  function askExample(text: string) {
    setQuestion(text)
    void ask(text)
  }

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Ask the news</h1>
        <p className="muted">
          Ask about the stocks we track. Answers come only from the news and signals stored in our
          database, with numbered sources you can check. If the data isn't there, it says so.
        </p>
      </div>

      <form className="card ask-form" onSubmit={onSubmit}>
        <label htmlFor="ask-question" className="card-title">
          Your question
        </label>
        <textarea
          id="ask-question"
          className="ask-input"
          rows={3}
          maxLength={MAX_CHARS}
          placeholder="e.g. What is driving the news around ASML?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            // Ctrl/Cmd+Enter submits; plain Enter still adds a new line.
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && canSubmit) {
              e.preventDefault()
              void ask(trimmed)
            }
          }}
        />
        <div className="ask-controls">
          <label className="ask-ticker">
            <span className="muted small">Ticker</span>
            <select value={ticker} onChange={(e) => setTicker(e.target.value)}>
              <option value="">All tickers</option>
              {tickers.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <span className="muted small char-count">
            {question.length}/{MAX_CHARS}
          </span>
          <button type="submit" className="button button-primary" disabled={!canSubmit}>
            {status === 'loading' ? 'Thinking…' : 'Ask'}
          </button>
        </div>
        <div className="examples">
          <span className="muted small">Try:</span>
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="filter-chip example-chip"
              onClick={() => askExample(example)}
              disabled={status === 'loading'}
            >
              {example}
            </button>
          ))}
        </div>
      </form>

      {status === 'loading' &&
        (waking ? (
          <WakingNotice action="Your question will be answered as soon as it is up." />
        ) : (
          <div className="state-box" role="status">
            <span className="spinner" aria-hidden="true" />
            <span className="muted">Searching the news and writing an answer…</span>
          </div>
        ))}
      {status === 'error' && (
        <div className="state-box state-error" role="alert">
          <div>
            <strong>Could not get an answer.</strong>
            <p className="muted">{error}</p>
          </div>
          <button type="button" className="button" onClick={() => void ask(trimmed)}>
            Try again
          </button>
        </div>
      )}
      {status === 'done' && result && <AnswerCard result={result} />}
    </div>
  )
}
