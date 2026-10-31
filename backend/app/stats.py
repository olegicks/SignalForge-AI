"""Track-record maths, kept free of the database so it is easy to test.

A bullish signal hits when its return is above 0, a bearish one when it is below 0.
Neutral signals have no direction, so they are left out of hit rates (but their average
return is still reported).
"""

from dataclasses import dataclass

from app.schemas import ConfidenceBucketStats, HorizonStats, SignalTypeStats

SIGNAL_TYPES = ("bullish", "bearish", "neutral")
# (label, lower bound inclusive, upper bound exclusive); the last bucket includes 1.0.
CONFIDENCE_BUCKETS = (("0.0-0.4", 0.0, 0.4), ("0.4-0.7", 0.4, 0.7), ("0.7-1.0", 0.7, 1.01))


@dataclass(frozen=True)
class Outcome:
    signal: str
    confidence: float
    ret: float


def is_hit(signal: str, ret: float) -> bool | None:
    if signal == "bullish":
        return ret > 0
    if signal == "bearish":
        return ret < 0
    return None


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def horizon_stats(horizon_days: int, outcomes: list[Outcome]) -> HorizonStats:
    directional = [o for o in outcomes if o.signal != "neutral"]
    hits = sum(1 for o in directional if is_hit(o.signal, o.ret))

    by_signal: dict[str, SignalTypeStats] = {}
    for signal_type in SIGNAL_TYPES:
        returns = [o.ret for o in outcomes if o.signal == signal_type]
        by_signal[signal_type] = SignalTypeStats(
            count=len(returns),
            avg_return=round(sum(returns) / len(returns), 6) if returns else None,
        )

    by_confidence: list[ConfidenceBucketStats] = []
    for label, low, high in CONFIDENCE_BUCKETS:
        bucket = [o for o in directional if low <= o.confidence < high]
        bucket_hits = sum(1 for o in bucket if is_hit(o.signal, o.ret))
        by_confidence.append(
            ConfidenceBucketStats(
                bucket=label,
                count=len(bucket),
                hits=bucket_hits,
                hit_rate=_rate(bucket_hits, len(bucket)),
            )
        )

    return HorizonStats(
        horizon_days=horizon_days,
        evaluated=len(outcomes),
        directional=len(directional),
        hits=hits,
        hit_rate=_rate(hits, len(directional)),
        by_signal=by_signal,
        by_confidence=by_confidence,
    )
