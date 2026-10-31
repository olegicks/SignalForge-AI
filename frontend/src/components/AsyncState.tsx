import type { ReactNode } from 'react'
import type { ApiState } from '../lib/useApi'

interface Props<T> {
  state: ApiState<T>
  children: (data: T) => ReactNode
}

/** Renders loading, cold-start, error or the data, so pages only deal with the happy path. */
export function AsyncState<T>({ state, children }: Props<T>) {
  if (state.loading && state.waking) {
    return (
      <div className="state-box" role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <div>
          <strong>Waking up the server…</strong>
          <p className="muted">
            The API runs on a free host that sleeps when idle. The first request can take up to a
            minute. This page will load by itself.
          </p>
        </div>
      </div>
    )
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
