export function pct(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined) return '—'
  const value = fraction * 100
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  return `${sign}${Math.abs(value).toFixed(digits)}%`
}

export function rate(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined) return '—'
  return `${Math.round(fraction * 100)}%`
}

export function price(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function usd(value: number): string {
  return value < 0.01 && value > 0 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`
}

export function dateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export function shortDate(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}

export function relativeTime(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (minutes < 60) return `${Math.max(minutes, 1)} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} days ago`
}

/** Hit when bullish and up, or bearish and down. Neutral has no direction. */
export function isHit(signal: string, ret: number | null): boolean | null {
  if (ret === null || signal === 'neutral') return null
  return signal === 'bullish' ? ret > 0 : ret < 0
}
