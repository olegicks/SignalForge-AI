import { useCallback, useEffect, useState } from 'react'
import { apiGet } from './api'

// Show the "waking up" message if a request is still pending after this long.
const SLOW_REQUEST_MS = 2_500

export interface ApiState<T> {
  data: T | null
  error: string | null
  loading: boolean
  waking: boolean
  reload: () => void
}

export function useApi<T>(path: string): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [waking, setWaking] = useState(false)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setWaking(false)
    const slowTimer = setTimeout(() => setWaking(true), SLOW_REQUEST_MS)

    apiGet<T>(path, { signal: controller.signal, onWaking: () => setWaking(true) })
      .then((result) => setData(result))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : 'Something went wrong')
      })
      .finally(() => {
        clearTimeout(slowTimer)
        if (!controller.signal.aborted) {
          setLoading(false)
          setWaking(false)
        }
      })

    return () => {
      clearTimeout(slowTimer)
      controller.abort()
    }
  }, [path, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data, error, loading, waking, reload }
}
