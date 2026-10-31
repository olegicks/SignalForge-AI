import type { RiskLevel, Run, SignalType } from '../lib/api'

const SIGNAL_ICON: Record<SignalType, string> = { bullish: '▲', bearish: '▼', neutral: '●' }

export function SignalBadge({ signal }: { signal: SignalType }) {
  return (
    <span className={`badge badge-${signal}`}>
      <span aria-hidden="true">{SIGNAL_ICON[signal]}</span> {signal}
    </span>
  )
}

export function RiskTag({ risk }: { risk: RiskLevel }) {
  return <span className={`tag tag-risk-${risk}`}>{risk}</span>
}

const STATUS_ICON: Record<Run['status'], string> = {
  success: '✓',
  partial: '!',
  failed: '✕',
  running: '…',
}

export function StatusBadge({ status }: { status: Run['status'] }) {
  return (
    <span className={`badge status-${status}`}>
      <span aria-hidden="true">{STATUS_ICON[status]}</span> {status}
    </span>
  )
}

export function HitMark({ hit }: { hit: boolean | null }) {
  if (hit === null) return <span className="muted">—</span>
  return hit ? (
    <span className="hit" title="Hit">
      ✓<span className="sr-only">hit</span>
    </span>
  ) : (
    <span className="miss" title="Miss">
      ✕<span className="sr-only">miss</span>
    </span>
  )
}

export function ScoreMeter({ score }: { score: number }) {
  return (
    <span className="score" title={`Score ${score} of 10`}>
      <span className="score-value">{score}</span>
      <span className="score-track" aria-hidden="true">
        <span className="score-fill" style={{ width: `${score * 10}%` }} />
      </span>
    </span>
  )
}
