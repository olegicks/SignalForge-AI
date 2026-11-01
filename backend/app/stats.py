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
    benchmark: float | None = None

    @property
    def excess(self) -> float | None:
        """Return over the benchmark (SPY) for the same window."""
        return None if self.benchmark is None else self.ret - self.benchmark


def is_hit(signal: str, ret: float) -> bool | None:
    if signal == "bullish":
        return ret > 0
    if signal == "bearish":
        return ret < 0
    return None


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def horizon_stats(horizon_days: int, outcomes: list[Outcome]) -> HorizonStats:
    directional = [o for o in outcomes if o.signal != "neutral"]
    hits = sum(1 for o in directional if is_hit(o.signal, o.ret))

    # Relative hits: did a bullish call beat the market, or a bearish call lag it?
    with_benchmark = [o for o in directional if o.excess is not None]
    relative_hits = sum(1 for o in with_benchmark if is_hit(o.signal, o.excess or 0.0))

    by_signal: dict[str, SignalTypeStats] = {}
    for signal_type in SIGNAL_TYPES:
        of_type = [o for o in outcomes if o.signal == signal_type]
        by_signal[signal_type] = SignalTypeStats(
            count=len(of_type),
            avg_return=_mean([o.ret for o in of_type]),
            avg_excess_return=_mean([o.excess for o in of_type if o.excess is not None]),
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
        # A naive "always bullish" guess would hit this often; the model should beat it.
        base_rate_up=_rate(sum(1 for o in outcomes if o.ret > 0), len(outcomes)),
        relative_directional=len(with_benchmark),
        relative_hits=relative_hits,
        relative_hit_rate=_rate(relative_hits, len(with_benchmark)),
        avg_benchmark_return=_mean([o.benchmark for o in outcomes if o.benchmark is not None]),
        by_signal=by_signal,
        by_confidence=by_confidence,
    )
