import type { ReactNode } from 'react'
import type { ApiState } from '../lib/useApi'

interface Props<T> {
  state: ApiState<T>
  children: (data: T) => ReactNode
}

/** The cold-start message, shared by every page that talks to the API. */
export function WakingNotice({ action = 'This page will load by itself.' }: { action?: string }) {
  return (
    <div className="state-box" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <div>
        <strong>Waking up the server…</strong>
        <p className="muted">
          The API runs on a free host that sleeps when idle. The first request can take up to a
          minute. {action}
        </p>
      </div>
    </div>
  )
}

/** Renders loading, cold-start, error or the data, so pages only deal with the happy path. */
export function AsyncState<T>({ state, children }: Props<T>) {
  if (state.loading && state.waking) {
    return <WakingNotice />
  }
  if (state.loading) {
    return (
      <div className="state-box" role="status">
        <span className="spinner" aria-hidden="true" />
        <span className="muted">Loading…</span>
      </div>
    )
  }
  if (state.error || state.data === null) {
    return (
      <div className="state-box state-error" role="alert">
        <div>
          <strong>Could not load data.</strong>
          <p className="muted">{state.error ?? 'No data returned.'}</p>
        </div>
        <button type="button" className="button" onClick={state.reload}>
          Try again
        </button>
      </div>
    )
  }
  return <>{children(state.data)}</>
}
